"""
blue/concierge_agent.py -- THE master / coordinator agent (the only one).

OWNER: Blue team

This is the SINGLE master agent for the blue side. It used to live under several
names (planner / orchestrator / analyzer-loop); those are gone. Develop and
upgrade THIS file.

Responsibilities:
  1. interpret the buyer's question + personal context (the ask)
  2. SPAWN one ISOLATED scout per seller -- each scout (blue/scout_agent.scout_one)
     sees ONLY its own seller, so one seller's fake-review flood can't pollute
     another's evaluation (this fan-out is the "sophisticated harness")
  3. ADJUDICATE the scouts' STRUCTURED reports (trust_score, product_score,
     risk_flags) -- never the raw seller text -- and recommend a winner

Entry points:
  run_concierge(stores, question)  -> ConciergeDecision      # full flow (use this)
  dispatch_scouts(stores, question) -> List[ScoutReport]     # step 2 only
  adjudicate(reports)               -> ConciergeDecision      # step 3 only

Decision rule: rank by a blend of trust and product fit, but HARD-GATE on trust
(a high product score can't rescue a low-trust seller). That gate is what keeps
the fake-review flood from winning the purchase.

ConciergeDecision lives here (like ScoutReport lives in scout_agent.py) so the
frozen schema.py contract is untouched.

MOCK-FIRST: inherits scout_one's mock fallback, so this runs with no API key.

TODO(blue): LLM concierge that writes the rationale from the structured evidence
(still never touching raw seller text); concurrent scout dispatch + "look closer"
re-dispatch when a scout's confidence is low.
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from blue.scout_agent import ScoutReport, scout_one
from schema import Store
from tracing import traced

TRUST_GATE = 50.0  # below this, reject regardless of product fit
DEFAULT_QUESTION = "Find the most trustworthy seller for this product under my budget."


class RejectedSeller(BaseModel):
    seller_id: str
    reason: str


class ConciergeDecision(BaseModel):
    """The system's final pick, derived from structured scout reports only."""

    winner_seller_id: str
    why: str = ""
    ranking: List[str] = Field(default_factory=list)         # seller_ids best -> worst
    rejected: List[RejectedSeller] = Field(default_factory=list)


@traced
def dispatch_scouts(stores: List[Store], question: str = DEFAULT_QUESTION) -> List[ScoutReport]:
    """Step 2: spawn ONE isolated scout per seller. Contamination stays quarantined."""
    return [scout_one(store) for store in stores]


def _final_score(r: ScoutReport) -> float:
    # trust-weighted: product fit only counts when the seller is trustworthy
    return 0.65 * r.trust_score + 0.35 * r.product_score


@traced
def adjudicate(reports: List[ScoutReport]) -> ConciergeDecision:
    """Step 3: pick the winner from structured scout reports only."""
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


@traced
def run_concierge(stores: List[Store], question: str = DEFAULT_QUESTION) -> ConciergeDecision:
    """Full flow: spawn isolated scouts, then adjudicate their structured reports."""
    return adjudicate(dispatch_scouts(stores, question))


if __name__ == "__main__":
    from data.stores import contaminated_stores

    reports = dispatch_scouts(contaminated_stores(0.6))
    for r in reports:
        print(f"  scout {r.seller_id}: trust={r.trust_score:5.1f} product={r.product_score:5.1f} "
              f"{r.recommendation}")
    d = adjudicate(reports)
    print(f"\nconcierge winner={d.winner_seller_id}\nwhy={d.why}\nranking={d.ranking}")
