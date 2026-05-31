"""
app/dashboard.py -- the money-shot: baseline contamination vs. isolated defense.

OWNER: Glue

Run:
    streamlit run app/dashboard.py

What's on screen:
  1. METRIC PANEL  -- vertical, strategy, the BREAKING POINT, isolated-held badge, mode
  2. MONEY-SHOT TABLE -- contamination level x {baseline pick, isolated pick}, colored
                         green (honest) / red (dishonest). Baseline flips; isolated holds.
  3. LEVEL DRILL-DOWN -- pick a contamination level: see the baseline's contaminated
                         pick vs. the isolated scouts' leaderboard, click a dishonest
                         seller to read the EVIDENCE (fake reviews, risk flags,
                         injected claims) + the concierge's reasoning.
  4. WEAVE NOTE -- where to view the agent traces (the audit trail).

MOCK-FIRST: if results.json is missing, it builds the full sweep on the fly via
the same code path as run.py. Populated on a fresh clone with NO codex CLI.

TODO(glue): embed a live Weave trace iframe; add a red "Inject more fakes" button
that bumps the selected level and re-renders the baseline flip on camera.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from llm import agent_available  # noqa: E402
from run import build_audit  # noqa: E402
from schema import AuditRun, GroundTruth  # noqa: E402

RESULTS_PATH = ROOT / "results.json"
st.set_page_config(page_title="Trust Agentic Commerce", page_icon="🛡️", layout="wide")


@st.cache_data(show_spinner="Running contamination sweep...")
def _load_dict() -> dict:
    if RESULTS_PATH.exists():
        return AuditRun.model_validate_json(RESULTS_PATH.read_text()).model_dump(mode="json")
    return build_audit().model_dump(mode="json")


def get_run() -> AuditRun:
    if "run" not in st.session_state:
        st.session_state.run = AuditRun.model_validate(_load_dict())
    return st.session_state.run


run = get_run()
q = run.question
honest = set(run.honest_seller_ids)


def seller_name(exp, sid: str) -> str:
    for s in exp.sellers:
        if s.seller_id == sid:
            return s.name
    return sid


def badge(sid: str) -> str:
    return "🟢 honest" if sid in honest else "🔴 DISHONEST"


# --------------------------------------------------------------------------- #
st.title("🛡️ Trust Agentic Commerce")
st.caption("AI shopping agents get contaminated by seller-side fake reviews. We give "
           "each seller an **isolated scout**, then a **concierge** adjudicates only "
           "structured evidence — so contamination stays quarantined.")

bp = run.breaking_point
isolated_held = all(e.isolated_picked_honest for e in run.experiments)
mode = "🟢 REAL AGENTS" if run.used_real_agents else "🟡 MOCK MODE"

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Vertical", q.vertical.split(" under")[0].title())
c2.metric("Merchants", q.n_merchants)
c3.metric("Baseline breaks at", f"{bp:.0%}" if bp is not None else "—")
c4.metric("Isolated held", "✅ yes" if isolated_held else "❌ no")
c5.metric("Mode", mode)

st.divider()

# ---- Money-shot table ----
st.subheader("The money-shot — contamination vs. who each system picks")
st.write(f"Strategy: **{q.strategies[0].value}** · buyer: _{q.product_query}_")

hdr = st.columns([1.2, 2.5, 2.5])
hdr[0].markdown("**Contamination**")
hdr[1].markdown("**Baseline (single context)**")
hdr[2].markdown("**Isolated scouts + concierge**")
for e in sorted(run.experiments, key=lambda x: x.contamination_level):
    row = st.columns([1.2, 2.5, 2.5])
    row[0].markdown(f"### {e.contamination_level:.0%}")
    b_sid, i_sid = e.baseline.chosen_seller_id, e.isolated.winner_seller_id
    b_color = "#1b7f3b" if e.baseline_picked_honest else "#b00020"
    i_color = "#1b7f3b" if e.isolated_picked_honest else "#b00020"
    row[1].markdown(
        f"<div style='background:{b_color};color:white;padding:8px;border-radius:6px'>"
        f"{seller_name(e, b_sid)} — {badge(b_sid)}</div>", unsafe_allow_html=True)
    row[2].markdown(
        f"<div style='background:{i_color};color:white;padding:8px;border-radius:6px'>"
        f"{seller_name(e, i_sid)} — {badge(i_sid)}</div>", unsafe_allow_html=True)

if bp is not None:
    st.error(f"⚠️ The single-context baseline flips to a **dishonest** seller at "
             f"**{bp:.0%}** contamination. The isolated system keeps picking an honest seller.")

st.divider()

# ---- Level drill-down ----
st.subheader("Drill into a contamination level")
levels = [e.contamination_level for e in sorted(run.experiments, key=lambda x: x.contamination_level)]
sel = st.select_slider("Contamination level (red attack strength)", options=levels,
                       value=bp if bp in levels else levels[-1],
                       format_func=lambda x: f"{x:.0%}")
exp = next(e for e in run.experiments if e.contamination_level == sel)
scouts = {o.seller_id: o for o in exp.scout_outputs}

left, right = st.columns(2)
with left:
    st.markdown("#### 🧠 Baseline (one shared context)")
    st.markdown(f"Picked **{seller_name(exp, exp.baseline.chosen_seller_id)}** — {badge(exp.baseline.chosen_seller_id)}")
    st.caption(exp.baseline.why)
    if not exp.baseline_picked_honest:
        st.error("Contaminated: the fake-review flood / injected claims won.")
    else:
        st.success("Held at this level.")
with right:
    st.markdown("#### 🛰️ Isolated scouts + concierge")
    st.markdown(f"Picked **{seller_name(exp, exp.isolated.winner_seller_id)}** — {badge(exp.isolated.winner_seller_id)}")
    st.caption(exp.isolated.why)
    if exp.isolated_picked_honest:
        st.success("Held: each scout quarantined its seller's contamination.")
    else:
        st.error("Isolated system also fooled at this level.")

st.markdown("#### Scout leaderboard (each scout saw only its own seller)")
for o in sorted(exp.scout_outputs, key=lambda x: (x.trust_score, x.product_score), reverse=True):
    seller = next(s for s in exp.sellers if s.seller_id == o.seller_id)
    color = "🟢" if o.trust_score >= 75 else "🟠" if o.trust_score >= 45 else "🔴"
    gt = "honest" if seller.ground_truth == GroundTruth.CLEAN else "DISHONEST"
    title = (f"{color} {seller.name} — trust {o.trust_score:.0f}/100 · product {o.product_score:.0f}/100 "
             f"· {o.recommendation.value} · [{gt}] · ${seller.price:.0f}")
    with st.expander(title, expanded=(o.seller_id == exp.isolated.winner_seller_id)):
        if o.risk_flags:
            st.markdown("**Risk flags:** " + ", ".join(f"`{f}`" for f in o.risk_flags))
        st.caption(o.notes)
        injected = [c for c in seller.claims if c.kind == "injection"]
        if injected:
            st.warning("Prompt-injection attempt in seller claims: " + " ".join(c.text for c in injected))
        if o.evidence:
            st.markdown("**Evidence:**")
            for ev in o.evidence[:6]:
                st.write(f"- `{ev.signal}` (w={ev.weight}): {ev.detail}")
        fakes = [r for r in seller.reviews if r.is_fake]
        if fakes:
            st.markdown(f"**Sample flagged reviews ({len(fakes)} fake of {len(seller.reviews)}):**")
            for r in fakes[:4]:
                st.markdown(f"> _{r.text}_ — {r.author}, {r.rating:.1f}★")

with st.sidebar:
    st.header("Red vs. Blue")
    st.write("Drag the contamination slider up to watch the **baseline flip** to a "
             "dishonest seller while the **isolated** system holds.")
    st.divider()
    st.subheader("Weave trace (audit trail)")
    st.write("Every agent call (red generator, each isolated scout, concierge) is "
             "traced. Run with `WANDB_API_KEY` set, then open the Weave project "
             "`trust-agentic-commerce` to show: red generated contamination → each "
             "scout ran separately → concierge saw only structured outputs.")
    st.caption(f"codex CLI: {'available (real agents)' if agent_available() else 'absent (mock)'}")
    st.button("↺ Rebuild sweep", use_container_width=True,
              on_click=lambda: (st.session_state.pop("run", None), _load_dict.clear()))
