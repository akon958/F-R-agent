import json
import unittest

from family_dialogue import build_family_dialogue

_BANNED_WORDS = [
    "买入", "卖出", "加仓", "减仓", "推荐", "强烈买入", "马上操作",
    "抄底", "必涨", "一定赚钱", "保证收益", "预测明天",
]


def _disagreement(focus="cash", focus_label="现金比例"):
    return {
        "has_conflict": True,
        "conflicts": [{
            "focus": focus,
            "focus_label": focus_label,
            "members": {"妈妈": "conservative", "爸爸": "aggressive"},
            "evidence": ["妈妈：想多留点现金应急", "爸爸：现金太多有点浪费"],
        }],
        "summary": "家庭成员在现金比例问题上存在不同看法。",
    }


def _gap(severity="notable"):
    return {
        "has_gap": True,
        "gaps": [{
            "member": "妈妈",
            "focus": "concentration",
            "focus_label": "持仓集中",
            "stated": "偏谨慎",
            "current_desc": "最大单只 40%",
            "gap_desc": "妈妈对集中度偏谨慎，但最大单只持仓仍占 40%。",
            "severity": severity,
        }],
        "summary": "发现 1 处持仓与家人立场的明显差距。",
    }


_PORTFOLIO = {"cash_ratio": 0.10, "stock_ratio": 0.90, "max_single_ratio": 0.40}


class DialogueTrigger(unittest.TestCase):
    def test_no_conflict_no_gap_is_unavailable(self):
        d = build_family_dialogue({"has_conflict": False}, {"has_gap": False})
        self.assertFalse(d["available"])

    def test_conflict_only_triggers_disagreement(self):
        d = build_family_dialogue(_disagreement(), {"has_gap": False})
        self.assertTrue(d["available"])
        self.assertEqual(d["trigger"], "disagreement")

    def test_gap_only_triggers_gap(self):
        d = build_family_dialogue({"has_conflict": False}, _gap())
        self.assertTrue(d["available"])
        self.assertEqual(d["trigger"], "gap")

    def test_both_triggers_both(self):
        d = build_family_dialogue(_disagreement(), _gap())
        self.assertEqual(d["trigger"], "both")

    def test_minor_gap_alone_does_not_trigger(self):
        d = build_family_dialogue({"has_conflict": False}, _gap(severity="minor"))
        self.assertFalse(d["available"])


class DialogueContent(unittest.TestCase):
    def test_perspectives_use_member_evidence(self):
        d = build_family_dialogue(_disagreement(), {"has_gap": False})
        voices = [p["voice"] for p in d["perspectives"]]
        self.assertIn("想多留点现金应急", voices)
        members = {p["member"] for p in d["perspectives"]}
        self.assertEqual(members, {"妈妈", "爸爸"})

    def test_facts_state_numbers_neutrally(self):
        d = build_family_dialogue(_disagreement(), {"has_gap": False}, portfolio_summary=_PORTFOLIO)
        joined = " ".join(d["facts"])
        self.assertIn("10%", joined)
        self.assertIn("40%", joined)

    def test_money_need_puts_cash_question_first(self):
        d = build_family_dialogue(
            _disagreement(focus="concentration", focus_label="持仓集中"),
            {"has_gap": False},
            reverse_qa={"money_need_6m": "possible"},
        )
        self.assertTrue(d["questions"])
        self.assertIn("用钱", d["questions"][0])

    def test_same_member_same_focus_not_duplicated_across_conflict_and_gap(self):
        # 妈妈在"持仓集中"上既有分歧、又有 notable 差距 → 只应出现一次
        disagreement = {
            "has_conflict": True,
            "conflicts": [{
                "focus": "concentration", "focus_label": "持仓集中",
                "members": {"妈妈": "conservative", "爸爸": "aggressive"},
                "evidence": ["妈妈：不想太集中"],
            }],
        }
        gap = {
            "has_gap": True,
            "gaps": [{
                "member": "妈妈", "focus": "concentration", "focus_label": "持仓集中",
                "stated": "偏谨慎", "current_desc": "最大单只 40%",
                "gap_desc": "妈妈对集中度偏谨慎，但最大单只持仓仍占 40%。",
                "severity": "notable",
            }],
        }
        d = build_family_dialogue(disagreement, gap)
        mom_concentration = [
            p for p in d["perspectives"]
            if p["member"] == "妈妈" and p["focus_label"] == "持仓集中"
        ]
        self.assertEqual(len(mom_concentration), 1)

    def test_questions_capped_at_three(self):
        many = {
            "has_conflict": True,
            "conflicts": [
                {"focus": f, "focus_label": f, "members": {"A": "conservative", "B": "aggressive"}, "evidence": []}
                for f in ("cash", "concentration", "valuation", "financial", "risk_tolerance")
            ],
        }
        d = build_family_dialogue(many, {"has_gap": False})
        self.assertLessEqual(len(d["questions"]), 3)


class DialogueRobustness(unittest.TestCase):
    def test_malformed_input_does_not_raise(self):
        for bad in (None, {}, {"has_conflict": True, "conflicts": "x"}):
            d = build_family_dialogue(bad, None)
            self.assertIn("available", d)


class DialogueCompliance(unittest.TestCase):
    def test_output_contains_no_trading_advice_words(self):
        d = build_family_dialogue(_disagreement(), _gap(), portfolio_summary=_PORTFOLIO,
                                  reverse_qa={"money_need_6m": "possible"})
        blob = json.dumps(d, ensure_ascii=False)
        for word in _BANNED_WORDS:
            self.assertNotIn(word, blob, f"沟通卡输出出现禁词：{word}")

    def test_does_not_judge_who_is_right(self):
        d = build_family_dialogue(_disagreement(), {"has_gap": False})
        self.assertIn("不评判谁对谁错", d["disclaimer"])


if __name__ == "__main__":
    unittest.main()
