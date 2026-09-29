"""Connect the visible browser and discover current Canvas assignments."""
from urllib.parse import urlsplit
from . import browser_control, canvas, canvas_feed, coursework, operator_workflows as workflows
from . import operator_store as store


def origin(url=''):
    raw = url or (store.get('control', 'canvas') or {}).get('origin') or canvas.base_url() or canvas_feed.feed_url() or ''
    parsed = urlsplit(raw)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Provide your HTTPS Canvas website URL.')
    return f'https://{parsed.netloc}'


async def connect(url=''):
    workflows.require_running()
    base = origin(url)
    async with workflows.action_lock, browser_control._lock:
        workflows.require_running()
        tab = await browser_control.page()
        workflows.require_running()
        await tab.goto(base, wait_until='domcontentloaded', timeout=30000)
        await tab.bring_to_front()
        try:
            profile = await coursework.read_json(base + '/courses/0/assignments/0', 'users/self/profile')
        except coursework.CourseworkError:
            return {'connected':False, 'url':base, 'message':'Canvas is open in Nova’s browser. Finish signing in there, then check connection again.'}
        store.put('control', 'canvas', {'origin':base})
        return {'connected':True, 'url':base, 'user_id':str(profile['id']), 'name':profile.get('name'), 'message':'Canvas browser session connected.'}


async def assignments(url='', include_submitted=False):
    base = origin(url)
    fake = base + '/courses/0/assignments/0'
    rows = []
    truncated = False
    async with workflows.action_lock, browser_control._lock:
        profile = await coursework.read_json(fake, 'users/self/profile')
        courses = await coursework.read_json(fake, 'courses?enrollment_state=active&per_page=100')
        if not isinstance(courses, list):
            raise ValueError('Canvas did not return a course list.')
        truncated = len(courses) >= 100
        for course in courses:
            workflows.require_running()
            course_id = str(course.get('id', ''))
            if not course_id.isdigit():
                continue
            for page_number in range(1, 11):
                workflows.require_running()
                bucket = '' if include_submitted else 'bucket=unsubmitted&'
                assignments = await coursework.read_json(fake, f'courses/{course_id}/assignments?{bucket}include[]=submission&per_page=100&page={page_number}')
                if not isinstance(assignments, list):
                    raise ValueError('Canvas did not return an assignment list.')
                for row in assignments:
                    rows.append({'title':row.get('name'), 'course_name':course.get('name'), 'due_at':row.get('due_at'),
                        'url':f'{base}/courses/{course_id}/assignments/{row["id"]}', 'locked':bool(row.get('locked_for_user')),
                        'submission_types':row.get('submission_types') or [], 'submitted':bool((row.get('submission') or {}).get('submitted_at'))})
                if len(assignments) < 100:
                    break
            else:
                truncated = True
    rows.sort(key=lambda r:r.get('due_at') or '9999')
    return {'assignments':rows,'truncated':truncated,'user_id':str(profile['id']), 'untrusted_content':True}
