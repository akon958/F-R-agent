from __future__ import annotations

import json
from typing import Any


DISCLAIMER = "本工具只做家庭投资风险体检和学习参考，不构成任何投资建议，也不提供买卖推荐。"

FOLLOWUP_QUESTIONS = [
    "现金比例怎么看？",
    "哪只标的最需要关注？",
    "PE/PB 对这次判断有什么帮助？",
    "数据缺失会影响判断吗？",
    "为什么这个组合还需要继续观察？",
    "给爸妈一句话怎么说？",
]


def _safe_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _fmt_percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "暂无"


def _sanitize_report_text(text: str) -> str:
    replacements = {
        "买入": "继续观察",
        "卖出": "重点复盘",
        "加仓": "增加投入前先讨论",
        "减仓": "控制集中度",
        "强烈": "明显",
        "抄底": "低位判断",
        "必涨": "确定上涨",
        "一定赚钱": "确定有收益",
        "马上操作": "立刻处理",
        "预测涨跌": "判断短期方向",
        "我们可能需要慢慢调整": "后续讨论时可以重点关注这一点",
    }
    safe = text
    for old, new in replacements.items():
        safe = safe.replace(old, new)
    return safe


def _flatten_missing_data(missing_data: dict[str, Any]) -> str:
    if not missing_data:
        return "这次体检没有发现明显的数据缺口。"
    parts = []
    valuation_missing = False
    for title, items in missing_data.items():
        if not items:
            continue
        if "估值" in title:
            valuation_missing = True
            continue
        parts.append(f"{title}涉及 {len(items)} 只标的")
    if valuation_missing:
        parts.insert(0, "估值数据暂缺，本次不评价估值高低。")
    return "；".join(parts) if parts else "这次体检没有发现明显的数据缺口。"


# ─────────────────────────────────────────────────────────────────
# 三种报告模式的内部实现
# ─────────────────────────────────────────────────────────────────

def _generate_brief_report(agent_context: dict[str, Any]) -> str:
    """简洁版：300 字以内，只讲结论、主要风险、重点关注点。"""
    risk_score = agent_context.get("risk_score", 0)
    risk_level = agent_context.get("risk_level", "暂无")
    cash_ratio = agent_context.get("cash_ratio", 0)
    max_position_ratio = agent_context.get("max_position_ratio", 0)
    main_risks = agent_context.get("main_risks", []) or []
    missing_data = agent_context.get("missing_data", {}) or {}

    primary_risk = main_risks[0] if main_risks else "目前没有特别突出的风险点。"
    valuation_missing = bool(missing_data.get("估值数据缺失"))
    valuation_note = " 估值数据暂缺，本次不评价估值高低。" if valuation_missing else ""

    if max_position_ratio >= 0.40:
        conclusion = "集中度偏高，需多留意单只占比。"
    elif cash_ratio < 0.15:
        conclusion = "现金比例偏低，备用金需优先关注。"
    else:
        conclusion = "整体结构暂无极端问题。"

    report = (
        f"【结论】综合评分 {risk_score}/100，风险等级{risk_level}。{conclusion}\n\n"
        f"【主要风险】{primary_risk}\n\n"
        f"【重点关注】现金比例 {_fmt_percent(cash_ratio)}，最大单只占比 {_fmt_percent(max_position_ratio)}。"
        f"{valuation_note}\n\n"
        f"【免责声明】{DISCLAIMER}"
    )
    return _sanitize_report_text(report)


