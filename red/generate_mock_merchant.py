#!/usr/bin/env python3
"""
Generate mock Universal Commerce Protocol merchant data for red-team commerce tests.

Example:
  python red/generate_mock_merchant.py \
    --out ./red/mock_merchant_data \
    --merchant-name "Cymbal Retail" \
    --organization "Cymbal Retail" \
    --base-url "http://localhost:10999" \
    --business-id "1234567890" \
    --provider-url "http://merchant.example.com" \
    --product-url-base "https://example.com" \
    --payment-handler-id "example_payment_provider" \
    --payment-handler-name "example.payment.provider" \
    --include-discount

Outputs:
  mock_merchant_data/
    ucp.json
    agent_card.json
    products.json
    temp_files_manifest.json
    images/
      cookies.png
      strawberries.png
      chips.png
      nutribar.png
"""

from __future__ import annotations

import argparse
import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


UCP_VERSION = "2026-01-23"
UCP_OVERVIEW_URI = "https://ucp.dev/2026-01-23/specification/overview?v=2026-01-23"
MANIFEST_FILENAME = "temp_files_manifest.json"

CAPABILITIES: dict[str, dict[str, Any]] = {
    "checkout": {
        "version": UCP_VERSION,
        "spec": "https://ucp.dev/2026-01-23/specification/shopping/checkout",
        "schema": "https://ucp.dev/2026-01-23/schemas/shopping/checkout.json",
    },
    "fulfillment": {
        "version": UCP_VERSION,
        "spec": "https://ucp.dev/2026-01-23/specification/shopping/fulfillment",
        "schema": "https://ucp.dev/2026-01-23/schemas/shopping/fulfillment.json",
        "extends": "dev.ucp.shopping.checkout",
    },
    "discount": {
        "version": UCP_VERSION,
        "spec": "https://ucp.dev/2026-01-23/specification/shopping/discount",
        "schema": "https://ucp.dev/2026-01-23/schemas/shopping/discount.json",
        "extends": "dev.ucp.shopping.checkout",
    },
}

MOCK_PRODUCTS: list[dict[str, str]] = [
    {
        "id": "BISC-001",
        "name": "Chocochip Cookies",
        "sku": "COOKIES-001",
        "image": "cookies.png",
        "brand": "CookieCo",
        "price": "4.99",
        "description": "Freshly baked chocochip cookies.",
        "gtin": "9876543210125",
        "mpn": "CC-SB-001",
        "category": "Groceries > Snacks > Cookies & Biscuits",
    },
    {
        "id": "STRAW-001",
        "name": "Fresh Strawberries",
        "sku": "STRAW-001",
        "image": "strawberries.png",
        "brand": "FarmFresh",
        "price": "4.49",
        "description": "Sweet and juicy fresh strawberries, 1 lb.",
        "gtin": "9876543210127",
        "mpn": "FF-ST-001",
        "category": "Groceries > Fresh Produce > Fruits",
    },
    {
        "id": "CHIPS-001",
        "name": "Classic Potato Chips",
        "sku": "CHIPS-001",
        "image": "chips.png",
        "brand": "SaltySnacks",
        "price": "3.79",
        "description": "Crispy and salty classic potato chips, family size.",
        "gtin": "9876543210128",
        "mpn": "SS-PC-001",
        "category": "Groceries > Snacks > Chips & Crisps",
    },
    {
        "id": "NUTRIBAR-001",
        "name": "Nutri-Bar",
        "sku": "NUTRIBAR-001",
        "image": "nutribar.png",
        "brand": "HealthEats",
        "price": "2.99",
        "description": "A nutritious snack bar packed with nuts and seeds.",
        "gtin": "9876543210135",
        "mpn": "HE-NB-001",
        "category": "Groceries > Health & Nutrition Bars",
    },
]

