from __future__ import annotations

"""纵向洞察（Longitudinal Story）。

定位：把多次体检的数据连起来，讲成 1-3 句父母能共情的"家庭投资小故事"，
而不是再堆一遍干巴巴的数字。重心是那块一直被计算、却从没在页面露面的
intention-action gap（"提醒了好几次、但一直没顾上"），辅以分歧演变与持续风险。

严格约束（遵守 CLAUDE.md）：
- 不预测涨跌、不给交易建议（不出现买入/卖出/加仓/减仓等字眼）。
- 不评判谁对谁错：只客观陈述"提了几次、数字怎么动"，引导沟通与复盘。
- 纯确定性合成，不调用 AI，不增加 DeepSeek 调用次数。
- 只读已算好的 history_analysis / task_review，不重新查库、不改评分。

⚠️ 合规警示：本模块文案【不经过】agent.py 的 _safe_ai_text() 中央禁词过滤器。
任何文案改动都必须先跑 `python -m unittest tests.test_longitudinal_story`。
"""

from typing import Any


_METRIC_LABEL = {
    "cash": "现金比例",
    "concentration": "最大单只占比",
}

_DISCLAIMER = (
    "以上是把几次体检连起来的观察，帮助家人看清自己的长期习惯，"
    "不评判对错，也不构成任何投资建议。"
)


def _f(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _gap_stories(task_review: dict[str, Any]) -> list[dict[str, Any]]:
    """从 compute_intention_action_gap 的输出里挖'说了好几次没动'的故事。"""
    stories: list[dict[str, Any]] = []
    gaps = task_review.get("gaps") if isinstance(task_review, dict) else None
    for gap in (gaps or []):
        if not isinstance(gap, dict):
            continue
        metric = str(gap.get("metric") or "")
        label = _METRIC_LABEL.get(metric)
        if not label:
            continue
        times = int(_f(gap.get("times_flagged")))
        if times < 2:  # 提醒过 2 次以上才算"模式"，否则不够格讲成故事
            continue
        first = _f(gap.get("first_value"))
        latest = _f(gap.get("latest_value"))
        against = bool(gap.get("moved_against_intention"))
        improved = (latest - first) > 0.005 if metric == "cash" else (first - latest) > 0.005

        if against:
            stories.append({
                "kind": "gap_persistent",
                "icon": "🔁",
                "tone": "watch",
                "text": (
                    f"「{label}」这个点，最近的体检里被提醒了 {times} 次。"
                    f"上次约 {first:.0%}、这次约 {latest:.0%}，数字一直没往更稳的方向走——"
                    "这种'提了好几回、却一直没顾上'的情况很常见，值得趁这次一起聊聊、定个小目标。"
                ),
            })
        elif improved:
            stories.append({
                "kind": "gap_improved",
                "icon": "✅",
                "tone": "good",
                "text": (
                    f"之前一直被提醒的「{label}」，上次约 {first:.0%}、这次约 {latest:.0%}，"
                    "家里确实在一点点往更稳的方向调，这是个好信号。"
                ),
            })
    return stories


def _conflict_story(history_analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """家庭分歧的演变：聊过之后消除 / 仍然存在 / 新出现。"""
    for change in (history_analysis.get("family_focus_changes") or []):
        s = str(change or "")
        if "已消除" in s:
            return [{
                "kind": "conflict_resolved", "icon": "🤝", "tone": "good",
                "text": f"{s}——家里的沟通起作用了。这种'聊过之后达成一致'的过程，本身就值得记下来。",
            }]
        if "仍然存在" in s:
            return [{
                "kind": "conflict_persistent", "icon": "💬", "tone": "watch",
                "text": (
                    f"{s}。同一个分歧出现不止一次，不一定是谁固执，"
                    "更可能是还没找到双方都能接受的方案，可以试着换个角度再聊一次。"
                ),
            }]
        if "出现" in s:
            return [{
                "kind": "conflict_new", "icon": "💬", "tone": "watch",
                "text": f"{s}。趁分歧还新鲜，先把各自的担心说清楚，往往比拖着更容易对齐。",
            }]
    return []


def _persistent_risk_story(history_analysis: dict[str, Any]) -> list[dict[str, Any]]:
    watch_points = [str(w) for w in (history_analysis.get("watch_points") or []) if str(w or "").strip()]
    if not watch_points:
        return []
    snippet = "；".join(watch_points[:2])[:50]
    return [{
        "kind": "risk_persistent", "icon": "📌", "tone": "neutral",
        "text": (
            f"有些风险连续两次体检都在：{snippet}。"
            "它不是一时的波动，适合放在心上，隔段时间回看一次趋势。"
        ),
    }]


def build_longitudinal_story(
    history_analysis: dict[str, Any] | None,
    task_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把多次体检连成 1-3 句故事。仅在有 2 次以上历史、且能讲出故事时 available=True。

    永不抛异常：任何异常降级为 available=False，不影响体检主流程。
    """
    unavailable = {
        "available": False,
        "records_count": 0,
        "headline": "",
        "stories": [],
        "disclaimer": _DISCLAIMER,
    }
    try:
        history_analysis = history_analysis or {}
        task_review = task_review or {}
        records_count = int(_f(history_analysis.get("records_count")))
        if not history_analysis.get("has_history") or records_count < 2:
            return unavailable

        stories: list[dict[str, Any]] = []
        # 优先级：言行差距（独家金矿）> 分歧演变 > 持续风险
        stories.extend(_gap_stories(task_review))
        if len(stories) < 3:
            stories.extend(_conflict_story(history_analysis))
        if len(stories) < 2:
            stories.extend(_persistent_risk_story(history_analysis))

        stories = stories[:3]
        if not stories:
            return unavailable

        return {
            "available": True,
            "records_count": records_count,
            "headline": f"把最近 {records_count} 次体检连起来看",
            "stories": stories,
            "disclaimer": _DISCLAIMER,
        }
    except Exception:  # noqa: BLE001 — 增量功能，异常不应影响体检主流程
        return unavailable
