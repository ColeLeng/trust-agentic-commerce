"""
blue/scout_agent.py -- the ISOLATED seller scout (the core of the defense).

OWNER: Blue team

Each scout investigates EXACTLY ONE seller, in its OWN context. It never sees a
competing seller, so one seller's fake-review flood can't pollute another's
evaluation. That isolation is the whole architectural claim.

investigate(seller, context) -> ScoutOutput
  - trust_score  : 100 * (1 - estimated_fake_fraction), via blue/signals.detect
  - product_score: fit of specs/price vs. the buyer's PersonalContext
  - evidence/risk_flags/recommendation/confidence

MOCK-FIRST: heuristics run with no codex CLI. With codex, an LLM second opinion
can nudge borderline trust scores (gated, optional).

TODO(blue): add the analyzer<->scraper "look closer" loop INSIDE the scout: on a
high-suspicion cluster, re-read just those reviews before finalizing.
"""

from __future__ import annotations

from blue.signals import detect
from schema import Evidence, PersonalContext, Recommendation, ScoutOutput, SellerProfile
from tracing import traced


def _product_score(seller: SellerProfile, ctx: PersonalContext) -> float:
    """Crude fit score from price + spec keywords vs. the buyer's priorities."""
    score = 60.0
    if seller.price <= ctx.budget:
        score += 20.0
    else:
        score -= 25.0
    spec_blob = " ".join(seller.specs.values()).lower() + " " + seller.product.lower()
    for pri in ctx.priorities:
        kw = pri.split()[0].lower()
        if kw in spec_blob or (kw in ("noise", "cancelling") and seller.specs.get("anc") == "yes"):
            score += 7.0
    # longer battery is generally better
    bat = seller.specs.get("battery_life", "0h").rstrip("h")
    try:
        score += min(10.0, float(bat) / 4.0)
    except ValueError:
        pass
    return round(max(0.0, min(100.0, score)), 1)


@traced
def investigate(seller: SellerProfile, context: PersonalContext) -> ScoutOutput:
    """Run one isolated scout against one seller."""
    evidence, risk_flags, fake_fraction = detect(seller.reviews)

    # inflated/injection claims are their own (strong) dishonesty signal
    trust_penalty = 0.0
    if any(c.kind == "injection" for c in seller.claims):
        risk_flags.append("prompt_injection_in_claims")
        trust_penalty += 25.0
        evidence.append(Evidence(signal="prompt_injection_in_claims",
            detail="Seller claim tries to instruct the buying agent directly.", weight=0.25))
    if any(c.inflated for c in seller.claims):
        risk_flags.append("inflated_claims")
        trust_penalty += 10.0

    trust_score = round(max(0.0, 100.0 * (1.0 - fake_fraction) - trust_penalty), 1)
    product_score = _product_score(seller, context)

    if trust_score >= 75:
        rec = Recommendation.TRUSTED
    elif trust_score >= 45:
        rec = Recommendation.CAUTION
    else:
        rec = Recommendation.RISKY

    confidence = round(min(1.0, 0.5 + 0.1 * len(set(risk_flags)) + 0.2 * (len(seller.reviews) >= 8)), 2)

    return ScoutOutput(
        seller_id=seller.seller_id,
        trust_score=trust_score,
        product_score=product_score,
        risk_flags=sorted(set(risk_flags)),
        evidence=evidence,
        recommendation=rec,
        confidence=confidence,
        notes=f"Estimated {fake_fraction:.0%} of reviews suspicious across {len(seller.reviews)} reviews.",
    )


if __name__ == "__main__":
    from data.marketplace import build_marketplace
    from red.question_agent import default_question

    ctx = default_question().personal_context
    for s in build_marketplace(0.6):
        out = investigate(s, ctx)
        print(f"{s.seller_id} {s.name:16s} trust={out.trust_score:5.1f} "
              f"product={out.product_score:5.1f} rec={out.recommendation.value} flags={out.risk_flags}")