# A tiny valid 1x1 transparent PNG for deterministic local test fixtures.
PLACEHOLDER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def capability_list(include_discount: bool) -> list[dict[str, Any]]:
    names = ["checkout", "fulfillment"]
    if include_discount:
        names.append("discount")
    return [CAPABILITIES[name] for name in names]


def build_ucp_profile(
    *,
    base_url: str,
    business_id: str,
    include_discount: bool,
    payment_handler_id: str,
    payment_handler_name: str,
) -> dict[str, Any]:
    return {
        "ucp": {
            "version": UCP_VERSION,
            "services": {
                "dev.ucp.shopping": {
                    "version": UCP_VERSION,
                    "spec": "https://ucp.dev/2026-01-23/specification/shopping",
                    "a2a": {
                        "endpoint": f"{base_url}/.well-known/agent-card.json",
                    },
                },
            },
            "capabilities": capability_list(include_discount),
        },
        "payment": {
            "handlers": [
                {
                    "id": payment_handler_id,
                    "name": payment_handler_name,
                    "version": UCP_VERSION,
                    "spec": "https://pay.provider.example/specs/handlers/payments",
                    "config_schema": "https://pay.provider.example/specs/handlers/config.json",
                    "instrument_schemas": [
                        "https://ucp.dev/2026-01-23/schemas/shopping/types/"
                        "card_payment_instrument.json"
                    ],
                    "config": {
                        "business_id": business_id,
                    },
                },
            ],
        },
    }


def build_agent_card(
    *,
    merchant_name: str,
    organization: str,
    base_url: str,
    include_discount: bool,
    provider_url: str,
) -> dict[str, Any]:
    return {
        "capabilities": {
            "extensions": [
                {
                    "description": "UCP Extension",
                    "required": True,
                    "uri": UCP_OVERVIEW_URI,
                    "params": {
                        "capabilities": capability_list(include_discount),
                    },
                },
            ],
            "streaming": False,
        },
        "defaultInputModes": ["text", "text/plain", "application/json"],
        "defaultOutputModes": ["text", "text/plain", "application/json"],
        "description": f"{merchant_name} Merchant Agent",
        "name": f"{merchant_name} Merchant Agent",
        "preferredTransport": "JSONRPC",
        "protocolVersion": "0.3.0",
        "provider": {
            "organization": organization,
            "url": provider_url,
        },
        "skills": [
            {
                "description": "Helps with product search for given user criteria",
                "examples": ["Help me find snacks for a weekend trip"],
                "id": "product_search",
                "name": "Perform product search",
                "tags": ["shopping", "search", "catalog search"],
            },
            {
                "description": "Adds checkout functionality for the agent",
                "examples": [
                    "Add a product to current checkout session",
                    "Change the quantity for a product",
                    "Remove a product from checkout",
                ],
                "id": "checkout",
                "name": "Checkout",
                "tags": ["checkout"],
            },
        ],
        "url": base_url,
        "version": "1.0.0",
    }


def build_products(*, base_url: str, product_url_base: str) -> list[dict[str, Any]]:
    products = []

    for item in MOCK_PRODUCTS:
        product_id = item["id"]
        product_slug = product_id.lower()
        products.append(
            {
                "@type": "Product",
                "productID": product_id,
                "name": item["name"],
                "sku": item["sku"],
                "image": [f"{base_url}/images/{item['image']}"],
                "brand": {
                    "@type": "Brand",
                    "name": item["brand"],
                },
                "offers": {
                    "price": item["price"],
                    "priceCurrency": "USD",
                    "priceSpecification": None,
                    "@type": "Offer",
                    "availability": "https://schema.org/InStock",
                    "itemCondition": "https://schema.org/NewCondition",
                },
                "aggregateRating": None,
                "url": f"{product_url_base.rstrip('/')}/{product_slug}",
                "description": item["description"],
                "gtin": item["gtin"],
                "mpn": item["mpn"],
                "category": item["category"],
            }
        )

    return products


