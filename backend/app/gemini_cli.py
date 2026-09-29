"""Prepared Google-account adapter. Disabled until interactive sign-in is verified."""
import os
import json
import shutil
from pathlib import Path

def availability() -> dict:
    return {'available': False, 'availability_reason': 'Google ended personal-account Gemini CLI access; use Antigravity CLI.'}


def _legacy_availability() -> dict:
    executable = shutil.which('gemini') or str(Path(os.environ.get('APPDATA', '')) / 'npm/gemini.cmd')
    try:
        installed = Path(executable).is_file()
    except OSError:
        installed = False
    if not installed:
        return {'available': False, 'availability_reason': 'Gemini CLI is not installed.'}
    # Login presence alone is not evidence of a valid AI Pro entitlement.
    if os.environ.get('NOVA_GEMINI_CLI_VERIFIED') != '1':
        return {'available': False, 'availability_reason': 'Installed; Google sign-in and subscription verification pending.'}
    try:
        settings = json.loads((Path.home() / '.gemini/settings.json').read_text(encoding='utf-8'))
        google = settings.get('security', {}).get('auth', {}).get('selectedType') == 'oauth-personal'
    except (OSError, ValueError):
        google = False
    if not google or not (Path.home() / '.gemini/oauth_creds.json').is_file():
        return {'available': False, 'availability_reason': 'Google-account authentication is missing; API-key fallback is disabled.'}
    return {'available': True, 'availability_reason': 'Google-account CLI explicitly verified; execution can still encounter quota limits.'}

def command() -> list[str]:
    status = availability()
    if not status['available']:
        raise RuntimeError(status['availability_reason'])
    # node avoids cmd.exe quoting on Windows. The official package owns OAuth.
    bundle = Path(os.environ.get('APPDATA', '')) / 'npm/node_modules/@google/gemini-cli/bundle/gemini.js'
    if not bundle.is_file():
        raise RuntimeError('Verified Gemini CLI bundle was not found.')
    return [shutil.which('node') or 'node', str(bundle), '--approval-mode', 'plan',
            '--extensions', '', '--output-format', 'text', '--prompt',
            'Answer the task supplied on stdin. This is a read-only specialist request. Do not modify files.']

def environment(base: dict) -> dict:
    # Never let an inherited key or Vertex setting select paid API authentication.
    result = {k:v for k,v in base.items() if k not in {
        'GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GOOGLE_APPLICATION_CREDENTIALS',
        'GOOGLE_GENAI_USE_VERTEXAI', 'GOOGLE_GENAI_USE_GCA', 'GOOGLE_CLOUD_PROJECT',
        'GOOGLE_CLOUD_LOCATION', 'CLOUDSDK_CORE_PROJECT'}}
    result['GOOGLE_GENAI_USE_GCA'] = 'true'
    result['NO_BROWSER'] = 'true'
    return result
