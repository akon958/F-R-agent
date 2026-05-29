from __future__ import annotations

"""家庭沟通卡（Family Dialogue）。

定位：当本次体检检测到"家人看法不一致"或"立场与持仓有明显差距"时，
不只是提醒"你们要聊聊"，而是给出一张可以照着说的中立沟通脚本，
帮助家人把分歧聊清楚、把用钱计划对齐。

严格约束（遵守 CLAUDE.md §5.6）：
- 不评判谁对谁错：中立复述各方关注点，不站队。
- 不给交易建议：不出现买入/卖出/加仓/减仓/抄底等字眼，只引导"沟通、对齐、观察"。
- 不预测涨跌。
- 纯确定性模板生成，不调用任何 AI，不增加 DeepSeek 调用次数。

⚠️ 合规警示：本模块产出的结构化文案【不经过】agent.py 的 _safe_ai_text() 中央禁词
过滤器。任何对本文件文案的改动，都必须先跑 `python -m unittest tests.test_family_dialogue`，
确保禁词回归测试通过后再提交。
"""

from typing import Any


_STANCE_LABEL = {
    "conservative": "偏谨慎",
    "aggressive": "偏进取",
    "neutral": "中性",
}

# 每个关注点对应一个中立的待讨论问题（只提问，不给答案，不给操作建议）
_FOCUS_QUESTION = {
    "cash": "我们家未来半年有没有要用钱的地方？现在的现金够不够应急？",
    "concentration": "如果持仓最重的那一只大幅波动，家里能不能接受？各自的底线在哪？",
    "valuation": "我们对这几只的估值判断，分别是基于什么信息？信息够不够充分？",
    "financial": "这几家公司的经营情况我们各自了解多少？要不要等数据更全再下结论？",
    "risk_tolerance": "我们对“能承受多大波动”的理解一致吗？各自最多能接受跌多少？",
    "data_missing": "这次有些数据还不全，我们要不要先不急着下结论，等补齐再一起看？",
    "other": "在这个问题上，我们各自最担心的到底是什么？",
}

_DISCLAIMER = (
    "这张沟通卡只帮助家人把看法聊清楚、把用钱计划对齐，不评判谁对谁错，"
    "也不构成任何投资建议。家里真正要用钱的计划，永远排在第一位。"
)


