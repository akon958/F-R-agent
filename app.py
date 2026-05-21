from __future__ import annotations

import os
import random as _random
from html import escape
from math import pi
from typing import Any

import pandas as pd
import streamlit as st

from analyzer import analyze_history_changes, analyze_portfolio, build_risk_factor_breakdown
from agent import run_family_risk_agent
from config import (
    APP_SUBTITLE,
    APP_TITLE,
    COMPLIANCE_REPLACEMENTS,
    DEFAULT_AMOUNTS,
    DEFAULT_CODES,
    DEFAULT_FOLLOWUP_QUESTIONS,
    DEFAULT_REPORT_MODE,
    FIXED_DISCLAIMER,
    HOME_DISCLAIMER,
    REPORT_DISCLAIMER,
    REPORT_MODES,
    RISK_PROFILE_HINTS,
    RISK_PROFILE_OPTIONS,
    RISK_PROFILE_SHORT_HINTS,
)
from question_router import route_slash_command
from validator import sanitize_compliance_text

# ─────────────────────────────────────────────────────────────────
# 追问功能本地实现：完整逻辑直接写在 app.py，
# 不依赖云端 ai_report.py 的版本，永远可用。
# ─────────────────────────────────────────────────────────────────
_DISCLAIMER = FIXED_DISCLAIMER
FOLLOWUP_VERSION = "v4_raw_error_diagnostic"


def _fmt_pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "暂无"


def _sanitize(text: str) -> str:
    for old, new in COMPLIANCE_REPLACEMENTS.items():
        text = text.replace(old, new)
    return text


def get_dynamic_questions(agent_context: dict) -> list[str]:
    """根据 agent_context 生成 6 个随机变体追问问题（本地实现，不依赖 ai_report.py）。"""
    _random.seed()
    cash_ratio = float(agent_context.get("cash_ratio", 0) or 0)
    stock_ratio = float(agent_context.get("stock_ratio", 0) or 0)
    max_pos = float(agent_context.get("max_position_ratio", 0) or 0)
    risk_score = int(agent_context.get("risk_score", 0) or 0)
    holdings = list(agent_context.get("holdings", []) or [])
    missing_data = dict(agent_context.get("missing_data", {}) or {})

    sorted_h = sorted(holdings, key=lambda x: x.get("amount", 0), reverse=True)
    top = sorted_h[0] if sorted_h else {}
    top_name = (top.get("name") or top.get("code") or "") if top else ""
    top_pct = f"{max_pos * 100:.0f}%"
    cash_pct = f"{cash_ratio * 100:.0f}%"
    stock_pct = f"{stock_ratio * 100:.0f}%"
    valuation_missing = bool(missing_data.get("估值数据缺失"))
    finance_missing = bool(missing_data.get("财务数据缺失"))
    questions: list[str] = []

    # 槽 1：现金
    if cash_ratio < 0.10:
        opts = [f"现金只剩 {cash_pct}，备用金够用吗？",
                f"家里现金只有 {cash_pct}，会不会太少了？",
                f"现金比例 {cash_pct}，遇到急用钱能撑住吗？"]
    elif cash_ratio < 0.15:
        opts = [f"现金比例 {cash_pct} 偏低，需要担心吗？",
                f"现金只有 {cash_pct}，够应对突发支出吗？",
                f"备用金 {cash_pct} 是否太薄了？"]
    elif cash_ratio >= 0.45:
        opts = [f"现金留了 {cash_pct}，是不是太保守了？",
                f"现金比例 {cash_pct}，还需要保留这么多吗？",
                f"家里 {cash_pct} 是现金，这样合理吗？"]
    else:
        opts = ["现金比例怎么看？", "家里留多少现金比较合适？", "现金比例对这次体检影响大吗？"]
    questions.append(_random.choice(opts))

    # 槽 2：集中度
    if top_name and max_pos >= 0.40:
        opts = [f"{top_name} 占了 {top_pct}，集中度高有什么风险？",
                f"最大持仓 {top_name} 占 {top_pct}，该怎么看？",
                f"哪只标的占比最高（{top_pct}）？需要重点关注吗？"]
    elif top_name and max_pos >= 0.25:
        opts = [f"{top_name} 占比最高（{top_pct}），需要重点关注吗？",
                "哪只标的目前持仓比例最重？",
                f"持仓里 {top_name} 这只标的占比最大，有风险吗？"]
    elif len(holdings) == 1:
        opts = ["只有一只标的，风险是不是太集中了？",
                "只持有一只，集中度风险怎么看？",
                "单只标的持仓和多只持仓有什么区别？"]
    else:
        opts = ["哪只标的最需要关注？", "这些持仓里哪只标的最需要盯着看？",
                "持仓里有没有特别需要关注的标的？"]
    questions.append(_random.choice(opts))

    # 槽 3：PE/PB
    if valuation_missing:
        opts = ["PE/PB 数据缺失，这次体检受影响吗？",
                "没有 PE/PB 数据，结论还准确吗？",
                "PE/PB 缺失会带来哪些判断盲区？"]
    else:
        opts = ["PE/PB 对这次判断有什么帮助？",
                "PE/PB 数据在体检里起什么作用？",
                "这次 PE/PB 数据说明了什么？"]
    questions.append(_random.choice(opts))

    # 槽 4：数据完整性
    if finance_missing:
        opts = ["财务数据有缺失，还能判断公司好坏吗？",
                "财务数据不全，对体检判断有多大影响？",
                "数据缺失的情况下，体检结论能信吗？"]
    else:
        opts = ["数据缺失会影响判断吗？", "这次体检数据缺失了哪些内容？",
                "数据完不完整，对体检结论影响大吗？"]
    questions.append(_random.choice(opts))

    # 槽 5：风险原因
    if risk_score < 50:
        opts = [f"评分 {risk_score} 分偏低，主要原因是什么？",
                f"这次评分只有 {risk_score} 分，说明了什么？",
                f"评分 {risk_score} 分，哪些方面拉低了分数？"]
    elif stock_ratio >= 0.85:
        opts = [f"股票/基金仓位已达 {stock_pct}，算重仓吗？",
                f"仓位 {stock_pct}，遇到市场大波动怎么看？",
                f"仓位这么重（{stock_pct}），风险怎么评估？"]
    else:
        opts = ["为什么这个组合还需要继续观察？",
                "体检完了，还需要继续观察哪些方面？",
                "这个组合为什么不能就此放心？"]
    questions.append(_random.choice(opts))

    # 槽 6：给爸妈一句话
    opts = ["给爸妈一句话怎么说？", "用一句话总结这次体检，怎么说？",
            "爸妈看这个结果，一句话能记住什么？",
            "如果只说一句话，爸妈最该知道什么？"]
    questions.append(_random.choice(opts))

    return questions


def _legacy_local_answer_followup_question(agent_context: dict, question: str) -> str:
    """根据 agent_context 回答追问（本地实现，不依赖 ai_report.py）。"""
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

    sorted_h = sorted(holdings, key=lambda x: x.get("amount", 0), reverse=True)
    top = sorted_h[0] if sorted_h else {}
    top_name = (top.get("name") or top.get("code") or "最大持仓") if top else "暂无"
    top_ratio = float(top.get("position_ratio", max_position_ratio) if top else max_position_ratio)
    valuation_missing = bool(missing_data.get("估值数据缺失"))
    finance_missing = bool(missing_data.get("财务数据缺失"))

    q = question.strip()

    # 问题 1：现金
    if "现金" in q or "备用金" in q:
        if cash_ratio >= 0.30:
            level_desc, advice = "比较充足", "短期用钱压力相对小，不必过于紧张；但现金闲置太多也未必是最优安排，可以定期复盘是否合适。"
        elif cash_ratio >= 0.15:
            level_desc, advice = "基本合理", "整体在参考范围内。如果近期有大额支出计划（装修、医疗、教育），提前留出充足流动资金更稳妥。"
        else:
            level_desc, advice = "偏低", "如果家里突然有急用，可能比较被动。备用金的重要性不低于持仓本身，建议优先确保现金储备充足。"
        body = (
            f"这次体检显示，家庭现金占比约 {_fmt_pct(cash_ratio)}，整体感觉属于「{level_desc}」。\n\n"
            f"通常家庭保留 15%–30% 现金是比较常见的参考范围，但每家情况不同，"
            f"关键是能不能覆盖突发的用钱需求。\n\n{advice}"
        )

    # 问题 2：集中度
    elif "哪只" in q or "集中" in q or ("占" in q and "%" in q) or "标的" in q or "一只" in q:
        if not top:
            body = "当前没有有效持仓数据，无法判断哪只标的最需要关注。请确认持仓信息填写正确。"
        else:
            body = f"从持仓金额来看，{top_name} 目前占比最高，约为家庭总资产的 {_fmt_pct(top_ratio)}。\n\n"
            if top_ratio >= 0.40:
                body += "这个占比已偏高（超过 40%），单只集中度风险比较突出。如果这只标的出现较大变化，家庭的感受会比较直接，需要多留意它的后续动态。"
            elif top_ratio >= 0.25:
                body += "占比处于中等水平，不算极端，但建议定期确认这只标的有没有出现值得关注的基本面变化，定期复盘比较稳妥。"
            else:
                body += "占比目前不算极端，整体集中度尚可，保持关注即可。"
            if finance_missing:
                body += "\n\n另外这次财务数据有部分缺失，对公司质量的判断会有一定局限，建议等数据补全后再做更完整的评估。"

    # 问题 3：PE/PB
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
                "不过它们只是参考，不是买卖的唯一依据——市场很多时候不按估值出牌。\n\n"
                "有了 PE/PB，这次体检的结论在估值层面会更有依据，整体可信度相对更高。"
            )

    # 问题 4：数据完整性
    elif "数据缺失" in q or ("数据" in q and ("影响" in q or "缺" in q)) or ("财务" in q and "判断" in q):
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
                "数据完整时，可以同时评估现金比例、持仓结构和公司基本面三个维度，结论的可信度会更高。"
            )
        else:
            body = f"这次体检发现：{'；'.join(missing_parts)}。\n\n缺失的数据不会被编造进结论，只做保守判断。\n\n"
            impacts: list[str] = []
            if finance_missing:
                impacts.append("财务数据缺失时，对公司盈利能力、资产质量的判断会有局限，只能依靠持仓结构层面做评估。")
            if valuation_missing:
                impacts.append("估值（PE/PB）数据缺失时，不对股价贵不贵做任何评价，以免误导判断。")
            body += "\n".join(impacts) if impacts else "当前缺失影响有限，主要结论仍然有效。"

    # 问题 5a：评分偏低
    elif "评分" in q and ("低" in q or "原因" in q or "分" in q):
        primary = main_risks[0] if main_risks else "持仓结构有待优化"
        if risk_score < 50:
            body = (
                f"评分主要由三部分影响：持仓集中度、现金比例和财务数据质量。\n\n"
                f"这次评分 {risk_score}/100 偏低，最主要的拉分项是：{primary}。\n\n"
                f"现金占比约 {_fmt_pct(cash_ratio)}，最大单只占比约 {_fmt_pct(max_position_ratio)}——"
                f"{'这两项都给评分带来了压力。' if cash_ratio < 0.15 and max_position_ratio > 0.35 else '集中度是主要影响因素。'}"
                f"{'财务数据缺失也会让体检保守降分。' if finance_missing else ''}"
            )
        else:
            body = (
                f"评分 {risk_score}/100 属于中等，整体没有特别极端的问题。"
                f"主要关注点是：{primary}。"
                f"现金比例 {_fmt_pct(cash_ratio)}，最大单只占比 {_fmt_pct(max_position_ratio)}，整体结构尚可。"
            )

    # 问题 5b：重仓/仓位
    elif "仓位" in q or "重仓" in q:
        if stock_ratio >= 0.85:
            body = (
                f"股票/基金占比 {_fmt_pct(stock_ratio)}，已经属于比较重的仓位。"
                f"在这种情况下，市场整体波动时对家庭的影响会比较明显。\n\n"
                f"家庭的备用金只有 {_fmt_pct(cash_ratio)}，"
                f"{'这个比例偏低，遇到急用钱时可能比较被动。' if cash_ratio < 0.15 else '这个比例尚可，短期用钱压力相对可控。'}"
            )
        elif stock_ratio >= 0.70:
            body = (
                f"股票/基金占比 {_fmt_pct(stock_ratio)}，处于中等偏高水平。"
                f"大部分资金在权益类资产里，遇到市场波动时感受会比较明显，"
                f"但只要家庭现金（{_fmt_pct(cash_ratio)}）够应急，整体还在可接受范围内。"
            )
        else:
            body = (
                f"当前股票/基金占比 {_fmt_pct(stock_ratio)}，整体仓位不算极端。"
                f"保持现金比例（{_fmt_pct(cash_ratio)}）充足是最重要的保障，"
                "仓位本身不是越低越好，关键是结构合不合理。"
            )

    # 问题 5c：继续观察
    elif "继续观察" in q or ("为什么" in q and "组合" in q) or ("需要" in q and "观察" in q):
        reasons: list[str] = []
        if cash_ratio < 0.15:
            reasons.append(f"现金比例偏低（约 {_fmt_pct(cash_ratio)}），备用金储备需要持续关注")
        if max_position_ratio >= 0.35:
            reasons.append(f"最大单只持仓占比较高（约 {_fmt_pct(max_position_ratio)}），集中度风险需要定期确认")
        if finance_missing:
            reasons.append("财务数据有缺失，对部分标的的公司质量判断尚不完整")
        if valuation_missing:
            reasons.append("估值数据暂缺，还无法判断各持仓的定价是否合理")
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

    # 问题 6：一句话总结
    elif "一句话" in q:
        primary = main_risks[0] if main_risks else "持仓集中度"
        if risk_score >= 75:
            sentence = (
                f"这个组合评分 {risk_score} 分，整体暂时没有特别刺眼的问题，"
                "按现在的安排定期看一看就行，不用急着做什么。"
            )
        elif risk_score >= 55:
            sentence = (
                f"这个组合评分 {risk_score} 分，有几个地方值得留意，"
                f"特别是{primary}，不用慌，但心里要有数，过一段时间再看看有没有变化。"
            )
        else:
            sentence = (
                f"这个组合评分 {risk_score} 分，{primary}这块需要认真对待，"
                "建议家人一起讨论一下，看看结构上有没有可以调整的地方。"
            )
        body = (
            f"给爸妈的一句话：\n\n「{sentence}」\n\n"
            "（这是本次体检的参考，不是操作建议。具体怎么做，还是要结合家庭实际情况讨论。）"
        )

    # 旧兼容兜底：相关但未命中特定关键词时，不再输出固定体检摘要
    else:
        body = "这个追问区主要回答本次投资体检相关问题。你可以问现金比例、持仓集中度、PE/PB、数据缺失或主要风险。"

    return _sanitize(f"{body}\n\n{_DISCLAIMER}")


# ─────────────────────────────────────────────────────────────────
# 兼容导入：若云端 ai_report.py 是新版本则用新版本覆盖上面的本地实现
# ─────────────────────────────────────────────────────────────────
_AI_REPORT_FALLBACK_MSG = "AI 报告模块需要重新部署最新版本。\n\n本工具只做家庭投资风险体检和学习参考，不构成任何投资建议，也不替任何人做交易决定。"

try:
    from ai_report import generate_agent_report  # type: ignore
except ImportError:
    def generate_agent_report(agent_context: dict, mode: str = DEFAULT_REPORT_MODE) -> dict[str, str]:  # type: ignore[misc]
        return {"ai_report": _AI_REPORT_FALLBACK_MSG, "report_source": "local_fallback"}

try:
    from ai_report import generate_parent_friendly_report  # type: ignore
except ImportError:
    def generate_parent_friendly_report(analysis: dict, api_key: str) -> str:  # type: ignore[misc]
        return _AI_REPORT_FALLBACK_MSG

_FALLBACK_QUESTIONS: list[str] = list(DEFAULT_FOLLOWUP_QUESTIONS)

try:
    from ai_report import answer_followup_question as _ai_answer, FOLLOWUP_QUESTIONS, get_dynamic_questions as _ai_get_q  # type: ignore
    answer_followup_question = _ai_answer  # type: ignore[assignment]
    get_dynamic_questions = _ai_get_q  # type: ignore[assignment]
    FOLLOWUP_ANSWER_IMPL = "ai_report.answer_followup_question"
except ImportError:
    FOLLOWUP_QUESTIONS: list[str] = _FALLBACK_QUESTIONS  # type: ignore[assignment]
    FOLLOWUP_ANSWER_IMPL = "app.local_fallback"

    def _app_fallback_answer_followup_question(agent_context: dict, question: str) -> dict[str, str]:
        q = question.strip()
        unrelated = (
            "这个追问区主要回答本次投资体检相关问题。"
            "你可以问现金比例、持仓集中度、PE/PB、数据缺失或主要风险。"
        )
        if not q:
            return {"answer": f"{unrelated}\n\n{_DISCLAIMER}", "source": "local_fallback", "error": "问题为空"}
        if "现金" in q:
            answer = f"这次体检显示，现金比例约 {_fmt_pct(agent_context.get('cash_ratio', 0))}。可以重点看备用金是否够覆盖家庭近期支出。"
        elif "PE" in q or "PB" in q or "估值" in q:
            answer = "PE/PB 主要帮助观察估值高低。如果数据暂缺，本次不评价估值高低，只看现金、仓位和集中度。"
        elif any(word in q for word in ["茅台", "占比", "集中", "持仓"]):
            answer = f"这次体检显示，最大单只占比约 {_fmt_pct(agent_context.get('max_position_ratio', 0))}。占比越高，组合越容易受单只标的影响。"
        elif "数据" in q or "缺失" in q:
            answer = "数据缺失会让判断更保守。缺失的数据不会被编造进结论，只对已有数据做风险体检。"
        elif any(word in q for word in ["值得买吗", "能买吗", "要不要买", "要不要卖", "卖吗"]):
            answer = "这个工具不能给买卖结论，也不预测涨跌。可以从占比、现金比例、估值数据是否完整和主要风险几个角度观察。"
        else:
            answer = unrelated
        return {"answer": f"{answer}\n\n{_DISCLAIMER}", "source": "local_fallback", "error": "ai_report.py 导入失败，使用 app 本地兜底"}

    answer_followup_question = _app_fallback_answer_followup_question  # type: ignore[assignment]


from data_fetcher import (
    get_cache_diagnostics,
    get_cache_summary,
    get_stock_metrics,
    normalize_code,
    refresh_current_holdings_cache,
    refresh_market_cache,
)
from report_generator import generate_ai_txt_report, generate_txt_report, money, percent
from storage import (
    format_datetime_for_display,
    get_last_family_comment_read_status,
    get_last_family_comment_save_status,
    get_last_followup_save_status,
    get_storage,
    get_storage_status,
    load_recent_analysis_history,
    load_recent_family_comments,
    load_recent_followup_history,
    make_note,
    save_family_comment,
    save_followup_history,
)


MARKET_INDEXES = [
    {"name": "上证指数", "code": "000001.SH", "value": "3,154.03", "change": 0.42},
    {"name": "深证成指", "code": "399001.SZ", "value": "9,681.18", "change": -0.18},
    {"name": "沪深300", "code": "000300.SH", "value": "3,673.22", "change": 0.25},
]

WATCH_ITEMS = [
    {"code": "600519", "name": "贵州茅台", "price": "1,486.20", "change": 0.86, "owner": "妈妈关注", "industry": "白酒"},
    {"code": "000001", "name": "平安银行", "price": "11.42", "change": -0.35, "owner": "爸爸关注", "industry": "银行"},
    {"code": "300750", "name": "宁德时代", "price": "196.80", "change": 1.12, "owner": "家庭共同", "industry": "电池"},
    {"code": "600036", "name": "招商银行", "price": "35.61", "change": 0.24, "owner": "家庭共同", "industry": "银行"},
]

RECENT_ITEMS = [
    {"code": "600519", "name": "贵州茅台", "time": "今天 09:42", "verdict": "稳健"},
    {"code": "300750", "name": "宁德时代", "time": "昨天 19:15", "verdict": "中性"},
    {"code": "000001", "name": "平安银行", "time": "3 天前", "verdict": "警示"},
]


st.set_page_config(page_title=APP_TITLE, layout="wide", initial_sidebar_state="collapsed")


def render_html(html: str) -> None:
    if hasattr(st, "html"):
        st.html(html)
    else:
        st.markdown(html, unsafe_allow_html=True)


