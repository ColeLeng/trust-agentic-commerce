"""
run.py -- the VERTICAL SLICE that wires everyone together.

OWNER: Glue

Pipeline:  load stores -> red.generate (per store) -> blue concierge
           (spawns one ISOLATED scout per store, then adjudicates) -> results.json

The blue side has ONE master agent now: blue/concierge_agent.py. It spawns the
isolated scouts (blue/scout_agent.scout_one) and adjudicates their structured
reports. (The old planner/orchestrator/analyzer/scraper agents were consolidated
into the concierge.)

    python run.py            # mock mode (no keys) -- always works

This is a quick CLI sanity check of the red -> scout -> concierge flow. The visual
demo is the HTML/JS UI served by app/server.py (python -m app.server).

MOCK-FIRST: a fresh clone with no LLM backend prints the ranked scouts + the
concierge's pick and writes results.json.

TODO(glue): add a --contaminate LEVEL flag to seed fakes via data.stores.contaminated_stores.
"""

from __future__ import annotations

import json
from pathlib import Path

from blue.concierge_agent import adjudicate, dispatch_scouts
from data.stores import load_stores
from llm import agent_available
from red.generator import generate
from tracing import init_tracing

RESULTS_PATH = Path(__file__).parent / "results.json"


def main() -> None:
    init_tracing()
    real = agent_available()
    print(f"=== Trust Agentic Commerce :: {'REAL AGENTS' if real else 'MOCK'} mode ===\n")

    # 1. Load the catalog and have RED (re)generate each store's reviews.
    stores = load_stores(with_mock_reviews=True)
    for store in stores:
        store.reviews = generate(store, n_clean=8, n_fake=4 if store.is_dirty else 1)
        planted = sum(1 for r in store.reviews if r.is_fake)
        print(f"  red  | {store.store_id} {store.name:26s} "
              f"{len(store.reviews):2d} reviews ({planted} planted fake)")

    print()

    # 2. BLUE concierge: spawn one isolated scout per store, then adjudicate.
    reports = dispatch_scouts(stores)
    for r in reports:
        flags = ", ".join(r.risk_flags) or "none"
        print(f"  scout | {r.seller_id} trust={r.trust_score:5.1f} {r.recommendation:10s} flags=[{flags}]")
    decision = adjudicate(reports)
    print(f"\n  concierge | winner={decision.winner_seller_id} :: {decision.why}")

    # 3. Persist the artifact the dashboard reads.
    artifact = {
        "used_real_agents": real,
        "stores": [s.model_dump(mode="json") for s in stores],
        "reports": [r.model_dump(mode="json") for r in reports],
        "decision": decision.model_dump(mode="json"),
    }
    RESULTS_PATH.write_text(json.dumps(artifact, indent=2))
    print(f"\nWrote {RESULTS_PATH.name}. For the visual demo:  python -m app.server  (http://localhost:8000)")


if __name__ == "__main__":
    main()
