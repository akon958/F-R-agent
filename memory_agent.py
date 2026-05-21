from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any


FOCUS_LABELS = {
    "cash": "现金比例",
    "concentration": "持仓集中",
    "valuation": "PE/PB估值",
    "financial": "财务数据",
    "data_missing": "数据缺失",
    "risk_tolerance": "风险承受",
    "other": "其他",
}

STANCE_LABELS = {
    "conservative": "偏谨慎",
    "aggressive": "偏进取",
    "neutral": "中性",
}

_BLOCKED_REPLACEMENTS = {
    "买入": "采取具体交易动作",
    "卖出": "采取具体交易动作",
    "加仓": "扩大持仓",
    "减仓": "调整持仓",
    "推荐": "提示",
    "预测上涨": "判断短期方向",
    "稳赚": "确定收益",
    "保证收益": "确定收益",
}


def _safe_text(value: Any, limit: int = 90) -> str:
    text = str(value or "").strip()
    for bad, repl in _BLOCKED_REPLACEMENTS.items():
        text = text.replace(bad, repl)
    return text[:limit]


def _loads_maybe(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return value
    value = value.strip()
    if not value:
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def _extract_risks_from_record(record: dict[str, Any]) -> list[str]:
    raw = _loads_maybe(record.get("main_risks"))
    if not raw:
        full = _loads_maybe(record.get("full_agent_result"))
        if isinstance(full, dict):
            raw = full.get("main_risks") or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [_safe_text(item) for item in raw if str(item or "").strip()]


def _focus_summary(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for item in comments:
        focus = str(item.get("focus") or item.get("focus_tag") or "other")
        counter[focus] += 1
    return [
        {
            "focus": focus,
            "focus_label": FOCUS_LABELS.get(focus, "其他"),
            "count": count,
        }
        for focus, count in counter.most_common(4)
    ]


def _stance_pattern(comments: list[dict[str, Any]]) -> str:
    by_stance: Counter[str] = Counter()
    by_member: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for item in comments:
        stance = str(item.get("stance") or "neutral")
        member = str(item.get("member") or item.get("author_name") or "家人")
        by_stance[stance] += 1
        by_member[member][stance] += 1

    if not by_stance:
        return ""

    top_stance, _ = by_stance.most_common(1)[0]
    top_label = STANCE_LABELS.get(top_stance, "中性")
    member_parts = []
    for member, stance_counter in list(by_member.items())[:4]:
        stance, _ = stance_counter.most_common(1)[0]
        member_parts.append(f"{member}多为{STANCE_LABELS.get(stance, '中性')}")
    detail = "，".join(member_parts)
    return f"家庭观察整体偏{top_label}。{detail}。" if detail else f"家庭观察整体偏{top_label}。"


def build_agent_memory_summary(
    history_records: list[dict[str, Any]] | None = None,
    family_comments: list[dict[str, Any]] | None = None,
    history_analysis: dict[str, Any] | None = None,
    portfolio_summary: dict[str, Any] | None = None,
    risk_factors: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a compact memory summary from already-loaded records.

    This function does not call Supabase or read local files. It only summarizes
    the memory inputs that agent.py has already loaded for the current run.
    """
    history_records = list(history_records or [])
    family_comments = list(family_comments or [])
    history_analysis = dict(history_analysis or {})
    portfolio_summary = dict(portfolio_summary or {})
    risk_factors = dict(risk_factors or {})

    risk_counter: Counter[str] = Counter()
    for record in history_records:
        for risk in _extract_risks_from_record(record):
            if risk:
                risk_counter[risk] += 1

    recurring_risks = [risk for risk, _ in risk_counter.most_common(3)]
    recurring_focus = _focus_summary(family_comments)
    stance_pattern = _stance_pattern(family_comments)

    watch_points: list[str] = []
    for point in history_analysis.get("watch_points") or []:
        text = _safe_text(point)
        if text and text not in watch_points:
            watch_points.append(text)
    weakest = risk_factors.get("weakest_factor")
    if isinstance(weakest, dict) and weakest.get("name"):
        text = f"继续观察{_safe_text(weakest.get('name'), 24)}。"
        if text not in watch_points:
            watch_points.append(text)
    if portfolio_summary.get("max_position_ratio", 0) and float(portfolio_summary.get("max_position_ratio") or 0) >= 0.2:
        text = "留意单只持仓占比对家庭心态的影响。"
        if text not in watch_points:
            watch_points.append(text)
    watch_points = watch_points[:4]

    has_memory = bool(history_records or family_comments)
    if not has_memory:
        summary = "目前记忆还不多，先以本次体检为主。"
    else:
        parts = []
        if recurring_risks:
            parts.append(f"最近体检里反复出现的是：{'；'.join(recurring_risks[:2])}")
        if recurring_focus:
            parts.append(f"家庭观察更多集中在{recurring_focus[0]['focus_label']}")
        if stance_pattern:
            parts.append(stance_pattern.rstrip("。"))
        summary = "；".join(parts) + "。" if parts else "已有一些历史记录，可继续观察风险变化。"

    return {
        "has_memory": has_memory,
        "records_count": len(history_records),
        "comments_count": len(family_comments),
        "recurring_risks": recurring_risks,
        "recurring_focus": recurring_focus,
        "family_stance_pattern": stance_pattern,
        "trend_summary": _safe_text(history_analysis.get("summary", "")),
        "next_watch_points": watch_points,
        "summary": _safe_text(summary, 180),
    }
