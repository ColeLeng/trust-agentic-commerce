"""
llm.py -- shared Anthropic client helper.

OWNER: Glue (shared utility)

`have_api_key()` -> bool tells any module whether to run real agents or mocks.
`complete(system, prompt)` -> str calls Claude when a key exists.

MOCK-FIRST: callers MUST check `have_api_key()` and provide their own mock path.
This helper never fabricates data; it only talks to the real API.

TODO(glue): add retry/backoff + a cheaper model toggle if we hit rate limits.
"""

from __future__ import annotations

import os
from pathlib import Path

try:  # load THIS repo's .env only (never walk up into a parent/global .env)
    from dotenv import load_dotenv

    _local_env = Path(__file__).resolve().parent / ".env"
    if _local_env.exists():
        load_dotenv(dotenv_path=_local_env)
except Exception:
    pass

DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")


def have_api_key() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def complete(system: str, prompt: str, max_tokens: int = 1024, model: str | None = None) -> str:
    """Call Claude. Raises if no key — callers should gate on have_api_key() first."""
    if not have_api_key():
        raise RuntimeError("ANTHROPIC_API_KEY missing; call have_api_key() and use a mock.")

    from anthropic import Anthropic

    client = Anthropic()
    resp = client.messages.create(
        model=model or DEFAULT_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
