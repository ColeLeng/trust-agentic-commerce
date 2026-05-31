"""
tracing.py -- Weave (wandb) tracing wrapper.

OWNER: Glue (shared utility — everyone imports `@traced`)

Usage:
    from tracing import traced, init_tracing

    init_tracing()  # call once at program start (run.py / dashboard already do this)

    @traced
    def my_agent_step(x): ...

MOCK-FIRST: if WANDB_API_KEY is missing OR the `weave` package is not installed,
`@traced` becomes a transparent no-op decorator. Nothing breaks on a fresh clone.

TODO(glue): add per-team trace tags / a shared Weave project name once we have keys.
"""

from __future__ import annotations

import functools
import os
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

_INITIALIZED = False
_WEAVE_ACTIVE = False

WEAVE_PROJECT = os.getenv("WEAVE_PROJECT", "trust-agentic-commerce")


def init_tracing(project: str | None = None) -> bool:
    """
    Initialize Weave once. Returns True if real tracing is active, False if mocked.
    Safe to call multiple times.
    """
    global _INITIALIZED, _WEAVE_ACTIVE
    if _INITIALIZED:
        return _WEAVE_ACTIVE
    _INITIALIZED = True

    if not os.getenv("WANDB_API_KEY"):
        print("[tracing] WANDB_API_KEY not set -> tracing disabled (mock mode).")
        return False

    try:
        import weave  # type: ignore

        weave.init(project or WEAVE_PROJECT)
        _WEAVE_ACTIVE = True
        print(f"[tracing] Weave active -> project '{project or WEAVE_PROJECT}'.")
    except Exception as exc:  # pragma: no cover - depends on env
        print(f"[tracing] weave.init failed ({exc}); continuing without tracing.")
        _WEAVE_ACTIVE = False
    return _WEAVE_ACTIVE


def traced(func: F) -> F:
    """
    Decorator everyone imports. When Weave is active it wraps the call with
    `weave.op`; otherwise it's a no-op passthrough.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not _INITIALIZED:
            init_tracing()
        if _WEAVE_ACTIVE:
            try:
                import weave  # type: ignore

                return weave.op()(func)(*args, **kwargs)
            except Exception:
                return func(*args, **kwargs)
        return func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]
