"""
cost_meter.py -- track live Anthropic spend and stop before it exceeds a budget.

OWNER: Glue

Every live call site records its `usage` here. Before each call, `check_budget()`
raises BudgetExceeded once the running total reaches MAX_COST_USD (default $10),
so a live sweep can never run up a surprise bill.

Live failures are never silent: in strict mode (LIVE_STRICT=1, set by the sweep)
a failed live call raises; otherwise it is counted in `fallbacks` and reported.

Prices are USD per 1M tokens (input, output), first-party API rates.
"""

from __future__ import annotations

import os
from typing import Dict, Tuple

PRICES: Dict[str, Tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
_UNKNOWN_PRICE = (10.00, 50.00)  # unknown model: assume the most expensive tier


class BudgetExceeded(RuntimeError):
    pass


_spent_usd = 0.0
calls = 0
fallbacks = 0
_by_model: Dict[str, Dict[str, float]] = {}


def client_kwargs() -> dict:
    """Extra anthropic.Anthropic() kwargs. Keys not scoped to a workspace need
    the anthropic-workspace-id header; set ANTHROPIC_WORKSPACE_ID for those."""
    ws = os.getenv("ANTHROPIC_WORKSPACE_ID")
    return {"default_headers": {"anthropic-workspace-id": ws}} if ws else {}


def max_cost_usd() -> float:
    return float(os.getenv("MAX_COST_USD", "10"))


def strict() -> bool:
    return os.getenv("LIVE_STRICT") == "1"


def cost_of(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES.get(model, _UNKNOWN_PRICE)
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def check_budget() -> None:
    if _spent_usd >= max_cost_usd():
        raise BudgetExceeded(
            f"Spent ${_spent_usd:.2f}, budget is ${max_cost_usd():.2f} "
            "(raise MAX_COST_USD to continue)."
        )


def record(model: str, usage) -> None:
    """Record one response's usage (anthropic `Message.usage`)."""
    global _spent_usd, calls
    tokens_in = (
        (getattr(usage, "input_tokens", 0) or 0)
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        + (getattr(usage, "cache_read_input_tokens", 0) or 0)
    )
    tokens_out = getattr(usage, "output_tokens", 0) or 0
    usd = cost_of(model, tokens_in, tokens_out)
    _spent_usd += usd
    calls += 1
    m = _by_model.setdefault(model, {"calls": 0, "in": 0, "out": 0, "usd": 0.0})
    m["calls"] += 1
    m["in"] += tokens_in
    m["out"] += tokens_out
    m["usd"] += usd


def live_failed(where: str, err: Exception) -> None:
    """A live call failed: raise in strict mode, otherwise count the fallback."""
    global fallbacks
    if isinstance(err, BudgetExceeded):
        raise err
    if strict():
        raise RuntimeError(f"Live call failed in {where}: {err!r}") from err
    fallbacks += 1


def spent_usd() -> float:
    return _spent_usd


def summary() -> str:
    lines = [f"Live API calls: {calls}  |  failed->mock fallbacks: {fallbacks}  |  "
             f"spent: ${_spent_usd:.2f} (budget ${max_cost_usd():.2f})"]
    for model, m in sorted(_by_model.items()):
        lines.append(f"  {model:20s} {int(m['calls']):4d} calls  "
                     f"{int(m['in']):>8,} in  {int(m['out']):>8,} out  ${m['usd']:.2f}")
    return "\n".join(lines)


def reset() -> None:
    global _spent_usd, calls, fallbacks
    _spent_usd, calls, fallbacks = 0.0, 0, 0
    _by_model.clear()
