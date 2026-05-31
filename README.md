# 🛡️ Trust Agentic Commerce

A multi-agent **trust audit** system for online stores, built for a 5-hour hackathon.

- **Red team** agents generate fake (and genuine) product reviews — including subtle
  "evasion" fakes designed to slip past detection.
- **Blue team** agents ingest each store's reviews, run a **feedback loop**
  (analyzer steers scraper: _"fetch more / look here"_), flag fakes with **evidence**,
  and assign each store a **trust score**.
- A **Streamlit dashboard** shows a Trustpilot-style ranked catalog, click-through
  evidence for every flagged review, and a live **red-vs-blue "Inject Attack"** view.

## ⭐ The one hard rule: MOCK-FIRST

On a **fresh clone with no LLM backend**, both of these succeed and show a populated
ranked catalog:

```bash
python run.py
streamlit run app/dashboard.py
```

Every module ships with a deterministic mock. When the **`codex` CLI** is installed
and logged in, the real red/blue agents run instead — same data shapes, no code
changes. **Do not break this guarantee.**

> We drive the model through the **Codex CLI (`codex exec`)** instead of the
> Anthropic SDK, so there's no API key or Python SDK to manage — it reuses your
> existing `codex` login. Tracing (Weave) still uses `WANDB_API_KEY` if present.

## Quickstart

```bash
# 1. install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. (optional) enable REAL agents — install + log in to the Codex CLI
npm install -g @openai/codex     # or: brew install codex
codex login                      # one-time
# (optional) tracing: cp .env.example .env and set WANDB_API_KEY

# 3. run the vertical slice (writes results.json)
python run.py                    # mock if no codex CLI; real agents if present

# 4. launch the dashboard
streamlit run app/dashboard.py

# 5. (optional) honest eval on the Salminen holdout
python eval/run_eval.py
```

## Ownership map — work in parallel without collisions

| Path | Owner | What it does |
|------|-------|--------------|
| `schema.py` | **Whole team (frozen contract)** | Pydantic models everyone shares. Changes need team sign-off. |
| `tracing.py` · `llm.py` | **Glue** | Weave `@traced` decorator + Codex CLI backend (both mock-safe). |
| `run.py` | **Glue** | Vertical slice: load → red → blue → `results.json`. |
| `data/stores.py` | **Data / Glue** | 6 stores (3 clean, 3 dirty) + deterministic mock reviews. |
| `data/salminen_holdout/` | **Blue / Eval** | Drop-in folder for the real 40k labeled fakes set. |
| `red/generator.py` | **🔴 Red** | LLM fake + clean review generator. |
| `red/evasion.py` | **🔴 Red** | Subtler fakes meant to beat blue. |
| `blue/scout_agent.py` | **🔵 Blue** | The **isolated scout**: audits ONE seller in its own context → `ScoutReport`. |
| `blue/concierge_agent.py` | **🔵 Blue** | **THE master agent** (the only one): spawns the isolated scouts and adjudicates their structured reports → `ConciergeDecision`. |
| `eval/run_eval.py` | **Blue / Eval** | Precision/recall of the scout's per-review signals on the holdout. |
| `app/dashboard.py` | **🟢 Glue** | Ranked catalog, scout evidence, Inject Attack, metrics. |

> **One master agent.** The blue side has exactly one coordinator —
> `blue/concierge_agent.py`. The old `planner` / `orchestrator` / `analyzer` /
> `scraper` agents were all the same role under different names; they've been
> consolidated into the concierge. Develop and upgrade THAT file.

### Suggested 5-person split (2 red / 2 blue / 1 glue)

- **Red 1** → `red/generator.py` (volume + realism of clean/fake reviews)
- **Red 2** → `red/evasion.py` (the arms race: beat blue's scout)
- **Blue 1** → `blue/scout_agent.py` (per-seller signals, weights, LLM second opinion)
- **Blue 2** → `blue/concierge_agent.py` + `eval/run_eval.py` (dispatch + adjudication + honest metrics)
- **Glue** → `app/dashboard.py` + `run.py` + keeps `schema.py` stable

The **frozen contract** in `schema.py` is the only shared surface — agree on it
first, then everyone codes against it independently.

## How the pieces talk

```
data/stores.py ──► red/generator.py ──► List[Review] ─┐
                       red/evasion.py ─┘               │
                                                       ▼
                                      blue/concierge_agent.py  (THE master agent)
                                          ├─ dispatch_scouts ─► blue/scout_agent.scout_one ×N  (ISOLATED)
                                          │                         └─► ScoutReport[]
                                          └─ adjudicate ──────────────► ConciergeDecision
                                                                              │
                                          run.py ──► results.json ──► app/dashboard.py
```

`schema.py` defines the shared objects: `Review`, `Store`, `Evidence`.
`ScoutReport` and `ConciergeDecision` live with their agents.

## Tech stack

Python 3.11 · Codex CLI `codex exec` (agents) · Weave/wandb (tracing) ·
Pydantic (schema) · Streamlit (dashboard).

---

## v3: Context Isolation as a Defense (the money-shot)

The headline architectural claim. A single-context shopping agent reads **every**
seller's reviews in one window, so a dishonest seller's fake-review flood (and
injected "system" instructions) can win past a contamination threshold. We defend
by giving each seller its **own isolated scout**, then the **concierge** (the one
master agent) adjudicates only the scouts' *structured* outputs — never the raw
seller text.

```
data/stores.contaminated_stores(level)
        │
        ├─► baseline/buyer_agent.choose()      # CONTROL: reads ALL sellers in ONE context
        │        └─► BaselineDecision           # gets contaminated past a threshold
        │
        └─► blue/concierge_agent  (THE master agent)
                 ├─ dispatch_scouts ─► blue/scout_agent.scout_one() ×N   # ISOLATED: one seller, one context
                 │                         └─► ScoutReport[]
                 └─ adjudicate ──────────────► ConciergeDecision         # structured-only
experiments/contamination_sweep.py  ──► defense_results.json ──► app/defense_dashboard.py
```

Run it (mock-first — works with no API key):

```bash
python experiments/contamination_sweep.py     # prints the contamination table
streamlit run app/defense_dashboard.py         # the visual money-shot
```

Expected money-shot: the **baseline** flips to a dishonest seller around **40%**
contamination, while the **isolated** system keeps picking an honest seller at
every level.

This layer reuses the existing `blue/scout_agent` (`scout_one`/`ScoutReport`,
isolated per seller), `schema.Store`, and `data/stores.py`. The pieces:
`blue/concierge_agent.py` (the master: `dispatch_scouts` + `adjudicate`),
`baseline/buyer_agent.py`, `experiments/contamination_sweep.py`,
`app/defense_dashboard.py`, plus `data.stores.contaminated_stores(level)`.
`ConciergeDecision` / `BaselineDecision` live with their agents (like `ScoutReport`)
so the frozen `schema.py` contract is untouched.
