"""
blue/planner_agent.py -- the planner that spawns isolated scouts.

OWNER: Blue team

The planner interprets the BuyerQuestion + the buyer's PersonalContext, then
SPAWNS ONE SCOUT PER SELLER -- each in its own isolated context. It collects the
structured ScoutOutputs and hands them to the concierge. The planner deliberately
does NOT merge raw seller text; it only orchestrates the sub-agents.

plan_and_dispatch(question, sellers) -> List[ScoutOutput]

This fan-out (planner -> N isolated scouts -> concierge) is what makes the system
a multi-agent harness rather than a single-prompt workflow.

TODO(blue): run scouts concurrently (thread pool) and let the planner re-dispatch
a scout with "look closer" when confidence is low.
"""

from __future__ import annotations

from typing import List

from blue.scout_agent import investigate
from schema import BuyerQuestion, ScoutOutput, SellerProfile
from tracing import traced


@traced
def plan_and_dispatch(question: BuyerQuestion, sellers: List[SellerProfile]) -> List[ScoutOutput]:
    """Spawn one isolated scout per seller; return their structured reports."""
    ctx = question.personal_context
    outputs: List[ScoutOutput] = []
    for seller in sellers:
        # Each scout gets ONLY this seller -> contamination stays quarantined.
        outputs.append(investigate(seller, ctx))
    return outputs


if __name__ == "__main__":
    from data.marketplace import build_marketplace
    from red.question_agent import default_question

    q = default_question()
    for out in plan_and_dispatch(q, build_marketplace(0.6)):
        print(f"{out.seller_id}: trust={out.trust_score} product={out.product_score} {out.recommendation.value}")
