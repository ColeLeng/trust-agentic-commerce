"""
examples/cheapest_agent.py -- the smallest agent you can plug into the sweep.

    python experiments/contamination_sweep.py --skip-isolated \
        --agent examples.cheapest_agent:choose

Your agent gets the same sellers the baseline sees (schema.Store, raw reviews
included) and returns one seller_id. Swap in your own model call here.
"""

from typing import List

from schema import Store


def choose(stores: List[Store], question: str) -> str:
    """Pick the best-rated seller, breaking ties on price."""
    def avg(s: Store) -> float:
        return sum(r.rating for r in s.reviews) / len(s.reviews) if s.reviews else 0.0
    return max(stores, key=lambda s: (avg(s), -s.price)).store_id
