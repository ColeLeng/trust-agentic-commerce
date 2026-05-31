"""
blue/concierge_agent.py -- adjudicates the scouts' STRUCTURED outputs.

OWNER: Blue team

The concierge is the final decision-maker. Crucially it sees ONLY ScoutReports
(trust_score, product_score, risk_flags) -- NEVER the raw seller reviews/claims.
Because the contamination lives in the raw text and the isolated scouts already
quarantined it, the concierge's input is clean structured signal.

adjudicate(reports) -> ConciergeDecision

Decision rule: rank by a blend of trust and product fit, but HARD-GATE on trust
(a high product score can't rescue a low-trust seller). That gate is what keeps
the fake-review flood from winning the purchase.

ConciergeDecision is defined here (like ScoutReport lives in scout_agent.py) to
avoid touching the frozen schema.py contract.

TODO(blue): optional LLM concierge that writes the rationale from the structured
evidence (still never touching raw seller text).
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from blue.scout_agent import ScoutReport
from tracing import traced

TRUST_GATE = 50.0  # below this, reject regardless of product fit


class RejectedSeller(BaseModel):
    seller_id: str
    reason: str


class ConciergeDecision(BaseModel):
    """The isolated system's final pick, from structured scout reports only."""

    winner_seller_id: str
    why: str = ""
    ranking: List[str] = Field(default_factory=list)         # seller_ids best -> worst
    rejected: List[RejectedSeller] = Field(default_factory=list)


def _final_score(r: ScoutReport) -> float:
    # trust-weighted: product fit only counts when the seller is trustworthy
    return 0.65 * r.trust_score + 0.35 * r.product_score


@traced
def adjudicate(reports: List[ScoutReport]) -> ConciergeDecision:
    """Pick the winner from structured scout reports only."""
    if not reports:
        return ConciergeDecision(winner_seller_id="", why="No scout reports.")

    eligible = [r for r in reports if r.trust_score >= TRUST_GATE and r.recommendation != "risky"]
    pool = eligible or reports  # if everyone is risky, still pick the least-bad
    ranked = sorted(pool, key=_final_score, reverse=True)
    full = sorted(reports, key=_final_score, reverse=True)
    winner = ranked[0]

    rejected = [
        RejectedSeller(
            seller_id=r.seller_id,
            reason=(f"trust {r.trust_score:.0f}/100"
                    + (f", flags: {', '.join(r.risk_flags[:3])}" if r.risk_flags else "")),
        )
        for r in full if r.seller_id != winner.seller_id
    ]
    why = (
        f"Picked {winner.seller_id}: trust {winner.trust_score:.0f}/100 + product fit "
        f"{winner.product_score:.0f}/100. Rejected higher-hype sellers whose isolated "
        f"scouts flagged contaminated reviews (trust below {TRUST_GATE:.0f})."
    )
    return ConciergeDecision(
        winner_seller_id=winner.seller_id, why=why,
        ranking=[r.seller_id for r in full], rejected=rejected,
    )


if __name__ == "__main__":
    from blue.planner_agent import plan_and_dispatch
    from data.stores import contaminated_stores

    d = adjudicate(plan_and_dispatch(contaminated_stores(0.6)))
    print(f"winner={d.winner_seller_id}\nwhy={d.why}\nranking={d.ranking}")
