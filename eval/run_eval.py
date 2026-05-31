"""
eval/run_eval.py -- the two honest numbers for the pitch.

OWNER: Blue / Eval

(A) CONTAMINATION THRESHOLD: sweep both strategies and report the level where the
    single-context BASELINE flips to a dishonest seller, vs. the ISOLATED system
    which should hold. This is the headline defensibility claim.

(B) SALMINEN HOLDOUT: per-review precision/recall of the scout's detector on the
    Salminen fake-review set -- fakes the detector NEVER saw or was tuned on.
    This converts "you graded your own homework" into a real number.

    python eval/run_eval.py

MOCK-FIRST: runs with no codex CLI and no dataset (built-in fallback sample).
Drop the real CSV into data/salminen_holdout/ for the real holdout number.

TODO(eval): sweep the scout's decision threshold and print a precision/recall curve.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from baseline.buyer_agent import choose  # noqa: E402
from blue.concierge_agent import adjudicate  # noqa: E402
from blue.planner_agent import plan_and_dispatch  # noqa: E402
from blue.signals import classify_reviews  # noqa: E402
from data.marketplace import honest_seller_ids  # noqa: E402
from red.question_agent import default_question  # noqa: E402
from red.seller_agent import simulate_sellers  # noqa: E402
from schema import ContaminationStrategy, Review, ReviewSource  # noqa: E402

HOLDOUT_DIR = Path(__file__).parent.parent / "data" / "salminen_holdout"
COLUMN_MAP = {"text": "text_", "label": "label", "rating": "rating"}
FAKE_LABELS = {"cg", "fake", "1", "true"}

_FALLBACK = [
    ("BEST headphones ever!!! Amazing, buy now!!!", True),
    ("Absolutely perfect!!! 10/10 recommend to everyone!!!", True),
    ("Life changing sound!!! Best deal, no regrets!!!", True),
    ("Incredible!!! Better than any brand, 5 stars!!!", True),
    ("Top quality!!! Everyone needs these!!!", True),
    ("Solid sound, comfortable for long sessions. Battery lasts a workday.", False),
    ("ANC is decent on the train. Case is a bit bulky though.", False),
    ("Good value. Minor bluetooth dropout once, fixed by an update.", False),
    ("Clear mids, treble a touch sharp for me, otherwise fine.", False),
    ("Comfortable but clamp is tight day one, loosens up after a week.", False),
    ("Battery matches the listing and fast charge is genuinely useful.", False),
    ("Works well for calls, mic clearer than I expected.", False),
]


# --------------------------------------------------------------------------- #
# (A) Contamination threshold                                                 #
# --------------------------------------------------------------------------- #
def contamination_report() -> None:
    q = default_question()
    print("=== (A) Contamination threshold: baseline vs. isolated ===")
    for strategy in (ContaminationStrategy.REVIEW_FLOOD, ContaminationStrategy.EVASION):
        baseline_break = None
        isolated_break = None
        honest_ids: List[str] = []
        row = []
        for level in q.contamination_levels:
            sellers = simulate_sellers(q, level, strategy)
            honest_ids = honest_ids or honest_seller_ids(sellers)
            b = choose(q, sellers).chosen_seller_id in honest_ids
            i = adjudicate(plan_and_dispatch(q, sellers), q.personal_context).winner_seller_id in honest_ids
            if not b and baseline_break is None:
                baseline_break = level
            if not i and isolated_break is None:
                isolated_break = level
            row.append(f"{level:.0%}:{'H' if b else 'X'}/{'H' if i else 'X'}")
        print(f"  {strategy.value:14s} [base/iso per level: {' '.join(row)}]")
        print(f"      baseline breaks at: {baseline_break if baseline_break is not None else 'never (in range)'}"
              f"   |   isolated breaks at: {isolated_break if isolated_break is not None else 'never (in range)'}")
    print("      (H = picked honest seller, X = picked dishonest)\n")


# --------------------------------------------------------------------------- #
# (B) Salminen holdout precision/recall                                       #
# --------------------------------------------------------------------------- #
def _load_holdout(limit: int = 2000) -> Tuple[List[Review], List[bool]]:
    csvs = sorted(HOLDOUT_DIR.glob("*.csv"))
    if not csvs:
        print("[eval] No Salminen CSV found -> built-in fallback sample.")
        reviews = [Review(review_id=f"f{i}", seller_id="holdout", rating=5.0 if fake else 4.0,
                          text=t, source=ReviewSource.SALMINEN, is_fake=fake)
                   for i, (t, fake) in enumerate(_FALLBACK)]
        return reviews, [bool(r.is_fake) for r in reviews]

    path = csvs[0]
    print(f"[eval] Loading holdout: {path.name}")
    reviews, labels = [], []
    with path.open(newline="", encoding="utf-8", errors="ignore") as fh:
        reader = csv.DictReader(fh)
        fields = {f.lower(): f for f in (reader.fieldnames or [])}
        text_col = fields.get(COLUMN_MAP["text"].lower()) or fields.get("text") or fields.get("review")
        label_col = fields.get(COLUMN_MAP["label"].lower()) or fields.get("label")
        for i, rrow in enumerate(reader):
            if i >= limit:
                break
            text = (rrow.get(text_col) or "").strip() if text_col else ""
            if not text:
                continue
            is_fake = ((rrow.get(label_col) or "").strip().lower() in FAKE_LABELS) if label_col else False
            reviews.append(Review(review_id=f"h{i}", seller_id="holdout", rating=4.0,
                                  text=text, source=ReviewSource.SALMINEN, is_fake=is_fake))
            labels.append(is_fake)
    return reviews, labels


def holdout_report() -> None:
    reviews, labels = _load_holdout()
    preds_map = classify_reviews(reviews)
    preds = [preds_map[r.review_id] for r in reviews]
    tp = sum(1 for p, y in zip(preds, labels) if p and y)
    fp = sum(1 for p, y in zip(preds, labels) if p and not y)
    fn = sum(1 for p, y in zip(preds, labels) if not p and y)
    tn = sum(1 for p, y in zip(preds, labels) if not p and not y)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    print("=== (B) Scout detector vs. Salminen holdout (UNSEEN fakes) ===")
    print(f"  n={len(labels)}  precision={precision:.3f}  recall={recall:.3f}  f1={f1:.3f}")
    print(f"  confusion: tp={tp} fp={fp} fn={fn} tn={tn}")


def main() -> None:
    contamination_report()
    holdout_report()


if __name__ == "__main__":
    main()
