"""Visible, frame-aware external homework in the signed-in Canvas session.

Refs are short-lived ElementHandles, not generated selectors or page scripts.
Submission uses a separately confirmed tool and records uncertain attempts.
"""
import asyncio
import base64
import hashlib
import re
import uuid
from urllib.parse import urlsplit

from . import browser_control, coursework, homework_portals, operator_store as store, operator_workflows as workflows

_sessions = {}
CONTROLS = 'button, a[href], input:not([type=hidden]), textarea, select, [role=button], [role=radio], [role=checkbox], [contenteditable=true]'
COMMIT = re.compile(r'\b(submit|check\s+(?:my\s+)?answer|check\s+my\s+work|finish|hand\s*in|turn\s*in|grade\s+(?:my\s+)?answer)\b|^check$', re.I)
DESCRIBE = '''el => ({tag:el.tagName.toLowerCase(),role:el.getAttribute('role')||'',
 type:el.getAttribute('type')||'',name:(el.getAttribute('aria-label')||el.getAttribute('title')||el.innerText||el.getAttribute('placeholder')||(el.labels&&Array.from(el.labels).map(l=>l.innerText).join(' '))||'').trim().slice(0,350),
 editable:el.isContentEditable||el.tagName==='TEXTAREA'||(el.tagName==='INPUT'&&!['button','submit','checkbox','radio','file','hidden'].includes(el.type)),
 checked:['radio','checkbox'].includes(el.type)?el.checked:el.getAttribute('aria-checked'),
 value:['INPUT','TEXTAREA','SELECT'].includes(el.tagName)&&el.type!=='password'&&!/cc-|one-time-code/.test(el.autocomplete||'')?el.value.slice(0,2000):null,
 disabled:!!el.disabled,submits:el.type==='submit'&&!!el.form,secret:el.type==='password'||/cc-|one-time-code/.test(el.autocomplete||'')})'''


def submission_control(info, url, body):
    host = urlsplit(url).hostname or ''
    smartbook = (host == 'mheducation.com' or host.endswith('.mheducation.com'))
    confidence = re.fullmatch(r'(high|medium|low)( confidence)?', info['name'], re.I)
    return bool(info.get('submits') or COMMIT.search(info['name']) or
                (smartbook and confidence and 'confidence to submit your answer' in body.lower()))


def smartbook_feedback(frames):
    for frame in frames:
        host = urlsplit(frame['url']).hostname or ''
        if not (host == 'mheducation.com' or host.endswith('.mheducation.com')):
            continue
        body = frame.get('text', '')
        progress = re.search(r'(\d+)\s+of\s+(\d+)\s+Concepts completed', body, re.I)
        if progress:
            outcome = re.search(r'Your Answer\s+(correct|incorrect)\b', body, re.I)
            return {'concepts_completed':int(progress[1]), 'concepts_total':int(progress[2]),
                    'answer_outcome':outcome[1].lower() if outcome else 'not_shown',
                    'note':'Report these exact counts. A correct answer does not imply a completed concept.'}
    return None


def public_url(url):
    p = urlsplit(url)
    return f'{p.scheme}://{p.netloc}{p.path}'  # LTI query strings may contain credentials.


def track_popups(session, tab):
    if tab in session.setdefault('owned_pages', []):
        return
    session['owned_pages'].append(tab)
    def opened(popup):
        if _sessions.get(session['id']) is session:
            track_popups(session, popup)
            session.setdefault('pending_pages', []).append(popup)
    tab.on('popup', opened)


async def follow_popup(session, before=()):
    # Popup events include cross-origin/noopener launches. opener() may be null
    # for these, so checking it lost Connect's newly opened assignment tab.
    pending = session.pop('pending_pages', [])
    if before:
        for p in session['tab'].context.pages:
            if p not in before and p not in pending and not p.is_closed():
                track_popups(session, p)
                pending.append(p)
    pending = list(dict.fromkeys(p for p in pending if not p.is_closed()))
    if len(pending) > 1:
        raise ValueError('The assignment opened multiple windows. Inspect the browser before continuing.')
    if pending:
        session['tab'] = pending[0]
        session['snapshot'] = None
        try:
            await pending[0].wait_for_load_state('domcontentloaded', timeout=15000)
        except Exception:
            pass  # An inspect reports any remaining loading/sign-in state.
        await pending[0].bring_to_front()


