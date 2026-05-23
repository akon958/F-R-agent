from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import numpy as np


FINANCIAL_COLUMNS = [
    "ROE",
    "净利率",
    "毛利率",
    "营收增长率",
    "净利润增长率",
    "资产负债率",
    "经营现金流/净利润",
]

FINANCIAL_FIELD_ALIASES = {
    "roe": "ROE",
    "net_margin": "净利率",
    "gross_margin": "毛利率",
    "revenue_growth": "营收增长率",
    "profit_growth": "净利润增长率",
    "debt_ratio": "资产负债率",
    "cashflow_profit_ratio": "经营现金流/净利润",
}

STOCK_FIELD_ALIASES = {
    "code": "股票代码",
    "name": "股票名称",
    "industry": "所属行业",
    "price": "最新收盘价",
    "pct_change": "涨跌幅",
    "turnover": "成交额",
    "pe": "市盈率-动态",
    "pb": "市净率",
    "turnover_rate": "换手率",
    "market_cap": "总市值",
    "float_market_cap": "流通市值",
    "volume_ratio": "量比",
    "amplitude": "振幅",
    "in_out_ratio": "内外盘比例",
    "roe": "ROE",
    "net_margin": "净利率",
    "gross_margin": "毛利率",
    "revenue_growth": "营收增长率",
    "profit_growth": "净利润增长率",
    "debt_ratio": "资产负债率",
    "cashflow_profit_ratio": "经营现金流/净利润",
    "data_source": "数据来源",
    "updated_at": "更新时间",
}

FAMILY_FOCUS_LABELS = {
    "cash": "现金比例",
    "concentration": "持仓集中",
    "valuation": "PE/PB估值",
    "financial": "财务数据",
    "data_missing": "数据缺失",
    "risk_tolerance": "风险承受",
    "other": "其他",
}

FAMILY_STANCE_LABELS = {
    "conservative": "偏谨慎",
    "aggressive": "偏进取",
    "neutral": "中性",
}

RISK_TARGETS = {
    "保守": 0.25,
    "稳健": 0.40,
    "平衡": 0.55,
    "进取": 0.70,
    "积极": 0.80,
}

# Intent-action gap thresholds — only flag when gap is unambiguous
_INTENT_GAP_CASH_LOW   = 0.10   # 现金低于 10% → 与"偏谨慎/现金"立场明显矛盾
_INTENT_GAP_CASH_HIGH  = 0.45   # 现金高于 45% → 与"偏进取/现金"立场明显矛盾
_INTENT_GAP_CONC_HIGH  = 0.35   # 单只超 35%   → 与"偏谨慎/集中"立场明显矛盾
_INTENT_GAP_STOCK_HIGH = 0.80   # 仓位超 80%   → 与"偏谨慎/风险承受"立场明显矛盾
_INTENT_GAP_STOCK_LOW  = 0.20   # 仓位低于 20% → 与"偏进取/风险承受"立场明显矛盾
_INTENT_GAP_MAX_RECENT = 10     # 最多处理最近 N 条非中性记录，避免历史噪声


RISK_FACTOR_META = {
    "家庭仓位安全": {
        "plain": "家里的钱放得是否太集中",
        "watch": "现金比例、股票/基金仓位、单只最大占比、行业集中度",
    },
    "公司财务质量": {
        "plain": "持仓公司的底子是否稳",
        "watch": "赚钱能力、利润率、负债压力、现金流质量",
    },
    "交易热度风险": {
        "plain": "短期交易是否太热、波动是否偏大",
        "watch": "换手率、量比、振幅、涨跌幅和成交活跃度",
    },
    "风险承受匹配": {
        "plain": "当前仓位是否匹配家庭能承受的波动",
        "watch": "选择的风险承受能力、股票仓位和单只集中度",
    },
}

RISK_FACTOR_WEIGHTS = {
    "现金缓冲": 14,
    "单只集中": 14,
    "行业集中": 10,
    "估值完整性": 8,
    "财务质量": 26,
    "交易热度": 8,
    "家庭分歧": 4,
    "数据可信度": 10,
    "风险承受匹配": 6,
    "极端集中": 28,
}


def _factor_tone(score: float) -> tuple[str, str, str]:
    if score >= 80:
        return "steady", "稳", "目前压力较小"
    if score >= 60:
        return "watch", "看", "需要继续观察"
    return "tight", "紧", "需要优先看"


def _factor_priority(score: float, weight: float = 10, boost: float = 0) -> tuple[float, str]:
    priority_score = max(0.0, min(100.0, (100 - score) * 0.75 + weight * 0.55 + boost))
    if priority_score >= 55:
        return round(priority_score, 1), "high"
    if priority_score >= 35:
        return round(priority_score, 1), "medium"
    return round(priority_score, 1), "low"


def _make_factor(
    name: str,
    score: float,
    weight: float,
    plain: str,
    watch: str,
    current_status: str = "",
    why: str = "",
    boost: float = 0,
) -> dict[str, Any]:
    score = max(0.0, min(100.0, float(score or 0)))
    tone, tone_label, status = _factor_tone(score)
    priority_score, priority = _factor_priority(score, weight, boost)
    return {
        "name": name,
        "score": round(score, 1),
        "weight": round(float(weight or 0), 1),
        "contribution": round(score * float(weight or 0) / 100, 1) if weight else round(score, 1),
        "tone": tone,
        "tone_label": tone_label,
        "status": current_status or status,
        "plain": plain,
        "watch": watch,
        "why": why or plain,
        "priority_score": priority_score,
        "priority": priority,
    }


