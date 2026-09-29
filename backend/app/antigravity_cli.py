"""Google-account Antigravity CLI adapter; activation follows a live login check."""
import os
import shutil
from pathlib import Path
from dotenv import dotenv_values

try:
    from . import config
except ImportError:  # direct unit-test loading
    config = None


def executable() -> str:
    return shutil.which('agy') or str(Path(os.environ.get('LOCALAPPDATA', '')) / 'agy/bin/agy.exe')


def availability() -> dict:
    exe = executable()
    if not (exe and Path(exe).is_file()):
        return {'available': False, 'availability_reason': 'Antigravity CLI is not installed.'}
    persisted = dotenv_values(config.ENV_PATH if config else Path.home() / '.ai-council' / '.env')
    marker = os.environ.get('NOVA_ANTIGRAVITY_CLI_VERIFIED', persisted.get('NOVA_ANTIGRAVITY_CLI_VERIFIED', '0'))
    if str(marker).strip().strip("\"'") != '1':
        return {'available': False, 'availability_reason': 'Antigravity CLI login has not been verified.'}
    return {'available': True, 'availability_reason': 'Antigravity CLI login verified.'}



def command(prompt: str) -> list[str]:
    status = availability()
    if not status['available']:
        raise RuntimeError(status['availability_reason'])
    if len(prompt) > 24000:
        raise ValueError('Antigravity context exceeds 24,000 characters; reduce the context before retrying.')
    return [executable(), '--mode', 'plan',
            '--model', 'gemini-3.8-flash-low', '--output-format', 'text',
            '--print-timeout', '120s', '--print', prompt]


def environment(base: dict) -> dict:
    blocked = {'GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GOOGLE_APPLICATION_CREDENTIALS',
               'GOOGLE_GENAI_USE_VERTEXAI', 'GOOGLE_GENAI_USE_GCA', 'GOOGLE_CLOUD_PROJECT',
               'GOOGLE_CLOUD_LOCATION', 'CLOUDSDK_CORE_PROJECT', 'ANTHROPIC_API_KEY', 'OPENAI_API_KEY'}
    return {key: value for key, value in base.items() if key.upper() not in blocked}
