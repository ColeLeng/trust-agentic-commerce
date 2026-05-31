"""
app/dashboard.py -- Trustpilot-style ranked catalog + live red-vs-blue view.

OWNER: Glue

Run:
    streamlit run app/dashboard.py

Three things on screen:
  1. METRIC PANEL          -- stores audited, fakes caught, avg trust, mode badge
  2. RANKED CATALOG        -- stores sorted by trust score, click a store to see
                              its reviews + blue's Evidence for each flagged fake
  3. "INJECT ATTACK" button -- red/evasion drops subtle fakes into a store live,
                              blue re-audits, and you watch the trust score move.

MOCK-FIRST: if results.json is missing, the dashboard generates it on the fly via
the same mock pipeline as run.py. Loads populated on a fresh clone with NO keys.

TODO(glue):
  - Add a per-round timeline of the analyzer<->scraper feedback loop.
  - Wire a "Red, evade THIS detector" button that passes the DetectorOutput to evasion.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blue.orchestrator import audit_store  # noqa: E402
from data.stores import load_stores  # noqa: E402
from llm import agent_available  # noqa: E402
from red.evasion import evolve  # noqa: E402
from red.generator import generate  # noqa: E402
from schema import AuditResult, DetectorOutput, Store  # noqa: E402

RESULTS_PATH = ROOT / "results.json"

st.set_page_config(page_title="Trust Agentic Commerce", page_icon="🛡️", layout="wide")


# --------------------------------------------------------------------------- #
# Data loading                                                                #
# --------------------------------------------------------------------------- #
def _build_fresh() -> AuditResult:
    stores = load_stores(with_mock_reviews=True)
    for s in stores:
        s.reviews = generate(s, n_clean=8, n_fake=4 if s.is_dirty else 1)
    detections = [audit_store(s) for s in stores]
    return AuditResult(used_real_agents=agent_available(), stores=stores, detections=detections)


@st.cache_data(show_spinner="Auditing catalog...")
def load_state_dict() -> dict:
    if RESULTS_PATH.exists():
        return AuditResult.model_validate_json(RESULTS_PATH.read_text()).model_dump(mode="json")
    return _build_fresh().model_dump(mode="json")


def get_state() -> AuditResult:
    if "audit" not in st.session_state:
        st.session_state.audit = AuditResult.model_validate(load_state_dict())
    return st.session_state.audit


def store_map(audit: AuditResult) -> dict[str, Store]:
    return {s.store_id: s for s in audit.stores}


def detection_map(audit: AuditResult) -> dict[str, DetectorOutput]:
    return {d.store_id: d for d in audit.detections}


# --------------------------------------------------------------------------- #
# Actions                                                                     #
# --------------------------------------------------------------------------- #
def inject_attack(store_id: str, n: int = 4) -> None:
    """Red drops subtle evasion fakes into a store; blue re-audits live."""
    audit = get_state()
    smap = store_map(audit)
    store = smap[store_id]
    target = detection_map(audit).get(store_id)
    new_fakes = evolve(store, n=n, target=target)
    store.reviews.extend(new_fakes)
    new_det = audit_store(store)
    audit.detections = [new_det if d.store_id == store_id else d for d in audit.detections]
    st.session_state.last_attack = (store_id, len(new_fakes))


def reset_state() -> None:
    st.session_state.pop("audit", None)
    st.session_state.pop("last_attack", None)
    load_state_dict.clear()


# --------------------------------------------------------------------------- #
# UI                                                                          #
# --------------------------------------------------------------------------- #
audit = get_state()
smap = store_map(audit)
dmap = detection_map(audit)
ranked = audit.ranked()

st.title("🛡️ Trust Agentic Commerce")
st.caption("Red-team agents plant fake reviews · Blue-team agents detect them · "
           "stores ranked by trust.")

# ---- Metric panel ----
total_reviews = sum(d.total_reviews for d in audit.detections)
total_fakes = sum(d.fake_count for d in audit.detections)
avg_trust = sum(d.trust_score for d in audit.detections) / len(audit.detections) if audit.detections else 0
mode = "🟢 REAL AGENTS" if audit.used_real_agents else "🟡 MOCK MODE"

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Stores audited", len(audit.stores))
c2.metric("Reviews scanned", total_reviews)
c3.metric("Fakes caught", total_fakes)
c4.metric("Avg trust", f"{avg_trust:.0f}/100")
c5.metric("Mode", mode)

if st.session_state.get("last_attack"):
    sid, k = st.session_state["last_attack"]
    st.warning(f"Red injected {k} evasion fake(s) into **{smap[sid].name}** — blue re-audited. "
               f"New trust score: **{dmap[sid].trust_score}/100**.")

with st.sidebar:
    st.header("Red vs. Blue")
    st.write("Pick a store and let **red** inject subtle fakes, then watch **blue** re-score it.")
    attack_target = st.selectbox("Target store", options=[s.store_id for s in audit.stores],
                                 format_func=lambda sid: smap[sid].name)
    n_attack = st.slider("Fakes to inject", 1, 8, 4)
    st.button("💉 Inject Attack", type="primary", use_container_width=True,
              on_click=inject_attack, args=(attack_target, n_attack))
    st.divider()
    st.button("↺ Reset catalog", use_container_width=True, on_click=reset_state)
    st.caption(f"codex CLI: {'available (real agents)' if agent_available() else 'absent (mock)'}")

st.divider()

# ---- Ranked catalog ----
st.subheader("Ranked catalog")
for rank, det in enumerate(ranked, start=1):
    store = smap[det.store_id]
    trust = det.trust_score
    color = "🟢" if trust >= 80 else "🟠" if trust >= 50 else "🔴"
    header = (f"{color}  #{rank}  {store.name}  —  trust {trust}/100  "
              f"·  {store.category}  ·  ${store.price}  ·  {det.fake_count} fake / {det.total_reviews}")
    with st.expander(header, expanded=(rank == 1)):
        meta = st.columns(4)
        meta[0].metric("Trust", f"{trust}/100")
        meta[1].metric("Flagged fake", det.fake_count)
        meta[2].metric("Total reviews", det.total_reviews)
        meta[3].metric("Feedback rounds", det.rounds)
        st.caption(det.summary)
        st.progress(min(1.0, trust / 100.0))

        rmap = {r.review_id: r for r in store.reviews}
        flagged = [v for v in det.verdicts if v.is_fake]
        if flagged:
            st.markdown("**🚩 Reviews blue flagged as fake (click-through evidence):**")
            for v in sorted(flagged, key=lambda x: x.confidence, reverse=True):
                r = rmap.get(v.review_id)
                if not r:
                    continue
                st.markdown(f"> _{r.text}_  \n"
                            f"— **{r.author}** · {r.rating}★ · confidence **{v.confidence:.2f}**")
                signals = ", ".join(f"`{e.signal}` ({e.weight:g})" for e in v.evidence)
                st.caption(f"Evidence: {signals or 'n/a'}")
                with st.popover("Why flagged?"):
                    for e in v.evidence:
                        st.write(f"- **{e.signal}** (w={e.weight}): {e.detail}")
        else:
            st.success("No fakes flagged — blue considers this catalog entry clean.")
