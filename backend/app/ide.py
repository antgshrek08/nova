"""Local IDE operations, scoped to the currently opened project."""
import asyncio
import os
from pathlib import Path
import shutil
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from . import code_files, config, db, dev_server

router = APIRouter(prefix="/code")


def nova_source_root():
    candidates = ([Path(os.environ['NOVA_SOURCE_ROOT'])] if os.environ.get('NOVA_SOURCE_ROOT') else []) + [Path(__file__).resolve().parents[2]]
    for candidate in candidates:
        if (candidate / 'backend/app/main.py').is_file() and (candidate / 'frontend/package.json').is_file():
            return candidate.resolve()
    raise HTTPException(404, 'Nova source checkout was not found. Select its folder manually.')


@router.post('/nova-source')
async def open_nova_source():
    root = nova_source_root()
    config.set_workspace_dir(root)
    await db.set_app_settings({'workspace_root': str(root)})
    return {'path': str(root), 'name': root.name, 'is_default': False}


@router.get('/preview')
async def preview_status():
    return dev_server.status()


@router.post('/preview/start')
async def preview_start():
    try:
        return await dev_server.start()
    except (RuntimeError, OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post('/preview/stop')
async def preview_stop():
    return await dev_server.stop()


def path_in_project(value, allow_root=False):
    try:
        path = code_files._resolve(str(value))
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    relative = path.relative_to(config.get_workspace_dir().resolve())
    if ".git" in relative.parts or (not relative.parts and not allow_root):
        raise HTTPException(400, "Choose a project file or folder outside .git")
    return path


@router.post("/folder")
async def create_folder(body: dict):
    target = path_in_project(body.get("path", ""))
    if target.exists():
        raise HTTPException(409, "A file or folder already exists at that path")
    target.mkdir(parents=True)
    return {"created": True}


@router.post("/rename")
async def rename_path(body: dict):
    source = path_in_project(body.get("path", ""))
    target = path_in_project(body.get("new_path", ""))
    if not source.exists():
        raise HTTPException(404, "Source does not exist")
    if target.exists():
        raise HTTPException(409, "Destination already exists")
    if source.is_dir() and target.is_relative_to(source):
        raise HTTPException(400, "A folder cannot be moved into itself")
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)
    return {"renamed": True}


@router.post("/import")
async def import_files(files: list[UploadFile] = File(...), directory: str = Form("")):
    folder = path_in_project(directory, allow_root=True)
    if not folder.is_dir():
        raise HTTPException(400, "Choose an existing destination folder")
    if len(files) > 100:
        raise HTTPException(413, "Import up to 100 files at a time")
    pending = []
    seen = set()
    total = 0
    for file in files:
        name = (file.filename or "").replace("\\", "/")
        if not name or Path(name).name != name or name in (".", ".."):
            raise HTTPException(400, "File names must not contain directories")
        target = path_in_project(str(folder / name))
        if target.exists() or str(target).casefold() in seen:
            raise HTTPException(409, f"{name} already exists; rename it before importing")
        data = await file.read(10 * 1024 * 1024 + 1)
        total += len(data)
        if len(data) > 10 * 1024 * 1024 or total > 30 * 1024 * 1024:
            raise HTTPException(413, "Maximum 10 MB per file and 30 MB per import")
        seen.add(str(target).casefold())
        pending.append((target, data))
    written = []
    try:
        for target, data in pending:
            with target.open("xb") as handle:
                written.append(target)
                handle.write(data)
    except OSError as exc:
        for target in written:
            target.unlink(missing_ok=True)
        raise HTTPException(409, str(exc)) from exc
    root = config.get_workspace_dir().resolve()
    return {"paths": [str(p.relative_to(root)).replace("\\", "/") for p in written]}
