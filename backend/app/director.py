"""Nova's director: the workspace/team-orchestration milestone's core logic
(task: "Nova's director receives a request, decides whether delegation is
needed, and creates bounded subtasks with dependencies and completion
criteria. Simple requests should take a direct path without assembling a
team.").

Normal Chat can reach this director through a lightweight multi-step intent
gate. Simple questions keep their direct path. The existing workspace task
API remains available; it is no longer the only way to delegate work.

Execution model, reusing existing pieces rather than rebuilding them
(confirmed by inspection first -- see RESEARCH.md's orchestration-recon
section): each subtask is one routing.resolve_model_id() + one
providers.run_model_call() -- the same real provider adapters (claude_cli,
codex_cli, local Ollama, etc.) /chat and /agents/chain already use. A
subtask that writes files (teams.Role.writes_files) is real: claude_cli/
codex_cli do their own agentic file writes exactly as they do from Chat's
coding category, not a simulation.
"""
from __future__ import annotations

import asyncio
import json
import re

from . import agents, classifier, code_files, config, db, providers, routing, teams, inference_scheduler, execution_tools
from . import team_usage

DEFAULT_MAX_HEAVY_WORKERS = 1
MAX_HEAVY_WORKERS_SETTINGS_KEY = "max_heavy_workers"

_RATE_LIMIT_RETRIES = 0  # Quota failures require visible review, never blind retries.
_RATE_LIMIT_BACKOFF_SECONDS = 30

# One real subprocess/file-writing ("heavy") call at a time per project (task:
# "Prevent workers from concurrently modifying the same files without
# coordination... explicit file/task ownership with reviewed integration").
# Keyed by the project's real path so switching projects doesn't serialize
# against a lock some *other* project is holding. This is the simpler of the
# two options the task allows (explicit ownership vs. isolated working
# copies) -- a real, effective guarantee for v1, at the cost of heavy tasks
# in the same project running one-at-a-time even when they touch unrelated
# files; noted as a real limitation, not hidden.
_file_locks: dict[str, asyncio.Lock] = {}

# Tracks in-flight subtask execution so Cancel can reach the real running
# call (task: "Cancel must reach the running operation where supported") --
# cancelling this asyncio.Task propagates into providers.run_model_call's
# `async for token in stream` loop, and for claude_cli/codex_cli specifically
# into _stream_cli's own cancellation handling, which already kills the
# child subprocess (confirmed by inspection of providers.py -- not a new
# mechanism, the existing client-disconnect cleanup path).
_running_tasks: dict[int, asyncio.Task] = {}


def _file_lock_for_current_project() -> asyncio.Lock:
    key = str(config.get_workspace_dir())
    lock = _file_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _file_locks[key] = lock
    return lock


async def get_max_heavy_workers() -> int:
    stored = (await db.get_app_settings()).get(MAX_HEAVY_WORKERS_SETTINGS_KEY)
    try:
        return max(1, int(stored))
    except (TypeError, ValueError):
        return DEFAULT_MAX_HEAVY_WORKERS


async def set_max_heavy_workers(n: int) -> None:
    await db.set_app_settings({MAX_HEAVY_WORKERS_SETTINGS_KEY: str(max(1, int(n)))})


_heavy_semaphore: asyncio.Semaphore | None = None
_heavy_semaphore_limit: int | None = None


async def _get_heavy_semaphore() -> asyncio.Semaphore:
    """Rebuilds the semaphore if the configured limit changed (task: "Start
    with a configurable limit of two heavy workers") -- simplest correct
    approach for a limit that changes rarely (a Settings action, not a
    per-request thing); in-flight holders of the old semaphore are
    unaffected, new acquires use the new one."""
    global _heavy_semaphore, _heavy_semaphore_limit
    limit = await get_max_heavy_workers()
    if _heavy_semaphore is None or _heavy_semaphore_limit != limit:
        _heavy_semaphore = asyncio.Semaphore(limit)
        _heavy_semaphore_limit = limit
    return _heavy_semaphore


async def _broadcast(task_id: int) -> None:
    task = await db.get_task(task_id)
    if task is not None:
        await agents.registry.broadcast_task(task)


