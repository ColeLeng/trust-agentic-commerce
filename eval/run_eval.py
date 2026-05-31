"""
eval/run_eval.py -- honest precision/recall of BLUE on the Salminen holdout.

OWNER: Blue / Eval

Blue is NEVER tuned on this set. We feed the labeled Salminen reviews through the
same analyzer blue uses in production and report precision / recall / F1 on the
"is this a fake?" task. This is the credibility number for the demo.

    python eval/run_eval.py

MOCK-FIRST: if data/salminen_holdout/*.csv is missing, this falls back to a small
built-in labeled sample so the eval pipeline runs on a fresh clone. Drop the real
CSV in (see data/salminen_holdout/README.md) to get the real numbers.

TODO(eval):
  - Report per-category breakdown once the real CSV is present.
  - Sweep DECISION_THRESHOLD and print a precision/recall curve.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import List, Tuple

# allow `python eval/run_eval.py` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blue.analyzer_agent import analyze  # noqa: E402
from schema import Review, ReviewSource  # noqa: E402

HOLDOUT_DIR = Path(__file__).parent.parent / "data" / "salminen_holdout"

# If the real CSV uses different headers, remap them here.
COLUMN_MAP = {"text": "text_", "label": "label", "rating": "rating"}
FAKE_LABELS = {"cg", "fake", "1", "true"}  # "CG" = computer-generated in Salminen

# Built-in fallback sample (text, is_fake) so eval runs with no dataset present.
_FALLBACK = [
    ("Best product ever!!! Amazing quality, buy it now!!!", True),
    ("Absolutely perfect!!! 10/10 would recommend to everyone!!!", True),
    ("This changed my life!!! Best purchase, no regrets!!!", True),
    ("Incredible!!! The best seller on Amazon, everyone needs this!!!", True),
    ("Top quality!!! My whole family loves it, best purchase of the year!!!", True),
    ("Solid product, exactly as described. Shipping took 3 days.", False),
    ("Been using it a month, holds up well. Worth the price.", False),
    ("Decent value. Small packaging issue but the item is fine.", False),
    ("Works great for my needs, though the manual was thin.", False),
    ("Good but not perfect. Battery life a bit short for me.", False),
    ("Arrived a day early. Matte finish scratches but reliable so far.", False),
    ("Does the job. Slightly smaller than pictured but fits fine.", False),
]


def _load_holdout(limit: int = 2000) -> Tuple[List[Review], List[bool]]:
    csvs = sorted(HOLDOUT_DIR.glob("*.csv"))
    if not csvs:
        print("[eval] No Salminen CSV found -> using built-in fallback sample.\n"
              "       (drop the real CSV in data/salminen_holdout/ for real numbers)")
        reviews = [
            Review(review_id=f"f{i}", store_id="holdout", rating=5.0 if fake else 4.0,
                   text=text, source=ReviewSource.SALMINEN, is_fake=fake)
            for i, (text, fake) in enumerate(_FALLBACK)
        ]
        return reviews, [r.is_fake for r in reviews]  # type: ignore[misc]

    path = csvs[0]
    print(f"[eval] Loading holdout: {path.name}")
    reviews, labels = [], []
    with path.open(newline="", encoding="utf-8", errors="ignore") as fh:
        reader = csv.DictReader(fh)
        fields = {f.lower(): f for f in (reader.fieldnames or [])}
        text_col = fields.get(COLUMN_MAP["text"].lower()) or fields.get("text") or fields.get("review")
        label_col = fields.get(COLUMN_MAP["label"].lower()) or fields.get("label")
        rating_col = fields.get(COLUMN_MAP["rating"].lower()) or fields.get("rating")
        for i, row in enumerate(reader):
            if i >= limit:
                break
            text = (row.get(text_col) or "").strip() if text_col else ""
            if not text:
                continue
            label_raw = (row.get(label_col) or "").strip().lower() if label_col else ""
            is_fake = label_raw in FAKE_LABELS
            try:
                rating = float(row.get(rating_col)) if rating_col and row.get(rating_col) else 4.0
            except ValueError:
                rating = 4.0
            reviews.append(Review(review_id=f"h{i}", store_id="holdout", rating=rating,
                                  text=text, source=ReviewSource.SALMINEN, is_fake=is_fake))
            labels.append(is_fake)
    return reviews, labels


def _metrics(preds: List[bool], labels: List[bool]) -> dict:
    tp = sum(1 for p, y in zip(preds, labels) if p and y)
    fp = sum(1 for p, y in zip(preds, labels) if p and not y)
    fn = sum(1 for p, y in zip(preds, labels) if not p and y)
    tn = sum(1 for p, y in zip(preds, labels) if not p and not y)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    acc = (tp + tn) / len(labels) if labels else 0.0
    return {"n": len(labels), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": precision, "recall": recall, "f1": f1, "accuracy": acc}


def main() -> None:
    reviews, labels = _load_holdout()
    verdicts, _ = analyze(reviews)
    by_id = {v.review_id: v for v in verdicts}
    preds = [by_id[r.review_id].is_fake for r in reviews]

    m = _metrics(preds, labels)
    print("\n=== BLUE vs. Salminen holdout (heuristic analyzer) ===")
    print(f"  n          : {m['n']}")
    print(f"  precision  : {m['precision']:.3f}")
    print(f"  recall     : {m['recall']:.3f}")
    print(f"  f1         : {m['f1']:.3f}")
    print(f"  accuracy   : {m['accuracy']:.3f}")
    print(f"  confusion  : tp={m['tp']} fp={m['fp']} fn={m['fn']} tn={m['tn']}")


if __name__ == "__main__":
    main()
