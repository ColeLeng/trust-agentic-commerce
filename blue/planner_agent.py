"""
blue/planner_agent.py -- the planner that spawns ISOLATED scouts.

OWNER: Blue team

The planner interprets the buyer's question + personal context, then SPAWNS ONE
SCOUT PER SELLER -- each scout (blue/scout_agent.scout_one) sees ONLY its own
seller's data. The planner collects the structured ScoutReports and hands them to
the concierge. It never merges raw seller text, so one seller's fake-review flood
can't pollute another seller's evaluation.

This fan-out (planner -> N isolated scouts -> concierge) is what makes the system
a multi-agent harness rather than a single-prompt workflow.

plan_and_dispatch(stores, question) -> List[ScoutReport]

MOCK-FIRST: inherits scout_one's mock fallback, so this runs with no API key.

TODO(blue): run scouts concurrently and re-dispatch a "look closer" pass when a
scout's confidence is low.
"""

from __future__ import annotations

from typing import List

from blue.scout_agent import ScoutReport, scout_one
from schema import Store
from tracing import traced

DEFAULT_QUESTION = "Find the most trustworthy seller for this product under my budget."


@traced
def plan_and_dispatch(stores: List[Store], question: str = DEFAULT_QUESTION) -> List[ScoutReport]:
    """Spawn one isolated scout per store; return their structured reports."""
    reports: List[ScoutReport] = []
    for store in stores:
        # Each scout gets ONLY this store -> contamination stays quarantined.
        reports.append(scout_one(store))
    return reports


if __name__ == "__main__":
    from data.stores import contaminated_stores

    for r in plan_and_dispatch(contaminated_stores(0.6)):
        print(f"{r.seller_id}: trust={r.trust_score:5.1f} product={r.product_score:5.1f} "
              f"{r.recommendation:10s} flags={r.risk_flags}")