def _generate_detailed_report(agent_context: dict[str, Any]) -> str:
    """详细版：600-800 字，解释现金比例、持仓占比、财务指标和数据缺失。"""
    holdings = agent_context.get("holdings", []) or []
    main_risks = agent_context.get("main_risks", []) or []
    missing_data = agent_context.get("missing_data", {}) or {}
    risk_score = agent_context.get("risk_score", 0)
    risk_level = agent_context.get("risk_level", "暂无")
    cash_ratio = agent_context.get("cash_ratio", 0)
    stock_ratio = agent_context.get("stock_ratio", 0)
    max_position_ratio = agent_context.get("max_position_ratio", 0)
    risk_preference = agent_context.get("risk_preference", "稳健")
    data_status = agent_context.get("data_status", "本地缓存")
    history_summary = agent_context.get("history_summary", "")
    family_cash = agent_context.get("family_cash", 0)
    total_position_value = agent_context.get("total_position_value", 0)

    holding_names = "、".join(
        f"{item.get('code', '')} {item.get('name', '')}".strip()
        for item in holdings[:5]
    ) or "当前持仓"

    max_holding = max(holdings, key=lambda x: x.get("amount", 0), default={}) if holdings else {}
    max_name = f"{max_holding.get('code', '')} {max_holding.get('name', '')}".strip() if max_holding else ""

    if max_position_ratio >= 0.40:
        overall = (
            f"这个组合最突出的特征是集中度偏高——{max_name} 单只占比达到 {_fmt_percent(max_position_ratio)}，"
            f"超过了家庭总资产的 40%，遇到个股变化时家庭感受会比较直接。"
        )
    elif stock_ratio >= 0.75:
        overall = (
            f"这个组合股票/基金占比达到 {_fmt_percent(stock_ratio)}，"
            f"整体仓位较重，市场波动时对家庭的影响会比较明显。"
        )
    elif cash_ratio >= 0.30:
        overall = (
            f"这个组合现金比例达到 {_fmt_percent(cash_ratio)}，"
            f"流动性较好，短期用钱压力相对小一些。"
        )
    else:
        overall = "这个组合整体结构暂无极端问题，但仍需关注集中度和现金是否够用。"

    risk_list = "；".join(main_risks[:4]) if main_risks else "目前没有特别突出的风险。"
    missing_text = _flatten_missing_data(missing_data)
    history_text = f"\n\n近期历史记录：{history_summary}" if history_summary else ""

    try:
        cash_str = f"{int(family_cash):,} 元"
        position_str = f"{int(total_position_value):,} 元"
    except (TypeError, ValueError):
        cash_str = "暂无"
        position_str = "暂无"

    report = f"""【整体判断】
当前组合持仓为 {holding_names}，综合评分 {risk_score}/100，风险等级为{risk_level}。按"{risk_preference}"风险承受能力衡量，家庭现金约 {cash_str}（占比 {_fmt_percent(cash_ratio)}），持仓市值约 {position_str}（占比 {_fmt_percent(stock_ratio)}）。{overall}

【主要风险】
需要关注的主要风险：{risk_list}。其中最优先考虑的是现金储备是否足够应对家庭突发支出，其次才是组合结构问题。

【数据缺失说明】
数据来源：{data_status}。{missing_text} 数据缺失的部分不作为判断依据，只对有数据支撑的部分做评估。

【给爸妈重点看的地方】
建议关注三件事：第一，家庭现金够不够应急；第二，单只标的占比有没有太高；第三，财务数据是否完整，数据越完整判断越可靠。{history_text}

这份报告适合作为家庭讨论和定期复盘的参考，不适合作为临时操作的依据。

【免责声明】
{DISCLAIMER}"""
    return _sanitize_report_text(report)


