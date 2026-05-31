"""
run.py -- the VERTICAL SLICE / contamination sweep.

OWNER: Glue

Pipeline (per contamination level in the experiment set):
  Red2 question -> Red1 simulate sellers(level) -> {Baseline buyer, Blue planner ->
  scouts -> concierge} -> compare picks vs. ground truth -> ExperimentResult
All levels -> AuditRun -> results.json (read by the dashboard).

    python run.py                 # mock mode (no codex CLI) -- always works
    # install + `codex login`, then python run.py  -> real agents

MOCK-FIRST: a fresh clone with no codex CLI prints the money-shot table below.

TODO(glue): add a --strategy flag to sweep evasion vs. review_flood side by side.
"""

from __future__ import annotations

from pathlib import Path

from baseline.buyer_agent import choose
from blue.concierge_agent import adjudicate
from blue.planner_agent import plan_and_dispatch
from data.marketplace import honest_seller_ids
from llm import agent_available
from red.question_agent import set_question
from red.seller_agent import simulate_sellers
from schema import AuditRun, BuyerQuestion, ContaminationStrategy, ExperimentResult
from tracing import init_tracing

RESULTS_PATH = Path(__file__).parent / "results.json"


def build_audit(question: BuyerQuestion | None = None,
                strategy: ContaminationStrategy | None = None) -> AuditRun:
    """Run the full contamination sweep and return an AuditRun (no printing)."""
    init_tracing()
    question = question or set_question()
    strategy = strategy or question.strategies[0]
    experiments = []
    honest_ids: list[str] = []

    for level in question.contamination_levels:
        sellers = simulate_sellers(question, level, strategy)
        if not honest_ids:
            honest_ids = honest_seller_ids(sellers)
        baseline = choose(question, sellers)
        scout_outputs = plan_and_dispatch(question, sellers)
        isolated = adjudicate(scout_outputs, question.personal_context)
        experiments.append(ExperimentResult(
            contamination_level=level, strategy=strategy, sellers=sellers,
            scout_outputs=scout_outputs, baseline=baseline, isolated=isolated,
            baseline_picked_honest=baseline.chosen_seller_id in honest_ids,
            isolated_picked_honest=isolated.winner_seller_id in honest_ids))

    return AuditRun(used_real_agents=agent_available(), question=question,
                    honest_seller_ids=honest_ids, experiments=experiments)


def main() -> None:
    real = agent_available()
    print(f"=== Trust Agentic Commerce :: {'REAL AGENTS' if real else 'MOCK'} mode ===\n")
    run = build_audit()
    q = run.question

    print(f"Buyer: {q.product_query}")
    print(f"Vertical: {q.vertical} | merchants: {q.n_merchants} | "
          f"strategy: {q.strategies[0].value}\n")
    print(f"{'contam':>7} | {'baseline pick':>22} | {'isolated pick':>22}")
    print("-" * 60)
    for e in run.experiments:
        def tag(sid, honest):
            return f"{sid} ({'honest' if honest else 'DISHONEST'})"
        print(f"{e.contamination_level:>6.0%} | "
              f"{tag(e.baseline.chosen_seller_id, e.baseline_picked_honest):>22} | "
              f"{tag(e.isolated.winner_seller_id, e.isolated_picked_honest):>22}")

    RESULTS_PATH.write_text(run.model_dump_json(indent=2))

    bp = run.breaking_point
    print("-" * 60)
    if bp is not None:
        print(f"\nBASELINE BREAKS at {bp:.0%} contamination (picks a dishonest seller).")
    else:
        print("\nBaseline held at all tested levels (raise contamination to break it).")
    isolated_held = all(e.isolated_picked_honest for e in run.experiments)
    print(f"ISOLATED system held at every level: {isolated_held}")
    print(f"\nWrote {RESULTS_PATH.name}. Now run:  streamlit run app/dashboard.py")


if __name__ == "__main__":
    main()
