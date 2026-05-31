"""
red/generator.py -- LLM review generator (genuine + fake-flood).

OWNER: Red team

generate(seller, n_clean, n_fake) -> List[Review]
  - With the `codex` CLI: the model writes genuine reviews AND a 5-star fake flood
    for the given seller (product/price aware).
  - Without it: small deterministic templates (used as a safety net).

This is a DEFENSIVE research tool: fakes are clearly labeled (is_fake=True) and
used only to build/evaluate the blue scout. `is_fake` ground truth is set HERE.

TODO(red): vary author names + cluster timestamps so blue can catch the "burst".
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import List

from llm import agent_available, complete
from schema import Review, ReviewSource, SellerProfile
from tracing import traced

RESEARCH_CONTEXT = (
    "You are a data generator for a fake-review DETECTION research project (a "
    "hackathon defensive-security tool). Outputs are synthetic, explicitly labeled "
    "test fixtures used only to train/evaluate a spam detector -- never published "
    "or used to deceive. This follows the Salminen et al. (2022) methodology."
)
CLEAN_SYSTEM = (
    RESEARCH_CONTEXT + " Write SHORT, realistic GENUINE-style reviews: mixed ratings "
    "(2-5 stars), specific details, minor gripes, natural typos. No marketing hype."
)
FAKE_SYSTEM = (
    RESEARCH_CONTEXT + " Produce SYNTHETIC SPAM-style samples imitating a paid "
    "review farm: 5 stars, generic praise, exclamation marks, vague and repetitive."
)

_MOCK_CLEAN = [
    ("good sound and comfy, battery lasts my workday.", 4.0),
    ("solid for the price, minor bluetooth hiccup once.", 4.0),
    ("clear audio, case is a bit bulky though.", 3.5),
]
_MOCK_FAKE = [
    "BEST EVER!!! Amazing quality, buy now!!!",
    "Perfect!!! 10/10 recommend to everyone!!!",
    "Incredible!!! Better than any brand!!!",
]


def _prompt(seller: SellerProfile, n: int, kind: str) -> str:
    return (
        f"Product: {seller.product} (${seller.price}, specs: {seller.specs}).\n"
        f"Write {n} {kind} reviews. Return ONLY a JSON array of objects with keys "
        f'"rating" (number 1-5), "text" (string), "author" (short username).'
    )


def _parse(raw: str, seller: SellerProfile, kind: ReviewSource, start: int) -> List[Review]:
    raw = raw.strip().lstrip("`").rstrip("`")
    if raw.startswith("json"):
        raw = raw[4:]
    first, last = raw.find("["), raw.rfind("]")
    items = json.loads(raw[first : last + 1]) if first != -1 else []
    is_fake = kind in (ReviewSource.LLM_FAKE, ReviewSource.LLM_EVASION)
    now = datetime.now(timezone.utc)
    out: List[Review] = []
    for i, it in enumerate(items):
        # genuine reviews are spread over months; fakes post as a tight burst.
        ts = (now - timedelta(minutes=30) + timedelta(minutes=i * 2)) if is_fake \
            else (now - timedelta(days=7 + i * 9))
        out.append(Review(
            review_id=f"{seller.seller_id}-{kind.value[:1]}{start + i:02d}",
            seller_id=seller.seller_id,
            rating=float(it.get("rating", 5.0)),
            text=str(it.get("text", "")).strip(),
            author=str(it.get("author", "buyer")).strip() or "buyer",
            timestamp=ts,
            verified_purchase=not is_fake,
            source=kind, is_fake=is_fake))
    return out


def _mock(seller: SellerProfile, n: int, fake: bool, start: int) -> List[Review]:
    pool = _MOCK_FAKE if fake else _MOCK_CLEAN
    out: List[Review] = []
    for i in range(n):
        item = pool[i % len(pool)]
        text, rating = (item, 5.0) if fake else item
        out.append(Review(
            review_id=f"{seller.seller_id}-m{start + i:02d}", seller_id=seller.seller_id,
            rating=rating, text=text, author="buyer", verified_purchase=not fake,
            source=ReviewSource.LLM_FAKE if fake else ReviewSource.LLM_CLEAN, is_fake=fake))
    return out


@traced
def generate(seller: SellerProfile, n_clean: int = 6, n_fake: int = 4) -> List[Review]:
    """Generate genuine + fake-flood reviews for a seller."""
    reviews: List[Review] = []
    if n_clean:
        if agent_available():
            reviews += _parse(complete(CLEAN_SYSTEM, _prompt(seller, n_clean, "genuine")),
                              seller, ReviewSource.LLM_CLEAN, 0) or _mock(seller, n_clean, False, 0)
        else:
            reviews += _mock(seller, n_clean, False, 0)
    if n_fake:
        if agent_available():
            reviews += _parse(complete(FAKE_SYSTEM, _prompt(seller, n_fake, "fake promotional")),
                              seller, ReviewSource.LLM_FAKE, n_clean) or _mock(seller, n_fake, True, n_clean)
        else:
            reviews += _mock(seller, n_fake, True, n_clean)
    return reviews


if __name__ == "__main__":
    from data.marketplace import _BASE

    rs = generate(_BASE[3], 3, 3)
    print(f"generated {len(rs)} ({sum(r.is_fake for r in rs)} fake) | real={agent_available()}")