def _generate_parent_report(agent_context: dict[str, Any]) -> str:
    """爸妈版（默认）：语言最简单，像子女给爸妈解释，少用专业词。"""
    holdings = agent_context.get("holdings", []) or []
    main_risks = agent_context.get("main_risks", []) or []
    missing_data = agent_context.get("missing_data", {}) or {}
    risk_score = agent_context.get("risk_score", 0)
    risk_level = agent_context.get("risk_level", "暂无")
    cash_ratio = agent_context.get("cash_ratio", 0)
    stock_ratio = agent_context.get("stock_ratio", 0)
    max_position_ratio = agent_context.get("max_position_ratio", 0)
    history_summary = agent_context.get("history_summary", "")

    holding_names = "、".join(
        f"{item.get('name', '') or item.get('code', '')}"
        for item in holdings[:3]
    ) or "这些持仓"

    if max_position_ratio >= 0.40:
        overall = "有一只股票放的钱比较多，家里对它的变化会比较敏感。"
    elif stock_ratio >= 0.75:
        overall = "家里大部分钱放在股票里了，如果行情不好，感受会比较明显。"
    elif cash_ratio >= 0.30:
        overall = "家里现金还比较充足，不容易出现急用钱却没钱的情况。"
    else:
        overall = "整体问题不算大，有几个地方值得定期关注。"

    primary_risk = main_risks[0] if main_risks else "暂时没有特别需要担心的事，但要记得定期看一看。"
    valuation_missing = bool(missing_data.get("估值数据缺失"))
    missing_note = "估值数据暂缺，本次不评价估值高低。" if valuation_missing else "这次体检数据基本齐全。"
    history_note = f"上次体检：{history_summary.split('；')[0]}。" if history_summary else ""

    report = f"""【整体判断】
爸妈，{holding_names} 这个组合体检完了。评分是 {risk_score} 分（满分 100），等级是"{risk_level}"。{overall}现金占比大约 {_fmt_percent(cash_ratio)}，股票/基金占比大约 {_fmt_percent(stock_ratio)}。

【主要风险】
最需要留心的一点是：{primary_risk} 不用马上做什么，但心里要有数。

【数据缺失说明】
{missing_note} 没有的数据我们不猜，只把有把握的部分放进结论里。

【给爸妈重点看的地方】
只需要记三件事：一，家里留的现金够不够用；二，有没有哪只股票放了太多钱；三，这个结果是参考，不是指令。{history_note} 有疑问可以继续问，或者等下次定期复盘再看。

【免责声明】
{DISCLAIMER}"""
    return _sanitize_report_text(report)


# ─────────────────────────────────────────────────────────────────
# 主入口：模式分发
# ─────────────────────────────────────────────────────────────────

def generate_agent_report(agent_context: dict[str, Any], mode: str = "爸妈版") -> str:
    """Generate a family-facing report strictly from agent_context fields.

    mode: "爸妈版" (default) | "简洁版" | "详细版"
    All three modes are strictly based on agent_context — no fabrication.
    """
    if mode == "简洁版":
        return _generate_brief_report(agent_context)
    if mode == "详细版":
        return _generate_detailed_report(agent_context)
    return _generate_parent_report(agent_context)


# ─────────────────────────────────────────────────────────────────
# 追问回答：严格基于 agent_context，200-400 字
# ─────────────────────────────────────────────────────────────────

