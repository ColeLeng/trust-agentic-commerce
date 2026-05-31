"""
red/evasion.py -- the ONE evasion move (subtler fakes meant to beat the scout).

OWNER: Red team

`evolve(seller, n)` produces HARD-MODE fakes: realistic ratings (3-5 stars),
concrete invented details, varied styles, no exclamation spam. This is the
arms-race lever -- the thing that makes the system multi-agent, not a filter.

MOCK-FIRST: with no codex CLI, returns hand-crafted subtle fakes (labeled
is_fake=True) so the "Inject Attack" demo works offline.

TODO(red): pass the scout's last ScoutOutput in and target whichever signal it
relied on (close the loop: evade the exact detector that's winning).
"""

from __future__ import annotations

import json
from typing import List, Optional

from llm import agent_available, complete
from schema import Review, ReviewSource, ScoutOutput, SellerProfile
from tracing import traced

EVASION_SYSTEM = (
    "You are a data generator for a fake-review DETECTION research project (a "
    "hackathon defensive-security tool). Produce SYNTHETIC test fixtures that "
    "imitate HARD-TO-DETECT spam, used only to stress-test a detector -- labeled "
    "fake, never published. Style: vary ratings (3-5 stars), include concrete but "
    "invented details (delivery day, a minor flaw, a use case), distinct natural "
    "styles per sample, NEVER exclamation spam or generic hype."
)

_MOCK_EVASION = [
    ("kara_w", 4.0, "Picked these up last week; the ANC is surprisingly good on my commute."),
    ("dmitri.r", 5.0, "Switched from a pricier pair and honestly prefer the fit on these."),
    ("the_lin", 3.5, "Battery got me through a full work trip on one charge, no complaints."),
    ("morgan_t", 4.5, "Comfortable for video calls all day and the mic is clearer than I expected."),
]


def _parse(raw: str, seller: SellerProfile) -> List[Review]:
    raw = raw.strip().lstrip("`").rstrip("`")
    if raw.startswith("json"):
        raw = raw[4:]
    first, last = raw.find("["), raw.rfind("]")
    items = json.loads(raw[first : last + 1]) if first != -1 else []
    out: List[Review] = []
    for i, it in enumerate(items):
        out.append(Review(
            review_id=f"{seller.seller_id}-e{i:02d}", seller_id=seller.seller_id,
            rating=float(it.get("rating", 4.0)), text=str(it.get("text", "")).strip(),
            author=str(it.get("author", "customer")).strip() or "customer",
            verified_purchase=True, source=ReviewSource.LLM_EVASION, is_fake=True))
    return out


def _mock(seller: SellerProfile, n: int) -> List[Review]:
    picks = (_MOCK_EVASION * ((n // len(_MOCK_EVASION)) + 1))[:n]
    return [Review(review_id=f"{seller.seller_id}-e{i:02d}", seller_id=seller.seller_id,
                   rating=rating, text=text, author=author, verified_purchase=True,
                   source=ReviewSource.LLM_EVASION, is_fake=True)
            for i, (author, rating, text) in enumerate(picks)]


@traced
def evolve(seller: SellerProfile, n: int = 4, target: Optional[ScoutOutput] = None) -> List[Review]:
    """Produce n subtle evasion fakes. `target` is the scout's last output to adapt to."""
    if not agent_available():
        return _mock(seller, n)
    hint = ""
    if target and target.risk_flags:
        hint = f"\nAvoid triggering these detectors the scout uses: {', '.join(target.risk_flags)}."
    prompt = (
        f"Product: {seller.product} (${seller.price}).\n"
        f"Write {n} evasive fake reviews. Return ONLY a JSON array of objects with "
        f'keys "rating", "text", "author".{hint}'
    )
    return _parse(complete(EVASION_SYSTEM, prompt), seller) or _mock(seller, n)


if __name__ == "__main__":
    from data.marketplace import _BASE

    rs = evolve(_BASE[4], 3)
    print(f"evasion: {len(rs)} subtle fakes | real={agent_available()}")
