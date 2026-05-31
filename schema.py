"""
================================================================================
schema.py  --  THE FROZEN CONTRACT
================================================================================

OWNER: Whole team (shared)

!!! WARNING !!!
This file is the integration boundary between Red, Blue, Data, and Glue.
DO NOT change field names, types, or remove fields without TEAM SIGN-OFF.
If you change a model here, you WILL break someone else's module mid-hackathon.

Adding a new OPTIONAL field with a default is usually safe.
Renaming / removing / retyping an existing field is NOT. Ask in the team chat.
================================================================================

All models are Pydantic v2 (`pydantic>=2`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ReviewSource(str, Enum):
    """Where a review came from. `is_fake` is GROUND TRUTH, set by whoever made it."""

    MOCK = "mock"          # deterministic mock data (no API key)
    LLM_CLEAN = "llm_clean"   # genuine-looking review written by red/generator
    LLM_FAKE = "llm_fake"     # planted fake written by red/generator
    LLM_EVASION = "llm_evasion"  # subtle fake from red/evasion (hard mode)
    SALMINEN = "salminen"  # real labeled review from the Salminen holdout set


class Review(BaseModel):
    """A single product review. The atomic unit that flows red -> blue."""

    review_id: str
    store_id: str
    rating: float = Field(ge=0.0, le=5.0)
    text: str
    author: str = "anonymous"
    timestamp: datetime = Field(default_factory=_now)
    verified_purchase: bool = False
    source: ReviewSource = ReviewSource.MOCK
    # GROUND TRUTH label. None == unknown/unlabeled (blue must not peek at this
    # except in eval). True == planted fake, False == genuine.
    is_fake: Optional[bool] = None


class Store(BaseModel):
    """A storefront / product listing being audited."""

    store_id: str
    name: str
    category: str          # e.g. "Electronics", "Beauty"
    asin: str              # real Amazon ASIN for flavor
    price: float
    # GROUND TRUTH: was this store seeded with planted fakes? (data/stores.py)
    is_dirty: bool = False
    reviews: List[Review] = Field(default_factory=list)


class Evidence(BaseModel):
    """One reason blue flagged something. Powers the dashboard click-through."""

    review_id: str
    signal: str            # e.g. "burst", "repetition", "generic_language", "rating_skew"
    detail: str            # human-readable explanation shown in the UI
    weight: float = Field(ge=0.0, le=1.0)  # contribution to suspicion (0..1)


class Verdict(BaseModel):
    """Blue's per-review judgement."""

    review_id: str
    is_fake: bool
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: List[Evidence] = Field(default_factory=list)


class DetectorOutput(BaseModel):
    """
    Blue's final report for ONE store. This is what blue/orchestrator emits
    and what the dashboard ranks stores by.
    """

    store_id: str
    trust_score: float = Field(ge=0.0, le=100.0)  # 100 = totally trustworthy
    verdicts: List[Verdict] = Field(default_factory=list)
    fake_count: int = 0
    total_reviews: int = 0
    summary: str = ""
    # how many feedback rounds the orchestrator ran (analyzer -> scraper loop)
    rounds: int = 1

    @property
    def fake_ratio(self) -> float:
        return self.fake_count / self.total_reviews if self.total_reviews else 0.0


class AuditResult(BaseModel):
    """Top-level artifact written to results.json by run.py and read by the dashboard."""

    generated_at: datetime = Field(default_factory=_now)
    used_real_agents: bool = False  # False == ran in mock mode (no API keys)
    stores: List[Store] = Field(default_factory=list)
    detections: List[DetectorOutput] = Field(default_factory=list)

    def ranked(self) -> List[DetectorOutput]:
        """Trustpilot-style ranking: most trustworthy first."""
        return sorted(self.detections, key=lambda d: d.trust_score, reverse=True)
