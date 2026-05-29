import json
import unittest

from longitudinal_story import build_longitudinal_story

_BANNED_WORDS = [
    "买入", "卖出", "加仓", "减仓", "推荐", "强烈买入", "马上操作",
    "抄底", "必涨", "一定赚钱", "保证收益", "预测明天",
]


def _history(records_count=3, **overrides):
    base = {
        "has_history": True,
        "records_count": records_count,
        "family_focus_changes": [],
        "watch_points": [],
    }
    base.update(overrides)
    return base


def _cash_gap(times=3, first=0.08, latest=0.07, against=True):
    return {"gaps": [{
        "metric": "cash", "task_title": "补足备用金",
        "times_flagged": times, "first_value": first,
        "latest_value": latest, "moved_against_intention": against,
    }]}


class StoryTrigger(unittest.TestCase):
    def test_no_history_unavailable(self):
        d = build_longitudinal_story({"has_history": False, "records_count": 0}, {})
        self.assertFalse(d["available"])

    def test_single_record_unavailable(self):
        d = build_longitudinal_story(_history(records_count=1), _cash_gap())
        self.assertFalse(d["available"])

    def test_no_story_material_unavailable(self):
        # 有历史但没有可讲的故事（gap 只提醒过 1 次、无分歧、无持续风险）
        d = build_longitudinal_story(_history(), _cash_gap(times=1))
        self.assertFalse(d["available"])


class StoryGapMining(unittest.TestCase):
    def test_persistent_cash_gap_becomes_story(self):
        d = build_longitudinal_story(_history(), _cash_gap(times=3, against=True))
        self.assertTrue(d["available"])
        kinds = [s["kind"] for s in d["stories"]]
        self.assertIn("gap_persistent", kinds)
        text = next(s["text"] for s in d["stories"] if s["kind"] == "gap_persistent")
        self.assertIn("3 次", text)
        self.assertIn("8%", text)   # first
        self.assertIn("7%", text)   # latest

    def test_improved_gap_is_positive_story(self):
        d = build_longitudinal_story(
            _history(),
            {"gaps": [{"metric": "concentration", "times_flagged": 2,
                       "first_value": 0.45, "latest_value": 0.30,
                       "moved_against_intention": False}]},
        )
        kinds = [s["kind"] for s in d["stories"]]
        self.assertIn("gap_improved", kinds)
        good = next(s for s in d["stories"] if s["kind"] == "gap_improved")
        self.assertEqual(good["tone"], "good")

    def test_gap_flagged_once_is_not_a_story(self):
        d = build_longitudinal_story(_history(family_focus_changes=["上次家庭分歧已消除"]),
                                     _cash_gap(times=1))
        # gap 不够格，但分歧演变能撑起故事
        self.assertTrue(d["available"])
        self.assertTrue(all(s["kind"] != "gap_persistent" for s in d["stories"]))


# 与 analyzer.analyze_history_changes 实际产出的字符串保持一致（含后缀）
_REAL_FOCUS_CHANGES = {
    "resolved": "上次家庭分歧已消除",
    "new": "本次出现家庭分歧，建议优先沟通",
    "persistent": "家庭分歧仍然存在，建议继续沟通",
}


class StoryOtherSources(unittest.TestCase):
    def test_conflict_resolved_story(self):
        d = build_longitudinal_story(_history(family_focus_changes=[_REAL_FOCUS_CHANGES["resolved"]]), {})
        self.assertTrue(d["available"])
        self.assertEqual(d["stories"][0]["kind"], "conflict_resolved")
        self.assertEqual(d["stories"][0]["tone"], "good")

    def test_all_real_conflict_strings_map_to_a_kind(self):
        expected = {
            "resolved": "conflict_resolved",
            "new": "conflict_new",
            "persistent": "conflict_persistent",
        }
        for key, real_str in _REAL_FOCUS_CHANGES.items():
            d = build_longitudinal_story(_history(family_focus_changes=[real_str]), {})
            self.assertTrue(d["available"], f"未触发：{real_str}")
            self.assertEqual(d["stories"][0]["kind"], expected[key], f"分类错误：{real_str}")
            # 真实串里嵌入 story 后仍不得带禁词
            blob = json.dumps(d, ensure_ascii=False)
            for word in _BANNED_WORDS:
                self.assertNotIn(word, blob, f"真实分歧串 {real_str} 引入禁词：{word}")

    def test_persistent_risk_story(self):
        d = build_longitudinal_story(_history(watch_points=["单只占比偏高", "现金偏少"]), {})
        self.assertTrue(d["available"])
        self.assertIn("risk_persistent", [s["kind"] for s in d["stories"]])

    def test_stories_capped_at_three(self):
        d = build_longitudinal_story(
            _history(family_focus_changes=["家庭分歧仍然存在，建议继续沟通"], watch_points=["风险A", "风险B"]),
            {"gaps": [
                {"metric": "cash", "times_flagged": 3, "first_value": 0.08,
                 "latest_value": 0.07, "moved_against_intention": True},
                {"metric": "concentration", "times_flagged": 3, "first_value": 0.30,
                 "latest_value": 0.45, "moved_against_intention": True},
            ]},
        )
        self.assertLessEqual(len(d["stories"]), 3)


class StoryRobustness(unittest.TestCase):
    def test_malformed_input_does_not_raise(self):
        for bad in (None, {}, {"has_history": True, "records_count": "x"}):
            d = build_longitudinal_story(bad, "not a dict")
            self.assertIn("available", d)


class StoryCompliance(unittest.TestCase):
    def test_output_contains_no_trading_advice_words(self):
        d = build_longitudinal_story(
            _history(family_focus_changes=["家庭分歧仍然存在，建议继续沟通"], watch_points=["单只占比偏高"]),
            _cash_gap(times=3, against=True),
        )
        blob = json.dumps(d, ensure_ascii=False)
        for word in _BANNED_WORDS:
            self.assertNotIn(word, blob, f"纵向洞察输出出现禁词：{word}")


if __name__ == "__main__":
    unittest.main()
