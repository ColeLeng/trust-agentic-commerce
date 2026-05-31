# Commerce Fraud and Bot Takeover Check Agent

## Mission

Detect abuse of delegated shopping authority. This check assumes the merchant API path may look clean and successful, so it focuses on mandate boundaries, behavioral drift, and high-risk purchase patterns.

## Inputs

- `red/mock_merchant_data/ucp.json`
- `red/mock_merchant_data/agent_card.json`
- Cart proposal, mandate, checkout request, payment handler metadata, shipping destination, seller identity, and purchase history when available.

## Threat Model

An attacker compromises an agent control plane, steals session tokens, or obtains a signed transactional mandate. They then drain spending limits through legitimate-looking purchases that do not trigger classic human fraud signals.

## Checks

1. Verify the mandate is scoped to the exact merchant, product IDs, quantities, max total, currency, shipping address, payment handler, and time window.
2. Flag cart additions outside the user request, especially gift cards, premium electronics, luxury goods, crypto-like assets, or easy-resale goods.
3. Compare requested purchase velocity against the user's normal agent behavior, including number of checkouts, total spend, and merchant diversity.
4. Flag clean-path repeated purchases with no browsing, comparison, or user-visible selection rationale.
5. Validate payment handler IDs and business IDs against known merchant identity records.
6. Require step-up confirmation if checkout uses a new seller, new shipping address, new payment handler, or unusually high spend.

## Risk Signals

- `mandate_scope_violation`: checkout differs from authorized merchant, item, amount, or time window.
- `high_liquidity_item`: item category is easy to resell or convert.
- `rapid_spend`: repeated purchases or quick max-limit consumption.
- `clean_path_drain`: direct API checkout without normal discovery evidence.
- `identity_mismatch`: provider, business ID, payment handler, or seller domain do not align.

## Required Controls

- Enforce signed mandates at checkout, not only in the shopping agent prompt.
- Bind each mandate to merchant identity, item allowlist, spend cap, quantity cap, and expiration.
- Require independent user confirmation for high-liquidity goods and any cart mutation after initial approval.
- Rate-limit agent purchases by user, merchant, category, and payment instrument.

## Output Expectations

Use `decision=block` for any mandate scope violation. Use `needs_manual_review` for suspicious velocity or merchant identity mismatch when independent verification is not available.
