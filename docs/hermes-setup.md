# Hermes in Nova

Select **Settings → Routing → Hermes · Qwen 3.5 4B** for the desired category.
Automatic routing and the existing Claude/Codex team assignments are unchanged.

Hermes 0.21.2 runs in `backend/.venv-hermes` using the pinned source revision
`1021a0325696e9070e6659f95fcd84c3e7e114df`. Reinstall with
`powershell -File scripts/install-hermes.ps1`. Restart Nova after installation.
`backend/hermes_entry.py` selects file, terminal, todo, memory, and skill-reading
tools. Browser and nested delegation tools are excluded from this local profile.
Git Bash is discovered beside the installed Git executable, including drive D.

The model is Ollama Qwen 3.5 4B with a 65,536-token context, required by this
Hermes release. All completions pass through Nova's single local inference queue;
there is only one active Hermes turn at a time. Measured GPU allocation was
5,372,106,504 bytes (about 5.0 GiB), and a warm follow-up took 2.74 seconds.
Cold startup and processing long prompts take longer. This is an agent for
coding tasks; ordinary clock questions still use Nova's instant answer path.

Configuration and session data stay in `backend/.hermes` (gitignored).
Workspace and temporary-file edits use Hermes's `accept_edits` mode. Requests
requiring additional permissions are denied by this host; browser automation
and unrestricted computer control are not enabled by this integration.

Diagnostics: `GET /hermes/status`. Direct NDJSON streaming:
`POST /hermes/prompt` with `{"prompt":"Your task", "session":"your-session-id"}`.
Explicit session IDs preserve history and are scoped to the current workspace.
Normal Nova model dispatch includes the conversation context in its request.
The internal OpenAI-compatible proxy requires a per-process runtime token.

Validated 2026-09-12: ACP startup, streamed response, follow-up memory, code-file
read, temporary-file write/read, live model catalog, and 44 backend unit tests.
