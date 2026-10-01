"""
experiments/contamination_sweep.py -- the v3 money-shot.

OWNER: Glue / Blue

Sweeps contamination 0% -> 60% and, at each level, compares:
  * BASELINE  (baseline/buyer_agent): reads ALL sellers in one context -> picks one
  * ISOLATED  (concierge -> isolated scouts -> structured adjudication)

against ground truth (Store.is_dirty). Shows the level where the single-context
baseline flips to a dishonest seller while the isolated system holds.

    python experiments/contamination_sweep.py     # mock mode -- always works

MOCK vs LIVE: with no ANTHROPIC_API_KEY the baseline is a hand-written naive
scorer (rating x volume, plus a bonus for injected text) -- a simulation, not a
model. With a key set, both sides call real models; every row is labelled with
what actually ran, and any failed live call aborts the run (LIVE_STRICT=1).

Live options (cost is printed up front and capped by --max-cost):
    --baseline-models claude-haiku-4-5,claude-sonnet-5-5,claude-opus-4-8
    --trials 3            # repeat each baseline pick (models are not deterministic)
    --skip-isolated       # baseline only: a few cents
    --max-cost 15         # hard stop, USD

Writes defense_results.json.

MOCK-FIRST: runs with no API key.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cost_meter  # noqa: E402
from baseline.buyer_agent import DEFAULT_BASELINE_MODEL, choose  # noqa: E402
from blue.concierge_agent import run_concierge_with_reports  # noqa: E402
from blue.scout_agent import SCOUT_MODEL  # noqa: E402
from data.stores import STORES, contaminated_stores, honest_store_ids  # noqa: E402
from tracing import init_tracing  # noqa: E402

RESULTS_PATH = Path(__file__).resolve().parent.parent / "defense_results.json"
LEVELS = [0.0, 0.2, 0.4, 0.6]
N_SCOUT_CHECKS = 4

# Worst-case tokens per call, for the up-front estimate (measured prompt sizes:
# baseline ~2K in; each scout check ~1.3K in, output capped at 2048).
_BASELINE_TOKENS = (2_500, 4_096)
_SCOUT_TOKENS = (1_500, 2_048)


def is_live() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def estimate_max_usd(models, trials, levels, skip_isolated) -> float:
    usd = sum(cost_meter.cost_of(m, *_BASELINE_TOKENS) for m in models) * trials * len(levels)
    if not skip_isolated:
        n_scout_calls = len(levels) * len(STORES) * N_SCOUT_CHECKS
        usd += cost_meter.cost_of(SCOUT_MODEL, *_SCOUT_TOKENS) * n_scout_calls
    return usd


def run_sweep(levels=None, baseline_models=None, trials: int = 1,
              skip_isolated: bool = False) -> dict:
    init_tracing()

    levels = levels or LEVELS
    live = is_live()
    # Mock mode has one deterministic baseline; models/trials only matter live.
    baseline_models = (baseline_models or [os.getenv("BASELINE_MODEL", DEFAULT_BASELINE_MODEL)]) if live else ["mock"]
    trials = trials if live else 1
    store_names = {s.store_id: s.name for s in STORES}
    experiments = []

    for level in levels:
        stores = contaminated_stores(level)
        honest = honest_store_ids(stores)

        baseline_runs = []
        for model in baseline_models:
            for trial in range(trials):
                d = choose(stores, model=None if model == "mock" else model)
                baseline_runs.append({
                    "model": model, "trial": trial, "mode": d.mode,
                    "pick": d.chosen_seller_id,
                    "pick_name": store_names.get(d.chosen_seller_id, d.chosen_seller_id),
                    "picked_honest": d.chosen_seller_id in honest,
                    "why": d.why,
                })

        first = baseline_runs[0]
        row = {
            "contamination_level": level,
            "baseline_runs": baseline_runs,
            "baseline_pick": first["pick"],
            "baseline_pick_name": first["pick_name"],
            "baseline_picked_honest": first["picked_honest"],
            "baseline_why": first["why"],
            "stores": [s.model_dump(mode="json") for s in stores],
        }

        if not skip_isolated:
            concierge_run = run_concierge_with_reports(stores)
            decision = concierge_run.decision
            row.update({
                "isolated_mode": f"live:{SCOUT_MODEL}" if live else "mock",
                "isolated_pick": decision.winner_seller_id,
                "isolated_pick_name": store_names.get(decision.winner_seller_id, decision.winner_seller_id),
                "isolated_picked_honest": decision.winner_seller_id in honest,
                "isolated_why": decision.why,
                "scout_reports": [r.model_dump(mode="json") for r in concierge_run.reports],
            })
        experiments.append(row)

    def first_break(model):
        for e in experiments:
            runs = [r for r in e["baseline_runs"] if r["model"] == model]
            if any(not r["picked_honest"] for r in runs):
                return e["contamination_level"]
        return None

    breaking_points = {m: first_break(m) for m in baseline_models}

    return {
        "mode": "live" if live else "mock",
        "baseline_models": baseline_models,
        "trials": trials,
        "honest_store_ids": honest_store_ids(contaminated_stores(0.0)),
        "store_names": store_names,
        "breaking_point": breaking_points[baseline_models[0]],
        "breaking_points": breaking_points,
        "isolated_held": None if skip_isolated else all(e["isolated_picked_honest"] for e in experiments),
        "cost_usd": round(cost_meter.spent_usd(), 4),
        "live_calls": cost_meter.calls,
        "experiments": experiments,
    }


def _print_table(result: dict) -> None:
    live = result["mode"] == "live"
    print(f"=== Context-isolation defense: contamination sweep [{result['mode'].upper()}] ===")
    if not live:
        print("    baseline = hand-written naive scorer (simulation, no model).")
    print()
    for e in result["experiments"]:
        print(f"contamination {e['contamination_level']:.0%}")
        for model in result["baseline_models"]:
            runs = [r for r in e["baseline_runs"] if r["model"] == model]
            n_honest = sum(r["picked_honest"] for r in runs)
            picks = ", ".join(f"{r['pick_name']}{'' if r['picked_honest'] else ' (DISHONEST)'}" for r in runs)
            label = runs[0]["mode"] if runs else model
            print(f"  baseline {label:28s} honest {n_honest}/{len(runs)}  -> {picks}")
        if "isolated_pick" in e:
            tag = "honest" if e["isolated_picked_honest"] else "DISHONEST"
            print(f"  isolated {e['isolated_mode']:28s} -> {e['isolated_pick_name']} ({tag})")
    print()
    for model, bp in result["breaking_points"].items():
        where = f"breaks at {bp:.0%} contamination" if bp is not None else "held at every tested level"
        print(f"BASELINE {model}: {where}.")
    if result["isolated_held"] is not None:
        print(f"ISOLATED system held at every level: {result['isolated_held']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baseline-models", default="",
                    help="comma-separated model IDs for the single-context baseline (live only)")
    ap.add_argument("--trials", type=int, default=1, help="baseline picks per model per level (live only)")
    ap.add_argument("--skip-isolated", action="store_true", help="run only the (cheap) baseline")
    ap.add_argument("--max-cost", type=float, default=None, help="hard USD cap (default $10 or MAX_COST_USD)")
    ap.add_argument("--yes", action="store_true", help="skip the cost confirmation prompt")
    args = ap.parse_args()

    models = [m.strip() for m in args.baseline_models.split(",") if m.strip()] or None
    if args.max_cost is not None:
        os.environ["MAX_COST_USD"] = str(args.max_cost)

    if is_live():
        os.environ["LIVE_STRICT"] = "1"  # a failed live call aborts instead of falling back
        m = models or [os.getenv("BASELINE_MODEL", DEFAULT_BASELINE_MODEL)]
        est = estimate_max_usd(m, args.trials, LEVELS, args.skip_isolated)
        print(f"LIVE run: baseline {m} x {args.trials} trial(s); "
              f"isolated {'skipped' if args.skip_isolated else SCOUT_MODEL}.")
        print(f"Worst-case estimate ${est:.2f}; hard cap ${cost_meter.max_cost_usd():.2f}.")
        if not args.yes and input("Proceed? [y/N] ").strip().lower() != "y":
            print("Aborted; nothing was spent.")
            return

    try:
        result = run_sweep(baseline_models=models, trials=args.trials, skip_isolated=args.skip_isolated)
    finally:
        if is_live():
            print("\n" + cost_meter.summary())

    _print_table(result)
    RESULTS_PATH.write_text(json.dumps(result, indent=2))
    print(f"\nWrote {RESULTS_PATH.name}.")


if __name__ == "__main__":
    main()
