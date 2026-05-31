"""
blue/signals.py -- shared fake-review detection heuristics.

OWNER: Blue team

Pure functions the scout uses to turn ONE seller's reviews into Evidence +
risk_flags + an estimated fake fraction. No LLM required, so the scout works
fully offline; the scout can add an LLM second opinion on top.

Signals: review_repetition, timestamp_cluster (sliding-window burst),
uniform_sentiment, generic_language, exclamation_spam, unverified_ratio.

TODO(blue): tune weights against eval/run_eval.py on the Salminen holdout.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Set, Tuple

from schema import Evidence, Review

GENERIC = ["best ever", "best headphones ever", "10/10", "buy now", "life changing",
           "better than any", "everyone needs", "highly recommend", "just wow",
           "no regrets", "5 stars", "best deal"]
BURST_WINDOW_SECONDS = 3600  # reviews within this window count as one burst


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def _burst(reviews: List[Review]) -> Tuple[int, int, Set[str]]:
    """Densest sliding window: (count, span_seconds, review_ids in that window)."""
    ordered = sorted(reviews, key=lambda r: r.timestamp)
    times = [r.timestamp for r in ordered]
    best_count, best_lo, best_hi = 0, 0, 0
    j = 0
    for i in range(len(times)):
        j = max(j, i)
        while j + 1 < len(times) and (times[j + 1] - times[i]).total_seconds() <= BURST_WINDOW_SECONDS:
            j += 1
        if j - i + 1 > best_count:
            best_count, best_lo, best_hi = j - i + 1, i, j
    if best_count < 2:
        return best_count, 0, set()
    span = int((times[best_hi] - times[best_lo]).total_seconds())
    return best_count, span, {r.review_id for r in ordered[best_lo : best_hi + 1]}


def review_suspicion(reviews: List[Review]) -> Dict[str, float]:
    """Per-review suspicion in [0, ~1]. Shared by detect() and the holdout eval."""
    suspicion = {r.review_id: 0.0 for r in reviews}
    if not reviews:
        return suspicion

    counts = Counter(_norm(r.text) for r in reviews)
    burst_count, _, burst_ids = _burst(reviews)
    burst = burst_count >= 4 and burst_count >= 0.4 * len(reviews)
    ratings = [r.rating for r in reviews]
    uniform = sum(1 for x in ratings if x >= 5.0) / len(ratings) > 0.6

    for r in reviews:
        if counts[_norm(r.text)] >= 2:
            suspicion[r.review_id] += 0.35
        if burst and r.review_id in burst_ids:
            suspicion[r.review_id] += 0.2
        if uniform and r.rating >= 5.0:
            suspicion[r.review_id] += 0.15
        low = r.text.lower()
        if any(p in low for p in GENERIC):
            suspicion[r.review_id] += 0.3
        if r.text.count("!") >= 3:
            suspicion[r.review_id] += 0.25
    return suspicion


def classify_reviews(reviews: List[Review], threshold: float = 0.5) -> Dict[str, bool]:
    """Per-review fake/not prediction (used by eval/run_eval.py)."""
    return {rid: s >= threshold for rid, s in review_suspicion(reviews).items()}


def detect(reviews: List[Review]) -> Tuple[List[Evidence], List[str], float]:
    """Return (evidence, risk_flags, estimated_fake_fraction) for one seller."""
    if not reviews:
        return [], [], 0.0

    evidence: List[Evidence] = []
    flags: Set[str] = set()
    suspicion = review_suspicion(reviews)

    counts = Counter(_norm(r.text) for r in reviews)
    if any(c >= 2 for c in counts.values()):
        flags.add("review_repetition")
        dupes = sum(c for c in counts.values() if c >= 2)
        evidence.append(Evidence(signal="review_repetition",
            detail=f"{dupes} reviews reuse near-identical text", weight=0.35))

    burst_count, span, burst_ids = _burst(reviews)
    if burst_count >= 4 and burst_count >= 0.4 * len(reviews):
        flags.add("timestamp_cluster")
        evidence.append(Evidence(signal="timestamp_cluster",
            detail=f"{burst_count} reviews posted within {max(1, span // 60)} min", weight=0.2))

    ratings = [r.rating for r in reviews]
    five_share = sum(1 for x in ratings if x >= 5.0) / len(ratings)
    if five_share > 0.6:
        flags.add("uniform_sentiment")
        evidence.append(Evidence(signal="uniform_sentiment",
            detail=f"{five_share:.0%} of reviews are a perfect 5.0", weight=0.15))

    for r in reviews:
        low = r.text.lower()
        hits = [p for p in GENERIC if p in low]
        if hits:
            flags.add("generic_language")
            evidence.append(Evidence(signal="generic_language", review_id=r.review_id,
                detail=f"Promo phrasing: {', '.join(hits[:2])}", weight=0.3))
        if r.text.count("!") >= 3:
            flags.add("exclamation_spam")
            evidence.append(Evidence(signal="exclamation_spam", review_id=r.review_id,
                detail=f"{r.text.count('!')} exclamation marks", weight=0.25))

    unverified = sum(1 for r in reviews if not r.verified_purchase) / len(reviews)
    if unverified > 0.5:
        flags.add("unverified_majority")
        evidence.append(Evidence(signal="unverified_majority",
            detail=f"{unverified:.0%} of reviews are unverified purchases", weight=0.1))

    fake_fraction = sum(1 for v in suspicion.values() if v >= 0.5) / len(reviews)
    return evidence, sorted(flags), round(fake_fraction, 3)
