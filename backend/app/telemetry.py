"""Bounded local request timings; no messages, audio, or credentials."""
from collections import deque
import time
from uuid import uuid4

_recent = deque(maxlen=200)
_active = {}


class RequestTimings:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") not in {"/chat", "/tts", "/tts/summarize", "/stt/transcribe", "/workspace/tasks"}:
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        record = {"id": uuid4().hex, "path": scope["path"], "method": scope["method"], "status": None, "first_body_ms": None}
        _active[record["id"]] = {"path": scope["path"], "started": started}
        async def timed_send(message):
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            if message["type"] == "http.response.start":
                record["status"] = message["status"]
                record["headers_ms"] = elapsed
                message = {**message, "headers": [*message.get("headers", []), (b"x-nova-request-id", record["id"].encode())]}
            elif message["type"] == "http.response.body" and message.get("body") and record["first_body_ms"] is None:
                record["first_body_ms"] = elapsed
            await send(message)
        try:
            await self.app(scope, receive, timed_send)
        except BaseException as exc:
            record["error_type"] = type(exc).__name__
            try:
                from . import sentinel
                sentinel.record_error(scope.get("path", "http"), exc)
            except Exception:
                pass
            raise

        finally:
            record["total_ms"] = round((time.perf_counter() - started) * 1000, 1)
            _active.pop(record["id"], None)
            _recent.append(record)


def snapshot():
    now = time.perf_counter()
    return {"recent": list(_recent), "active": [{"id": key, "path": value["path"], "elapsed_ms": round((now-value["started"])*1000)} for key, value in _active.items()]}
