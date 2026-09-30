"""Identity of the source loaded at process startup, without exposing secrets."""
import hashlib
import os
from pathlib import Path


def source_revision():
    digest = hashlib.sha256()
    for source in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(source.name.encode("utf-8"))
        digest.update(source.read_bytes())
    return digest.hexdigest()[:16]


REVISION = source_revision()


def health():
    import platform
    # The computer's short name, so a phone can say which Nova it found.
    host = (platform.node() or "").split(".")[0]
    return {"status": "ok", "app": "nova", "protocol": 1, "revision": REVISION, "pid": os.getpid(), "host": host}
