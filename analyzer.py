from __future__ import annotations

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


def detect_family_disagreement(comments: list[dict]) -> dict:
    """
    检测家庭成员在同一关注点上的风险立场分歧。

    只使用家人主动选择的 stance，不根据内容猜测立场。
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in comments or []:
        if not isinstance(raw, dict):
            continue
        member = str(raw.get("member") or raw.get("author_name") or "").strip()
        focus = str(raw.get("focus") or raw.get("focus_tag") or "other").strip() or "other"
        stance = str(raw.get("stance") or "neutral").strip() or "neutral"
        content = str(raw.get("content") or raw.get("comment_text") or "").strip()
        if not member or stance == "neutral":
            continue
        if stance not in ("conservative", "aggressive"):
            continue
        grouped.setdefault(focus, []).append(
            {
                "member": member,
                "focus": focus,
                "stance": stance,
                "content": content,
            }
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


def financial_quality(stock: dict[str, Any]) -> dict[str, Any]:
    name = stock_value(stock, "name") or stock_value(stock, "code")
    source = stock.get("财务数据来源") or stock_value(stock, "data_source")
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

    score = 0.0
    score += clamp(roe / 0.20 * 18)
    score += clamp(net_margin / 0.20 * 10)
    score += clamp(gross_margin / 0.40 * 7)
    score += clamp((revenue_growth + 0.10) / 0.30 * 14)
    score += clamp((profit_growth + 0.10) / 0.35 * 14)
    score += clamp((0.85 - debt_ratio) / 0.85 * 18)
    score += clamp(cash_profit / 1.00 * 19)
    score -= missing_count * 4
    score = clamp(score)

    notes: list[str] = []
    if roe >= 0.15:
        notes.append(f"{name} 的 ROE（公司用自己的钱赚钱的能力）看起来较强。")
    elif roe < 0.08:
        notes.append(f"{name} 的 ROE（公司用自己的钱赚钱的能力）偏弱，需要多留心。")

    if net_margin >= 0.20:
        notes.append(f"{name} 净利率（每卖出100元最终留下多少利润）较高，留利能力好。")
    elif net_margin < 0.05:
        notes.append(f"{name} 净利率（每卖出100元最终留下多少利润）偏低，留利空间不大。")

    if revenue_growth < 0 or profit_growth < 0:
        notes.append(f"{name} 营收增长率或净利润增长率（公司收入和利润有没有在增加）出现下滑，先别只看短期热闹。")

    if debt_ratio > 0.75:
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
