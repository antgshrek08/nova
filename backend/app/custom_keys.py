"""Any API key the user has, by a name they choose.

The model guide covers the services Nova knows. This is for everything else:
the user types a name ("Jev", "Together", "my school's AI"), pastes the key,
and optionally the service's web address. Nova then does the most useful
honest thing with it:

- a name Nova recognizes goes where that key belongs (Jev/TypeSafe is
  verified with a real call; OpenRouter and Gemini are Nova settings; the
  services in model_catalog use their known address);
- with an address that serves models (the OpenAI-compatible /models list,
  which nearly every provider offers), its models are listed to pick from;
- otherwise the key is kept under its name in the same .env file as every
  other key (NAME_API_KEY), where Nova's tools and connectors can use it.

Keys are never returned to the client; only their names.
"""
from __future__ import annotations

import re

from . import config

INDEX = "NOVA_CUSTOM_KEYS"  # comma-separated env names of keys saved here


def env_name(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()
    if not slug:
        raise ValueError("Give the key a name, like the service it's for.")
    return slug if slug.endswith("_API_KEY") else f"{slug}_API_KEY"


def match(name: str) -> str | None:
    """The known home for a key with this name, if Nova has one."""
    n = re.sub(r"[^a-z0-9]", "", name.lower())
    if n in {"jev", "typesafe", "typesafejev", "typesafeai"}:
        return "typesafe"
    if n in {"openrouter"}:
        return "openrouter"
    if n in {"gemini", "google", "googlegemini", "googleai", "aistudio"}:
        return "gemini"
    from .model_catalog import CATALOG
    for item in CATALOG:
        if item.get("api_base") and n in {re.sub(r"[^a-z0-9]", "", item["id"]), re.sub(r"[^a-z0-9]", "", item["name"].lower())}:
            return item["id"]
    return None


def saved() -> list[dict]:
    names = [x for x in (config.read_env_value(INDEX) or "").split(",") if x]
    return [{"env": e, "name": e.removesuffix("_API_KEY").replace("_", " ").title(), "set": bool(config.read_env_value(e))} for e in names]


def store(name: str, key: str) -> dict:
    env = env_name(name)
    config.write_env_value(env, key.strip())
    names = [x for x in (config.read_env_value(INDEX) or "").split(",") if x]
    if env not in names:
        names.append(env)
        config.write_env_value(INDEX, ",".join(names))
    return {"env": env, "name": name.strip()}


def forget(env: str) -> None:
    import os
    from dotenv import unset_key
    names = [x for x in (config.read_env_value(INDEX) or "").split(",") if x and x != env]
    # Remove the lines themselves rather than leave empty keys behind.
    for gone in [env] + ([] if names else [INDEX]):
        unset_key(str(config.ENV_PATH), gone)
        os.environ.pop(gone, None)
    if names:
        config.write_env_value(INDEX, ",".join(names))