def answer_followup_question(agent_context: dict[str, Any], question: str) -> str:
    """Answer a follow-up question strictly based on agent_context.

    Supported questions (matched by FOLLOWUP_QUESTIONS):
      1. 现金比例怎么看？
      2. 哪只标的最需要关注？
      3. PE/PB 对这次判断有什么帮助？
      4. 数据缺失会影响判断吗？
      5. 为什么这个组合还需要继续观察？
      6. 给爸妈一句话怎么说？

    Rules:
    - Must be strictly based on agent_context fields
    - No fabrication of PE/PB, ROE, net_margin or other missing metrics
    - No stock recommendations, price predictions, or trade suggestions
    - No "您家" / "贵家庭" / "您的家庭资产"
    - 200-400 Chinese characters + DISCLAIMER
    """
    risk_score = int(agent_context.get("risk_score", 0) or 0)
    risk_level = agent_context.get("risk_level", "暂无") or "暂无"
    cash_ratio = float(agent_context.get("cash_ratio", 0) or 0)
    stock_ratio = float(agent_context.get("stock_ratio", 0) or 0)
    max_position_ratio = float(agent_context.get("max_position_ratio", 0) or 0)
    main_risks = list(agent_context.get("main_risks", []) or [])
    holdings = list(agent_context.get("holdings", []) or [])
    missing_data = dict(agent_context.get("missing_data", {}) or {})
    pe_pb_status: str = agent_context.get("pe_pb_status", "") or ""
    financial_status: str = agent_context.get("financial_status", "") or ""

    sorted_holdings = sorted(holdings, key=lambda x: x.get("amount", 0), reverse=True)
    top = sorted_holdings[0] if sorted_holdings else {}
    top_name = (top.get("name") or top.get("code") or "最大持仓") if top else "暂无"
    top_ratio = float(top.get("position_ratio", max_position_ratio) if top else max_position_ratio)

    valuation_missing = bool(missing_data.get("估值数据缺失"))
    finance_missing = bool(missing_data.get("财务数据缺失"))

    q = question.strip()

    # ── 问题 1：现金比例怎么看？ ─────────────────────────────────
    if "现金比例" in q:
        if cash_ratio >= 0.30:
            level_desc = "比较充足"
            advice = "短期用钱压力相对小，不必过于紧张；但现金闲置太多也未必是最优安排，可以定期复盘是否合适。"
        elif cash_ratio >= 0.15:
            level_desc = "基本合理"
            advice = "整体在参考范围内。如果近期有大额支出计划（装修、医疗、教育），提前留出充足流动资金更稳妥。"
        else:
            level_desc = "偏低"
            advice = "如果家里突然有急用，可能比较被动。备用金的重要性不低于持仓本身，建议优先确保现金储备充足。"
        body = (
            f"这次体检显示，家庭现金占比约 {_fmt_percent(cash_ratio)}，整体感觉属于「{level_desc}」。\n\n"
            f"通常家庭保留 15%–30% 现金是比较常见的参考范围，但每家情况不同，"
            f"关键是能不能覆盖突发的用钱需求。\n\n{advice}"
        )

    # ── 问题 2：哪只标的最需要关注？ ────────────────────────────
    elif "哪只" in q or ("标的" in q and "关注" in q):
        if not top:
            body = "当前没有有效持仓数据，无法判断哪只标的最需要关注。请确认持仓信息填写正确。"
        else:
            body = f"从持仓金额来看，{top_name} 目前占比最高，约为家庭总资产的 {_fmt_percent(top_ratio)}。\n\n"
            if top_ratio >= 0.40:
                body += (
                    "这个占比已偏高（超过 40%），单只集中度风险比较突出。"
                    "如果这只标的出现较大变化，家庭的感受会比较直接，需要多留意它的后续动态。"
                )
            elif top_ratio >= 0.25:
                body += (
                    "占比处于中等水平，不算极端，但建议定期确认这只标的有没有出现值得关注的基本面变化，"
                    "定期复盘比较稳妥。"
                )
            else:
                body += "占比目前不算极端，整体集中度尚可，保持关注即可。"
            if finance_missing:
                body += "\n\n另外这次财务数据有部分缺失，对公司质量的判断会有一定局限，建议等数据补全后再做更完整的评估。"

    # ── 问题 3：PE/PB 对这次判断有什么帮助？ ────────────────────
    elif "PE" in q or "PB" in q or "市盈率" in q or "市净率" in q:
        if valuation_missing:
            status_desc = pe_pb_status or "PE/PB 数据暂缺"
            body = (
                f"这次体检中估值数据（PE/PB）暂缺（{status_desc}），所以本次结论里没有对股价高低做评判。\n\n"
                "PE（市盈率）是看「按现在股价买，大约需要多少年回本」；"
                "PB（市净率）是看「股价相对公司账面资产是贵还是便宜」。\n\n"
                "这两个数字缺失，意味着这次无法判断各持仓现在是否处于合理定价区间。"
                "但这不影响对持仓结构、现金比例和集中度的判断——这些结论依然有效。\n\n"
                "后续如果数据补全，可以再跑一次体检，会得到关于估值层面更完整的参考。"
            )
        else:
            status_desc = pe_pb_status or "PE/PB 数据已有一定覆盖"
            body = (
                f"这次体检中估值数据（{status_desc}）。\n\n"
                "PE（市盈率）反映「按现在股价买要多少年回本」，"
                "PB（市净率）反映「股价相对公司账面资产是贵还是便宜」。\n\n"
                "体检用这两个数据来辅助判断各持仓是否处于合理区间。"
                "不过它们只是参考，不是买卖的唯一依据——市场很多时候不按估值出牌，"
                "高 PE 不一定会跌，低 PE 也不一定会涨。\n\n"
                "有了 PE/PB，这次体检的结论在估值层面会更有依据，整体可信度相对更高。"
            )

    # ── 问题 4：数据缺失会影响判断吗？ ─────────────────────────
    elif "数据缺失" in q:
        missing_parts: list[str] = []
        for title, items in missing_data.items():
            if items:
                if "估值" in title:
                    missing_parts.append(f"估值数据（PE/PB）暂缺，涉及 {len(items)} 只")
                elif "财务" in title:
                    missing_parts.append(f"财务数据（ROE、净利率等）暂缺，涉及 {len(items)} 只")
                else:
                    missing_parts.append(f"{title}涉及 {len(items)} 只")
        if not missing_parts:
            body = (
                "这次体检的数据基本完整，没有发现明显缺口，各项判断的依据相对充分。\n\n"
                "数据完整时，可以同时评估现金比例、持仓结构和公司基本面三个维度，"
                "这是最理想的体检状态。结论的可信度会更高。"
            )
        else:
            body = f"这次体检发现：{'；'.join(missing_parts)}。\n\n缺失的数据不会被编造进结论，只做保守判断。\n\n"
            impacts: list[str] = []
            if finance_missing:
                impacts.append(
                    "财务数据缺失时，对公司盈利能力、资产质量的判断会有局限，"
                    "只能依靠持仓结构层面做评估，建议多留心这部分缺口。"
                )
            if valuation_missing:
                impacts.append("估值（PE/PB）数据缺失时，不对股价贵不贵做任何评价，以免误导判断。")
            body += "\n".join(impacts) if impacts else "当前缺失影响有限，主要结论仍然有效。"

    # ── 问题 5：为什么这个组合还需要继续观察？ ──────────────────
    elif "继续观察" in q or ("为什么" in q and "组合" in q):
        reasons: list[str] = []
        # 现金比例
        if cash_ratio < 0.15:
            reasons.append(f"现金比例偏低（约 {_fmt_percent(cash_ratio)}），备用金储备需要持续关注")
        # 集中度
        if max_position_ratio >= 0.35:
            reasons.append(
                f"最大单只持仓占比较高（约 {_fmt_percent(max_position_ratio)}），"
                f"集中度风险需要定期确认"
            )
        # 数据缺失
        if finance_missing:
            reasons.append("财务数据有缺失，对部分标的的公司质量判断尚不完整")
        if valuation_missing:
            reasons.append("估值数据暂缺，还无法判断各持仓的定价是否合理")
        # 主要风险
        if main_risks:
            reasons.append(f"体检发现的主要风险点：{main_risks[0]}")
        if not reasons:
            reasons.append("市场环境持续变化，定期复盘是任何组合的基本要求")

        reason_text = "；\n".join(f"• {r}" for r in reasons[:4])
        body = (
            f"这个组合评分 {risk_score}/100，等级{risk_level}。"
            f"需要继续关注的原因主要有：\n\n{reason_text}\n\n"
            "持续观察不代表要频繁操作，而是要定期确认这些关注点有没有出现明显变化。"
            "家庭投资组合最重要的是「结构稳」，不是「短期涨跌」。"
        )

    # ── 问题 6：给爸妈一句话怎么说？ ────────────────────────────
    elif "一句话" in q:
        primary = main_risks[0] if main_risks else "持仓集中度"
        if risk_score >= 75:
            sentence = (
                f"这个组合评分 {risk_score} 分，整体暂时没有特别刺眼的问题，"
                f"按现在的安排定期看一看就行，不用急着做什么。"
            )
        elif risk_score >= 55:
            sentence = (
                f"这个组合评分 {risk_score} 分，有几个地方值得留意，"
                f"特别是{primary}，不用慌，但心里要有数，过一段时间再看看有没有变化。"
            )
        else:
            sentence = (
                f"这个组合评分 {risk_score} 分，{primary}这块需要认真对待，"
                f"建议家人一起讨论一下，看看结构上有没有可以调整的地方。"
            )
        body = (
            f"给爸妈的一句话：\n\n「{sentence}」\n\n"
            "（这是本次体检的参考，不是操作建议。具体怎么做，还是要结合家庭实际情况讨论。）"
        )

    # ── 兜底：未匹配到任何问题 ───────────────────────────────────
    else:
        body = (
            f"根据这次体检：评分 {risk_score}/100，等级{risk_level}。\n"
            f"主要关注点：{main_risks[0] if main_risks else '持仓结构整体无极端问题'}。\n"
            f"现金比例 {_fmt_percent(cash_ratio)}，最大单只占比 {_fmt_percent(max_position_ratio)}。"
            f"{'估值数据暂缺，本次不评价估值高低。' if valuation_missing else ''}\n\n"
            "如需更具体的解答，可以从上方的快捷问题中选择。"
        )

    return _sanitize_report_text(f"{body}\n\n{DISCLAIMER}")


