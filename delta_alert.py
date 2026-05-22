"""delta_alert.py – 主动预警：比较本次体检与上次记录的关键指标变化。

每次 run_family_risk_agent 结束时调用 compute_delta，结果写入 agent_result["delta_alert"]。
app.py 读取该字段在体检结论顶部展示变化摘要；没有历史时静默跳过。
"""
from __future__ import annotations

from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def compute_delta(
    current_result: dict[str, Any],
    history_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare the current run against the most recent historical record.

    Returns
    -------
    {
        "has_alert":      bool,
        "level":          "warning" | "caution" | "improved" | "stable",
        "changes":        list[str],   # 每条描述一个维度的变化
        "summary":        str,         # 所有变化用 ；连接
        "score_change":   int | None,
        "cash_change":    float | None,
        "position_change": float | None,
    }
    """
    _empty: dict[str, Any] = {
        "has_alert": False,
        "level": "stable",
        "changes": [],
        "summary": "",
        "score_change": None,
        "cash_change": None,
        "position_change": None,
    }

    if not history_records:
        return _empty

    prev = history_records[0]

    # ── 评分 ──────────────────────────────────────────────────────
    cur_score  = _safe_int(current_result.get("risk_score"))
    prev_score = _safe_int(prev.get("risk_score") or prev.get("综合评分"))
    score_change = cur_score - prev_score

    # ── 现金比例 ──────────────────────────────────────────────────
    portfolio = current_result.get("portfolio_summary") or {}
    cur_cash   = _safe_float(portfolio.get("cash_ratio"))
    prev_cash  = _safe_float(prev.get("cash_ratio"))
    cash_change = cur_cash - prev_cash

    # ── 最大持仓占比 ──────────────────────────────────────────────
    cur_max    = _safe_float(portfolio.get("max_single_ratio"))
    prev_max   = _safe_float(prev.get("max_position_ratio"))
    position_change = cur_max - prev_max

    changes: list[str] = []
    level = "stable"

    # 评分变化阈值：≥10 / ≥6 / ≥10
    if score_change <= -10:
        changes.append(f"综合评分下降 {abs(score_change)} 分，风险明显上升")
        level = "warning"
    elif score_change <= -6:
        changes.append(f"综合评分下降 {abs(score_change)} 分")
        level = "caution"
    elif score_change >= 10:
        changes.append(f"综合评分提升 {score_change} 分，整体有所改善")
        level = "improved"

    # 现金比例变化阈值：±6%
    if cash_change < -0.06:
        changes.append(f"现金比例下降 {abs(cash_change) * 100:.0f}%，流动性收紧")
        if level in ("stable", "improved"):
            level = "caution"
    elif cash_change > 0.06:
        changes.append(f"现金比例提升 {cash_change * 100:.0f}%，流动性改善")

    # 集中度变化阈值：±6%
    if position_change > 0.06:
        changes.append(f"最大持仓占比上升 {position_change * 100:.0f}%，集中度加剧")
        if level in ("stable", "improved"):
            level = "caution"
    elif position_change < -0.06:
        changes.append(f"持仓集中度下降 {abs(position_change) * 100:.0f}%")

    if not changes:
        return {**_empty, "summary": "与上次体检相比无明显变化"}

    return {
        "has_alert":       True,
        "level":           level,
        "changes":         changes,
        "summary":         "；".join(changes),
        "score_change":    score_change,
        "cash_change":     cash_change,
        "position_change": position_change,
    }
