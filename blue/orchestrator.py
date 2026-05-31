"""
blue/orchestrator.py -- the FEEDBACK LOOP. analyzer steers scraper -> DetectorOutput.

OWNER: Blue team

This is blue's headline artifact. The loop:
    1. scraper fetches a page of reviews
    2. analyzer scores them and emits focus_hints ("look at this bursty author")
    3. orchestrator re-tasks the scraper on those hints ("look here" / "fetch more")
    4. repeat up to `max_rounds`, accumulating verdicts
    5. collapse verdicts -> trust_score -> DetectorOutput

trust_score = 100 * (1 - fake_ratio), lightly penalized by detector confidence.

MOCK-FIRST: runs fully offline (analyzer heuristics + in-memory scraper).

TODO(blue):
  - Make the stop condition smarter (stop when a round yields no new fakes).
  - Feed DetectorOutput back to red/evasion to close the arms-race loop.
"""

from __future__ import annotations

from typing import Dict, List

from blue.analyzer_agent import analyze
from blue.scraper_agent import ScrapeRequest, ScraperAgent
from schema import DetectorOutput, Store, Verdict
from tracing import traced


@traced
def audit_store(store: Store, max_rounds: int = 3) -> DetectorOutput:
    """Run the analyzer<->scraper feedback loop and produce one DetectorOutput."""
    scraper = ScraperAgent(store=store)
    verdicts_by_id: Dict[str, Verdict] = {}
    rounds = 0

    # Round 0: page through everything once.
    page = 0
    while True:
        batch = scraper.fetch(ScrapeRequest(page=page, page_size=6))
        if not batch:
            break
        for v in _run(batch, verdicts_by_id):
            verdicts_by_id[v.review_id] = v
        page += 1
    rounds += 1

    # Feedback rounds: re-task scraper on suspicious authors the analyzer flagged.
    investigated: set = set()
    for _ in range(max_rounds - 1):
        _, hints = analyze(list(scraper.store.reviews))
        new_hints = [h for h in hints if h not in investigated]
        if not new_hints:
            break
        for author in new_hints:
            investigated.add(author)
            focused = scraper.fetch(ScrapeRequest(focus_author=author, fetch_more=True))
            for v in _run(focused, verdicts_by_id):
                verdicts_by_id[v.review_id] = v
        rounds += 1

    verdicts = list(verdicts_by_id.values())
    fake_count = sum(1 for v in verdicts if v.is_fake)
    total = len(verdicts)
    fake_ratio = fake_count / total if total else 0.0

    avg_fake_conf = (
        sum(v.confidence for v in verdicts if v.is_fake) / fake_count if fake_count else 0.0
    )
    trust_score = round(max(0.0, 100.0 * (1 - fake_ratio) - 10.0 * avg_fake_conf * fake_ratio), 1)

    return DetectorOutput(
        store_id=store.store_id,
        trust_score=trust_score,
        verdicts=verdicts,
        fake_count=fake_count,
        total_reviews=total,
        rounds=rounds,
        summary=(
            f"Audited {total} reviews over {rounds} round(s); flagged {fake_count} "
            f"fake ({fake_ratio:.0%}). Trust score {trust_score}/100."
        ),
    )


def _run(batch, existing: Dict[str, Verdict]) -> List[Verdict]:
    """Analyze a batch; analyze() needs full context so we score the batch together."""
    verdicts, _ = analyze(batch)
    return verdicts


@traced
def audit_all(stores: List[Store], max_rounds: int = 3) -> List[DetectorOutput]:
    return [audit_store(s, max_rounds=max_rounds) for s in stores]


if __name__ == "__main__":
    from data.stores import load_stores

    for d in audit_all(load_stores()):
        print(f"{d.store_id}: trust={d.trust_score:5.1f} "
              f"fakes={d.fake_count}/{d.total_reviews} rounds={d.rounds}")
