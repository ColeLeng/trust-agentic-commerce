"""
red/seller_agent.py -- RED 1: the seller-simulation agent.

OWNER: Red team (person 1)

Simulates the marketplace's sellers under a chosen CONTAMINATION STRATEGY and
DIFFICULTY (level). Honest sellers stay honest; dishonest sellers get a fake
flood (or subtle evasion fakes) scaled by the contamination level.

simulate_sellers(question, level, strategy) -> List[SellerProfile]
  - MOCK (no codex): deterministic marketplace from data/marketplace.py.
  - REAL (codex): same seller structure + labels/counts, but review TEXT is
    authored by red/generator + red/evasion. Counts stay deterministic so the
    contamination sweep (and the money-shot) remains stable.

TODO(red): add per-seller "difficulty" (how aggressively to evade) and a
seller-manipulation pass that rewrites the seller CLAIMS, not just reviews.
"""

from __future__ import annotations

from typing import List

from data.marketplace import build_marketplace
from llm import agent_available
from red.evasion import evolve
from red.generator import generate
from schema import BuyerQuestion, ContaminationStrategy, GroundTruth, SellerProfile
from tracing import traced


@traced
def simulate_sellers(
    question: BuyerQuestion,
    level: float,
    strategy: ContaminationStrategy = ContaminationStrategy.REVIEW_FLOOD,
) -> List[SellerProfile]:
    """Build the contaminated marketplace for one experiment cell."""
    sellers = build_marketplace(level, strategy, question.n_merchants)
    if not agent_available():
        return sellers  # deterministic mock marketplace

    # REAL mode: keep counts/labels, regenerate review text with the LLM.
    for s in sellers:
        n_fake = sum(1 for r in s.reviews if r.is_fake)
        n_clean = len(s.reviews) - n_fake
        reviews = generate(s, n_clean=n_clean, n_fake=0)  # genuine reviews
        if n_fake and s.ground_truth == GroundTruth.DIRTY:
            if strategy == ContaminationStrategy.EVASION:
                reviews += evolve(s, n=n_fake)
            else:
                reviews += generate(s, n_clean=0, n_fake=n_fake)
        s.reviews = reviews
    return sellers


if __name__ == "__main__":
    from red.question_agent import default_question

    q = default_question()
    for lvl in q.contamination_levels:
        sellers = simulate_sellers(q, lvl)
        dirty = [s for s in sellers if s.ground_truth == GroundTruth.DIRTY]
        fakes = sum(1 for s in dirty for r in s.reviews if r.is_fake)
        print(f"level {lvl:.0%}: {len(sellers)} sellers, {fakes} fake reviews on dirty sellers")
