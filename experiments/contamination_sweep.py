"""
experiments/contamination_sweep.py -- the v3 money-shot.

OWNER: Glue / Blue

Sweeps contamination 0% -> 60% and, at each level, compares:
  * BASELINE  (baseline/buyer_agent): reads ALL sellers in one context -> picks one
  * ISOLATED  (concierge -> isolated scouts -> structured adjudication)

against ground truth (Store.is_dirty). Shows the level where the single-context
baseline flips to a dishonest seller while the isolated system holds.

    python experiments/contamination_sweep.py     # mock mode -- always works

Writes defense_results.json, read by app/defense_dashboard.py.

MOCK-FIRST: runs with no API key.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from baseline.buyer_agent import choose  # noqa: E402
from blue.concierge_agent import run_concierge_with_reports  # noqa: E402
from data.stores import STORES, contaminated_stores, honest_store_ids  # noqa: E402
from tracing import init_tracing  # noqa: E402

RESULTS_PATH = Path(__file__).resolve().parent.parent / "defense_results.json"
LEVELS = [0.0, 0.2, 0.4, 0.6]


def run_sweep(levels=None) -> dict:
    init_tracing()

    levels = levels or LEVELS
    store_names = {s.store_id: s.name for s in STORES}
    experiments = []

    for level in levels:
        stores = contaminated_stores(level)
        honest = honest_store_ids(stores)

        baseline = choose(stores)

        concierge_run = run_concierge_with_reports(stores)
        reports = concierge_run.reports
        decision = concierge_run.decision

        experiments.append(
            {
                "contamination_level": level,
                "baseline_pick": baseline.chosen_seller_id,
                "baseline_pick_name": store_names.get(
                    baseline.chosen_seller_id,
                    baseline.chosen_seller_id,
                ),
                "baseline_picked_honest": baseline.chosen_seller_id in honest,
                "baseline_why": baseline.why,
                "isolated_pick": decision.winner_seller_id,
                "isolated_pick_name": store_names.get(
                    decision.winner_seller_id,
                    decision.winner_seller_id,
                ),
                "isolated_picked_honest": decision.winner_seller_id in honest,
                "isolated_why": decision.why,
                "scout_reports": [r.model_dump(mode="json") for r in reports],
                "stores": [s.model_dump(mode="json") for s in stores],
            }
        )

    breaking_point = next(
        (
            e["contamination_level"]
            for e in experiments
            if not e["baseline_picked_honest"]
        ),
        None,
    )

    return {
        "honest_store_ids": honest_store_ids(contaminated_stores(0.0)),
        "store_names": store_names,
        "breaking_point": breaking_point,
        "isolated_held": all(e["isolated_picked_honest"] for e in experiments),
        "experiments": experiments,
    }


def main() -> None:
    result = run_sweep()

    print("=== Context-isolation defense: contamination sweep ===\n")
    print(f"{'contam':>7} | {'baseline pick':>26} | {'isolated pick':>26}")
    print("-" * 68)

    for e in result["experiments"]:

        def tag(name: str, honest: bool) -> str:
            return f"{name} ({'honest' if honest else 'DISHONEST'})"

        print(
            f"{e['contamination_level']:>6.0%} | "
            f"{tag(e['baseline_pick_name'], e['baseline_picked_honest']):>26} | "
            f"{tag(e['isolated_pick_name'], e['isolated_picked_honest']):>26}"
        )

    print("-" * 68)

    breaking_point = result["breaking_point"]
    if breaking_point is not None:
        print(
            f"\nBASELINE BREAKS at {breaking_point:.0%} contamination "
            f"(picks a dishonest seller)."
        )
    else:
        print("\nBaseline held at all tested levels.")

    print(f"ISOLATED system held at every level: {result['isolated_held']}")

    RESULTS_PATH.write_text(json.dumps(result, indent=2))
    print(f"\nWrote {RESULTS_PATH.name}. View it:  streamlit run app/defense_dashboard.py")


if __name__ == "__main__":
    main()