def init_state() -> None:
    defaults = {
        "holding_rows": 2,
        "font_size": 14,
        "dark_mode": False,
        "fit_open": False,
        "notes": [],
        "notes_loaded": False,  # 用于只在 session 首次启动时从文件加载一次
        "report_mode": DEFAULT_REPORT_MODE,
        "followup_answers": [],
        "followup_questions": [],  # 每次体检生成一次，rerun 时保持不变
        "followup_version": FOLLOWUP_VERSION,
        "family_comments_cache": None,
        "family_comments": [],
        "family_comments_last_count": 0,
        "family_comment_last_save": {},
        "active_view": "analysis",
        "reverse_qa": dict(_REVERSE_QA_DEFAULT),
        "last_followup_save": {},
        "risk_profile": "平衡",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    for idx, code in enumerate(DEFAULT_CODES):
        st.session_state.setdefault(f"code_{idx}", code)
    for idx, amount in enumerate(DEFAULT_AMOUNTS):
        st.session_state.setdefault(f"amount_{idx}", amount)
    if st.session_state.get("followup_version") != FOLLOWUP_VERSION:
        st.session_state["followup_answers"] = []
        st.session_state["followup_version"] = FOLLOWUP_VERSION
    # 每个 session 只从本地文件读取一次，之后以 session_state 为准
    if not st.session_state.notes_loaded:
        try:
            st.session_state.notes = get_storage().load_notes()
        except Exception:  # noqa: BLE001
            st.session_state.notes = []
        st.session_state.notes_loaded = True


def css_vars() -> dict[str, str]:
    if st.session_state.dark_mode:
        return {
            "bg": "#1a1714",
            "bg_2": "#211d19",
            "surface": "#25211d",
            "surface_2": "#2c2823",
            "border": "#3a3530",
            "border_strong": "#514940",
            "text": "#ede5d8",
            "text_2": "#a89e8e",
            "text_3": "#6f675c",
            "accent": "#d18a73",
            "accent_soft": "#3a2923",
            "accent_2": "#7ea892",
            "accent_2_soft": "#26382f",
            "gold": "#d0b083",
            "gold_soft": "#3a3125",
            "up": "#e57878",
            "up_soft": "#432525",
            "down": "#6eb89c",
            "down_soft": "#213a30",
            "warn": "#d39a62",
            "warn_soft": "#3b2f21",
        }
    return {
        "bg": "#fbf7f2",
        "bg_2": "#f5efe6",
        "surface": "#ffffff",
        "surface_2": "#faf6ef",
        "border": "#e8dfd0",
        "border_strong": "#d4c6b0",
        "text": "#2a2520",
        "text_2": "#6b6357",
        "text_3": "#9a9085",
        "accent": "#7a3e2e",
        "accent_soft": "#f1e3db",
        "accent_2": "#3a5a4a",
        "accent_2_soft": "#e3ece7",
        "gold": "#b8956a",
        "gold_soft": "#f3e9d8",
        "up": "#c14545",
        "up_soft": "#f7e7e3",
        "down": "#2d7d5e",
        "down_soft": "#e2efe7",
        "warn": "#a05a25",
        "warn_soft": "#f5e6d2",
    }


def inject_css() -> None:
    v = css_vars()
    render_html(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Noto+Sans+SC:wght@400;500;600;700&family=Noto+Serif+SC:wght@500;600;700&display=swap');

        :root {{
            --bg: {v["bg"]};
            --bg-2: {v["bg_2"]};
            --surface: {v["surface"]};
            --surface-2: {v["surface_2"]};
            --border: {v["border"]};
            --border-strong: {v["border_strong"]};
            --text: {v["text"]};
            --text-2: {v["text_2"]};
            --text-3: {v["text_3"]};
            --accent: {v["accent"]};
            --accent-soft: {v["accent_soft"]};
            --accent-2: {v["accent_2"]};
            --accent-2-soft: {v["accent_2_soft"]};
            --gold: {v["gold"]};
            --gold-soft: {v["gold_soft"]};
            --up: {v["up"]};
            --up-soft: {v["up_soft"]};
            --down: {v["down"]};
            --down-soft: {v["down_soft"]};
            --warn: {v["warn"]};
            --warn-soft: {v["warn_soft"]};
            --font-display: "Noto Serif SC", "Source Han Serif SC", Georgia, serif;
            --font-body: "Noto Sans SC", "PingFang SC", system-ui, sans-serif;
            --font-num: "Inter", "Noto Sans SC", system-ui, sans-serif;
        }}

        html, body, [class*="css"], [data-testid="stAppViewContainer"] {{
            font-size: {st.session_state.font_size}px;
            font-family: var(--font-body);
            color: var(--text);
            background: var(--bg);
            font-feature-settings: "tnum" on, "lnum" on;
        }}
        [data-testid="stAppViewContainer"] > .main {{
            background: var(--bg);
        }}
        .main .block-container {{
            max-width: 960px;
            padding: 1.25rem 1.5rem 90px;
        }}
        header[data-testid="stHeader"], [data-testid="stToolbar"], #MainMenu, footer {{
            visibility: hidden;
            height: 0;
        }}
        h1, h2, h3 {{
            font-family: var(--font-display);
            color: var(--text);
            letter-spacing: -0.01em;
            line-height: 1.28;
        }}
        p, li, label, .stMarkdown {{
            color: var(--text);
            line-height: 1.7;
            text-wrap: pretty;
        }}
        a {{
            color: var(--accent);
        }}
        .stButton button, .stDownloadButton button, .stFormSubmitButton button {{
            min-height: 2.2rem;
            border-radius: 999px;
            border: 1px solid var(--border-strong);
            background: var(--surface);
            color: var(--text);
            font-weight: 600;
            font-size: 0.88rem;
            font-family: var(--font-body);
            box-shadow: none;
            transition: all 160ms ease;
        }}
        .stButton button:hover, .stDownloadButton button:hover, .stFormSubmitButton button:hover {{
            border-color: var(--accent);
            color: var(--accent);
            transform: translateY(-1px);
            box-shadow: 0 8px 18px rgba(78, 62, 48, 0.10);
        }}
        .stFormSubmitButton button {{
            min-height: 3.05rem;
            background: linear-gradient(135deg, #7b4937 0%, var(--accent) 58%, #a46a47 100%);
            color: #fff;
            border-color: var(--accent);
            font-size: 1rem;
            font-weight: 800;
            box-shadow: 0 14px 28px rgba(124, 73, 55, 0.20);
        }}
        .stFormSubmitButton button:hover {{
            color: #fff;
            background: linear-gradient(135deg, #6f4030 0%, var(--accent) 58%, #9c6140 100%);
            box-shadow: 0 16px 32px rgba(124, 73, 55, 0.25);
        }}
        .stButton button[kind="primary"] {{
            min-height: 3.05rem;
            background: linear-gradient(135deg, #7b4937 0%, var(--accent) 58%, #a46a47 100%);
            color: #fff;
            border-color: var(--accent);
            font-size: 1rem;
            font-weight: 800;
            box-shadow: 0 14px 28px rgba(124, 73, 55, 0.20);
        }}
        .stButton button[kind="primary"]:hover {{
            color: #fff;
            background: linear-gradient(135deg, #6f4030 0%, var(--accent) 58%, #9c6140 100%);
            box-shadow: 0 16px 32px rgba(124, 73, 55, 0.25);
        }}
        div[data-testid="stTextInput"] input,
        div[data-testid="stNumberInput"] input,
        div[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
        textarea {{
            background: var(--bg-2) !important;
            color: #2b211b !important;
            border: 1px solid var(--border) !important;
            border-radius: 14px !important;
            min-height: 3rem;
            font-size: 1rem !important;
        }}
        div[data-testid="stTextInput"] input::placeholder,
        div[data-testid="stNumberInput"] input::placeholder,
        textarea::placeholder {{
            color: #8a8178 !important;
            opacity: 1 !important;
        }}
        div[data-testid="stTextInput"] input,
        div[data-testid="stNumberInput"] input,
        textarea {{
            -webkit-text-fill-color: #2b211b !important;
        }}
        div[data-testid="stTextInput"] input:focus,
        div[data-testid="stNumberInput"] input:focus,
        textarea:focus {{
            border-color: var(--accent) !important;
            box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 15%, transparent) !important;
        }}
        div[data-testid="stRadio"] > label {{
            font-weight: 800;
            color: var(--text);
        }}
        div[data-testid="stRadio"] div[role="radiogroup"] {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.48rem;
        }}
        div[data-testid="stRadio"] div[role="radiogroup"] label {{
            min-height: 2.35rem;
            margin: 0 !important;
            padding: 0.35rem 0.68rem;
            border: 1px solid var(--border);
            border-radius: 999px;
            background: var(--surface);
            color: var(--text-2);
            transition: all 160ms ease;
        }}
        div[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) {{
            border-color: var(--accent);
            background: var(--accent-soft);
            color: var(--accent);
            box-shadow: 0 8px 18px rgba(78, 62, 48, 0.08);
        }}
        div[data-testid="stRadio"] div[role="radiogroup"] label:hover {{
            border-color: var(--accent);
        }}
        .risk-hint-grid {{
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 0.35rem;
            margin: 0.45rem 0 0.2rem;
        }}
        .risk-hint {{
            border: 1px solid var(--border);
            border-radius: 12px;
            background: color-mix(in srgb, var(--surface) 88%, var(--bg-2));
            padding: 0.42rem 0.48rem;
            color: var(--text-2);
            font-size: 0.72rem;
            line-height: 1.35;
        }}
        .risk-hint strong {{
            display: block;
            color: var(--text);
            font-size: 0.78rem;
            margin-bottom: 0.12rem;
        }}
        .risk-hint.active {{
            border-color: var(--accent);
            background: var(--accent-soft);
            color: var(--accent);
        }}
        .risk-hint.active strong {{
            color: var(--accent);
        }}
        [data-testid="stExpander"] {{
            border: 1px solid var(--border);
            border-radius: 14px;
            background: var(--surface);
            overflow: hidden;
        }}
        [data-testid="stExpander"] details summary {{
            color: var(--text);
            font-family: var(--font-display);
            font-weight: 600;
        }}
        div[data-testid="stMetric"] {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 1.1rem;
        }}
        div[data-testid="stMetricLabel"] p {{
            color: var(--text-2);
            font-size: 0.86rem;
        }}
        div[data-testid="stMetricValue"] {{
            color: var(--accent);
            font-family: var(--font-num);
            font-size: 1.55rem;
        }}
        [data-testid="stDataFrame"] {{
            border: 1px solid var(--border);
            border-radius: 14px;
            overflow: hidden;
        }}

        .site-header {{
            position: sticky;
            top: 0;
            z-index: 20;
            margin: -1.25rem -2rem 2rem;
            padding: 0.8rem 2rem;
            display: grid;
            grid-template-columns: 1fr auto 1fr;
            gap: 1rem;
            align-items: center;
            background: color-mix(in srgb, var(--bg) 92%, transparent);
            border-bottom: 1px solid var(--border);
            backdrop-filter: blur(12px);
        }}
        .brand {{
            display: flex;
            align-items: center;
            gap: 0.7rem;
        }}
        .brand-mark {{
            width: 40px;
            height: 40px;
            flex-shrink: 0;
            display: grid;
            place-items: center;
            filter: drop-shadow(0 2px 6px rgba(122,62,46,0.28));
        }}
        .brand-cn {{
            font-family: var(--font-display);
            font-weight: 700;
            font-size: 1.08rem;
            color: var(--text);
            line-height: 1.1;
            letter-spacing: 0.01em;
        }}
        .brand-en {{
            font-size: 0.68rem;
            color: var(--text-3);
            font-family: var(--font-num);
            line-height: 1.2;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }}
        .brand-badge {{
            display: inline-block;
            font-size: 0.55rem;
            font-family: var(--font-num);
            font-weight: 600;
            letter-spacing: 0.06em;
            color: var(--accent);
            background: var(--accent-soft);
            border-radius: 4px;
            padding: 1px 5px;
            margin-left: 5px;
            vertical-align: middle;
            line-height: 1.6;
        }}
        .site-nav {{
            display: flex;
            align-items: center;
            gap: 1.7rem;
            justify-content: center;
            color: var(--text-2);
            font-size: 0.92rem;
        }}
        .site-nav span:first-child {{
            color: var(--accent);
            border-bottom: 2px solid var(--accent);
            padding-bottom: 0.35rem;
        }}
        .family-chip {{
            justify-self: end;
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            border: 1px solid var(--border);
            border-radius: 999px;
            background: var(--surface);
            padding: 0.38rem 0.65rem 0.38rem 0.42rem;
            color: var(--text-2);
            font-size: 0.86rem;
            white-space: nowrap;
        }}
        .family-avatar {{
            width: 1.7rem;
            height: 1.7rem;
            border-radius: 999px;
            display: grid;
            place-items: center;
            color: var(--accent);
            background: var(--accent-soft);
            font-weight: 700;
        }}

        .settings-strip {{
            display: flex;
            justify-content: flex-end;
            align-items: center;
            gap: 0.65rem;
            margin: -0.8rem 0 1.2rem;
            color: var(--text-2);
            font-size: 0.85rem;
        }}
        .settings-strip .pill {{
            border: 1px solid var(--border);
            background: var(--surface);
            border-radius: 999px;
            padding: 0.28rem 0.65rem;
            color: var(--text-2);
        }}

        .hero-grid {{
            display: grid;
            grid-template-columns: 1.65fr 1fr;
            gap: 1.5rem;
            align-items: stretch;
            margin-bottom: 2.5rem;
        }}
        .card, .hero-card, .market-card, .guide-block, .list-shell, .stock-head, .verdict-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 14px;
            box-shadow: 0 14px 35px rgba(42, 37, 32, 0.04);
        }}
        .hero-card {{
            padding: 2.2rem;
        }}
        .eyebrow {{
            display: inline-flex;
            width: fit-content;
            border-radius: 999px;
            background: var(--accent-soft);
            color: var(--accent);
            padding: 0.42rem 0.8rem;
            font-size: 0.82rem;
            font-weight: 700;
        }}
        .hero-title {{
            margin: 0.6rem 0 0.65rem;
            font-family: var(--font-display);
            font-size: 1.5rem;
            font-weight: 600;
            line-height: 1.28;
            color: var(--text);
            letter-spacing: -0.01em;
        }}
        .hero-subtitle {{
            color: var(--text-2);
            max-width: 47rem;
            font-size: 1.02rem;
            margin-bottom: 1.5rem;
        }}
        .search-shell {{
            border: 1px solid var(--border);
            border-radius: 999px;
            background: var(--bg-2);
            padding: 0.45rem;
            margin: 0.25rem 0 1rem;
        }}
        .search-shell:focus-within {{
            border-color: var(--accent);
            background: var(--surface);
        }}
        .quick-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.55rem;
            align-items: center;
            color: var(--text-2);
            font-size: 0.9rem;
        }}
        .chip {{
            display: inline-flex;
            gap: 0.35rem;
            align-items: center;
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 0.4rem 0.75rem;
            color: var(--text);
            background: var(--surface);
            font-weight: 700;
        }}
        .chip small {{
            color: var(--text-3);
            font-family: var(--font-num);
            font-weight: 500;
        }}
        .market-card {{
            padding: 1.5rem;
        }}
        .market-title {{
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            margin-bottom: 0.65rem;
        }}
        .market-title h3 {{
            margin: 0;
            font-size: 1.2rem;
        }}
        .market-row {{
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            padding: 1rem 0;
            border-bottom: 1px dashed var(--border);
        }}
        .market-row:last-of-type {{
            border-bottom: 0;
        }}
        .market-name {{
            color: var(--text);
            font-weight: 700;
        }}
        .market-code, .muted {{
            color: var(--text-3);
            font-size: 0.84rem;
        }}
        .market-value {{
            font-family: var(--font-num);
            color: var(--text);
            font-weight: 700;
            text-align: right;
        }}
        .up {{ color: var(--up); }}
        .down {{ color: var(--down); }}
        .flat {{ color: var(--text-2); }}
        .delay {{
            display: flex;
            align-items: center;
            gap: 0.45rem;
            color: var(--text-3);
            font-size: 0.84rem;
            padding-top: 0.6rem;
        }}
        .delay-dot {{
            width: 0.45rem;
            height: 0.45rem;
            border-radius: 999px;
            background: var(--accent-2);
        }}

        .block {{
            margin: 2.8rem 0;
        }}
        .block-head {{
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            align-items: end;
            margin-bottom: 1.1rem;
        }}
        .block-title {{
            font-family: var(--font-display);
            font-size: 1.55rem;
            font-weight: 600;
            color: var(--text);
            margin: 0;
        }}
        .block-subtitle {{
            color: var(--text-2);
            margin: 0.25rem 0 0;
        }}
        .ghost-btn {{
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 0.5rem 0.85rem;
            color: var(--accent);
            background: var(--surface);
            font-weight: 700;
            white-space: nowrap;
        }}
        .watch-grid, .metric-grid, .risk-grid, .news-grid {{
            display: grid;
            gap: 1.5rem;
        }}
        .watch-grid {{
            grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
        }}
        .watch-card {{
            border: 1px solid var(--border);
            border-radius: 14px;
            background: var(--surface);
            padding: 0.9rem 1.1rem;
            transition: all 160ms ease;
        }}
        .watch-card:hover {{
            border-color: var(--accent);
            transform: translateY(-1px);
        }}
        .watch-top, .price-line, .risk-card-head, .note-head {{
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            align-items: start;
        }}
        .watch-name {{
            font-family: var(--font-display);
            font-size: 1.2rem;
            font-weight: 700;
            color: var(--text);
        }}
        .owner-pill, .verdict-pill, .tag {{
            display: inline-flex;
            align-items: center;
            width: fit-content;
            border-radius: 999px;
            font-size: 0.78rem;
            padding: 0.28rem 0.6rem;
            font-weight: 700;
            white-space: nowrap;
        }}
        .owner-pill {{
            color: var(--gold);
            background: var(--gold-soft);
        }}
        .price-line {{
            margin: 1.2rem 0 0.9rem;
            align-items: baseline;
        }}
        .big-number {{
            font-family: var(--font-num);
            font-size: 1.65rem;
            font-weight: 700;
            color: var(--text);
        }}
        .change-text {{
            font-family: var(--font-num);
            font-weight: 700;
        }}
        .watch-link {{
            border-top: 1px dashed var(--border);
            padding-top: 0.9rem;
            color: var(--accent);
            font-weight: 700;
            font-size: 0.9rem;
        }}
        .list-shell {{
            overflow: hidden;
        }}
        .recent-row {{
            display: grid;
            grid-template-columns: 1fr auto auto;
            gap: 1rem;
            align-items: center;
            padding: 1rem 1.25rem;
            border-bottom: 1px solid var(--border);
        }}
        .recent-row:last-child {{
            border-bottom: 0;
        }}
        .recent-row:hover {{
            background: var(--surface-2);
        }}
        .verdict-pill {{
            color: var(--accent-2);
            background: var(--accent-2-soft);
        }}
        .guide-block {{
            background: var(--surface-2);
            padding: 1.25rem 1.35rem;
        }}
        .compact-guide {{
            margin: 1.1rem 0 1.35rem;
            background: linear-gradient(180deg, color-mix(in srgb, var(--surface) 86%, var(--accent-soft)), var(--surface));
        }}
        .compact-guide .block-head {{
            margin-bottom: 0.65rem;
        }}
        .compact-guide .block-title {{
            font-size: 1.08rem;
        }}
        .compact-guide .block-subtitle {{
            font-size: 0.9rem;
        }}
        .guide-list {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 0.75rem;
        }}
        .guide-step {{
            display: grid;
            grid-template-columns: auto 1fr;
            gap: 0.65rem;
            align-items: start;
        }}
        .step-num {{
            width: 1.55rem;
            height: 1.55rem;
            border-radius: 999px;
            border: 1px solid var(--border-strong);
            background: var(--surface);
            color: var(--accent);
            display: grid;
            place-items: center;
            font-family: var(--font-num);
            font-weight: 800;
            font-size: 0.86rem;
        }}
        .step-title {{
            color: var(--text);
            font-weight: 800;
            margin-bottom: 0.08rem;
            font-size: 0.98rem;
        }}
        .guide-step .muted {{
            font-size: 0.88rem;
            line-height: 1.55;
        }}
        .guide-foot, .page-foot {{
            margin-top: 0.85rem;
            padding-top: 0.75rem;
            border-top: 1px dashed var(--border);
            color: var(--text-2);
            font-size: 0.82rem;
        }}

        .breadcrumb {{
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            align-items: center;
            color: var(--text-2);
            font-size: 0.88rem;
            margin-bottom: 1.1rem;
        }}
        .crumb-link {{
            color: var(--accent);
            font-weight: 700;
        }}
        .stock-head {{
            display: grid;
            grid-template-columns: 1.5fr 1fr;
            gap: 1.6rem;
            padding: 2.2rem;
            margin-bottom: 2.4rem;
        }}
        .tag-row {{
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
        }}
        .tag-code {{
            background: var(--accent-soft);
            color: var(--accent);
        }}
        .tag-exchange {{
            background: var(--accent-2-soft);
            color: var(--accent-2);
        }}
        .tag-industry {{
            background: var(--bg-2);
            color: var(--text-2);
        }}
        .stock-title {{
            margin: 0.6rem 0 0.2rem;
            font-family: var(--font-display);
            font-size: 1.7rem;
            font-weight: 600;
        }}
        .basic-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1rem;
            border-top: 1px solid var(--border);
            margin-top: 1.4rem;
            padding-top: 1.2rem;
        }}
        .kv dt {{
            color: var(--text-2);
            font-size: 0.84rem;
            margin-bottom: 0.28rem;
        }}
        .kv dd {{
            margin: 0;
            color: var(--text);
            font-family: var(--font-num);
            font-weight: 700;
            font-size: 1.35rem;
        }}
        .spark-card {{
            height: 100%;
            min-height: 245px;
            border-radius: 14px;
            background: var(--bg-2);
            padding: 1.2rem;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }}
        .spark-svg {{
            width: 100%;
            height: 120px;
            margin: 1rem 0;
        }}

        .verdict-card {{
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 1.5rem;
            align-items: center;
            padding: 1.7rem;
            background: linear-gradient(180deg, var(--accent-soft), var(--surface) 70%);
            margin-bottom: 1rem;
        }}
        .kicker {{
            color: var(--accent);
            font-size: 0.75rem;
            font-weight: 800;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }}
        .verdict-title {{
            font-family: var(--font-display);
            font-size: 1.85rem;
            font-weight: 700;
            margin: 0.3rem 0;
        }}
        .risk-signal {{
            display: flex;
            gap: 1rem;
            align-items: center;
        }}
        .risk-light {{
            width: 3.25rem;
            height: 3.25rem;
            border-radius: 999px;
            flex: 0 0 auto;
            border: 4px solid rgba(255, 255, 255, 0.72);
            box-shadow: 0 12px 30px rgba(42, 37, 32, 0.14), inset 0 0 0 1px rgba(0, 0, 0, 0.06);
        }}
        .risk-green .risk-light {{
            background: radial-gradient(circle at 35% 30%, #eefaf1 0, #4e9f68 48%, #247a45 100%);
        }}
        .risk-yellow .risk-light {{
            background: radial-gradient(circle at 35% 30%, #fff8dc 0, #dfb844 52%, #aa8422 100%);
        }}
        .risk-red .risk-light {{
            background: radial-gradient(circle at 35% 30%, #ffe8e3 0, #c85a4a 52%, #933123 100%);
        }}
        .risk-neutral .risk-light {{
            background: radial-gradient(circle at 35% 30%, #f3f1ee 0, #9b9288 54%, #6f665e 100%);
        }}
        .risk-status {{
            font-family: var(--font-display);
            font-size: 1.8rem;
            font-weight: 700;
            margin: 0.22rem 0;
        }}
        .risk-score-line {{
            color: var(--text-2);
            font-size: 0.92rem;
        }}
        .score-dial {{
            width: 104px;
            text-align: center;
        }}
        .score-caption {{
            color: var(--text-2);
            font-size: 0.84rem;
            margin-top: 0.2rem;
        }}
        .ai-detail-note {{
            border: 1px solid var(--border);
            border-radius: 14px;
            background: var(--surface);
            padding: 1rem 1.2rem;
            margin: 0.75rem 0;
        }}
        .tone-accent {{
            border-left: 3px solid var(--accent);
        }}
        .tone-warn {{
            border-left: 3px solid var(--warn);
        }}
        .tone-neutral {{
            border-left: 3px solid var(--accent-2);
        }}
        .bullet-list {{
            margin: 0.4rem 0 0;
            padding-left: 1.2rem;
        }}
        .bullet-list li::marker {{
            color: var(--accent);
        }}
        .metric-grid {{
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        }}
        .metric-card {{
            border: 1px solid var(--border);
            border-radius: 14px;
            background: var(--surface);
            padding: 1.6rem;
        }}
        .metric-label {{
            color: var(--text-2);
            font-size: 0.92rem;
        }}
        .metric-value {{
            color: var(--text);
            font-family: var(--font-num);
            font-size: 1.85rem;
            font-weight: 700;
            margin: 0.45rem 0;
        }}
        /* ── 两列紧凑指标网格 ─────────────────────────────────── */
        .metric-grid-2 {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 0.65rem;
        }}
        .metric-card-sm {{
            border: 1px solid var(--border);
            border-radius: 12px;
            background: var(--surface);
            padding: 0.8rem 0.9rem 0.75rem;
            min-width: 0;
        }}
        .metric-value-sm {{
            color: var(--text);
            font-family: var(--font-num);
            font-size: 1.25rem;
            font-weight: 700;
            margin: 0.2rem 0 0.12rem;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .metric-note-sm {{
            color: var(--text-3);
            font-size: 0.72rem;
            line-height: 1.3;
        }}
        .metric-note {{
            color: var(--text-3);
            font-size: 0.85rem;
        }}
        .risk-grid {{
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        }}
        .risk-card-new {{
            border: 1px solid var(--border);
            border-left-width: 4px;
            border-radius: 14px;
            background: var(--surface);
            padding: 1.25rem;
        }}
        .r-hi {{
            border-left-color: var(--up);
        }}
        .r-mid {{
            border-left-color: var(--gold);
        }}
        .r-lo {{
            border-left-color: var(--accent-2);
        }}
        .risk-title-pill {{
            border-radius: 999px;
            background: var(--bg-2);
            color: var(--text);
            padding: 0.28rem 0.55rem;
            font-weight: 700;
            font-size: 0.82rem;
        }}
        .news-grid {{
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
        }}
        .news-card, .note-card {{
            border: 1px solid var(--border);
            border-radius: 14px;
            background: var(--surface);
            padding: 1.1rem;
        }}
        .note-avatar {{
            width: 2rem;
            height: 2rem;
            border-radius: 999px;
            display: grid;
            place-items: center;
            color: var(--accent);
            background: var(--accent-soft);
            font-weight: 800;
        }}
        .allocation-bar {{
            height: 0.8rem;
            border-radius: 999px;
            overflow: hidden;
            background: var(--bg-2);
            display: flex;
            border: 1px solid var(--border);
        }}
        .allocation-cash {{
            background: var(--accent-2);
        }}
        .allocation-stock {{
            background: var(--gold);
        }}
        .page-foot {{
            text-align: center;
            border-top-style: solid;
        }}

        @media (max-width: 1000px) {{
            .site-header {{
                grid-template-columns: 1fr auto;
            }}
            .site-nav {{
                display: none;
            }}
            .hero-grid, .stock-head {{
                grid-template-columns: 1fr;
            }}
            .basic-grid {{
                grid-template-columns: repeat(2, 1fr);
            }}
            .guide-list {{
                grid-template-columns: 1fr;
            }}
        }}
        @media (max-width: 640px) {{
            .main .block-container {{
                padding: 1rem 0.85rem 90px;
            }}
            .site-header {{
                margin-left: -0.85rem;
                margin-right: -0.85rem;
                padding-left: 0.85rem;
                padding-right: 0.85rem;
            }}
            .family-chip {{
                display: none;
            }}
            .hero-card, .stock-head {{
                padding: 1.45rem;
            }}
            .guide-block {{
                padding: 1.05rem;
            }}
            .guide-list {{
                gap: 0.85rem;
            }}
            .risk-hint-grid {{
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }}
            .hero-title, .stock-title {{
                font-size: 1.25rem;
            }}
            .block-head, .breadcrumb, .watch-top, .price-line {{
                align-items: start;
                flex-direction: column;
            }}
            .basic-grid {{
                grid-template-columns: 1fr;
            }}
            .recent-row {{
                grid-template-columns: 1fr auto;
            }}
            .recent-row .recent-time {{
                display: none;
            }}
            .verdict-card {{
                grid-template-columns: 1fr;
            }}
        }}
        /* ── 体检进度：步骤转圈动画 ──────────────────────────── */
        @keyframes fi-spin {{
            to {{ transform: rotate(360deg); }}
        }}
        .fi-spinner {{
            display: inline-block;
            width: 0.85em; height: 0.85em;
            border: 2px solid rgba(122,62,46,0.18);
            border-top-color: #7a3e2e;
            border-radius: 50%;
            animation: fi-spin 0.75s linear infinite;
            vertical-align: middle;
            flex-shrink: 0;
        }}
        /* ── 持仓删除按钮：手机端紧凑化 ─────────────────────── */
        [data-testid="stExpander"] [data-testid="column"]:last-child button {{
            padding: 0 0.45rem !important;
            min-height: 1.85rem !important;
            height: 1.85rem !important;
            font-size: 0.78rem !important;
            line-height: 1 !important;
            margin-top: 1.65rem !important;
            opacity: 0.55;
            background: transparent !important;
            border-color: var(--border) !important;
            color: var(--text-2) !important;
            border-radius: 6px !important;
            box-shadow: none !important;
        }}
        </style>
        """
    )


def html_escape(value: Any) -> str:
    return escape(str(value if value is not None else ""))


def _hesc(d: dict, key: str, default: str = "") -> str:
    """html_escape a single key from a dict, with a safe default."""
    return html_escape(str(d.get(key, default) or default))


def site_header() -> None:
    render_html(
        f"""
        <div class="brand" style="padding: 0.2rem 0 0.05rem;">
            <div class="brand-mark">
                <svg width="40" height="40" viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <defs>
                        <radialGradient id="fi-bg" cx="50%" cy="40%" r="60%">
                            <stop offset="0%" stop-color="#fff8f5"/>
                            <stop offset="100%" stop-color="#edddd6"/>
                        </radialGradient>
                    </defs>
                    <circle cx="20" cy="20" r="18.5" fill="url(#fi-bg)" stroke="#7a3e2e" stroke-width="1.5"/>
                    <path d="M5 20 L12 20 L13 22 L15 10 L17 28 L19 19 L21 20 L35 20"
                          stroke="#7a3e2e" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </div>
            <div>
                <div class="brand-cn">{html_escape(APP_TITLE)}<span class="brand-badge">AI</span></div>
                <div class="brand-en">{html_escape(APP_SUBTITLE)}</div>
            </div>
        </div>
        """
    )


def display_settings() -> None:
    c1, c2, c3 = st.columns(3)
    if c1.button("A-", use_container_width=True, help="字号减小", key="toolbar_font_minus"):
        st.session_state.font_size = max(14, int(st.session_state.font_size) - 1)
        st.rerun()
    if c2.button("A+", use_container_width=True, help="字号增大", key="toolbar_font_plus"):
        st.session_state.font_size = min(22, int(st.session_state.font_size) + 1)
        st.rerun()
    label = "浅色" if st.session_state.dark_mode else "暗色"
    if c3.button(label, use_container_width=True, help="切换深色/浅色", key="toolbar_theme_toggle"):
        st.session_state.dark_mode = not st.session_state.dark_mode
        st.rerun()


def top_toolbar() -> None:
    """统一顶部导航入口：主页 / 历史 / 显示设置。"""
    has_analysis = "analysis" in st.session_state
    left, spacer, hist_col, display_col = st.columns([1.25, 4.2, 0.8, 0.8])
    with left:
        if has_analysis:
            if st.button("← 首页", key="toolbar_home", use_container_width=True):
                st.session_state.pop("analysis", None)
                st.session_state.pop("stocks", None)
                st.session_state.pop("fetch_warnings", None)
                st.session_state.pop("agent_result", None)
                st.session_state["active_view"] = "analysis"
                st.rerun()
    with hist_col:
        if has_analysis:
            if st.button("历史", key="toolbar_history", use_container_width=True, help="历史体检记录"):
                st.session_state["active_view"] = "history"
                st.rerun()
    with display_col:
        with st.popover("Aa", use_container_width=True, help="显示设置"):
            st.caption("显示设置")
            display_settings()



def signed_change(value: float) -> str:
    arrow = "▲" if value >= 0 else "▼"
    return f"{arrow} {abs(value):.2f}%"


def change_class(value: float | None) -> str:
    if value is None:
        return "flat"
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"


def market_aside() -> None:
    rows = []
    for item in MARKET_INDEXES:
        cls = change_class(float(item["change"]))
        rows.append(
            f"""
            <div class="market-row">
                <div>
                    <div class="market-name">{html_escape(item["name"])}</div>
                    <div class="market-code">{html_escape(item["code"])}</div>
                </div>
                <div>
                    <div class="market-value">{html_escape(item["value"])}</div>
                    <div class="change-text {cls}">{signed_change(float(item["change"]))}</div>
                </div>
            </div>
            """
        )
    render_html(
        f"""
        <aside class="market-card">
            <div class="market-title">
                <h3>今日大盘</h3>
                <span class="muted">A 股</span>
            </div>
            {''.join(rows)}
            <div class="delay"><span class="delay-dot"></span>行情延迟 15 分钟 · 仅供参考</div>
        </aside>
        """
    )


def set_first_code(code: str) -> None:
    st.session_state["pending_code"] = normalize_code(code)


def risk_profile_hint_grid(selected: str) -> str:
    items = []
    for name in RISK_PROFILE_OPTIONS:
        cls = "risk-hint active" if name == selected else "risk-hint"
        items.append(
            f"""
            <div class="{cls}">
                <strong>{html_escape(name)}</strong>
                {html_escape(RISK_PROFILE_SHORT_HINTS.get(name, ""))}
            </div>
            """
        )
    return f'<div class="risk-hint-grid">{"".join(items)}</div>'


def home_hero() -> None:
    render_html(
        """
        <div class="hero-card" style="padding: 1.3rem 1.3rem 0.6rem; margin-bottom: 0.5rem;">
            <div class="eyebrow">家庭持仓风险读懂工具</div>
            <h1 class="hero-title">输入持仓，看清风险。</h1>
            <p class="hero-subtitle">帮助家人看清这只标的的风险、数据是否完整，以及是否需要继续观察。不预测涨跌，不构成买卖建议。</p>
        </div>
        """
    )
    portfolio_form()


def portfolio_form() -> None:
    pending_code = st.session_state.pop("pending_code", "")
    if pending_code:
        st.session_state["code_0"] = pending_code
        if float(st.session_state.get("amount_0", 0) or 0) <= 0:
            st.session_state["amount_0"] = 20000.0

    st.markdown('<div class="search-shell">', unsafe_allow_html=True)
    code_col, amount_col = st.columns([1.4, 1])
    with code_col:
        first_code = st.text_input(
            "股票/基金代码",
            key="code_0",
            placeholder="例如：600519、贵州茅台、招商银行",
        )
    with amount_col:
        first_amount = st.number_input(
            "持仓金额（元）",
            min_value=0.0,
            step=1000.0,
            key="amount_0",
        )

    # Handle row deletion before widgets render (must precede the expander)
    if "pending_delete_row" in st.session_state:
        _del = st.session_state.pop("pending_delete_row")
        for _j in range(_del, st.session_state.holding_rows - 1):
            st.session_state[f"code_{_j}"] = st.session_state.get(f"code_{_j + 1}", "")
            st.session_state[f"amount_{_j}"] = st.session_state.get(f"amount_{_j + 1}", 0.0)
        st.session_state.holding_rows = max(1, st.session_state.holding_rows - 1)

    with st.expander("＋ 添加更多持仓（可选）", expanded=False):
        st.markdown('<p class="muted">填写第 2 只及之后的持仓；不填也可以直接体检。</p>', unsafe_allow_html=True)
        for index in range(1, st.session_state.holding_rows):
            cols = st.columns([1.4, 1, 0.25])
            cols[0].text_input(
                f"第 {index + 1} 只代码",
                key=f"code_{index}",
                placeholder="例如 000001",
            )
            cols[1].number_input(
                f"第 {index + 1} 只金额（元）",
                min_value=0.0,
                step=1000.0,
                key=f"amount_{index}",
            )
            if cols[2].button("×", key=f"del_row_{index}", help="删除这条持仓"):
                st.session_state.pending_delete_row = index
                st.rerun()
        if st.button("＋ 继续添加一只", use_container_width=True, key="add_holding_row"):
            st.session_state.holding_rows += 1
            st.rerun()

    cash = st.number_input("家庭可用于投资的现金金额（元）", min_value=0.0, value=50000.0, step=1000.0)
    current_risk = str(st.session_state.get("risk_profile", "平衡") or "平衡")
    if current_risk not in RISK_PROFILE_OPTIONS:
        current_risk = "平衡"
        st.session_state["risk_profile"] = current_risk
    risk_profile = current_risk
    st.markdown('<p style="margin:.6rem 0 .3rem;font-size:.9rem;font-weight:600;">家庭风险承受能力</p>', unsafe_allow_html=True)
    _rc1 = st.columns(3)
    _rc2 = st.columns([1, 1, 2])
    for _i, _n in enumerate(RISK_PROFILE_OPTIONS[:3]):
        with _rc1[_i]:
            if st.button(_n, key=f"risk_btn_{_n}", use_container_width=True,
                         type="primary" if _n == current_risk else "secondary"):
                st.session_state["risk_profile"] = _n
                st.rerun()
    for _i, _n in enumerate(RISK_PROFILE_OPTIONS[3:]):
        with _rc2[_i]:
            if st.button(_n, key=f"risk_btn_{_n}", use_container_width=True,
                         type="primary" if _n == current_risk else "secondary"):
                st.session_state["risk_profile"] = _n
                st.rerun()
    st.caption(f"{current_risk}：{RISK_PROFILE_HINTS.get(current_risk, '')}")

    submitted = st.button("开始一键智能体检", type="primary", use_container_width=True)

    if submitted:
        raw_rows: list[dict[str, float | str]] = [{"code": first_code, "amount": first_amount}]
        for idx in range(1, st.session_state.holding_rows):
            raw_rows.append(
                {
                    "code": st.session_state.get(f"code_{idx}", ""),
                    "amount": st.session_state.get(f"amount_{idx}", 0.0),
                }
            )
        run_analysis(cash, risk_profile, raw_rows)
    st.markdown("</div>", unsafe_allow_html=True)


def clean_holdings(raw_rows: list[dict[str, float | str]]) -> list[dict[str, float | str]]:
    holdings: list[dict[str, float | str]] = []
    for row in raw_rows:
        code = normalize_code(str(row.get("code", "")))
        amount = float(row.get("amount", 0) or 0)
        if code and amount > 0:
            holdings.append({"code": code, "amount": amount})
    return holdings


def loading_card(code: str) -> None:
    render_html(
        f"""
        <div class="card" style="padding: 2.2rem; margin: 1rem 0;">
            <div class="kicker">Generating report</div>
            <h3 style="margin: .35rem 0;">正在生成 {html_escape(code)} 的分析报告…</h3>
            <p class="muted">✓ 获取公司基础信息<br>✓ 拉取最近财报数据<br>○ AI 综合分析中<br>○ 整理风险提示</p>
        </div>
        """
    )


AGENT_PROGRESS_STEPS = [
    "检查输入是否完整",
    "读取行情和财务缓存",
    "计算持仓比例和现金比例",
    "识别集中风险和数据缺失",
    "组装 agent_context",
    "调用 DeepSeek 生成 AI 风险说明",
    "保存历史记录到 Supabase",
    "准备智能追问建议",
    "完成体检",
]

# 对用户展示的友好文案（与 AGENT_PROGRESS_STEPS 一一对应）
_STEP_LABELS = [
    "检查持仓输入是否完整",
    "读取行情和财务数据",
    "计算持仓比例和现金比例",
    "识别集中风险和数据缺失",
    "整理本次体检数据",
    "AI 正在生成风险说明（需几秒）",
    "保存本次记录",
    "准备追问建议",
    "体检完成 ✓",
]


def render_agent_progress(
    card_placeholder: Any,
    detail_placeholder: Any,
    current_step: str,
    percent_value: int,
) -> None:
    percent_value = max(0, min(100, int(percent_value)))

    # ── 顶部进度卡（极简）──────────────────────────────────────
    with card_placeholder.container():
        st.markdown("**智能体检进行中…**")
        st.progress(percent_value)

    # ── 步骤列表：按进度逐条揭示 ───────────────────────────────
    try:
        current_index = AGENT_PROGRESS_STEPS.index(current_step)
    except ValueError:
        current_index = 0

    done_all = percent_value >= 100
    rows_html = ""
    for idx in range(current_index + 1):          # 只显示已到达的步骤
        label = _STEP_LABELS[idx] if idx < len(_STEP_LABELS) else AGENT_PROGRESS_STEPS[idx]
        if idx < current_index or done_all:
            # 已完成：细小勾 + 灰色文字
            rows_html += (
                f'<div style="display:flex;align-items:center;gap:0.55rem;padding:0.25rem 0;">'
                f'<span style="color:#7a3e2e;font-size:0.78rem;width:1em;text-align:center;flex-shrink:0;">✓</span>'
                f'<span style="font-size:0.82rem;color:var(--text-3);">{html_escape(label)}</span>'
                f'</div>'
            )
        else:
            # 进行中：转圈 + 正常色粗体
            rows_html += (
                f'<div style="display:flex;align-items:center;gap:0.55rem;padding:0.28rem 0;">'
                f'<span class="fi-spinner"></span>'
                f'<span style="font-size:0.87rem;color:var(--text);font-weight:600;">{html_escape(label)}</span>'
                f'</div>'
            )

    with detail_placeholder.container():
        render_html(
            f'<div style="padding:0.1rem 0 0.3rem;">{rows_html}</div>'
        )


def _safe_error_text(value: Any) -> str:
    text = str(value or "")
    for secret_name in ("DEEPSEEK_API_KEY", "SUPABASE_KEY", "SUPABASE_URL"):
        secret_value = ""
        try:
            secret_value = str(st.secrets.get(secret_name, "")).strip()
        except Exception:  # noqa: BLE001
            secret_value = ""
        env_value = os.getenv(secret_name, "").strip()
        for raw in (secret_value, env_value):
            if raw:
                text = text.replace(raw, "***")
    return text[:800]


def _build_agent_error_info(exc: Exception) -> dict[str, Any]:
    diagnostics = get_cache_diagnostics()
    return {
        "错误类型": type(exc).__name__,
        "错误信息": _safe_error_text(exc),
        "当前工作目录": diagnostics.get("cwd", os.getcwd()),
        "stock_metrics.csv 检查路径": diagnostics.get("checked_paths", []),
        "已找到缓存文件": diagnostics.get("found_path", "") or "未找到",
    }


def render_error_debug(error_info: dict[str, Any] | None) -> None:
    if not error_info:
        return
    with st.expander("开发者信息 / 调试详情", expanded=False):
        st.write(f"- 错误类型：{error_info.get('错误类型', '')}")
        st.write(f"- 错误信息：{error_info.get('错误信息', '')}")
        st.write(f"- 当前工作目录：{error_info.get('当前工作目录', '')}")
        st.write("- stock_metrics.csv 检查过的路径：")
        for path in error_info.get("stock_metrics.csv 检查路径", []) or []:
            st.write(f"  - {path}")
        st.write(f"- 已找到缓存文件：{error_info.get('已找到缓存文件', '')}")


def run_analysis(cash: float, risk_profile: str, raw_rows: list[dict[str, float | str]]) -> None:
    holdings = clean_holdings(raw_rows)
    if not holdings:
        st.error("请至少填写一只持仓，并填写大于 0 的持仓金额。")
        st.stop()

    try:
        progress_card = st.empty()
        progress_detail = st.empty()
        render_agent_progress(progress_card, progress_detail, "检查输入是否完整", 0)

        def update_progress(step: str, percent_value: int) -> None:
            render_agent_progress(progress_card, progress_detail, step, percent_value)

        agent_result = run_family_risk_agent(
            holdings=holdings,
            family_cash=cash,
            risk_preference=risk_profile,
            user_goal="检查家庭持仓风险",
            reverse_qa=_normalize_reverse_qa(st.session_state.get("reverse_qa")),
            progress_callback=update_progress,
        )
        if agent_result.get("report_source") == "local_fallback":
            st.info("DeepSeek 暂时不可用，已使用本地规则兜底生成。")
        storage_status = agent_result.get("storage_status", {})
        if agent_result.get("saved_history") and storage_status.get("backend") == "local_csv":
            st.info("云端保存失败，已使用本地兜底。")
        render_agent_progress(progress_card, progress_detail, "完成体检", 100)
        if not agent_result.get("success"):
            for warning in agent_result.get("warnings", []):
                st.warning(warning)
            st.error("智能体检没有完成，请检查持仓代码和金额。")
            st.stop()

        analysis = agent_result["analysis"]
        stocks = agent_result["stocks"]
        st.session_state["analysis"] = analysis
        st.session_state["stocks"] = stocks
        st.session_state["holdings"] = holdings
        st.session_state["fetch_warnings"] = agent_result.get("warnings", [])
        st.session_state["agent_result"] = agent_result
        st.session_state.pop("ai_report", None)
        st.session_state.pop("ai_report_failed", None)
        st.session_state.pop("followup_answers", None)
        st.session_state.pop("followup_questions", None)  # 新一次体检，重新随机生成问题
        st.session_state.pop("last_agent_error", None)
        st.session_state["report_mode"] = DEFAULT_REPORT_MODE
        st.session_state["active_view"] = "analysis"
        st.rerun()
    except Exception as exc:  # noqa: BLE001
        error_info = _build_agent_error_info(exc)
        st.session_state["last_agent_error"] = error_info
        st.error("体检时遇到问题，但页面没有崩。请稍后重试，或检查 stock_metrics.csv 是否存在。")
        render_error_debug(error_info)
        st.stop()


def watchlist_block() -> None:
    cards = []
    for item in WATCH_ITEMS:
        cls = change_class(float(item["change"]))
        cards.append(
            f"""
            <article class="watch-card">
                <div class="watch-top">
                    <div>
                        <div class="watch-name">{html_escape(item["name"])}</div>
                        <div class="muted">{html_escape(item["code"])} · {html_escape(item["industry"])}</div>
                    </div>
                    <div class="owner-pill">{html_escape(item["owner"])}</div>
                </div>
                <div class="price-line">
                    <div class="big-number">{html_escape(item["price"])}</div>
                    <div class="change-text {cls}">{signed_change(float(item["change"]))}</div>
                </div>
            </article>
            """
        )
    render_html(
        f"""
        <section class="block">
            <div class="block-head">
                <div>
                    <h2 class="block-title">我的关注列表</h2>
                    <p class="block-subtitle">常看的公司放在一起，快速触发分析。接入云数据库后可多人共享。</p>
                </div>
                <div class="ghost-btn">＋ 添加关注</div>
            </div>
            <div class="watch-grid">{''.join(cards)}</div>
        </section>
        """
    )
    cols = st.columns(len(WATCH_ITEMS))
    for idx, item in enumerate(WATCH_ITEMS):
        if cols[idx].button(f"分析 {item['name']}", key=f"watch_{item['code']}", use_container_width=True):
            set_first_code(item["code"])
            st.rerun()


def recent_block() -> None:
    rows = []
    for item in RECENT_ITEMS:
        rows.append(
            f"""
            <div class="recent-row">
                <div>
                    <strong>{html_escape(item["name"])}</strong>
                    <div class="muted">{html_escape(item["code"])}</div>
                </div>
                <div class="muted recent-time">{html_escape(item["time"])}</div>
                <div><span class="verdict-pill">{html_escape(item["verdict"])}</span> <span class="muted">→</span></div>
            </div>
            """
        )
    render_html(
        f"""
        <section class="block">
            <div class="block-head">
                <div>
                    <h2 class="block-title">最近分析过的股票</h2>
                    <p class="block-subtitle">保留最近看过的公司，方便家人继续接着聊。</p>
                </div>
            </div>
            <div class="list-shell">{''.join(rows)}</div>
        </section>
        """
    )


def guide_block() -> None:
    render_html(
        f"""
        <section class="block guide-block compact-guide">
            <div class="block-head">
                <div>
                    <h2 class="block-title">Agent 怎么体检</h2>
                    <p class="block-subtitle">填持仓，看风险，再追问。</p>
                </div>
            </div>
            <div class="guide-list">
                <div class="guide-step">
                    <div class="step-num">1</div>
                    <div><div class="step-title">填信息</div><div class="muted">输入代码、金额、现金和风险偏好。</div></div>
                </div>
                <div class="guide-step">
                    <div class="step-num">2</div>
                    <div><div class="step-title">看结论</div><div class="muted">先看风险灯、评分、现金和集中度。</div></div>
                </div>
                <div class="guide-step">
                    <div class="step-num">3</div>
                    <div><div class="step-title">继续问</div><div class="muted">用 AI 追问和家庭观察，把分歧聊清楚。</div></div>
                </div>
            </div>
            <div class="guide-foot">{HOME_DISCLAIMER}</div>
        </section>
        """
    )


def cache_tools() -> None:
    with st.expander("高级选项：数据缓存工具", expanded=False):
        try:
            summary = get_cache_summary()
            st.info(summary.get("message", "缓存状态未知"))
        except Exception:  # noqa: BLE001
            summary = {"count": 0, "latest_update": "未知", "finance_count": 0}
            st.info("缓存状态暂时无法读取，不影响风险体检。")
        st.caption(
            f"当前本地缓存约 {summary.get('count', 0)} 只标的，其中 {summary.get('finance_count', 0)} 只有财务数据；"
            f"最近更新时间：{summary.get('latest_update', '未知')}。"
        )
        st.caption("页面默认读取 stock_metrics.csv，本地和云端都更稳定。下面的按钮会尝试联网更新，接口可能失败。")
        cache_col1, cache_col2 = st.columns(2)
        if cache_col1.button("更新全部 A 股行情缓存", use_container_width=True):
            with st.spinner("正在拉取全部 A 股行情，可能需要几十秒..."):
                update_summary, messages = refresh_market_cache()
            for message in messages:
                st.info(message)
            st.success(f"缓存现有 {update_summary.get('count', 0)} 只标的。")

        current_input_codes = []
        for idx in range(st.session_state.holding_rows):
            normalized_code = normalize_code(str(st.session_state.get(f"code_{idx}", "")))
            if normalized_code:
                current_input_codes.append(normalized_code)

        if cache_col2.button("手动更新当前持仓数据", use_container_width=True):
            with st.spinner("正在尝试更新当前填写代码的行情数据..."):
                update_summary, messages = refresh_current_holdings_cache(current_input_codes)
            for message in messages:
                st.info(message)
            st.success(
                f"缓存现有 {update_summary.get('count', 0)} 只标的，"
                f"{update_summary.get('finance_count', 0)} 只有财务数据。"
            )


def home_page() -> None:
    home_hero()
    guide_block()
    st.divider()
    cache_tools()
    with st.expander("开发中功能（暂未接入实时数据 / 云数据库，后续开放）", expanded=False):
        st.info("以下功能正在开发中，当前展示为静态演示数据，不代表真实行情或真实账户。")
        st.markdown("#### 今日大盘")
        market_aside()
        st.markdown("---")
        watchlist_block()
        st.markdown("---")
        recent_block()


def to_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
    except Exception:
        if value is None:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fmt_optional(value: Any, suffix: str = "", default: str = "暂无") -> str:
    number = to_float(value)
    if number is None:
        return default
    if abs(number) >= 10000:
        return f"{number:,.0f}{suffix}"
    if abs(number) >= 100:
        return f"{number:,.1f}{suffix}"
    return f"{number:.2f}{suffix}"


def fmt_market_cap(value: Any) -> str:
    number = to_float(value)
    if number is None:
        return "暂无"
    return f"{number / 100000000:.1f} 亿"


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


def stock_field(stock: dict[str, Any], field: str) -> Any:
    value = stock.get(field)
    if value is not None:
        return value
    legacy_name = STOCK_FIELD_ALIASES.get(field)
    if legacy_name:
        return stock.get(legacy_name)
    return None


def fmt_ratio(value: Any, default: str = "财务数据暂缺") -> str:
    number = to_float(value)
    if number is None:
        return default
    return f"{number * 100:.2f}%"


def exchange_name(code: str) -> str:
    if code.startswith(("600", "601", "603", "605", "688", "689")):
        return "上海证券交易所"
    if code.startswith(("000", "001", "002", "003", "300", "301")):
        return "深圳证券交易所"
    if code.startswith(("8", "4")):
        return "北京证券交易所"
    return "交易所待确认"


def first_stock() -> dict[str, Any]:
    stocks = st.session_state.get("stocks", [])
    if stocks:
        return stocks[0]
    return {}


def spark_svg(change: float | None, score: int) -> str:
    base = 54
    points = []
    for idx in range(12):
        direction = 1 if (change or 0) >= 0 else -1
        wobble = ((idx * 7 + score) % 13) - 6
        y = base - direction * idx * 2.3 + wobble * 0.9
        x = 8 + idx * 20
        points.append((x, max(18, min(94, y))))
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area = f"8,108 {line} 228,108"
    cls = "var(--up)" if (change or 0) >= 0 else "var(--down)"
    return f"""
    <svg class="spark-svg" viewBox="0 0 236 120" role="img" aria-label="近 30 日走势">
        <polygon points="{area}" fill="{cls}" opacity="0.10"></polygon>
        <polyline points="{line}" fill="none" stroke="{cls}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></polyline>
    </svg>
    """


def score_dial(score: int) -> str:
    radius = 42
    circumference = 2 * pi * radius
    offset = circumference * (1 - score / 100)
    return f"""
    <div class="score-dial">
        <svg width="104" height="104" viewBox="0 0 104 104" aria-label="综合评分 {score}/100">
            <circle cx="52" cy="52" r="{radius}" stroke="var(--border)" stroke-width="9" fill="none"></circle>
            <circle cx="52" cy="52" r="{radius}" stroke="var(--accent)" stroke-width="9" fill="none"
                    stroke-linecap="round" transform="rotate(-90 52 52)"
                    stroke-dasharray="{circumference:.2f}" stroke-dashoffset="{offset:.2f}"></circle>
            <text x="52" y="50" text-anchor="middle" font-size="25" font-weight="700" fill="var(--text)" font-family="var(--font-num)">{score}</text>
            <text x="52" y="71" text-anchor="middle" font-size="13" fill="var(--text-3)" font-family="var(--font-num)">/100</text>
        </svg>
        <div class="score-caption">综合评分</div>
    </div>
    """


def risk_signal_info(score: int, raw_level: str = "") -> dict[str, str]:
    text = str(raw_level or "")
    if "无法" in text or score <= 0:
        return {
            "class": "risk-neutral",
            "status": "暂无法判断",
            "caption": "请先确认持仓和缓存数据",
        }
    if "红" in text or score < 60:
        return {
            "class": "risk-red",
            "status": "风险偏高",
            "caption": "先看现金、单只占比和家庭承受能力",
        }
    if "黄" in text or score < 80:
        return {
            "class": "risk-yellow",
            "status": "需要注意",
            "caption": "有风险点需要持续观察",
        }
    return {
        "class": "risk-green",
        "status": "风险较低",
        "caption": "结构相对可控，但仍需定期复盘",
    }


def verdict_headline(score: int) -> str:
    if score >= 80:
        return "稳健 · 适合长期观察"
    if score >= 60:
        return "中性 · 需观察"
    if score >= 45:
        return "谨慎 · 不建议作为家庭主仓"
    return "不适合 · 风险与家庭账户不匹配"


def stock_header(analysis: dict[str, Any]) -> None:
    stock = first_stock()
    first_result = analysis["stock_results"][0]
    code = first_result["code"]
    name = first_result["name"]
    industry = first_result.get("industry") or stock_field(stock, "industry") or "行业待补充"
    change = to_float(stock_field(stock, "pct_change"))
    price = fmt_optional(stock_field(stock, "price"))
    change_label = "暂无" if change is None else signed_change(change)
    change_cls = change_class(change)
    render_html(
        f"""
        <div class="breadcrumb">
            <div><span class="crumb-link">← 返回首页</span> <span class="muted">/</span> <strong>分析报告</strong></div>
            <div class="muted">报告生成于 {html_escape(analysis["analysis_time"])} · 数据延迟约 15 分钟</div>
        </div>
        <section class="stock-head">
            <div>
                <div class="tag-row">
                    <span class="tag tag-code">{html_escape(code)}</span>
                    <span class="tag tag-exchange">{html_escape(exchange_name(code))}</span>
                    <span class="tag tag-industry">{html_escape(industry)}</span>
                </div>
                <h1 class="stock-title">{html_escape(name)}</h1>
                <div class="muted">{html_escape(name)} · 上市日期待补充</div>
                <dl class="basic-grid">
                    <div class="kv"><dt>当前股价</dt><dd>{price}</dd></div>
                    <div class="kv"><dt>今日变动</dt><dd class="{change_cls}">{change_label}</dd></div>
                    <div class="kv"><dt>总市值</dt><dd>{fmt_market_cap(stock_field(stock, "market_cap"))}</dd></div>
                    <div class="kv"><dt>市盈率 PE</dt><dd>{fmt_optional(stock_field(stock, "pe"), default="估值数据暂缺")}</dd></div>
                    <div class="kv"><dt>市净率 PB</dt><dd>{fmt_optional(stock_field(stock, "pb"), default="估值数据暂缺")}</dd></div>
                    <div class="kv"><dt>更新时间</dt><dd>{html_escape(stock_field(stock, "updated_at") or "暂无")}</dd></div>
                </dl>
            </div>
            <div class="spark-card">
                <div>
                    <div class="kicker">近 30 日走势</div>
                    {spark_svg(change, int(analysis["score"]))}
                </div>
                <div class="muted">30 日走势仅作视觉提示 · 1 年数据待后端补充</div>
            </div>
        </section>
        """
    )


def ai_report_block(analysis: dict[str, Any]) -> None:
    score = int(analysis["score"])
    headline = verdict_headline(score)
    summary = analysis["advice"][0]
    pros = [
        f"家庭仓位安全得分 {analysis['module_scores']['家庭仓位安全']:.0f}/100，可作为讨论的第一层参考。",
        f"风险承受匹配得分 {analysis['module_scores']['风险承受匹配']:.0f}/100，用来衡量这笔钱是否放得舒服。",
        "报告重点看现金、仓位、公司底子和短期交易热度，不鼓励追逐短线涨跌。",
    ]
    risks = analysis["risk_notes"][:4] or ["当前没有明显刺眼的问题，但仍建议定期复盘。"]
    render_html(
        f"""
        <section class="block ai-report">
            <div class="block-head">
                <div>
                    <h2 class="block-title">综合体检结论</h2>
                    <p class="block-subtitle">根据缓存数据自动评分 · 无需 AI 接口 · 不构成买卖建议</p>
                </div>
                <div class="muted">报告版本 v2026-05-17</div>
            </div>
            <div class="verdict-card">
                <div>
                    <div class="kicker">综合判断</div>
                    <div class="verdict-title">{html_escape(headline)}</div>
                    <p class="muted">{html_escape(summary)}</p>
                </div>
                {score_dial(score)}
            </div>
            <div class="ai-detail-note tone-accent">
                <strong>为什么说"适合长期"——优势</strong>
                <ul class="bullet-list">{''.join(f'<li>{html_escape(item)}</li>' for item in pros)}</ul>
            </div>
            <div class="ai-detail-note tone-warn">
                <strong>需要留意的风险</strong>
                <ul class="bullet-list">{''.join(f'<li>{html_escape(item)}</li>' for item in risks)}</ul>
            </div>
        </section>
        """
    )
    with st.expander('适合 / 不适合放进哪种账户', expanded=bool(st.session_state.fit_open)):
        fit_col, not_fit_col = st.columns(2)
        fit_col.markdown(
            """
            **适合**
            - 家庭已经有足够现金备用金
            - 愿意按季度或半年复盘
            - 能接受短期波动，不把它当作急用钱
            """
        )
        not_fit_col.markdown(
            """
            **不适合**
            - 未来 6 个月有大额刚性支出
            - 单只持仓已经占家庭资金过高
            - 只因为短期上涨而临时冲动
            """
        )


def metric_grid(analysis: dict[str, Any]) -> None:
    stock = first_stock()
    metrics = [
        ("PE", fmt_optional(stock_field(stock, "pe"), default="估值数据暂缺"), "估值指标，越高越需要解释增长来源"),
        ("PB", fmt_optional(stock_field(stock, "pb"), default="估值数据暂缺"), "股价相对账面资产的倍数"),
        ("ROE", fmt_ratio(stock_field(stock, "roe")), "公司用自己的钱赚钱的能力"),
        ("净利率", fmt_ratio(stock_field(stock, "net_margin")), "每卖出100元最终留下多少利润"),
        ("毛利率", fmt_ratio(stock_field(stock, "gross_margin")), "产品本身的赚钱空间"),
        ("资产负债率", fmt_ratio(stock_field(stock, "debt_ratio")), "公司借了多少钱相对自己的家底"),
        ("现金比例", percent(analysis["cash_ratio"]), "家庭备用金厚度"),
        ("股票/基金仓位", percent(analysis["stock_ratio"]), "家庭资金暴露在权益资产里的比例"),
        ("单只最大占比", percent(analysis["max_single_ratio"]), "用于判断是否过度集中"),
    ]
    cards = "".join(
        f"""
        <article class="metric-card">
            <div class="metric-label">{html_escape(label)}</div>
            <div class="metric-value">{html_escape(value)}</div>
            <div class="metric-note">{html_escape(note)}</div>
        </article>
        """
        for label, value, note in metrics
    )
    render_html(
        f"""
        <section class="block">
            <div class="block-head">
                <div>
                    <h2 class="block-title">核心财务指标</h2>
                    <p class="block-subtitle">数据来源：公司公告 · 最近报告期</p>
                </div>
            </div>
            <div class="metric-grid">{cards}</div>
        </section>
        """
    )


def watch_tasks_block(agent_result: dict[str, Any]) -> None:
    """体检后待办卡：展示 agent 生成的结构化观察任务。"""
    tasks: list[dict[str, Any]] = list(agent_result.get("watch_tasks") or [])
    if not tasks:
        return

    _PRIORITY_STYLE = {
        "high":   ("高", "#b94040", "#fff5f5"),
        "medium": ("中", "#b97a1a", "#fff9f0"),
        "low":    ("低", "#666",    "#f5f5f5"),
    }
    _CATEGORY_ICON = {
        "cash":          "💰",
        "concentration": "📊",
        "industry":      "🏭",
        "data":          "📋",
        "history":       "🔄",
        "general":       "⚠️",
    }

    rows_html = ""
    for task in tasks:
        priority = task.get("priority", "medium")
        label, color, bg = _PRIORITY_STYLE.get(priority, _PRIORITY_STYLE["medium"])
        icon = _CATEGORY_ICON.get(task.get("category", "general"), "⚠️")
        title = html_escape(str(task.get("title", "")))
        desc  = html_escape(str(task.get("desc", "")))
        rows_html += f"""
        <li style="display:flex;gap:0.65rem;padding:0.55rem 0.9rem;
                   border-bottom:1px solid var(--border);align-items:flex-start;">
            <span style="flex-shrink:0;font-size:1rem;margin-top:0.05rem;">{icon}</span>
            <div style="min-width:0;flex:1;">
                <div style="display:flex;align-items:center;gap:0.45rem;margin-bottom:0.18rem;">
                    <span style="font-size:0.82rem;font-weight:700;color:var(--text);">{title}</span>
                    <span style="font-size:0.65rem;font-weight:700;color:{color};
                                 background:{bg};padding:0.1rem 0.45rem;border-radius:10px;
                                 white-space:nowrap;">{label}</span>
                </div>
                <p style="font-size:0.78rem;color:var(--text-2);margin:0;line-height:1.5;">{desc}</p>
            </div>
        </li>"""

    render_html(f"""
    <section style="margin:0.8rem 0;border-radius:12px;
                    border:1px solid var(--border);background:var(--surface);overflow:hidden;">
        <div style="padding:0.5rem 0.9rem;display:flex;align-items:center;
                    justify-content:space-between;border-bottom:1px solid var(--border);">
            <span style="font-size:0.9rem;font-weight:700;color:var(--text);">📌&nbsp;体检后待办</span>
            <span style="font-size:0.72rem;color:var(--text-3);">共 {len(tasks)} 项</span>
        </div>
        <ul style="margin:0;padding:0;list-style:none;">{rows_html}</ul>
    </section>
    """)


def portfolio_metrics_block(summary: dict[str, Any], analysis: dict[str, Any]) -> None:
    """合并版指标卡：持仓结构 + 核心财务，两列紧凑布局，去除重复。"""
    if not analysis:
        return
    stock = first_stock()
    cash_ratio  = max(0.0, min(1.0, float(summary.get("cash_ratio",  0) or 0)))
    stock_ratio = max(0.0, min(1.0, float(summary.get("stock_ratio", 0) or 0)))
    top_industry = str(analysis.get("top_industry") or "")
    ind_conc     = float(analysis.get("industry_concentration") or 0)

    rows = [
        ("家庭总资产",   money(float(summary.get("total_assets", 0) or 0)),                      "现金 + 持仓合计"),
        ("现金比例",     percent(cash_ratio),                                                      "备用金厚度"),
        ("股票/基金仓位", percent(stock_ratio),                                                    "资金暴露比例"),
        ("单只最大占比", percent(float(summary.get("max_single_ratio", 0) or 0)),                 "集中度风险参考"),
        ("行业集中度",   f"{html_escape(top_industry)}&nbsp;{percent(ind_conc)}" if top_industry else "暂无", "行业分布是否过于集中"),
        ("PE 市盈率",    fmt_optional(stock_field(stock, "pe"),          default="暂缺"),          "估值高低参考"),
        ("PB 市净率",    fmt_optional(stock_field(stock, "pb"),          default="暂缺"),          "账面价值倍数"),
        ("ROE",          fmt_ratio(stock_field(stock, "roe")),                                     "公司用自己的钱赚钱的能力"),
        ("净利率",       fmt_ratio(stock_field(stock, "net_margin")),                              "每百元营收留下的利润"),
        ("毛利率",       fmt_ratio(stock_field(stock, "gross_margin")),                            "产品本身的盈利空间"),
        ("资产负债率",   fmt_ratio(stock_field(stock, "debt_ratio")),                              "公司借钱占家底的比例"),
    ]
    cards = "".join(
        f'<article class="metric-card-sm">'
        f'<div class="metric-label">{label}</div>'
        f'<div class="metric-value-sm">{value}</div>'
        f'<div class="metric-note-sm">{note}</div>'
        f'</article>'
        for label, value, note in rows
    )
    render_html(
        f"""
        <section class="block">
            <div class="block-head" style="margin-bottom:.6rem;">
                <div>
                    <h2 class="block-title">体检数据一览</h2>
                    <p class="block-subtitle">持仓结构 · 核心财务 · 数据来源：最近报告期</p>
                </div>
            </div>
            <div class="metric-grid-2">{cards}</div>
            <div style="margin-top:.9rem;">
                <div class="allocation-bar" aria-label="资产配置">
                    <div class="allocation-cash"  style="width:{cash_ratio  * 100:.1f}%"></div>
                    <div class="allocation-stock" style="width:{stock_ratio * 100:.1f}%"></div>
                </div>
                <p class="muted" style="margin-top:.3rem;">沉松绿代表现金，暖金代表股票/基金。</p>
            </div>
        </section>
        """
    )


def allocation_block(analysis: dict[str, Any]) -> None:
    cash_ratio = max(0, min(1, float(analysis["cash_ratio"])))
    stock_ratio = max(0, min(1, float(analysis["stock_ratio"])))
    render_html(
        f"""
        <section class="block">
            <div class="block-head">
                <div>
                    <h2 class="block-title">家庭账户概况</h2>
                    <p class="block-subtitle">先看钱放在哪里，再讨论某一只股票合不合适。</p>
                </div>
            </div>
            <div class="metric-grid">
                <article class="metric-card"><div class="metric-label">家庭总资产</div><div class="metric-value">{money(analysis["total_assets"])}</div><div class="metric-note">现金 + 股票/基金持仓</div></article>
                <article class="metric-card"><div class="metric-label">现金比例</div><div class="metric-value">{percent(cash_ratio)}</div><div class="metric-note">备用金越薄，越要保守</div></article>
                <article class="metric-card"><div class="metric-label">行业集中度</div><div class="metric-value">{html_escape(analysis["top_industry"])} {percent(analysis["industry_concentration"])}</div><div class="metric-note">行业过于集中时要多留意</div></article>
            </div>
            <div style="margin-top: 1.2rem;">
                <div class="allocation-bar" aria-label="资产配置">
                    <div class="allocation-cash" style="width:{cash_ratio * 100:.1f}%"></div>
                    <div class="allocation-stock" style="width:{stock_ratio * 100:.1f}%"></div>
                </div>
                <p class="muted">沉松绿代表现金，暖金代表股票/基金。</p>
            </div>
        </section>
        """
    )


def financial_insight_card(item: dict[str, Any]) -> None:
    """为单只持仓渲染公司底子说明卡、交易热度卡和仓位说明卡。"""

    def _tone(score: float) -> tuple[str, str, str]:
        """返回 (标签, 文字色, 背景色)。"""
        if score >= 75:
            return "稳", "#3f7d55", "rgba(63,125,85,0.10)"
        if score >= 55:
            return "看", "#b97a1a", "rgba(185,122,26,0.10)"
        return "紧", "#b94040", "rgba(185,64,64,0.10)"

    def _badge(label: str, fg: str, bg: str, score: float) -> str:
        return (
            f'<span style="font-size:0.68rem;font-weight:700;color:{fg};'
            f'background:{bg};border-radius:6px;padding:0.1rem 0.48rem;">'
            f'{label}&nbsp;{score:.0f}</span>'
        )

    def _notes_html(notes: list[str], limit: int = 3) -> str:
        return "".join(
            f'<li style="font-size:0.8rem;color:var(--text);'
            f'margin:0.1rem 0;line-height:1.45;">{html_escape(n)}</li>'
            for n in notes[:limit]
        )

    def _card(icon: str, title: str, badge_html: str, subtitle: str,
              notes_html: str) -> str:
        return (
            f'<div style="border:1px solid rgba(0,0,0,0.08);border-radius:10px;'
            f'padding:0.65rem 0.9rem;margin:0.3rem 0;">'
            f'<div style="display:flex;align-items:center;gap:0.45rem;margin-bottom:0.3rem;">'
            f'<span style="font-size:0.88rem;">{icon}</span>'
            f'<span style="font-size:0.85rem;font-weight:700;color:var(--text);">{title}</span>'
            f'{badge_html}'
            f'</div>'
            f'<p style="font-size:0.73rem;color:var(--text-3);margin:0 0 0.28rem;">{subtitle}</p>'
            f'<ul style="margin:0;padding-left:0.9rem;list-style:disc;">{notes_html}</ul>'
            f'</div>'
        )

    # ── 公司底子 ────────────────────────────────────────────────
    fin_score = float(item.get("financial_score") or 0)
    fin_label, fin_fg, fin_bg = _tone(fin_score)
    fin_text  = str(item.get("financial_text") or "")
    fin_notes = list(item.get("financial_notes") or [])

    metrics: list[str] = []
    for raw_key, display, multiplier in [
        ("roe",        "ROE",    100),
        ("net_margin", "净利率", 100),
        ("debt_ratio", "负债率", 100),
    ]:
        val = item.get(raw_key)
        if val is not None:
            try:
                metrics.append(f"{display} {float(val) * multiplier:.1f}%")
            except (TypeError, ValueError):
                pass
    for raw_key, display in [("pe", "PE"), ("pb", "PB")]:
        val = item.get(raw_key)
        if val is not None:
            try:
                metrics.append(f"{display} {float(val):.1f}")
            except (TypeError, ValueError):
                pass
    metrics_str = "　".join(metrics) if metrics else "核心指标暂缺"

    fin_sub_notes = ([fin_text] if fin_text else []) + fin_notes
    render_html(_card(
        "📊", "公司底子",
        _badge(fin_label, fin_fg, fin_bg, fin_score),
        metrics_str,
        _notes_html(fin_sub_notes, limit=3),
    ))

    # ── 交易热度 ────────────────────────────────────────────────
    heat_score = float(item.get("heat_score") or 0)
    heat_label, heat_fg, heat_bg = _tone(heat_score)
    heat_text  = str(item.get("heat_text") or "")
    heat_notes = list(item.get("heat_notes") or [])
    heat_sub   = ([heat_text] if heat_text else []) + heat_notes
    render_html(_card(
        "🌡", "交易热度",
        _badge(heat_label, heat_fg, heat_bg, heat_score),
        "换手率 / 量比 / 振幅 / 涨跌幅",
        _notes_html(heat_sub, limit=2),
    ))

    # ── 仓位占比 ────────────────────────────────────────────────
    pos_notes    = list(item.get("position_notes") or [])
    single_ratio = float(item.get("single_ratio") or 0)
    render_html(_card(
        "⚖️", "持仓占比",
        f'<span style="font-size:0.72rem;color:var(--text-3);">'
        f'占家庭总资产 {single_ratio * 100:.1f}%</span>',
        "单只集中度 / 整体仓位 / 风险承受匹配",
        _notes_html(pos_notes, limit=2),
    ))


def holdings_detail(analysis: dict[str, Any]) -> None:
    detail_rows = []
    for item in analysis["stock_results"]:
        detail_rows.append(
            {
                "代码": item["code"],
                "名称": item["name"],
                "金额": money(item["amount"]),
                "占比": percent(item["single_ratio"]),
                "行业": item["industry"],
                "行情": "已匹配" if item["market_source"] != "数据缺失" else "缺失",
                "财务": "已匹配" if item["finance_source"] != "数据缺失" else "暂缺",
                "风险": item["level"],
            }
        )
    render_html(
        """
        <section class="block">
            <div class="block-head">
                <div>
                    <h2 class="block-title">持仓明细</h2>
                    <p class="block-subtitle">每只标的都按数据状态、仓位和风险提示单独列出。</p>
                </div>
            </div>
        </section>
        """
    )
    st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

    for item in analysis["stock_results"]:
        with st.expander(f"📊 {item['name']} 底子说明", expanded=False):
            financial_insight_card(item)


def risk_grid(analysis: dict[str, Any]) -> None:
    notes = analysis["risk_notes"][:3] or ["当前组合没有明显刺眼的问题，但仍不代表没有风险。"]
    levels = [("中", "仓位与现金", "r-mid"), ("中", "公司与数据", "r-mid"), ("低", "短期波动", "r-lo")]
    if analysis["score"] < 60:
        levels[0] = ("高", "家庭承受度", "r-hi")
    cards = []
    for idx, note in enumerate(notes):
        level, title, cls = levels[min(idx, len(levels) - 1)]
        cards.append(
            f"""
            <article class="risk-card-new {cls}">
                <div class="risk-card-head">
                    <div class="muted">风险等级 · {level}</div>
                    <div class="risk-title-pill">{html_escape(title)}</div>
                </div>
                <p class="muted">{html_escape(note)}</p>
            </article>
            """
        )
    render_html(
        f"""
        <section class="block">
            <div class="block-head">
                <div>
                    <h2 class="block-title">风险提示</h2>
                    <p class="block-subtitle">这些不是"会发生"，而是"需要心里有数"。</p>
                </div>
            </div>
            <div class="risk-grid">{''.join(cards)}</div>
        </section>
        """
    )


def news_block() -> None:
    news = [
        {"date": "今天", "source": "公告", "title": "近期公告摘要待后端接入", "tag": "公告"},
        {"date": "本周", "source": "行业", "title": "行业新闻字段暂用前端占位", "tag": "行业"},
        {"date": "最近", "source": "新闻", "title": "后续可补充 news 接口返回内容", "tag": "新闻"},
    ]
    cards = "".join(
        f"""
        <article class="news-card">
            <div class="tag tag-industry">{html_escape(item["tag"])}</div>
            <h3 style="font-size:1.05rem;">{html_escape(item["title"])}</h3>
            <div class="muted">{html_escape(item["date"])} · {html_escape(item["source"])}</div>
        </article>
        """
        for item in news
    )
    render_html(
        f"""
        <section class="block">
            <div class="block-head">
                <div>
                    <h2 class="block-title">近期新闻与公告</h2>
                    <p class="block-subtitle">当前后端未返回新闻字段，先用前端占位，后续可接真实数据。</p>
                </div>
            </div>
            <div class="news-grid">{cards}</div>
        </section>
        """
    )


_MEMBER_OPTIONS = ["我", "爸爸", "妈妈", "其他"]
_TYPE_OPTIONS = ["疑问", "担心", "观察", "备注", "已讨论"]
_FOCUS_LABELS = ["现金比例", "持仓集中", "PE/PB估值", "财务数据", "数据缺失", "风险承受", "其他"]
_FOCUS_MAP = {
    "现金比例": "cash",
    "持仓集中": "concentration",
    "PE/PB估值": "valuation",
    "财务数据": "financial",
    "数据缺失": "data_missing",
    "风险承受": "risk_tolerance",
    "其他": "other",
}
_STANCE_LABELS = ["偏谨慎", "偏进取", "中性 / 只是记录"]
_STANCE_MAP = {
    "偏谨慎": "conservative",
    "偏进取": "aggressive",
    "中性 / 只是记录": "neutral",
}
# ── 向导式家庭看法记录选项 ────────────────────────────────────────
_GW_MEMBER_OPTIONS: list[str] = ["爸爸", "妈妈", "我", "全家一致"]
_GW_FOCUS_OPTIONS: list[tuple[str, str]] = [
    ("现金比例",  "cash"),
    ("持仓集中",  "concentration"),
    ("估值高低",  "valuation"),
    ("财务数据",  "financial"),
    ("整体风险",  "risk_tolerance"),
    ("其他",     "other"),
]
_GW_STANCE_OPTIONS: list[tuple[str, str]] = [
    ("偏谨慎",   "conservative"),
    ("中性观察",  "neutral"),
    ("偏进取",   "aggressive"),
]
_REVERSE_QA_DEFAULT = {
    "money_need_6m": "uncertain",
    "volatility_reaction": "discuss",
    "last_disagreement": "",
}
_MONEY_NEED_LABELS = ["可能要用", "不确定", "基本不会用"]
_MONEY_NEED_MAP = {
    "可能要用": "possible",
    "不确定": "uncertain",
    "基本不会用": "unlikely",
}
_VOLATILITY_LABELS = ["会比较慌，想马上处理", "能接受波动，先观察", "看情况，需要一起商量"]
_VOLATILITY_MAP = {
    "会比较慌，想马上处理": "panic",
    "能接受波动，先观察": "tolerate",
    "看情况，需要一起商量": "discuss",
}


def _normalize_reverse_qa(raw: Any) -> dict[str, str]:
    data = dict(_REVERSE_QA_DEFAULT)
    if isinstance(raw, dict):
        data.update({k: str(v or "") for k, v in raw.items() if k in data})
    if data["money_need_6m"] not in set(_MONEY_NEED_MAP.values()):
        data["money_need_6m"] = _REVERSE_QA_DEFAULT["money_need_6m"]
    if data["volatility_reaction"] not in set(_VOLATILITY_MAP.values()):
        data["volatility_reaction"] = _REVERSE_QA_DEFAULT["volatility_reaction"]
    data["last_disagreement"] = str(data.get("last_disagreement", "") or "").strip()
    return data


def _reverse_label(value: str, mapping: dict[str, str]) -> str:
    reverse = {v: k for k, v in mapping.items()}
    return reverse.get(value, value or "不确定")


def _comment_stance_label(stance: str) -> str:
    reverse = {v: k for k, v in _STANCE_MAP.items()}
    return reverse.get(stance, stance)


def _comment_focus_label(focus: str) -> str:
    reverse = {v: k for k, v in _FOCUS_MAP.items()}
    return reverse.get(focus, focus)


def discussion_block(run_id: str = "") -> None:
    storage_status = get_storage_status()
    render_html(
        """
        <section class="block">
            <div class="block-head">
                <div>
                    <h2 class="block-title">家庭观察记录</h2>
                    <p class="block-subtitle">记录家人对这次体检的看法，方便回顾和共同讨论。不作为任何操作建议。</p>
                </div>
            </div>
        </section>
        """
    )

    with st.form("family_comment_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            member = st.selectbox("成员", _MEMBER_OPTIONS, key="comment_member")
            comment_type = st.selectbox("类型", _TYPE_OPTIONS, key="comment_type")
        with col2:
            focus_label = st.selectbox("关注点", _FOCUS_LABELS, key="comment_focus")
            stance_label = st.selectbox("立场", _STANCE_LABELS, key="comment_stance")
        submitted = st.form_submit_button("保存立场记录", use_container_width=True)

    if submitted:
        comment = {
            "member": member,
            "comment_type": comment_type,
            "focus": _FOCUS_MAP.get(focus_label, "other"),
            "stance": _STANCE_MAP.get(stance_label, "neutral"),
            "content": "",
            "run_id": run_id,
        }
        result: dict[str, Any] = {"success": False, "backend": "local_csv", "error": ""}
        try:
            result = save_family_comment(comment)
            st.session_state["family_comment_last_save"] = get_last_family_comment_save_status()
        except Exception as exc:  # noqa: BLE001
            st.session_state["family_comment_last_save"] = {
                "success": False,
                "backend": "local_csv",
                "connected": False,
                "saved": False,
                "message": "观察记录保存失败，不影响体检结果。",
                "error": f"{type(exc).__name__}: {str(exc)[:160]}",
            }
            result = {"success": False, "backend": "local_csv", "error": st.session_state["family_comment_last_save"]["error"]}
        if result.get("success") and result.get("backend") == "supabase":
            for stale_key in ("comment_error", "save_error", "family_comment_error"):
                st.session_state.pop(stale_key, None)
        # 也写旧版 note（保持 session_state.notes 展示兼容）
        note_body = f"{focus_label}｜{stance_label}"
        note = make_note(note_body, who=member)
        try:
            get_storage().save_note(note)
        except Exception:  # noqa: BLE001
            pass
        st.session_state.notes.insert(0, note)
        try:
            st.session_state["family_comments"] = load_recent_family_comments(limit=20)
            st.session_state["family_comments_cache"] = st.session_state["family_comments"]
            st.session_state["family_comments_last_count"] = len(st.session_state["family_comments"])
            read_status = get_last_family_comment_read_status()
            if not result.get("success") and read_status.get("backend") == "supabase":
                saved_row_seen = any(
                    str(row.get("member", "")) == str(comment["member"])
                    and str(row.get("focus", "")) == str(comment["focus"])
                    and str(row.get("stance", "")) == str(comment["stance"])
                    and str(row.get("content", "") or "") == str(comment["content"])
                    and (not comment.get("run_id") or str(row.get("run_id", "")) == str(comment["run_id"]))
                    for row in st.session_state["family_comments"]
                )
                if saved_row_seen:
                    result = {"success": True, "backend": "supabase", "error": ""}
                    st.session_state["family_comment_last_save"] = {
                        "success": True,
                        "backend": "supabase",
                        "connected": True,
                        "saved": True,
                        "message": "观察记录已保存到 Supabase 云数据库",
                        "error": "",
                    }
        except Exception as exc:  # noqa: BLE001
            save_status_for_fallback = st.session_state.get("family_comment_last_save", {})
            locally_available = bool(save_status_for_fallback.get("saved"))
            st.session_state["family_comments"] = [comment] if locally_available else []
            st.session_state["family_comments_cache"] = st.session_state["family_comments"]
            st.session_state["family_comments_last_count"] = len(st.session_state["family_comments"])
            st.session_state["family_comment_last_save"] = {
                **st.session_state.get("family_comment_last_save", {}),
                "error": f"保存后重新读取失败：{type(exc).__name__}",
            }
        save_status = st.session_state.get("family_comment_last_save", {})
        if result.get("success") and result.get("backend") == "supabase":
            st.session_state["family_comment_notice"] = "观察记录已保存到云端"
            st.session_state["family_comment_notice_detail"] = ""
        elif result.get("backend") == "local_csv" and save_status.get("saved"):
            st.session_state["family_comment_notice"] = "观察记录已保存到本地，云端同步失败"
            st.session_state["family_comment_notice_detail"] = str(save_status.get("error", "") or result.get("error", ""))
        else:
            st.session_state["family_comment_notice"] = "观察记录保存失败，不影响体检结果。"
            st.session_state["family_comment_notice_detail"] = str(save_status.get("error", "") or result.get("error", ""))
        st.rerun()

    notice = st.session_state.pop("family_comment_notice", "")
    notice_detail = st.session_state.pop("family_comment_notice_detail", "")
    if notice:
        if "失败" in notice or "本地" in notice:
            st.warning(notice)
            if notice_detail:
                with st.expander("查看云端同步失败原因", expanded=False):
                    st.caption(notice_detail[:400])
        else:
            st.success(notice)

    st.caption(storage_status.get("message", "当前使用本地 CSV 兜底"))

    # 读取并展示最近观察记录
    comments: list[dict[str, Any]] = (
        st.session_state.get("family_comments")
        or st.session_state.get("family_comments_cache")
        or []
    )
    if not comments:
        try:
            comments = load_recent_family_comments(limit=20)
        except Exception:  # noqa: BLE001
            comments = []
        st.session_state["family_comments"] = comments
        st.session_state["family_comments_cache"] = comments
        st.session_state["family_comments_last_count"] = len(comments)

    if not comments:
        st.info("暂无观察记录。选择上方立场即可新增。")
        return

    def _render_comment(c: dict[str, Any]) -> None:
        member_disp = html_escape(c.get("member") or "我")
        ctype = html_escape(c.get("comment_type") or "备注")
        focus_disp = html_escape(_comment_focus_label(c.get("focus") or "other"))
        stance_disp = html_escape(_comment_stance_label(c.get("stance") or "neutral"))
        text = html_escape(c.get("content") or c.get("comment_text") or "")
        when = format_datetime_for_display(c.get("created_at"))
        content_line = f'<p class="muted" style="margin:0;">"{text}"</p>' if text else ""
        render_html(
            f"""
            <article class="note-card" style="margin-bottom:.7rem;">
                <div class="note-head" style="margin-bottom:.3rem;">
                    <span style="font-weight:600;">{member_disp}</span>
                    <span class="muted">｜{ctype}｜{focus_disp}｜{stance_disp}</span>
                    <span class="muted" style="float:right;font-size:.78rem;">{when}</span>
                </div>
                {content_line}
            </article>
            """
        )

    recent = comments[:3]
    for c in recent:
        _render_comment(c)

    if len(comments) > 3:
        with st.expander(f"查看全部 {len(comments)} 条观察记录", expanded=False):
            for c in comments[3:]:
                _render_comment(c)


def get_deepseek_api_key() -> str:
    key = ""
    try:
        key = str(st.secrets.get("DEEPSEEK_API_KEY", "")).strip()
    except Exception:  # noqa: BLE001
        key = ""
    return key or os.getenv("DEEPSEEK_API_KEY", "").strip()


def deepseek_block(analysis: dict[str, Any]) -> None:
    render_html(
        """
        <section class="block">
            <div class="block-head">
                <div>
                    <h2 class="block-title">数据报告下载</h2>
                    <p class="block-subtitle">普通分析入口只保留规则分析和调试信息，不再单独调用 DeepSeek。</p>
                </div>
            </div>
        </section>
        """
    )
    report_text = generate_txt_report(analysis)
    st.download_button(
        "↓ 数据分析报告",
        data=report_text.encode("utf-8"),
        file_name="FamilyReader_体检数据报告.txt",
        mime="text/plain",
        use_container_width=True,
        help="包含评分、持仓明细、风险提示的结构化报告",
    )


def followup_source_label(source: str) -> str:
    if source == "deepseek":
        return "DeepSeek AI"
    if source == "local_command":
        return "本地命令"
    return "本地规则兜底"


def followup_save_label(item: dict[str, Any]) -> str:
    if item.get("saved") == "true":
        backend = item.get("save_backend", "local_csv")
        return "已保存到云端" if backend == "supabase" else "已保存到本地"
    if item.get("saved") == "false":
        return "保存失败"
    return "保存状态未知"


def unpack_followup_result(result: Any) -> tuple[str, str, str, str, str]:
    """Return (answer, source, error, raw_error, call_path)."""
    if isinstance(result, dict):
        answer = str(result.get("answer", "") or "")
        source = str(result.get("source", "local_fallback") or "local_fallback")
        error = str(result.get("error", "") or "")
        raw_error = str(result.get("raw_error", "") or "")
        call_path = str(result.get("call_path", "") or "")
        return answer or _AI_REPORT_FALLBACK_MSG, source, error, raw_error, call_path
    return (
        str(result or _AI_REPORT_FALLBACK_MSG),
        "local_fallback",
        "追问函数返回旧字符串格式",
        "ai_report.answer_followup_question returned a str instead of dict",
        "(unknown — legacy return shape)",
    )


def save_followup_answer(agent_context: dict[str, Any], question: str) -> None:
    clean_question = question.strip()
    if not clean_question:
        return
    routed = route_slash_command(clean_question)
    effective_question = clean_question
    command = ""
    try:
        if routed.get("is_command"):
            command = str(routed.get("command", "") or "")
            if routed.get("direct"):
                answer = sanitize_compliance_text(str(routed.get("answer", "") or ""))
                source = "local_command"
                error = ""
                raw_error = ""
                call_path = "app.save_followup_answer -> question_router.route_slash_command"
            else:
                effective_question = str(routed.get("routed_question", "") or clean_question)
                answer, source, error, raw_error, call_path = unpack_followup_result(
                    answer_followup_question(agent_context, effective_question)
                )
                answer = sanitize_compliance_text(answer)
        else:
            answer, source, error, raw_error, call_path = unpack_followup_result(
                answer_followup_question(agent_context, clean_question)
            )
            answer = sanitize_compliance_text(answer)
    except Exception as exc:  # noqa: BLE001
        answer = _AI_REPORT_FALLBACK_MSG
        source = "local_fallback"
        error = f"追问调用异常：{type(exc).__name__}"
        raw_error = f"{type(exc).__name__}: {exc}"[:500]
        call_path = "save_followup_answer caught top-level exception"

    answers: list[dict[str, str]] = list(st.session_state.get("followup_answers", []))
    existing = next((a for a in answers if a["question"] == clean_question), None)
    record = {
        "question": clean_question,
        "answer": answer,
        "source": source,
        "error": error,
        "raw_error": raw_error,
        "call_path": call_path,
    }
    if command:
        record["command"] = command
    if effective_question != clean_question:
        record["routed_question"] = effective_question
    if source == "local_fallback":
        st.session_state["last_followup_error"] = {
            "question": clean_question,
            "source": source,
            "error": error or "DeepSeek 未返回可用结果",
            "raw_error": raw_error,
            "call_path": call_path,
        }
    else:
        st.session_state.pop("last_followup_error", None)
    try:
        saved = save_followup_history(question=clean_question, answer=answer, source=source, error=error)
        save_status = get_last_followup_save_status()
    except Exception:  # noqa: BLE001
        saved = False
        save_status = {
            "backend": "local_csv",
            "saved": False,
            "message": "追问记录保存失败",
            "error": "保存函数调用异常",
        }
    record["saved"] = "true" if saved else "false"
    record["save_backend"] = str(save_status.get("backend", "local_csv"))
    record["save_message"] = str(save_status.get("message", ""))
    record["save_error"] = str(save_status.get("error", ""))
    st.session_state["last_followup_save"] = save_status
    if existing:
        existing.update(record)
    else:
        answers.insert(0, record)
    st.session_state["followup_answers"] = answers


def followup_block(agent_context: dict[str, Any]) -> None:
    """继续追问区域：动态问题按钮（每次体检结果不同，问题随之变化） + 保留回答历史。"""
    existing_answers = list(st.session_state.get("followup_answers", []))
    if existing_answers and any(
        "source" not in item or "error" not in item or "raw_error" not in item
        for item in existing_answers
        if isinstance(item, dict)
    ):
        # 旧版本字段不全（v3 之前），全部清掉，避免诊断信息缺失
        st.session_state["followup_answers"] = []

    st.markdown("---")
    render_html(
        """
        <section class="block ai-report" style="padding:1.15rem 1.2rem;">
            <div class="block-head" style="margin-bottom:.35rem;">
                <div>
                    <h2 class="block-title" style="font-size:1.34rem;">继续追问这次体检</h2>
                    <p class="block-subtitle">问题根据本次体检数据自动生成，点击即可继续问 AI。回答只基于本次体检结果，不荐股，不预测涨跌。</p>
                </div>
            </div>
        </section>
        """
    )
    # 从缓存读取问题——每次体检只随机生成一次，rerun 时保持稳定
    cached: list[str] = st.session_state.get("followup_questions", [])
    if not cached:
        try:
            cached = get_dynamic_questions(agent_context) if agent_context else _FALLBACK_QUESTIONS
            if not cached:
                cached = _FALLBACK_QUESTIONS
        except Exception:  # noqa: BLE001
            cached = _FALLBACK_QUESTIONS
        st.session_state["followup_questions"] = cached
    questions: list[str] = cached

    st.caption("你可以这样问：")
    col_a, col_b = st.columns(2)
    for qi, question in enumerate(questions):
        col = col_a if qi % 2 == 0 else col_b
        if col.button(f"AI 建议｜{question}", use_container_width=True, key=f"fq_{qi}"):
            save_followup_answer(agent_context, question)
            st.rerun()

    custom_question = st.text_input(
        "自定义追问",
        placeholder="也可以自己输入问题，例如：这次主要风险到底是什么？",
        label_visibility="collapsed",
        key="custom_followup_question",
    )
    if st.button("发送追问", use_container_width=True):
        if custom_question.strip():
            save_followup_answer(agent_context, custom_question)
            st.rerun()

    followup_answers: list[dict[str, str]] = st.session_state.get("followup_answers", [])
    if followup_answers:
        _ans_n = len(followup_answers)
        with st.expander(f"📝 查看 AI 回答（{_ans_n} 条）", expanded=True):
            for item in followup_answers[:3]:
                st.markdown(f"**问题：** {item['question']}")
                st.markdown(f"**AI 回答：**\n\n{item['answer']}")
                source = item.get("source", "local_fallback")
                st.caption(f"回答来源：{followup_source_label(source)}")
                st.caption(f"保存状态：{followup_save_label(item)}")
                if source == "local_fallback":
                    raw = item.get("raw_error", "") or item.get("error", "")
                    if raw:
                        with st.expander("为什么进入本地兜底？（开发者诊断）", expanded=False):
                            st.code(raw, language="text")
                            cp = item.get("call_path", "")
                            if cp:
                                st.caption(f"调用路径：{cp}")
            if _ans_n > 3:
                for item in followup_answers[3:]:
                    st.markdown(f"**问题：** {item['question']}")
                    st.markdown(f"**AI 回答：**\n\n{item['answer']}")
                    st.caption(f"回答来源：{followup_source_label(item.get('source', 'local_fallback'))}")
                    st.caption(f"保存状态：{followup_save_label(item)}")
                    st.markdown("---")


def followup_entry_block(agent_result: dict[str, Any], agent_context: dict[str, Any]) -> None:
    followup_answers: list[dict[str, Any]] = list(st.session_state.get("followup_answers", []))
    saved_count = sum(1 for item in followup_answers if item.get("saved") == "true")
    subtitle = (
        f"本次已追问 {len(followup_answers)} 条，已保存 {saved_count} 条。"
        if followup_answers
        else "点击进入后可以继续问 AI，回答会尝试保存到历史记录。"
    )
    render_html(
        f"""
        <section class="block ai-report" style="padding:1rem 1.1rem;">
            <div class="block-head" style="margin-bottom:.35rem;">
                <div>
                    <h2 class="block-title" style="font-size:1.18rem;">继续追问这次体检</h2>
                    <p class="block-subtitle">{html_escape(subtitle)}</p>
                </div>
            </div>
        </section>
        """
    )
    if st.button("继续追问这次体检 →", use_container_width=True, key="open_followup_view"):
        st.session_state["active_view"] = "followup"
        st.rerun()
    if followup_answers:
        latest = followup_answers[0]
        st.caption(f"最近一次：{latest.get('question', '')}")
        st.caption(f"保存状态：{followup_save_label(latest)}")


def _unpack_agent_report(report_result: Any) -> tuple[str, str, str]:
    if isinstance(report_result, dict):
        text = str(report_result.get("ai_report", "") or report_result.get("report", "") or "")
        dinner = str(report_result.get("dinner_talk", "") or "")
        source = str(report_result.get("report_source", "local_fallback") or "local_fallback")
        return text or _AI_REPORT_FALLBACK_MSG, source, dinner
    return str(report_result or _AI_REPORT_FALLBACK_MSG), "local_fallback", ""


def _report_source_label(report_source: str) -> str:
    return "DeepSeek AI 生成" if report_source == "deepseek" else "本地规则兜底生成"


def reverse_qa_block(agent_result: dict[str, Any], agent_context: dict[str, Any], mode: str) -> None:
    current = _normalize_reverse_qa(
        agent_result.get("reverse_qa")
        or agent_context.get("reverse_qa")
        or st.session_state.get("reverse_qa")
    )
    with st.expander("补充家庭情况，让报告更贴近实际", expanded=False):
        st.caption("这是可选项，不填写也不影响体检。填写后会重新生成本次 AI 风险说明。")
        with st.form("reverse_qa_form"):
            money_label = st.selectbox(
                "这笔钱半年内有没有可能要用？",
                _MONEY_NEED_LABELS,
                index=_MONEY_NEED_LABELS.index(_reverse_label(current["money_need_6m"], _MONEY_NEED_MAP)),
                key="reverse_money_need_6m",
            )
            volatility_label = st.selectbox(
                "如果最大那只持仓短期波动比较大，你第一反应更可能是？",
                _VOLATILITY_LABELS,
                index=_VOLATILITY_LABELS.index(_reverse_label(current["volatility_reaction"], _VOLATILITY_MAP)),
                key="reverse_volatility_reaction",
            )
            last_disagreement = st.text_input(
                "你们上一次因为投资有不同意见，是关于什么？",
                value=current.get("last_disagreement", ""),
                placeholder="例如：现金留多少、某只股票占比高不高、要不要继续观察等",
                key="reverse_last_disagreement",
            )
            submitted = st.form_submit_button("更新本次 AI 风险说明", use_container_width=True)

        if submitted:
            reverse_qa = {
                "money_need_6m": _MONEY_NEED_MAP.get(money_label, "uncertain"),
                "volatility_reaction": _VOLATILITY_MAP.get(volatility_label, "discuss"),
                "last_disagreement": str(last_disagreement or "").strip(),
            }
            st.session_state["reverse_qa"] = reverse_qa
            agent_context["reverse_qa"] = reverse_qa
            agent_result["reverse_qa"] = reverse_qa
            with st.spinner("正在根据补充情况更新报告..."):
                report_text, report_source, dinner_talk = _unpack_agent_report(
                    generate_agent_report(agent_context, mode)
                )
            agent_result["ai_report"] = report_text
            agent_result["dinner_talk"] = dinner_talk
            agent_result["report_source"] = report_source
            agent_result["report_mode"] = mode
            agent_context["ai_report"] = report_text
            agent_context["dinner_talk"] = dinner_talk
            agent_context["report_source"] = report_source
            agent_context["report_mode"] = mode
            agent_result["agent_context"] = agent_context
            st.session_state["agent_result"] = agent_result
            st.session_state.pop("followup_questions", None)
            st.success("已根据补充家庭情况更新本次报告。")
            st.rerun()


def family_disagreement_block(disagreement: dict[str, Any]) -> None:
    if not isinstance(disagreement, dict) or not disagreement.get("has_conflict"):
        return
    conflicts = disagreement.get("conflicts") or []
    if not conflicts:
        return
    first = conflicts[0]
    focus_label = html_escape(first.get("focus_label") or first.get("focus") or "风险关注点")
    members = first.get("members") or {}
    conservative = [name for name, stance in members.items() if stance == "conservative"]
    aggressive = [name for name, stance in members.items() if stance == "aggressive"]
    if conservative and aggressive:
        line = f"{html_escape(conservative[0])}在「{focus_label}」上偏谨慎，{html_escape(aggressive[0])}在同一问题上偏进取。"
    else:
        line = html_escape(disagreement.get("summary") or "家庭成员在同一个风险关注点上存在不同看法。")
    render_html(
        f"""
        <div style="display:flex;align-items:flex-start;gap:0.5rem;
                    padding:0.45rem 0.85rem;margin:0.3rem 0 0.35rem;
                    background:#fff7ed;border-radius:10px;border:1.5px solid #d08a2d;">
            <span style="font-size:0.9rem;flex-shrink:0;line-height:1.6;">⚠️</span>
            <div style="min-width:0;">
                <span style="font-size:0.86rem;font-weight:700;color:#7a3e2e;">
                    家庭风险看法不一致
                </span>
                <span style="font-size:0.8rem;color:#7a3e2e;margin-left:0.3rem;">{line}</span>
                <p style="font-size:0.72rem;color:#9a6a2a;margin:0.1rem 0 0;">
                    建议这次体检先围绕这一点聊清楚。
                </p>
            </div>
        </div>
        """
    )


def intent_action_gap_block(gap_data: dict[str, Any]) -> None:
    """意图-行动差距镜：把家人立场记录和当前持仓数据对比，提示明显差距。"""
    if not isinstance(gap_data, dict) or not gap_data.get("has_gap"):
        return
    gaps = list(gap_data.get("gaps") or [])
    if not gaps:
        return

    notable = [g for g in gaps if g.get("severity") == "notable"]
    show_gaps = notable if notable else gaps[:2]   # 最多显示 2 条

    rows_html = ""
    for g in show_gaps:
        member      = _hesc(g, "member")
        focus_label = _hesc(g, "focus_label")
        stated      = _hesc(g, "stated")
        current     = _hesc(g, "current_desc")
        gap_desc    = _hesc(g, "gap_desc")
        rows_html += (
            f'<li style="padding:0.22rem 0;border-bottom:1px solid rgba(122,62,46,0.08);'
            f'display:flex;align-items:flex-start;gap:0.45rem;">'
            f'<span style="flex-shrink:0;font-size:0.72rem;font-weight:700;color:#7a3e2e;'
            f'background:rgba(122,62,46,0.1);border-radius:999px;padding:0.1rem 0.45rem;'
            f'white-space:nowrap;">{member}</span>'
            f'<span style="font-size:0.82rem;color:var(--text);line-height:1.45;">'
            f'{gap_desc}'
            f'<span style="font-size:0.7rem;color:var(--text-3);margin-left:0.25rem;">'
            f'立场：{stated}／{focus_label}／{current}</span>'
            f'</span></li>'
        )
    extra = len(gaps) - len(show_gaps)
    extra_html = (
        f'<p style="font-size:0.72rem;color:var(--text-3);margin:0.35rem 0 0;">'
        f'另有 {extra} 处细微差距，可在追问时进一步了解。</p>'
        if extra > 0 else ""
    )
    render_html(
        f"""
        <section style="margin:0.3rem 0 0.45rem;border-radius:10px;
                        border:1.5px solid rgba(122,62,46,0.3);
                        background:rgba(122,62,46,0.04);overflow:hidden;">
            <div style="padding:0.35rem 0.85rem 0.25rem;display:flex;align-items:center;
                        gap:0.4rem;border-bottom:1px solid rgba(122,62,46,0.1);">
                <span style="font-size:0.85rem;">🪞</span>
                <span style="font-size:0.85rem;font-weight:700;color:#7a3e2e;">意图与持仓差距</span>
                <span style="font-size:0.7rem;color:var(--text-3);margin-left:auto;">
                    家人立场 vs 当前持仓
                </span>
            </div>
            <ul style="margin:0;padding:0.1rem 0.85rem 0.35rem;list-style:none;">
                {rows_html}
            </ul>
            {extra_html}
        </section>
        """
    )


def risk_factor_breakdown_block(analysis: dict[str, Any], factor_data: dict[str, Any] | None = None) -> None:
    """把现有评分拆成父母能看懂的风险因子，不改变分析逻辑。"""
    factor_data = factor_data or build_risk_factor_breakdown(analysis or {})
    factors = list((factor_data or {}).get("factors") or [])
    weakest = (factor_data or {}).get("weakest_factor") or {}
    if not factors:
        return

    color_by_tone = {
        "steady": "#3f7d55",
        "watch": "#b97a1a",
        "tight": "#b94040",
    }

    cards = []
    for item in factors:
        name = str(item.get("name", ""))
        score = float(item.get("score", 0) or 0)
        weight = float(item.get("weight", 0) or 0)
        contribution = float(item.get("contribution", 0) or 0)
        tone_label = str(item.get("tone_label", "看") or "看")
        color = color_by_tone.get(str(item.get("tone", "")), "#b97a1a")
        status = str(item.get("status", "") or "需要继续观察")
        plain = str(item.get("plain", "") or name)
        watch = str(item.get("watch", "") or "结合本次体检结果继续观察")
        cards.append(
            f"""
            <article style="border:1px solid var(--border);border-radius:12px;background:var(--surface);
                            padding:0.85rem 0.9rem;min-width:0;">
                <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.35rem;">
                    <span style="width:1.65rem;height:1.65rem;border-radius:999px;background:{color};
                                 color:#fff;display:inline-flex;align-items:center;justify-content:center;
                                 font-size:0.78rem;font-weight:800;flex-shrink:0;">{html_escape(tone_label)}</span>
                    <div style="min-width:0;">
                        <div style="font-size:0.9rem;font-weight:800;color:var(--text);line-height:1.25;">
                            {html_escape(name)}
                        </div>
                        <div style="font-size:0.72rem;color:var(--text-3);line-height:1.35;">
                            权重 {weight:.0f}% · 贡献约 {contribution:.1f} 分
                        </div>
                    </div>
                </div>
                <div style="height:0.42rem;border-radius:999px;background:var(--bg-2);overflow:hidden;
                            border:1px solid var(--border);margin:0.55rem 0 0.45rem;">
                    <div style="width:{max(0, min(100, score)):.1f}%;height:100%;background:{color};
                                border-radius:999px;"></div>
                </div>
                <div style="font-size:0.78rem;font-weight:700;color:{color};margin-bottom:0.25rem;">
                    {score:.0f}/100 · {html_escape(status)}
                </div>
                <p style="font-size:0.78rem;color:var(--text-2);line-height:1.5;margin:0 0 0.25rem;">
                    {html_escape(plain)}
                </p>
                <p style="font-size:0.72rem;color:var(--text-3);line-height:1.45;margin:0;">
                    看：{html_escape(watch)}
                </p>
            </article>
            """
        )

    focus_name = str(weakest.get("name", factors[0].get("name", "")) or "")
    focus_score = float(weakest.get("score", factors[0].get("score", 0)) or 0)
    focus_plain = str(weakest.get("plain", focus_name) or focus_name)

    render_html(
        f"""
        <section class="block" style="padding:1rem 1rem 0.95rem;">
            <div class="block-head" style="margin-bottom:0.65rem;">
                <div>
                    <h2 class="block-title" style="font-size:1.15rem;">风险因子拆解</h2>
                    <p class="block-subtitle">这不是额外预测，只是把综合评分拆开看清楚。</p>
                </div>
            </div>
            <div style="border:1px solid #e8c4b2;background:#fff9f6;border-radius:12px;
                        padding:0.75rem 0.85rem;margin-bottom:0.75rem;">
                <p style="font-size:0.82rem;color:var(--text);line-height:1.55;margin:0;">
                    本次最需要先看的因子是：
                    <strong>{html_escape(focus_name)}</strong>（{focus_score:.0f}/100）。
                    简单说，就是{html_escape(focus_plain)}。
                </p>
            </div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:0.6rem;">
                {''.join(cards)}
            </div>
        </section>
        """
    )


def _confidence_badge_html(level: str, level_code: str, summary: str) -> str:
    """Compliance Guard 置信度标签 HTML 片段。无数据时返回空字符串。"""
    if not level:
        return ""
    colors = {
        "high":   ("#3f7d55", "rgba(63,125,85,0.10)"),
        "medium": ("#b97a1a", "rgba(185,122,26,0.10)"),
        "low":    ("#b94040", "rgba(185,64,64,0.10)"),
    }
    fg, bg = colors.get(level_code, ("#888", "rgba(0,0,0,0.06)"))
    return (
        f'<p style="margin:0 0 0.45rem;padding-left:0.2rem;">'
        f'<span style="font-size:0.68rem;font-weight:700;color:{fg};'
        f'background:{bg};border-radius:6px;padding:0.1rem 0.5rem;">'
        f'数据置信度：{html_escape(level)}</span>'
        f'<span style="font-size:0.68rem;color:var(--text-3);margin-left:0.4rem;">'
        f'{html_escape(summary)}</span>'
        f'</p>'
    )


def agent_result_block(agent_result: dict[str, Any]) -> None:
    if not agent_result:
        return

    summary = agent_result.get("portfolio_summary", {})
    main_risks = agent_result.get("main_risks", []) or ["当前没有明显刺眼的问题，但仍需定期复盘。"]
    missing_data = agent_result.get("missing_data", {})
    data_status = agent_result.get("data_status", "未知")
    agent_context = agent_result.get("agent_context", {})
    _confidence = agent_result.get("data_confidence") or {}
    _conf_level   = str(_confidence.get("level") or "")
    _conf_code    = str(_confidence.get("level_code") or "")
    _conf_summary = str(_confidence.get("summary") or "")
    _history_analysis = agent_result.get("history_analysis") or {}
    _behavior_note = str(_history_analysis.get("behavior_note") or "")

    # ── 1. 简洁状态卡（4 行以内，不含技术词）──────────────────
    data_source_label = (
        "实时行情"
        if not agent_result.get("debug_info", {}).get("使用本地缓存", True)
        else "本地缓存"
    )
    storage_status = agent_result.get("storage_status") or get_storage_status()
    storage_backend = storage_status.get("backend", "local_csv")
    storage_label = "Supabase 云数据库" if storage_backend == "supabase" else "本地 CSV 兜底"
    saved_label = "已保存" if agent_result.get("saved_history") else "未保存"
    storage_note = (
        "记录已保存到云端，重新打开页面后仍可读取。"
        if storage_backend == "supabase" and agent_result.get("saved_history")
        else "本地 CSV 仅适合开发测试，Streamlit Cloud 重启或重新部署后可能丢失。"
        if agent_result.get("saved_history")
        else "本次历史记录暂未保存，不影响体检结果。"
    )
    render_html(
        f"""
        <div style="display:flex;align-items:center;gap:0.55rem;
                    padding:0.5rem 0.85rem;margin-bottom:0.25rem;
                    background:var(--accent-soft);border-radius:10px;">
            <svg width="22" height="22" viewBox="0 0 22 22" fill="none" style="flex-shrink:0;">
                <circle cx="11" cy="11" r="11" fill="#7a3e2e" opacity="0.14"/>
                <path d="M6.5 11.5 L9.5 14.5 L15.5 8" stroke="#7a3e2e"
                      stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <div style="min-width:0;">
                <span style="font-size:0.92rem;font-weight:700;color:var(--text);">智能体检已完成</span>
                <span style="font-size:0.75rem;color:var(--text-3);margin-left:0.45rem;">·&nbsp;已检查持仓结构、现金比例与集中风险</span>
            </div>
        </div>
        <p style="font-size:0.72rem;color:var(--text-3);margin:0 0 0.4rem;padding-left:0.2rem;">
            数据来源：{html_escape(data_source_label)}&ensp;·&ensp;存储方式：{html_escape(storage_label)}&ensp;·&ensp;历史记录：{html_escape(saved_label)}&ensp;·&ensp;{html_escape(storage_note)}
        </p>
        {_confidence_badge_html(_conf_level, _conf_code, _conf_summary)}
        """
    )

    if _behavior_note:
        render_html(
            f'<p style="font-size:0.78rem;color:var(--text-3);'
            f'margin:0 0 0.4rem;padding:0.35rem 0.75rem;'
            f'background:var(--accent-soft);border-radius:8px;">'
            f'📌&nbsp;{html_escape(_behavior_note)}</p>'
        )

    _show_risks = main_risks[:4]
    _extra_risk_n = max(0, len(main_risks) - 4)
    _risk_rows = "".join(
        f'<li style="padding:0.18rem 0;display:flex;align-items:baseline;gap:0.55rem;'
        f'border-bottom:1px solid rgba(122,62,46,0.07);">'
        f'<span style="flex-shrink:0;font-size:0.65rem;font-weight:700;color:#fff;'
        f'background:#b94040;border-radius:50%;width:1.35em;height:1.35em;'
        f'display:inline-flex;align-items:center;justify-content:center;line-height:1;">'
        f'{i + 1}</span>'
        f'<span style="font-size:0.83rem;line-height:1.45;color:var(--text);">{html_escape(r)}</span>'
        f'</li>'
        for i, r in enumerate(_show_risks)
    )
    _more_html = (
        f'<p style="font-size:0.7rem;color:var(--text-3);margin:0.2rem 0 0;padding-left:0.1rem;">'
        f'另有 {_extra_risk_n} 项，可在"查看完整持仓数据"中查看。</p>'
        if _extra_risk_n else ""
    )
    render_html(
        f"""
        <section style="margin:0.35rem 0 0.5rem;border-radius:10px;
                        border:1.5px solid #e8c4b2;background:#fff9f6;overflow:hidden;">
            <div style="padding:0.4rem 0.85rem 0.28rem;display:flex;align-items:center;
                        gap:0.4rem;border-bottom:1px solid #f0ddd3;">
                <svg width="15" height="15" viewBox="0 0 17 17" fill="none" style="flex-shrink:0;">
                    <path d="M8.5 1.5 L15.5 14.5 L1.5 14.5 Z"
                          fill="#b94040" opacity="0.18"
                          stroke="#b94040" stroke-width="1.4" stroke-linejoin="round"/>
                    <line x1="8.5" y1="6.5" x2="8.5" y2="10.5"
                          stroke="#b94040" stroke-width="1.6" stroke-linecap="round"/>
                    <circle cx="8.5" cy="12.5" r="0.85" fill="#b94040"/>
                </svg>
                <span style="font-size:0.85rem;font-weight:700;color:#7a3e2e;">本次风险预警</span>
                <span style="font-size:0.7rem;color:var(--text-3);margin-left:auto;">
                    共 {len(main_risks)} 项待关注
                </span>
            </div>
            <ul style="margin:0;padding:0.1rem 0.85rem 0.35rem;list-style:none;">
                {_risk_rows}
            </ul>
            {_more_html}
        </section>
        """
    )

    family_disagreement_block(agent_result.get("family_disagreement", {}))
    intent_action_gap_block(agent_result.get("intent_action_gap", {}))

    # ── 2. 综合体检结论：评分 + 三项指标 ──────────────────────
    conclusion = (
        f"现金比例 {percent(float(summary.get('cash_ratio', 0) or 0))}，"
        f"股票/基金持仓 {percent(float(summary.get('stock_ratio', 0) or 0))}，"
        f"最大单只占比 {percent(float(summary.get('max_single_ratio', 0) or 0))}。"
        f"主要关注点：{main_risks[0]}"
    )
    risk_score = int(agent_result.get("risk_score", 0) or 0)
    risk_info = risk_signal_info(risk_score, str(agent_result.get("risk_level", "") or ""))
    render_html(
        f"""
        <section class="block ai-report">
            <div class="block-head">
                <div>
                    <h2 class="block-title">本次智能体检结论</h2>
                    <p class="block-subtitle">{html_escape(conclusion)}</p>
                </div>
            </div>
            <div class="verdict-card">
                <div class="risk-signal {html_escape(risk_info["class"])}">
                    <div class="risk-light" aria-hidden="true"></div>
                    <div>
                        <div class="kicker">综合风险等级</div>
                        <div class="risk-status">{html_escape(risk_info["status"])}</div>
                        <div class="risk-score-line">综合评分 {risk_score}/100 · {html_escape(risk_info["caption"])}</div>
                        <p class="muted">{html_escape(data_status)}</p>
                    </div>
                </div>
                {score_dial(risk_score)}
            </div>
        </section>
        """
    )

    # ── 3. 详细数据折叠（不阻断主流程，按需展开）──────────────
    _analysis = st.session_state.get("analysis") or agent_result.get("analysis") or {}
    with st.expander("📊 查看完整持仓数据", expanded=False):
        if _analysis:
            risk_factor_breakdown_block(_analysis, agent_result.get("risk_factors"))
            portfolio_metrics_block(summary, _analysis)
            with st.expander("持仓明细与数据来源", expanded=False):
                holdings_detail(_analysis)
        has_missing = any(bool(v) for v in missing_data.values())
        if has_missing:
            st.markdown("**数据缺失说明**")
            for title, items in missing_data.items():
                if items:
                    if "估值" in title:
                        st.caption("· 估值数据暂缺，本次不评价估值高低。")
                    else:
                        st.caption(f"· {title}：{len(items)} 只数据缺失")
        watch_tasks_block(agent_result)

    # ── 4. 下一步 CTA：进入 AI 风险说明页 ──────────────────────
    st.markdown("---")
    render_html("""
    <div style="margin:0.2rem 0 0.65rem;border-radius:14px;
                border:1.5px solid #e8c4b2;background:#fff9f6;
                padding:0.9rem 1.1rem 0.75rem;">
        <p style="font-size:0.73rem;font-weight:600;letter-spacing:.06em;
                  color:#7a3e2e;text-transform:uppercase;margin:0 0 0.35rem;">
            第 2 步
        </p>
        <p style="font-size:0.97rem;font-weight:700;color:var(--text);margin:0 0 0.2rem;">
            查看 AI 对这次风险的完整说明
        </p>
        <p style="font-size:0.82rem;color:var(--text-3);margin:0;">
            基于本次体检数据生成，不构成买卖建议。
        </p>
    </div>
    """)
    if st.button("查看 AI 风险说明 →", use_container_width=True,
                 key="goto_ai_report_btn", type="primary"):
        st.session_state["active_view"] = "ai_report"
        st.rerun()


def developer_debug_block(agent_result: dict[str, Any]) -> None:
    if not agent_result:
        render_error_debug(st.session_state.get("last_agent_error"))
        return
    with st.expander("开发者信息 / 调试详情", expanded=False):
        error_info = st.session_state.get("last_agent_error")
        if error_info:
            st.write("**最近一次错误**")
            st.write(f"- 错误类型：{error_info.get('错误类型', '')}")
            st.write(f"- 错误信息：{error_info.get('错误信息', '')}")
            st.write(f"- 当前工作目录：{error_info.get('当前工作目录', '')}")
            st.write(f"- 已找到缓存文件：{error_info.get('已找到缓存文件', '')}")
        followup_error = st.session_state.get("last_followup_error")
        if followup_error:
            st.write("**最近一次追问兜底**")
            st.write(f"- 追问回答来源：{followup_source_label(followup_error.get('source', 'local_fallback'))}")
            st.write(f"- 兜底原因：{followup_error.get('error', '')}")
            raw_err = followup_error.get("raw_error", "")
            if raw_err:
                st.code(raw_err, language="text")
            call_path = followup_error.get("call_path", "")
            if call_path:
                st.caption(f"调用路径：{call_path}")
        followup_save = st.session_state.get("last_followup_save") or get_last_followup_save_status()
        if followup_save:
            st.write("**AI 追问保存**")
            st.write(f"- 保存状态：{'成功' if followup_save.get('saved') else '未保存'}")
            st.write(f"- 保存位置：{'Supabase' if followup_save.get('backend') == 'supabase' else '本地 CSV'}")
            if followup_save.get("error"):
                st.write(f"- 保存说明：{followup_save.get('error')}")
        comment_status = st.session_state.get("family_comment_last_save") or get_last_family_comment_save_status()
        comment_read_status = get_last_family_comment_read_status()
        comment_backend = comment_status.get("backend") or get_storage_status().get("backend", "local_csv")
        comment_read_backend = comment_read_status.get("backend") or "local_csv"
        comment_backend_label = "Supabase" if comment_backend == "supabase" else "本地 CSV"
        comment_read_label = "Supabase" if comment_read_backend == "supabase" else "local_csv"
        st.write("**家庭观察记录**")
        save_state_label = "成功" if comment_status.get("saved") or comment_status.get("success") else "失败"
        st.write(f"- 最近一次观察记录保存状态：{save_state_label}")
        st.write(f"- 保存位置：{comment_backend_label}")
        st.write(f"- 当前读取来源：{comment_read_label}")
        st.write(f"- 最近读取到的观察记录数量：{st.session_state.get('family_comments_last_count', 0)}")
        st.write(f"- 最后一条保存状态：{comment_status.get('message', '')}")
        if comment_status.get("error"):
            st.write(f"- 保存失败原因：{comment_status.get('error')}")
        if comment_read_status.get("error"):
            st.write(f"- 读取失败原因：{comment_read_status.get('error')}")
        agent_context = agent_result.get("agent_context", {}) if agent_result else {}

        col_t1, col_t2 = st.columns(2)
        with col_t1:
            if st.button("测试 DeepSeek 追问接口", key="test_deepseek_followup_api"):
                if agent_context:
                    try:
                        st.session_state["followup_self_test"] = answer_followup_question(
                            agent_context, "1+1是多少"
                        )
                    except Exception as exc:  # noqa: BLE001
                        st.session_state["followup_self_test"] = {
                            "answer": "",
                            "source": "local_fallback",
                            "error": f"追问自检调用异常：{type(exc).__name__}",
                            "raw_error": f"{type(exc).__name__}: {exc}",
                            "call_path": "app.developer_debug_block test button (top-level except)",
                        }
                else:
                    st.session_state["followup_self_test"] = {
                        "answer": "",
                        "source": "local_fallback",
                        "error": "缺少本次体检上下文，请先完成一键智能体检",
                        "raw_error": "agent_context missing",
                        "call_path": "n/a",
                    }
        with col_t2:
            if st.button("DeepSeek 直连自检（绕过 followup）", key="test_deepseek_direct"):
                try:
                    from ai_report import deepseek_self_test as _ds_probe  # type: ignore
                    st.session_state["deepseek_direct_test"] = _ds_probe()
                except Exception as exc:  # noqa: BLE001
                    st.session_state["deepseek_direct_test"] = {
                        "ok": False,
                        "api_key_present": False,
                        "shared_call_deepseek_id": None,
                        "response_preview": "",
                        "error": f"deepseek_self_test 调用异常：{type(exc).__name__}",
                        "raw_error": f"{type(exc).__name__}: {exc}",
                    }
        self_test = st.session_state.get("followup_self_test")
        if self_test:
            st.write("**追问自检结果（answer_followup_question）**")
            st.write(f"- source: {self_test.get('source', '')}")
            st.write(f"- error: {self_test.get('error', '')}")
            raw = self_test.get("raw_error", "")
            if raw:
                st.code(raw, language="text")
            st.write(f"- call_path: {self_test.get('call_path', '')}")
            st.write(f"- answer: {self_test.get('answer', '')[:400]}")
        direct_test = st.session_state.get("deepseek_direct_test")
        if direct_test:
            st.write("**DeepSeek 直连自检结果（_call_deepseek 直接探测）**")
            st.write(f"- ok: {direct_test.get('ok', False)}")
            st.write(f"- api_key_present: {direct_test.get('api_key_present', False)}")
            st.write(f"- shared_call_deepseek_id: {direct_test.get('shared_call_deepseek_id', '')}")
            st.write(f"- response_preview: {direct_test.get('response_preview', '')}")
            st.write(f"- error: {direct_test.get('error', '')}")
            raw = direct_test.get("raw_error", "")
            if raw:
                st.code(raw, language="text")
            st.caption(
                "如果『直连自检』ok=True 但『追问自检』source=local_fallback，"
                "说明 DeepSeek 通的，问题在 _call_deepseek_followup 的 prompt 组装或 agent_context 序列化。"
            )
        debug_info = agent_result.get("debug_info", {})
        if debug_info:
            for key, value in debug_info.items():
                st.write(f"- {key}：{value}")
        for step in agent_result.get("debug_steps", []):
            st.write(f"- {step}")
        st.write(f"- saved_history: {agent_result.get('saved_history')}")
        st.write(f"- data_status: {agent_result.get('data_status')}")


def inspection_process_block(agent_result: dict[str, Any]) -> None:
    if not agent_result:
        return
    with st.expander("本次补充家庭情况", expanded=False):
        reverse_qa = _normalize_reverse_qa(agent_result.get("reverse_qa") or agent_result.get("agent_context", {}).get("reverse_qa"))
        st.write(f"- 半年内资金使用：{_reverse_label(reverse_qa['money_need_6m'], _MONEY_NEED_MAP)}")
        st.write(f"- 波动反应：{_reverse_label(reverse_qa['volatility_reaction'], _VOLATILITY_MAP)}")
        st.write(f"- 过往分歧：{reverse_qa.get('last_disagreement') or '未填写'}")


def history_replay_block(agent_result: dict[str, Any] | None) -> None:
    """历史体检回放：对比最近两次体检的风险变化。"""
    try:
        rows = load_recent_analysis_history(limit=5)
    except Exception:  # noqa: BLE001
        rows = []

    history_analysis: dict[str, Any] = {}
    if rows:
        history_analysis = analyze_history_changes(rows)
    elif agent_result:
        history_analysis = agent_result.get("history_analysis") or {}

    count = int(history_analysis.get("records_count", 0) or len(rows) or 0)
    summary = str(history_analysis.get("summary", "") or "")

    render_html(
        """
        <section class="block" style="padding:1rem 1rem 0.85rem;margin-bottom:0.9rem;">
            <div class="block-head" style="margin-bottom:.45rem;">
                <div>
                    <h2 class="block-title" style="font-size:1.15rem;">历史体检回放</h2>
                    <p class="block-subtitle">看最近几次体检里，分数、现金和主要风险有没有变化。</p>
                </div>
            </div>
        </section>
        """
    )

    if count == 0:
        st.info("历史记录还不够，先完成几次体检后，这里会显示风险变化。")
        return

    latest_date = format_datetime_for_display(history_analysis.get("latest_date", ""))
    if count == 1:
        st.info("目前只有一次体检记录，暂时无法比较变化。")
        st.caption(f"最近一次体检：{latest_date}")
        return

    previous_date = format_datetime_for_display(history_analysis.get("previous_date", ""))
    score_change = history_analysis.get("score_change")

    if score_change is None:
        trend_title = "评分变化暂时无法判断"
        trend_note = "历史记录里缺少完整评分，后续新体检会自动补齐。"
        trend_color = "#7a3e2e"
    elif score_change > 5:
        trend_title = f"评分比上次上升 {score_change:+.1f} 分"
        trend_note = "整体风险压力比上次低一些，但仍要看具体风险点。"
        trend_color = "#3f7d55"
    elif score_change < -5:
        trend_title = f"评分比上次下降 {score_change:.1f} 分"
        trend_note = "这次比上次更需要留意，先看新增风险和仓位变化。"
        trend_color = "#b94040"
    else:
        trend_title = f"评分基本持平（{score_change:+.1f} 分）"
        trend_note = "整体变化不大，重点看哪些风险仍然反复出现。"
        trend_color = "#8a6a2a"

    def _ratio_change_text(key: str, label: str) -> str:
        val = history_analysis.get(key)
        if val is None:
            return f"{label}：暂无对比"
        sign = "+" if float(val) >= 0 else ""
        return f"{label}：{sign}{float(val) * 100:.1f} 个百分点"

    change_lines = [
        _ratio_change_text("cash_ratio_change", "现金比例"),
        _ratio_change_text("stock_ratio_change", "股票/基金仓位"),
        _ratio_change_text("max_position_ratio_change", "最大单只占比"),
    ]

    render_html(
        f"""
        <div style="border:1px solid var(--border);border-radius:14px;background:var(--surface);
                    padding:1rem 1rem 0.85rem;margin-bottom:0.85rem;">
            <div style="display:flex;align-items:flex-start;gap:0.75rem;">
                <div style="width:0.7rem;height:0.7rem;border-radius:999px;background:{trend_color};
                            margin-top:0.35rem;flex-shrink:0;"></div>
                <div style="min-width:0;">
                    <div style="font-size:1rem;font-weight:800;color:var(--text);line-height:1.35;">
                        {html_escape(trend_title)}
                    </div>
                    <p style="margin:0.25rem 0 0;color:var(--text-2);font-size:0.82rem;line-height:1.55;">
                        {html_escape(trend_note)}
                    </p>
                    <p style="margin:0.45rem 0 0;color:var(--text-3);font-size:0.74rem;">
                        本次：{html_escape(latest_date)}　上次：{html_escape(previous_date)}
                    </p>
                </div>
            </div>
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:0.45rem;margin-top:0.85rem;">
                {''.join(
                    f'<div style="border:1px solid var(--border);border-radius:10px;padding:0.55rem 0.5rem;background:var(--bg-2);">'
                    f'<div style="font-size:0.72rem;color:var(--text-3);line-height:1.35;">{html_escape(line.split("：")[0])}</div>'
                    f'<div style="font-size:0.85rem;font-weight:700;color:var(--text);line-height:1.4;">{html_escape(line.split("：", 1)[1])}</div>'
                    f'</div>'
                    for line in change_lines
                )}
            </div>
        </div>
        """
    )

    risk_changes = history_analysis.get("risk_factor_changes") or []
    new_risks = [str(c.get("text", "")) for c in risk_changes if c.get("type") == "new" and c.get("text")]
    resolved_risks = [str(c.get("text", "")) for c in risk_changes if c.get("type") == "resolved" and c.get("text")]
    watch_points = [str(wp) for wp in (history_analysis.get("watch_points") or []) if wp]
    family_changes = [str(fc) for fc in (history_analysis.get("family_focus_changes") or []) if fc]

    focus_items: list[tuple[str, str, str]] = []
    if new_risks:
        focus_items.append(("新出现", new_risks[0][:100], "#b94040"))
    if resolved_risks:
        focus_items.append(("已改善", resolved_risks[0][:100], "#3f7d55"))
    if watch_points:
        focus_items.append(("仍需关注", watch_points[0][:100], "#8a6a2a"))
    if family_changes:
        focus_items.append(("家庭沟通", family_changes[0][:100], "#7a3e2e"))
    if not focus_items and summary:
        focus_items.append(("回放结论", summary[:120], "#7a3e2e"))

    if focus_items:
        rows_html = "".join(
            f"""
            <li style="display:flex;gap:0.6rem;align-items:flex-start;padding:0.55rem 0;
                       border-bottom:1px solid var(--border);">
                <span style="font-size:0.72rem;font-weight:800;color:#fff;background:{color};
                             border-radius:999px;padding:0.14rem 0.55rem;white-space:nowrap;">{html_escape(label)}</span>
                <span style="font-size:0.84rem;color:var(--text);line-height:1.55;">{html_escape(text)}</span>
            </li>
            """
            for label, text, color in focus_items
        )
        render_html(
            f"""
            <div style="border:1px solid var(--border);border-radius:14px;background:var(--surface);
                        padding:0.45rem 0.9rem;margin-bottom:0.85rem;">
                <div style="font-size:0.9rem;font-weight:800;color:var(--text);padding:0.35rem 0 0.15rem;">
                    这次回放重点
                </div>
                <ul style="list-style:none;margin:0;padding:0;">{rows_html}</ul>
            </div>
            """
        )

    timeline_rows = rows[:5]
    if timeline_rows:
        with st.expander("最近 5 次体检轨迹", expanded=False):
            for row in timeline_rows:
                full = row.get("full_agent_result") if isinstance(row.get("full_agent_result"), dict) else {}
                portfolio = full.get("portfolio_summary") if isinstance(full.get("portfolio_summary"), dict) else {}
                created_at = format_datetime_for_display(row.get("created_at") or row.get("分析时间"))
                score = row.get("risk_score") or row.get("综合评分") or ""
                level = str(row.get("risk_level") or row.get("风险等级") or "")
                cash_ratio = float(row.get("cash_ratio") or portfolio.get("cash_ratio") or 0)
                stock_ratio = float(row.get("stock_ratio") or portfolio.get("stock_ratio") or 0)
                max_ratio = float(row.get("max_position_ratio") or portfolio.get("max_single_ratio") or 0)
                st.caption(
                    f"{created_at}｜评分 {score}｜{level}｜现金 {percent(cash_ratio)}｜"
                    f"持仓 {percent(stock_ratio)}｜最大单只 {percent(max_ratio)}"
                )

    if summary:
        st.info(summary)


def _level_icon(level: str) -> str:
    s = str(level)
    if "红" in s:
        return "🔴"
    if "黄" in s:
        return "🟡"
    if "绿" in s:
        return "🟢"
    return "⚪"


def history_records_block() -> None:
    with st.expander("历史体检记录", expanded=False):
        status = get_storage_status()
        st.caption(status.get("message", "当前使用本地 CSV 兜底"))
        try:
            rows = load_recent_analysis_history(limit=10)
        except Exception:  # noqa: BLE001
            rows = []
        if not rows:
            st.info("暂无历史体检记录。完成一次一键智能体检后，这里会显示最近记录。")
            return
        for idx, row in enumerate(rows):
            created_at = format_datetime_for_display(row.get("created_at") or row.get("分析时间"))
            score = row.get("risk_score") or row.get("综合评分") or ""
            level = str(row.get("risk_level") or row.get("风险等级") or "")
            cash_ratio = float(row.get("cash_ratio") or row.get("现金比例") or 0)
            stock_ratio = float(row.get("stock_ratio") or row.get("股票仓位") or 0)
            holdings_summary = str(row.get("holdings_summary") or "")

            # full_agent_result is already a dict (deserialized by storage._normalize_analysis_row)
            full: dict[str, Any] = row.get("full_agent_result") or {}
            if not isinstance(full, dict):
                full = {}

            ai_report = str(full.get("ai_report") or row.get("ai_report_summary") or "").strip()
            main_risks_raw = full.get("main_risks") or row.get("main_risks") or []
            if isinstance(main_risks_raw, str):
                try:
                    import json as _json
                    main_risks_raw = _json.loads(main_risks_raw)
                except Exception:  # noqa: BLE001
                    main_risks_raw = [main_risks_raw] if main_risks_raw else []
            main_risks: list[str] = [str(r) for r in (main_risks_raw or []) if r]

            icon = _level_icon(level)
            label = f"{icon} {created_at or '体检记录'}｜评分 {score}｜{level}"
            with st.expander(label, expanded=False):
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.metric("综合评分", f"{score} 分")
                with c2:
                    st.metric("现金比例", percent(cash_ratio))
                with c3:
                    st.metric("股票仓位", percent(stock_ratio))

                if holdings_summary:
                    st.caption(f"持仓：{holdings_summary[:160]}")

                if main_risks:
                    st.markdown("**主要风险**")
                    for risk in main_risks[:6]:
                        st.caption(f"• {risk[:120]}")

                if ai_report:
                    st.markdown("---")
                    st.markdown("**AI 风险说明**")
                    st.markdown(ai_report)
                elif idx == 0:
                    st.caption("此次记录未保存完整 AI 说明（可能是旧格式记录）。")


def discussion_entry_block(run_id: str = "") -> None:
    """家庭观察记录入口卡片（主结果页显示，点击跳入专属子页）。"""
    try:
        comments: list[dict[str, Any]] = st.session_state.get("family_comments_cache") or []
        if not comments:
            comments = load_recent_family_comments(limit=5)
            st.session_state["family_comments_cache"] = comments
    except Exception:  # noqa: BLE001
        comments = []
    count = len(comments)
    subtitle = (
        f"已有 {count} 条家庭观察，点击进入查看或新增。"
        if count
        else "记录家人对这次体检的看法，方便沟通和分歧检测。"
    )
    render_html(
        f"""
        <section class="block" style="padding:1rem 1.1rem;">
            <div class="block-head" style="margin-bottom:.35rem;">
                <div>
                    <h2 class="block-title" style="font-size:1.18rem;">家庭观察记录</h2>
                    <p class="block-subtitle">{html_escape(subtitle)}</p>
                </div>
            </div>
        </section>
        """
    )
    if st.button("记录家人看法 →", use_container_width=True, key="open_comments_view"):
        st.session_state["_comments_run_id"] = run_id
        st.session_state["active_view"] = "comments"
        st.rerun()


def comments_page(agent_result: dict[str, Any]) -> None:
    """家庭观察记录专属子页。"""
    if st.button("← 继续深入", use_container_width=True, key="back_from_comments_view"):
        st.session_state["active_view"] = "followup"
        st.rerun()
    run_id = str(st.session_state.get("_comments_run_id", "") or
                 (agent_result.get("run_id", "") if agent_result else ""))
    discussion_block(run_id=run_id)


def ai_report_page(agent_result: dict[str, Any]) -> None:
    """第 2 步：AI 风险说明页（从体检结论点进来，报告 + 模式切换 + 进入追问）。"""
    agent_context = agent_result.get("agent_context", {}) if agent_result else {}

    if st.button("← 体检结论", key="back_from_ai_report"):
        st.session_state["active_view"] = "analysis"
        st.rerun()
    render_html(
        '<p style="font-size:0.72rem;color:var(--text-3);margin:0 0 0.6rem;">'
        '体检结论 &rsaquo; AI 风险说明</p>'
    )

    if not agent_result:
        st.info("请先完成一次一键智能体检，再查看 AI 风险说明。")
        return

    render_html("""
    <div style="padding:0.1rem 0 0.8rem;">
        <h2 style="font-size:1.2rem;font-weight:700;color:var(--text);margin:0 0 0.12rem;">
            本次 AI 风险说明
        </h2>
        <p style="font-size:0.82rem;color:var(--text-3);margin:0;">
            基于本次体检数据生成，不构成买卖建议。
        </p>
    </div>
    """)

    mode = st.radio(
        "报告模式",
        options=REPORT_MODES,
        horizontal=True,
        key="report_mode",
    )
    display_report = str(agent_result.get("ai_report", "") or "暂无风险说明。")
    report_source = str(agent_result.get("report_source", "local_fallback") or "local_fallback")
    cached_mode = str(agent_result.get("report_mode", DEFAULT_REPORT_MODE) or DEFAULT_REPORT_MODE)
    if agent_context and mode != cached_mode:
        with st.spinner("正在按新的报告模式生成说明..."):
            report_text, report_source, dinner_talk = _unpack_agent_report(
                generate_agent_report(agent_context, mode)
            )
        display_report = report_text
        agent_result["ai_report"] = display_report
        agent_result["dinner_talk"] = dinner_talk
        agent_result["report_source"] = report_source
        agent_result["report_mode"] = mode
        agent_context["ai_report"] = display_report
        agent_context["dinner_talk"] = dinner_talk
        agent_context["report_source"] = report_source
        agent_context["report_mode"] = mode
        agent_result["agent_context"] = agent_context
        st.session_state["agent_result"] = agent_result
    st.caption(f"报告来源：{_report_source_label(report_source)}")

    if st.button("看完了，开始 AI 追问 →", use_container_width=True,
                 key="goto_followup_from_report", type="primary"):
        st.session_state["active_view"] = "followup"
        st.rerun()

    render_html('<div class="card" style="padding:1.4rem;margin-top:0.6rem;">')
    st.markdown(display_report)
    render_html("</div>")


def followup_page(agent_result: dict[str, Any]) -> None:
    agent_context = agent_result.get("agent_context", {}) if agent_result else {}
    if st.button("← AI 风险说明", key="back_to_analysis_view"):
        st.session_state["active_view"] = "ai_report"
        st.rerun()
    render_html(
        '<p style="font-size:0.72rem;color:var(--text-3);margin:0 0 0.6rem;">'
        '体检结论 &rsaquo; AI 风险说明 &rsaquo; AI 追问</p>'
    )
    if not agent_context:
        st.info("请先完成一次一键智能体检，再继续追问。")
        return

    _fup_answers = list(st.session_state.get("followup_answers", []))
    _has_followup = bool(_fup_answers)
    _fup_ans_n = len(_fup_answers)
    _fup_run_id = str(agent_result.get("run_id", "") if agent_result else "")
    _cta_label = (
        f"追问完成（{_fup_ans_n} 条），记录家人看法 →"
        if _has_followup
        else "跳过追问，直接记录家人看法 →"
    )
    if st.button(
        _cta_label,
        use_container_width=True,
        key="fup_to_guided_comment",
        type="primary",
    ):
        st.session_state["_guided_run_id"] = _fup_run_id
        for _k in ("guided_step", "guided_member", "guided_focus", "guided_focus_label",
            "guided_stance", "guided_stance_label", "guided_text", "guided_save_result"):
            st.session_state.pop(_k, None)
        st.session_state["guided_step"] = 1
        st.session_state["active_view"] = "guided_comment"
        st.rerun()

    _fup_mode = agent_result.get("report_mode", DEFAULT_REPORT_MODE) or DEFAULT_REPORT_MODE
    reverse_qa_block(agent_result, agent_context, _fup_mode)
    followup_block(agent_context)
    with st.expander("追问历史保存情况", expanded=False):
        latest_status = st.session_state.get("last_followup_save") or get_last_followup_save_status()
        backend = latest_status.get("backend", "local_csv")
        backend_label = "Supabase 云数据库" if backend == "supabase" else "本地 CSV"
        saved_label = "已保存" if latest_status.get("saved") else "未保存"
        st.write(f"- 最近一次保存状态：{saved_label}")
        st.write(f"- 保存位置：{backend_label}")
        if latest_status.get("error"):
            st.write(f"- 保存说明：{latest_status.get('error')}")
        try:
            recent = load_recent_followup_history(limit=5)
        except Exception:  # noqa: BLE001
            recent = []
        st.write(f"- 最近读取到的追问记录数量：{len(recent)}")
        if recent:
            st.caption("最近保存的追问：")
        for row in recent[:3]:
            created_at = format_datetime_for_display(row.get("created_at"))
            st.write(f"- {created_at}｜{row.get('question', '')}")


def history_page(agent_result: dict[str, Any]) -> None:
    if st.button("← 体检结论", key="back_from_history_view"):
        st.session_state["active_view"] = "analysis"
        st.rerun()
    render_html(
        """
        <div style="padding:0.25rem 0 0.85rem;">
            <p style="font-size:0.72rem;color:var(--text-3);margin:0 0 0.25rem;">
                体检结论 &rsaquo; 历史
            </p>
            <h2 style="font-size:1.2rem;font-weight:700;color:var(--text);margin:0 0 0.12rem;">
                历史体检
            </h2>
            <p style="font-size:0.82rem;color:var(--text-3);margin:0;">
                回看最近记录、评分变化和仍需关注的风险点。
            </p>
        </div>
        """
    )
    history_replay_block(agent_result)
    history_records_block()


def next_steps_entry_block(agent_result: dict[str, Any]) -> None:
    """智能引导卡 — 体检结论底部，感知上下文，引导进入追问/记录/历史子页。"""
    followup_answers = list(st.session_state.get("followup_answers", []))
    followup_count = len(followup_answers)
    try:
        comments: list[dict[str, Any]] = st.session_state.get("family_comments_cache") or []
        if not comments:
            comments = load_recent_family_comments(limit=5)
            st.session_state["family_comments_cache"] = comments
    except Exception:  # noqa: BLE001
        comments = []
    comment_count = len(comments)

    followup_chip = f"{followup_count} 条追问" if followup_count else "可追问 AI"
    comment_chip  = f"{comment_count} 条记录" if comment_count else "记录家人看法"

    render_html(f"""
    <div style="margin:1rem 0 0.5rem;border-radius:14px;
                border:1.5px solid #e8c4b2;background:#fff9f6;
                padding:1rem 1.1rem 0.9rem;">
        <p style="font-size:0.73rem;font-weight:600;letter-spacing:.06em;
                  color:#7a3e2e;text-transform:uppercase;margin:0 0 0.5rem;">
            Agent · 下一步
        </p>
        <p style="font-size:0.97rem;font-weight:700;color:var(--text);margin:0 0 0.35rem;">
            结论已生成，继续深入了解这次风险
        </p>
        <div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-bottom:0;">
            <span style="font-size:0.78rem;padding:0.28rem 0.75rem;border-radius:20px;
                         background:rgba(122,62,46,0.09);color:#7a3e2e;font-weight:600;">
                📋&nbsp;AI 风险说明
            </span>
            <span style="font-size:0.78rem;padding:0.28rem 0.75rem;border-radius:20px;
                         background:rgba(122,62,46,0.09);color:#7a3e2e;font-weight:600;">
                💬&nbsp;{html_escape(followup_chip)}
            </span>
            <span style="font-size:0.78rem;padding:0.28rem 0.75rem;border-radius:20px;
                         background:rgba(122,62,46,0.09);color:#7a3e2e;font-weight:600;">
                👨‍👩‍👧&nbsp;{html_escape(comment_chip)}
            </span>
        </div>
    </div>
    """)
    if st.button("查看 AI 风险说明 →", use_container_width=True,
                 key="open_ai_report_from_next", type="primary"):
        st.session_state["active_view"] = "ai_report"
        st.rerun()


def guided_comment_page(agent_result: dict[str, Any]) -> None:
    """向导式家庭看法记录 — 分步引导（共 3 步 + 完成确认）。"""
    step = int(st.session_state.get("guided_step", 1))
    run_id = str(
        st.session_state.get("_guided_run_id", "")
        or (agent_result.get("run_id", "") if agent_result else "")
    )

    def _clear_wizard() -> None:
        for _k in (
            "guided_step", "guided_member", "guided_focus", "guided_focus_label",
            "guided_stance", "guided_stance_label", "guided_text",
            "guided_save_result", "gw_extra_text",
        ):
            st.session_state.pop(_k, None)

    # ── 返回按钮（步骤 1~3 可以返回） ──────────────────────────
    if step < 4:
        if st.button("← 返回 AI 追问", key="guided_back_btn"):
            _clear_wizard()
            st.session_state["active_view"] = "followup"
            st.rerun()
        render_html(
            '<p style="font-size:0.72rem;color:var(--text-3);margin:0 0 0.3rem;">'
            '体检结论 &rsaquo; AI 风险说明 &rsaquo; AI 追问 &rsaquo; 记录家人看法</p>'
        )

    # ── 进度指示器（步骤 1~3）──────────────────────────────────
    if step <= 3:
        _step_labels = ["谁来记录", "关注什么", "整体倾向"]
        _chips = ""
        for _i, _lbl in enumerate(_step_labels):
            _is_active = (_i + 1 == step)
            _bg    = "#7a3e2e" if _is_active else "#ece5e1"
            _color = "#fff"    if _is_active else "#9e8070"
            _fw    = "700"     if _is_active else "500"
            _chips += (
                '<span style="display:inline-block;padding:0.22rem 0.72rem;'
                'border-radius:20px;font-size:0.72rem;font-weight:' + _fw + ';'
                'background:' + _bg + ';color:' + _color + ';margin:0 0.15rem;">'
                + html_escape(_lbl) + '</span>'
            )
        render_html('<div style="margin:0.3rem 0 1.1rem;">' + _chips + '</div>')

    # ── 步骤 1：谁来记录 ────────────────────────────────────────
    if step == 1:
        render_html(
            '<p style="font-size:1.05rem;font-weight:700;color:var(--text);'
            'margin:0 0 0.85rem;">这次是谁来记录看法？</p>'
        )
        _c1, _c2 = st.columns(2)
        for _i, _opt in enumerate(_GW_MEMBER_OPTIONS):
            with (_c1 if _i % 2 == 0 else _c2):
                if st.button(_opt, use_container_width=True, key=f"gw_m_{_i}"):
                    st.session_state["guided_member"] = _opt
                    st.session_state["guided_step"] = 2
                    st.rerun()
        render_html(
            '<p style="font-size:0.82rem;color:var(--text-3);margin:0.75rem 0 0.3rem;">或者自填：</p>'
        )
        _custom = st.text_input(
            "自填成员",
            placeholder="例如：奶奶、全家讨论…",
            key="gw_member_custom_input",
            label_visibility="collapsed",
        )
        if st.button("确认并下一步 →", use_container_width=True, key="gw_m_custom_confirm"):
            st.session_state["guided_member"] = (_custom.strip() or "其他")
            st.session_state["guided_step"] = 2
            st.rerun()

    # ── 步骤 2：关注什么 ────────────────────────────────────────
    elif step == 2:
        _member = html_escape(str(st.session_state.get("guided_member", "") or ""))
        render_html(
            '<p style="font-size:1.05rem;font-weight:700;color:var(--text);'
            'margin:0 0 0.85rem;">' + _member + ' 最关注哪一块？</p>'
        )
        _c1, _c2 = st.columns(2)
        for _i, (_lbl, _val) in enumerate(_GW_FOCUS_OPTIONS):
            with (_c1 if _i % 2 == 0 else _c2):
                if st.button(_lbl, use_container_width=True, key=f"gw_f_{_i}"):
                    st.session_state["guided_focus"] = _val
                    st.session_state["guided_focus_label"] = _lbl
                    st.session_state["guided_step"] = 3
                    st.rerun()

    # ── 步骤 3：整体倾向 → 可选文字 → 保存 ─────────────────────
    elif step == 3:
        _member      = html_escape(str(st.session_state.get("guided_member", "") or ""))
        _focus_label = html_escape(str(st.session_state.get("guided_focus_label", "") or ""))
        _stance_set  = bool(st.session_state.get("guided_stance"))

        if not _stance_set:
            # 3a：选择立场
            render_html(
                '<p style="font-size:1.05rem;font-weight:700;color:var(--text);margin:0 0 0.85rem;">'
                + _member
                + ' 对<span style="color:#7a3e2e;"> '
                + _focus_label
                + '</span> 的整体倾向是？</p>'
            )
            _sc1, _sc2, _sc3 = st.columns(3)
            for _i, (_lbl, _val) in enumerate(_GW_STANCE_OPTIONS):
                with [_sc1, _sc2, _sc3][_i]:
                    if st.button(_lbl, use_container_width=True, key=f"gw_s_{_i}"):
                        st.session_state["guided_stance"] = _val
                        st.session_state["guided_stance_label"] = _lbl
                        st.rerun()
        else:
            # 3b：立场已选，补充文字 + 保存
            _stance_label = html_escape(str(st.session_state.get("guided_stance_label", "") or ""))
            render_html(
                '<div style="background:#fff9f6;border:1.5px solid #e8c4b2;'
                'border-radius:12px;padding:0.85rem 1rem;margin-bottom:0.85rem;">'
                '<p style="font-size:0.75rem;color:var(--text-3);margin:0 0 0.35rem;">已选择</p>'
                '<p style="font-size:0.97rem;font-weight:600;color:var(--text);margin:0;">'
                + _member + '&nbsp;·&nbsp;' + _focus_label + '&nbsp;·&nbsp;' + _stance_label
                + '</p></div>'
                '<p style="font-size:0.88rem;color:var(--text-3);margin:0 0 0.4rem;">'
                '还有什么想补充的吗？（选填）</p>'
            )
            st.text_area(
                "补充说明",
                placeholder="例如：觉得现金再多一点会更安心…",
                height=90,
                key="gw_extra_text",
                label_visibility="collapsed",
            )
            st.caption("记录仅供家庭参考，不作为任何操作建议。")
            if st.button("保存这条记录 ✓", use_container_width=True, key="gw_save_btn"):
                _text_val = str(st.session_state.get("gw_extra_text", "") or "").strip()
                st.session_state["guided_text"] = _text_val
                _comment: dict[str, Any] = {
                    "member":       str(st.session_state.get("guided_member", "") or ""),
                    "comment_type": "观察",
                    "focus":        str(st.session_state.get("guided_focus", "other") or "other"),
                    "stance":       str(st.session_state.get("guided_stance", "neutral") or "neutral"),
                    "content":      _text_val,
                    "run_id":       run_id,
                }
                try:
                    _save_res = save_family_comment(_comment)
                    st.session_state["guided_save_result"] = _save_res
                    st.session_state["family_comment_last_save"] = get_last_family_comment_save_status()
                    st.session_state.pop("family_comments_cache", None)
                    st.session_state.pop("family_comments", None)
                except Exception as _exc:  # noqa: BLE001
                    st.session_state["guided_save_result"] = {
                        "success": False,
                        "backend": "local_csv",
                        "error":   str(_exc)[:80],
                    }
                st.session_state["guided_step"] = 4
                st.rerun()

    # ── 步骤 4：完成确认 ────────────────────────────────────────
    elif step == 4:
        _save_result  = dict(st.session_state.get("guided_save_result") or {})
        _member_raw   = str(st.session_state.get("guided_member", "") or "")
        _focus_raw    = str(st.session_state.get("guided_focus_label", "") or "")
        _stance_raw   = str(st.session_state.get("guided_stance_label", "") or "")
        _extra_raw    = str(st.session_state.get("guided_text", "") or "")
        _saved_ok     = bool(_save_result.get("success"))
        _backend      = str(_save_result.get("backend", "local_csv") or "local_csv")
        _backend_lbl  = "云端" if _backend == "supabase" else "本地"
        _icon = "✅" if _saved_ok else "⚠️"
        _msg  = ("记录已保存到" + _backend_lbl) if _saved_ok else "保存时遇到问题"

        _extra_html = ""
        if _extra_raw:
            _extra_html = (
                '<p style="font-size:0.85rem;color:var(--text-3);margin:0.3rem 0 0;">'
                + html_escape(_extra_raw[:120]) + "</p>"
            )
        render_html(
            '<div style="text-align:center;padding:1.1rem 0 0.6rem;">'
            '<p style="font-size:2rem;margin:0 0 0.35rem;">' + _icon + '</p>'
            '<p style="font-size:1.05rem;font-weight:700;color:var(--text);margin:0 0 0.2rem;">'
            + html_escape(_msg) + '</p>'
            '</div>'
            '<div style="background:#fff9f6;border:1px solid #e8c4b2;border-radius:12px;'
            'padding:0.85rem 1rem;margin:0.5rem 0 1rem;">'
            '<p style="font-size:0.75rem;color:var(--text-3);margin:0 0 0.4rem;">这条记录内容</p>'
            '<p style="font-size:0.95rem;font-weight:600;color:var(--text);margin:0;">'
            + html_escape(_member_raw)
            + '&nbsp;·&nbsp;' + html_escape(_focus_raw)
            + '&nbsp;·&nbsp;' + html_escape(_stance_raw)
            + '</p>'
            + _extra_html
            + '</div>'
        )
        _ca, _cb = st.columns(2)
        with _ca:
            if st.button("再记录一条", use_container_width=True, key="gw_another"):
                _clear_wizard()
                st.session_state["guided_step"] = 1
                st.rerun()
        with _cb:
            if st.button("返回填仓页面", use_container_width=True, key="gw_go_home"):
                _clear_wizard()
                st.session_state.pop("analysis", None)
                st.session_state.pop("stocks", None)
                st.session_state.pop("fetch_warnings", None)
                st.rerun()


def records_hub_page(agent_result: dict[str, Any]) -> None:
    """追问 / 家庭记录 / 历史 汇总子页面（观察记录在追问后自动出现）。"""
    if st.button("← 返回体检结论", key="records_hub_back_btn"):
        st.session_state["active_view"] = "analysis"
        st.rerun()
    render_html(
        '<p style="font-size:0.72rem;color:var(--text-3);margin:0 0 0.5rem;">'
        '体检结论 &rsaquo; 继续深入</p>'
    )
    render_html("""
    <div style="padding:0.3rem 0 0.9rem;">
        <h2 style="font-size:1.2rem;font-weight:700;color:var(--text);margin:0 0 0.15rem;">
            继续深入这次体检
        </h2>
        <p style="font-size:0.82rem;color:var(--text-3);margin:0;">
            先追问 AI，再记录家人看法
        </p>
    </div>
    """)
    agent_context = (agent_result.get("agent_context") or {}) if agent_result else {}
    run_id = str(agent_result.get("run_id", "") or "") if agent_result else ""
    followup_entry_block(agent_result, agent_context)
    # ── 追问后自动出现：家庭观察记录入口 ─────────────────────────
    _fup_answers = list(st.session_state.get("followup_answers", []))
    if _fup_answers:
        _fup_n = len(_fup_answers)
        render_html(
            '<div style="background:#fff9f6;border:1.5px solid #e8c4b2;border-radius:14px;'
            'padding:0.9rem 1rem;margin:0.5rem 0 0;">'
            '<p style="font-size:0.72rem;font-weight:600;letter-spacing:.06em;'
            'color:#7a3e2e;text-transform:uppercase;margin:0 0 0.3rem;">Agent · 下一步</p>'
            '<p style="font-size:0.97rem;font-weight:700;color:var(--text);margin:0 0 0.3rem;">'
            + '已追问 ' + str(_fup_n) + ' 条，记录一下家人看法？'
            + '</p>'
            '<p style="font-size:0.82rem;color:var(--text-3);margin:0;">'
            '30 秒完成，自动保存，方便以后对比家庭意见变化。</p>'
            '</div>'
        )
        if st.button("开始记录家人看法 →", use_container_width=True, key="hub_auto_guided"):
            st.session_state["_guided_run_id"] = run_id
            for _k in ("guided_step", "guided_member", "guided_focus", "guided_focus_label",
                       "guided_stance", "guided_stance_label", "guided_text", "guided_save_result"):
                st.session_state.pop(_k, None)
            st.session_state["guided_step"] = 1
            st.session_state["active_view"] = "guided_comment"
            st.rerun()
    history_replay_block(agent_result)
    history_records_block()


def analysis_page() -> None:
    analysis = st.session_state["analysis"]
    fetch_warnings = st.session_state.get("fetch_warnings", [])
    agent_result = st.session_state.get("agent_result", {})
    _active = st.session_state.get("active_view", "analysis")
    if _active == "followup":
        followup_page(agent_result)
        render_html(f'<div class="page-foot">{REPORT_DISCLAIMER}</div>')
        return
    if _active == "history":
        history_page(agent_result)
        render_html(f'<div class="page-foot">{REPORT_DISCLAIMER}</div>')
        return
    if _active == "comments":
        comments_page(agent_result)
        render_html(f'<div class="page-foot">{REPORT_DISCLAIMER}</div>')
        return
    if _active == "guided_comment":
        guided_comment_page(agent_result)
        render_html(f'<div class="page-foot">{REPORT_DISCLAIMER}</div>')
        return
    if _active == "records":
        followup_page(agent_result)
        render_html(f'<div class="page-foot">{REPORT_DISCLAIMER}</div>')
        return
    if _active == "ai_report":
        ai_report_page(agent_result)
        render_html(f'<div class="page-foot">{REPORT_DISCLAIMER}</div>')
        return
    agent_result_block(agent_result)

    # ── 体检过程 / 调试（折叠，不占主流程空间）──────────────────
    with st.expander("⚙️ 体检过程详情", expanded=False):
        inspection_process_block(agent_result)
        for warning in fetch_warnings:
            if "本地缓存" in str(warning) or "实时行情模块" in str(warning):
                st.info(warning)
            else:
                st.warning(warning)
    developer_debug_block(agent_result)
    render_html(f'<div class="page-foot">{REPORT_DISCLAIMER}</div>')


init_state()
inject_css()
site_header()
top_toolbar()

if "analysis" in st.session_state:
    analysis_page()
else:
    home_page()
