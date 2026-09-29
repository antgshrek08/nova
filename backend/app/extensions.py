"""Extension management for N.O.V.A. (Plan §8: User-directed changes).

Manages installable extensions with full lifecycle: install → disable → remove
→ restore, manifest validation, dependency enforcement, file ownership, data
persistence, version history, and export/import.

Extensions are the mechanism through which users can tell Nova what to add
and Nova can safely deliver it — new tabs, tools, connectors, or complete
features like a grade calculator.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from . import config

# ── Schema ──────────────────────────────────────────────────────────────────

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS extensions (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'active',
    manifest_json TEXT NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS extension_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ext_id TEXT NOT NULL REFERENCES extensions(id),
    version TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(ext_id, version)
);
CREATE TABLE IF NOT EXISTS extension_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ext_id TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_CURRENT_API_VERSION = 1
_ALLOWED_PERMISSIONS = {"storage", "network", "filesystem", "ui"}
_PRIVATE_SUFFIXES = {".env", ".db", ".sqlite", ".key", ".pem"}

# ── DB helpers ──────────────────────────────────────────────────────────────

async def _db() -> aiosqlite.Connection:
    db_path = config.DB_PATH
    conn = await aiosqlite.connect(str(db_path))
    conn.row_factory = aiosqlite.Row
    await conn.executescript(_SCHEMA)
    return conn


async def _record(conn: aiosqlite.Connection, ext_id: str, action: str, detail: str = ""):
    await conn.execute(
        "INSERT INTO extension_history (ext_id, action, detail) VALUES (?, ?, ?)",
        (ext_id, action, detail),
    )


# ── Manifest validation ────────────────────────────────────────────────────

def _validate_manifest(m: dict) -> None:
    """Reject manifests that violate safety or versioning rules."""
    required = {"schema_version", "id", "title", "version", "owner", "kind",
                "compatibility", "permissions", "dependencies", "owned_files",
                "data_migrations"}
    missing = required - set(m.keys())
    if missing:
        raise ValueError(f"Manifest missing required fields: {missing}")

    if m.get("schema_version") != 1:
        raise ValueError("Only schema_version 1 is supported.")

    api = (m.get("compatibility") or {}).get("api")
    if api is not None and api != _CURRENT_API_VERSION:
        raise ValueError(f"Incompatible API version {api}; expected {_CURRENT_API_VERSION}.")

    v = m.get("version", "")
    if not v or v == "latest":
        raise ValueError("Version must be a concrete semver string, not 'latest'.")

    bad_perms = set(m.get("permissions", [])) - _ALLOWED_PERMISSIONS
    if bad_perms:
        raise ValueError(f"Unknown/disallowed permissions: {bad_perms}")

    for f in m.get("owned_files", []):
        if ".." in f or f.startswith("/"):
            raise ValueError(f"owned_files path escapes project: {f}")

    for mig in m.get("data_migrations", []):
        sql = (mig.get("sql") or "").upper()
        if any(kw in sql for kw in ("DROP", "TRUNCATE", "ALTER")):
            raise ValueError(f"Destructive migration disallowed: {mig.get('sql', '')[:80]}")


# ── Core lifecycle ──────────────────────────────────────────────────────────

async def manage(action: str, **kwargs) -> dict:
    """Single entry point for extension lifecycle actions."""
    handlers = {
        "install": _install,
        "disable": _disable,
        "remove": _remove,
        "restore": _restore,
        "export": _export,
        "history": _history,
        "list": _list,
        "get": _get,
    }
    handler = handlers.get(action)
    if not handler:
        raise ValueError(f"Unknown action: {action}")
    return await handler(**kwargs)


async def _install(manifest: dict, **_) -> dict:
    _validate_manifest(manifest)
    ext_id = manifest["id"]
    conn = await _db()
    try:
        # Check file ownership conflicts against other extensions' current manifests
        owners = await _file_owners(conn, exclude=ext_id)
        for f in manifest.get("owned_files", []):
            owner = owners.get(_norm_path(f))
            if owner:
                raise ValueError(f"File '{f}' is already owned by extension '{owner}'.")

        cursor = await conn.execute("SELECT * FROM extensions WHERE id = ?", (ext_id,))
        existing = await cursor.fetchone()

        if existing:
            ex_manifest = json.loads(existing["manifest_json"])
            # Owner cannot change
            if manifest["owner"] != ex_manifest["owner"]:
                raise ValueError(f"Extension owner cannot be changed (current: {ex_manifest['owner']}).")
            # Same version must be identical (immutable release)
            if manifest["version"] == ex_manifest["version"]:
                if manifest != ex_manifest:
                    raise ValueError("Cannot change an already-published version (immutable).")
                return {"extension": _row_to_dict(existing), "action": "unchanged"}

            # Check if dependents would break with a new major version
            await _check_dependents_compat(conn, ext_id, manifest["version"])

            await conn.execute(
                "UPDATE extensions SET manifest_json = ?, updated_at = datetime('now') WHERE id = ?",
                (json.dumps(manifest), ext_id),
            )
        else:
            await conn.execute(
                "INSERT INTO extensions (id, owner, state, manifest_json) VALUES (?, ?, 'active', ?)",
                (ext_id, manifest["owner"], json.dumps(manifest)),
            )

        # Record version
        await conn.execute(
            "INSERT OR IGNORE INTO extension_versions (ext_id, version, manifest_json) VALUES (?, ?, ?)",
            (ext_id, manifest["version"], json.dumps(manifest)),
        )
        await _record(conn, ext_id, "install", f"v{manifest['version']}")
        await conn.commit()

        cursor = await conn.execute("SELECT * FROM extensions WHERE id = ?", (ext_id,))
        row = await cursor.fetchone()
        return {"extension": _row_to_dict(row), "action": "installed"}
    finally:
        await conn.close()


async def _disable(id: str, **_) -> dict:
    conn = await _db()
    try:
        await _require(conn, id)
        await _check_dependents_active(conn, id)
        await conn.execute(
            "UPDATE extensions SET state = 'disabled', updated_at = datetime('now') WHERE id = ?",
            (id,),
        )
        await _record(conn, id, "disable")
        await conn.commit()
        cursor = await conn.execute("SELECT * FROM extensions WHERE id = ?", (id,))
        row = await cursor.fetchone()
        return {"extension": _row_to_dict(row)}
    finally:
        await conn.close()


async def _remove(id: str, **_) -> dict:
    conn = await _db()
    try:
        await _require(conn, id)
        await _check_dependents_active(conn, id)
        await conn.execute(
            "UPDATE extensions SET state = 'removed', updated_at = datetime('now') WHERE id = ?",
            (id,),
        )
        await _record(conn, id, "remove")
        await conn.commit()
        return {"removed": True}
    finally:
        await conn.close()


async def _restore(id: str, version: str | None = None, **_) -> dict:
    conn = await _db()
    try:
        await _require(conn, id)
        if version:
            cursor = await conn.execute(
                "SELECT manifest_json FROM extension_versions WHERE ext_id = ? AND version = ?",
                (id, version),
            )
            ver_row = await cursor.fetchone()
            if not ver_row:
                raise ValueError(f"Extension '{id}' has no recorded version {version}.")
            manifest = json.loads(ver_row["manifest_json"])
            owners = await _file_owners(conn, exclude=id)
            for f in manifest.get("owned_files", []):
                if _norm_path(f) in owners:
                    raise ValueError(f"File '{f}' is now owned by extension '{owners[_norm_path(f)]}'.")
            await conn.execute(
                "UPDATE extensions SET state = 'active', manifest_json = ?, updated_at = datetime('now') WHERE id = ?",
                (json.dumps(manifest), id),
            )
        else:
            await conn.execute(
                "UPDATE extensions SET state = 'active', updated_at = datetime('now') WHERE id = ?",
                (id,),
            )
        await _record(conn, id, "restore", f"v{version}" if version else "")
        await conn.commit()
        cursor = await conn.execute("SELECT * FROM extensions WHERE id = ?", (id,))
        row = await cursor.fetchone()
        return {"extension": _row_to_dict(row)}
    finally:
        await conn.close()


async def _export(id: str, include_data: bool = False, **_) -> dict:
    conn = await _db()
    try:
        cursor = await conn.execute("SELECT * FROM extensions WHERE id = ?", (id,))
        row = await cursor.fetchone()
        if not row:
            raise ValueError(f"Extension '{id}' not found.")

        cursor = await conn.execute(
            "SELECT version, manifest_json FROM extension_versions WHERE ext_id = ? ORDER BY created_at",
            (id,),
        )
        versions = [{"version": r["version"], "manifest": json.loads(r["manifest_json"])}
                     for r in await cursor.fetchall()]

        export = {
            "id": id,
            "manifest": json.loads(row["manifest_json"]),
            "versions": versions,
        }
        if include_data:
            export["data"] = json.loads(row["data_json"])
        return {"export": export}
    finally:
        await conn.close()


async def _history(id: str, **_) -> dict:
    conn = await _db()
    try:
        cursor = await conn.execute(
            "SELECT * FROM extension_history WHERE ext_id = ? ORDER BY created_at",
            (id,),
        )
        rows = await cursor.fetchall()
        return {"history": [dict(r) for r in rows]}
    finally:
        await conn.close()


async def _list(**_) -> dict:
    conn = await _db()
    try:
        cursor = await conn.execute("SELECT * FROM extensions WHERE state != 'removed' ORDER BY id")
        rows = await cursor.fetchall()
        return {"extensions": [_row_to_dict(r) for r in rows]}
    finally:
        await conn.close()


async def _get(id: str, **_) -> dict:
    conn = await _db()
    try:
        cursor = await conn.execute("SELECT * FROM extensions WHERE id = ?", (id,))
        row = await cursor.fetchone()
        if not row:
            raise ValueError(f"Extension '{id}' not found.")
        return {"extension": _row_to_dict(row)}
    finally:
        await conn.close()


# ── Data persistence ────────────────────────────────────────────────────────

async def set_data(ext_id: str, data: dict) -> None:
    conn = await _db()
    try:
        await conn.execute(
            "UPDATE extensions SET data_json = ?, updated_at = datetime('now') WHERE id = ?",
            (json.dumps(data), ext_id),
        )
        await conn.commit()
    finally:
        await conn.close()


async def get_data(ext_id: str) -> dict:
    conn = await _db()
    try:
        cursor = await conn.execute("SELECT data_json FROM extensions WHERE id = ?", (ext_id,))
        row = await cursor.fetchone()
        return json.loads(row["data_json"]) if row else {}
    finally:
        await conn.close()


# ── Source conflict check (called by source_updates) ────────────────────────

async def check_source_conflicts(files: list[str]) -> bool:
    """Return True if any of the given file paths are owned by an active extension."""
    conn = await _db()
    try:
        owners = await _file_owners(conn, states=("active",))
        return any(_norm_path(f) in owners for f in files)
    finally:
        await conn.close()


def _norm_path(path: str) -> str:
    return str(path).replace("\\", "/").removeprefix("./").lower()


async def _file_owners(conn: aiosqlite.Connection, exclude: str | None = None,
                       states: tuple[str, ...] = ("active", "disabled")) -> dict[str, str]:
    """Map each owned file (normalized) to the extension that currently owns it."""
    cursor = await conn.execute("SELECT id, state, manifest_json FROM extensions")
    owners = {}
    for row in await cursor.fetchall():
        if row["id"] == exclude or row["state"] not in states:
            continue
        for f in json.loads(row["manifest_json"]).get("owned_files", []):
            owners[_norm_path(f)] = row["id"]
    return owners


async def _require(conn: aiosqlite.Connection, ext_id: str) -> None:
    cursor = await conn.execute("SELECT 1 FROM extensions WHERE id = ?", (ext_id,))
    if not await cursor.fetchone():
        raise ValueError(f"Extension '{ext_id}' not found.")


# ── Dependency checks ──────────────────────────────────────────────────────

async def _check_dependents_active(conn: aiosqlite.Connection, ext_id: str) -> None:
    """Raise if any active extension depends on this one."""
    cursor = await conn.execute(
        "SELECT id, manifest_json FROM extensions WHERE state = 'active' AND id != ?",
        (ext_id,),
    )
    for row in await cursor.fetchall():
        m = json.loads(row["manifest_json"])
        if ext_id in (m.get("dependencies") or {}):
            raise ValueError(f"Cannot disable '{ext_id}': extension '{row['id']}' depends on it.")


async def _check_dependents_compat(conn: aiosqlite.Connection, ext_id: str, new_version: str) -> None:
    """Raise if a new version breaks existing dependents (major bump)."""
    cursor = await conn.execute(
        "SELECT id, manifest_json FROM extensions WHERE state = 'active' AND id != ?",
        (ext_id,),
    )
    for row in await cursor.fetchall():
        m = json.loads(row["manifest_json"])
        dep_version = (m.get("dependencies") or {}).get(ext_id)
        if dep_version:
            dep_major = dep_version.split(".")[0]
            new_major = new_version.split(".")[0]
            if dep_major != new_major:
                raise ValueError(
                    f"Cannot install '{ext_id}' v{new_version}: extension '{row['id']}' "
                    f"depends on v{dep_version} (major version mismatch)."
                )


# ── Helpers ─────────────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    d = dict(row)
    d["manifest"] = json.loads(d.pop("manifest_json", "{}"))
    d["data"] = json.loads(d.pop("data_json", "{}"))
    return d


# ── Built-in: Grade Calculator (plan §8 acceptance example) ─────────────────

_GRADE_CALC_ID = "grade-calculator"
_GRADE_CALC_MANIFEST = {
    "schema_version": 1,
    "id": _GRADE_CALC_ID,
    "title": "Grade Calculator",
    "version": "1.0.0",
    "owner": "nova",
    "kind": "widget",
    "compatibility": {"api": 1},
    "permissions": ["storage"],
    "dependencies": {},
    "owned_files": [],
    "data_migrations": [],
}


async def grade_calculator(action: str = "get", entries: list[dict] | None = None) -> dict:
    """Built-in grade calculator extension — a concrete example of a real working
    extension that the plan requires (§8 acceptance example).
    """
    # Ensure the extension is installed
    conn = await _db()
    try:
        cursor = await conn.execute("SELECT * FROM extensions WHERE id = ?", (_GRADE_CALC_ID,))
        row = await cursor.fetchone()
        if not row:
            await conn.close()
            await manage("install", manifest=_GRADE_CALC_MANIFEST)
            conn = await _db()
            cursor = await conn.execute("SELECT * FROM extensions WHERE id = ?", (_GRADE_CALC_ID,))
            row = await cursor.fetchone()

        current_data = json.loads(row["data_json"]) if row else {}

        if action == "get":
            return {"data": current_data}

        if action == "calculate":
            if not entries:
                raise ValueError("At least one grade entry is required.")

            total_weight = 0.0
            weighted_sum = 0.0
            has_weights = any("weight" in e for e in entries)

            for e in entries:
                earned = e.get("earned", 0)
                possible = e.get("possible", 0)

                if isinstance(earned, float) and (math.isnan(earned) or math.isinf(earned)):
                    raise ValueError(f"Invalid earned value: {earned}")
                if isinstance(possible, float) and (math.isnan(possible) or math.isinf(possible)):
                    raise ValueError(f"Invalid possible value: {possible}")
                if earned < 0 or possible < 0:
                    raise ValueError(f"Negative values not allowed: earned={earned}, possible={possible}")
                if possible == 0:
                    raise ValueError("Possible points cannot be zero.")

                w = e.get("weight", None)
                if has_weights:
                    if w is None:
                        raise ValueError("If any entry has a weight, all entries must have weights.")
                    total_weight += w
                    weighted_sum += (earned / possible) * w
                else:
                    weighted_sum += earned
                    total_weight += possible

            if has_weights and total_weight != 100:
                raise ValueError(f"Weights must sum to 100 (got {total_weight}).")

            if total_weight == 0:
                raise ValueError("Total weight/possible cannot be zero.")

            percentage = round((weighted_sum / total_weight) * 100) if not has_weights else round(weighted_sum)

            result_data = {"result": {"percentage": percentage, "entries": entries}}
            await conn.execute(
                "UPDATE extensions SET data_json = ?, updated_at = datetime('now') WHERE id = ?",
                (json.dumps(result_data), _GRADE_CALC_ID),
            )
            await conn.commit()
            return {"data": result_data}

        raise ValueError(f"Unknown grade_calculator action: {action}")
    finally:
        await conn.close()
