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

On a **fresh clone with NO API keys**, both of these succeed and show a populated
ranked catalog:

```bash
python run.py
streamlit run app/dashboard.py
```

Every module ships with a deterministic mock. When `ANTHROPIC_API_KEY` /
`WANDB_API_KEY` are present, the real agents and tracing run instead — same data
shapes, no code changes. **Do not break this guarantee.**

## Quickstart

```bash
# 1. install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. (optional) enable real agents + tracing
cp .env.example .env        # then fill in ANTHROPIC_API_KEY / WANDB_API_KEY

# 3. run the vertical slice (writes results.json)
python run.py

# 4. launch the dashboard
streamlit run app/dashboard.py

# 5. (optional) honest eval on the Salminen holdout
python eval/run_eval.py
```

## Ownership map — work in parallel without collisions

| Path | Owner | What it does |
|------|-------|--------------|
| `schema.py` | **Whole team (frozen contract)** | Pydantic models everyone shares. Changes need team sign-off. |
| `tracing.py` · `llm.py` | **Glue** | Weave `@traced` decorator + Anthropic client (both mock-safe). |
| `run.py` | **Glue** | Vertical slice: load → red → blue → `results.json`. |
| `data/stores.py` | **Data / Glue** | 6 stores (3 clean, 3 dirty) + deterministic mock reviews. |
| `data/salminen_holdout/` | **Blue / Eval** | Drop-in folder for the real 40k labeled fakes set. |
| `red/generator.py` | **🔴 Red** | LLM fake + clean review generator. |
| `red/evasion.py` | **🔴 Red** | Subtler fakes meant to beat blue. |
| `blue/scraper_agent.py` | **🔵 Blue** | Ingests a store's reviews (steerable). |
| `blue/analyzer_agent.py` | **🔵 Blue** | Heuristic + LLM fake detection → `Verdict` + `Evidence`. |
| `blue/orchestrator.py` | **🔵 Blue** | The **feedback loop**, emits `DetectorOutput`. |
| `eval/run_eval.py` | **Blue / Eval** | Precision/recall of blue on the holdout. |
| `app/dashboard.py` | **🟢 Glue** | Ranked catalog, evidence, Inject Attack, metrics. |

### Suggested 5-person split (2 red / 2 blue / 1 glue)

- **Red 1** → `red/generator.py` (volume + realism of clean/fake reviews)
- **Red 2** → `red/evasion.py` (the arms race: beat blue's current detectors)
- **Blue 1** → `blue/analyzer_agent.py` (signals, weights, LLM second opinion)
- **Blue 2** → `blue/orchestrator.py` + `eval/run_eval.py` (loop logic + honest metrics)
- **Glue** → `app/dashboard.py` + `run.py` + keeps `schema.py` stable

The **frozen contract** in `schema.py` is the only shared surface — agree on it
first, then everyone codes against it independently.

## How the pieces talk

```
data/stores.py ──► red/generator.py ──► List[Review] ──► blue/orchestrator.py
                       red/evasion.py ─┘   (feedback loop)        │
                                                                  ▼
                                                          DetectorOutput
                                                                  │
                                          run.py ──► results.json ──► app/dashboard.py
```

`schema.py` defines every object on those arrows: `Review`, `Store`, `Evidence`,
`Verdict`, `DetectorOutput`, `AuditResult`.

## Tech stack

Python 3.11 · Anthropic SDK (agents) · Weave/wandb (tracing) · Pydantic (schema) ·
Streamlit (dashboard).
