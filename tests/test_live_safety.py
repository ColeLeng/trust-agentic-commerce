"""
Live-mode safety: a failed or over-budget live call must never be reported as a
result. Regressions for two silent fallbacks found before the Oct 1 talk:
  * the baseline swallowed any API error and quietly used the naive scorer, and
  * a failed scout check returned decision="allow", marking the seller safe.

Uses a fake anthropic client -- no network, no spend.

    python -m unittest discover tests
"""

import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cost_meter  # noqa: E402
from baseline import buyer_agent  # noqa: E402
from blue import scout_agent  # noqa: E402
from data.stores import contaminated_stores  # noqa: E402


def _fake_anthropic(create):
    """A stand-in `anthropic` module whose client.messages.create is `create`."""
    client = types.SimpleNamespace(messages=types.SimpleNamespace(create=create))
    return types.SimpleNamespace(Anthropic=lambda: client)


def _reply(text, in_tok=2000, out_tok=10):
    return types.SimpleNamespace(
        content=[types.SimpleNamespace(type="text", text=text)],
        usage=types.SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok),
        stop_reason="end_turn",
    )


def _boom(**_):
    raise RuntimeError("401 invalid x-api-key")


class LiveSafetyTest(unittest.TestCase):
    def setUp(self):
        cost_meter.reset()
        self.stores = contaminated_stores(0.4)
        env = {"ANTHROPIC_API_KEY": "test-key", "MAX_COST_USD": "10"}
        self._env = mock.patch.dict(os.environ, env)
        self._env.start()
        os.environ.pop("LIVE_STRICT", None)

    def tearDown(self):
        self._env.stop()

    def _with_anthropic(self, create):
        return mock.patch.dict(sys.modules, {"anthropic": _fake_anthropic(create)})

    def test_baseline_api_error_aborts_in_strict_mode_instead_of_using_naive_scorer(self):
        os.environ["LIVE_STRICT"] = "1"
        with self._with_anthropic(_boom), self.assertRaises(RuntimeError):
            buyer_agent.choose(self.stores)

    def test_baseline_api_error_outside_strict_mode_is_counted_not_hidden(self):
        with self._with_anthropic(_boom):
            d = buyer_agent.choose(self.stores)
        self.assertEqual(d.mode, "mock")
        self.assertEqual(cost_meter.fallbacks, 1)

    def test_baseline_live_pick_is_labelled_and_metered(self):
        with self._with_anthropic(lambda **_: _reply("s3")):
            d = buyer_agent.choose(self.stores, model="claude-haiku-4-5")
        self.assertEqual((d.chosen_seller_id, d.mode), ("s3", "live:claude-haiku-4-5"))
        self.assertEqual(cost_meter.calls, 1)
        self.assertAlmostEqual(cost_meter.spent_usd(), (2000 * 1 + 10 * 5) / 1e6)

    def test_baseline_reply_without_a_seller_id_is_a_failure_not_a_naive_pick(self):
        os.environ["LIVE_STRICT"] = "1"
        with self._with_anthropic(lambda **_: _reply("I would need more information.")):
            with self.assertRaises(RuntimeError):
                buyer_agent.choose(self.stores)

    def test_seller_id_parse_is_exact(self):
        self.assertIsNone(buyer_agent._parse_seller_id("s10", self.stores))
        self.assertEqual(buyer_agent._parse_seller_id("Best: s5.", self.stores), "s5")

    def test_failed_scout_check_never_reports_allow(self):
        dirty = next(s for s in self.stores if s.is_dirty)
        heuristic = scout_agent._mock_ipi(dirty)
        with self._with_anthropic(_boom):
            client = sys.modules["anthropic"].Anthropic()
            finding = scout_agent.run_injection_check(dirty, client)
        self.assertEqual(finding, heuristic)
        self.assertEqual(cost_meter.fallbacks, 1)

    def test_failed_scout_check_aborts_in_strict_mode(self):
        os.environ["LIVE_STRICT"] = "1"
        with self._with_anthropic(_boom), self.assertRaises(RuntimeError):
            scout_agent.scout_one(self.stores[0])

    def test_budget_cap_stops_before_the_next_call(self):
        os.environ["MAX_COST_USD"] = "0.001"
        calls = []

        def create(**_):
            calls.append(1)
            return _reply("s1", in_tok=10_000, out_tok=0)  # $0.01 on Haiku

        with self._with_anthropic(create):
            buyer_agent.choose(self.stores, model="claude-haiku-4-5")
            with self.assertRaises(cost_meter.BudgetExceeded):
                buyer_agent.choose(self.stores, model="claude-haiku-4-5")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