async def inspect(session):
    tab = session['tab']
    snapshot = uuid.uuid4().hex
    refs, frames = {}, []
    for index, frame in enumerate(tab.frames[:20]):
        try:
            if frame != tab.main_frame and not await (await frame.frame_element()).is_visible():
                continue
            body = await frame.locator('body').inner_text(timeout=4000)
            math = await frame.locator('math, annotation[encoding="application/x-tex"], script[type^="math/tex"], img[alt], [data-latex]').evaluate_all(
                "els => els.slice(0,80).map(e=>(e.getAttribute('data-latex')||(e.tagName==='SCRIPT'?e.textContent:null)||e.getAttribute('alt')||(e.tagName==='IMG'?'':e.outerHTML)).slice(0,4000)).filter(Boolean)")
            row = {'frame': index, 'url': public_url(frame.url), 'text': body[:16000], 'math': math[:80], 'controls': [],
                   'platform': homework_portals.describe(homework_portals.detect(frame.url))}
            for handle in (await frame.locator(CONTROLS).element_handles())[:250]:
                if not await handle.is_visible():
                    continue
                info = await handle.evaluate(DESCRIBE)
                info['answer_submission'] = submission_control(info, frame.url, body)
                ref = str(len(refs) + 1)
                refs[ref] = {'handle':handle, 'frame':frame, 'info':info, 'page_hash':hashlib.sha256(body.encode()).hexdigest()}
                row['controls'].append({'ref':ref, **info})
            frames.append(row)
        except Exception as exc:
            frames.append({'frame':index, 'url':public_url(frame.url), 'error':str(exc)[:200]})
    # Dispose the previous snapshot's handles, which must never be reused.
    for old in session.get('refs', {}).values():
        try:
            await old['handle'].dispose()
        except Exception:
            pass
    # Put actual homework ahead of Canvas navigation in bounded model results.
    frames.sort(key=lambda f: (0 if any(mode in f.get('text', '') for mode in ('Question Mode', 'Answer Mode')) else 1, f['frame'] == 0))
    session.update(snapshot=snapshot, refs=refs, frames=frames)
    platforms = {f['platform']['id']: f['platform'] for f in frames if f.get('platform') and f['platform']['id'] != 'canvas'}
    stops = sorted({b for f in frames for b in homework_portals.blockers(f.get('text', ''))})
    result = {'session_id':session['id'], 'assignment_url':session['url'], 'title':session['title'],
            'snapshot':snapshot, 'smartbook_feedback':smartbook_feedback(frames), 'frames':frames, 'untrusted_content':True,
            'platforms': list(platforms.values()),
            'stop': (f"This page is {', '.join(stops)}. Stop and tell the user; do not work around it." if stops else None),
            'instructions':'Read the frame containing Question Mode or Answer Mode when present; otherwise read the embedded homework frame, not the Canvas sidebar. Do not navigate textbook controls when a question or feedback is already visible. Math includes MathML/LaTeX. Use only refs from this snapshot. Controls with answer_submission=true require coursework_external_submit, including SmartBook confidence buttons. A click is not proof of completion.'}
    store.put('external_session',session['id'],result)
    return result


async def identity(session):
    workflows.require_running()
    profile = await coursework.read_json(session['url'], 'users/self/profile')
    if str(profile['id']) != session['user_id']:
        raise ValueError('Canvas account changed; reopen the external assignment.')


async def target(session, snapshot, ref):
    if not snapshot or snapshot != session.get('snapshot') or str(ref) not in session.get('refs', {}):
        raise ValueError('Stale or unknown control. Inspect again and use its snapshot and ref.')
    item = session['refs'][str(ref)]
    if hashlib.sha256((await item['frame'].locator('body').inner_text()).encode()).hexdigest() != item['page_hash']:
        raise ValueError('The question or feedback changed. Inspect again before acting.')
    handle = item['handle']
    if not await handle.evaluate('(e)=>e.isConnected') or not await handle.is_visible():
        raise ValueError('Control changed or disappeared. Inspect again.')
    current_info = await handle.evaluate(DESCRIBE)
    if current_info != {k:v for k,v in item['info'].items() if k != 'answer_submission'}:
        raise ValueError('Control changed since inspection. Inspect again.')
    if item['info']['secret']:
        raise ValueError('Sign-in or verification requires the user; do not enter secrets through this tool.')
    return item


