"""
blue/concierge_agent.py -- adjudicates the scouts' STRUCTURED outputs.

OWNER: Blue team

The concierge is the final decision-maker. Crucially, it sees ONLY ScoutOutputs
(trust_score, product_score, risk_flags, evidence) -- NEVER the raw seller
reviews/claims. Because the contamination lives in the raw text and the scouts
already quarantined it, the concierge's input is clean structured signal.

adjudicate(scout_outputs, context) -> ConciergeDecision

Decision rule: rank by a blend of trust and product fit, but HARD-GATE on trust
(a high product score can't rescue a low-trust seller). This is what keeps the
fake-review flood from winning.

TODO(blue): add an LLM concierge that writes the `why` narrative from the
structured evidence (still never touching raw seller text).
"""

from __future__ import annotations

from typing import List

from schema import ConciergeDecision, PersonalContext, Recommendation, RejectedSeller, ScoutOutput
from tracing import traced

TRUST_GATE = 45.0  # below this, a seller is rejected regardless of product fit


def _final_score(out: ScoutOutput) -> float:
    # trust-weighted: product fit only counts when the seller is trustworthy
    return 0.65 * out.trust_score + 0.35 * out.product_score


@traced
def adjudicate(scout_outputs: List[ScoutOutput], context: PersonalContext) -> ConciergeDecision:
    """Pick the winner from structured scout reports only."""
    if not scout_outputs:
        return ConciergeDecision(winner_seller_id="", why="No scouts reported.")

    trusted = [o for o in scout_outputs if o.trust_score >= TRUST_GATE
               and o.recommendation != Recommendation.RISKY]
    pool = trusted or scout_outputs  # if everyone is risky, still pick the least-bad
    ranked = sorted(pool, key=_final_score, reverse=True)
    full_ranked = sorted(scout_outputs, key=_final_score, reverse=True)
    winner = ranked[0]

    rejected = [
        RejectedSeller(
            seller_id=o.seller_id,
            reason=(f"trust {o.trust_score:.0f}/100"
                    + (f", flags: {', '.join(o.risk_flags[:3])}" if o.risk_flags else "")),
        )
        for o in full_ranked if o.seller_id != winner.seller_id
    ]
    why = (
        f"Picked {winner.seller_id}: trust {winner.trust_score:.0f}/100 and product "
        f"fit {winner.product_score:.0f}/100. Rejected higher-hype sellers whose scouts "
        f"flagged contaminated reviews (trust below {TRUST_GATE:.0f})."
    )
    return ConciergeDecision(
        winner_seller_id=winner.seller_id,
        why=why,
        ranking=[o.seller_id for o in full_ranked],
        rejected=rejected,
    )


if __name__ == "__main__":
    from blue.planner_agent import plan_and_dispatch
    from data.marketplace import build_marketplace
    from red.question_agent import default_question

    q = default_question()
    outs = plan_and_dispatch(q, build_marketplace(0.6))
    d = adjudicate(outs, q.personal_context)
    print(f"winner={d.winner_seller_id}\nwhy={d.why}\nranking={d.ranking}")
