"""One owned local web preview process, with bounded logs and explicit cleanup."""
import asyncio
from collections import deque
import json
import os
from pathlib import Path
import shutil

import httpx
from . import config

_process = None
_reader = None
_root = None
_url = None
_logs = deque(maxlen=80)
_lock = asyncio.Lock()


def command(root, port=3000):
    root = Path(root)
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Node.js is not installed')
    package = json.loads((root / 'package.json').read_text(encoding='utf-8'))
    dependencies = {**package.get('dependencies', {}), **package.get('devDependencies', {})}
    if 'next' in dependencies:
        entry = root / 'node_modules/next/dist/bin/next'
        args = ['dev', '--hostname', '127.0.0.1', '--port', str(port)]
    elif 'vite' in dependencies:
        entry = root / 'node_modules/vite/bin/vite.js'
        args = ['--host', '127.0.0.1', '--port', str(port), '--strictPort']
    else:
        raise RuntimeError('Automatic preview supports Next.js and Vite. Use Code > Terminal for this project’s custom start command.')
    if not entry.is_file():
        raise RuntimeError('Project dependencies are missing. Install them in Code > Terminal first.')
    return [node, str(entry), *args]


def status():
    return {'running': _process is not None and _process.returncode is None,
            'url': _url, 'root': _root, 'logs': list(_logs)}


async def _read(process):
    while line := await process.stdout.readline():
        _logs.append(line.decode(errors='replace').rstrip()[:1000])


async def start():
    global _process, _reader, _root, _url
    async with _lock:
        root = config.get_workspace_dir().resolve()
        if status()['running']:
            if _root != str(root):
                raise RuntimeError('Stop the previous project preview before starting another.')
            return status()
        port = 3000
        try:
            _, writer = await asyncio.open_connection('127.0.0.1', port)
        except OSError:
            pass
        else:
            writer.close()
            await writer.wait_closed()
            raise RuntimeError('Port 3000 is already in use. Nova has not stopped that process.')
        args = command(root, port)
        _logs.clear()
        _process = await asyncio.create_subprocess_exec(*args, cwd=str(root),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            creationflags=0x08000000 if os.name == 'nt' else 0)
        _root, _url = str(root), f'http://127.0.0.1:{port}'
        _reader = asyncio.create_task(_read(_process))
        # Readiness is established by the server response, not just a PID.
        async with httpx.AsyncClient(timeout=2) as client:
            for _ in range(30):
                if _process.returncode is not None:
                    raise RuntimeError('Preview exited: ' + '\n'.join(_logs)[-1500:])
                try:
                    response = await client.get(_url)
                    if response.status_code < 500:
                        return {**status(), 'ready': True}
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(.5)
        return {**status(), 'ready': False}


async def stop():
    global _process, _reader
    async with _lock:
        if _process is not None and _process.returncode is None:
            if os.name == 'nt':
                killer = await asyncio.create_subprocess_exec('taskkill.exe', '/PID', str(_process.pid), '/T', '/F',
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, creationflags=0x08000000)
                await killer.wait()
            else:
                _process.terminate()
            await _process.wait()
        if _reader:
            _reader.cancel()
            await asyncio.gather(_reader, return_exceptions=True)
        _process = _reader = None
        return status()