# ─────────────────────────────────────────────────────────────────
# 以下为旧式 DeepSeek 接口（保留在"普通分析/调试入口"中使用）
# ─────────────────────────────────────────────────────────────────

def _build_ai_context(analysis: dict[str, Any]) -> dict[str, Any]:
    stock_items = []
    for item in analysis.get("stock_results", []):
        stock_items.append(
            {
                "code": item.get("code", ""),
                "name": item.get("name", ""),
                "amount": item.get("amount", 0),
                "single_ratio": item.get("single_ratio", 0),
                "level": item.get("level", ""),
                "industry": item.get("industry", ""),
                "financial_text": item.get("financial_text", ""),
                "heat_text": item.get("heat_text", ""),
                "position_notes": item.get("position_notes", []),
                "price": item.get("price"),
                "pct_change": item.get("pct_change"),
                "turnover": item.get("turnover"),
                "pe": item.get("pe"),
                "pb": item.get("pb"),
                "turnover_rate": item.get("turnover_rate"),
                "market_cap": item.get("market_cap"),
                "float_market_cap": item.get("float_market_cap"),
                "volume_ratio": item.get("volume_ratio"),
                "amplitude": item.get("amplitude"),
                "in_out_ratio": item.get("in_out_ratio"),
                "roe": item.get("roe"),
                "net_margin": item.get("net_margin"),
                "gross_margin": item.get("gross_margin"),
                "revenue_growth": item.get("revenue_growth"),
                "profit_growth": item.get("profit_growth"),
                "debt_ratio": item.get("debt_ratio"),
                "cashflow_profit_ratio": item.get("cashflow_profit_ratio"),
                "updated_at": item.get("updated_at"),
                "data_source": item.get("data_source", ""),
                "market_source": item.get("market_source", ""),
                "finance_source": item.get("finance_source", ""),
            }
        )

    return {
        "score": analysis.get("score", 0),
        "level": analysis.get("level", ""),
        "level_text": analysis.get("level_text", ""),
        "data_status": analysis.get("data_status", ""),
        "analysis_time": analysis.get("analysis_time", ""),
        "cash": analysis.get("cash", 0),
        "total_assets": analysis.get("total_assets", 0),
        "cash_ratio": analysis.get("cash_ratio", 0),
        "stock_ratio": analysis.get("stock_ratio", 0),
        "max_single_ratio": analysis.get("max_single_ratio", 0),
        "top_industry": analysis.get("top_industry", ""),
        "industry_concentration": analysis.get("industry_concentration", 0),
        "module_scores": analysis.get("module_scores", {}),
        "risk_notes": analysis.get("risk_notes", []),
        "advice": analysis.get("advice", []),
        "stocks": stock_items,
    }


