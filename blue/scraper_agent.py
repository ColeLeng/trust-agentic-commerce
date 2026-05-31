"""
blue/scraper_agent.py -- ingest a store's reviews.

OWNER: Blue team

The scraper is the "eyes". The orchestrator's feedback loop steers it: the analyzer
can ask it to "fetch more" or "look here" (focus on a subset). In a real system this
hits a live API; here it pages over the store's already-loaded reviews.

MOCK-FIRST: works entirely offline — it just slices the in-memory review list.

TODO(blue):
  - Replace `fetch` internals with a real reviews API/scrape when we have a source.
  - Support `focus` filters richer than author/keyword (date windows, rating bands).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from schema import Review, Store
from tracing import traced


@dataclass
class ScrapeRequest:
    """What the orchestrator/analyzer asks the scraper to fetch next."""

    page: int = 0
    page_size: int = 6
    focus_author: Optional[str] = None      # "look here": only this author's reviews
    focus_keyword: Optional[str] = None     # "look here": reviews containing keyword
    fetch_more: bool = False                # "fetch more": ignore paging, return all


@dataclass
class ScraperAgent:
    store: Store
    _seen: set = field(default_factory=set)

    @traced
    def fetch(self, req: ScrapeRequest) -> List[Review]:
        reviews = self.store.reviews

        if req.focus_author:
            reviews = [r for r in reviews if r.author == req.focus_author]
        if req.focus_keyword:
            kw = req.focus_keyword.lower()
            reviews = [r for r in reviews if kw in r.text.lower()]

        if req.fetch_more or req.focus_author or req.focus_keyword:
            page = reviews
        else:
            start = req.page * req.page_size
            page = reviews[start : start + req.page_size]

        for r in page:
            self._seen.add(r.review_id)
        return page

    @property
    def seen_count(self) -> int:
        return len(self._seen)

    @property
    def total(self) -> int:
        return len(self.store.reviews)