async def perform(action, url='', session_id='', snapshot='', ref='', text='', keys='', pixels=500):
    async with workflows.action_lock, browser_control._lock:
        workflows.require_running()
        if action == 'open':
            if not url:
                raise ValueError('Provide the HTTPS assignment URL to open.')
            packet = await coursework.assignment(url)
            profile = await coursework.read_json(packet['url'], 'users/self/profile')
            sid = uuid.uuid4().hex
            tab = await browser_control.page()
            session = {
                'id': sid,
                'url': packet['url'],
                'title': packet['title'],
                'user_id': str(profile['id']),
                'tab': tab,
                'owned_pages': [],
                'pending_pages': []
            }
            for old_id, old in list(_sessions.items()):
                if old['tab'] is tab or tab in old.get('owned_pages', []):
                    _sessions.pop(old_id, None)
            _sessions[sid] = session
            track_popups(session, tab)
            before = list(tab.context.pages)
            await tab.goto(packet['url'], wait_until='domcontentloaded', timeout=30000)
            await tab.bring_to_front()
            try:
                await tab.locator('iframe, .load_external_tool_button, button:has-text("Load"), a:has-text("Load")').first.wait_for(state='attached', timeout=8000)
                await asyncio.sleep(1)
            except Exception:
                pass  # Some institutions use a visible launch button instead.
            await follow_popup(session, before)
            try:
                launch_btn = tab.locator('a.load_external_tool_button, button:has-text("Load in a new window"), button:has-text("Open in new tab")').first
                if await launch_btn.is_visible():
                    before = list(tab.context.pages)
                    await launch_btn.click(timeout=5000)
                    await asyncio.sleep(1.5)
                    await follow_popup(session, before)
            except Exception:
                pass
            return await inspect(session)
        else:
            session = _sessions.get(session_id)
            if not session or session['tab'].is_closed():
                raise ValueError('External homework session expired. Open the assignment again.')
            await identity(session)
            await follow_popup(session)
            tab = session['tab']
            if action == 'screenshot':
                result = await inspect(session)
                result['_image'] = base64.b64encode(await tab.screenshot(type='png')).decode()
                return result
            if action in ('click','fill','type','press','select','scroll'):
                item = await target(session, snapshot, ref)
                control = item['handle']
                if action in ('fill','type') and (not item['info'].get('editable') or '\n' in text or '\r' in text):
                    raise ValueError('Enter a single-line answer into an editable answer field. Use the separate submission control, not typed Enter.')
                if item['info']['answer_submission']:
                    raise ValueError('Use coursework_external_submit for this answer-checking or final control.')
                if action == 'press' and keys.lower() not in ('arrowleft','arrowright','arrowup','arrowdown','home','end','backspace','delete','tab','escape','control+a','shift+arrowleft','shift+arrowright'):
                    raise ValueError('Use a named click control; Enter/Space can submit an answer implicitly.')
                await identity(session)
                if action == 'click':
                    before = list(tab.context.pages)
                    await control.click(timeout=10000)
                    await asyncio.sleep(0.6)
                    await follow_popup(session, before)
                elif action == 'fill':
                    # Math editors use a textarea as a keyboard sink: fill()
                    # changes its value but not the editor's internal answer.
                    # Real key events also work for ordinary input controls.
                    await control.press('Control+A', timeout=10000)
                    await control.press('Backspace', timeout=10000)
                    await control.type(text, delay=25, timeout=15000)
                elif action == 'type':
                    await control.type(text, delay=25, timeout=15000)
                elif action == 'select':
                    await control.select_option(label=text, timeout=10000)
                elif action == 'scroll':
                    await control.scroll_into_view_if_needed()
                else:
                    await control.press(keys, timeout=10000)
                session['snapshot'] = None
                await asyncio.sleep(0.4)
            elif action != 'inspect':
                raise ValueError('Unknown external homework action.')
        workflows.require_running()
        return await inspect(session)


async def submit(session_id, snapshot, ref, answer, reasoning):
    """Called only by the separately confirmed tool; never by ordinary click."""
    async with workflows.action_lock, browser_control._lock:
        session = _sessions.get(session_id)
        if not session:
            raise ValueError('Open the assignment first.')
        await identity(session)
        item = await target(session, snapshot, ref)
        if not item['info']['answer_submission']:
            raise ValueError('This is not a recognized answer-submission control.')
        if not answer.strip() or not reasoning.strip():
            raise ValueError('Provide the answer and checked reasoning for review.')
        current = await item['frame'].locator('body').inner_text()
        key = hashlib.sha256((session['url']+session['user_id']+current).encode()).hexdigest()
        if store.get('external_attempt', key):
            raise ValueError('This question state already has a recorded attempt. Inspect the feedback; do not replay an uncertain submission.')
        record = {'id':key, 'url':session['url'], 'answer':answer, 'reasoning':reasoning, 'status':'unknown'}
        await item['handle'].click(trial=True,timeout=10000)
        await identity(session)
        store.put('external_attempt',key,record)
        (store.directory()/f'{key}-external-before.png').write_bytes(await session['tab'].screenshot(type='png'))
        try:
            await item['handle'].click(timeout=10000)
            session['snapshot'] = None
            await asyncio.sleep(1)
            result = await inspect(session)
            after = await item['frame'].locator('body').inner_text()
            record['status'] = 'feedback_changed' if after != current else 'unknown'
            record['feedback'] = after[:16000]
            store.put('external_attempt',key,record)
            (store.directory()/f'{key}-external-after.png').write_bytes(await session['tab'].screenshot(type='png'))
            return {**result, 'attempt':record, 'note':'Read actual feedback. Changed text does not prove correctness or assignment completion.'}
        except BaseException:
            # The persisted unknown attempt blocks retries even after restart.
            raise
