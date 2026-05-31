"""
app/dashboard.py -- Trustpilot-style ranked catalog + live red-vs-blue view.

OWNER: Glue

Run:
    streamlit run app/dashboard.py

  1. METRIC PANEL          -- stores audited, avg trust, the concierge's pick, mode
  2. RANKED CATALOG        -- stores sorted by each isolated scout's trust score;
                              click a store to see the scout's risk flags + evidence
  3. "INJECT ATTACK" button -- red/evasion drops subtle fakes into a store live, the
                              store's ISOLATED scout re-scores, the concierge re-picks.

Blue has ONE master agent: blue/concierge_agent.py. It spawns an isolated scout
(blue/scout_agent.scout_one) per store and adjudicates their structured reports.

MOCK-FIRST: if results.json is missing, it rebuilds via the same mock pipeline as
run.py. Populated on a fresh clone with NO keys.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blue.concierge_agent import ConciergeDecision, adjudicate, dispatch_scouts  # noqa: E402
from blue.scout_agent import ScoutReport, scout_one  # noqa: E402
from data.stores import load_stores  # noqa: E402
from llm import agent_available  # noqa: E402
from red.evasion import evolve  # noqa: E402
from red.generator import generate  # noqa: E402
from schema import Store  # noqa: E402

RESULTS_PATH = ROOT / "results.json"
st.set_page_config(page_title="Trust Agentic Commerce", page_icon="🛡️", layout="wide")


def _build_fresh() -> dict:
    stores = load_stores(with_mock_reviews=True)
    for s in stores:
        s.reviews = generate(s, n_clean=8, n_fake=4 if s.is_dirty else 1)
    reports = dispatch_scouts(stores)
    decision = adjudicate(reports)
    return {
        "used_real_agents": agent_available(),
        "stores": [s.model_dump(mode="json") for s in stores],
        "reports": [r.model_dump(mode="json") for r in reports],
        "decision": decision.model_dump(mode="json"),
    }


@st.cache_data(show_spinner="Auditing catalog...")
def load_state_dict() -> dict:
    if RESULTS_PATH.exists():
        return json.loads(RESULTS_PATH.read_text())
    return _build_fresh()


def get_state() -> dict:
    if "audit" not in st.session_state:
        st.session_state.audit = load_state_dict()
    return st.session_state.audit


def inject_attack(store_id: str, n: int = 4) -> None:
    """Red drops subtle evasion fakes into a store; its isolated scout re-scores."""
    audit = get_state()
    stores = [Store.model_validate(s) for s in audit["stores"]]
    smap = {s.store_id: s for s in stores}
    store = smap[store_id]
    store.reviews.extend(evolve(store, n=n))
    new_report = scout_one(store)
    reports = [ScoutReport.model_validate(r) for r in audit["reports"]]
    reports = [new_report if r.seller_id == store_id else r for r in reports]
    decision = adjudicate(reports)

    audit["stores"] = [s.model_dump(mode="json") for s in stores]
    audit["reports"] = [r.model_dump(mode="json") for r in reports]
    audit["decision"] = decision.model_dump(mode="json")
    st.session_state.last_attack = (store_id, n)


def reset_state() -> None:
    st.session_state.pop("audit", None)
    st.session_state.pop("last_attack", None)
    load_state_dict.clear()


# --------------------------------------------------------------------------- #
audit = get_state()
stores = {s["store_id"]: s for s in audit["stores"]}
reports = {r["seller_id"]: r for r in audit["reports"]}
decision = ConciergeDecision.model_validate(audit["decision"])
ranked = sorted(audit["reports"], key=lambda r: r["trust_score"], reverse=True)

st.title("🛡️ Trust Agentic Commerce")
st.caption("Red-team agents plant fake reviews · an ISOLATED blue scout audits each "
           "store · the concierge adjudicates the structured reports and picks a winner.")

total_reviews = sum(len(s["reviews"]) for s in audit["stores"])
avg_trust = sum(r["trust_score"] for r in audit["reports"]) / len(audit["reports"]) if audit["reports"] else 0
mode = "🟢 REAL AGENTS" if audit.get("used_real_agents") else "🟡 MOCK MODE"
winner_name = stores.get(decision.winner_seller_id, {}).get("name", decision.winner_seller_id)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Stores audited", len(audit["stores"]))
c2.metric("Reviews scanned", total_reviews)
c3.metric("Avg trust", f"{avg_trust:.0f}/100")
c4.metric("Concierge pick", winner_name)
c5.metric("Mode", mode)

st.success(f"🛎️ **Concierge recommends: {winner_name}** — {decision.why}")

if st.session_state.get("last_attack"):
    sid, k = st.session_state["last_attack"]
    st.warning(f"Red injected {k} evasion fake(s) into **{stores[sid]['name']}** — its isolated "
               f"scout re-scored to **{reports[sid]['trust_score']:.0f}/100**. "
               f"Concierge now picks **{winner_name}**.")

with st.sidebar:
    st.header("Red vs. Blue")
    st.write("Pick a store, let **red** inject subtle fakes, watch that store's "
             "**isolated scout** re-score and the **concierge** re-decide.")
    target = st.selectbox("Target store", options=list(stores.keys()),
                          format_func=lambda sid: stores[sid]["name"])
    n_attack = st.slider("Fakes to inject", 1, 8, 4)
    st.button("💉 Inject Attack", type="primary", use_container_width=True,
              on_click=inject_attack, args=(target, n_attack))
    st.divider()
    st.button("↺ Reset catalog", use_container_width=True, on_click=reset_state)
    st.caption(f"codex CLI: {'available' if agent_available() else 'absent (mock)'}")

st.divider()
st.subheader("Ranked catalog (by isolated scout trust score)")
for rank, rep in enumerate(ranked, start=1):
    store = stores[rep["seller_id"]]
    trust = rep["trust_score"]
    color = "🟢" if trust >= 70 else "🟠" if trust >= 40 else "🔴"
    crown = " 🛎️" if rep["seller_id"] == decision.winner_seller_id else ""
    header = (f"{color}  #{rank}  {store['name']}{crown}  —  trust {trust:.0f}/100  ·  "
              f"product {rep['product_score']:.0f}/100  ·  {rep['recommendation']}  ·  ${store['price']}")
    with st.expander(header, expanded=(rank == 1)):
        meta = st.columns(3)
        meta[0].metric("Trust", f"{trust:.0f}/100")
        meta[1].metric("Product fit", f"{rep['product_score']:.0f}/100")
        meta[2].metric("Confidence", f"{rep['confidence']:.2f}")
        if rep["risk_flags"]:
            st.markdown("**🚩 Risk flags:** " + ", ".join(f"`{f}`" for f in rep["risk_flags"]))
        st.progress(min(1.0, trust / 100.0))

        flagged_ids = {e["review_id"] for e in rep.get("evidence", [])}
        if rep.get("evidence"):
            st.markdown("**Why the scout was suspicious (click-through evidence):**")
            rmap = {r["review_id"]: r for r in store["reviews"]}
            for e in rep["evidence"]:
                rv = rmap.get(e["review_id"])
                quote = f"  \n> _{rv['text']}_ — {rv['author']}, {rv['rating']}★" if rv else ""
                st.markdown(f"- **{e['signal']}** (w={e['weight']}): {e['detail']}{quote}")
        else:
            st.success("No risk signals — the scout considers this store clean.")
