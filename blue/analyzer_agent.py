"""
blue/analyzer_agent.py -- flag spam/repetition/bursts -> Verdict + Evidence.

OWNER: Blue team

The analyzer is the "brain". It scores each review and emits a Verdict with an
Evidence list (the signals that fired). It also proposes a NEXT ACTION for the
scraper (the feedback loop lives in orchestrator.py).

MOCK-FIRST: heuristics run with ZERO API key and catch the obvious mock fakes.
When ANTHROPIC_API_KEY is present, an LLM pass refines borderline cases.

Heuristic signals: generic_language, exclamation_spam, rating_skew, repetition,
author_burst, unverified. Each contributes a weight; suspicion = clamped sum.

TODO(blue):
  - Add an LLM "second opinion" on reviews scored 0.35..0.65 (the borderline band).
  - Tune weights against eval/run_eval.py on the Salminen holdout.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import List, Optional, Tuple

from schema import Evidence, Review, Verdict
from tracing import traced

GENERIC_PHRASES = [
    "best product ever", "changed my life", "10/10", "highly recommend",
    "buy it now", "best purchase", "amazing quality", "no regrets",
    "best seller", "everyone needs", "just wow",
]
DECISION_THRESHOLD = 0.5


def _exclamation_ratio(text: str) -> float:
    return text.count("!") / max(len(text), 1)


@traced
def score_review(
    review: Review,
    author_counts: Optional[Counter] = None,
) -> Verdict:
    """Score a single review into a Verdict with weighted Evidence."""
    evidence: List[Evidence] = []
    text_low = review.text.lower()

    hits = [p for p in GENERIC_PHRASES if p in text_low]
    if hits:
        evidence.append(Evidence(
            review_id=review.review_id, signal="generic_language",
            detail=f"Generic promo phrasing: {', '.join(hits[:3])}", weight=0.35))

    excl = review.text.count("!")
    if excl >= 3:
        evidence.append(Evidence(
            review_id=review.review_id, signal="exclamation_spam",
            detail=f"{excl} exclamation marks", weight=0.3))

    if review.rating >= 5.0 and (hits or excl >= 3):
        evidence.append(Evidence(
            review_id=review.review_id, signal="rating_skew",
            detail="Perfect 5.0 paired with hype language", weight=0.2))

    if not review.verified_purchase:
        evidence.append(Evidence(
            review_id=review.review_id, signal="unverified",
            detail="Not a verified purchase", weight=0.1))

    if author_counts and author_counts.get(review.author, 0) >= 3:
        evidence.append(Evidence(
            review_id=review.review_id, signal="author_burst",
            detail=f"Author '{review.author}' posted {author_counts[review.author]} reviews", weight=0.25))

    suspicion = min(1.0, sum(e.weight for e in evidence))
    return Verdict(
        review_id=review.review_id,
        is_fake=suspicion >= DECISION_THRESHOLD,
        confidence=round(suspicion, 3),
        evidence=evidence,
    )


@traced
def analyze(reviews: List[Review]) -> Tuple[List[Verdict], List[str]]:
    """
    Score a batch. Returns (verdicts, focus_hints) where focus_hints are
    suggestions for the scraper ("look at author X", "search keyword Y").
    """
    author_counts = Counter(r.author for r in reviews)

    # repetition: near-duplicate texts shared across reviews
    text_counts = Counter(re.sub(r"\W+", " ", r.text.lower()).strip() for r in reviews)

    verdicts: List[Verdict] = []
    for r in reviews:
        v = score_review(r, author_counts=author_counts)
        norm = re.sub(r"\W+", " ", r.text.lower()).strip()
        if text_counts[norm] >= 2:
            v.evidence.append(Evidence(
                review_id=r.review_id, signal="repetition",
                detail=f"Near-duplicate text seen {text_counts[norm]}x", weight=0.3))
            v.confidence = round(min(1.0, v.confidence + 0.3), 3)
            v.is_fake = v.confidence >= DECISION_THRESHOLD
        verdicts.append(v)

    # Feedback hints for the scraper: bursty authors are worth a focused fetch.
    focus_hints = [a for a, c in author_counts.items() if c >= 3]
    return verdicts, focus_hints
