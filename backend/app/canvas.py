"""Canvas LMS client.

Two ways in, because one of them is not always available:

  * **REST API with a personal access token** (this module). The richer source:
    it knows points, full descriptions, and crucially whether something has
    already been submitted. Tokens are issued by the user from their own account
    (Account -> Settings -> New Access Token) and keep working regardless of SSO.
  * **The per-user Calendar Feed** (`canvas_feed.py`). Many institutions disable
    student access-token generation entirely, which makes the API path
    impossible no matter how it is configured. The feed needs no token and no
    admin permission, at the cost of submission state and points.

`assignments()` below picks whichever is configured, preferring the API. Either
way the rows come back in one shape, so the nightly sync, the dedupe, and the
tools do not care which door was used.

Neither path is driven through a scraped browser session: a job that runs
unattended at 11:59pm cannot depend on an SSO cookie that expires on its own
schedule and fails silently.

Read-only. Nothing here submits, uploads, or posts — it lists courses and
assignments and reads due dates.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import httpx
from dotenv import set_key

from . import config

TIMEOUT = 30
PAGE_LIMIT = 10  # safety bound on Link-header pagination


class CanvasError(RuntimeError):
    """Configuration or API failure, phrased for display."""


def base_url() -> str | None:
    raw = os.getenv("CANVAS_BASE_URL", "").strip().rstrip("/")
    if not raw:
        return None
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    return raw


def access_token() -> str | None:
    return os.getenv("CANVAS_ACCESS_TOKEN", "").strip() or None


def configured() -> bool:
    return bool(base_url() and access_token())


def update_credentials(url: str | None = None, token: str | None = None) -> dict:
    """Persist to the same .env the other provider keys live in."""
    if url and url.strip():
        cleaned = url.strip().rstrip("/")
        set_key(str(config.ENV_PATH), "CANVAS_BASE_URL", cleaned)
        os.environ["CANVAS_BASE_URL"] = cleaned
    if token and token.strip():
        set_key(str(config.ENV_PATH), "CANVAS_ACCESS_TOKEN", token.strip())
        os.environ["CANVAS_ACCESS_TOKEN"] = token.strip()
    return status()


def source() -> str:
    """Which door is usable right now: "api", "feed", or "none"."""
    from . import canvas_feed

    if configured():
        return "api"
    return "feed" if canvas_feed.configured() else "none"


def any_configured() -> bool:
    return source() != "none"


def status() -> dict:
    from . import canvas_feed

    return {
        "configured": configured(),
        "base_url": base_url(),
        "token_set": bool(access_token()),
        "source": source(),
        "any_configured": any_configured(),
        "feed": canvas_feed.status(),
    }


async def _get(client: httpx.AsyncClient, path: str, **params) -> list[dict]:
    """GET one Canvas collection, following Link-header pagination."""
    url = f"{base_url()}/api/v1/{path.lstrip('/')}"
    collected: list[dict] = []
    for _ in range(PAGE_LIMIT):
        response = await client.get(url, params=params or None)
        if response.status_code == 401:
            raise CanvasError(
                "Canvas rejected the access token (401). Generate a new one at "
                "Account -> Settings -> New Access Token and re-save it in Settings -> Canvas."
            )
        if response.status_code == 404:
            raise CanvasError(f"Canvas returned 404 for {path} — check the Canvas URL in Settings.")
        response.raise_for_status()
        page = response.json()
        if isinstance(page, dict):
            return [page]
        collected.extend(page)
        nxt = response.links.get("next", {}).get("url")
        if not nxt:
            break
        url, params = nxt, None
    return collected


async def _client() -> httpx.AsyncClient:
    if not configured():
        raise CanvasError(
            "Canvas isn't set up yet. Add your Canvas URL and an access token in Settings -> Canvas."
        )
    return httpx.AsyncClient(
        timeout=TIMEOUT,
        headers={"Authorization": f"Bearer {access_token()}", "Accept": "application/json"},
        follow_redirects=True,
    )


async def list_courses() -> list[dict]:
    async with await _client() as client:
        rows = await _get(client, "courses", enrollment_state="active", per_page=100)
    return [
        {"id": row["id"], "name": row.get("name") or f"Course {row['id']}",
         "code": row.get("course_code") or ""}
        for row in rows
        if isinstance(row, dict) and row.get("id") and not row.get("access_restricted_by_date")
    ]


def _parse_due(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


async def list_assignments(include_undated: bool = False) -> list[dict]:
    """Every assignment across active courses, normalised.

    Canvas exposes `submitted` per-assignment only via the submission
    sub-object, which `include[]=submission` attaches in the same request --
    one call per course instead of two, and it is what lets the nightly job
    skip things already handed in.
    """
    courses = await list_courses()
    if not courses:
        return []

    async with await _client() as client:
        async def for_course(course: dict) -> list[dict]:
            try:
                rows = await _get(
                    client, f"courses/{course['id']}/assignments",
                    per_page=100, order_by="due_at", **{"include[]": "submission"},
                )
            except Exception:  # noqa: BLE001 - one unreadable course must not sink the run
                return []
            out = []
            for row in rows:
                if not isinstance(row, dict) or not row.get("id"):
                    continue
                due = _parse_due(row.get("due_at"))
                if due is None and not include_undated:
                    continue
                submission = row.get("submission") or {}
                out.append({
                    "canvas_id": str(row["id"]),
                    "course_id": str(course["id"]),
                    "course_name": course["name"],
                    "title": (row.get("name") or "Untitled assignment").strip(),
                    "due_at": due.isoformat() if due else None,
                    "points": row.get("points_possible"),
                    "url": row.get("html_url") or "",
                    "description": (row.get("description") or "")[:4000],
                    "submitted": bool(submission.get("submitted_at")) or bool(submission.get("workflow_state") == "graded"),
                })
            return out

        results = await asyncio.gather(*(for_course(c) for c in courses), return_exceptions=True)

    assignments: list[dict] = []
    for result in results:
        if isinstance(result, list):
            assignments.extend(result)
    assignments.sort(key=lambda a: a["due_at"] or "9999")
    return assignments


async def assignments() -> list[dict]:
    """Every assignment, from whichever source is configured.

    The API is preferred when a token exists because only it reports submission
    state; the feed is the fallback for institutions that block tokens.
    """
    from . import canvas_feed

    picked = source()
    if picked == "api":
        return await list_assignments()
    if picked == "feed":
        return await canvas_feed.fetch()
    raise CanvasError(
        "Canvas isn't set up yet. In Settings -> Canvas either add an access token, or — if "
        "your school blocks those — paste your Canvas calendar feed link (Canvas -> Calendar "
        "-> \"Calendar Feed\")."
    )


async def upcoming(days: int = 14, include_submitted: bool = False) -> list[dict]:
    """Assignments due between now and `days` out."""
    now = datetime.now(timezone.utc)
    horizon = now.timestamp() + days * 86400
    rows = []
    for item in await assignments():
        due = _parse_due(item["due_at"])
        if due is None:
            continue
        if not include_submitted and item["submitted"]:
            continue
        if now.timestamp() <= due.timestamp() <= horizon:
            rows.append(item)
    return rows
