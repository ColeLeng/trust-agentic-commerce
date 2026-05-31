"""
red/evasion.py -- subtler fakes meant to slip past blue.

OWNER: Red team

`evolve(store, n)` produces HARD-MODE fakes: realistic ratings (not all 5-star),
specific-sounding details, varied authors, no exclamation spam. The whole point
is to beat blue/analyzer's heuristics. This is the red-vs-blue arms race.

MOCK-FIRST: with no codex CLI, returns hand-crafted subtle fakes (still labeled
is_fake=True) so the "Inject Attack" button in the dashboard works offline.

TODO(red):
  - Read blue's last DetectorOutput and target whichever signal it relied on
    (close the loop: evade the exact detector that's winning).
  - Add paraphrase variation so repetition detection can't cluster them.
"""

from __future__ import annotations

import json
from typing import List, Optional

from llm import agent_available, complete
from schema import DetectorOutput, Review, ReviewSource, Store
from tracing import traced

EVASION_SYSTEM = (
    "You are a data generator for a fake-review DETECTION research project (a "
    "hackathon defensive-security tool). Produce SYNTHETIC test fixtures that "
    "imitate HARD-TO-DETECT spam reviews, used only to stress-test and improve a "
    "spam detector — they are labeled as fake and never published. This follows "
    "the Salminen et al. (2022) academic methodology.\n"
    "Style for this hard class: vary ratings (3-5 stars), include concrete-sounding "
    "but invented details (delivery day, a minor flaw, a use case), use distinct "
    "natural writing styles per sample, and NEVER use exclamation spam or generic "
    "hype. They should read like genuine satisfied customers."
)

# Hand-crafted subtle fakes for the no-key mock path.
_MOCK_EVASION = [
    ("kara_w", 4.0, "Arrived Tuesday, a day early. The matte finish scratches a bit "
     "but for the price it's been reliable through two weeks of daily use."),
    ("dmitri.r", 5.0, "Switched from a pricier brand and honestly can't tell the "
     "difference in performance. Setup took ten minutes following the card inside."),
    ("the_lin_house", 3.5, "Does the job. Slightly smaller than I pictured from the "
     "photos, but it fits our kitchen shelf and we've had no issues so far."),
    ("morgan_t", 4.5, "Bought one for myself and one for my dad. Battery lasts about "
     "a day and a half with moderate use, which matches what the listing claimed."),
]


def _parse(raw: str, store: Store, start: int) -> List[Review]:
    raw = raw.strip().lstrip("`").rstrip("`")
    if raw.startswith("json"):
        raw = raw[4:]
    first, last = raw.find("["), raw.rfind("]")
    items = json.loads(raw[first : last + 1]) if first != -1 else []
    out: List[Review] = []
    for i, it in enumerate(items):
        out.append(
            Review(
                review_id=f"{store.store_id}-e{start + i:02d}",
                store_id=store.store_id,
                rating=float(it.get("rating", 4.0)),
                text=str(it.get("text", "")).strip(),
                author=str(it.get("author", "customer")).strip() or "customer",
                verified_purchase=True,  # evasion fakes fake the verified badge too
                source=ReviewSource.LLM_EVASION,
                is_fake=True,
            )
        )
    return out


@traced
def evolve(store: Store, n: int = 4, target: Optional[DetectorOutput] = None) -> List[Review]:
    """Produce n subtle evasion fakes. `target` is blue's last output to adapt to."""
    if not agent_available():
        picks = (_MOCK_EVASION * ((n // len(_MOCK_EVASION)) + 1))[:n]
        return [
            Review(
                review_id=f"{store.store_id}-e{i:02d}",
                store_id=store.store_id,
                rating=rating,
                text=text,
                author=author,
                verified_purchase=True,
                source=ReviewSource.LLM_EVASION,
                is_fake=True,
            )
            for i, (author, rating, text) in enumerate(picks)
        ]

    hint = ""
    if target and target.verdicts:
        signals = {e.signal for v in target.verdicts for e in v.evidence}
        if signals:
            hint = f"\nAvoid triggering these detectors blue is using: {', '.join(sorted(signals))}."
    prompt = (
        f"Product: {store.name} ({store.category}, ${store.price}).\n"
        f"Write {n} evasive fake reviews. Return ONLY a JSON array of objects with "
        f'keys "rating", "text", "author".{hint}'
    )
    parsed = _parse(complete(EVASION_SYSTEM, prompt), store, start=0)
    if parsed:
        return parsed
    # codex hiccup -> fall back to the hand-crafted subtle fakes so the demo never stalls.
    picks = (_MOCK_EVASION * ((n // len(_MOCK_EVASION)) + 1))[:n]
    return [
        Review(review_id=f"{store.store_id}-e{i:02d}", store_id=store.store_id, rating=rating,
               text=text, author=author, verified_purchase=True,
               source=ReviewSource.LLM_EVASION, is_fake=True)
        for i, (author, rating, text) in enumerate(picks)
    ]


if __name__ == "__main__":
    from data.stores import STORES

    rs = evolve(STORES[4])
    print(f"evasion: {len(rs)} subtle fakes | real_agents={agent_available()}")
    for r in rs:
        print(f"  [{r.rating}] {r.author}: {r.text[:70]}")