def write_placeholder_images(out_dir: Path) -> list[Path]:
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    image_paths = []
    for item in MOCK_PRODUCTS:
        image_path = images_dir / item["image"]
        image_path.write_bytes(PLACEHOLDER_PNG)
        image_paths.append(image_path)
    return image_paths


def build_manifest(
    *,
    out_dir: Path,
    files: list[Path],
    args: argparse.Namespace,
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "description": "Temporary mock Universal Commerce Protocol merchant files.",
        "output_directory": str(out_dir.resolve()),
        "cleanup_hint": f"rm -rf {out_dir}",
        "inputs": {
            "merchant_name": args.merchant_name,
            "organization": args.organization,
            "base_url": args.base_url,
            "business_id": args.business_id,
            "include_discount": args.include_discount,
            "provider_url": args.provider_url,
            "product_url_base": args.product_url_base,
            "payment_handler_id": args.payment_handler_id,
            "payment_handler_name": args.payment_handler_name,
        },
        "files": [
            {
                "path": str(path),
                "absolute_path": str(path.resolve()),
                "purpose": file_purpose(path),
            }
            for path in files
        ],
    }


def file_purpose(path: Path) -> str:
    if path.name == "ucp.json":
        return "UCP profile with shopping capabilities and payment handler metadata."
    if path.name == "agent_card.json":
        return "A2A agent card advertising the merchant agent and UCP extension."
    if path.name == "products.json":
        return "Mock Schema.org product catalog consumed by merchant-agent tests."
    if path.name == MANIFEST_FILENAME:
        return "Manifest that tracks generated temporary mock merchant files."
    if path.parent.name == "images":
        return "Placeholder product image referenced by products.json."
    return "Generated mock merchant file."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate mock Universal Commerce Protocol merchant data."
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory for generated mock data.",
    )
    parser.add_argument(
        "--merchant-name",
        required=True,
        help="Merchant display name.",
    )
    parser.add_argument(
        "--organization",
        required=True,
        help="Provider organization name.",
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="Base URL where the merchant agent is served.",
    )
    parser.add_argument(
        "--business-id",
        required=True,
        help="Mock payment provider business ID.",
    )
    parser.add_argument(
        "--provider-url",
        required=True,
        help="Provider URL written to the A2A agent card.",
    )
    parser.add_argument(
        "--product-url-base",
        required=True,
        help="Base URL used for product detail pages in products.json.",
    )
    parser.add_argument(
        "--payment-handler-id",
        required=True,
        help="Payment handler ID written to ucp.json.",
    )
    parser.add_argument(
        "--payment-handler-name",
        required=True,
        help="Payment handler name written to ucp.json.",
    )
    parser.add_argument(
        "--include-discount",
        action="store_true",
        help="Also advertise dev.ucp.shopping.discount.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    ucp_path = out_dir / "ucp.json"
    agent_card_path = out_dir / "agent_card.json"
    products_path = out_dir / "products.json"
    manifest_path = out_dir / MANIFEST_FILENAME

    write_json(
        ucp_path,
        build_ucp_profile(
            base_url=args.base_url,
            business_id=args.business_id,
            include_discount=args.include_discount,
            payment_handler_id=args.payment_handler_id,
            payment_handler_name=args.payment_handler_name,
        ),
    )
    write_json(
        agent_card_path,
        build_agent_card(
            merchant_name=args.merchant_name,
            organization=args.organization,
            base_url=args.base_url,
            include_discount=args.include_discount,
            provider_url=args.provider_url,
        ),
    )
    write_json(
        products_path,
        build_products(
            base_url=args.base_url,
            product_url_base=args.product_url_base,
        ),
    )
    image_paths = write_placeholder_images(out_dir)

    generated_files = [ucp_path, agent_card_path, products_path, *image_paths, manifest_path]
    write_json(manifest_path, build_manifest(out_dir=out_dir, files=generated_files, args=args))

    print(f"Wrote mock UCP merchant data to {out_dir.resolve()}")
    for path in generated_files:
        print(f"  - {path}")


if __name__ == "__main__":
    main()
