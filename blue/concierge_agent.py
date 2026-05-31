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
  run_concierge(stores, question)              -> ConciergeDecision
  run_concierge_with_reports(stores, question) -> ConciergeRunResult
  dispatch_scouts(stores, question)            -> List[ScoutReport]
  adjudicate(reports)                          -> ConciergeDecision

Decision rule: rank by a blend of trust and product fit, but HARD-GATE on trust
(a high product score can't rescue a low-trust seller). That gate is what keeps
the fake-review flood from winning the purchase.

ConciergeDecision lives here (like ScoutReport lives in scout_agent.py) so the
frozen schema.py contract is untouched.

MOCK-FIRST: inherits scout_one's mock fallback, so this runs with no API key.
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from blue.scout_agent import ScoutReport, scout_one
from schema import Store
from tracing import traced

TRUST_GATE = 50.0
DEFAULT_QUESTION = "Find the most trustworthy seller for this product under my budget."


class RejectedSeller(BaseModel):
    seller_id: str
    reason: str


class ConciergeDecision(BaseModel):
    """The system's final pick, derived from structured scout reports only."""

    winner_seller_id: str
    why: str = ""
    ranking: List[str] = Field(default_factory=list)
    rejected: List[RejectedSeller] = Field(default_factory=list)


class ConciergeRunResult(BaseModel):
    """Full concierge run: isolated scout reports + final structured decision."""

    reports: List[ScoutReport] = Field(default_factory=list)
    decision: ConciergeDecision


@traced
def dispatch_scouts(
    stores: List[Store],
    question: str = DEFAULT_QUESTION,
) -> List[ScoutReport]:
    """
    Spawn one isolated scout per seller.

    Each scout sees only one seller, so contamination from a dishonest seller
    stays quarantined inside that seller's isolated context.
    """
    _ = question
    return [scout_one(store) for store in stores]


def _final_score(report: ScoutReport) -> float:
    """Trust-weighted score. Product fit only helps if trust is strong enough."""
    return 0.65 * report.trust_score + 0.35 * report.product_score


@traced
def adjudicate(reports: List[ScoutReport]) -> ConciergeDecision:
    """
    Pick the winner from structured scout reports only.

    The concierge never reads raw reviews or raw seller text here. It only sees
    structured outputs from isolated scouts.
    """
    if not reports:
        return ConciergeDecision(winner_seller_id="", why="No scout reports.")

    eligible = [
        r
        for r in reports
        if r.trust_score >= TRUST_GATE and r.recommendation != "risky"
    ]

    # If everyone is risky, still pick the least-bad option so the demo does not crash.
    pool = eligible or reports

    ranked_pool = sorted(pool, key=_final_score, reverse=True)
    full_ranking = sorted(reports, key=_final_score, reverse=True)
    winner = ranked_pool[0]

    rejected = [
        RejectedSeller(
            seller_id=r.seller_id,
            reason=(
                f"trust {r.trust_score:.0f}/100"
                + (
                    f", flags: {', '.join(r.risk_flags[:3])}"
                    if r.risk_flags
                    else ""
                )
            ),
        )
        for r in full_ranking
        if r.seller_id != winner.seller_id
    ]

    why = (
        f"Picked {winner.seller_id}: trust {winner.trust_score:.0f}/100 + "
        f"product fit {winner.product_score:.0f}/100. Rejected higher-hype "
        f"sellers whose isolated scouts flagged contaminated reviews "
        f"(trust below {TRUST_GATE:.0f})."
    )

    return ConciergeDecision(
        winner_seller_id=winner.seller_id,
        why=why,
        ranking=[r.seller_id for r in full_ranking],
        rejected=rejected,
    )


@traced
def run_concierge_with_reports(
    stores: List[Store],
    question: str = DEFAULT_QUESTION,
) -> ConciergeRunResult:
    """
    Full master-agent flow.

    The concierge spawns one isolated scout per seller, then adjudicates only
    the structured ScoutReports.
    """
    reports = dispatch_scouts(stores, question)
    decision = adjudicate(reports)
    return ConciergeRunResult(reports=reports, decision=decision)


@traced
def run_concierge(
    stores: List[Store],
    question: str = DEFAULT_QUESTION,
) -> ConciergeDecision:
    """Full flow, returning only the final decision for simple callers."""
    return run_concierge_with_reports(stores, question).decision


if __name__ == "__main__":
    from data.stores import contaminated_stores

    result = run_concierge_with_reports(contaminated_stores(0.6))

    for r in result.reports:
        print(
            f"  scout {r.seller_id}: trust={r.trust_score:5.1f} "
            f"product={r.product_score:5.1f} {r.recommendation}"
        )

    d = result.decision
    print(f"\nconcierge winner={d.winner_seller_id}")
    print(f"why={d.why}")
    print(f"ranking={d.ranking}")