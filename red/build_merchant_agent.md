# Build Mock UCP Merchant Agent Data

Use `red/generate_mock_merchant.py` to generate temporary mock Universal Commerce Protocol (UCP) data for a merchant agent. The script creates an A2A agent card, a UCP profile, a product catalog, placeholder product images, and a manifest that tracks every generated temporary file. All merchant-specific values must be provided explicitly so prompts can gather the right inputs instead of inheriting defaults.

## Quick start

```bash
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
```

The output directory is temporary test data. Do not commit generated output unless a test fixture explicitly requires it.

## Argument guide

| Argument | Required? | What to enter |
| --- | --- | --- |
| `--out` | Yes | Directory where generated files should be written. Prefer a scratch path such as `./red/mock_merchant_data` or `/tmp/mock_merchant_data`. |
| `--merchant-name` | Yes | Customer-facing merchant name displayed in the generated agent card. |
| `--organization` | Yes | Legal or provider organization name for the agent-card `provider.organization` field. |
| `--base-url` | Yes | URL where the merchant agent will be served. This value is used for the agent-card URL, UCP A2A endpoint, and product image URLs. |
| `--business-id` | Yes | Mock payment provider business identifier written to `ucp.json`. Use a non-production ID. |
| `--provider-url` | Yes | Provider URL written to the generated A2A agent card. |
| `--product-url-base` | Yes | Base URL used to construct product detail URLs in `products.json`. |
| `--payment-handler-id` | Yes | Payment handler ID written to the UCP payment handler metadata. |
| `--payment-handler-name` | Yes | Payment handler name written to the UCP payment handler metadata. |
| `--include-discount` | No | Add this flag when the merchant should advertise `dev.ucp.shopping.discount` in addition to checkout and fulfillment. Omit it when the merchant should not advertise discounts. |

## Generated temporary files

For an output directory of `./red/mock_merchant_data`, the script creates:

| File or directory | Purpose | Cleanup action |
| --- | --- | --- |
| `red/mock_merchant_data/ucp.json` | UCP profile containing shopping capabilities and payment handler metadata. | Remove with the output directory. |
| `red/mock_merchant_data/agent_card.json` | A2A agent card advertising the merchant agent and UCP extension. | Remove with the output directory. |
| `red/mock_merchant_data/products.json` | Mock Schema.org product catalog. | Remove with the output directory. |
| `red/mock_merchant_data/images/` | Placeholder PNG images referenced by the catalog. | Remove with the output directory. |
| `red/mock_merchant_data/temp_files_manifest.json` | Machine-readable manifest of the generated temporary files and input arguments. | Remove with the output directory after review. |

## Tracking workflow

1. Choose an `--out` directory for the temporary merchant data.
2. Run `python red/generate_mock_merchant.py` with the merchant-specific arguments.
3. Open `<out>/temp_files_manifest.json` to verify the generated file list, absolute paths, input arguments, and cleanup command.
4. Pass `<out>/ucp.json`, `<out>/agent_card.json`, and `<out>/products.json` to the merchant-agent sample or test harness.
5. Delete the temp directory when finished:

```bash
rm -rf ./red/mock_merchant_data
```

## Example parameter sets

### Local merchant without discounts

```bash
python red/generate_mock_merchant.py \
  --out /tmp/superstore_ucp \
  --merchant-name "SuperStore" \
  --organization "SuperStore Labs" \
  --base-url "http://localhost:10999" \
  --business-id "test-business-001" \
  --provider-url "http://superstore.example.com" \
  --product-url-base "https://superstore.example.com/products" \
  --payment-handler-id "superstore_payment_provider" \
  --payment-handler-name "superstore.payment.provider"
```

### Local merchant with discount capability

```bash
python red/generate_mock_merchant.py \
  --out /tmp/cymbal_ucp \
  --merchant-name "Cymbal Retail" \
  --organization "Cymbal Retail" \
  --base-url "http://localhost:10999" \
  --business-id "test-business-002" \
  --provider-url "http://cymbal.example.com" \
  --product-url-base "https://cymbal.example.com/products" \
  --payment-handler-id "cymbal_payment_provider" \
  --payment-handler-name "cymbal.payment.provider" \
  --include-discount
```
