"""Durable, account-bound Canvas homework queues; receipt-based recovery only."""
from __future__ import annotations
import asyncio
import json
import time
import uuid
from . import browser_control, coursework, coursework_autopilot as pilot, operator_store as store, operator_workflows as workflows

KIND = 'coursework_queue'
_ACTIVE: dict[str, asyncio.Task] = {}
_LOCK = asyncio.Lock()
SAFE_RETRY = {'queued', 'blocked', 'failed', 'unreachable', 'auth_required', 'attempted'}


def create_queue(assignments, *, account_id, authorize_submission=False, mode='autopilot', browser=None, max_attempts=2, assignment_timeout_seconds=300):
    if mode not in {'autopilot', 'tutor'} or (mode == 'autopilot' and authorize_submission is not True):
        raise ValueError('Explicit assignment-scoped submission authorization is required for autopilot.')
    if not str(account_id or '').strip():
        raise ValueError('Select the Canvas account ID authorized for this queue.')
    # None: the browser chosen in Settings, the same one Canvas reads use.
    # Onyx is not a Playwright session, so queues run in Nova's Playwright browser.
    if browser is not None:
        browser = browser_control.normalize_browser(browser)
        if browser in (None, 'onyx'):
            raise ValueError('Choose a browser Nova can run a queue in: ' + ', '.join(
                k for k in browser_control.BROWSERS if k != 'onyx') + '.')
    if not 1 <= len(assignments) <= 50 or not 1 <= max_attempts <= 3 or not 30 <= assignment_timeout_seconds <= 1800:
        raise ValueError('Choose 1-50 assignments, 1-3 attempts, and a 30-1800 second assignment timeout.')
    items, urls = [], set()
    for assignment in assignments:
        _, _, aid, url = coursework.assignment_location(assignment.get('url', ''))
        if url in urls:
            raise ValueError('Duplicate assignments are not allowed in a queue.')
        urls.add(url)
        items.append({'id': uuid.uuid4().hex, 'assignment': {'id': aid, 'url': url,
                      'title': str(assignment.get('title') or 'Assignment'), 'course_name': str(assignment.get('course_name') or '')},
                      'state': 'queued', 'attempts': 0, 'result': None})
    return store.create(KIND, state='queued', items=items, account_id=str(account_id), mode=mode,
                        browser=browser, authorized=authorize_submission is True, expires_at=time.time()+86400,
                        max_attempts=max_attempts, assignment_timeout_seconds=assignment_timeout_seconds, lease_until=0)


def status(queue_id):
    job = store.get(KIND, queue_id)
    if not job:
        raise ValueError('Queue not found.')
    return job


def list_queues():
    return store.listing(KIND)


def _save(job):
    with store.transaction() as conn:
        current = store.get(KIND, job['id'], conn)
        if current and current['state'] == 'cancelled':
            job['state'] = 'cancelled'
        job['updated_at'] = time.time()
        store.put(KIND, job['id'], job, conn)
    return job


def recover_on_boot():
    """No queue can be running when the backend has just started. Items that
    were mid-assignment become 'unknown' (check the receipt), never replayed."""
    recovered = 0
    with store.transaction() as conn:
        for (data,) in conn.execute('SELECT data FROM records WHERE kind=?', (KIND,)).fetchall():
            job = json.loads(data)
            if job.get('state') not in ('running', 'queued') and not any(i.get('state') == 'executing' for i in job.get('items', [])):
                continue
            for item in job.get('items', []):
                if item.get('state') == 'executing':
                    item['state'] = 'unknown'
                    item['result'] = {'status': 'unknown', 'reason': 'Nova restarted mid-assignment; check the receipt.'}
            if job.get('state') == 'running':
                job['state'] = _finish_state(job) if all(i['state'] not in SAFE_RETRY for i in job['items']) else 'waiting_for_user'
            job['lease_until'] = 0
            store.put(KIND, job['id'], job, conn)
            recovered += 1
    return recovered


def cancel_queue(queue_id):
    with store.transaction() as conn:
        job = store.get(KIND, queue_id, conn)
        if not job:
            raise ValueError('Queue not found.')
        job['state'] = 'cancelled'
        store.put(KIND, queue_id, job, conn)
    task = _ACTIVE.get(queue_id)
    if task:
        task.cancel()
    return job


async def _check_authorization(job, item):
    workflows.require_running()
    if status(job['id'])['state'] == 'cancelled':
        raise ValueError('Queue cancelled.')
    if job['expires_at'] <= time.time() or (job['mode'] == 'autopilot' and not job['authorized']):
        raise ValueError('Queue authorization expired; create a newly authorized queue.')
    profile = await coursework.read_json(item['assignment']['url'], 'users/self/profile')
    if str(profile.get('id')) != job['account_id']:
        raise ValueError('Canvas account differs from this queue authorization.')


