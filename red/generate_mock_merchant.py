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
    --products-file ./merchant_products.json \
    --include-discount

Outputs:
  mock_merchant_data/
    ucp.json
    agent_card.json
    products.json
    temp_files_manifest.json
    images/
      <one placeholder PNG per product image name>
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


REQUIRED_PRODUCT_FIELDS = {
    "id",
    "name",
    "sku",
    "image",
    "brand",
    "price",
    "price_currency",
    "availability",
    "item_condition",
    "description",
    "gtin",
    "mpn",
    "category",
}


def load_product_inputs(products_file: Path) -> list[dict[str, str]]:
    try:
        data = json.loads(products_file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Products file not found: {products_file}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Products file is not valid JSON: {products_file}: {exc}") from exc

    if not isinstance(data, list) or not data:
        raise SystemExit("Products file must contain a non-empty JSON array of product objects.")

    products: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_images: set[str] = set()
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise SystemExit(f"Product #{index} must be a JSON object.")

        missing_fields = sorted(REQUIRED_PRODUCT_FIELDS.difference(item))
        if missing_fields:
            raise SystemExit(
                f"Product #{index} is missing required fields: {', '.join(missing_fields)}"
            )

        product: dict[str, str] = {}
        for field in sorted(REQUIRED_PRODUCT_FIELDS):
            value = item[field]
            if not isinstance(value, str) or not value.strip():
                raise SystemExit(f"Product #{index} field '{field}' must be a non-empty string.")
            product[field] = value.strip()

        product_id_key = product["id"].casefold()
        if product_id_key in seen_ids:
            raise SystemExit(
                "Duplicate product id in products file (case-insensitive): "
                f"{product['id']}"
            )
        seen_ids.add(product_id_key)

        image_path = Path(product["image"])
        if image_path.name != product["image"] or product["image"] in {".", ".."}:
            raise SystemExit(
                f"Product #{index} image must be a filename, not a path: {product['image']}"
            )
        if product["image"] in seen_images:
            raise SystemExit(f"Duplicate product image filename: {product['image']}")
        seen_images.add(product["image"])

        products.append(product)

    return products


def build_products(
    *,
    base_url: str,
    product_url_base: str,
    product_inputs: list[dict[str, str]],
) -> list[dict[str, Any]]:
    products = []

    for item in product_inputs:
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
                    "priceCurrency": item["price_currency"],
                    "priceSpecification": None,
                    "@type": "Offer",
                    "availability": item["availability"],
                    "itemCondition": item["item_condition"],
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


def write_placeholder_images(out_dir: Path, product_inputs: list[dict[str, str]]) -> list[Path]:
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    image_paths = []
    for item in product_inputs:
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
            "products_file": str(args.products_file),
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
        "--products-file",
        type=Path,
        required=True,
        help="JSON file containing merchant-specific product inputs.",
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
    product_inputs = load_product_inputs(args.products_file)

    if out_dir.exists():
        raise SystemExit(
            f"Output directory already exists: {out_dir}. "
            "Choose a unique --out path for each merchant or remove the "
            "existing directory before regenerating it."
        )
    out_dir.mkdir(parents=True, exist_ok=False)

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
            product_inputs=product_inputs,
        ),
    )
    image_paths = write_placeholder_images(out_dir, product_inputs)

    generated_files = [ucp_path, agent_card_path, products_path, *image_paths, manifest_path]
    write_json(manifest_path, build_manifest(out_dir=out_dir, files=generated_files, args=args))

    print(f"Wrote mock UCP merchant data to {out_dir.resolve()}")
    for path in generated_files:
        print(f"  - {path}")


if __name__ == "__main__":
    main()
