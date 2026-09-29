"""User-facing operator controls. Grants are not exposed as model tools."""
import asyncio
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import coursework, nova_tools, operator_store as store, operator_workflows as workflows
from . import coursework_browser
from . import coursework_materials
from . import coursework_external
from . import coursework_queue

router = APIRouter(prefix='/operator', tags=['operator'])


class ExternalRequest(BaseModel):
    action: str
    url: str = ''
    session_id: str = ''
    snapshot: str = ''
    ref: str = ''
    text: str = ''
    keys: str = ''


@router.post('/external')
async def external_homework(body: ExternalRequest):
    await writable()
    try:
        return await coursework_external.perform(**body.model_dump())
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


class Authorization(BaseModel):
    url: str
    enabled: bool
    hours: int = Field(default=24, ge=1, le=168)


class AssignmentRequest(BaseModel):
    url: str


class ConnectionRequest(BaseModel):
    url: str = ''


@router.post('/form-check')
async def check_submission_form(body: AssignmentRequest):
    await writable()
    try:
        return await coursework.check_form(body.url)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


class TopicApproval(BaseModel):
    topic_id: str


class MaterialRequest(BaseModel):
    url: str
    resource_url: str


@router.post('/material')
async def read_material(body: MaterialRequest):
    await writable()
    try:
        return await coursework_materials.read(body.url, body.resource_url)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post('/canvas/connect')
async def connect_canvas(body: ConnectionRequest):
    await writable()
    try:
        return await coursework_browser.connect(body.url)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post('/canvas/assignments')
async def browser_assignments(body: ConnectionRequest, include_submitted: bool = False):
    try:
        return await coursework_browser.assignments(body.url, include_submitted=include_submitted)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post('/topics/approve')
async def approve_topic(body: TopicApproval):
    await writable()
    try:
        return coursework.approve_topic(body.topic_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post('/drafts/{draft_id}/approve')
async def approve_draft(draft_id: str):
    await writable()
    try:
        return coursework.approve_essay(draft_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


async def writable():
    if await nova_tools.autonomy_level() == 'readonly':
        raise HTTPException(403, 'Nova is in read-only mode.')


@router.get('/status')
async def status():
    return {'stopped': workflows.stopped(), 'tasks': store.listing('task'),
            'external_sessions':store.listing('external_session'), 'external_attempts':store.listing('external_attempt'),
            'topics':[t for t in store.listing('essay_topic') if t['id'] in {c['topic_id'] for c in store.listing('essay_current')}],
            'drafts': store.listing('draft'), 'grants': store.listing('grant'),
            'playbooks': store.listing('playbook'), 'budgets': store.listing('budget'), 'downloads': store.listing('download'),
            'queues': coursework_queue.list_queues()}


@router.post('/stop')
async def stop():
    return workflows.stop()


@router.post('/resume')
async def resume():
    await writable()
    return workflows.resume()


@router.post('/authorize')
async def authorize(body: Authorization):
    await writable()
    try:
        packet = await coursework.assignment(body.url) if body.enabled else None
        return coursework.grant(body.url, body.enabled, body.hours, packet['user_id'] if packet else None)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post('/assignment')
async def assignment(body: AssignmentRequest):
    try:
        return await coursework.assignment(body.url)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post('/drafts/{draft_id}/submit')
async def submit(draft_id: str):
    await writable()
    try:
        return await coursework.submit(draft_id)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post('/drafts/{draft_id}/reconcile')
async def reconcile(draft_id: str):
    try:
        return await coursework.status(draft_id)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get('/drafts/{draft_id}/evidence/{kind}')
async def evidence(draft_id: str, kind: str):
    if kind not in ('prepared', 'receipt') or not store.get('draft', draft_id):
        raise HTTPException(404, 'No such evidence.')
    path = store.directory() / f'{draft_id}-{kind}.png'
    if not path.is_file():
        raise HTTPException(404, 'No screenshot was recorded.')
    return FileResponse(path, media_type='image/png')


@router.get('/tasks/{task_id}/evidence/{evidence_id}/{kind}')
async def task_evidence(task_id: str, evidence_id: str, kind: str):
    task = store.get('task', task_id) or {}
    if kind not in ('before', 'after') or not any(s.get('evidence_id') == evidence_id for s in task.get('steps', [])):
        raise HTTPException(404, 'No such evidence.')
    path = store.directory() / f'{evidence_id}-{kind}.png'
    if not path.is_file():
        raise HTTPException(404, 'No screenshot was recorded.')
    return FileResponse(path, media_type='image/png')


# Durable coursework queues. Created only from the user-facing API: the
# assignment-scoped submission authorization is the user's, never a model's.

class QueueAssignment(BaseModel):
    url: str
    title: str = ''
    course_name: str = ''


class QueueRequest(BaseModel):
    assignments: list[QueueAssignment] = Field(min_length=1, max_length=50)
    account_id: str
    authorize_submission: bool = False
    mode: str = 'autopilot'
    browser: str | None = None  # None: the browser chosen in Settings
    max_attempts: int = 2
    assignment_timeout_seconds: int = 300


_QUEUE_RUNS: dict[str, asyncio.Task] = {}


def _log_queue_failure(task: asyncio.Task):
    # Item outcomes are persisted by the queue itself; this only surfaces a run
    # that failed before starting (stopped operator, lease held, missing queue).
    if not task.cancelled() and task.exception():
        logging.getLogger(__name__).warning('Coursework queue run ended: %s', task.exception())


@router.post('/queues')
async def create_queue(body: QueueRequest):
    await writable()
    try:
        return coursework_queue.create_queue(
            [a.model_dump() for a in body.assignments], account_id=body.account_id,
            authorize_submission=body.authorize_submission, mode=body.mode, browser=body.browser,
            max_attempts=body.max_attempts, assignment_timeout_seconds=body.assignment_timeout_seconds)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get('/queues/{queue_id}')
async def queue_status(queue_id: str):
    try:
        return coursework_queue.status(queue_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post('/queues/{queue_id}/run')
async def run_queue(queue_id: str, resume: bool = False):
    """Start (or explicitly resume) a queue in the background; poll its status."""
    await writable()
    try:
        coursework_queue.status(queue_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    running = _QUEUE_RUNS.get(queue_id)
    if running and not running.done():
        raise HTTPException(409, 'This queue is already running.')
    task = asyncio.create_task(coursework_queue.run_queue(queue_id, resume=resume))
    _QUEUE_RUNS[queue_id] = task
    task.add_done_callback(_log_queue_failure)
    return {'started': True, 'queue_id': queue_id}


@router.post('/queues/{queue_id}/cancel')
async def cancel_queue(queue_id: str):
    try:
        return coursework_queue.cancel_queue(queue_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post('/queues/{queue_id}/items/{item_id}/reconcile')
async def reconcile_queue_item(queue_id: str, item_id: str):
    """Check the portal receipt for an uncertain item; never accepts a client-supplied outcome."""
    try:
        return await coursework_queue.reconcile_item(queue_id, item_id)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