def _f(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _collect_conflicts(family_disagreement: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(family_disagreement, dict) or not family_disagreement.get("has_conflict"):
        return []
    return [c for c in (family_disagreement.get("conflicts") or []) if isinstance(c, dict)]


def _collect_gaps(intent_action_gap: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(intent_action_gap, dict) or not intent_action_gap.get("has_gap"):
        return []
    gaps = [g for g in (intent_action_gap.get("gaps") or []) if isinstance(g, dict)]
    # 只有"明显差距"才值得专门组织一次家庭沟通，细微差距不强行触发
    notable = [g for g in gaps if g.get("severity") == "notable"]
    return notable


def _build_perspectives(conflicts: list[dict[str, Any]]) -> list[dict[str, str]]:
    """中立复述各方关注点，优先用家人自己写下的原话（evidence）。"""
    perspectives: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for conflict in conflicts:
        focus_label = str(conflict.get("focus_label") or conflict.get("focus") or "这个问题")
        members = conflict.get("members") or {}
        evidence_by_member: dict[str, str] = {}
        for line in (conflict.get("evidence") or []):
            text = str(line or "")
            if "：" in text:
                who, said = text.split("：", 1)
                evidence_by_member.setdefault(who.strip(), said.strip())
        for member, stance in members.items():
            member = str(member or "").strip()
            if not member:
                continue
            key = (member, focus_label)
            if key in seen:
                continue
            seen.add(key)
            stance_label = _STANCE_LABEL.get(str(stance), "")
            voice = evidence_by_member.get(member, "")
            perspectives.append({
                "member": member,
                "focus_label": focus_label,
                "stance_label": stance_label,
                "voice": voice,
            })
    return perspectives


def _build_facts(portfolio_summary: dict[str, Any] | None) -> list[str]:
    """只陈述客观数字，不做任何评价。"""
    if not isinstance(portfolio_summary, dict):
        return []
    facts: list[str] = []
    cash_ratio = _f(portfolio_summary.get("cash_ratio"))
    stock_ratio = _f(portfolio_summary.get("stock_ratio"))
    max_single = _f(portfolio_summary.get("max_single_ratio"))
    if cash_ratio > 0 or stock_ratio > 0:
        facts.append(f"目前现金约占全家 {cash_ratio:.0%}，股票和基金约占 {stock_ratio:.0%}。")
    if max_single > 0:
        facts.append(f"持仓最重的一只，约占全家总资产 {max_single:.0%}。")
    return facts


def _build_questions(
    focuses: list[str],
    reverse_qa: dict[str, Any] | None,
) -> list[str]:
    questions: list[str] = []
    seen: set[str] = set()

    # 半年内可能用钱：把流动性问题放在最前面，最贴近父母的真实顾虑
    money_need = ""
    if isinstance(reverse_qa, dict):
        money_need = str(reverse_qa.get("money_need_6m") or "")
    if money_need == "possible":
        q = _FOCUS_QUESTION["cash"]
        questions.append(q)
        seen.add(q)

    for focus in focuses:
        q = _FOCUS_QUESTION.get(focus, _FOCUS_QUESTION["other"])
        if q not in seen:
            questions.append(q)
            seen.add(q)
        if len(questions) >= 3:
            break
    return questions[:3]


def build_family_dialogue(
    family_disagreement: dict[str, Any] | None,
    intent_action_gap: dict[str, Any] | None = None,
    portfolio_summary: dict[str, Any] | None = None,
    reverse_qa: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """生成家庭沟通卡。仅在有分歧或明显意图-行动差距时返回 available=True。

    永不抛异常：任何异常都降级为 available=False，不影响体检主流程。
    """
    unavailable = {
        "available": False,
        "trigger": "",
        "topics": [],
        "opening": "",
        "perspectives": [],
        "facts": [],
        "questions": [],
        "closing": "",
        "disclaimer": _DISCLAIMER,
    }
    try:
        conflicts = _collect_conflicts(family_disagreement or {})
        gaps = _collect_gaps(intent_action_gap or {})
        if not conflicts and not gaps:
            return unavailable

        if conflicts and gaps:
            trigger = "both"
        elif conflicts:
            trigger = "disagreement"
        else:
            trigger = "gap"

        # ── 涉及的关注点（focus）──────────────────────────────────────
        focuses: list[str] = []
        topic_labels: list[str] = []
        for conflict in conflicts:
            f = str(conflict.get("focus") or "other")
            if f not in focuses:
                focuses.append(f)
                topic_labels.append(str(conflict.get("focus_label") or f))
        for gap in gaps:
            f = str(gap.get("focus") or "other")
            if f not in focuses:
                focuses.append(f)
                topic_labels.append(str(gap.get("focus_label") or f))

        topics_text = "、".join(topic_labels[:3]) or "家庭风险关注点"

        # ── 开场白：中立、不指责 ─────────────────────────────────────
        if trigger == "gap":
            opening = (
                f"这次体检发现，家里有人记下的想法和现在的持仓在「{topics_text}」上有点对不上。"
                "这很常见——先不急着说谁对谁错，我们一起看看是不是哪里需要对齐一下。"
            )
        else:
            opening = (
                f"这次体检发现家里在「{topics_text}」上看法不太一样。这很正常，"
                "也说明大家都在认真为这个家考虑。先不急着争对错，我们一起把它聊清楚。"
            )

        perspectives = _build_perspectives(conflicts)
        # 意图-行动差距也作为"一种声音"补进来，让发起人看到客观对照。
        # 对 (member, focus_label) 去重，避免同一人同一关注点在分歧和差距里重复出现。
        seen_persp = {(p["member"], p["focus_label"]) for p in perspectives}
        for gap in gaps:
            member = str(gap.get("member") or "").strip()
            if not member:
                continue
            focus_label = str(gap.get("focus_label") or "")
            if (member, focus_label) in seen_persp:
                continue
            seen_persp.add((member, focus_label))
            perspectives.append({
                "member": member,
                "focus_label": focus_label,
                "stance_label": str(gap.get("stated") or ""),
                "voice": str(gap.get("gap_desc") or ""),
            })

        facts = _build_facts(portfolio_summary)
        questions = _build_questions(focuses, reverse_qa)

        closing = (
            "聊到大家都清楚彼此在担心什么、并且对“下一步先一起看什么”有个一致的方向，"
            "这次沟通就算有结果了。不用今天就做任何决定，先把想法对齐最重要。"
        )

        return {
            "available": True,
            "trigger": trigger,
            "topics": topic_labels[:3],
            "opening": opening,
            "perspectives": perspectives,
            "facts": facts,
            "questions": questions,
            "closing": closing,
            "disclaimer": _DISCLAIMER,
        }
    except Exception:  # noqa: BLE001 — 沟通卡是增量功能，任何异常都不应影响体检主流程
        return unavailable
