"""
data/stores.py -- the 6 stores under audit + mock review seeding.

OWNER: Data / Glue

3 CLEAN stores (is_dirty=False) + 3 DIRTY stores (is_dirty=True, seeded with fakes).
ASINs/categories/prices are flavored from real Amazon listings.

MOCK-FIRST: `seed_reviews(store)` always returns a populated review list with NO
API key. When red/generator runs (key present), run.py replaces these with
LLM-generated reviews instead.

TODO(data): swap mock_reviews flavor text for category-specific templates so the
demo catalog reads more realistically per product type.
"""

from __future__ import annotations

import hashlib
import random
from typing import List

from schema import Review, ReviewSource, Store

# ---------------------------------------------------------------------------
# The catalog. 3 clean, 3 dirty. is_dirty is GROUND TRUTH for the eval.
# ---------------------------------------------------------------------------
STORES: List[Store] = [
    # ---- CLEAN ----
    Store(store_id="s1", name="Anker PowerCore Hub", category="Electronics",
          asin="B07S829LBX", price=39.99, is_dirty=False),
    Store(store_id="s2", name="Hydro Flask Outfitters", category="Sports & Outdoors",
          asin="B083GBZJ5L", price=44.95, is_dirty=False),
    Store(store_id="s3", name="CeraVe Daily Skin Co", category="Beauty",
          asin="B00TTD9BRC", price=16.08, is_dirty=False),
    # ---- DIRTY (planted fakes) ----
    Store(store_id="s4", name="LumeGlow Beauty Deals", category="Beauty",
          asin="B09XB4M2YT", price=12.99, is_dirty=True),
    Store(store_id="s5", name="ProMax Gadget Outlet", category="Electronics",
          asin="B08L5VG843", price=23.49, is_dirty=True),
    Store(store_id="s6", name="EliteFit Supplements Hub", category="Health & Household",
          asin="B07YGZ7C4N", price=29.95, is_dirty=True),
]

CLEAN_TEMPLATES = [
    "Solid product, exactly as described. Shipping took 3 days, no complaints.",
    "Been using it for a month now and it holds up well. Worth the price.",
    "Pretty good overall. The build quality could be slightly better but I'm happy.",
    "Does what it says. Not life-changing but reliable and I'd buy again.",
    "Decent value. Had a small issue with packaging but the item itself is fine.",
    "Works great for my needs. The instructions were a little thin though.",
    "Happy with this purchase, it's lasted longer than my previous one.",
    "Good but not perfect. Battery/usage life is a bit shorter than I hoped.",
]

# Fakes: over-the-top, repetitive, generic, 5-star, exclamation-heavy.
FAKE_TEMPLATES = [
    "BEST PRODUCT EVER!!! Amazing quality, amazing price, buy it now!!!",
    "Absolutely perfect!!! 10/10 would recommend to everyone I know!!!",
    "This changed my life!!! Five stars is not enough, deserves a hundred!!!",
    "Incredible!!! Fast shipping, perfect item, the best seller on Amazon!!!",
    "Wow just wow!!! Everyone needs to buy this immediately, no regrets!!!",
    "Top quality!!! My whole family loves it!!! Best purchase of the year!!!",
]

CLEAN_AUTHORS = ["jdoe21", "mariam_k", "trailrunner", "skeptic_sam", "quietbuyer", "n.patel"]
FAKE_AUTHORS = ["happy_customer", "verified_buyer99", "best_deals", "review_pro", "shopper2024"]


def _rng(store_id: str) -> random.Random:
    """Deterministic RNG so the mock catalog is identical on every clone."""
    seed = int(hashlib.sha256(store_id.encode()).hexdigest(), 16) % (2**32)
    return random.Random(seed)


def seed_reviews(store: Store, n: int = 12) -> List[Review]:
    """
    Deterministic mock reviews. Dirty stores get a heavy dose of fakes;
    clean stores get mostly genuine reviews with maybe one borderline.
    """
    rng = _rng(store.store_id)
    reviews: List[Review] = []
    fake_share = 0.55 if store.is_dirty else 0.08

    for i in range(n):
        is_fake = rng.random() < fake_share
        if is_fake:
            text = rng.choice(FAKE_TEMPLATES)
            rating = 5.0
            author = rng.choice(FAKE_AUTHORS)
            source = ReviewSource.MOCK
        else:
            text = rng.choice(CLEAN_TEMPLATES)
            rating = float(rng.choice([3.0, 4.0, 4.0, 5.0, 4.5]))
            author = rng.choice(CLEAN_AUTHORS)
            source = ReviewSource.MOCK
        reviews.append(
            Review(
                review_id=f"{store.store_id}-r{i:02d}",
                store_id=store.store_id,
                rating=rating,
                text=text,
                author=author,
                verified_purchase=not is_fake and rng.random() < 0.8,
                source=source,
                is_fake=is_fake,
            )
        )
    return reviews


def load_stores(with_mock_reviews: bool = True, n: int = 12) -> List[Store]:
    """Return fresh Store copies. If with_mock_reviews, attach deterministic reviews."""
    stores = [s.model_copy(deep=True) for s in STORES]
    if with_mock_reviews:
        for s in stores:
            s.reviews = seed_reviews(s, n=n)
    return stores


if __name__ == "__main__":
    for s in load_stores():
        fakes = sum(1 for r in s.reviews if r.is_fake)
        print(f"{s.store_id} {s.name:28s} dirty={s.is_dirty!s:5s} "
              f"reviews={len(s.reviews)} planted_fakes={fakes}")
