"""
acp/protocol.py -- the Agentic/Universal Commerce Protocol (ACP/UCP) data layer.

OWNER: Glue (shared)

v3 narrows scope to THE DATA going into and out of ACP. Modeled on the Universal
Commerce Protocol samples (https://github.com/Universal-Commerce-Protocol/samples):
merchants expose a schema.org-style product feed + an A2A "agent card" over the
UCP shopping capability, and buyer agents read those merchant-controlled fields.

THE KEY INSIGHT: every field below is MERCHANT-CONTROLLED. When a buyer agent
ingests the product description, claims, reviews, and even the agent card's free
-text `description`, a dishonest merchant can smuggle fake reviews and prompt
-injection text into the buyer's context. `render_buyer_context()` produces the
exact blob a naive single-context buyer would read -- i.e. the contamination
surface our isolated scouts defend.

TODO(glue): add a real A2A/JSON-RPC client if we want to pull from a live UCP
merchant agent instead of our in-memory marketplace.
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from schema import SellerProfile


class UCPOffer(BaseModel):
    """schema.org Offer (mirrors UCP products.json `offers`)."""

    price: str
    priceCurrency: str = "USD"
    availability: str = "https://schema.org/InStock"
    itemCondition: str = "https://schema.org/NewCondition"


class UCPProduct(BaseModel):
    """schema.org Product as a UCP merchant exposes it to buyer agents."""

    type_: str = Field(default="Product", alias="@type")
    productID: str
    name: str
    brand: str
    offers: UCPOffer
    description: str = ""        # merchant-controlled free text -> injection surface
    category: str = ""
    aggregateRating: float | None = None

    model_config = {"populate_by_name": True}


class MerchantAgentCard(BaseModel):
    """
    A2A agent card the buyer agent discovers (mirrors UCP agent_card.json).
    `description` and `skills` are free text the merchant controls -> a classic
    prompt-injection vector against the buyer/scout agent itself.
    """

    name: str
    organization: str
    description: str = ""
    protocolVersion: str = "0.3.0"
    ucp_capabilities: List[str] = Field(
        default_factory=lambda: [
            "dev.ucp.shopping.checkout",
            "dev.ucp.shopping.fulfillment",
        ]
    )
    skills: List[str] = Field(default_factory=lambda: ["product_search", "checkout"])


def to_ucp_product(seller: SellerProfile) -> UCPProduct:
    """Project a SellerProfile into the UCP product feed a buyer agent would fetch."""
    avg = (
        round(sum(r.rating for r in seller.reviews) / len(seller.reviews), 2)
        if seller.reviews else None
    )
    return UCPProduct(
        productID=seller.seller_id,
        name=seller.product,
        brand=seller.name,
        offers=UCPOffer(price=f"{seller.price:.2f}"),
        description=seller.product,
        category=seller.specs.get("category", "Electronics"),
        aggregateRating=avg,
    )


def to_agent_card(seller: SellerProfile) -> MerchantAgentCard:
    """Project a SellerProfile into its A2A merchant agent card."""
    # Dirty sellers may inject instructions into their own card description.
    injected = [c.text for c in seller.claims if c.kind == "injection"]
    desc = f"{seller.name} merchant agent. {' '.join(injected)}".strip()
    return MerchantAgentCard(name=f"{seller.name} Agent", organization=seller.name, description=desc)


def render_buyer_context(seller: SellerProfile) -> str:
    """
    The raw, merchant-controlled blob a NAIVE single-context buyer ingests for one
    seller: product, claims, and ALL reviews verbatim. This is the contamination
    surface. The baseline buyer reads this for every seller in one window; an
    isolated scout reads it for exactly one seller.
    """
    lines = [
        f"SELLER: {seller.name}  (id={seller.seller_id})",
        f"PRODUCT: {seller.product} — ${seller.price:.2f}",
        f"SPECS: {', '.join(f'{k}={v}' for k, v in seller.specs.items()) or 'n/a'}",
        f"SHIPPING: {seller.shipping} | RETURNS: {seller.return_policy}",
    ]
    if seller.claims:
        lines.append("SELLER CLAIMS:")
        lines += [f"  - {c.text}" for c in seller.claims]
    lines.append(f"REVIEWS ({len(seller.reviews)}):")
    for r in seller.reviews:
        badge = "✓verified" if r.verified_purchase else "unverified"
        lines.append(f"  [{r.rating:.1f}★ {badge}] {r.author}: {r.text}")
    return "\n".join(lines)
