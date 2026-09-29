"""Canvas work packets, persisted drafts and verified browser submissions.

Reading uses Canvas's JSON endpoints with the signed-in browser cookies when
personal tokens are unavailable. Writing happens through the visible form.
An assignment-scoped user grant is mandatory and is never a model argument.
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, urljoin, parse_qs

import httpx

from . import browser_control, canvas, desktop, operator_store as store, operator_workflows as workflows, providers


class CourseworkError(ValueError):
    pass


def assignment_location(url):
    parsed = urlsplit(url)
    match = re.fullmatch(r'/courses/(\d+)/assignments/(\d+)/?', parsed.path)
    if not match and parsed.path == '/calendar':
        course = re.fullmatch(r'course_(\d+)', parse_qs(parsed.query).get('include_contexts', [''])[0])
        assignment_id = re.fullmatch(r'assignment_(\d+)', parsed.fragment)
        if course and assignment_id:
            parsed = parsed._replace(path=f'/courses/{course[1]}/assignments/{assignment_id[1]}', query='', fragment='')
            match = re.fullmatch(r'/courses/(\d+)/assignments/(\d+)', parsed.path)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or not match:
        raise CourseworkError('Use the HTTPS Canvas assignment URL: /courses/COURSE/assignments/ASSIGNMENT.')
    origin = f'https://{parsed.netloc}'
    return origin, match[1], match[2], origin + parsed.path.rstrip('/')


class _Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text, self.links = [], []
    def handle_data(self, data):
        self.text.append(data)
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            values = dict(attrs)
            href = values.get('href')
            if href and ('$CANVAS' in href or '/file_ref/' in href) and values.get('data-api-endpoint'):
                href = values['data-api-endpoint'].replace('/api/v1/', '/')
            if href:
                self.links.append(href)


def plain(value):
    doc = _Document()
    doc.feed(value or '')
    return ' '.join(' '.join(doc.text).split())


async def read_json(url, path):
    origin, _, _, _ = assignment_location(url)
    endpoint = origin + '/api/v1/' + path.lstrip('/')
    # Use the same browser identity for reads and visible writes. A separately
    # configured API token may belong to a different Canvas account.
    tab = await browser_control.page()
    response = await tab.context.request.get(endpoint, max_redirects=0, timeout=30000)
    if response.status != 200 or 'json' not in response.headers.get('content-type', ''):
        raise CourseworkError('Sign into Canvas in Nova’s browser first. The calendar feed cannot read or submit coursework.')
    return await response.json()


async def assignment(url):
    origin, course, aid, normalized = assignment_location(url)
    row = await read_json(normalized, f'courses/{course}/assignments/{aid}?include[]=submission')
    if str(row.get('id')) != aid or str(row.get('course_id')) != course:
        raise CourseworkError('Canvas returned a different assignment; stopped.')
    doc = _Document()
    doc.feed(row.get('description') or '')
    profile = await read_json(normalized, 'users/self/profile')
    essay = bool(re.search(r'\b(essay|paper|composition|writing assignment|writing assignments|comparative analysis|literary analysis|critical analysis|research report|reflection)\b', (row.get('name') or '') + ' ' + plain(row.get('description')), re.I))
    from . import skills
    writing = next((s.body for s in skills.all_skills() if s.name == 'essay-writing'), '') if essay else ''
    return {'url': normalized, 'course_id': course, 'assignment_id': aid,
            'essay': essay, 'writing_guidance': writing,
            'title': row.get('name'), 'user_id': str(profile['id']), 'user_name': profile.get('name'), 'instructions': plain(row.get('description')),
            'rubric': row.get('rubric') or [], 'due_at': row.get('due_at'),
            'submission_types': row.get('submission_types') or [],
            'allowed_extensions': row.get('allowed_extensions') or [],
            'locked': bool(row.get('locked_for_user')), 'lock_explanation': row.get('lock_explanation'),
            'resources': [urljoin(origin, link) for link in doc.links],
            'submission': row.get('submission') or {}, 'untrusted_content': True}


def grant(url, enabled, hours=24, user_id=None):
    _, _, _, normalized = assignment_location(url)
    return store.put('grant', normalized, {'url': normalized, 'enabled': bool(enabled),
        'user_id': str(user_id) if user_id is not None else None,
        'expires_at': time.time() + min(max(float(hours), 0), 168) * 3600})


def require_grant(url, user_id=None):
    workflows.require_running()
    value = store.get('grant', url) or {}
    if not value.get('enabled') or value.get('expires_at', 0) <= time.time():
        raise CourseworkError('This assignment needs authorization in School → Operator before Nova can submit it.')
    if user_id is not None and value.get('user_id') != str(user_id):
        raise CourseworkError('The Canvas account differs from the authorized account. Authorize the current account first.')


def fingerprint(path):
    file = Path(path).expanduser().resolve()
    if not file.is_file() or file.stat().st_size > 50_000_000:
        raise CourseworkError('Submission files must exist and be no larger than 50 MB each.')
    from .nova_tools import _deny_path
    if _deny_path(file) or file.name.lower().endswith('.env'):
        raise CourseworkError('Credential files cannot be submitted.')
    return {'path': str(file), 'name': file.name, 'size': file.stat().st_size,
            'sha256': hashlib.sha256(file.read_bytes()).hexdigest()}


async def prepare(url, submission_type, text='', file_paths=None, submission_url='', notes='', sources=None):
    packet = await assignment(url)
    current = store.get('essay_current', packet['url'] + ':' + str(packet['user_id'])) or {}
    proposal = store.get('essay_topic', current.get('topic_id', ''))
    if packet.get('essay') and (not proposal or not proposal.get('approved')):
        raise CourseworkError('Propose an essay topic first and have the user approve it in School → Operator.')
    if packet['locked']:
        raise CourseworkError('Assignment is locked: ' + str(packet['lock_explanation'] or 'Canvas does not allow submission.'))
    if submission_type not in packet['submission_types'] or submission_type not in ('online_text_entry', 'online_upload', 'online_url'):
        raise CourseworkError('This assignment needs a specialized workflow; supported forms are text, files and URL.')
    files = [fingerprint(path) for path in (file_paths or [])]
    if len(files) > 10:
        raise CourseworkError('At most ten files per submission.')
    if submission_type == 'online_text_entry' and not text.strip():
        raise CourseworkError('The submission text is empty.')
    if submission_type == 'online_upload' and not files:
        raise CourseworkError('Select the completed assignment files.')
    if submission_type == 'online_url' and urlsplit(submission_url).scheme not in ('http', 'https'):
        raise CourseworkError('A URL submission requires an HTTP(S) URL.')
    allowed = packet['allowed_extensions']
    if allowed and any(Path(f['path']).suffix.lstrip('.').lower() not in [e.lower().lstrip('.') for e in allowed] for f in files):
        raise CourseworkError('A file extension is not permitted by this assignment.')
    return store.create('draft', url=packet['url'], title=packet['title'], submission_type=submission_type,
                        text=text, files=files, submission_url=submission_url, notes=notes,
                        sources=sources or [], status='prepared', packet=packet,
                        review_required=bool(packet.get('essay') or submission_type in ('online_text_entry', 'online_upload')), essay_reviewed=False,
                        essay_topic=proposal['topic'] if proposal and packet.get('essay') else None)


async def topic(url, topic='', rationale=''):
    packet = await assignment(url)
    key = packet['url'] + ':' + str(packet['user_id'])
    if not topic.strip():
        current = store.get('essay_current', key) or {}
        return store.get('essay_topic', current.get('topic_id', '')) or {'status': 'not_proposed'}
    if not rationale.strip():
        raise CourseworkError('Include a short rationale for the suggested topic.')
    proposal = store.create('essay_topic', url=packet['url'], user_id=packet['user_id'],
        topic=topic, rationale=rationale, approved=False)
    store.put('essay_current', key, {'topic_id':proposal['id']})
    return proposal


def approve_topic(topic_id):
    with store.transaction() as connection:
        proposal = store.get('essay_topic', topic_id, connection)
        if not proposal:
            raise CourseworkError('Unknown essay topic.')
        current = store.get('essay_current', proposal['url'] + ':' + str(proposal['user_id']), connection) or {}
        if current.get('topic_id') != topic_id:
            raise CourseworkError('This topic has been replaced. Review the latest proposal.')
        proposal['approved'] = True
        return store.put('essay_topic', topic_id, proposal, connection)


def approve_essay(draft_id):
    with store.transaction() as connection:
        draft = store.get('draft', draft_id, connection)
        if not draft or draft['status'] != 'prepared':
            raise CourseworkError('Only a prepared draft can be approved.')
        draft['essay_reviewed'] = True
        return store.put('draft', draft_id, draft, connection)


def matches(draft, receipt):
    if not receipt.get('submitted_at') or str(receipt.get('assignment_id')) != draft['packet']['assignment_id']:
        return False
    kind = draft['submission_type']
    if receipt.get('submission_type') != kind:
        return False
    if kind == 'online_text_entry':
        return plain(receipt.get('body')) == ' '.join(draft['text'].split())
    if kind == 'online_url':
        return receipt.get('url', '').rstrip('/') == draft['submission_url'].rstrip('/')
    attachments = receipt.get('attachments') or []
    return sorted((f['name'], f['size'], f['sha256']) for f in draft['files']) == sorted(
        (f.get('display_name') or f.get('filename'), f.get('size'), f.get('_verified_sha256', '')) for f in attachments)


async def verify_receipt(draft, receipt):
    if str(receipt.get('user_id')) != str(draft['packet'].get('user_id')):
        return False
    if draft['submission_type'] == 'online_upload' and receipt.get('submitted_at'):
        tab = await browser_control.page()
        attachments = receipt.get('attachments') or []
        if len(attachments) != len(draft['files']):
            return False
        origin, _, _, _ = assignment_location(draft['url'])
        for attachment in attachments:
            file_id = str(attachment.get('id', ''))
            if not file_id.isdigit():
                return False
            # Canvas serves the actual submitted file, not the current local
            # file. Browser cookies remain scoped by the browser's cookie jar.
            response = await tab.context.request.get(f'{origin}/files/{file_id}/download', timeout=30000)
            if response.status != 200:
                return False
            body = await response.body()
            if len(body) > 50_000_000:
                return False
            attachment['_verified_sha256'] = hashlib.sha256(body).hexdigest()
    return matches(draft, receipt)


async def current_receipt(draft):
    _, course, aid, _ = assignment_location(draft['url'])
    return await read_json(draft['url'], f'courses/{course}/assignments/{aid}/submissions/self')


async def visible_click(tab, label, authorize=None):
    workflows.require_running()
    await tab.bring_to_front()
    # Canvas exposes named controls. Browser input targets their actual bounds
    # and checks visibility/obstructions, unlike model-generated desktop points.
    if label.startswith('Start Assignment'):
        target = tab.locator('a.submit_assignment_link, button.submit_assignment_link').filter(
            has_text=re.compile(r'^(Start Assignment|New Attempt|Re-submit Assignment)$', re.I))
    elif label.startswith('Submit Assignment'):
        target = tab.locator('#submit_assignment').get_by_role('button', name='Submit Assignment', exact=True)
    else:
        name = next((n for n in ('File Upload', 'Website URL', 'Text Entry') if label.startswith(n)), None)
        if not name:
            raise CourseworkError('Unknown Canvas control: ' + label)
        form = tab.locator('#submit_assignment')
        target = form.get_by_role('tab', name=name, exact=True).or_(form.get_by_role('button', name=name, exact=True)).or_(form.get_by_role('link', name=name, exact=True))
    if await target.count() != 1:
        raise CourseworkError('Canvas control is missing or ambiguous: ' + label)
    await target.scroll_into_view_if_needed(timeout=10000)
    await target.click(trial=True, timeout=10000)
    workflows.require_running()
    if authorize:
        result = authorize()
        if asyncio.iscoroutine(result):
            await result
    workflows.require_running()
    await target.click(timeout=10000)
    await asyncio.sleep(0.4)


async def _form(tab, draft):
    await tab.goto(draft['url'], wait_until='domcontentloaded', timeout=30000)
    if assignment_location(tab.url)[3] != draft['url']:
        raise CourseworkError('Canvas redirected away from the intended assignment.')
    opener = tab.locator('a.submit_assignment_link, button.submit_assignment_link').first
    if await opener.count() and await opener.is_visible():
        await visible_click(tab, 'Start Assignment or New Attempt button for this assignment')
    form = tab.locator('#submit_assignment')
    await form.wait_for(state='visible', timeout=15000)
    kind = draft['submission_type']
    if kind == 'online_upload':
        await visible_click(tab, 'File Upload tab in the assignment submission form')
        field = form.locator('input[type=file]').first
        payloads = []
        for file in draft['files']:
            content = Path(file['path']).read_bytes()
            if len(content) != file['size'] or hashlib.sha256(content).hexdigest() != file['sha256']:
                raise CourseworkError('A submission file changed while preparing the form. Prepare a new draft.')
            payloads.append({'name': file['name'], 'mimeType': 'application/octet-stream', 'buffer': content})
        await field.set_input_files(payloads)
    elif kind == 'online_url':
        await visible_click(tab, 'Website URL tab in the assignment submission form')
        await form.locator('input[name="submission[url]"]').fill(draft['submission_url'])
    else:
        await visible_click(tab, 'Text Entry tab in the assignment submission form')
        # Canvas rich-text editors use an iframe; plain HTML forms use a textarea.
        frame = form.locator('iframe').first
        if await frame.count():
            editor = form.frame_locator('iframe').first.locator('body[contenteditable=true]')
            await editor.fill(draft['text'])
        else:
            await form.locator('textarea[name="submission[body]"]').fill(draft['text'])
    # Record the actual prepared form before the irreversible click.
    shot = await tab.screenshot(type='png')
    (store.directory() / f'{draft["id"]}-prepared.png').write_bytes(shot)
    async def authorized_account():
        profile = await read_json(draft['url'], 'users/self/profile')
        if str(profile['id']) != str(draft['packet'].get('user_id')):
            raise CourseworkError('The Canvas account changed while preparing the form.')
        require_grant(draft['url'], profile['id'])
    await authorized_account()
    await visible_click(tab, 'Submit Assignment button at the bottom of the prepared submission form',
                        authorize=authorized_account)


async def check_form(url):
    """Open the submission form, without filling or submitting anything."""
    async with workflows.action_lock, browser_control._lock:
        workflows.require_running()
        packet = await assignment(url)
        if packet['locked'] or packet.get('submission', {}).get('submitted_at'):
            raise CourseworkError('Only an unlocked, unsubmitted assignment can be checked this way.')
        if not set(packet['submission_types']) & {'online_upload', 'online_text_entry', 'online_url'}:
            raise CourseworkError('This assignment uses an unsupported external or quiz workflow.')
        tab = await browser_control.page()
        await tab.goto(packet['url'], wait_until='domcontentloaded', timeout=30000)
        workflows.require_running()
        if assignment_location(tab.url)[3] != packet['url']:
            raise CourseworkError('Canvas redirected away from the assignment.')
        opener = tab.locator('a.submit_assignment_link, button.submit_assignment_link').first
        if await opener.count() and await opener.is_visible():
            await visible_click(tab, 'Start Assignment button for ' + packet['title'])
        form = tab.locator('#submit_assignment')
        await form.wait_for(state='visible', timeout=15000)
        fields = {'file_inputs':await form.locator('input[type=file]').count(),
                  'text_inputs':await form.locator('textarea, iframe').count(),
                  'url_inputs':await form.locator('input[name="submission[url]"]').count()}
        if not any(fields.values()):
            raise CourseworkError('The visible form does not contain a supported submission field.')
        result = store.create('form_check', url=packet['url'], title=packet['title'], fields=fields, submitted=False)
        (store.directory() / f'{result["id"]}-form-check.png').write_bytes(await tab.screenshot(type='png'))
        return result


async def submit(draft_id):
    async with workflows.action_lock, browser_control._lock:
        draft = store.get('draft', draft_id)
        if not draft:
            raise CourseworkError('Unknown draft.')
        if draft['status'] == 'submitted':
            return draft
        if draft.get('review_required') and not draft.get('essay_reviewed'):
            raise CourseworkError('The user must review and approve this written draft before submission.')
        require_grant(draft['url'], draft['packet'].get('user_id'))
        # Unknown outcomes are reconciled, never retried by posting again.
        before = await current_receipt(draft)
        if str(before.get('user_id')) != str(draft['packet'].get('user_id')):
            raise CourseworkError('The signed-in Canvas account changed. Prepare and authorize a new draft.')
        attempt_key = draft['url'] + ':' + str(before['user_id'])
        unresolved = store.get('attempt', attempt_key)
        if unresolved and unresolved['draft_id'] != draft_id and unresolved['status'] in ('submitting', 'unknown'):
            raise CourseworkError('Another draft has an unknown submission for this assignment. Reconcile its receipt first.')
        if await verify_receipt(draft, before):
            draft.update(status='submitted', receipt=before, verified_at=time.time())
            store.put('attempt', attempt_key, {'draft_id': draft_id, 'status': 'submitted'})
            return store.put('draft', draft_id, draft)
        if draft['status'] in ('submitting', 'unknown'):
            raise CourseworkError('Previous submission outcome is unknown. Inspect Canvas and reconcile before trying again.')
        fresh = await assignment(draft['url'])
        if fresh['locked'] or draft['submission_type'] not in fresh['submission_types']:
            raise CourseworkError('Canvas changed the assignment or locked submissions; refresh the draft.')
        for file in draft['files']:
            if fingerprint(file['path']) != file:
                raise CourseworkError('A submission file changed since preparation. Prepare a new draft.')
        draft.update(status='submitting', previous_attempt=before.get('attempt'), started_at=time.time())
        store.put('draft', draft_id, draft)
        store.put('attempt', attempt_key, {'draft_id': draft_id, 'status': 'submitting'})
        try:
            tab = await browser_control.page()
            await _form(tab, draft)
            for _ in range(6):
                receipt = await current_receipt(draft)
                if await verify_receipt(draft, receipt):
                    shot = await tab.screenshot(type='png')
                    (store.directory() / f'{draft_id}-receipt.png').write_bytes(shot)
                    draft.update(status='submitted', receipt=receipt, verified_at=time.time())
                    store.put('attempt', attempt_key, {'draft_id': draft_id, 'status': 'submitted'})
                    return store.put('draft', draft_id, draft)
                await asyncio.sleep(1)
            raise CourseworkError('Canvas has not confirmed this exact submission. Check the receipt before retrying.')
        except BaseException as exc:
            draft.update(status='unknown', error=type(exc).__name__ + ': submission not verified; inspect Canvas before retrying.')
            store.put('draft', draft_id, draft)
            store.put('attempt', attempt_key, {'draft_id': draft_id, 'status': 'unknown'})
            if isinstance(exc, asyncio.CancelledError) or 'corner' in str(exc).lower():
                workflows.stop('Submission interrupted. Inspect Canvas before resuming.')
            raise


async def status(draft_id):
    async with workflows.action_lock, browser_control._lock:
        return await _status(draft_id)


async def _status(draft_id):
    draft = store.get('draft', draft_id)
    if not draft:
        raise CourseworkError('Unknown draft.')
    if draft['status'] in ('submitting', 'unknown'):
        receipt = await current_receipt(draft)
        if await verify_receipt(draft, receipt):
            draft.update(status='submitted', receipt=receipt, verified_at=time.time())
            with store.transaction() as connection:
                store.put('draft', draft_id, draft, connection)
                key = draft['url'] + ':' + str(receipt['user_id'])
                attempt = store.get('attempt', key, connection)
                if not attempt or attempt['draft_id'] == draft_id:
                    store.put('attempt', key, {'draft_id': draft_id, 'status': 'submitted'}, connection)
    return draft
