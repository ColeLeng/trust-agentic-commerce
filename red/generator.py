"""
red/generator.py -- LLM review generator (fake + clean).

OWNER: Red team

generate(store, n_clean, n_fake) -> List[Review]
  - With ANTHROPIC_API_KEY: Claude writes realistic genuine reviews AND planted
    fakes for the given store (category/price aware).
  - With NO key: deterministic mock reviews from data.stores.seed_reviews.

The `is_fake` ground-truth label is set HERE by red. Blue must not peek at it.

TODO(red):
  - Tune the fake prompt so 5-star spam isn't TOO obvious (move subtlety to evasion.py).
  - Vary author names + timestamps to simulate review "bursts" for blue to catch.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import List

from llm import complete, have_api_key
from schema import Review, ReviewSource, Store
from tracing import traced

CLEAN_SYSTEM = (
    "You write SHORT, realistic, genuine Amazon product reviews. Mixed ratings "
    "(2-5 stars), specific details, minor gripes, natural typos. No marketing hype."
)
FAKE_SYSTEM = (
    "You write FAKE promotional Amazon reviews designed to inflate a product's "
    "rating: 5 stars, generic praise, exclamation marks, vague, repetitive. "
    "These are the kind of reviews a paid review farm produces."
)


def _prompt(store: Store, n: int, kind: str) -> str:
    return (
        f"Product: {store.name} (category: {store.category}, ${store.price}).\n"
        f"Write {n} {kind} reviews. Return ONLY a JSON array of objects with keys "
        f'"rating" (number 1-5), "text" (string), "author" (short username).'
    )


def _parse(raw: str, store: Store, kind: ReviewSource, start: int) -> List[Review]:
    """Parse the LLM JSON array into Review objects. Tolerant of code fences."""
    raw = raw.strip().lstrip("`").rstrip("`")
    if raw.startswith("json"):
        raw = raw[4:]
    first, last = raw.find("["), raw.rfind("]")
    items = json.loads(raw[first : last + 1]) if first != -1 else []
    reviews: List[Review] = []
    is_fake = kind in (ReviewSource.LLM_FAKE, ReviewSource.LLM_EVASION)
    for i, it in enumerate(items):
        reviews.append(
            Review(
                review_id=f"{store.store_id}-g{start + i:02d}",
                store_id=store.store_id,
                rating=float(it.get("rating", 5.0)),
                text=str(it.get("text", "")).strip(),
                author=str(it.get("author", "buyer")).strip() or "buyer",
                timestamp=store.reviews[0].timestamp + timedelta(minutes=i) if store.reviews else None,  # type: ignore[arg-type]
                verified_purchase=not is_fake,
                source=kind,
                is_fake=is_fake,
            )
        )
    return reviews


@traced
def generate(store: Store, n_clean: int = 8, n_fake: int = 4) -> List[Review]:
    """Generate a mix of clean + fake reviews for a store."""
    if not have_api_key():
        # MOCK PATH: reuse deterministic seeded reviews.
        from data.stores import seed_reviews

        return seed_reviews(store, n=n_clean + n_fake)

    reviews: List[Review] = []
    if n_clean:
        reviews += _parse(
            complete(CLEAN_SYSTEM, _prompt(store, n_clean, "genuine")),
            store, ReviewSource.LLM_CLEAN, start=0,
        )
    if n_fake:
        reviews += _parse(
            complete(FAKE_SYSTEM, _prompt(store, n_fake, "fake promotional")),
            store, ReviewSource.LLM_FAKE, start=n_clean,
        )
    return reviews


if __name__ == "__main__":
    from data.stores import STORES

    rs = generate(STORES[3])
    print(f"generated {len(rs)} reviews "
          f"({sum(r.is_fake for r in rs)} fake) | real_agents={have_api_key()}")
