# 🛡️ Trust Agentic Commerce — *Context Isolation as a Defense*

**Multi-agent shopping defense built for a 5-hour hackathon (v3).**

> AI shopping agents are becoming buyers. When a buyer agent reads every seller's
> reviews and claims in **one shared context**, a dishonest seller can flood that
> context with fake reviews (and inject instructions over the ACP/UCP feed) until
> the agent trusts them. We defend by giving **each seller its own isolated scout
> agent**; a **concierge** then adjudicates only the scouts' *structured* outputs —
> never the raw seller propaganda. We prove a single-context **baseline** flips to a
> dishonest seller past a contamination threshold, while the **isolated** system holds.

**One-sentence pitch:** *We built a multi-agent shopping defense that isolates each
seller into its own scout context, preventing fake-review floods from contaminating
the buyer agent's final decision.*

---

## ⭐ The one hard rule: MOCK-FIRST

On a **fresh clone with no LLM backend**, both of these succeed and show the money-shot:

```bash
python run.py                      # prints the contamination table
streamlit run app/dashboard.py     # the visual money-shot + evidence drill-down
```

Every module ships a deterministic mock. When the **`codex` CLI** is installed and
logged in, the real red/blue agents run instead — same data shapes, no code changes.
**Do not break this guarantee.** It's how 5 people build in parallel without the demo
ever going dark.

> Real agents run through the **Codex CLI (`codex exec`)** — no Anthropic key/SDK.
> Tracing uses **Weave** (W&B / CoreWeave) when `WANDB_API_KEY` is set.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# (optional) real agents:  npm i -g @openai/codex && codex login
# (optional) tracing:      cp .env.example .env  # set WANDB_API_KEY

