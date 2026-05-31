"""
blue/scout_agent.py -- 4 specialized security sub-agents + aggregation.

OWNER: Blue team

scout_one(store) runs four independent sub-agents on ONE seller's data:
  1. indirect_prompt_injection  -- injection attacks in listing / review fields
  2. commerce_fraud_bto         -- mandate abuse, bot takeover, cart poisoning
  3. fraudulent_storefront_lure -- fake storefronts, identity-thin merchants
  4. logic_hijacking_returns    -- return/refund workflow manipulation

Each sub-agent loads its spec from blue/security_checks/*.md, analyses ONE seller
in isolation, and returns a SubAgentFinding. scout_one aggregates the four findings
using the team decision rules and maps them to ScoutReport — the downstream
pipeline (orchestrator, dashboard, eval) is unaffected.

Aggregation rules:
  - Any block                   → block  → recommendation = "risky"
  - 2+ needs_manual_review      → needs_manual_review → "suspicious"
  - Any allow_with_constraints  → allow_with_constraints → "suspicious"
  - All allow                   → allow → "safe"

MOCK-FIRST: no ANTHROPIC_API_KEY → heuristic checks per sub-agent, deterministic.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

from schema import Evidence, Store
from tracing import traced

# ---------------------------------------------------------------------------
# Spec files (loaded once at import time)
# ---------------------------------------------------------------------------

_SPEC_DIR = Path(__file__).resolve().parent / "security_checks"

def _load_spec(name: str) -> str:
    p = _SPEC_DIR / f"{name}.md"
    return p.read_text(encoding="utf-8") if p.exists() else f"# {name} check"

_SPECS = {
    "indirect_prompt_injection": _load_spec("indirect_prompt_injection"),
    "commerce_fraud_bto":        _load_spec("commerce_fraud_bto"),
    "fraudulent_storefront_lure":_load_spec("fraudulent_storefront_lure"),
    "logic_hijacking_returns":   _load_spec("logic_hijacking_returns"),
}

# ---------------------------------------------------------------------------
# Internal models
# ---------------------------------------------------------------------------

class _Finding(BaseModel):
    id: str
    severity: str          # "low" | "medium" | "high" | "critical"
    signal: str
    evidence: str
    reason: str

class SubAgentFinding(BaseModel):
    agent: str
    risk_level: str        # "low" | "medium" | "high" | "critical"
    decision: str          # "allow" | "allow_with_constraints" | "block" | "needs_manual_review"
    findings: List[_Finding] = Field(default_factory=list)

# ---------------------------------------------------------------------------
# Output contract (unchanged — rest of pipeline depends on this)
# ---------------------------------------------------------------------------

class ScoutReport(BaseModel):
    seller_id: str
    trust_score: float = Field(ge=0.0, le=100.0)
    product_score: float = Field(ge=0.0, le=100.0)
    risk_flags: List[str] = Field(default_factory=list)
    evidence: List[Evidence] = Field(default_factory=list)
    recommendation: str     # "safe" | "suspicious" | "risky"
    confidence: float = Field(ge=0.0, le=1.0)

# ---------------------------------------------------------------------------
# JSON schema for structured LLM output (sub-agent level)
# ---------------------------------------------------------------------------

_SUBAGENT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "agent":      {"type": "string"},
        "risk_level": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
        "decision":   {"type": "string",
                       "enum": ["allow", "allow_with_constraints",
                                "block", "needs_manual_review"]},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id":       {"type": "string"},
                    "severity": {"type": "string"},
                    "signal":   {"type": "string"},
                    "evidence": {"type": "string"},
                    "reason":   {"type": "string"},
                },
                "required": ["id", "severity", "signal", "evidence", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["agent", "risk_level", "decision", "findings"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------
# Shared prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(store: Store) -> str:
    lines = [
        f"SELLER_ID  : {store.store_id}",
        f"NAME       : {store.name}",
        f"CATEGORY   : {store.category}",
        f"ASIN       : {store.asin}",
        f"PRICE (USD): {store.price:.2f}",
        "",
        f"REVIEWS ({len(store.reviews)} total):",
    ]
    for r in store.reviews:
        ts = r.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
        vflag = "VERIFIED" if r.verified_purchase else "unverified"
        lines.append(
            f"  [{r.review_id}] rating={r.rating:.1f} "
            f"author={r.author} ts={ts} {vflag}"
        )
        lines.append(f'    "{r.text}"')
    return "\n".join(lines)

def _det_seed(store_id: str) -> int:
    return int(hashlib.sha256(store_id.encode()).hexdigest(), 16) % (2 ** 32)

# ---------------------------------------------------------------------------
# Live helper: one API call per sub-agent
# ---------------------------------------------------------------------------

def _live_call(
    client,
    agent_name: str,
    spec_text: str,
    store: Store,
) -> SubAgentFinding:
    system_prompt = (
        f"{spec_text}\n\n"
        "You are performing the security check described above on ONE seller.\n"
        "Output ONLY a JSON object with keys: agent, risk_level, decision, findings.\n"
        "Each finding must have: id (use review_id or '<seller_id>-meta'), "
        "severity, signal (from the Risk Signals section), evidence, reason.\n"
        "Set agent to the check name. Set risk_level and decision per Output Expectations."
    )
    try:
        msg = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=2048,
            thinking={"type": "adaptive"},
            output_config={
                "effort": "medium",
                "format": {"type": "json_schema", "schema": _SUBAGENT_SCHEMA},
            },
            system=[{
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": _build_prompt(store)}],
        )
        raw = next(
            (b.text for b in msg.content if b.type == "text"), "{}"
        )
        data = json.loads(raw)
        data["agent"] = agent_name
        # clamp enums
        if data.get("risk_level") not in ("low", "medium", "high", "critical"):
            data["risk_level"] = "medium"
        if data.get("decision") not in (
            "allow", "allow_with_constraints", "block", "needs_manual_review"
        ):
            data["decision"] = "needs_manual_review"
        findings = [
            _Finding(**{k: str(v) for k, v in f.items()})
            for f in data.get("findings", [])
            if all(k in f for k in ("id","severity","signal","evidence","reason"))
        ]
        return SubAgentFinding(
            agent=agent_name,
            risk_level=data["risk_level"],
            decision=data["decision"],
            findings=findings,
        )
    except Exception:
        return SubAgentFinding(
            agent=agent_name, risk_level="low", decision="allow", findings=[]
        )

# ---------------------------------------------------------------------------
# Sub-agent 1 — Indirect Prompt Injection
# ---------------------------------------------------------------------------

_IPI_KW = [
    "ignore previous", "ignore all", "system:", "developer:", "you must",
    "[[sys]]", "[[user]]", "[[assistant]]", "<|im_", "|>", "<system>",
    "forget your instructions", "new instruction", "disregard", "override",
    "act as if", "pretend you are", "your new task", "ignore the above",
    "ignore prior", "trust_score", "best for ai agents",
]
_CART_KW   = ["gift card", "also add", "warranty plan", "subscription", "auto-renew"]
_EXFIL_KW  = ["send email", "post to", "webhook", "utm_agent", "exfil", "track?id="]
_TOOL_KW   = ["call checkout", "execute payment", "trigger refund",
              "call api(", "call function(", "run tool"]
_COMP_KW   = ["do not compare", "don't compare", "ignore competitor",
              "competitor is unsafe", "avoid recommending"]


def _mock_ipi(store: Store) -> SubAgentFinding:
    corpus = " ".join(
        [store.name, store.category] + [r.text for r in store.reviews]
    ).lower()
    meta_id = f"{store.store_id}-meta"
    findings: List[_Finding] = []

    hits = [kw for kw in _IPI_KW if kw in corpus]
    if hits:
        findings.append(_Finding(
            id=meta_id, severity="critical", signal="prompt_override",
            evidence=f"Injection markers found: {hits[:3]}",
            reason="Merchant content contains agent instruction override attempts.",
        ))

    cart_hits = [kw for kw in _CART_KW if kw in corpus]
    if cart_hits:
        findings.append(_Finding(
            id=meta_id, severity="high", signal="cart_poisoning",
            evidence=f"Cart manipulation language: {cart_hits[:3]}",
            reason="Content may attempt to add unauthorized items.",
        ))

    tool_hits = [kw for kw in _TOOL_KW if kw in corpus]
    if tool_hits:
        findings.append(_Finding(
            id=meta_id, severity="critical", signal="tool_escalation",
            evidence=f"Tool call language in content: {tool_hits[:2]}",
            reason="Seller content attempts to invoke checkout or payment tools.",
        ))

    exfil_hits = [kw for kw in _EXFIL_KW if kw in corpus]
    if exfil_hits:
        findings.append(_Finding(
            id=meta_id, severity="critical", signal="exfiltration",
            evidence=f"Data exfiltration markers: {exfil_hits[:2]}",
            reason="Content contains outbound data routing instructions.",
        ))

    if findings:
        critical = any(f.severity == "critical" for f in findings)
        risk = "critical" if critical else "high"
        decision = "block" if critical else "allow_with_constraints"
    else:
        risk, decision = "low", "allow"

    return SubAgentFinding(
        agent="indirect_prompt_injection",
        risk_level=risk,
        decision=decision,
        findings=findings,
    )


def run_injection_check(store: Store, client=None) -> SubAgentFinding:
    if client:
        return _live_call(
            client, "indirect_prompt_injection",
            _SPECS["indirect_prompt_injection"], store,
        )
    return _mock_ipi(store)

# ---------------------------------------------------------------------------
# Sub-agent 2 — Commerce Fraud / Bot Takeover
# ---------------------------------------------------------------------------

_MANDATE_KW  = ["bypass limit", "no limit", "unlimited budget",
                "ignore cap", "override mandate", "no spending cap"]
_HIGH_LIQ_KW = ["gift card", "crypto", "resell", "bulk purchase",
                "easy to resell", "high value"]
_CHEAP_ELECTRONICS_THRESHOLD = 10.0   # Electronics/Health under $10 is suspicious


def _mock_fraud_bto(store: Store) -> SubAgentFinding:
    reviews = store.reviews
    total = len(reviews)
    meta_id = f"{store.store_id}-meta"
    findings: List[_Finding] = []

    # Timestamp burst: meaningful only when reviews actually have spread timestamps.
    # If all timestamps are within 60 seconds it is a mock-data artifact, not a signal.
    if total >= 4:
        timestamps = sorted(r.timestamp for r in reviews)
        overall_span = (timestamps[-1] - timestamps[0]).total_seconds()
        if overall_span > 60:
            for i in range(len(timestamps) - 3):
                window = timestamps[i + 3] - timestamps[i]
                if window < timedelta(minutes=30):
                    findings.append(_Finding(
                        id=reviews[0].review_id, severity="high",
                        signal="rapid_spend",
                        evidence=f"4+ reviews within {window.seconds//60} min "
                                 f"(total span {overall_span/3600:.1f} h)",
                        reason="Unusual review velocity suggests coordinated bot activity.",
                    ))
                    break

    # Clean-path drain: majority unverified + majority 5-star
    unverified = sum(1 for r in reviews if not r.verified_purchase)
    five_star   = sum(1 for r in reviews if r.rating >= 5.0)
    if total > 0 and unverified / total >= 0.65 and five_star / total >= 0.60:
        findings.append(_Finding(
            id=meta_id, severity="high", signal="clean_path_drain",
            evidence=f"{unverified}/{total} unverified, {five_star}/{total} 5-star",
            reason="All-unverified + all-5-star pattern matches bot purchase drain.",
        ))

    # Mandate abuse language
    corpus = " ".join(r.text for r in reviews).lower()
    mandate_hits = [kw for kw in _MANDATE_KW if kw in corpus]
    if mandate_hits:
        findings.append(_Finding(
            id=meta_id, severity="critical", signal="mandate_scope_violation",
            evidence=f"Mandate abuse keywords: {mandate_hits}",
            reason="Content attempts to override purchase authority limits.",
        ))

    # Price anomaly for high-value categories
    if store.category in ("Electronics", "Health & Household") \
            and store.price < _CHEAP_ELECTRONICS_THRESHOLD:
        findings.append(_Finding(
            id=meta_id, severity="medium", signal="identity_mismatch",
            evidence=f"{store.category} priced at ${store.price:.2f}",
            reason="Suspiciously low price for category may indicate fraudulent listing.",
        ))

    if findings:
        if any(f.severity == "critical" for f in findings):
            risk, decision = "critical", "block"
        elif any(f.severity == "high" for f in findings):
            risk, decision = "high", "needs_manual_review"
        else:
            risk, decision = "medium", "allow_with_constraints"
    else:
        risk, decision = "low", "allow"

    return SubAgentFinding(
        agent="commerce_fraud_bto",
        risk_level=risk,
        decision=decision,
        findings=findings,
    )


def run_fraud_bto_check(store: Store, client=None) -> SubAgentFinding:
    if client:
        return _live_call(
            client, "commerce_fraud_bto",
            _SPECS["commerce_fraud_bto"], store,
        )
    return _mock_fraud_bto(store)

# ---------------------------------------------------------------------------
# Sub-agent 3 — Fraudulent Storefront Lure
# ---------------------------------------------------------------------------

_CATEGORY_PRICE_FLOOR = {
    "Electronics":      15.0,
    "Health & Household": 8.0,
    "Beauty":           5.0,
    "Sports & Outdoors": 10.0,
}
_GENERIC_STORE_KW = ["deals", "outlet", "hub", "shop", "store", "best", "pro", "elite"]


def _mock_storefront(store: Store) -> SubAgentFinding:
    reviews = store.reviews
    total = len(reviews)
    meta_id = f"{store.store_id}-meta"
    findings: List[_Finding] = []

    # Price anomaly
    floor = _CATEGORY_PRICE_FLOOR.get(store.category, 5.0)
    if store.price < floor:
        findings.append(_Finding(
            id=meta_id, severity="high", signal="price_anomaly",
            evidence=f"${store.price:.2f} vs expected floor ${floor:.2f} "
                     f"for {store.category}",
            reason="Price materially below market range without credible explanation.",
        ))

    # Schema-only trust: high five-star rate + low verified rate
    if total > 0:
        five_star_ratio = sum(1 for r in reviews if r.rating >= 5.0) / total
        verified_ratio  = sum(1 for r in reviews if r.verified_purchase) / total
        if five_star_ratio >= 0.65 and verified_ratio < 0.40:
            findings.append(_Finding(
                id=meta_id, severity="high", signal="schema_only_trust",
                evidence=f"{five_star_ratio:.0%} 5-star, "
                         f"only {verified_ratio:.0%} verified",
                reason="Perfect structured ratings with near-zero verified "
                       "purchases indicates fabricated trust signals.",
            ))

    # Identity thin: store name is entirely generic keywords
    name_lower = store.name.lower()
    if all(w in name_lower for w in _GENERIC_STORE_KW[:2]) or \
       sum(1 for w in _GENERIC_STORE_KW if w in name_lower) >= 3:
        findings.append(_Finding(
            id=meta_id, severity="medium", signal="identity_thin",
            evidence=f"Store name '{store.name}' contains generic keywords",
            reason="Merchant lacks distinct identity evidence.",
        ))

    # Human trust gap: repeated templated review text
    if total >= 2:
        norms = [re.sub(r"\W+", " ", r.text.lower()).strip() for r in reviews]
        counts = Counter(norms)
        top_count = counts.most_common(1)[0][1]
        if top_count >= 2 and top_count / total >= 0.15:
            findings.append(_Finding(
                id=reviews[0].review_id, severity="medium",
                signal="human_trust_gap",
                evidence=f"{top_count}/{total} reviews share near-identical text",
                reason="Templated reviews suggest fabricated human trust signals.",
            ))

    if findings:
        if any(f.severity == "high" for f in findings):
            # price_anomaly + schema_only_trust together → block
            signals = {f.signal for f in findings}
            if "price_anomaly" in signals and "schema_only_trust" in signals:
                risk, decision = "critical", "block"
            else:
                risk, decision = "high", "needs_manual_review"
        else:
            risk, decision = "medium", "allow_with_constraints"
    else:
        risk, decision = "low", "allow"

    return SubAgentFinding(
        agent="fraudulent_storefront_lure",
        risk_level=risk,
        decision=decision,
        findings=findings,
    )


def run_storefront_check(store: Store, client=None) -> SubAgentFinding:
    if client:
        return _live_call(
            client, "fraudulent_storefront_lure",
            _SPECS["fraudulent_storefront_lure"], store,
        )
    return _mock_storefront(store)

# ---------------------------------------------------------------------------
# Sub-agent 4 — Logic Hijacking / Returns Fraud
# ---------------------------------------------------------------------------

_REFUND_KW = [
    "instant refund", "immediate refund", "no return needed",
    "keep the item", "no questions asked refund", "auto-refund",
    "refund without", "skip verification",
]
_STATE_OVERRIDE_KW = [
    "mark as received", "mark delivered", "set status",
    "already received", "already delivered", "override tracking",
    "mark package", "set order state",
]
_TOOL_CALL_IN_CONTENT_KW = [
    "call refund(", "trigger settlement", "execute return",
    "settle(", "cancel_order(", "process_refund(",
    "issue_refund(", "initiate_return(",
]
_POLICY_CONFLICT_KW = [
    "no returns", "all sales final", "return not accepted",
    "no refunds whatsoever", "non-refundable",
]


def _mock_returns(store: Store) -> SubAgentFinding:
    corpus = " ".join(r.text for r in store.reviews).lower()
    meta_id = f"{store.store_id}-meta"
    findings: List[_Finding] = []

    refund_hits = [kw for kw in _REFUND_KW if kw in corpus]
    if refund_hits:
        findings.append(_Finding(
            id=meta_id, severity="critical", signal="refund_bypass",
            evidence=f"Refund bypass language: {refund_hits[:2]}",
            reason="Merchant content instructs agent to skip verification steps.",
        ))

    override_hits = [kw for kw in _STATE_OVERRIDE_KW if kw in corpus]
    if override_hits:
        findings.append(_Finding(
            id=meta_id, severity="critical", signal="state_machine_override",
            evidence=f"State override instructions: {override_hits[:2]}",
            reason="Merchant text attempts to directly set order state.",
        ))

    tool_hits = [kw for kw in _TOOL_CALL_IN_CONTENT_KW if kw in corpus]
    if tool_hits:
        findings.append(_Finding(
            id=meta_id, severity="critical", signal="tool_call_in_content",
            evidence=f"Tool call syntax in content: {tool_hits[:2]}",
            reason="Seller content names specific refund/settlement functions.",
        ))

    policy_hits = [kw for kw in _POLICY_CONFLICT_KW if kw in corpus]
    if policy_hits:
        findings.append(_Finding(
            id=meta_id, severity="medium", signal="policy_conflict",
            evidence=f"Restrictive return language: {policy_hits[:2]}",
            reason="Return terms may conflict with platform policy.",
        ))

    if findings:
        if any(f.signal in ("refund_bypass", "state_machine_override",
                            "tool_call_in_content")
               for f in findings):
            risk, decision = "critical", "block"
        else:
            risk, decision = "medium", "allow_with_constraints"
    else:
        risk, decision = "low", "allow"

    return SubAgentFinding(
        agent="logic_hijacking_returns",
        risk_level=risk,
        decision=decision,
        findings=findings,
    )


def run_returns_check(store: Store, client=None) -> SubAgentFinding:
    if client:
        return _live_call(
            client, "logic_hijacking_returns",
            _SPECS["logic_hijacking_returns"], store,
        )
    return _mock_returns(store)

# ---------------------------------------------------------------------------
# Aggregation: 4 SubAgentFindings → ScoutReport
# ---------------------------------------------------------------------------

_RISK_PENALTY = {"low": 5, "medium": 15, "high": 30, "critical": 50}
_SEV_WEIGHT   = {"low": 0.2, "medium": 0.4, "high": 0.7, "critical": 0.9}


def _aggregate(store_id: str, sub_findings: List[SubAgentFinding]) -> ScoutReport:
    decisions   = [f.decision for f in sub_findings]
    risk_levels = [f.risk_level for f in sub_findings]

    # Decision aggregation rules
    if "block" in decisions:
        recommendation = "risky"
    elif decisions.count("needs_manual_review") >= 2:
        recommendation = "suspicious"
    elif "needs_manual_review" in decisions or "allow_with_constraints" in decisions:
        recommendation = "suspicious"
    else:
        recommendation = "safe"

    # Trust score from risk penalties
    penalty = sum(_RISK_PENALTY.get(r, 0) for r in risk_levels)
    trust_score = round(max(0.0, 100.0 - penalty), 1)

    # Override recommendation based on numeric score too
    if trust_score < 40:
        recommendation = "risky"
    elif trust_score < 70:
        recommendation = "suspicious"
    else:
        recommendation = "safe"

    product_score = round(min(100.0, trust_score + 5.0), 1)

    # Confidence: higher when there are critical/high signals
    worst = risk_levels[0] if risk_levels else "low"
    for lvl in ("critical", "high", "medium", "low"):
        if lvl in risk_levels:
            worst = lvl
            break
    confidence = {"critical": 0.92, "high": 0.80, "medium": 0.65, "low": 0.55}[worst]

    # Collect risk_flags and Evidence from all findings
    risk_flags: List[str] = []
    evidence:   List[Evidence] = []
    seen_signals: set = set()

    for sf in sub_findings:
        for f in sf.findings:
            if f.signal not in seen_signals:
                seen_signals.add(f.signal)
                risk_flags.append(f.signal)
            evidence.append(Evidence(
                review_id=f.id if f.id else f"{store_id}-meta",
                signal=f.signal,
                detail=f.reason,
                weight=_SEV_WEIGHT.get(f.severity, 0.5),
            ))

    return ScoutReport(
        seller_id=store_id,
        trust_score=trust_score,
        product_score=product_score,
        risk_flags=risk_flags,
        evidence=evidence,
        recommendation=recommendation,
        confidence=confidence,
    )

# ---------------------------------------------------------------------------
# Master entry point
# ---------------------------------------------------------------------------

@traced
def scout_one(store: Store) -> ScoutReport:
    """
    Run all 4 security sub-agents on ONE seller in isolation.
    Falls back to deterministic heuristics when ANTHROPIC_API_KEY is absent.
    """
    live = bool(os.getenv("ANTHROPIC_API_KEY"))
    client = None

    if live:
        try:
            import anthropic  # type: ignore
            client = anthropic.Anthropic()
        except ImportError:
            live = False

    sub_findings = [
        run_injection_check(store,  client),
        run_fraud_bto_check(store,  client),
        run_storefront_check(store, client),
        run_returns_check(store,    client),
    ]

    return _aggregate(store.store_id, sub_findings)


def scout_all(stores: List[Store]) -> List[ScoutReport]:
    """Convenience wrapper — scout every store in isolation."""
    return [scout_one(s) for s in stores]

# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from data.stores import load_stores

    for store in load_stores():
        r = scout_one(store)
        flags = ", ".join(r.risk_flags) or "none"
        print(
            f"{r.seller_id} {store.name:28s} "
            f"trust={r.trust_score:5.1f} "
            f"rec={r.recommendation:10s} "
            f"conf={r.confidence:.2f} "
            f"flags=[{flags}]"
        )
