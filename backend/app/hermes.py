"""Lazy persistent Hermes ACP process, using Nova's bounded local inference."""
import asyncio
from collections import deque
import json
import os
from pathlib import Path
import secrets
import hashlib
import shutil

from . import config, db

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv-hermes" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
HOME = ROOT / ".hermes"
TOKEN = secrets.token_hex(24)
_process = None
_reader = None
_stderr = None
_pending = {}
_next_id = 0
_start_lock = asyncio.Lock()
_turn_lock = asyncio.Lock()
_sessions = {}
_updates = {}
_events = deque(maxlen=40)


def status():
    return {"installed": PYTHON.exists(), "running": _process is not None and _process.returncode is None,
            "model": "qwen3.5:4b", "provider": "Nova local queue", "sessions": len(_sessions), "events": list(_events)}


async def _send(payload):
    _process.stdin.write((json.dumps({"jsonrpc": "2.0", **payload}) + "\n").encode())
    await _process.stdin.drain()


async def _rpc(method, params, timeout=45):
    global _next_id
    _next_id += 1
    request_id = _next_id
    future = asyncio.get_running_loop().create_future()
    _pending[request_id] = future
    try:
        await _send({"id": request_id, "method": method, "params": params})
        return await asyncio.wait_for(future, timeout)
    finally:
        _pending.pop(request_id, None)


async def _read():
    try:
        while line := await _process.stdout.readline():
            message = json.loads(line)
            if "method" not in message and message.get("id") in _pending:
                future = _pending[message["id"]]
                if not future.done():
                    if "error" in message:
                        future.set_exception(RuntimeError(str(message["error"].get("message", "Hermes failed"))))
                    else:
                        future.set_result(message.get("result", {}))
            elif message.get("method") == "session/update":
                params = message.get("params", {})
                update = params.get("update", {})
                queue = _updates.get(params.get("sessionId"))
                if queue:
                    await queue.put(update)
                if update.get("sessionUpdate") in ("tool_call", "tool_call_update"):
                    _events.append({"type": update.get("sessionUpdate"), "title": update.get("title"), "status": update.get("status")})
            elif "method" in message and "id" in message:
                # ACP permission prompts are surfaced as a refusal. Nova's
                # conversation stream reports this; never hang awaiting stdin.
                if message["method"] == "session/request_permission":
                    await _send({"id": message["id"], "result": {"outcome": {"outcome": "cancelled"}}})
                else:
                    await _send({"id": message["id"], "error": {"code": -32601, "message": "Host capability unavailable"}})
    except Exception as exc:
        _events.append({"type": "connection_error", "message": str(exc)[:160]})
    finally:
        for future in list(_pending.values()):
            if not future.done():
                future.set_exception(RuntimeError("Hermes ACP connection closed"))


async def _drain_stderr():
    while line := await _process.stderr.readline():
        text = line.decode(errors="replace").strip().replace(TOKEN, "[redacted]")
        if text and any(level in text for level in ("[WARNING]", "[ERROR]")):
            _events.append({"type": "runtime", "message": text[-400:]})


async def start():
    global _process, _reader, _stderr
    async with _start_lock:
        if _process and _process.returncode is None:
            return
        if not PYTHON.exists():
            raise RuntimeError("Hermes runtime is not installed")
        HOME.mkdir(parents=True, exist_ok=True)
        settings = {"model": {"default": "qwen3.5:4b", "provider": "nova-local", "context_length": 65536},
                    "custom_providers": [{"name": "nova-local", "base_url": "http://127.0.0.1:8000/hermes/v1", "api_key": TOKEN, "model": "qwen3.5:4b", "api_mode": "chat_completions"}],
                    "agent": {"max_turns": 6}, "mcp_servers": {}}
        (HOME / "config.yaml").write_text(json.dumps(settings, indent=2), encoding="utf-8")
        env = {key: value for key, value in os.environ.items() if not key.upper().endswith(("API_KEY", "ACCESS_TOKEN"))}
        env.update(HERMES_HOME=str(HOME), HERMES_ACP_SKIP_CONFIGURED_MCP="1", PYTHONUTF8="1")
        git = shutil.which("git")
        if git and not env.get("HERMES_GIT_BASH_PATH"):
            bash = Path(git).resolve().parents[1] / "bin" / "bash.exe"
            if bash.exists():
                env["HERMES_GIT_BASH_PATH"] = str(bash)
        _process = await asyncio.create_subprocess_exec(str(PYTHON), str(ROOT / "hermes_entry.py"), cwd=str(config.get_workspace_dir()), env=env,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=2**20)
        _sessions.clear()
        _reader = asyncio.create_task(_read())
        _stderr = asyncio.create_task(_drain_stderr())
        try:
            await _rpc("initialize", {"protocolVersion": 1, "clientInfo": {"name": "Nova", "version": "0.2.0"}, "clientCapabilities": {}})
        except BaseException:
            await stop()
            raise


async def stream(messages, session_key=None):
    async with _turn_lock:
        await start()
        workspace = str(config.get_workspace_dir().resolve())
        key = hashlib.sha256(f"{workspace}:{session_key}".encode()).hexdigest() if session_key else secrets.token_hex(8)
        if key not in _sessions:
            saved = (await db.get_app_settings()).get(f"hermes_session:{key}") if session_key else None
            if saved:
                try:
                    await _rpc("session/load", {"sessionId": saved, "cwd": str(config.get_workspace_dir()), "mcpServers": []})
                    _sessions[key] = saved
                except RuntimeError:
                    saved = None
            if not saved:
                result = await _rpc("session/new", {"cwd": str(config.get_workspace_dir()), "mcpServers": []})
                _sessions[key] = result["sessionId"]
                if session_key:
                    await db.set_app_settings({f"hermes_session:{key}": result["sessionId"]})
        session_id = _sessions[key]
        await _rpc("session/set_mode", {"sessionId": session_id, "modeId": "accept_edits"})
        queue = asyncio.Queue()
        _updates[session_id] = queue
        text = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
        if not session_key and len(messages) > 1:
            text = "Conversation context (follow the latest user request):\n" + json.dumps(messages, ensure_ascii=False)
        prompt = asyncio.create_task(_rpc("session/prompt", {"sessionId": session_id, "prompt": [{"type": "text", "text": str(text)}]}, timeout=180))
        completed = False
        try:
            while not prompt.done() or not queue.empty():
                try:
                    update = await asyncio.wait_for(queue.get(), .1)
                except asyncio.TimeoutError:
                    continue
                if update.get("sessionUpdate") == "agent_message_chunk":
                    content = update.get("content", {})
                    if content.get("type") == "text":
                        yield content.get("text", "")
            result = await prompt
            completed = True
            if result.get("stopReason") in ("refusal", "cancelled"):
                raise RuntimeError(f"Hermes turn stopped: {result['stopReason']}")
        finally:
            _updates.pop(session_id, None)
            if not completed:
                # A timed-out RPC can still have an active agent turn. End the
                # owned process before releasing the serial turn lease.
                await stop()
                prompt.cancel()
                await asyncio.gather(prompt, return_exceptions=True)


async def stop():
    global _process
    if _process and _process.returncode is None:
        _process.terminate()
        await _process.wait()
    for task in (_reader, _stderr):
        if task:
            task.cancel()
    await asyncio.gather(*[t for t in (_reader, _stderr) if t], return_exceptions=True)
    _process = None