def _finish_state(job):
    states = [item['state'] for item in job['items']]
    return 'completed' if all(s == 'completed' for s in states) else ('guidance_ready' if all(s == 'guidance_ready' for s in states) else 'waiting_for_user')


async def run_queue(queue_id, *, resume=False):
    """Run once, or explicitly resume cancellation; unknown items are never replayed."""
    async with _LOCK:
        # Checked before the transaction: the stop flag lives in the same store,
        # and a second connection inside BEGIN IMMEDIATE would wait on this one.
        workflows.require_running()
        with store.transaction() as conn:
            job = store.get(KIND, queue_id, conn)
            if not job:
                raise ValueError('Queue not found.')
            if job['lease_until'] > time.time() or (job['state'] == 'cancelled' and not resume):
                return job
            job['state'] = 'running'
            job['lease_until'] = time.time() + len(job['items']) * (job['assignment_timeout_seconds'] + 65)
            store.put(KIND, queue_id, job, conn)
        try:
            for item in job['items']:
                if item['state'] == 'executing':
                    item['state'] = 'unknown'
                    item['result'] = {'status': 'unknown', 'reason': 'Execution interrupted; verify a portal receipt before continuing.'}
                if workflows.stopped() or status(queue_id)['state'] == 'cancelled':
                    job['state'] = 'cancelled'
                    break
                if item['state'] not in SAFE_RETRY or item['attempts'] >= job['max_attempts']:
                    continue
                item['attempts'] += 1
                try:
                    async with asyncio.timeout(35):
                        await _check_authorization(job, item)
                except Exception as exc:
                    item['state'] = 'auth_required'
                    item['result'] = {'status': 'auth_required', 'reason': str(exc)}
                    _save(job)
                    continue
                item['state'] = 'executing'
                _save(job)
                task = asyncio.create_task(pilot.run_autopilot_assignment(item['assignment'], browser_channel=job['browser'], mode=job['mode'],
                    submission_guard=lambda: _check_authorization(job, item)))
                _ACTIVE[queue_id] = task
                try:
                    async with asyncio.timeout(job['assignment_timeout_seconds']):
                        result = await task
                    item['result'] = result
                    item['state'] = result.get('status', 'unknown')
                except (asyncio.CancelledError, TimeoutError):
                    item['state'] = 'unknown'
                    item['result'] = {'status': 'unknown', 'reason': 'Interrupted or timed out; reconcile portal receipt.'}
                    if asyncio.current_task().cancelling():
                        raise
                except Exception as exc:
                    item['state'] = 'unknown'
                    item['result'] = {'status': 'unknown', 'reason': str(exc)}
                finally:
                    _ACTIVE.pop(queue_id, None)
                    _save(job)
            if job['state'] != 'cancelled':
                job['state'] = _finish_state(job)
        finally:
            job['lease_until'] = 0
            _save(job)
        return job


async def reconcile_item(queue_id, item_id):
    """Read the authorized Canvas account's receipt. Never accepts a client outcome."""
    async with _LOCK:
        job = status(queue_id)
        if job['lease_until'] > time.time():
            raise ValueError('Queue execution is still leased; wait for it to finish.')
        item = next((i for i in job['items'] if i['id'] == item_id), None)
        if not item or item['state'] not in {'unknown', 'executing'}:
            raise ValueError('Select an uncertain queue item.')
        async with pilot._ASSIGNMENT_LOCK:
            await _check_authorization(job, item)
            url = item['assignment']['url']
            _, course, aid, _ = coursework.assignment_location(url)
            row = await coursework.read_json(url, f'courses/{course}/assignments/{aid}?include[]=submission')
        receipt = row.get('submission') or {}
        verified = (str(row.get('id')) == aid and str(row.get('course_id')) == course
                    and str(receipt.get('assignment_id')) == aid and str(receipt.get('user_id')) == job['account_id']
                    and receipt.get('workflow_state') in {'submitted', 'graded'} and bool(receipt.get('submitted_at')))
        item['reconciliation'] = {'checked_at': time.time(), 'verified': verified,
                                  'source': 'Canvas authenticated assignment submission',
                                  'submitted_at': receipt.get('submitted_at') if verified else None}
        if verified:
            item['state'] = 'completed'
            item['result'] = {'status': 'completed', 'reason': 'Matching Canvas submission receipt observed; correctness is not inferred.'}
        else:
            item['state'] = 'unknown'
        job['state'] = _finish_state(job)
        return _save(job)
