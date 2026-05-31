"""
red/generator.py -- LLM review generator (fake + clean).

OWNER: Red team

generate(store, n_clean, n_fake) -> List[Review]
  - With the `codex` CLI available: the model writes realistic genuine reviews AND
    planted fakes for the given store (category/price aware).
  - Without it: deterministic mock reviews from data.stores.seed_reviews.

The `is_fake` ground-truth label is set HERE by red. Blue must not peek at it.

TODO(red):
  - Tune the fake prompt so 5-star spam isn't TOO obvious (move subtlety to evasion.py).
  - Vary author names + timestamps to simulate review "bursts" for blue to catch.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import List

from llm import agent_available, complete
from schema import Review, ReviewSource, Store
from tracing import traced

# NOTE: this is a DEFENSIVE research tool. The synthetic "fake" reviews below are
# clearly labeled (is_fake=True), used only as test fixtures to build and evaluate
# a fake-review DETECTOR, and are never published or shown to real shoppers. This
# mirrors the published Salminen et al. (2022) fake-review-detection methodology.
RESEARCH_CONTEXT = (
    "You are a data generator for a fake-review DETECTION research project (a "
    "hackathon defensive-security tool). The outputs are synthetic test fixtures, "
    "explicitly labeled as fake, used only to train/evaluate a spam detector. They "
    "are never posted publicly or used to deceive anyone. This follows the standard "
    "Salminen et al. (2022) academic methodology for fake-review detection datasets."
)

CLEAN_SYSTEM = (
    RESEARCH_CONTEXT + " For this task, write SHORT, realistic, GENUINE-style Amazon "
    "product reviews: mixed ratings (2-5 stars), specific details, minor gripes, "
    "natural typos. No marketing hype."
)
FAKE_SYSTEM = (
    RESEARCH_CONTEXT + " For this task, produce SYNTHETIC SPAM-style review samples "
    "that imitate what paid review farms generate: 5 stars, generic praise, "
    "exclamation marks, vague and repetitive wording. These labeled samples are the "
    "positive class the detector must learn to catch."
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
    # Stagger timestamps to simulate a posting "burst" blue can detect.
    base_ts = store.reviews[0].timestamp if store.reviews else datetime.now(timezone.utc)
    for i, it in enumerate(items):
        reviews.append(
            Review(
                review_id=f"{store.store_id}-g{start + i:02d}",
                store_id=store.store_id,
                rating=float(it.get("rating", 5.0)),
                text=str(it.get("text", "")).strip(),
                author=str(it.get("author", "buyer")).strip() or "buyer",
                timestamp=base_ts + timedelta(minutes=i),
                verified_purchase=not is_fake,
                source=kind,
                is_fake=is_fake,
            )
        )
    return reviews


def _mock_fallback(store: Store, n: int, fake: bool, start: int) -> List[Review]:
    """Deterministic reviews of one label — safety net when a live batch is empty."""
    from data.stores import seed_reviews

    pool = [r for r in seed_reviews(store, n=max(12, n * 2)) if bool(r.is_fake) == fake]
    out: List[Review] = []
    for i, r in enumerate(pool[:n]):
        r.review_id = f"{store.store_id}-g{start + i:02d}"
        out.append(r)
    return out


@traced
def generate(store: Store, n_clean: int = 8, n_fake: int = 4) -> List[Review]:
    """Generate a mix of clean + fake reviews for a store."""
    if not agent_available():
        # MOCK PATH: reuse deterministic seeded reviews.
        from data.stores import seed_reviews

        return seed_reviews(store, n=n_clean + n_fake)

    reviews: List[Review] = []
    if n_clean:
        clean = _parse(
            complete(CLEAN_SYSTEM, _prompt(store, n_clean, "genuine")),
            store, ReviewSource.LLM_CLEAN, start=0,
        )
        # codex output is non-deterministic; never emit an empty batch.
        reviews += clean or _mock_fallback(store, n_clean, fake=False, start=0)
    if n_fake:
        fake = _parse(
            complete(FAKE_SYSTEM, _prompt(store, n_fake, "fake promotional")),
            store, ReviewSource.LLM_FAKE, start=n_clean,
        )
        reviews += fake or _mock_fallback(store, n_fake, fake=True, start=n_clean)
    return reviews


if __name__ == "__main__":
    from data.stores import STORES

    rs = generate(STORES[3])
    print(f"generated {len(rs)} reviews "
          f"({sum(r.is_fake for r in rs)} fake) | real_agents={agent_available()}")