def generate_parent_friendly_report(analysis: dict[str, Any], api_key: str) -> str:
    """Call DeepSeek to write a plain-language risk explanation for family users."""
    if not api_key:
        raise ValueError("missing api key")

    from openai import OpenAI

    context = _build_ai_context(analysis)
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    rules = [
        "1. 语气像在家庭微信群里回消息：用'我们''爸''妈'，偶尔用'其实''不过''另外'等口语连接词，"
        "读起来像真人在说话，不像在朗读报告。不用'您家''贵家庭''阁下'等疏远表达。",
        "2. 不推荐任何股票，不预测涨跌，不说'必涨''抄底''一定赚''马上卖'，"
        "不给买入/卖出/加仓/减仓的具体指令。",
        "3. 每次出现财务或交易指标，先写专业术语，括号里跟一句通俗说明，两者缺一不可。"
        "标准写法示例（格式不变）：\n"
        "   ROE（公司用自己的钱赚钱的能力）\n"
        "   净利率（每卖出100元最终留下多少利润）\n"
        "   毛利率（产品本身的赚钱空间）\n"
        "   营收增长率（公司收入有没有在增加）\n"
        "   净利润增长率（公司最终到手的钱有没有在增加）\n"
        "   资产负债率（公司借了多少钱相对自己的家底）\n"
        "   经营现金流（公司账面利润有多少真正变成了现金）\n"
        "   换手率（今天有多少人在买卖这只股票）\n"
        "   量比（今天成交量比平时多多少）\n"
        "   振幅（今天股价最高最低相差多少）\n"
        "   市盈率（按现在股价买，需要多少年回本）\n"
        "   市净率（股价相对公司账面资产贵不贵）",
        "4. 总字数控制在 600～700 字，内容要扎实，但不要凑字数，爸妈一口气能看完最好。",
        "5. 按下面五段结构输出，每段加标题，顺序不变，不增减段落：\n"
        "   【整体感觉】\n   【主要风险】\n   【数据缺失说明】\n   【爸妈重点看什么】\n   【免责声明】",
        "6. 【免责声明】那段原文照抄，一字不改：" + DISCLAIMER,
    ]

    system_prompt = (
        "你是家里懂一点投资的亲戚，正在用微信跟家人解释这次持仓风险体检的结果。\n"
        "你说话直接、温和，会把枯燥的数据翻译成家人听得懂的话，"
        "但绝不给任何买卖建议，因为你知道预测市场是不靠谱的。\n\n"
        "写作要求：\n"
        + "\n".join(rules)
    )

    data_note = (
        "数据缺失处理：\n"
        "- 某只持仓的 finance_source 是「数据缺失」→ 【数据缺失说明】里提一句：行情找到了，但财务数据暂时缺，"
        "对这只股票的公司质量判断不完整，要多留心。\n"
        "- 所有数据都完整 → 写：这次体检数据都找到了，没有明显缺失。"
    )

    user_prompt = (
        "下面是家庭投资风险体检的 JSON 结果，请按你的写作要求输出给爸妈看的说明。\n\n"
        + data_note
        + "\n\n体检数据：\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
    )

    response = client.chat.completions.create(
        model="deepseek-reasoner",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.6,
        max_tokens=2048,
    )

    content = _safe_text(response.choices[0].message.content).strip()
    if DISCLAIMER not in content:
        content = f"{content}\n\n{DISCLAIMER}"
    return content
