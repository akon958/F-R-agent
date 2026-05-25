import unittest

from analyzer import build_risk_factor_breakdown


def _factor_by_name(result: dict, name: str) -> dict:
    for factor in result["factors"]:
        if factor.get("name") == name:
            return factor
    raise AssertionError(f"Missing factor: {name}")


class RiskFactorBreakdownTests(unittest.TestCase):
    def test_top_tier_factors_dominate_secondary_ones(self) -> None:
        """合并后持仓集中度和财务质量是两大支柱，应明显大于次要因子。"""
        result = build_risk_factor_breakdown(_sample_analysis())

        finance = _factor_by_name(result, "财务质量")
        concentration = _factor_by_name(result, "持仓集中度")
        family = _factor_by_name(result, "家庭分歧")
        heat = _factor_by_name(result, "交易热度")

        # 一级因子（持仓集中度、财务质量）明显大于次要因子（家庭分歧、交易热度）
        self.assertGreater(concentration["weight"], family["weight"])
        self.assertGreater(concentration["weight"], heat["weight"])
        self.assertGreater(finance["weight"], family["weight"])
        self.assertGreater(finance["weight"], heat["weight"])

    def test_weak_company_quality_is_prioritized_ahead_of_family_disagreement(self) -> None:
        result = build_risk_factor_breakdown(
            _sample_analysis(finance_score=62, max_single_ratio=0.30),
            family_disagreement={"has_conflict": True},
            data_confidence={"level_code": "high"},
        )

        top_focus_names = [item["name"] for item in result["top_focus"]]

        self.assertIn("财务质量", top_focus_names)
        self.assertNotEqual(top_focus_names[0], "家庭分歧")


def _sample_analysis(finance_score: float = 78, max_single_ratio: float = 0.25) -> dict:
    return {
        "cash_ratio": 0.25,
        "stock_ratio": 0.75,
        "max_single_ratio": max_single_ratio,
        "industry_concentration": 0.25,
        "module_scores": {
            "公司财务质量": finance_score,
            "交易热度风险": 82,
            "风险承受匹配": 82,
        },
        "stock_results": [
            {"code": "000001", "pe": 12.0, "pb": 1.1},
            {"code": "000002", "pe": 14.0, "pb": 1.3},
        ],
    }


if __name__ == "__main__":
    unittest.main()
