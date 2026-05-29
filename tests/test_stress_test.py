import json
import unittest

from stress_test import run_stress_test

# CLAUDE.md 绝对安全边界：压力测试输出中不得出现任何确定性交易词。
_BANNED_WORDS = [
    "买入", "卖出", "加仓", "减仓", "推荐", "强烈买入", "马上操作",
    "抄底", "必涨", "一定赚钱", "保证收益", "预测明天",
]


def _sample_analysis(**overrides):
    base = {
        "total_assets": 1_000_000,
        "cash": 100_000,
        "stock_total": 900_000,
        "cash_ratio": 0.10,
        "max_single_ratio": 0.40,
        "top_industry": "食品饮料",
        "industry_concentration": 700_000 / 900_000,
        "stock_results": [
            {"name": "白酒A", "code": "600519", "industry": "食品饮料", "amount": 400_000},
            {"name": "白酒B", "code": "000858", "industry": "食品饮料", "amount": 300_000},
            {"name": "医药C", "code": "600276", "industry": "医药生物", "amount": 200_000},
        ],
    }
    base.update(overrides)
    return base


class StressTestComputation(unittest.TestCase):
    def test_single_stock_loss_matches_position_times_shock(self):
        result = run_stress_test(_sample_analysis())
        self.assertTrue(result["available"])
        single = next(s for s in result["scenarios"] if s["key"] == "single_stock")
        # 最大单只 40万 × 30% = 12万
        self.assertAlmostEqual(single["loss"], 120_000, delta=1)
        self.assertAlmostEqual(single["loss_ratio"], 0.12, places=3)

    def test_industry_scenario_aggregates_all_holdings_in_industry(self):
        result = run_stress_test(_sample_analysis())
        industry = next(s for s in result["scenarios"] if s["key"] == "industry")
        # 食品饮料 (40万+30万) × 30% = 21万
        self.assertAlmostEqual(industry["loss"], 210_000, delta=1)

    def test_market_scenario_uses_full_equity_value(self):
        result = run_stress_test(_sample_analysis())
        market = next(s for s in result["scenarios"] if s["key"] == "market")
        # 全部股票 90万 × 20% = 18万
        self.assertAlmostEqual(market["loss"], 180_000, delta=1)

    def test_worst_case_is_max_loss(self):
        result = run_stress_test(_sample_analysis())
        worst = result["worst_case"]
        self.assertEqual(worst["key"], "industry")  # 21万 为最大
        self.assertGreaterEqual(worst["loss"], max(s["loss"] for s in result["scenarios"]))


class StressTestEdgeCases(unittest.TestCase):
    def test_no_equity_returns_unavailable(self):
        result = run_stress_test({
            "total_assets": 50_000, "cash": 50_000, "stock_total": 0, "stock_results": [],
        })
        self.assertFalse(result["available"])
        self.assertEqual(result["scenarios"], [])

    def test_single_holding_unknown_industry_skips_industry_scenario(self):
        result = run_stress_test({
            "total_assets": 200_000, "cash": 5_000, "stock_total": 195_000,
            "top_industry": "未知", "industry_concentration": 1.0,
            "stock_results": [
                {"name": "某股", "code": "300001", "industry": "未知", "amount": 195_000},
            ],
        })
        keys = {s["key"] for s in result["scenarios"]}
        self.assertNotIn("industry", keys)  # 行业未知 + 单只，不重复列行业情景
        self.assertIn("single_stock", keys)
        self.assertIn("market", keys)

    def test_malformed_input_does_not_raise(self):
        for bad in ({}, {"total_assets": "x"}, {"stock_results": "not a list"}):
            result = run_stress_test(bad)
            self.assertIn("available", result)
            self.assertIsInstance(result["scenarios"], list)


class StressTestCompliance(unittest.TestCase):
    def test_output_contains_no_trading_advice_words(self):
        result = run_stress_test(_sample_analysis())
        blob = json.dumps(result, ensure_ascii=False)
        for word in _BANNED_WORDS:
            self.assertNotIn(word, blob, f"压力测试输出出现禁词：{word}")

    def test_disclaimer_states_it_is_not_a_prediction(self):
        result = run_stress_test(_sample_analysis())
        self.assertIn("不是", result["disclaimer"])
        self.assertIn("预测", result["disclaimer"])


if __name__ == "__main__":
    unittest.main()