python run.py                      # contamination sweep -> results.json
streamlit run app/dashboard.py     # dashboard
python eval/run_eval.py            # threshold report + Salminen holdout P/R
```

## The money-shot (what's in the 2-min video)

| Contamination | Baseline (single context) | Isolated scouts + concierge |
|--------------:|---------------------------|-----------------------------|
| 0%            | 🟢 honest seller          | 🟢 honest seller            |
| 20%           | 🟢 honest seller          | 🟢 honest seller            |
| 40%           | 🔴 **dishonest seller**   | 🟢 honest seller            |
| 60%           | 🔴 **dishonest seller**   | 🟢 honest seller            |

Then click into the dishonest seller → see the **evidence** (timestamp-clustered
fake-review burst, repeated phrasing, uniform 5★ sentiment, injected "system" claim)
→ then the **Weave trace** proving each scout ran in isolation and the concierge only
ever saw structured outputs.

---

## Architecture

```
 Red2 question_agent ─────────────► BuyerQuestion (vertical, personal context,
        (the scenario + experiments)   #merchants, contamination levels/strategies)
                                              │
 Red1 seller_agent ──► SellerProfile[] ◄──────┘   (UCP/ACP merchant feed; acp/protocol.py)
   (contaminates dirty sellers)   │
                ┌─────────────────┴───────────────────────────┐
                ▼                                              ▼
   baseline/buyer_agent  (CONTROL)                blue/planner_agent
   reads ALL sellers in ONE context               spawns 1 ISOLATED scout per seller
                │                                              │
                ▼                                              ▼
        BaselineDecision  ◄── compare vs ──►   blue/scout_agent ──► ScoutOutput[]
        (gets contaminated)   ground truth              │  (one seller, one context)
                                                        ▼
                                          blue/concierge_agent (sees ONLY ScoutOutputs)
                                                        ▼
                                               ConciergeDecision
   run.py sweeps contamination levels ──► ExperimentResult[] ──► AuditRun (results.json)
                                                        ▼
                                            app/dashboard.py (money-shot)
```

The orchestration reads as **agents fighting**, not a pipeline: red actively
contaminates / evades, the planner fans out to isolated scouts, and the concierge
adjudicates. That's what scores on "Most Sophisticated Harness."

## Ownership map — work in parallel without collisions

| Path | Owner | What it does |
|------|-------|--------------|
| `schema.py` | **Whole team (frozen at H0)** | The contract. Changes need sign-off. |
| `acp/protocol.py` | **Glue** | UCP/ACP merchant feed + agent card; `render_buyer_context()` = the injection surface. |
| `tracing.py` · `llm.py` | **Glue** | Weave `@traced` + Codex CLI backend (both mock-safe). |
| `data/marketplace.py` | **Data / Glue** | 6 sellers (3 honest/3 dishonest) + contamination levels. |
| `red/question_agent.py` | **🔴 Red 2** | Buyer question + personal context + experiment set. |
| `red/seller_agent.py` | **🔴 Red 1** | Simulates sellers under contamination strategy/difficulty. |
| `red/generator.py` · `red/evasion.py` | **🔴 Red** | Fake-review flood + the one evasion move. |
| `blue/planner_agent.py` | **🔵 Blue** | Interprets the question, spawns isolated scouts. |
| `blue/scout_agent.py` | **🔵 Blue** | Isolated per-seller investigation → `ScoutOutput`. |
| `blue/concierge_agent.py` | **🔵 Blue** | Adjudicates structured scout outputs → `ConciergeDecision`. |
| `blue/signals.py` | **🔵 Blue** | Shared fake-review detection heuristics. |
| `baseline/buyer_agent.py` | **Glue / Blue** | Single-context control (the vulnerable agent). |
| `eval/run_eval.py` | **Blue / Eval** | Contamination threshold + Salminen holdout P/R. |
| `app/dashboard.py` | **🟢 Glue** | Money-shot table, evidence drill-down, Weave note. |

### 5-person split (2 red / 2 blue / 1 glue)

- **Red 1** → `red/seller_agent.py` (+ `generator.py`): contamination strategies & difficulty
- **Red 2** → `red/question_agent.py` (+ `evasion.py`): the buyer scenario & experiment design
- **Blue 1** → `blue/scout_agent.py` + `blue/signals.py`: isolated investigation & evidence
- **Blue 2** → `blue/planner_agent.py` + `blue/concierge_agent.py` + `eval/`: orchestration & honest metrics
- **Glue** → `app/dashboard.py` + `acp/` + `schema.py` + Weave + the 2-min recording

## The frozen contract (`schema.py`)

`BuyerQuestion` · `PersonalContext` · `SellerProfile` · `Review` · `Claim` ·
`ScoutOutput` (trust_score, product_score, risk_flags, evidence, recommendation,
confidence) · `ConciergeDecision` · `BaselineDecision` · `ExperimentResult` ·
`AuditRun`. Agree on these at **H0** before splitting.

## 5-hour timeline

- **H0 (0:00–0:30)** — all together: freeze `schema.py`, pick the vertical (wireless
  headphones < $150), 6 sellers (3/3), decide the money-shot. Glue scaffolds + Weave.
- **H1 (0:30–1:30)** — parallel: Red generates sellers/contamination; Blue builds the
  isolated scout + scoring; Glue stands up the UI shell + Weave everyone imports.
- **H2 (1:30–2:30)** — **vertical slice / go-no-go**: one level end-to-end, baseline vs.
  isolated, ugly but live. If it doesn't work by 2:30, cut scope.
- **H3 (2:30–3:30)** — breadth + pressure: all levels (0/20/40/60), one evasion move,
  find the contamination threshold where the baseline breaks.
- **H4 (3:30–4:30)** — honest eval: Salminen holdout precision/recall; freeze UI; start
  recording.
- **H5 (4:30–5:00)** — record the 2-min video, write submission copy, rehearse the pitch.

## Honest eval (non-negotiable)

`eval/run_eval.py` reports (A) the contamination threshold where the baseline flips,
and (B) the scout detector's precision/recall on the **Salminen 40k holdout** — fakes
the detector never trained on. Drop the CSV into `data/salminen_holdout/` (see its
README). "We tested against 40k published fakes the detector never saw" turns a
self-grading gotcha into a flex.

## Tech stack

Python 3.11 · Codex CLI `codex exec` (agents) · UCP/ACP data layer (`acp/`) ·
Weave / W&B (tracing) · Pydantic (schema) · Streamlit (dashboard).
Protocols: **MCP** for the agent–tool layer, **A2A / UCP** for the merchant↔buyer feed.
