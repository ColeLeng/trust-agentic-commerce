"""
Run the blue concierge against a local JSON fixture.

This is a small harness for testing blue/scout_agent.py and
blue/concierge_agent.py without invoking the red generator pipeline.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blue.concierge_agent import adjudicate, dispatch_scouts  # noqa: E402
from schema import Store  # noqa: E402

DEFAULT_FIXTURE = Path(__file__).resolve().parent / "mock_data" / "stores.json"


def load_fixture(path: Path) -> list[Store]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array of stores.")
    return [Store.model_validate(item) for item in data]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run blue agents on mock store data.")
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
        help="Path to a JSON array of schema.Store objects.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Allow live scout model calls when ANTHROPIC_API_KEY is set.",
    )
    args = parser.parse_args()

    if not args.live:
        os.environ.pop("ANTHROPIC_API_KEY", None)

    stores = load_fixture(args.fixture)
    reports = dispatch_scouts(stores)

    for report in reports:
        flags = ", ".join(report.risk_flags) or "none"
        print(
            f"scout | {report.seller_id:18s} "
            f"trust={report.trust_score:5.1f} "
            f"product={report.product_score:5.1f} "
            f"{report.recommendation:10s} flags=[{flags}]"
        )

    decision = adjudicate(reports)
    print()
    print(f"concierge | winner={decision.winner_seller_id}")
    print(f"why       | {decision.why}")
    print(f"ranking   | {', '.join(decision.ranking)}")


if __name__ == "__main__":
    main()
