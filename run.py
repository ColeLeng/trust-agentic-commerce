"""
run.py -- the VERTICAL SLICE that wires everyone together.

OWNER: Glue

Pipeline:  load stores -> red.generate (per store) -> blue.audit -> write results.json

This is the integration spine. If this runs green on a fresh clone with NO API keys,
the team can develop their module in isolation and trust the seams.

    python run.py            # mock mode (no keys) — always works
    ANTHROPIC_API_KEY=... python run.py   # real red+blue agents

TODO(glue): add a --rounds flag and a --no-red flag (audit raw mock reviews only).
"""

from __future__ import annotations

import json
from pathlib import Path

from blue.orchestrator import audit_all
from data.stores import load_stores
from llm import have_api_key
from red.generator import generate
from schema import AuditResult
from tracing import init_tracing

RESULTS_PATH = Path(__file__).parent / "results.json"


def main() -> None:
    init_tracing()
    real = have_api_key()
    mode = "REAL AGENTS" if real else "MOCK"
    print(f"=== Trust Agentic Commerce :: {mode} mode ===\n")

    # 1. Load the catalog (mock reviews attached by default).
    stores = load_stores(with_mock_reviews=True)

    # 2. RED: regenerate each store's reviews via the generator.
    #    (mock mode returns deterministic seeded reviews — same shape, no key needed)
    for store in stores:
        store.reviews = generate(store, n_clean=8, n_fake=4 if store.is_dirty else 1)
        planted = sum(1 for r in store.reviews if r.is_fake)
        print(f"  red  | {store.store_id} {store.name:26s} "
              f"{len(store.reviews):2d} reviews ({planted} planted fake)")

    print()

    # 3. BLUE: audit every store with the feedback-loop orchestrator.
    detections = audit_all(stores)
    for d in detections:
        print(f"  blue | {d.store_id} trust={d.trust_score:5.1f} "
              f"caught {d.fake_count}/{d.total_reviews} fakes in {d.rounds} round(s)")

    # 4. Persist the artifact the dashboard reads.
    result = AuditResult(used_real_agents=real, stores=stores, detections=detections)
    RESULTS_PATH.write_text(result.model_dump_json(indent=2))
    print(f"\nWrote {RESULTS_PATH.name}. Now run:  streamlit run app/dashboard.py")


if __name__ == "__main__":
    main()