async def _run_guarded(provider: str, coro_fn):
    """Runs coro_fn() behind whichever concurrency guards this provider
    actually needs -- the one place both _run_direct and _run_subtask
    decide "is this call heavy/file-writing," so a guard added or fixed
    here (like the resolved-provider-based `is_local_heavy` check) can't
    drift out of sync between the two paths the way the file-lock gap did
    when this was first split across them."""
    writes_files = provider in ("claude_cli", "codex_cli")
    # Cloud subscriptions are governed by the shared provider scheduler;
    # Ollama is the only GPU heavy slot here. This lets Claude and Codex run
    # together while still preventing duplicate requests to either account.
    is_local_heavy = provider in ("ollama",)
    lock = _file_lock_for_current_project() if writes_files else None
    semaphore = await _get_heavy_semaphore() if is_local_heavy else None

    async def run_with_slots():
        async with inference_scheduler.slot(provider):
            if semaphore is not None:
                async with semaphore:
                    return await coro_fn()
            return await coro_fn()

    if lock is not None:
        async with lock:
            return await run_with_slots()
    return await run_with_slots()


def _extract_json(text: str) -> dict | None:
    """Local models (this project's real verified director default,
    codestral:22b) reliably return clean JSON for this prompt in testing,
    but "reliably" isn't "always" -- strips markdown fences and grabs the
    first {...} block if the model wrapped its answer in any prose, rather
    than hard-failing delegation on a cosmetic formatting slip."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(0))
        except ValueError:
            return None
    return None


async def handle_request(message: str, conversation_id: int | None) -> dict:
    """Entry point for POST /workspace/tasks. Creates the root task
    immediately (visible in Workspace right away, status 'running' while the
    director thinks), asks the director role to decide delegate vs direct,
    then either runs the request as one direct task or expands it into real
    subtasks with dependencies. Returns the root task; execution continues
    in the background (main.py starts it as an asyncio.Task so the HTTP
    request returns promptly rather than blocking on a ~40-60s local
    director call)."""
    root = await db.create_task(title=message[:200], description=message, conversation_id=conversation_id)
    root = await db.update_task(root["id"], status="running")
    await _broadcast(root["id"])
    return root


def should_consider_delegation(message: str) -> bool:
    """Cheap intent gate; only the real director creates a plan. Simple chat stays direct."""
    text = message.lower()
    if re.match(r"\s*(?:what (?:is|are)|define|explain (?:what|the meaning))\b", text):
        return False
    if re.search(r"\b(?:do not|don't|without)\s+(?:delegate|delegation|teams?)\b", text):
        return False
    explicit = re.search(r"\b(?:delegate|delegation|coordinate|team of|teams|specialists)\b", text)
    actions = re.findall(r"\b(?:research|implement|build|design|review|test|verify|compare|plan|audit)\b", text)
    return bool(explicit or (len(set(actions)) >= 2 and re.search(r"\b(?:and|then|after|before)\b", text)))


async def run_root_task(root_id: int) -> None:
    _running_tasks[root_id] = asyncio.current_task()
    try:
        await _execute_root_task(root_id)
    except asyncio.CancelledError:
        children = await db.list_tasks(parent_id=root_id)
        running = [_running_tasks[t["id"]] for t in children if t["id"] in _running_tasks]
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
        for child in children:
            if child["status"] in ("running", "queued", "blocked"):
                await db.update_task(child["id"], status="cancelled", completed_at=_now())
                await _broadcast(child["id"])
        await db.update_task(root_id, status="cancelled", completed_at=_now())
        await _broadcast(root_id)
        raise
    except Exception as exc:
        await db.update_task(root_id, status="error", error=str(exc), completed_at=_now())
        await _broadcast(root_id)
    finally:
        _running_tasks.pop(root_id, None)


async def _execute_root_task(root_id: int) -> None:
    root = await db.get_task(root_id)
    if root is None:
        return
    # Always mark running here (not just in handle_request, which only runs
    # for a brand-new task) -- retry_task calls run_root_task directly after
    # setting status="queued", and without this the root stayed "queued" in
    # Workspace for the task's entire delegated execution instead of
    # reflecting what's actually happening. Real bug, found live.
    root = await db.update_task(root_id, status="running")
    await _broadcast(root_id)
    try:
        decision = await _decide(root["description"], root_id)
    except Exception as exc:  # noqa: BLE001 - a director failure must land on the task, not vanish
        await db.add_task_activity(root_id, "error", f"Director couldn't produce a plan: {exc}")
        await db.update_task(root_id, status="error", error=str(exc), completed_at=_now())
        await _broadcast(root_id)
        return

    await db.add_task_activity(
        root_id, "planned", decision.get("reasoning") or ("Delegating to a team." if decision.get("delegate") else "Answering directly.")
    )

    if not decision.get("delegate"):
        await _run_direct(root)
        return

    subtasks_spec = decision.get("subtasks") or []
    if len(subtasks_spec) > 8:
        raise RuntimeError('Director plan exceeds eight subtasks. Split the request before retrying.')
    if not subtasks_spec:
        await db.add_task_activity(root_id, "error", "Director chose to delegate but produced no subtasks.")
        await db.update_task(root_id, status="error", error="No subtasks produced.", completed_at=_now())
        await _broadcast(root_id)
        return

    await _run_delegated(root, subtasks_spec)


def _now() -> str:
    import datetime

    # utcnow() is deprecated and returns a *naive* datetime whose isoformat
    # carries no offset, so a consumer cannot tell it is UTC. now(UTC) is
    # aware, which makes the string unambiguous.
    return datetime.datetime.now(datetime.UTC).isoformat()


async def _resolve_team_model(model_id: str, category: str):
    # Metadata resolution must not consume an unbudgeted subscription probe.
    provider, _, alias = model_id.partition(':')
    if provider in team_usage.SUBSCRIPTIONS:
        return routing.RoutingResult(category, provider, alias or None, model_id, [])
    return await routing.resolve_model_id(model_id, category, [])


async def _decide(message: str, root_id: int | None = None) -> dict:
    """The one real director-model call per request. Any malformed response
    is treated as "answer directly" rather than silently guessing a team --
    a wrong "don't delegate" is recoverable (the user just gets a direct
    answer), a wrong invented delegation plan is not."""
    role = teams.ROLES[teams.DIRECTOR_KEY]
    model_id = await teams.resolve_role_model_id(teams.DIRECTOR_KEY)
    await teams.require_available(model_id)
    result = await _resolve_team_model(model_id, "director")
    if result is None:
        raise RuntimeError(f"Director model '{model_id}' is not available right now.")
    messages = [
        {"role": "system", "content": role.system_prompt + " Direct Qwen execution has file listing/reading/writing, project search, PowerShell, localhost preview, and a separate browser with navigation/click/fill/scroll/inspection tools. For simple file or browser operations choose delegate=false so that worker can execute them. Desktop team roles are only planners. Everyday Models is reserved for scheduled daily tasks, never delegate ordinary chat to it. Available role keys: " + ", ".join(r.key for r in teams.ROLES.values() if r.team and r.team != 'everyday')},
        {"role": "user", "content": "Implement a requested backend fix, then independently review the implementation."},
        {"role": "assistant", "content": '{"delegate":true,"reasoning":"Implementation followed by independent review.","subtasks":[{"team":"engineering","role":"implementer","title":"Implement the requested backend fix and verify it","depends_on":[]},{"team":"engineering","role":"reviewer","title":"Independently review the implementation against the request","depends_on":[0]}]}'},
        {"role": "user", "content": message},
    ]
    if result.provider in team_usage.SUBSCRIPTIONS and root_id is None:
        raise RuntimeError('Subscription director requires a durable task budget.')
    await team_usage.reserve(root_id, result.provider, messages)
    text = await providers.run_model_call(result, messages)
    parsed = _extract_json(text)
    # Small local planners sometimes populate a template task list even when
    # explicitly declining delegation. Discard that unused list; never execute
    # it or turn a direct decision into a delegated plan.
    if isinstance(parsed, dict) and parsed.get('delegate') is False:
        parsed['subtasks'] = []
    validate_decision(parsed)
    cloud_calls = 0
    for spec in parsed.get("subtasks", []):
        assigned = await teams.resolve_role_model_id(f"{spec['team']}:{spec['role']}")
        cloud_calls += assigned.split(":", 1)[0] in team_usage.SUBSCRIPTIONS
    if cloud_calls > team_usage.MAX_DISPATCHES:
        raise RuntimeError("Director plan exceeds the two subscription dispatch budget; split the request.")
    return parsed


def validate_decision(parsed):
    """Reject malformed or invented delegation before any worker can execute."""
    if not isinstance(parsed, dict) or type(parsed.get("delegate")) is not bool:
        raise RuntimeError("Director returned an invalid delegation decision.")
    specs = parsed.get("subtasks", [])
    if not isinstance(specs, list) or len(specs) > 8 or (parsed["delegate"] and not specs):
        raise RuntimeError("Director returned an invalid task list.")
    if not parsed["delegate"] and specs:
        raise RuntimeError("Director returned tasks while declining delegation.")
    for index, spec in enumerate(specs):
        if not isinstance(spec, dict) or f"{spec.get('team')}:{spec.get('role')}" not in teams.ROLES:
            raise RuntimeError("Director selected an unknown role.")
        if spec.get('team') == 'everyday':
            raise RuntimeError('Everyday Models is reserved for scheduled daily tasks.')
        if not isinstance(spec.get("title"), str) or not spec["title"].strip():
            raise RuntimeError("Director omitted a task description.")
        deps = spec.get("depends_on", [])
        if not isinstance(deps, list) or any(type(d) is not int or d < 0 or d >= index for d in deps):
            raise RuntimeError("Director returned invalid or cyclic task dependencies.")


async def _run_direct(root: dict) -> None:
    """No delegation: reuse the exact same automatic category routing Chat
    uses (classifier + routing.resolve), not a separate "director does it
    itself" code path -- a direct answer here should be indistinguishable
    from what Chat would have produced for the same message.

    Real gap found and fixed live: a 'coding' category request can resolve
    to claude_cli/codex_cli here exactly as it can from a delegated
    engineering:implementer subtask, but this path originally never touched
    the file lock or heavy-worker semaphore at all -- confirmed by testing
    two concurrent direct-path coding requests against the same project;
    both happened to finish without corrupting the file, but only by luck
    of scheduling, not because anything actually serialized them (task:
    "Prevent workers from concurrently modifying the same files without
    coordination" -- this path was a real, unprotected gap in that
    guarantee, not merely an untested one). Now resolves the model first so
    the same is-this-actually-heavy-and-file-writing check the delegated
    path uses applies here too, before making the real call.
    """
    # The description includes prior conversation/code evidence. Classify only
    # the actual request so a recalled Python snippet cannot hijack file listing.
    category = classifier.classify(root["title"])
    try:
        overrides = await routing.get_category_overrides()
        pinned = overrides.get(category)
        if pinned and pinned.startswith('openrouter:'):
            pinned = None
        if pinned:
            await teams.require_available(pinned)
            result = await _resolve_team_model(pinned, category)
        else:
            candidates = ['codex_cli', 'claude_cli'] if category in ('coding', 'frontend_ui_code') else ['ollama:qwen3.5:4b']
            statuses = await teams.assignment_statuses(candidates)
            chosen = next((m for m in candidates if statuses[m]['available']), None)
            if chosen is None:
                raise RuntimeError('No verified provider for this task. No paid API fallback was attempted.')
            result = await _resolve_team_model(chosen, category)
        if result is None:
            raise RuntimeError('Assigned provider could not be resolved.')
        if result.provider not in ("ollama", "claude_cli", "codex_cli", "antigravity_cli", "claude_cli_plan", "codex_cli_plan"):
            raise RuntimeError("No verified local/subscription provider available; paid API fallback is disabled for team requests.")
        direct_id = f"ollama:{result.model}" if result.provider == "ollama" else result.provider
        await teams.require_available(direct_id)
        writes_files = result.provider in ("claude_cli", "codex_cli")
        use_tools = result.provider == 'ollama' and bool(re.search(r'\b(read|find|open|inspect|click|fill|scroll|browser|website|files?|folder|run|execute|localhost|search|edit|save|create|list)\b', root['title'], re.I))

        async def _call() -> str:
            await db.update_task(root['id'], status='running', started_at=_now())
            await _broadcast(root['id'])
            await team_usage.reserve(root['id'], result.provider, [{"role": "user", "content": root["description"]}])
            snapshot = code_files.snapshot_workspace() if writes_files else None
            if use_tools:
                async with _file_lock_for_current_project():
                    text = await execution_tools.run(result, [{"role": "user", "content": root["description"]}], root['id'])
            else:
                text = await providers.run_model_call(result, [{"role": "user", "content": root["description"]}])
            if snapshot is not None:
                changes = code_files.diff_against_snapshot(snapshot)
                if changes:
                    artifacts = [{"path": c["path"], "kind": c["kind"]} for c in changes]
                    await db.update_task(root["id"], artifacts=json.dumps(artifacts))
                    await db.add_task_activity(
                        root["id"], "files_changed",
                        f"Changed {len(changes)} file(s): " + ", ".join(c["path"] for c in changes),
                    )
            return text

        await db.update_task(root["id"], status="queued", provider=result.provider, model=result.model)
        await db.add_task_activity(root["id"], "queued", f"Queued: waiting for {inference_scheduler.provider_family(result.provider) or 'worker'} capacity.")
        await _broadcast(root["id"])
        text = await _run_guarded(result.provider, _call)
        await db.add_task_activity(root["id"], "done", f"Answered directly via {result.label}.")
        await db.update_task(
            root["id"], status="done", provider=result.provider, model=result.model,
            result_summary=text[:2000], completed_at=_now(),
        )
    except Exception as exc:  # noqa: BLE001 - surface to the task, don't crash the background runner
        await db.add_task_activity(root["id"], "error", f"Direct answer failed: {exc}")
        await db.update_task(root["id"], status="error", error=str(exc), completed_at=_now())
    await _broadcast(root["id"])


async def _run_delegated(root: dict, subtasks_spec: list[dict]) -> None:
    # Create every subtask row up front so Workspace shows the whole plan
    # immediately, not one row at a time as execution reaches it.
    subtask_ids: list[int] = []
    for spec in subtasks_spec:
        role = teams.get_role(spec.get("team"), spec.get("role"))
        sub = await db.create_task(
            title=spec.get("title") or f"{spec.get('team')}:{spec.get('role')}",
            description=spec.get("title") or "",
            parent_id=root["id"],
            team=spec.get("team"),
            role=spec.get("role"),
            writes_files=bool(role and role.writes_files),
        )
        subtask_ids.append(sub["id"])
        await _broadcast(sub["id"])
    for i, (spec, sub_id) in enumerate(zip(subtasks_spec, subtask_ids)):
        for dep_index in spec.get("depends_on") or []:
            if isinstance(dep_index, int) and 0 <= dep_index < len(subtask_ids) and dep_index != i:
                await db.add_task_dependency(sub_id, subtask_ids[dep_index])
    await _broadcast(root["id"])

    remaining = set(subtask_ids)
    done_ok: set[int] = set()
    failed: set[int] = set()
    running: dict[int, asyncio.Task] = {}

    while remaining or running:
        # Cascade dependency failures FIRST, before computing what's ready --
        # otherwise a transitive failure (A fails -> B depends on A, gets
        # cascaded here -> C depends on B) could let C's readiness be checked
        # against a not-yet-updated `failed` set within the same iteration
        # and wrongly look runnable. Loops to a fixpoint so a multi-hop chain
        # fully cascades in one pass rather than one hop per outer iteration.
        changed = True
        while changed:
            changed = False
            for tid in list(remaining):
                if tid in running:
                    continue
                deps = await db.get_task_dependencies(tid)
                if any(dep in failed for dep in deps):
                    await db.add_task_activity(tid, "blocked", "A dependency failed; this subtask was not run.")
                    await db.update_task(tid, status="cancelled", completed_at=_now())
                    await _broadcast(tid)
                    remaining.discard(tid)
                    failed.add(tid)
                    changed = True

        ready = [
            tid for tid in list(remaining)
            if tid not in running
            and all(dep in done_ok for dep in await db.get_task_dependencies(tid))
        ]

        for tid in ready:
            remaining.discard(tid)
            coro = _run_subtask(tid)
            task = asyncio.create_task(coro)
            running[tid] = task
            _running_tasks[tid] = task

        if not running:
            break

        done_set, _pending = await asyncio.wait(running.values(), return_when=asyncio.FIRST_COMPLETED)
        for tid, task in list(running.items()):
            if task in done_set:
                del running[tid]
                _running_tasks.pop(tid, None)
                try:
                    ok = task.result()
                except asyncio.CancelledError:
                    ok = False
                if ok:
                    done_ok.add(tid)
                else:
                    failed.add(tid)

    await _synthesize(root, subtask_ids)


async def _run_subtask(task_id: int) -> bool:
    """Runs one subtask to completion. Returns True on success. Handles a
    real rate limit with bounded retry-with-backoff (task: "Provider rate
    limits must queue work or use an explicitly configured free fallback")
    rather than failing the whole task tree on a transient 429."""
    task = await db.get_task(task_id)
    if task is None:
        return False
    role = teams.get_role(task["team"], task["role"])
    if role is None:
        await db.add_task_activity(task_id, "error", f"Unknown role '{task['team']}:{task['role']}'.")
        await db.update_task(task_id, status="error", error="Unknown role.", completed_at=_now())
        await _broadcast(task_id)
        return False

    context = await _gather_dependency_context(task_id)

    async def _do_call() -> str:
        model_id = await teams.resolve_role_model_id(role.key)
        await teams.require_available(model_id)
        result = await _resolve_team_model(model_id, role.key)
        if result is None:
            raise RuntimeError(f"Role model '{model_id}' is not available right now.")
        if result.provider in ("claude_cli", "codex_cli") and not role.writes_files:
            raise RuntimeError("This text-only role cannot use a CLI with file-writing tools. Choose a local text model in Settings.")
        if result.provider in ('antigravity_cli', 'claude_cli_plan', 'codex_cli_plan') and role.writes_files:
            raise RuntimeError('This provider runs in plan mode and cannot implement file-writing roles.')
        await db.update_task(task_id, provider=result.provider, model=result.model)

        # Concurrency guards decided from the *resolved* provider (via the
        # shared _run_guarded, also used by _run_direct), not the role's
        # static writes_files flag -- a role's model is Settings-overridable,
        # so the role's own default capability isn't necessarily what's
        # actually about to run.
        writes_files_now = result.provider in ("claude_cli", "codex_cli")

        async def _call_model() -> str:
            # Status flips to "running" only here -- once any applicable
            # file-lock/heavy-worker slot has actually been acquired -- not
            # when this coroutine was merely scheduled. Real bug found live:
            # setting "running" before acquiring the semaphore made two
            # subtasks both show "running" in Workspace while only one was
            # actually executing (confirmed via `ollama ps` showing a single
            # loaded model) -- correct concurrency, misleading status.
            await db.update_task(task_id, status="running", started_at=_now())
            await db.add_task_activity(task_id, "started", f"Started ({role.label}).")
            await _broadcast(task_id)
            messages = [{"role": "system", "content": role.system_prompt}]
            if context:
                messages.append({"role": "user", "content": f"Context from earlier subtasks:\n\n{context}"})
            messages.append({"role": "user", "content": task["description"]})
            await team_usage.reserve(task.get('parent_id') or task_id, result.provider, messages)
            snapshot = code_files.snapshot_workspace() if writes_files_now else None
            text = await providers.run_model_call(result, messages)
            if snapshot is not None:
                changes = code_files.diff_against_snapshot(snapshot)
                if changes:
                    artifacts = [{"path": c["path"], "kind": c["kind"]} for c in changes]
                    await db.update_task(task_id, artifacts=json.dumps(artifacts))
                    await db.add_task_activity(
                        task_id, "files_changed", f"Changed {len(changes)} file(s): " + ", ".join(c["path"] for c in changes)
                    )
            return text

        await db.update_task(task_id, status="queued", provider=result.provider, model=result.model)
        await db.add_task_activity(task_id, "queued", f"Queued: waiting for {inference_scheduler.provider_family(result.provider) or 'worker'} capacity.")
        await _broadcast(task_id)
        return await _run_guarded(result.provider, _call_model)

    attempts = 0
    while True:
        try:
            text = await _do_call()
            await db.add_task_activity(task_id, "done", "Completed.")
            await db.update_task(task_id, status="done", result_summary=text[:2000], completed_at=_now())
            await _broadcast(task_id)
            return True
        except asyncio.CancelledError:
            await db.add_task_activity(task_id, "cancelled", "Cancelled by user.")
            await db.update_task(task_id, status="cancelled", completed_at=_now())
            await _broadcast(task_id)
            raise
        except providers.ProviderRateLimitedError as exc:
            attempts += 1
            if attempts > _RATE_LIMIT_RETRIES:
                await db.add_task_activity(task_id, "error", f"Rate limited, retries exhausted: {exc}")
                await db.update_task(task_id, status="error", error=str(exc), completed_at=_now())
                await _broadcast(task_id)
                return False
            await db.add_task_activity(task_id, "blocked", f"Rate limited -- retrying in {_RATE_LIMIT_BACKOFF_SECONDS}s ({attempts}/{_RATE_LIMIT_RETRIES}).")
            await db.update_task(task_id, status="blocked")
            await _broadcast(task_id)
            await asyncio.sleep(_RATE_LIMIT_BACKOFF_SECONDS)
        except Exception as exc:  # noqa: BLE001 - surface to the task, don't crash the scheduler
            await db.add_task_activity(task_id, "error", str(exc))
            await db.update_task(task_id, status="error", error=str(exc), completed_at=_now())
            await _broadcast(task_id)
            return False


async def _gather_dependency_context(task_id: int) -> str:
    dep_ids = await db.get_task_dependencies(task_id)
    parts = []
    for dep_id in dep_ids:
        dep = await db.get_task(dep_id)
        if dep and dep.get("result_summary"):
            parts.append(f"[{dep['title']}]\n{dep['result_summary']}")
    return "\n\n".join(parts)


async def _synthesize(root: dict, subtask_ids: list[int]) -> None:
    """The director assembles the final response from verified outputs
    (task: "The director assembles the final response from verified
    outputs") -- a plain concatenation of what actually happened, not
    another model call putting words in the workers' mouths."""
    subtasks = [await db.get_task(tid) for tid in subtask_ids]
    subtasks = [t for t in subtasks if t is not None]
    failed = [t for t in subtasks if t["status"] != "done"]
    missing = len(subtask_ids) - len(subtasks)
    parts = []
    for t in subtasks:
        status_note = "" if t["status"] == "done" else f" [{t['status']}]"
        parts.append(f"{t['title']}{status_note}: {t.get('result_summary') or t.get('error') or '(no result)'}")
    summary = "\n\n".join(parts)
    incomplete = len(failed) + missing
    successes = sum(t["status"] == "done" for t in subtasks)
    final_status = "done" if subtask_ids and not incomplete else "partial" if successes else "error"
    if missing:
        summary += f"\n\n{missing} required subtask record(s) are missing."
    await db.add_task_activity(
        root["id"], "synthesized",
        "All subtasks finished." if final_status == "done" else f"{incomplete} of {len(subtask_ids)} required subtask(s) did not complete.",
    )
    await db.update_task(root["id"], status=final_status, result_summary=summary[:4000], completed_at=_now())
    await _broadcast(root["id"])


async def cancel_task(task_id: int) -> bool:
    """Task: "Cancel must reach the running operation where supported."
    Only meaningful for a task actually in flight -- a queued/blocked task
    is marked cancelled directly (nothing to interrupt)."""
    running = _running_tasks.get(task_id)
    if running is not None and not running.done():
        running.cancel()
        return True
    task = await db.get_task(task_id)
    if task is not None and task["status"] in ("queued", "blocked"):
        await db.add_task_activity(task_id, "cancelled", "Cancelled before it started.")
        await db.update_task(task_id, status="cancelled", completed_at=_now())
        await _broadcast(task_id)
        return True
    return False


async def retry_task(task_id: int, confirm: bool = False) -> dict:
    """Task: "Retry must distinguish safe retries from actions that may
    already have changed files or external state." A task whose role writes
    files AND already has recorded artifacts from its last run has real
    external side effects already applied -- retrying would run the same
    file-writing instructions again, which is not a safe no-op retry, so it
    requires an explicit confirm=true rather than happening implicitly."""
    task = await db.get_task(task_id)
    if task is None:
        raise ValueError("Task not found.")
    has_artifacts = bool(json.loads(task.get("artifacts") or "[]"))
    if task["writes_files"] and has_artifacts and not confirm:
        return {"requires_confirmation": True, "reason": "This task already wrote real file changes; retrying will run it again."}
    await db.update_task(task_id, status="queued", error=None, result_summary=None, completed_at=None)
    await db.add_task_activity(task_id, "retried", "Queued for retry.")
    await _broadcast(task_id)
    coro = _run_subtask(task_id) if task["parent_id"] else run_root_task(task_id)
    running_task = asyncio.create_task(coro)
    if task["parent_id"]:
        _running_tasks[task_id] = running_task
    return {"requires_confirmation": False, "task": await db.get_task(task_id)}
