# Blue Mock Data

`stores.json` is a deterministic fixture for running the blue scout and concierge
agents without waiting on red-team generation.

Run it from the repository root:

```bash
python blue/run_mock_agent.py
```

The fixture includes:

- `blue-safe-01`: ordinary verified reviews.
- `blue-suspicious-01`: duplicate promotional reviews.
- `blue-risky-01`: prompt-injection and inflated review signals.
