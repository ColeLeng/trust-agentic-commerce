"""
llm.py -- shared LLM backend via the Codex CLI (`codex exec`).

OWNER: Glue (shared utility)

We call the model through the `codex exec` CLI instead of the Anthropic SDK, so
there's NO ANTHROPIC_API_KEY and no `anthropic` dependency. It uses your existing
Codex login (`~/.codex/auth.json`).

    agent_available()           -> bool : is the `codex` CLI installed?
    complete(system, prompt)    -> str  : one non-interactive completion's text.

MOCK-FIRST: callers MUST check `agent_available()` and provide their own mock path.
This helper never fabricates data; it only shells out to the real CLI.

Setup for real agents:
    npm install -g @openai/codex   # or: brew install codex
    codex login                    # one-time, stores ~/.codex/auth.json

TODO(glue): add a retry on empty output + an optional `--json` event stream if we
want token usage in the dashboard.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

try:  # load THIS repo's .env only (never walk up into a parent/global .env)
    from dotenv import load_dotenv

    _local_env = Path(__file__).resolve().parent / ".env"
    if _local_env.exists():
        load_dotenv(dotenv_path=_local_env)
except Exception:
    pass

CODEX_BIN = os.getenv("CODEX_BIN", "codex")
CODEX_MODEL = os.getenv("CODEX_MODEL")  # optional, e.g. "gpt-5.5"; None = codex default


def agent_available() -> bool:
    """True when the codex CLI is installed (real-agent mode is possible)."""
    return shutil.which(CODEX_BIN) is not None


# Backwards-compat alias: earlier code referenced have_api_key().
def have_api_key() -> bool:
    return agent_available()


def complete(
    system: str,
    prompt: str,
    max_tokens: int = 1024,  # kept for call-site compatibility; codex manages its own
    model: str | None = None,
    timeout: int = 180,
) -> str:
    """
    Run one non-interactive Codex completion and return the final message text.
    Raises if the CLI is missing — callers should gate on agent_available() first.

    The system + prompt are concatenated (codex exec has no separate system slot).
    Runs with `-s read-only` so the agent can't modify the workspace; the answer
    is captured via `--output-last-message` for clean, log-free text.
    """
    if not agent_available():
        raise RuntimeError("codex CLI not found; call agent_available() and use a mock.")

    combined = (
        f"{system.strip()}\n\n{prompt.strip()}\n\n"
        "Output ONLY what was requested. No preamble, no explanation, no code fences."
    )

    out_fd, out_path = tempfile.mkstemp(suffix=".txt", prefix="codex_")
    os.close(out_fd)
    cmd = [
        CODEX_BIN, "exec",
        "--skip-git-repo-check",
        "-s", "read-only",
        "--color", "never",
        "-o", out_path,
    ]
    m = model or CODEX_MODEL
    if m:
        cmd += ["-m", m]
    cmd += ["-"]  # read prompt from stdin

    try:
        subprocess.run(
            cmd, input=combined, text=True,
            capture_output=True, timeout=timeout, check=False,
        )
        return Path(out_path).read_text(encoding="utf-8", errors="ignore").strip()
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass
