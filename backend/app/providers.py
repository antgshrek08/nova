"""Provider access: Gemini, OpenRouter, local Ollama (via LiteLLM), and
subprocess wrappers around the Claude Code CLI and Codex CLI.

Claude CLI and Codex CLI use the user's existing Pro/ChatGPT subscriptions
(no extra API cost) via `claude -p "..."` and `codex exec "..."`. Ollama uses
whatever models are actually pulled locally, discovered live via its /api/tags
endpoint rather than hardcoded, the same "never hardcode ids" principle the
spec applies to OpenRouter's rotating free roster.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

import httpx
import litellm

from . import config, costs, desktop, desktop_registry, file_access, mcp_manager, inference_scheduler
from .local_inference import completion

litellm.drop_params = True  # tolerate provider-specific kwarg differences


@dataclass
class FreeModel:
    id: str
    name: str
    input_modalities: list[str] = field(default_factory=lambda: ['text'])
    supported_parameters: list[str] = field(default_factory=list)
    context_length: int = 0


@dataclass
class _FreeModelCache:
    models: list[FreeModel] = field(default_factory=list)
    fetched_at: float = 0.0


_cache = _FreeModelCache()
_unavailable_free_models: dict[str, float] = {}


async def _fetch_openrouter_models() -> list[dict]:
    headers = {}
    key = config.openrouter_api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(config.OPENROUTER_MODELS_URL, headers=headers)
        resp.raise_for_status()
        return resp.json().get("data", [])


def _is_free(model: dict) -> bool:
    pricing = model.get("pricing", {})
    try:
        prompt_price = float(pricing.get("prompt", "1"))
        completion_price = float(pricing.get("completion", "1"))
    except (TypeError, ValueError):
        return False
    try:
        return prompt_price == 0.0 and completion_price == 0.0 and float(pricing.get('request', 0)) == 0
    except (TypeError, ValueError):
        return False


async def get_free_openrouter_models(force_refresh: bool = False) -> list[FreeModel]:
    """Live free-tier roster from OpenRouter, filtered on pricing.prompt == 0.

    Per spec: never hardcode model IDs here, since the free roster rotates
    weekly. Cached for OPENROUTER_FREE_CACHE_TTL_SECONDS to avoid hammering
    the /models endpoint on every chat request.
    """
    now = time.time()
    if not force_refresh and _cache.models and (now - _cache.fetched_at) < config.OPENROUTER_FREE_CACHE_TTL_SECONDS:
        return [m for m in _cache.models if m.id != "openrouter/free" and _unavailable_free_models.get(m.id, 0) <= now]

    raw_models = await _fetch_openrouter_models()
    free = [FreeModel(id=m["id"], name=m.get("name", m["id"]),
                      input_modalities=(m.get('architecture') or {}).get('input_modalities') or ['text'],
                      supported_parameters=m.get('supported_parameters') or [],
                      context_length=m.get('context_length') or 0) for m in raw_models if _is_free(m)]
    _cache.models = free
    _cache.fetched_at = now
    return [m for m in free if m.id != "openrouter/free" and _unavailable_free_models.get(m.id, 0) <= now]


def find_free_model_by_keywords(
    models: list[FreeModel], keywords: list[str], exclude: set[str] | None = None
) -> FreeModel | None:
    """First free model whose id or display name contains any keyword (case-insensitive).

    `exclude` skips model ids already tried and rejected in this request (see
    ProviderRateLimitedError / routing.resolve's exclude_models) -- lets a
    retry re-run the same keyword step and land on a *different* real model
    under it before giving up and moving to the chain's next step.
    """
    exclude = exclude or set()
    for keyword in keywords:
        needle = keyword.lower()
        for model in models:
            if model.id in exclude:
                continue
            if needle in model.id.lower() or needle in model.name.lower():
                return model
    return None


class ProviderUnavailableError(RuntimeError):
    """Raised when a provider step can't serve the request (auth, rate limit, etc.)."""



class ProviderRateLimitedError(ProviderUnavailableError):
    """Raised specifically for an HTTP 429 / rate-limit failure from a provider.

    Kept distinct from the general ProviderUnavailableError so callers (see
    main.py's /chat retry loop) can catch *this* failure mode specifically and
    reroute to the next model in the category's fallback chain, while other
    failures (missing API key, CLI not found, genuine model errors) still
    surface to the user as before.
    """


class ProviderNoProgressError(ProviderUnavailableError):
    """A model ran out of its whole tool-step budget without ever narrating a
    step -- just tool call after tool call, nothing explained, nothing to
    show (found live: a small free model spun 24 browser_act calls this way
    on a homework request). Kept distinct so agent_loop's "an action was
    attempted, don't replay on a fallback model" guard -- which exists to
    stop a genuine submission or purchase being repeated -- doesn't also
    swallow this case: a model that never said a word about what it was
    doing didn't leave anything worth protecting from a retry.
    """


def _finalize_litellm_usage(chunks: list) -> tuple[float, int]:
    """Best-effort (cost_usd, total_tokens) recovered from a completed stream.

    litellm.stream_chunk_builder reassembles a full, usage-populated response
    from the raw chunks collected while streaming (many providers only carry
    usage on the reconstructed response, not on individual chunks); cost is
    then read off litellm's static per-model pricing map. Returns (0.0, 0) on
    any failure -- most commonly a free/local model litellm has no price
    entry for, which correctly means $0 rather than an error.
    """
    try:
        full_response = litellm.stream_chunk_builder(chunks)
        usage = getattr(full_response, "usage", None)
        tokens = int(getattr(usage, "total_tokens", 0) or 0)
        cost = float(litellm.completion_cost(completion_response=full_response) or 0.0)
        return cost, tokens
    except Exception:  # noqa: BLE001 - cost tracking must never break the chat itself
        return 0.0, 0


async def stream_openrouter(model_id: str, messages: list[dict]) -> AsyncIterator[str]:
    key = config.openrouter_api_key()
    if not key:
        raise ProviderUnavailableError("OpenRouter API key is not configured.")
    try:
        # This call itself needs its own timeout, separate from the
        # per-chunk idle timeout below: live-tested with only the chunk-loop
        # timeout in place and a real hang still went the full length of the
        # calling client's own timeout with zero movement, which only
        # happens if the hang is here, before any chunk iteration even
        # starts. litellm.acompletion has no timeout of its own, so a
        # provider that accepts the connection but never sends a response at
        # all blocks this forever with nothing downstream able to react.
        response = await asyncio.wait_for(
            completion(
                model=f"openrouter/{model_id}",
                messages=messages,
                api_key=key,
                stream=True,
            ),
            timeout=config.OPENROUTER_STREAM_IDLE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise ProviderRateLimitedError(
            f"OpenRouter model '{model_id}' didn't respond within "
            f"{config.OPENROUTER_STREAM_IDLE_TIMEOUT_SECONDS:.0f}s."
        ) from exc
    except litellm.RateLimitError as exc:
        _unavailable_free_models[model_id] = time.time() + 3600
        raise ProviderRateLimitedError("This model is busy. Trying another available model.") from exc
    except Exception as exc:  # noqa: BLE001 - surfaced to caller as unavailable
        if getattr(exc, 'status_code', None) in (404, 410, 429):
            _unavailable_free_models[model_id] = time.time() + 1800
        raise ProviderUnavailableError("This model is currently unavailable. Try another model or automatic routing.") from exc

    chunks = []
    got_chunk = False
    stream_iter = response.__aiter__()
    while True:
        try:
            chunk = await asyncio.wait_for(
                stream_iter.__anext__(), timeout=config.OPENROUTER_STREAM_IDLE_TIMEOUT_SECONDS
            )
        except StopAsyncIteration:
            break
        except asyncio.TimeoutError as exc:
            # Reuse ProviderRateLimitedError so main.py's existing retry loop
            # (already built for "this model/step didn't pan out, exclude it
            # and reroute to the next one in the chain") handles a silently
            # stalled stream the same graceful way it handles a real 429 --
            # but only when nothing has streamed yet (see that loop's
            # `can_reroute` check: not got_token). A stall *after* real
            # content already streamed falls through to a plain error
            # instead, which is correct -- rerouting mid-reply would silently
            # discard a partial real answer.
            raise ProviderRateLimitedError(
                f"OpenRouter model '{model_id}' went silent for "
                f"{config.OPENROUTER_STREAM_IDLE_TIMEOUT_SECONDS:.0f}s mid-stream "
                f"(got_chunk={got_chunk})."
            ) from exc
        got_chunk = True
        chunks.append(chunk)
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta

    cost_usd, tokens = _finalize_litellm_usage(chunks)
    await costs.tracker.record(cost_usd, tokens, provider="openrouter")


@dataclass
class _LastKnownOllama:
    models: list[FreeModel] = field(default_factory=list)
    have_result: bool = False


_last_known_ollama = _LastKnownOllama()


async def get_local_ollama_models() -> list[FreeModel]:
    """Live roster of models actually pulled into the local Ollama install.

    Queried fresh every call (no TTL cache, unlike OpenRouter's): it's a
    local call, and the installed set can change any time via `ollama
    pull`/`rm`. It DOES fall back to the last successful result on a
    transient failure, though -- Ollama's HTTP server can go briefly
    unresponsive to /api/tags while it's mid-generation on another request
    (e.g. actively streaming a chat reply), and without this fallback that
    single slow tick made every caller (routing, and main.py's /models used
    by the Workspace network view) treat the whole local roster as gone,
    which is what made Workspace nodes flicker offline/online instead of
    reliably showing connected. A cold-start failure (Ollama never reachable
    yet) still raises -- there's nothing to fall back to, and that's the
    correct "not connected" state, not a transient blip.
    """
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(f"{config.OLLAMA_BASE_URL}/api/tags")
            resp.raise_for_status()
        models = [FreeModel(id=m["name"], name=m["name"]) for m in resp.json().get("models", [])]
        _last_known_ollama.models = models
        _last_known_ollama.have_result = True
        return models
    except Exception:
        if _last_known_ollama.have_result:
            return _last_known_ollama.models
        raise


def _has_image_blocks(messages: list[dict]) -> bool:
    return any(
        isinstance(m.get("content"), list)
        and any(b.get("type") == "image_url" for b in m["content"])
        for m in messages
    )


def _to_ollama_native(messages: list[dict]) -> list[dict]:
    """Rewrite OpenAI-style content blocks into Ollama's own message shape.

    Ollama does not take `image_url` parts. It takes a flat `content` string
    plus an `images` list of bare base64, and litellm's ollama_chat adapter
    does not translate between the two -- handed a content-block message it
    hangs until the first-token timeout rather than erroring, which is how
    local vision looked like a broken model instead of a wrong payload.
    """
    converted: list[dict] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            converted.append(message)
            continue
        text = "\n\n".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
        images: list[str] = []
        for block in content:
            if block.get("type") != "image_url":
                continue
            url = (block.get("image_url") or {}).get("url", "")
            # Only data URIs: a remote URL would have to be fetched, and
            # every image on this path was uploaded by the user and is
            # already in memory.
            if "," in url and url.startswith("data:"):
                images.append(url.split(",", 1)[1])
        entry = {"role": message.get("role", "user"), "content": text}
        if images:
            entry["images"] = images
        converted.append(entry)
    return converted


async def stream_ollama_vision(model_id: str, messages: list[dict]) -> AsyncIterator[str]:
    """Stream from Ollama's native /api/chat so images actually arrive.

    Deliberately not routed through litellm. This is the one call in Nova
    where the payload shape differs from OpenAI's, and going direct is both
    shorter than teaching litellm the difference and verifiable against the
    same endpoint `ollama run` uses.
    """
    payload = {
        "model": model_id,
        "messages": _to_ollama_native(messages),
        "stream": True,
        # Images are expensive to prefill and this machine prefills slowly,
        # so the first-token wait is longer here than for a text turn.
        "options": {"num_ctx": 4096},
        "think": False,
    }
    url = f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    produced = False
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(config.OLLAMA_VISION_TIMEOUT_SECONDS)) as client:
            async with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("error"):
                        raise ProviderUnavailableError(f"Ollama vision error: {event['error']}")
                    token = (event.get("message") or {}).get("content")
                    if token:
                        produced = True
                        yield token
                    if event.get("done"):
                        break
    except ProviderUnavailableError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ProviderUnavailableError(f"Local vision model '{model_id}' failed: {exc}") from exc
    if not produced:
        raise ProviderUnavailableError(f"Local vision model '{model_id}' returned nothing.")


async def stream_ollama(model_id: str, messages: list[dict], json_mode: bool = False) -> AsyncIterator[str]:
    # An image turn cannot go through litellm (see _to_ollama_native).
    if _has_image_blocks(messages):
        async for token in stream_ollama_vision(model_id, messages):
            yield token
        return
    try:
        response = await asyncio.wait_for(
            completion(
                model=f"ollama_chat/{model_id}",
                messages=messages,
                api_base=config.OLLAMA_BASE_URL,
                stream=True,
                **({"format": "json", "max_tokens": 1024, "temperature": 0} if json_mode else {}),
            ),
            timeout=config.OLLAMA_FIRST_TOKEN_TIMEOUT_SECONDS,
        )
    except litellm.RateLimitError as exc:
        raise ProviderRateLimitedError(f"Ollama model '{model_id}' is rate-limited: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ProviderUnavailableError(f"Ollama model '{model_id}' failed: {exc}") from exc

    try:
        chunks = []
        iterator = response.__aiter__()
        while True:
            try:
                chunk = await asyncio.wait_for(
                    iterator.__anext__(), timeout=config.OLLAMA_STREAM_IDLE_TIMEOUT_SECONDS
                )
            except StopAsyncIteration:
                break
            chunks.append(chunk)
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
    finally:
        await response.aclose()

    cost_usd, tokens = _finalize_litellm_usage(chunks)
    await costs.tracker.record(cost_usd, tokens, provider="ollama")


def _format_cli_transcript(messages: list[dict]) -> str:
    """Flatten chat history into a single one-shot prompt.

    claude -p / codex exec are one-shot subprocess calls here (no
    session/thread reuse yet in this Phase 1/2/3 wiring), so prior turns are
    rendered as a plain transcript ahead of the final user message. A
    "system" role message (project instructions and/or recalled memory
    context, see main.py) is emitted as its own paragraph as-is -- its
    content already self-describes ("Project instructions: ...",
    "Relevant context from earlier conversations: ...") so no extra label
    is added.
    """
    lines = []
    for message in messages[:-1]:
        if message["role"] == "system":
            lines.append(message["content"])
            continue
        speaker = "User" if message["role"] == "user" else "Assistant"
        lines.append(f"{speaker}: {message['content']}")
    lines.append(messages[-1]["content"])
    return "\n\n".join(lines)


# Real risk found live (diagnostic task): ANTHROPIC_API_KEY/OPENAI_API_KEY
# aren't set anywhere on this machine today, but every CLI subprocess spawn
# below previously inherited the full parent environment verbatim -- no
# env= override at all. If either var were ever set at the OS level later
# (a different dev tool, a copied .env, a shell profile change), the
# Claude/Codex CLI would silently prioritize it over the user's actual paid
# subscription login and switch to pay-per-token API billing, with no error
# or warning. This app is built entirely around using each CLI's
# subscription auth, never its API-key billing -- stripping both vars from
# every subprocess spawned here means that can never happen silently,
# regardless of what shows up in the environment in the future.
_CLI_ENV_BLOCKLIST = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")


def _cli_subprocess_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _CLI_ENV_BLOCKLIST}


async def _stream_cli(command: list[str], cli_name: str, stdin_data: str | None = None, env_override: dict | None = None,
                      idle_timeout: int | None = None) -> AsyncIterator[str]:
    family = {"Claude Code": "claude_cli", "Codex": "codex_cli", "Antigravity": "antigravity_cli", "Gemini CLI": "gemini_cli"}.get(cli_name)
    async with inference_scheduler.slot(family or ""):
        stream = _stream_cli_unqueued(command, cli_name, stdin_data, env_override, idle_timeout)
        try:
            async for chunk in stream:
                yield chunk
        finally:
            await stream.aclose()


async def _stream_cli_unqueued(command: list[str], cli_name: str, stdin_data: str | None = None, env_override: dict | None = None,
                                idle_timeout: int | None = None) -> AsyncIterator[str]:
    """Run a CLI subprocess and yield stdout as it's produced.

    Runs from config.CLI_WORKSPACE_DIR, not this repo, so any file tools the
    CLI itself invokes while answering stay isolated from the AI Council
    project. Each read is timeout-bounded so a hung CLI can't block a request
    forever, in the spirit of the spec's "no unattended... cap" rule.

    stdin_data, when given, is written to the process then stdin is closed
    (EOF) so the CLI knows no more is coming. Exists because of a real,
    reproduced bug: `codex` resolves to `codex.cmd` (no matching .exe exists,
    unlike `claude`), and passing a prompt with embedded newlines as a
    positional argv element through that batch shim silently truncates it at
    the first newline -- confirmed live, both through this app and via a
    bare shell invocation with the exact same prompt. `codex exec` accepts
    `-` as the prompt argument to mean "read the real prompt from stdin
    instead", which sidesteps cmd.exe's argument parsing entirely.
    """
    # On Windows, npm-installed CLIs are often a .cmd shim with no matching
    # .exe (e.g. codex.cmd, no codex.exe), which CreateProcess can't resolve
    # from the bare name the way it auto-appends ".exe". shutil.which() walks
    # PATHEXT and finds the real target on any platform.
    resolved = shutil.which(command[0])
    if resolved:
        command = [resolved, *command[1:]]

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE if stdin_data is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(config.get_workspace_dir()),
            env=env_override if env_override is not None else _cli_subprocess_env(),
        )
    except FileNotFoundError as exc:
        raise ProviderUnavailableError(
            f"{cli_name} CLI not found on PATH. Install and log in, then retry."
        ) from exc
    except NotImplementedError as exc:
        # Real, reproduced dev-only gap on Windows: uvicorn's own loop
        # factory (uvicorn/loops/asyncio.py) hands the worker a
        # SelectorEventLoop instead of ProactorEventLoop whenever
        # use_subprocess is true (`--reload` or `--workers > 1`), and
        # SelectorEventLoop has no subprocess support at all -- this is
        # exactly what raised here. The packaged Electron app never hits
        # this: main.cjs starts uvicorn with neither flag, so it gets a
        # real ProactorEventLoop. Only `uvicorn ... --reload` on Windows is
        # affected; confirmed live by comparing the two.
        raise ProviderUnavailableError(
            f"{cli_name} CLI can't start a subprocess on this event loop. If you're running "
            "the backend dev server on Windows with `--reload`, restart it without --reload "
            "(uvicorn forces an event loop there that can't run subprocesses) -- the packaged "
            "app is unaffected."
        ) from exc

    if stdin_data is not None:
        assert process.stdin is not None
        process.stdin.write(stdin_data.encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()

    assert process.stdout is not None
    try:
        while True:
            try:
                chunk = await asyncio.wait_for(
                    process.stdout.read(4096), timeout=idle_timeout or config.CLI_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError as exc:
                process.kill()
                await process.wait()
                raise ProviderUnavailableError(
                    f"{cli_name} CLI timed out after {idle_timeout or config.CLI_TIMEOUT_SECONDS}s."
                ) from exc
            if not chunk:
                break
            yield chunk.decode("utf-8", errors="replace")
    except BaseException:
        # Only reached on an abnormal exit (an exception propagating through,
        # including asyncio.CancelledError -- a client disconnecting mid-
        # stream cancels whichever `await` this generator is suspended at).
        # asyncio doesn't kill child processes just because the awaiting
        # coroutine was cancelled, so without this the CLI subprocess was
        # left running as an untracked orphan for the rest of its generation
        # (confirmed live: it kept running ~20s past a simulated client
        # disconnect, burning CPU on output nobody would ever read, save, or
        # bill). Deliberately not a `finally` -- that would also fire on the
        # normal EOF `break` above and risk killing a process that's already
        # exiting cleanly, turning a real 0 exit code into a false failure.
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise

    returncode = await process.wait()
    if returncode != 0:
        stderr = (await process.stderr.read()) if process.stderr else b""
        raise ProviderUnavailableError(
            f"{cli_name} CLI exited with code {returncode}: "
            f"{stderr.decode('utf-8', errors='replace')[:500]}"
        )


async def _record_cli_usage(output_chunks: list[str], provider: str) -> None:
    """Record a flat estimated cost for a completed CLI call.

    Only called after the CLI finishes successfully (an error raised mid-call
    propagates out of the caller's `async for` before reaching this, so
    failed calls aren't charged). Token count is a rough ~4-chars-per-token
    estimate over the full response text, for the visible counter only --
    it isn't used in the budget check, only cost is.
    """
    text = "".join(output_chunks)
    tokens_estimate = max(len(text) // 4, 0)
    await costs.tracker.record(config.CLI_CALL_COST_ESTIMATE_USD, tokens_estimate, provider=provider)


async def stream_claude_cli(messages: list[dict], model: str | None = None, read_only: bool = False) -> AsyncIterator[str]:
    """`model`, when given, overrides config.CLAUDE_CLI_MODEL for this one
    call -- either a real alias (opus/sonnet/haiku/fable) or a resolved full
    name (e.g. "claude-opus-5"), both accepted by the CLI's own --model flag.
    Lets routing.py dispatch a specific tier (manual override, or the tier
    detect_claude_cli_model() found for the default chain) instead of every
    call silently going through whatever the process-wide config says.
    """
    prompt = _format_cli_transcript(messages)
    # Real, live-confirmed behavior (not assumed): claude -p in non-interactive
    # mode refuses to write files at all by default -- "the edit was denied,
    # permission wasn't granted... this session is non-interactive so I can't
    # prompt for it" -- reproduced with a bare `claude -p` call with no flags,
    # before this flag existed. `acceptEdits` auto-approves file edits
    # specifically (this app's whole reason for calling claude_cli in the
    # coding category, and the workspace/team-orchestration milestone's
    # implementer role) without the much broader
    # --dangerously-skip-permissions, which would also silently approve
    # arbitrary shell commands.
    command = [config.CLAUDE_CLI_PATH, "--permission-mode", "plan" if read_only else "acceptEdits"]
    if read_only:
        command += ["--tools", "Read,Grep,Glob"]
    effective_model = model if model is not None else config.CLAUDE_CLI_MODEL
    if effective_model:
        command += ["--model", effective_model]
    # Nova's own hands in the browser (see onyx_mcp_config): with Onyx open
    # and agent control on, Claude drives Onyx directly -- read, click, type,
    # scroll -- and keeps going until the job is done. Found live: without
    # it, Claude through Nova could not touch the browser at all.
    onyx_config = None if read_only else onyx_mcp_config()
    idle_timeout = None
    if onyx_config:
        command += ["--mcp-config", str(onyx_config), "--allowedTools", "mcp__onyx"]
        # claude -p prints only when it is finished; a long browser task is
        # quiet for many minutes, which the 120 s default would cut off.
        idle_timeout = CLI_BROWSER_IDLE_TIMEOUT_SECONDS
    command += ["-p", prompt]
    output_chunks = []
    try:
        async for chunk in _stream_cli(command, "Claude Code", idle_timeout=idle_timeout):
            output_chunks.append(chunk)
            yield chunk
    finally:
        if onyx_config:
            onyx_config.unlink(missing_ok=True)
    await _record_cli_usage(output_chunks, "claude_cli")


# How long a Claude call that is driving Onyx may run without printing.
CLI_BROWSER_IDLE_TIMEOUT_SECONDS = 3600


def onyx_mcp_config():
    """An MCP config file for Claude pointing at Onyx's agent server, or None
    when Onyx is not open with agent control on. The key in it is the one
    Onyx already wrote to its endpoint file for local agents; the file is
    private to this call and deleted afterwards."""
    import json as _json
    import os as _os
    import tempfile as _tempfile
    from pathlib import Path as _Path
    from . import onyx as _onyx
    endpoint = _onyx.read_endpoint()
    if not endpoint or not endpoint.get("url") or not endpoint.get("token"):
        return None
    config_body = {"mcpServers": {"onyx": {
        "type": "http",
        "url": endpoint["url"],
        "headers": {"Authorization": f"Bearer {endpoint['token']}", "X-Agent-Name": "Nova"},
    }}}
    fd, name = _tempfile.mkstemp(prefix="nova-onyx-", suffix=".json")
    with _os.fdopen(fd, "w", encoding="utf-8") as handle:
        _json.dump(config_body, handle)
    return _Path(name)


async def stream_antigravity_cli(messages: list[dict]) -> AsyncIterator[str]:
    from . import antigravity_cli
    prompt = _format_cli_transcript(messages)
    async for chunk in _stream_cli(antigravity_cli.command(prompt), 'Antigravity',
                                   env_override=antigravity_cli.environment(_cli_subprocess_env())):
        yield chunk


async def stream_gemini_cli(messages: list[dict]) -> AsyncIterator[str]:
    from . import gemini_cli
    command = gemini_cli.command()  # Refuses to launch before sign-in verification.
    async for chunk in _stream_cli(command, 'Gemini CLI', stdin_data=_format_cli_transcript(messages),
                                   env_override=gemini_cli.environment(_cli_subprocess_env())):
        yield chunk


async def stream_codex_cli(messages: list[dict], model: str | None = None, read_only: bool = False) -> AsyncIterator[str]:
    """See stream_claude_cli's `model` docstring -- same per-call override,
    Codex side."""
    prompt = _format_cli_transcript(messages)
    # CLI_WORKSPACE_DIR is deliberately not a git repo (an isolated sandbox,
    # not a project), so codex exec needs to be told explicitly it's fine to
    # run there. Prompt goes over stdin ("-") rather than as an argv element
    # -- see _stream_cli's docstring for why: the argv path silently
    # truncates any prompt containing a newline through the codex.cmd shim.
    # Real, live-confirmed behavior: codex exec defaults to a read-only
    # sandbox with approvals disabled in non-interactive mode -- even with
    # `-s workspace-write` alone it still refused ("approvals are disabled"),
    # reproduced before this flag existed. --approve-for-me auto-approves
    # through the workspace-write sandbox specifically (same scoped intent as
    # claude_cli's --permission-mode acceptEdits above), not the much
    # broader --dangerously-bypass-approvals-and-sandbox.
    command = [config.CODEX_CLI_PATH, "exec", "--skip-git-repo-check"]
    command += ["--sandbox", "read-only"] if read_only else ["--approve-for-me"]
    effective_model = model if model is not None else config.CODEX_CLI_MODEL
    if effective_model:
        command += ["--model", effective_model]
    command.append("-")
    output_chunks = []
    async for chunk in _stream_cli(command, "Codex", stdin_data=prompt):
        output_chunks.append(chunk)
        yield chunk
    await _record_cli_usage(output_chunks, "codex_cli")


# --- real CLI model detection -------------------------------------------
#
# Claude Code CLI and Codex CLI are dispatched with config.CLAUDE_CLI_MODEL /
# config.CODEX_CLI_MODEL (see stream_claude_cli/stream_codex_cli above) --
# empty means "whatever the CLI's own default resolves to for this login",
# same as before either config existed. Either way, this app has no other
# way to know what a given alias ("opus") or an empty override actually
# resolves to on Anthropic's/OpenAI's end, and must not just assume/hardcode
# it -- that resolution can change independent of anything here, silently
# making a hardcoded label wrong. Detected empirically, once per process, by
# making one minimal real call in exactly the same shape (same --model/-m
# value, if any) /chat already uses and reading the model back out of that
# call's own real output -- if detection used a different --model value than
# real dispatch, the label shown in chat badges/Workspace nodes/agent job
# cards would silently lie about which model actually answered.

_claude_cli_model: str | None = None
_claude_cli_detected = False  # distinguishes "not tried yet" from "tried, got nothing"
_claude_cli_model_lock = asyncio.Lock()
_codex_cli_model: str | None = None
_codex_cli_detected = False
_codex_cli_model_lock = asyncio.Lock()


async def detect_claude_cli_model() -> str | None:
    """`claude -p ... --output-format json` (same invocation as
    stream_claude_cli, plus JSON output) echoes the real model it answered
    with in its `modelUsage` map -- e.g. {"claude-sonnet-5": {...}}. Cached
    for the process's lifetime -- including a failed attempt, via the
    `_claude_cli_detected` flag, since None is also a valid cached result
    (CLI not logged in, etc); without that distinction a failure would
    retry a real paid/quota-consuming CLI call on every single poll tick
    for the rest of the process's life instead of once. Falls back to a
    generic label at the call site if detection never succeeds.
    """
    global _claude_cli_model, _claude_cli_detected
    if _claude_cli_detected:
        return _claude_cli_model
    if shutil.which(config.CLAUDE_CLI_PATH) is None:
        return None
    async with _claude_cli_model_lock:
        if _claude_cli_detected:
            return _claude_cli_model
        try:
            resolved = shutil.which(config.CLAUDE_CLI_PATH) or config.CLAUDE_CLI_PATH
            detect_command = [resolved]
            if config.CLAUDE_CLI_MODEL:
                detect_command += ["--model", config.CLAUDE_CLI_MODEL]
            detect_command += ["-p", "hi", "--output-format", "json"]
            process = await asyncio.create_subprocess_exec(
                *detect_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(config.get_workspace_dir()),
                env=_cli_subprocess_env(),
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=60)
            data = json.loads(stdout.decode("utf-8", errors="replace"))
            model_usage = data.get("modelUsage") or {}
            if model_usage:
                _claude_cli_model = next(iter(model_usage))
        except Exception:  # noqa: BLE001 -- best-effort detection, never fatal
            pass
        _claude_cli_detected = True
    return _claude_cli_model


# Every alias the Claude CLI's own `--model` help text documents (`claude
# --help`: "Provide an alias for the latest model (e.g. 'fable', 'opus', or
# 'sonnet')") -- NOT a guess. Which of these actually work is still
# subscription-dependent (a lower tier can reject a higher alias), which is
# exactly what detect_claude_cli_models() below empirically checks rather
# than assuming every alias here is live.
CLAUDE_CLI_MODEL_ALIASES = ["opus", "sonnet", "haiku", "fable"]


@dataclass
class CliModelInfo:
    alias: str
    resolved: str


_claude_cli_models: list[CliModelInfo] = []
_claude_cli_models_detected = False
_claude_cli_models_lock = asyncio.Lock()


async def _probe_claude_cli_alias(resolved_path: str, alias: str) -> CliModelInfo | None:
    try:
        process = await asyncio.create_subprocess_exec(
            resolved_path,
            "--model",
            alias,
            "-p",
            "hi",
            "--output-format",
            "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(config.get_workspace_dir()),
            env=_cli_subprocess_env(),
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=60)
        if process.returncode != 0:
            return None
        data = json.loads(stdout.decode("utf-8", errors="replace"))
        model_usage = data.get("modelUsage") or {}
        if not model_usage:
            return None
        return CliModelInfo(alias=alias, resolved=next(iter(model_usage)))
    except Exception:  # noqa: BLE001 -- a rejected/unavailable alias is a normal, expected outcome
        return None


async def detect_claude_cli_models() -> list[CliModelInfo]:
    """Empirically probes every documented Claude CLI alias with one
    minimal real call each (run concurrently), and keeps only the ones that
    actually succeeded on this login/subscription -- this is the real fix
    for only one Claude model ever showing up in Settings/Workspace/
    routing: the old code only ever asked "what does the CLI's bare
    default resolve to", never "what's the full set this account can
    reach". Cached for the process's lifetime, same rationale as
    detect_claude_cli_model's cache: each probe is a real call against the
    user's subscription, so this must not re-run on every /models poll.
    """
    global _claude_cli_models, _claude_cli_models_detected
    if _claude_cli_models_detected:
        return _claude_cli_models
    resolved_path = shutil.which(config.CLAUDE_CLI_PATH)
    if resolved_path is None:
        return []
    async with _claude_cli_models_lock:
        if _claude_cli_models_detected:
            return _claude_cli_models
        results = await asyncio.gather(
            *(_probe_claude_cli_alias(resolved_path, alias) for alias in CLAUDE_CLI_MODEL_ALIASES)
        )
        _claude_cli_models = [r for r in results if r is not None]
        _claude_cli_models_detected = True
    return _claude_cli_models


def _find_model_field(value) -> str | None:
    """Recursively hunts a parsed JSON value for a key literally named
    "model" with a string value. Needed because the field's exact nesting
    isn't stable to depend on -- confirmed live it can sit several levels
    deep (e.g. a rollout line's top level is {timestamp, ordinal, type,
    payload}, with "model" down inside payload, not at the top) -- so a
    shallow dict.get("model") missed it in an earlier version of this
    function. Depth-first, first hit wins."""
    if isinstance(value, dict):
        found = value.get("model")
        if isinstance(found, str):
            return found
        for v in value.values():
            result = _find_model_field(v)
            if result:
                return result
    elif isinstance(value, list):
        for v in value:
            result = _find_model_field(v)
            if result:
                return result
    return None


def _read_codex_session_model(thread_id: str) -> str | None:
    """Codex's own --json event stream (unlike Claude's) doesn't report the
    model it used -- but it does report the session's thread_id, and Codex
    writes a real session log (its own record of what it actually ran)
    under ~/.codex/sessions/**/rollout-*-<thread_id>.jsonl containing a
    "model" field somewhere in its structure. Read that back rather than
    guessing."""
    sessions_dir = Path.home() / ".codex" / "sessions"
    matches = list(sessions_dir.glob(f"**/*{thread_id}*.jsonl"))
    if not matches:
        return None
    path = max(matches, key=lambda p: p.stat().st_mtime)
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                model = _find_model_field(data)
                if model:
                    return model
    except OSError:
        return None
    return None


async def detect_codex_cli_model() -> str | None:
    """Same invocation shape as stream_codex_cli, plus --json so the real
    thread_id is visible; the model itself is then read back from that
    thread's own session log (see _read_codex_session_model). Cached for
    the process's lifetime -- including a failed attempt (see
    _claude_cli_detected's docstring for why that distinction matters);
    None (falls back to a generic label at the call site) if the CLI isn't
    installed/logged in or detection fails."""
    global _codex_cli_model, _codex_cli_detected
    if _codex_cli_detected:
        return _codex_cli_model
    if shutil.which(config.CODEX_CLI_PATH) is None:
        return None
    async with _codex_cli_model_lock:
        if _codex_cli_detected:
            return _codex_cli_model
        try:
            # codex resolves to codex.cmd with no matching .exe -- bare
            # asyncio.create_subprocess_exec can't CreateProcess that
            # directly on Windows (the same issue _stream_cli already works
            # around); resolve the real target first.
            resolved = shutil.which(config.CODEX_CLI_PATH) or config.CODEX_CLI_PATH
            detect_command = [resolved, "exec", "--skip-git-repo-check"]
            if config.CODEX_CLI_MODEL:
                detect_command += ["--model", config.CODEX_CLI_MODEL]
            detect_command += ["--json", "-"]
            process = await asyncio.create_subprocess_exec(
                *detect_command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(config.get_workspace_dir()),
                env=_cli_subprocess_env(),
            )
            stdout, _ = await asyncio.wait_for(process.communicate(input=b"hi"), timeout=60)
            thread_id = None
            for line in stdout.decode("utf-8", errors="replace").splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("type") == "thread.started":
                    thread_id = event.get("thread_id")
                    break
            if thread_id:
                _codex_cli_model = _read_codex_session_model(thread_id)
        except Exception:  # noqa: BLE001 -- best-effort detection, never fatal
            pass
        _codex_cli_detected = True
    return _codex_cli_model


async def stream_gemini(messages: list[dict]) -> AsyncIterator[str]:
    key = config.gemini_api_key()
    if not key:
        raise ProviderUnavailableError("Gemini API key is not configured.")
    try:
        response = await completion(
            model=f"gemini/{config.GEMINI_MODEL}",
            messages=messages,
            api_key=key,
            stream=True,
        )
    except litellm.RateLimitError as exc:
        raise ProviderRateLimitedError(f"Gemini is rate-limited: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ProviderUnavailableError(f"Gemini call failed: {exc}") from exc

    chunks = []
    async for chunk in response:
        chunks.append(chunk)
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta

    cost_usd, tokens = _finalize_litellm_usage(chunks)
    await costs.tracker.record(cost_usd, tokens, provider="gemini")


# --- custom model connections (Settings > Models > Add Model) ---------------


async def stream_custom(
    model_id: str, api_base: str, api_key: str | None, messages: list[dict]
) -> AsyncIterator[str]:
    """Any OpenAI-compatible endpoint (self-hosted, LM Studio, vLLM, another
    router, etc) added via Settings > Models > Add Model > Custom. Routed
    through litellm's generic openai/ provider with api_base overridden --
    the standard way to point it at something other than api.openai.com.
    api_key is optional since many local OpenAI-compatible servers don't
    check one; litellm still requires *a* string, so a placeholder is used.
    """
    try:
        response = await completion(
            model=f"openai/{model_id}",
            messages=messages,
            api_base=api_base,
            api_key=api_key or "not-needed",
            stream=True,
        )
    except litellm.RateLimitError as exc:
        raise ProviderRateLimitedError(f"Custom model '{model_id}' is rate-limited: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ProviderUnavailableError(f"Custom model '{model_id}' failed: {exc}") from exc

    chunks = []
    async for chunk in response:
        chunks.append(chunk)
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta

    cost_usd, tokens = _finalize_litellm_usage(chunks)
    await costs.tracker.record(cost_usd, tokens, provider="custom")


DISCOVER_TIMEOUT_SECONDS = 20
DISCOVER_MAX_MODELS = 2000


async def discover_openai_models(api_base: str, api_key: str | None) -> list[str]:
    """Model ids an OpenAI-compatible endpoint advertises at GET /v1/models.

    Typing model ids by hand is fine for a single local server; it is the whole
    friction for a gateway that fronts hundreds of endpoints (FreeLLMAPI ships
    635), where a typo produces a model that simply never answers. Every
    OpenAI-compatible server exposes this -- LM Studio, vLLM, llama.cpp, and the
    hosted providers in the preset list above -- so this is one generic call
    rather than a per-provider integration.

    Returns ids only. Ranking or filtering them is the caller's business, and
    the shape of the rest of the payload varies far more between servers than
    `id` does.
    """
    base = (api_base or "").strip().rstrip("/")
    if not base:
        raise ProviderUnavailableError("A base URL is required to look up models.")
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=DISCOVER_TIMEOUT_SECONDS, follow_redirects=True) as client:
            response = await client.get(f"{base}/models", headers=headers)
    except httpx.HTTPError as exc:
        raise ProviderUnavailableError(f"Couldn't reach {base}: {exc}") from exc

    if response.status_code in (401, 403):
        raise ProviderUnavailableError(
            f"{base} rejected that API key ({response.status_code})."
        )
    if response.status_code == 404:
        raise ProviderUnavailableError(
            f"{base} has no /models endpoint. You can still add a model by typing its id."
        )
    if response.status_code >= 400:
        raise ProviderUnavailableError(f"{base} returned HTTP {response.status_code}.")

    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderUnavailableError(
            f"{base} didn't return JSON — check the base URL includes the /v1 path."
        ) from exc

    # OpenAI's documented shape is {"data": [{"id": ...}]}; some servers return a
    # bare list. Both are common enough in the wild to be worth handling.
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ProviderUnavailableError(f"{base} returned an unexpected /models response.")

    ids, seen = [], set()
    for row in rows[:DISCOVER_MAX_MODELS]:
        model_id = row.get("id") if isinstance(row, dict) else row
        if isinstance(model_id, str) and model_id.strip() and model_id not in seen:
            seen.add(model_id)
            ids.append(model_id.strip())
    return sorted(ids)


async def pull_ollama_model(name: str) -> AsyncIterator[dict]:
    """Streams Ollama's own /api/pull progress (NDJSON: {status, completed,
    total, ...} per line) so the UI can show real download progress instead
    of a spinner. No fixed timeout -- a model pull can legitimately take
    many minutes depending on size and connection."""
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST", f"{config.OLLAMA_BASE_URL}/api/pull", json={"name": name, "stream": True}
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                yield json.loads(line)


# --- shared dispatch helpers ------------------------------------------------


# Categories where a reasoning model's private thinking does not earn what it
# costs. Measured on qwen3.5:4b, "whats 12 percent of 250": thinking on, 755
# completion tokens and 47.8s; thinking off, 98 tokens and 7.8s -- same answer.
#
# Latency here is generation, not prefill. A 3,900-token tool prompt costs less
# than 200 generated tokens, because prefill is parallel and generation is one
# token at a time. So the lever is how much the model writes, and on a simple
# question almost all of it is thinking nobody reads.
#
# Kept ON for the categories where it genuinely changes the answer: real maths,
# code, and multi-step planning. This is about not deliberating over "what's
# 12% of 250", not about making Nova think less.
NO_THINK_CATEGORIES = frozenset({
    "quick_simple", "everyday", "general_writing", "creative_writing",
})


def wants_thinking(category: str | None) -> bool:
    return (category or "") not in NO_THINK_CATEGORIES


def _litellm_kwargs(provider: str, model: str | None, category: str | None = None) -> dict:
    """Same model-string/auth construction the stream_* functions above use,
    factored out so a caller can drive a plain litellm.acompletion (streaming
    or not) against whichever provider routing picked. Used by agent_loop and
    director."""
    if provider == "openrouter":
        return {"model": f"openrouter/{model}", "api_key": config.openrouter_api_key()}
    if provider == "ollama":
        kwargs = {"model": f"ollama_chat/{model}", "api_base": config.OLLAMA_BASE_URL}
        # Only sent when we want it off: passing think=True to a model that has
        # no thinking mode is an error on some Ollama builds, while omitting
        # the field is always valid and means "the model's own default".
        if not wants_thinking(category):
            kwargs["think"] = False
        return kwargs
    return {"model": f"gemini/{config.GEMINI_MODEL}", "api_key": config.gemini_api_key()}


DESKTOP_GROUNDING_TIMEOUT_SECONDS = 30
DESKTOP_DESCRIBE_TIMEOUT_SECONDS = 45


class DesktopGroundingError(Exception):
    """Real failure resolving a natural-language screen-element description
    to pixel coordinates. Callers treat this as "couldn't find it," not a
    crash -- see nova_tools' desktop_click_on."""


async def describe_screen(png_bytes: bytes, question: str) -> str:
    """Answer a question about what is on screen right now.

    The missing half of screen control. `resolve_screen_target` converts a
    description into coordinates, which lets Nova *act*; this lets it *look* --
    read a dialog, check whether a click worked, find out what state an app is
    in. Without it every GUI interaction is blind: click, then guess.

    Same vision model and the same real-spend accounting as grounding. Kept
    separate from it because the prompts pull in opposite directions -- one
    wants coordinates and nothing else, this wants prose.
    """
    if await costs.tracker.is_over_budget():
        raise DesktopGroundingError(
            "Today's spend budget is used up -- can't make a screen-reading call right now."
        )

    b64 = base64.b64encode(png_bytes).decode("ascii")
    prompt = (
        "This is a screenshot of the user's screen. Answer this question about it: "
        f"{question}\n\n"
        "Describe only what is actually visible. Quote on-screen text exactly. If the "
        "answer is not visible, say so rather than guessing. Be concise."
    )
    try:
        response = await asyncio.wait_for(
            completion(
                model=f"openrouter/{config.DESKTOP_GROUNDING_MODEL}",
                api_key=config.openrouter_api_key(),
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                }],
                stream=False,
            ),
            timeout=DESKTOP_DESCRIBE_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001
        raise DesktopGroundingError(f"Couldn't reach the screen-reading model: {exc}") from exc

    try:
        cost_usd = float(litellm.completion_cost(completion_response=response) or 0.0)
        tokens = int(getattr(response.usage, "total_tokens", 0) or 0)
    except Exception:  # noqa: BLE001 - cost tracking must never break the call itself
        cost_usd, tokens = 0.0, 0
    await costs.tracker.record(cost_usd, tokens, provider="openrouter")

    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise DesktopGroundingError("The screen-reading model returned nothing.")
    return text


async def resolve_screen_target(png_bytes: bytes, target: str) -> tuple[int, int]:
    """Phase 4 (RESEARCH.md, 2026-09-03): the one piece desktop.py's
    existing click/type/screenshot execution and desktop_registry.py's
    approval gate were missing -- turning a natural-language description
    of a screen element ("the login button") into real pixel coordinates,
    by actually showing the screenshot to a model instead of asking the
    calling chat model to already know coordinates it was never shown (see
    desktop_screenshot's handling below in run_desktop_tool_loop -- it
    deliberately never sends image bytes to the model, only tells it
    capture succeeded).

    Uses a dedicated call to bytedance/ui-tars-1.5-7b via OpenRouter
    (config.DESKTOP_GROUNDING_MODEL) -- a model purpose-trained for exactly
    this screenshot-to-coordinate task, independent of whatever model is
    actually running the conversation (same "small dedicated utility call
    outside the main loop" pattern as main.py's _pick_summary_model).
    **Not free** -- correcting the research pass's original finding
    (RESEARCH.md, 2026-09-03): the specific free `bytedance-research/
    ui-tars-72b:free` listing that research found no longer exists on
    OpenRouter's live model list by the time this was actually implemented
    (confirmed live against /api/v1/models -- same "the free roster moves
    on" volatility already documented for other models in RESEARCH.md's
    routing notes). This 7B variant is the only UI-TARS model currently
    listed at all, priced at $0.10/M input + $0.20/M output tokens --
    genuinely cheap (a single screenshot-sized call costs a small fraction
    of a cent) but real spend, so this respects costs.tracker's daily
    budget cap and records real cost like every other paid call in this
    file, rather than being a silent exception to that policy.

    Raises DesktopGroundingError on any failure to reach the model, an
    over-budget day, or a reply with no parseable coordinate pair --
    deliberately not the SDK's own action-parser DSL, which this doesn't
    vendor; a plain JSON ask is more robust against a model that wasn't
    specifically prompted the way bytedance's own SDK prompts it.
    """
    if await costs.tracker.is_over_budget():
        raise DesktopGroundingError("Today's spend budget is used up -- can't make a grounding call right now.")

    b64 = base64.b64encode(png_bytes).decode("ascii")
    prompt = (
        f"Here is a screenshot of the user's screen. Find this element: {target!r}. "
        "Reply with ONLY a JSON object giving the exact pixel coordinates of its "
        'center, in the form {"x": <integer>, "y": <integer>}. No other text.'
    )
    try:
        response = await asyncio.wait_for(
            completion(
                model=f"openrouter/{config.DESKTOP_GROUNDING_MODEL}",
                api_key=config.openrouter_api_key(),
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        ],
                    }
                ],
                stream=False,
            ),
            timeout=DESKTOP_GROUNDING_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001
        raise DesktopGroundingError(f"Couldn't reach the screen-grounding model: {exc}") from exc

    try:
        cost_usd = float(litellm.completion_cost(completion_response=response) or 0.0)
        tokens = int(getattr(response.usage, "total_tokens", 0) or 0)
    except Exception:  # noqa: BLE001 - cost tracking must never break grounding itself
        cost_usd, tokens = 0.0, 0
    await costs.tracker.record(cost_usd, tokens, provider="openrouter")

    raw = (response.choices[0].message.content or "").strip()
    # Verified live 2026-09-03 (RESEARCH.md): the model doesn't always
    # follow the exact schema asked for -- a real reply came back as
    # {"x": [1775, 1083]} (a coordinate pair under one key) instead of
    # separate "x"/"y" keys. Handle both shapes rather than assuming the
    # one requested in the prompt is the only one that shows up.
    match = re.search(r'"x"\s*:\s*\[\s*(-?\d+)\s*,\s*(-?\d+)\s*\]', raw)
    if not match:
        match = re.search(r'"x"\s*:\s*(-?\d+).*?"y"\s*:\s*(-?\d+)', raw, re.DOTALL)
    if not match:
        raise DesktopGroundingError(
            f"Couldn't find {target!r} -- the grounding model's reply didn't contain "
            f"parseable coordinates: {raw[:200]!r}"
        )
    return int(match.group(1)), int(match.group(2))

# Only offered to providers with a real function-calling completions API
# (same restriction run_mcp_tool_loop uses, and for the same reason:
# claude_cli/codex_cli are one-shot subprocess transcripts, no tool-calling
# surface to hook a confirmation gate into -- see main.py's call site).


class ModelCallError(Exception):
    """Raised by stream_for_result/run_model_call for a provider that needs
    more than (result, messages) to dispatch -- currently just 'custom',
    which needs its DB row's api_base/api_key looked up by the caller (see
    main.py's own /agents/chain, which already special-cases it the same
    way)."""


def stream_for_result(result, messages: list[dict]):
    """The one real provider -> stream-function dispatch table, shared by
    /chat's main loop, /agents/chain (main.py's pre-existing manual chain
    runner), and director.py's team-role task execution. `result` is a
    routing.RoutingResult; kept untyped here to avoid a routing<->providers
    import cycle (routing.py already imports this module). Does not handle
    'custom' -- that needs a DB lookup (api_base/api_key) only the caller
    has context for; callers already special-case it before reaching here
    (see /agents/chain and /chat's own dispatch)."""
    if result.provider == "hermes":
        from . import hermes
        return hermes.stream(messages)
    if result.provider == "openrouter":
        return stream_openrouter(result.model, messages)
    if result.provider == "ollama":
        return stream_ollama(result.model, messages, json_mode=getattr(result, "category", None) == "director")
    if result.provider == "claude_cli_plan":
        return stream_claude_cli(messages, model=result.model, read_only=True)
    if result.provider == "codex_cli_plan":
        return stream_codex_cli(messages, model=result.model, read_only=True)
    if result.provider == "claude_cli":
        return stream_claude_cli(messages, model=result.model)
    if result.provider == "codex_cli":
        return stream_codex_cli(messages, model=result.model)
    if result.provider == "gemini_cli":
        return stream_gemini_cli(messages)
    if result.provider == "antigravity_cli":
        return stream_antigravity_cli(messages)
    if result.provider == "custom":
        raise ModelCallError("The 'custom' provider needs its api_base/api_key row looked up by the caller.")
    if result.provider == "gemini":
        return stream_gemini(messages)
    raise ProviderUnavailableError(f"Unsupported provider: {result.provider}")


async def run_model_call(result, messages: list[dict]) -> str:
    """Runs one provider call to completion and returns the full text --
    the non-streaming counterpart to /chat's SSE dispatch, for workspace/
    team-orchestration task execution (director/worker/reviewer), which
    needs one finished result per task rather than a token-by-token
    response. Built on stream_for_result, the same dispatch every other
    caller uses -- not a second implementation of "how to call claude_cli".
    """
    stream = stream_for_result(result, messages)
    parts: list[str] = []
    try:
        async for token in stream:
            parts.append(token)
    finally:
        await stream.aclose()
    return "".join(parts)


# ---------------------------------------------------------------------------
# File tool loop
#
# The counterpart to run_desktop_tool_loop above, for the granted folders in
# file_access.py. Both follow the same shape (async generator, private
# "_final_messages" sentinel, a cheap gate so ordinary turns never pay for it).
#
# Why this exists alongside project_context's evidence block: that block is
# *pushed* -- main.py decides a message looks file-related and injects a
# directory listing plus any name/content matches before the model runs. It is
# one shot and it guesses. This loop lets the model *pull*: read the assignment
# it just found the name of, search for a phrase it only thought of after
# seeing the listing, open the file the user actually meant after asking which
# one. That is the difference between "here is what I found" and going to look.
#
# Reads are ungated -- the user already granted the folder, and a read that
# needed per-call approval would make the capability useless. Writes are gated
# through the same desktop_registry approval the desktop loop uses, so the
# existing ApprovalCallout/DesktopEventCard UI renders them with no frontend
# change: the request genuinely blocks server-side until Allow/Deny, and
# nothing is written if the user never answers. Every path still goes through
# file_access's own guardrails, so the credential deny-list, the root
# containment check and the size caps apply here exactly as they do to the
# HTTP routes.
# ---------------------------------------------------------------------------

_FILE_INTENT_RE = re.compile(
    r"\b(file|files|folder|directory|document|documents|note|notes|assignment|"
    r"homework|essay|draft|worksheet|problem set|read|open|search|find|look|"
    r"contents?|project|repo|code|script|spreadsheet|pdf|markdown)\b",
    re.I,
)


def message_mentions_files(text: str) -> bool:
    """Public form of the gate below, for callers holding only the raw user
    message. main.py uses it to decide whether resolving granted roots is
    worth doing at all -- that lookup is a settings read plus a filesystem
    resolve per root, and this loop cannot run without roots anyway."""
    return bool(_FILE_INTENT_RE.search(text or ""))




# ---------------------------------------------------------------------------
# The user's rules (backend/NOVA_RULES.md) ride at the top of every request
# through every provider. Wrapped here, once, at import time, so no caller
# can reach a model without them. Requests that also pass through
# local_inference.completion are not doubled: nova_rules marks its message.
from . import nova_rules as _nova_rules  # noqa: E402

for _name in (
    "stream_openrouter", "stream_ollama_vision", "stream_ollama", "stream_claude_cli",
    "stream_antigravity_cli", "stream_gemini_cli", "stream_codex_cli", "stream_gemini",
    "stream_custom", "stream_for_result", "run_model_call",
):
    if _name in globals() and not getattr(globals()[_name], "__nova_rules__", False):
        globals()[_name] = _nova_rules.enforce(globals()[_name])