def _is_valid_positive_metric(value: Any) -> bool:
    if value in (None, ""):
        return False
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def build_risk_factor_breakdown(
    analysis: dict[str, Any],
    missing_data: dict[str, list[str]] | None = None,
    family_disagreement: dict[str, Any] | None = None,
    data_confidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an agent-style risk-factor workstation.

    The function does not change the original score. It turns the score into
    eight readable factors and lets the Agent choose the 1-2 things worth
    looking at first.
    """
    module_scores = analysis.get("module_scores") or {}
    if not isinstance(module_scores, dict):
        module_scores = {}
    missing_data = missing_data or {}
    family_disagreement = family_disagreement or {}
    data_confidence = data_confidence or {}
    stock_results = list(analysis.get("stock_results") or [])
    holding_count = max(1, len(stock_results))

    cash_ratio = float(analysis.get("cash_ratio", 0) or 0)
    stock_ratio = float(analysis.get("stock_ratio", 0) or 0)
    max_single = float(analysis.get("max_single_ratio", 0) or 0)
    industry_conc = float(analysis.get("industry_concentration", 0) or 0)
    top_industry = str(analysis.get("top_industry") or "")

    if cash_ratio < 0.05:
        cash_score, cash_status = 25, "现金垫很薄"
    elif cash_ratio < 0.10:
        cash_score, cash_status = 45, "备用金偏少"
    elif cash_ratio < 0.20:
        cash_score, cash_status = 68, "现金需要继续观察"
    else:
        cash_score, cash_status = 88, "现金缓冲较充足"

    if max_single >= 0.40:
        single_score, single_status = 25, "单只占比偏高"
    elif max_single >= 0.30:
        single_score, single_status = 52, "单只占比需要关注"
    elif max_single >= 0.20:
        single_score, single_status = 70, "单只占比略集中"
    else:
        single_score, single_status = 90, "单只集中压力较小"

    if industry_conc >= 0.80:
        industry_score, industry_status = 40, f"股票部分集中在{top_industry or '同一行业'}"
    elif industry_conc >= 0.60:
        industry_score, industry_status = 58, "行业集中度偏高"
    elif industry_conc >= 0.40:
        industry_score, industry_status = 72, "行业分布需要观察"
    else:
        industry_score, industry_status = 88, "行业集中压力较小"

    valuation_missing_n = len(missing_data.get("估值数据缺失") or [])
    if not valuation_missing_n:
        for stock in stock_results:
            pe = stock.get("pe") if stock.get("pe") is not None else stock.get("市盈率-动态")
            pb = stock.get("pb") if stock.get("pb") is not None else stock.get("市净率")
            if not _is_valid_positive_metric(pe) or not _is_valid_positive_metric(pb):
                valuation_missing_n += 1
    valuation_score = max(25.0, 100.0 - valuation_missing_n / holding_count * 70.0)
    valuation_status = "估值数据完整" if valuation_missing_n == 0 else f"{valuation_missing_n} 只估值数据暂缺"

    finance_missing_n = len(missing_data.get("财务数据缺失") or [])
    finance_score = float(module_scores.get("公司财务质量", 75) or 75)
    if finance_missing_n:
        finance_score = min(finance_score, max(35.0, 100.0 - finance_missing_n / holding_count * 60.0))

    heat_score = float(module_scores.get("交易热度风险", 75) or 75)
    match_score = float(module_scores.get("风险承受匹配", 75) or 75)
    if stock_ratio >= 0.8:
        match_status = "整体仓位偏高，需要看是否匹配家里承受能力"
    else:
        match_status = "仓位和风险偏好大体匹配" if match_score >= 70 else "仓位和风险偏好需要再确认"

    if family_disagreement.get("has_conflict"):
        family_score, family_status, family_boost = 48, "家人看法不一致，需要先沟通", 6
    else:
        family_score, family_status, family_boost = 88, "暂未发现明显家庭分歧", 0

    conf_code = str(data_confidence.get("level_code") or "")
    if conf_code == "low":
        data_score, data_status, data_boost = 35, "数据可信度偏低", 10
    elif conf_code == "medium":
        data_score, data_status, data_boost = 65, "数据可信度中等", 6
    else:
        data_score, data_status, data_boost = 88, "数据可信度较高", 0

    _is_extreme = max_single >= 0.95 or cash_ratio <= 0.05
    if _is_extreme:
        _extreme_factor = [_make_factor(
            "极端集中", min(cash_score, single_score), RISK_FACTOR_WEIGHTS["极端集中"],
            "资产高度集中在单只标的，且现金缓冲极薄",
            "单只占比是否继续升高，家里是否能承受极端波动",
            f"极端集中：资产几乎全部在一只股票上，没有现金缓冲（单只 {max_single:.0%} / 现金 {cash_ratio:.0%}）",
            f"单只 {max_single:.1%}，现金 {cash_ratio:.1%}。", boost=20,
        )]
    else:
        _extreme_factor = [
            _make_factor(
                "现金缓冲", cash_score, RISK_FACTOR_WEIGHTS["现金缓冲"], "家里短期用钱是否有余地",
                "现金比例、半年内资金用途、家庭备用金是否够用",
                cash_status, f"现金比例约 {cash_ratio:.1%}。", boost=6 if cash_ratio < 0.15 else 0,
            ),
            _make_factor(
                "单只集中", single_score, RISK_FACTOR_WEIGHTS["单只集中"], "钱是否过多集中在一只标的上",
                "最大单只占比是否继续升高，波动时家里是否能接受",
                single_status, f"最大单只占比约 {max_single:.1%}。", boost=8 if max_single >= 0.30 else 0,
            ),
        ]

    factors = [
        *_extreme_factor,
        _make_factor(
            "行业集中", industry_score, RISK_FACTOR_WEIGHTS["行业集中"], "股票部分是否集中在同一行业",
            "行业政策、经营环境和家庭是否理解该行业波动",
            industry_status, f"行业集中度约 {industry_conc:.1%}。", boost=6 if industry_conc >= 0.60 else 0,
        ),
        _make_factor(
            "估值完整性", valuation_score, RISK_FACTOR_WEIGHTS["估值完整性"], "PE/PB 等估值数据是否足够完整",
            "估值数据缺失时，不评价便宜或贵，只提示数据不完整",
            valuation_status, "估值完整性决定这次能不能讨论估值高低。",
            boost=8 if valuation_missing_n else 0,
        ),
        _make_factor(
            "财务质量", finance_score, RISK_FACTOR_WEIGHTS["财务质量"], "持仓公司的经营底子是否稳",
            "ROE、利润率、负债压力、现金流质量",
            "财务数据需要关注" if finance_score < 70 else "财务质量压力较小",
            "财务质量只说明公司经营底子，不代表未来涨跌。",
            boost=16 if (finance_score < 70 or finance_missing_n) else 4,
        ),
        _make_factor(
            "交易热度", heat_score, RISK_FACTOR_WEIGHTS["交易热度"], "短期交易是否太热、波动是否偏大",
            "换手率、量比、振幅、涨跌幅和成交活跃度",
            "短期交易热度需要关注" if heat_score < 70 else "短期交易热度不算突出",
            "交易热度只反映短期活跃程度，不能作为买卖依据。",
            boost=5 if heat_score < 70 else 0,
        ),
        _make_factor(
            "家庭分歧", family_score, RISK_FACTOR_WEIGHTS["家庭分歧"], "家人对同一风险点是否看法不一致",
            "先沟通现金安排、风险承受和观察重点，不评判谁对谁错",
            family_status, "家庭风险有时不只来自市场，也来自理解不一致。",
            boost=family_boost,
        ),
        _make_factor(
            "数据可信度", data_score, RISK_FACTOR_WEIGHTS["数据可信度"], "这次结论的数据基础是否扎实",
            "行情、估值、财务数据是否完整，缓存是否足够新",
            data_status, data_confidence.get("summary") or "数据越完整，结论越有参考价值。",
            boost=data_boost,
        ),
        _make_factor(
            "风险承受匹配", match_score, RISK_FACTOR_WEIGHTS["风险承受匹配"], "当前仓位是否匹配家庭能承受的波动",
            "选择的风险承受能力、股票仓位和单只集中度",
            match_status, "风险偏好不是口号，要和仓位、现金、集中度一起看。",
            boost=4 if match_score < 65 else 0,
        ),
    ]

    factors.sort(key=lambda item: item.get("priority_score", 0), reverse=True)
    top_focus = [item for item in factors if item.get("priority") in ("high", "medium")][:2]
    if not top_focus:
        top_focus = factors[:1]
    weakest = min(factors, key=lambda item: item.get("score", 0)) if factors else None
    names = "、".join(item["name"] for item in top_focus)
    summary = f"这次最该先看：{names}。" if names else ""
    if data_confidence.get("summary"):
        summary += f" {data_confidence.get('summary')}"
    return {
        "factors": factors,
        "top_focus": top_focus,
        "weakest_factor": weakest,
        "summary": summary.strip(),
    }


def _normalise_comment(raw: dict) -> dict[str, str]:
    """Normalize a raw comment dict to the canonical field names used by both detect functions."""
    return {
        "member":  str(raw.get("member")  or raw.get("author_name")  or "").strip(),
        "focus":   (str(raw.get("focus")  or raw.get("focus_tag")    or "other").strip() or "other"),
        "stance":  (str(raw.get("stance") or "neutral").strip()      or "neutral"),
        "content": str(raw.get("content") or raw.get("comment_text") or "").strip(),
    }


def detect_family_disagreement(comments: list[dict]) -> dict:
    """
    检测家庭成员在同一关注点上的风险立场分歧。

    只使用家人主动选择的 stance，不根据内容猜测立场。
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in comments or []:
        if not isinstance(raw, dict):
            continue
        c = _normalise_comment(raw)
        member, focus, stance, content = c["member"], c["focus"], c["stance"], c["content"]
        if not member or stance not in ("conservative", "aggressive"):
            continue
        grouped.setdefault(focus, []).append(
            {"member": member, "focus": focus, "stance": stance, "content": content}
        )

    conflicts: list[dict[str, Any]] = []
    for focus, rows in grouped.items():
        conservative_members = {row["member"] for row in rows if row["stance"] == "conservative"}
        aggressive_members = {row["member"] for row in rows if row["stance"] == "aggressive"}
        if not conservative_members or not aggressive_members:
            continue
        if not conservative_members.isdisjoint(aggressive_members) and len(conservative_members | aggressive_members) < 2:
            continue

        members: dict[str, str] = {}
        evidence: list[str] = []
        seen_evidence: set[tuple[str, str]] = set()
        for row in rows:
            member = row["member"]
            stance = row["stance"]
            if member not in members:
                members[member] = stance
            content = row.get("content") or FAMILY_STANCE_LABELS.get(stance, stance)
            marker = (member, content)
            if marker not in seen_evidence:
                evidence.append(f"{member}：{content}")
                seen_evidence.add(marker)

        conflicts.append(
            {
                "focus": focus,
                "focus_label": FAMILY_FOCUS_LABELS.get(focus, focus),
                "members": members,
                "evidence": evidence,
            }
        )

    if not conflicts:
        return {"has_conflict": False, "conflicts": [], "summary": ""}

    labels = "、".join(conflict["focus_label"] for conflict in conflicts[:3])
    return {
        "has_conflict": True,
        "conflicts": conflicts,
        "summary": f"家庭成员在{labels}问题上存在不同看法。",
    }


def detect_intent_action_gap(
    comments: list[dict],
    portfolio_summary: dict[str, Any],
) -> dict[str, Any]:
    """
    检测家人记录的立场与当前持仓数据之间的差距（意图-行动差距镜）。

    如果某家人说"偏谨慎"但当前持仓数据显示风险偏高，则记录为差距。
    只处理最近 10 条非中性记录，避免历史噪声。
    不修改评分，不给交易建议，只做客观对比提示。
    """
    cash_ratio   = float(portfolio_summary.get("cash_ratio",       0) or 0)
    max_single   = float(portfolio_summary.get("max_single_ratio", 0) or 0)
    stock_ratio  = float(portfolio_summary.get("stock_ratio",      0) or 0)

    # Dedup first, then cap — prevents a single member's repeated rows from
    # monopolising the window before we can check for unique (member, focus, stance).
    seen_keys: set[tuple[str, str, str]] = set()
    recent: list[dict[str, str]] = []
    for r in (comments or []):
        if not isinstance(r, dict):
            continue
        c = _normalise_comment(r)
        if c["stance"] not in ("conservative", "aggressive"):
            continue
        key = (c["member"], c["focus"], c["stance"])
        if key in seen_keys or not c["member"]:
            continue
        seen_keys.add(key)
        recent.append(c)
        if len(recent) >= _INTENT_GAP_MAX_RECENT:
            break

    gaps: list[dict[str, Any]] = []

    for c in recent:
        member  = c["member"]
        focus   = c["focus"]
        stance  = c["stance"]

        focus_label  = FAMILY_FOCUS_LABELS.get(focus,  focus)
        stance_label = FAMILY_STANCE_LABELS.get(stance, stance)
        gap_desc     = ""
        current_desc = ""
        severity     = "minor"

        if stance == "conservative":
            if focus == "cash" and cash_ratio < _INTENT_GAP_CASH_LOW:
                pct = f"{cash_ratio * 100:.0f}%"
                gap_desc     = f"{member}希望保留更多现金，但当前现金比例只有 {pct}。"
                current_desc = f"现金 {pct}"
                severity     = "notable"
            elif focus == "concentration" and max_single > _INTENT_GAP_CONC_HIGH:
                pct = f"{max_single * 100:.0f}%"
                gap_desc     = f"{member}对集中度偏谨慎，但最大单只持仓仍占 {pct}。"
                current_desc = f"最大单只 {pct}"
                severity     = "notable"
            elif focus == "risk_tolerance" and stock_ratio > _INTENT_GAP_STOCK_HIGH:
                pct = f"{stock_ratio * 100:.0f}%"
                gap_desc     = f"{member}风险承受偏保守，但股票/基金仓位高达 {pct}。"
                current_desc = f"仓位 {pct}"
                severity     = "notable"

        elif stance == "aggressive":
            if focus == "cash" and cash_ratio > _INTENT_GAP_CASH_HIGH:
                pct = f"{cash_ratio * 100:.0f}%"
                gap_desc     = f"{member}倾向充分利用资金，但现金比例高达 {pct}。"
                current_desc = f"现金 {pct}"
                severity     = "minor"
            elif focus == "risk_tolerance" and stock_ratio < _INTENT_GAP_STOCK_LOW:
                pct = f"{stock_ratio * 100:.0f}%"
                gap_desc     = f"{member}风险承受偏积极，但股票/基金仓位只有 {pct}。"
                current_desc = f"仓位 {pct}"
                severity     = "minor"

        if gap_desc:
            gaps.append({
                "member":       member,
                "focus":        focus,
                "focus_label":  focus_label,
                "stated":       stance_label,
                "current_desc": current_desc,
                "gap_desc":     gap_desc,
                "severity":     severity,
            })

    if not gaps:
        return {"has_gap": False, "gaps": [], "summary": ""}

    notable_n = sum(1 for g in gaps if g["severity"] == "notable")
    summary = (
        f"发现 {notable_n} 处持仓与家人立场的明显差距。"
        if notable_n
        else f"发现 {len(gaps)} 处意图与持仓的细微差距。"
    )
    return {"has_gap": True, "gaps": gaps, "summary": summary}


def compute_intention_action_gap(
    history_records: list[dict[str, Any]],
    current_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    """比对历史关注项（集中度/现金）与当前指标，返回≤2条言行差距。"""
    if not history_records:
        return []

    cur_cash = float(current_summary.get("cash_ratio") or 0)
    cur_single = float(current_summary.get("max_single_ratio") or 0)
    prev_cash = float(history_records[0].get("cash_ratio") or 0)
    prev_single = float(history_records[0].get("max_position_ratio") or 0)

    _TRACKED = {"cash", "concentration"}
    tracked: dict[str, dict[str, Any]] = {}

    def _get_tasks(rec: dict[str, Any]) -> list[dict[str, Any]]:
        raw = rec.get("watch_tasks")
        if not raw:
            full = rec.get("full_agent_result")
            if isinstance(full, str):
                try:
                    full = json.loads(full)
                except Exception:  # noqa: BLE001
                    full = {}
            if isinstance(full, dict):
                raw = full.get("watch_tasks")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:  # noqa: BLE001
                raw = []
        if not isinstance(raw, list):
            return []
        return [t for t in raw if isinstance(t, dict)]

    for rec in reversed(history_records):  # oldest → newest
        for task in _get_tasks(rec):
            cat = str(task.get("category") or "")
            if cat not in _TRACKED:
                continue
            title = str(task.get("title") or cat)
            if cat not in tracked:
                tracked[cat] = {"times_flagged": 1, "task_title": title}
            else:
                tracked[cat]["times_flagged"] += 1
                tracked[cat]["task_title"] = title

    gaps: list[dict[str, Any]] = []
    if "cash" in tracked:
        info = tracked["cash"]
        gaps.append({
            "metric": "cash",
            "task_title": info["task_title"],
            "times_flagged": info["times_flagged"],
            "first_value": prev_cash,
            "latest_value": cur_cash,
            "moved_against_intention": (prev_cash - cur_cash) > 0.005,
        })
    if "concentration" in tracked:
        info = tracked["concentration"]
        gaps.append({
            "metric": "concentration",
            "task_title": info["task_title"],
            "times_flagged": info["times_flagged"],
            "first_value": prev_single,
            "latest_value": cur_single,
            "moved_against_intention": (cur_single - prev_single) > 0.005,
        })
    return gaps[:2]


def assess_data_confidence(
    analysis: dict[str, Any],
    missing_data: dict[str, list[str]],
) -> dict[str, Any]:
    """
    Compliance Guard：在 Risk Agent 评分后评估本次数据可信度。
    不修改评分，只描述依据的充分程度，供界面渲染置信度标签。
    """
    cap_reasons       = list(analysis.get("cap_reasons") or [])
    missing_market_n  = len(missing_data.get("行情数据缺失")  or [])
    missing_value_n   = len(missing_data.get("估值数据缺失")  or [])
    missing_finance_n = len(missing_data.get("财务数据缺失") or [])
    stale_count = 0
    newest_date = ""
    now = datetime.now()

    for stock in analysis.get("stock_results") or []:
        raw_time = str(stock.get("updated_at") or stock.get("更新时间") or "").strip()
        if not raw_time:
            continue
        try:
            parsed = datetime.fromisoformat(raw_time.replace("Z", "+00:00")[:19])
            if not newest_date or raw_time > newest_date:
                newest_date = raw_time
            if (now - parsed.replace(tzinfo=None)).days >= 7:
                stale_count += 1
        except Exception:  # noqa: BLE001
            continue

    issues: list[str] = []
    if missing_market_n:
        issues.append(f"{missing_market_n} 只行情数据缺失")
    if missing_value_n:
        issues.append(f"{missing_value_n} 只估值数据不完整")
    if missing_finance_n:
        issues.append(f"{missing_finance_n} 只财务数据不完整")
    if stale_count:
        issues.append(f"{stale_count} 只缓存更新时间超过 7 天")
    if cap_reasons:
        issues.append(f"评分因 {len(cap_reasons)} 项原因被保守限制")

    if missing_market_n > 0:
        level, level_code = "低", "low"
        summary = "关键行情数据缺失，结论仅供参考"
    elif missing_finance_n > 0 or missing_value_n > 0 or stale_count > 0 or cap_reasons:
        level, level_code = "中等", "medium"
        if missing_value_n and not missing_finance_n:
            summary = "估值数据不完整，本次不评价估值高低"
        elif stale_count:
            summary = "部分缓存时间偏旧，已保守处理"
        else:
            summary = "部分数据不完整，已保守处理"
    else:
        level, level_code = "高", "high"
        summary = "数据完整，结论可信度较高"

    return {
        "level": level,
        "level_code": level_code,
        "summary": summary,
        "issues": issues,
        "latest_cache_time": newest_date,
    }


def _build_behavior_note(
    score_change: float | None,
    latest_snapshot: dict[str, Any],
    previous_snapshot: dict[str, Any],
) -> str:
    """
    从两次体检快照中提取一句"家庭行为反馈"说明。
    只在变化幅度超过阈值（5pp 或 5 分）时才生成，避免噪声。
    """
    def _delta(key: str) -> float | None:
        a = latest_snapshot.get(key)
        b = previous_snapshot.get(key)
        if a is None or b is None:
            return None
        return round(float(a) - float(b), 4)

    max_change  = _delta("max_position_ratio")
    cash_change = _delta("cash_ratio")
    latest_max  = latest_snapshot.get("max_position_ratio")
    prev_max    = previous_snapshot.get("max_position_ratio")
    latest_cash = latest_snapshot.get("cash_ratio")
    prev_cash   = previous_snapshot.get("cash_ratio")

    notes: list[str] = []

    if max_change is not None and prev_max and latest_max and abs(max_change) >= 0.05:
        verb = "降到" if max_change < 0 else "升至"
        tail = "集中度提示有响应" if max_change < 0 else "集中度有所增加"
        notes.append(
            f"最大单只持仓从 {prev_max * 100:.0f}% {verb} {latest_max * 100:.0f}%，{tail}"
        )

    if cash_change is not None and prev_cash and latest_cash and abs(cash_change) >= 0.05:
        verb = "提升到" if cash_change > 0 else "降至"
        tail = "备用金有改善" if cash_change > 0 else "需留意流动性"
        notes.append(
            f"现金比例从 {prev_cash * 100:.0f}% {verb} {latest_cash * 100:.0f}%，{tail}"
        )

    if not notes and score_change is not None and abs(score_change) >= 5:
        latest_score = latest_snapshot.get("score")
        prev_score   = previous_snapshot.get("score")
        if latest_score is not None and prev_score is not None:
            direction = "上升" if score_change > 0 else "下降"
            notes.append(f"综合评分从 {prev_score:.0f} {direction}到 {latest_score:.0f} 分")

    if not notes:
        return ""
    return "和上次相比：" + "；".join(notes[:2]) + "。"


def analyze_history_changes(history_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare the two most recent check-up records and summarise changes.

    Safe: never raises — all field access is guarded.
    """
    _empty: dict[str, Any] = {
        "has_history": False,
        "records_count": 0,
        "latest_date": "",
        "previous_date": "",
        "score_change": None,
        "risk_factor_changes": [],
        "family_focus_changes": [],
        "watch_points": [],
        "summary": "历史记录还不够，先完成几次体检后，这里会显示风险变化。",
        "behavior_note": "",
    }
    if not history_records:
        return dict(_empty)

    def _parse_ts(row: dict[str, Any]) -> datetime:
        val = str(row.get("created_at") or row.get("分析时间") or "")
        if not val:
            return datetime.min
        try:
            normalized = val.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized)
        except Exception:  # noqa: BLE001
            return datetime.min

    sorted_records = sorted(history_records, key=_parse_ts, reverse=True)
    count = len(sorted_records)
    latest = sorted_records[0]

    if count < 2:
        return {
            **_empty,
            "has_history": True,
            "records_count": count,
            "latest_date": str(latest.get("created_at", "")),
            "summary": "目前只有一次体检记录，暂时无法比较变化。",
        }

    previous = sorted_records[1]

    def _to_num(val: Any) -> float | None:
        try:
            f = float(val or 0)
            return f
        except (TypeError, ValueError):
            return None

    def _load_risks(row: dict[str, Any]) -> list[str]:
        val = row.get("main_risks") or row.get("主要风险") or []
        if isinstance(val, list):
            return [str(r) for r in val]
        try:
            parsed = json.loads(str(val))
            return [str(r) for r in parsed] if isinstance(parsed, list) else []
        except Exception:  # noqa: BLE001
            return []

    def _load_full(row: dict[str, Any]) -> dict[str, Any]:
        val = row.get("full_agent_result")
        if isinstance(val, dict):
            return val
        try:
            parsed = json.loads(str(val or ""))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    latest_score = _to_num(latest.get("risk_score") or latest.get("综合评分"))
    prev_score = _to_num(previous.get("risk_score") or previous.get("综合评分"))
    score_change: float | None = None
    if latest_score is not None and prev_score is not None:
        score_change = round(latest_score - prev_score, 1)

    def _ratio(row: dict[str, Any], key: str, fallback_key: str = "") -> float | None:
        full = _load_full(row)
        portfolio = full.get("portfolio_summary") if isinstance(full.get("portfolio_summary"), dict) else {}
        candidates = [
            row.get(key),
            row.get(fallback_key) if fallback_key else None,
            portfolio.get(key),
            portfolio.get("max_single_ratio") if key == "max_position_ratio" else None,
        ]
        for item in candidates:
            val = _to_num(item)
            if val is not None:
                return val
        return None

    latest_cash = _ratio(latest, "cash_ratio", "现金比例")
    previous_cash = _ratio(previous, "cash_ratio", "现金比例")
    latest_stock = _ratio(latest, "stock_ratio", "股票仓位")
    previous_stock = _ratio(previous, "stock_ratio", "股票仓位")
    latest_max = _ratio(latest, "max_position_ratio")
    previous_max = _ratio(previous, "max_position_ratio")

    def _change(now: float | None, before: float | None) -> float | None:
        if now is None or before is None:
            return None
        return round(now - before, 4)

    latest_risks = _load_risks(latest)
    prev_risks = _load_risks(previous)
    risk_factor_changes: list[dict[str, str]] = []
    for risk in latest_risks:
        if risk not in prev_risks:
            risk_factor_changes.append({"type": "new", "text": risk})
    for risk in prev_risks:
        if risk not in latest_risks:
            risk_factor_changes.append({"type": "resolved", "text": risk})

    latest_full = _load_full(latest)
    prev_full = _load_full(previous)
    family_focus_changes: list[str] = []
    had_conflict = bool((prev_full.get("family_disagreement") or {}).get("has_conflict"))
    has_conflict_now = bool((latest_full.get("family_disagreement") or {}).get("has_conflict"))
    if had_conflict and not has_conflict_now:
        family_focus_changes.append("上次家庭分歧已消除")
    elif not had_conflict and has_conflict_now:
        family_focus_changes.append("本次出现家庭分歧，建议优先沟通")
    elif had_conflict and has_conflict_now:
        family_focus_changes.append("家庭分歧仍然存在，建议继续沟通")

    watch_points = [r for r in latest_risks if r in prev_risks][:5]

    if score_change is not None:
        if score_change > 5:
            trend = f"综合评分上升 {score_change:.0f} 分"
        elif score_change < -5:
            trend = f"综合评分下降 {abs(score_change):.0f} 分，需要关注"
        else:
            trend = f"综合评分基本持平（{score_change:+.1f} 分）"
    else:
        trend = "评分数据不完整"

    new_count = sum(1 for c in risk_factor_changes if c["type"] == "new")
    resolved_count = sum(1 for c in risk_factor_changes if c["type"] == "resolved")
    if new_count:
        risk_note = f"，新出现 {new_count} 个风险点需要关注"
    elif resolved_count:
        risk_note = f"，{resolved_count} 个上次风险点已改善"
    else:
        risk_note = "，风险因子没有明显变化"

    summary = f"和上次体检相比，{trend}{risk_note}。"

    latest_snap: dict[str, Any] = {
        "score": latest_score,
        "risk_level": latest.get("risk_level") or latest.get("风险等级") or "",
        "cash_ratio": latest_cash,
        "stock_ratio": latest_stock,
        "max_position_ratio": latest_max,
    }
    previous_snap: dict[str, Any] = {
        "score": prev_score,
        "risk_level": previous.get("risk_level") or previous.get("风险等级") or "",
        "cash_ratio": previous_cash,
        "stock_ratio": previous_stock,
        "max_position_ratio": previous_max,
    }

    return {
        "has_history": True,
        "records_count": count,
        "latest_date": str(latest.get("created_at", "")),
        "previous_date": str(previous.get("created_at", "")),
        "score_change": score_change,
        "cash_ratio_change": _change(latest_cash, previous_cash),
        "stock_ratio_change": _change(latest_stock, previous_stock),
        "max_position_ratio_change": _change(latest_max, previous_max),
        "latest_snapshot": latest_snap,
        "previous_snapshot": previous_snap,
        "risk_factor_changes": risk_factor_changes,
        "family_focus_changes": family_focus_changes,
        "watch_points": watch_points,
        "summary": summary,
        "behavior_note": _build_behavior_note(score_change, latest_snap, previous_snap),
    }


def clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if np.isnan(value):
            return None
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def stock_value(stock: dict[str, Any], field: str) -> Any:
    value = stock.get(field)
    if value is not None:
        return value
    legacy_name = STOCK_FIELD_ALIASES.get(field)
    if legacy_name:
        return stock.get(legacy_name)
    return None


def weighted_average(items: list[tuple[float, float]], default: float = 0) -> float:
    total_weight = sum(weight for _, weight in items if weight > 0)
    if total_weight <= 0:
        return default
    return sum(score * weight for score, weight in items if weight > 0) / total_weight


def _score_linear(value: float, poor: float, excellent: float, max_pts: float) -> float:
    """在 poor（0 分）到 excellent（满分）之间线性插值，严格限制在 [0, max_pts]。

    解决 clamp(value/bench*max) 的溢出问题：当 value 超过 excellent 时，
    旧写法仍会继续叠加，导致单项得分超过预期满分，破坏各维度权重。
    """
    if excellent == poor:
        return float(max_pts) if value >= excellent else 0.0
    raw = (value - poor) / (excellent - poor) * max_pts
    return float(clamp(raw, 0.0, max_pts))


def financial_quality(stock: dict[str, Any]) -> dict[str, Any]:
    name = stock_value(stock, "name") or stock_value(stock, "code")
    source = stock.get("财务数据来源") or stock_value(stock, "data_source")
    industry = str(stock_value(stock, "industry") or "").strip()

    # ── 行业分类：不同行业财务结构不同，避免用统一标准误判 ──────────────
    # 金融业：负债是存款/资本，毛利率概念不适用
    _is_finance_sector = any(kw in industry for kw in (
        "银行", "金融", "保险", "证券", "信托", "期货",
    ))
    # 基础设施/公用事业：高负债来自资本性投入，由监管机构管理定价，风险结构不同
    _is_infra_sector = any(kw in industry for kw in (
        "公用事业", "电力", "水务", "燃气", "交通运输", "航空", "航运", "港口", "高速公路",
    ))
    # 低毛利行业：毛利率/净利率本身天然偏低，不能和消费/科技行业用同一标准
    _is_low_margin_sector = any(kw in industry for kw in (
        "建筑", "钢铁", "有色金属", "化工", "商贸零售", "纺织", "农林牧渔", "煤炭", "采矿",
    ))

    values = {
        standard: to_float(stock_value(stock, standard) if stock_value(stock, standard) is not None else stock.get(legacy))
        for standard, legacy in FINANCIAL_FIELD_ALIASES.items()
    }
    missing_count = sum(value is None for value in values.values())

    if missing_count >= 5:
        return {
            "score": 35,
            "text": f"{name} 的公司财务数据不足，不能做完整判断。",
            "notes": [f"{name} 缺少较多公司财务数据，不能因为看起来熟悉就给低风险。"],
            "missing": True,
            "source": source,
        }

    roe = values["roe"] or 0
    net_margin = values["net_margin"] or 0
    gross_margin = values["gross_margin"] or 0
    revenue_growth = values["revenue_growth"] or 0
    profit_growth = values["profit_growth"] or 0
    debt_ratio = values["debt_ratio"] if values["debt_ratio"] is not None else 0.7
    cash_profit = values["cashflow_profit_ratio"] if values["cashflow_profit_ratio"] is not None else 0.5

    # ── 财务评分（总满分 100 分）──────────────────────────────────────
    # 每项用 _score_linear 严格限制在 [0, max_pts]，防止高值溢出破坏权重。
    # 基准校准为 A 股实际分位数：超过"优秀"线即得满分，低于"差"线得 0 分。
    score = 0.0

    # ROE（18 分）：0% → 0 分，≥15% → 满分
    # A 股优质公司中位数约 10-12%，15% 以上属于头部，无需设更高门槛
    score += _score_linear(roe, poor=0.0, excellent=0.15, max_pts=18)

    # 净利率（10 分）：按行业基准差异化
    # 低毛利行业：≥8% 满分；其他行业：≥15% 满分
    if _is_low_margin_sector:
        score += _score_linear(net_margin, poor=0.0, excellent=0.08, max_pts=10)
    else:
        score += _score_linear(net_margin, poor=0.0, excellent=0.15, max_pts=10)

    # 营收增长率（14 分）：-10% → 0 分，≥15% → 满分
    # 负增长扣分；0% 增长约得 4.7 分（停滞但非崩溃）
    score += _score_linear(revenue_growth, poor=-0.10, excellent=0.15, max_pts=14)

    # 净利润增长率（14 分）：-10% → 0 分，≥20% → 满分
    score += _score_linear(profit_growth, poor=-0.10, excellent=0.20, max_pts=14)

    if _is_finance_sector:
        # 银行/金融业：高负债是正常业务模式，毛利率概念不适用，给固定中性分
        score += 9   # 资产负债率固定分（不惩罚高杠杆）
        score += 4   # 毛利率固定分（概念不适用）
    elif _is_infra_sector:
        # 公用事业/交通运输：高资本投入导致高负债，设最低 8 分底线
        # 资产负债率（18 分）：≤40% 满分，≥80% 得 0 分，底线 8 分
        score += max(8.0, _score_linear(-debt_ratio, poor=-0.80, excellent=-0.40, max_pts=18))
        # 毛利率（7 分）：0% → 0 分，≥35% → 满分
        score += _score_linear(gross_margin, poor=0.0, excellent=0.35, max_pts=7)
    elif _is_low_margin_sector:
        # 建筑/钢铁/化工/零售：负债标准不变，毛利率基准降为 20%
        score += _score_linear(-debt_ratio, poor=-0.80, excellent=-0.40, max_pts=18)
        score += _score_linear(gross_margin, poor=0.0, excellent=0.20, max_pts=7)
    else:
        # 一般行业：资产负债率 ≤40% 满分，≥80% 得 0 分；毛利率 ≥35% 满分
        score += _score_linear(-debt_ratio, poor=-0.80, excellent=-0.40, max_pts=18)
        score += _score_linear(gross_margin, poor=0.0, excellent=0.35, max_pts=7)

    # 经营现金流/净利润（19 分）：0 → 0 分，≥1.0 → 满分
    # 现金流质量是利润真实性的最重要验证，给最高权重
    score += _score_linear(cash_profit, poor=0.0, excellent=1.0, max_pts=19)

    score -= missing_count * 4
    score = clamp(score)

    notes: list[str] = []
    # 行业特征说明（优先输出，让家人知道为何评分有特殊处理）
    if _is_finance_sector:
        notes.append(f"{name} 属于银行/金融行业，高资产负债率是正常业务特征，毛利率概念也不适用，不按普通企业标准判断。")
    elif _is_infra_sector:
        notes.append(f"{name} 属于公用事业/基础设施行业，高负债来自基础设施资本投入，评分时已适当放宽负债标准。")
    elif _is_low_margin_sector:
        notes.append(f"{name} 属于低毛利行业（建筑/钢铁/零售等），毛利率和净利率比较基准已按行业特点调低，不与白酒/科技行业直接比较。")

    if roe >= 0.15:
        notes.append(f"{name} 的 ROE（公司用自己的钱赚钱的能力）看起来较强。")
    elif roe < 0.08:
        notes.append(f"{name} 的 ROE（公司用自己的钱赚钱的能力）偏弱，需要多留心。")

    if net_margin >= 0.20:
        notes.append(f"{name} 净利率（每卖出100元最终留下多少利润）较高，留利能力好。")
    elif _is_low_margin_sector and net_margin < 0.02:
        notes.append(f"{name} 净利率极低（低于同类行业一般水平），留利空间很小，经营抗压能力有限。")
    elif not _is_low_margin_sector and net_margin < 0.05:
        notes.append(f"{name} 净利率（每卖出100元最终留下多少利润）偏低，留利空间不大。")

    if revenue_growth < 0 or profit_growth < 0:
        notes.append(f"{name} 营收增长率或净利润增长率（公司收入和利润有没有在增加）出现下滑，先别只看短期热闹。")

    # 债务警告：金融业和基础设施业不触发
    if not _is_finance_sector and not _is_infra_sector and debt_ratio > 0.75:
        notes.append(f"{name} 资产负债率（公司借了多少钱相对自己的家底）偏高，环境不好时压力可能更大。")

    if cash_profit < 0.8:
        notes.append(f"{name} 经营现金流/净利润（账面利润有多少真正变成了现金）不够理想。")

    if not notes:
        notes.append(f"{name} 的公司底子没有特别刺眼的问题。")

    if score >= 75:
        text = "公司底子看起来比较稳。"
    elif score >= 55:
        text = "公司底子还需要继续观察。"
    else:
        text = "公司底子偏弱，不能只靠名气或短期上涨来判断。"

    return {"score": score, "text": text, "notes": notes, "missing": missing_count > 0, "source": source}


def trading_heat(stock: dict[str, Any]) -> dict[str, Any]:
    name = stock_value(stock, "name") or stock_value(stock, "code")
    turnover = to_float(stock_value(stock, "turnover_rate"))
    volume_ratio = to_float(stock_value(stock, "volume_ratio"))
    amplitude = to_float(stock_value(stock, "amplitude"))
    change = to_float(stock_value(stock, "pct_change"))
    amount = to_float(stock_value(stock, "turnover"))
    bid_ask_ratio = to_float(stock_value(stock, "in_out_ratio"))

    score = 100.0
    notes: list[str] = []
    overheated = False

    if turnover is None:
        score -= 12
        notes.append(f"{name} 缺少换手率（今天有多少人在买卖这只股票）数据，短期热度判断不完整。")
    elif turnover > 5:
        score -= 28
        overheated = True
        notes.append(f"{name} 换手率（今天有多少人在买卖这只股票）很高，价格容易上上下下。")
    elif turnover > 3:
        score -= 18
        notes.append(f"{name} 换手率（今天有多少人在买卖这只股票）偏高，别被短期气氛带着做决定。")
    elif turnover > 1.5:
        score -= 8

    if volume_ratio is None:
        score -= 8
    elif volume_ratio > 2:
        score -= 20
        overheated = True
        notes.append(f"{name} 量比（今天成交量比平时多多少）明显放大，容易让人冲动。")
    elif volume_ratio > 1.4:
        score -= 9

    if amplitude is None:
        score -= 8
    elif amplitude > 7:
        score -= 22
        overheated = True
        notes.append(f"{name} 振幅（今天股价最高最低相差多少）较大，持有时心理压力会更大。")
    elif amplitude > 4:
        score -= 12

    if change is not None and abs(change) > 5:
        score -= 18
        notes.append(f"{name} 涨跌幅（今天整体涨或跌的幅度）较大，不建议被一天走势带着做决定。")
    elif change is not None and abs(change) > 3:
        score -= 8

    if change is not None and change > 4 and turnover is not None and turnover > 3:
        overheated = True
        notes.append(f"{name} 涨跌幅和换手率同时偏高，不建议被短期热度带着走。")

    if amount is None:
        notes.append(f"{name} 缺少成交额数据，交易热度只能保守判断。")

    if bid_ask_ratio is not None and (bid_ask_ratio > 1.4 or bid_ask_ratio < 0.7):
        score -= 8
        notes.append(f"{name} 内外盘比例（短期主动成交力量对比）不太平衡，只能当作短期情绪参考。")

    score = clamp(score)
    if not notes:
        notes.append(f"{name} 短期交易热度不算夸张。")

    if score >= 75:
        text = "短期交易不算太热。"
    elif score >= 55:
        text = "短期交易有点热，需要慢一点。"
    else:
        text = "短期交易偏热，容易大起大落。"

    return {"score": score, "text": text, "notes": notes, "overheated": overheated}


def position_safety(
    holding_amount: float,
    total_assets: float,
    stock_total: float,
    risk_profile: str,
) -> dict[str, Any]:
    single_ratio = holding_amount / total_assets if total_assets > 0 else 0
    stock_ratio = stock_total / total_assets if total_assets > 0 else 0
    score = 100.0
    notes: list[str] = []

    if single_ratio > 0.40:
        score -= 45
        notes.append("这只标的占家庭资金太高，已经需要红色提醒。")
    elif single_ratio > 0.30:
        score -= 28
        notes.append("这只标的占比偏高，建议不要把家庭资金过度集中到这一只。")
    elif single_ratio > 0.20:
        score -= 15
        notes.append("这只标的占比已经不低，后续需要重点观察集中度。")
    else:
        notes.append("这只标的占家庭资金比例还算可控。")

    if stock_ratio > 0.80:
        score -= 20
        notes.append("股票和基金总仓位很高，家里现金安全垫会变薄。")

    target = RISK_TARGETS.get(risk_profile, 0.55)
    if stock_ratio > target:
        score -= min(25, (stock_ratio - target) * 80)
        notes.append(f"按“{risk_profile}”类型看，当前股票仓位偏高。")

    return {"score": clamp(score), "notes": notes, "single_ratio": single_ratio}


def portfolio_position_score(
    cash: float,
    stock_total: float,
    holdings: list[dict[str, Any]],
    stocks: list[dict[str, Any]],
    risk_profile: str,
) -> dict[str, Any]:
    total_assets = cash + stock_total
    cash_ratio = cash / total_assets if total_assets > 0 else 0
    stock_ratio = stock_total / total_assets if total_assets > 0 else 0
    max_single_ratio = max((item["amount"] / total_assets for item in holdings), default=0) if total_assets > 0 else 0

    score = 100.0
    notes: list[str] = []

    if max_single_ratio > 0.40:
        score -= 35
        notes.append("单只股票或基金超过家庭总资金的 40%，风险偏集中。")
    elif max_single_ratio > 0.30:
        score -= 20
        notes.append("单只股票或基金超过家庭总资金的 30%，需要注意集中风险。")
    elif max_single_ratio > 0.20:
        score -= 10
        notes.append("单只股票或基金超过家庭总资金的 20%，需要持续关注集中度。")

    if stock_ratio > 0.80:
        score -= 25
        notes.append("股票和基金总仓位超过 80%，遇到急用钱会比较被动。")
    elif stock_ratio > 0.65:
        score -= 12
        notes.append("股票和基金仓位偏高，建议保留更厚的现金垫。")

    if cash_ratio < 0.05:
        score -= 25
        notes.append("现金比例低于 5%，家庭备用金明显偏少。")
    elif cash_ratio < 0.10:
        score -= 16
        notes.append("现金比例低于 10%，建议先补足备用金。")

    industry_amounts: dict[str, float] = {}
    code_to_industry = {stock_value(stock, "code"): stock_value(stock, "industry") or "未知" for stock in stocks}
    for holding in holdings:
        industry = code_to_industry.get(holding["code"], "未知")
        industry_amounts[industry] = industry_amounts.get(industry, 0) + holding["amount"]

    top_industry = "无"
    industry_concentration = 0.0
    if stock_total > 0 and industry_amounts:
        top_industry, top_amount = max(industry_amounts.items(), key=lambda item: item[1])
        industry_concentration = top_amount / stock_total
        if industry_concentration > 0.80 and top_industry != "未知":
            score -= 22
            notes.append(f"股票/基金部分高度集中在{top_industry}，行业风险需要放在前面看。")
        elif industry_concentration > 0.60 and top_industry != "未知":
            score -= 16
            notes.append(f"持仓较集中在{top_industry}，行业风险需要留心。")
        elif industry_concentration > 0.45 and top_industry != "未知":
            score -= 8
            notes.append(f"股票/基金部分有一定{top_industry}集中度，建议持续观察行业风险。")
        elif industry_concentration > 0.60:
            score -= 10
            notes.append("部分持仓行业信息不完整，行业集中度只能保守判断。")

    if not notes:
        notes.append("家庭仓位没有明显刺眼的问题。")

    return {
        "score": clamp(score),
        "notes": notes,
        "cash_ratio": cash_ratio,
        "stock_ratio": stock_ratio,
        "max_single_ratio": max_single_ratio,
        "top_industry": top_industry,
        "industry_concentration": industry_concentration,
    }


def risk_match_score(risk_profile: str, stock_ratio: float, max_single_ratio: float) -> dict[str, Any]:
    target = RISK_TARGETS.get(risk_profile, 0.55)
    score = 100.0
    notes: list[str] = []

    if stock_ratio > target:
        score -= min(35, (stock_ratio - target) * 100)
        notes.append(f"你选择的是“{risk_profile}”，当前股票和基金仓位偏高。")

    if risk_profile == "保守" and max_single_ratio > 0.20:
        score -= 25
        notes.append("保守型家庭更需要避免单只标的占比过高。")
    elif risk_profile == "保守" and max_single_ratio > 0.15:
        score -= 15
        notes.append("保守型家庭需要更早关注单只标的占比。")
    elif risk_profile == "稳健" and max_single_ratio > 0.25:
        score -= 20
        notes.append("稳健型家庭不适合把太多钱压在单只标的上。")
    elif risk_profile == "稳健" and max_single_ratio > 0.20:
        score -= 10
        notes.append("稳健型家庭需要更早关注单只标的占比。")
    elif risk_profile == "平衡" and max_single_ratio > 0.35:
        score -= 15
        notes.append("平衡型家庭也要避免单只标的太集中。")
    elif risk_profile == "进取" and max_single_ratio > 0.42:
        score -= 12
        notes.append("进取型家庭也要留意单只标的集中风险。")
    elif risk_profile == "积极" and max_single_ratio > 0.48:
        score -= 12
        notes.append("即使是积极型，也不建议满仓或过度集中。")

    if not notes:
        notes.append("当前仓位和你选择的风险承受能力大体匹配。")

    return {"score": clamp(score), "notes": notes}


def _level_from_score(score: float) -> tuple[str, str, str]:
    if score >= 80:
        return "绿色", "green", "风险较低"
    if score >= 60:
        return "黄色", "yellow", "需要注意"
    return "红色", "red", "风险偏高"


def _family_advice(level: str) -> str:
    if level == "绿色":
        return "当前组合整体风险相对可控，但仍不建议因为短期上涨而频繁调整。建议继续关注公司经营情况，并保留足够现金。"
    if level == "黄色":
        return "当前组合需要注意，主要问题可能是股票仓位较高、持仓较集中，或部分持仓交易较热。建议优先保持现金储备，并避免把家庭资金过度集中在少数标的上。"
    return "当前组合风险偏高，先不要被短期热度带着做决定。建议先把单只占比、备用金和家庭用钱计划聊清楚。"


def analyze_portfolio(
    cash: float,
    risk_profile: str,
    holdings: list[dict[str, Any]],
    stocks: list[dict[str, Any]],
) -> dict[str, Any]:
    stock_by_code = {stock_value(stock, "code"): stock for stock in stocks}
    stock_total = sum(item["amount"] for item in holdings)
    total_assets = cash + stock_total

    stock_results = []
    finance_scores: list[tuple[float, float]] = []
    heat_scores: list[tuple[float, float]] = []
    severe_missing = False
    finance_missing = False
    overheated = False

    position_summary = portfolio_position_score(cash, stock_total, holdings, stocks, risk_profile)

    for holding in holdings:
        stock = stock_by_code.get(holding["code"], {})
        finance = financial_quality(stock)
        heat = trading_heat(stock)
        pos = position_safety(holding["amount"], total_assets, stock_total, risk_profile)

        finance_scores.append((finance["score"], holding["amount"]))
        heat_scores.append((heat["score"], holding["amount"]))

        severe_missing = severe_missing or stock_value(stock, "data_source") == "数据缺失"
        finance_missing = finance_missing or finance["missing"]
        overheated = overheated or heat["overheated"] or heat["score"] < 55

        single_ratio = pos["single_ratio"]
        if single_ratio > 0.40:
            item_level = ("红色", "red")
        elif finance["score"] < 55 or heat["score"] < 55 or single_ratio > 0.30:
            item_level = ("黄色", "yellow")
        else:
            item_level = ("绿色", "green")

        stock_results.append(
            {
                "code": holding["code"],
                "name": stock_value(stock, "name") or holding["code"],
                "industry": stock_value(stock, "industry") or "未知",
                "amount": holding["amount"],
                "single_ratio": single_ratio,
                "data_source": stock_value(stock, "data_source") or "数据缺失",
                "market_source": stock.get("市场数据来源", stock_value(stock, "data_source") or "数据缺失"),
                "finance_source": stock.get("财务数据来源", stock_value(stock, "data_source") or "数据缺失"),
                "price": stock_value(stock, "price"),
                "pct_change": stock_value(stock, "pct_change"),
                "turnover": stock_value(stock, "turnover"),
                "pe": stock_value(stock, "pe"),
                "pb": stock_value(stock, "pb"),
                "turnover_rate": stock_value(stock, "turnover_rate"),
                "market_cap": stock_value(stock, "market_cap"),
                "float_market_cap": stock_value(stock, "float_market_cap"),
                "volume_ratio": stock_value(stock, "volume_ratio"),
                "amplitude": stock_value(stock, "amplitude"),
                "in_out_ratio": stock_value(stock, "in_out_ratio"),
                "roe": stock_value(stock, "roe"),
                "net_margin": stock_value(stock, "net_margin"),
                "gross_margin": stock_value(stock, "gross_margin"),
                "revenue_growth": stock_value(stock, "revenue_growth"),
                "profit_growth": stock_value(stock, "profit_growth"),
                "debt_ratio": stock_value(stock, "debt_ratio"),
                "cashflow_profit_ratio": stock_value(stock, "cashflow_profit_ratio"),
                "updated_at": stock_value(stock, "updated_at"),
                "level": item_level[0],
                "color": item_level[1],
                "financial_score": finance["score"],
                "financial_text": finance["text"],
                "financial_notes": finance["notes"],
                "heat_score": heat["score"],
                "heat_text": heat["text"],
                "heat_notes": heat["notes"],
                "position_score": pos["score"],
                "position_notes": pos["notes"],
            }
        )

    financial_score = weighted_average(finance_scores, default=35)
    heat_score = weighted_average(heat_scores, default=35)
    position_score = position_summary["score"]
    match = risk_match_score(risk_profile, position_summary["stock_ratio"], position_summary["max_single_ratio"])
    match_score = match["score"]

    # 家庭工具更看重账户安全，而不是把公司质量当成单只股票评分。
    total_score = financial_score * 0.30 + heat_score * 0.20 + position_score * 0.35 + match_score * 0.15

    cap_reasons: list[str] = []
    score_cap = 100.0
    if severe_missing:
        score_cap = min(score_cap, 59)
        cap_reasons.append("有持仓缺少真实数据和本地缓存，不能做完整判断。")
    elif finance_missing:
        score_cap = min(score_cap, 79)
        cap_reasons.append("部分公司财务数据不完整，最高只能给黄色。")

    if position_summary["max_single_ratio"] > 0.40:
        score_cap = min(score_cap, 79)
        cap_reasons.append("单只持仓超过 40%，即使公司不错也不能给绿色。")

    if position_summary["max_single_ratio"] >= 0.95:
        score_cap = min(score_cap, 15)
        cap_reasons.append("单只持仓超过 95%，组合几乎等同于单只股票，综合评分上限 15。")
    elif position_summary["max_single_ratio"] >= 0.80:
        score_cap = min(score_cap, 25)
        cap_reasons.append("单只持仓超过 80%，集中度极高，综合评分上限 25。")

    if position_summary["cash_ratio"] < 0.05:
        score_cap = min(score_cap, 79)
        cap_reasons.append("现金比例低于 5%，不能给绿色。")

    if overheated:
        score_cap = min(score_cap, 79)
        cap_reasons.append("部分持仓短期交易明显偏热，不能给绿色。")

    if risk_profile == "保守" and position_summary["max_single_ratio"] > 0.20:
        score_cap = min(score_cap, 79)
        cap_reasons.append("保守型家庭的单只持仓占比偏高，不能给绿色。")
    elif position_summary["max_single_ratio"] > 0.25 and risk_profile == "稳健":
        score_cap = min(score_cap, 84)
        cap_reasons.append("稳健型家庭的单只持仓占比已经不低，最高只给浅绿色观察。")

    if position_summary["industry_concentration"] > 0.80 and position_summary["top_industry"] != "未知":
        score_cap = min(score_cap, 84)
        cap_reasons.append("股票/基金部分高度集中在同一行业，绿色也需要继续观察。")

    final_score = round(min(total_score, score_cap))
    level, color, level_text = _level_from_score(final_score)

    risk_notes: list[str] = []
    risk_notes.extend(cap_reasons)
    risk_notes.extend(position_summary["notes"])
    risk_notes.extend(match["notes"])
    for stock in stock_results:
        for note in stock["financial_notes"][:2] + stock["heat_notes"][:2] + stock["position_notes"][:1]:
            if note not in risk_notes:
                risk_notes.append(note)

    advice = [
        _family_advice(level),
        "本工具只做风险体检，不构成投资建议；家里真正用钱计划要放在第一位。",
        "不要因为一天上涨就追，也不要因为一天下跌就慌。先看仓位、现金和公司经营是否踏实。",
    ]

    if severe_missing:
        data_status = "数据不足，不能做完整判断"
    elif finance_missing:
        data_status = "部分数据缺失，已保守判断"
    elif any(stock_value(stock, "data_source") == "真实数据" for stock in stocks):
        data_status = "已使用真实数据，并结合本地缓存"
    elif all(stock_value(stock, "data_source") == "示例数据" for stock in stocks):
        data_status = "示例数据"
    else:
        data_status = "本地缓存"

    return {
        "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "score": int(final_score),
        "raw_score": round(total_score, 1),
        "level": level,
        "color": color,
        "level_text": level_text,
        "data_status": data_status,
        "total_assets": total_assets,
        "cash": cash,
        "stock_total": stock_total,
        "cash_ratio": position_summary["cash_ratio"],
        "stock_ratio": position_summary["stock_ratio"],
        "max_single_ratio": position_summary["max_single_ratio"],
        "top_industry": position_summary["top_industry"],
        "industry_concentration": position_summary["industry_concentration"],
        "module_scores": {
            "公司财务质量": round(financial_score, 1),
            "交易热度风险": round(heat_score, 1),
            "家庭仓位安全": round(position_score, 1),
            "风险承受匹配": round(match_score, 1),
        },
        "scoring_weights": {
            "家庭仓位安全": 35,
            "公司财务质量": 30,
            "交易热度风险": 20,
            "风险承受匹配": 15,
        },
        "stock_results": stock_results,
        "risk_notes": risk_notes[:12],
        "advice": advice,
        "cap_reasons": cap_reasons,
    }
