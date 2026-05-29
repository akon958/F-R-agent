import json
import unittest

from history_replay import HISTORICAL_SCENARIOS, run_history_replay

# CLAUDE.md 绝对安全边界：历史回放输出中不得出现任何确定性交易词。
_BANNED_WORDS = [
    "买入", "卖出", "加仓", "减仓", "推荐", "强烈买入", "马上操作",
    "抄底", "必涨", "一定赚钱", "保证收益", "预测明天",
]


def _sample_analysis(**overrides):
    base = {
        "total_assets": 1_000_000,
        "cash": 100_000,
        "stock_total": 900_000,
        "stock_results": [
            {"name": "白酒A", "code": "600519", "industry": "食品饮料", "amount": 500_000},
            {"name": "医药C", "code": "600276", "industry": "医药生物", "amount": 400_000},
        ],
    }
    base.update(overrides)
    return base


class HistoryReplayComputation(unittest.TestCase):
    def test_returns_one_scenario_per_table_row(self):
        result = run_history_replay(_sample_analysis())
        self.assertTrue(result["available"])
        self.assertEqual(len(result["scenarios"]), len(HISTORICAL_SCENARIOS))

    def test_loss_matches_equity_times_drawdown(self):
        result = run_history_replay(_sample_analysis())
        s2015 = next(s for s in result["scenarios"] if s["key"] == "crash_2015")
        # 股票 90万 × 47%（沪深300 2015 峰谷回撤）= 42.3万
        self.assertAlmostEqual(s2015["loss"], 423_000, delta=1)
        self.assertAlmostEqual(s2015["loss_ratio"], 0.423, places=3)

    def test_assets_after_equals_total_minus_loss(self):
        result = run_history_replay(_sample_analysis())
        for s in result["scenarios"]:
            self.assertAlmostEqual(s["assets_after"], 1_000_000 - s["loss"], delta=1)

    def test_assets_after_never_negative(self):
        # 全仓无现金时，再深的回撤也不应让账面资产变成负数（max(0, …) 兜底）。
        result = run_history_replay({
            "total_assets": 100_000, "cash": 0, "stock_total": 100_000,
        })
        for s in result["scenarios"]:
            self.assertGreaterEqual(s["assets_after"], 0)

    def test_worst_case_is_deepest_drawdown(self):
        result = run_history_replay(_sample_analysis())
        worst = result["worst_case"]
        # 2008 系数最大（0.60），应为最深
        self.assertEqual(worst["key"], "crisis_2008")
        self.assertGreaterEqual(worst["loss"], max(s["loss"] for s in result["scenarios"]))

    def test_scenarios_keep_table_order(self):
        result = run_history_replay(_sample_analysis())
        keys = [s["key"] for s in result["scenarios"]]
        self.assertEqual(keys, [s["key"] for s in HISTORICAL_SCENARIOS])


class HistoryReplayEdgeCases(unittest.TestCase):
    def test_no_equity_returns_unavailable(self):
        result = run_history_replay({
            "total_assets": 50_000, "cash": 50_000, "stock_total": 0, "stock_results": [],
        })
        self.assertFalse(result["available"])
        self.assertEqual(result["scenarios"], [])

    def test_malformed_input_does_not_raise(self):
        for bad in ({}, {"total_assets": "x"}, {"stock_total": None}):
            result = run_history_replay(bad)
            self.assertIn("available", result)
            self.assertIsInstance(result["scenarios"], list)


class HistoryReplayCompliance(unittest.TestCase):
    def test_output_contains_no_trading_advice_words(self):
        result = run_history_replay(_sample_analysis())
        blob = json.dumps(result, ensure_ascii=False)
        for word in _BANNED_WORDS:
            self.assertNotIn(word, blob, f"历史回放输出出现禁词：{word}")

    def test_disclaimer_states_it_is_not_a_prediction(self):
        result = run_history_replay(_sample_analysis())
        self.assertIn("不是", result["disclaimer"])
        self.assertIn("预测", result["disclaimer"])

    def test_disclaimer_states_it_is_an_approximation(self):
        result = run_history_replay(_sample_analysis())
        self.assertIn("近似", result["disclaimer"])


if __name__ == "__main__":
    unittest.main()
