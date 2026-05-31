"""
app/defense_dashboard.py -- the v3 money-shot view (context-isolation defense).

OWNER: Glue

Run:
    streamlit run app/defense_dashboard.py

Shows the contamination sweep: at each level, the single-context BASELINE vs. the
ISOLATED planner -> scouts -> concierge, colored green (honest) / red (dishonest).
The baseline flips past a threshold; the isolated system holds. Drill into a level
to see each scout's trust score + evidence and the concierge's reasoning.

Separate from app/dashboard.py and app/server.py so it doesn't collide with the
existing UIs. Reads defense_results.json (built by experiments/contamination_sweep);
rebuilds on the fly if missing. MOCK-FIRST: works with no API key.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.contamination_sweep import run_sweep  # noqa: E402

RESULTS_PATH = ROOT / "defense_results.json"
st.set_page_config(page_title="Context-Isolation Defense", page_icon="🛡️", layout="wide")


@st.cache_data(show_spinner="Running contamination sweep...")
def load_result() -> dict:
    if RESULTS_PATH.exists():
        import json
        return json.loads(RESULTS_PATH.read_text())
    return run_sweep()


result = load_result()
honest = set(result["honest_store_ids"])
exps = sorted(result["experiments"], key=lambda e: e["contamination_level"])


def chip(name: str, is_honest: bool) -> str:
    color = "#1b7f3b" if is_honest else "#b00020"
    label = "honest" if is_honest else "DISHONEST"
    return (f"<div style='background:{color};color:white;padding:8px;border-radius:6px'>"
            f"{name} — {label}</div>")


st.title("🛡️ Context Isolation as a Defense")
st.caption("A single-context shopping agent gets contaminated by seller-side fake "
           "reviews. We isolate each seller into its own scout, then a concierge "
           "adjudicates only structured evidence — so contamination stays quarantined.")

bp = result["breaking_point"]
c1, c2, c3 = st.columns(3)
c1.metric("Baseline breaks at", f"{bp:.0%}" if bp is not None else "—")
c2.metric("Isolated held", "✅ yes" if result["isolated_held"] else "❌ no")
c3.metric("Sellers", len(result["store_names"]))

st.divider()
st.subheader("The money-shot — contamination vs. who each system picks")
hdr = st.columns([1, 2.5, 2.5])
hdr[0].markdown("**Contamination**")
hdr[1].markdown("**Baseline (single context)**")
hdr[2].markdown("**Isolated scouts + concierge**")
for e in exps:
    row = st.columns([1, 2.5, 2.5])
    row[0].markdown(f"### {e['contamination_level']:.0%}")
    row[1].markdown(chip(e["baseline_pick_name"], e["baseline_picked_honest"]), unsafe_allow_html=True)
    row[2].markdown(chip(e["isolated_pick_name"], e["isolated_picked_honest"]), unsafe_allow_html=True)

if bp is not None:
    st.error(f"⚠️ The single-context baseline flips to a **dishonest** seller at "
             f"**{bp:.0%}** contamination. The isolated system keeps picking honest.")

st.divider()
st.subheader("Drill into a contamination level")
levels = [e["contamination_level"] for e in exps]
sel = st.select_slider("Contamination level (red attack strength)", options=levels,
                       value=bp if bp in levels else levels[-1], format_func=lambda x: f"{x:.0%}")
exp = next(e for e in exps if e["contamination_level"] == sel)
store_by_id = {s["store_id"]: s for s in exp["stores"]}

left, right = st.columns(2)
with left:
    st.markdown("#### 🧠 Baseline (one shared context)")
    st.markdown(chip(exp["baseline_pick_name"], exp["baseline_picked_honest"]), unsafe_allow_html=True)
    st.caption(exp["baseline_why"])
    st.error("Contaminated: the flood / injection won.") if not exp["baseline_picked_honest"] \
        else st.success("Held at this level.")
with right:
    st.markdown("#### 🛰️ Isolated scouts + concierge")
    st.markdown(chip(exp["isolated_pick_name"], exp["isolated_picked_honest"]), unsafe_allow_html=True)
    st.caption(exp["isolated_why"])
    st.success("Held: each scout quarantined its seller.") if exp["isolated_picked_honest"] \
        else st.error("Isolated system also fooled here.")

st.markdown("#### Scout leaderboard (each scout saw only its own seller)")
for r in sorted(exp["scout_reports"], key=lambda x: (x["trust_score"], x["product_score"]), reverse=True):
    store = store_by_id.get(r["seller_id"], {})
    is_honest = r["seller_id"] in honest
    color = "🟢" if r["trust_score"] >= 70 else "🟠" if r["trust_score"] >= 40 else "🔴"
    title = (f"{color} {store.get('name', r['seller_id'])} — trust {r['trust_score']:.0f}/100 · "
             f"product {r['product_score']:.0f}/100 · {r['recommendation']} · "
             f"[{'honest' if is_honest else 'DISHONEST'}]")
    with st.expander(title, expanded=(r["seller_id"] == exp["isolated_pick"])):
        if r["risk_flags"]:
            st.markdown("**Risk flags:** " + ", ".join(f"`{f}`" for f in r["risk_flags"]))
        for ev in r.get("evidence", [])[:6]:
            st.write(f"- `{ev['signal']}` (w={ev['weight']}): {ev['detail']}")
        fakes = [rv for rv in store.get("reviews", []) if rv.get("is_fake")]
        if fakes:
            st.markdown(f"**Sample flagged reviews ({len(fakes)} fake of {len(store.get('reviews', []))}):**")
            for rv in fakes[:4]:
                st.markdown(f"> _{rv['text']}_ — {rv['author']}, {rv['rating']:.1f}★")

with st.sidebar:
    st.header("Red vs. Blue")
    st.write("Drag the slider up to watch the **baseline flip** to a dishonest seller "
             "while the **isolated** system holds.")
    st.divider()
    st.caption("Built on the team's blue/scout_agent (isolated per-seller) + the new "
               "planner/concierge and baseline control. Reuses data/stores.py.")
    st.button("↺ Rebuild sweep", use_container_width=True,
              on_click=lambda: (load_result.clear()))
