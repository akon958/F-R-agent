from __future__ import annotations

import json
import os
import random
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


def get_dynamic_questions(agent_context: dict[str, Any]) -> list[str]:
    """根据 agent_context 生成 6 个最相关的追问问题。

    每个槽位准备 3 个措辞变体，用 random.choice 随机选一个：
    - 相同持仓多次体检，问题措辞会有变化
    - 调用方应将结果缓存到 session_state，避免每次 rerun 都重新随机
    - 关键词设计保证 answer_followup_question 能正确路由
    """
    random.seed()  # 每次调用都从系统熵重新种随机数，避免跨 session 重复
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

    # ── 槽 1：现金相关（路由关键词："现金" 或 "备用金"）───────────
    if cash_ratio < 0.10:
        opts = [
            f"现金只剩 {cash_pct}，备用金够用吗？",
            f"家里现金只有 {cash_pct}，会不会太少了？",
            f"现金比例 {cash_pct}，遇到急用钱能撑住吗？",
        ]
    elif cash_ratio < 0.15:
        opts = [
            f"现金比例 {cash_pct} 偏低，需要担心吗？",
            f"现金只有 {cash_pct}，够应对突发支出吗？",
            f"备用金 {cash_pct} 是否太薄了？",
        ]
    elif cash_ratio >= 0.45:
        opts = [
            f"现金留了 {cash_pct}，是不是太保守了？",
            f"现金比例 {cash_pct}，还需要保留这么多吗？",
            f"家里 {cash_pct} 是现金，这样合理吗？",
        ]
    else:
        opts = [
            "现金比例怎么看？",
            "家里留多少现金比较合适？",
            "现金比例对这次体检影响大吗？",
        ]
    questions.append(random.choice(opts))

    # ── 槽 2：持仓集中度（路由关键词："集中" / "占...%" / "标的" / "哪只" / "一只"）──
    if top_name and max_pos >= 0.40:
        opts = [
            f"{top_name} 占了 {top_pct}，集中度高有什么风险？",
            f"最大持仓 {top_name} 占 {top_pct}，该怎么看？",
            f"哪只标的占比最高（{top_pct}）？需要重点关注吗？",
        ]
    elif top_name and max_pos >= 0.25:
        opts = [
            f"{top_name} 占比最高（{top_pct}），需要重点关注吗？",
            f"哪只标的目前持仓比例最重？",
            f"持仓里 {top_name} 这只标的占比最大，有风险吗？",
        ]
    elif len(holdings) == 1:
        opts = [
            "只有一只标的，风险是不是太集中了？",
            "只持有一只，集中度风险怎么看？",
            "单只标的持仓和多只持仓有什么区别？",
        ]
    else:
        opts = [
            "哪只标的最需要关注？",
            "这些持仓里哪只标的最需要盯着看？",
            "持仓里有没有特别需要关注的标的？",
        ]
    questions.append(random.choice(opts))

    # ── 槽 3：PE/PB（路由关键词："PE" 或 "PB"）──────────────────
    if valuation_missing:
        opts = [
            "PE/PB 数据缺失，这次体检受影响吗？",
            "没有 PE/PB 数据，结论还准确吗？",
            "PE/PB 缺失会带来哪些判断盲区？",
        ]
    else:
        opts = [
            "PE/PB 对这次判断有什么帮助？",
            "PE/PB 数据在体检里起什么作用？",
            "这次 PE/PB 数据说明了什么？",
        ]
    questions.append(random.choice(opts))

    # ── 槽 4：数据完整性（路由关键词："数据"+"缺"/"影响" 或 "财务"+"判断"）──
    if finance_missing:
        opts = [
            "财务数据有缺失，还能判断公司好坏吗？",
            "财务数据不全，对体检判断有多大影响？",
            "数据缺失的情况下，体检结论能信吗？",
        ]
    else:
        opts = [
            "数据缺失会影响判断吗？",
            "这次体检数据缺失了哪些内容？",
            "数据完不完整，对体检结论影响大吗？",
        ]
    questions.append(random.choice(opts))

    # ── 槽 5：风险原因（路由关键词："评分"/"仓位"/"继续观察"/"需要"+"观察"）──
    if risk_score < 50:
        opts = [
            f"评分 {risk_score} 分偏低，主要原因是什么？",
            f"这次评分只有 {risk_score} 分，说明了什么？",
            f"评分 {risk_score} 分，哪些方面拉低了分数？",
        ]
    elif stock_ratio >= 0.85:
        opts = [
            f"股票/基金仓位已达 {stock_pct}，算重仓吗？",
            f"仓位 {stock_pct}，遇到市场大波动怎么看？",
            f"仓位这么重（{stock_pct}），风险怎么评估？",
        ]
    else:
        opts = [
            "为什么这个组合还需要继续观察？",
            "体检完了，还需要继续观察哪些方面？",
            "这个组合为什么不能就此放心？",
        ]
    questions.append(random.choice(opts))

    # ── 槽 6：给爸妈总结（路由关键词："一句话"）─────────────────
    opts = [
        "给爸妈一句话怎么说？",
        "用一句话总结这次体检，怎么说？",
        "爸妈看这个结果，一句话能记住什么？",
        "如果只说一句话，爸妈最该知道什么？",
    ]
    questions.append(random.choice(opts))

    return questions


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
    disclaimer_token = "__FIXED_DISCLAIMER__"
    safe = text.replace(DISCLAIMER, disclaimer_token)
    replacements = {
        "买入": "继续观察",
        "卖出": "重点复盘",
        "加仓": "增加投入前先讨论",
        "减仓": "控制集中度",
        "推荐": "提示",
        "强烈": "明显",
        "抄底": "低位判断",
        "必涨": "确定上涨",
        "一定赚钱": "确定有收益",
        "马上操作": "立刻处理",
        "预测涨跌": "判断短期方向",
        "我们可能需要慢慢调整": "后续讨论时可以重点关注这一点",
    }
    for old, new in replacements.items():
        safe = safe.replace(old, new)
    return safe.replace(disclaimer_token, DISCLAIMER)


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
# 主入口：DeepSeek 优先，本地模板兜底
# ─────────────────────────────────────────────────────────────────

def _ensure_disclaimer(text: str) -> str:
    """Append the fixed disclaimer without letting safety replacements alter it."""
    safe = _safe_text(text).strip()
    if not safe:
        safe = "本次报告暂时无法生成完整说明。"
    # 兼容早期兜底里曾把“推荐”替换成“提示”的情况，固定免责声明保持原文。
    safe = safe.replace(DISCLAIMER.replace("推荐", "提示"), DISCLAIMER)
    if DISCLAIMER not in safe:
        if "【免责声明】" in safe:
            safe = f"{safe.rstrip()}\n{DISCLAIMER}"
        else:
            safe = f"{safe.rstrip()}\n\n【免责声明】\n{DISCLAIMER}"
    return safe


def _get_deepseek_api_key() -> str:
    try:
        import streamlit as st

        key = str(st.secrets.get("DEEPSEEK_API_KEY", "")).strip()
        if key:
            return key
    except Exception:  # noqa: BLE001
        pass
    return os.getenv("DEEPSEEK_API_KEY", "").strip()


def _agent_context_for_prompt(agent_context: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = [
        "holdings",
        "family_cash",
        "total_position_value",
        "cash_ratio",
        "stock_ratio",
        "max_position_ratio",
        "risk_preference",
        "risk_score",
        "risk_level",
        "main_risks",
        "missing_data",
        "data_status",
        "history_summary",
        "pe_pb_status",
        "financial_status",
    ]
    return {key: agent_context.get(key) for key in allowed_keys}


def _call_deepseek_agent_report(agent_context: dict[str, Any], mode: str, api_key: str) -> str:
    """Call DeepSeek for the one-click Agent report, strictly from agent_context."""
    from openai import OpenAI

    context = _agent_context_for_prompt(agent_context)
    valuation_missing = bool((context.get("missing_data") or {}).get("估值数据缺失"))
    valuation_rule = (
        "如果估值数据缺失，必须只写：估值数据暂缺，本次不评价估值高低。"
        if valuation_missing
        else "如果估值数据没有缺失，可以说明估值数据已纳入体检，但仍不能据此做买卖判断。"
    )

    system_prompt = f"""
你是“家庭持仓风险体检 Agent”的报告生成器。你只能根据用户提供的 agent_context 写报告，不能编造任何缺失数据。

输出对象是爸妈或普通家庭成员，语言要自然、简单，不像券商研报。

必须遵守：
1. 不荐股，不预测涨跌，不承诺收益。
2. 不给买入、卖出、加仓、减仓等操作指令。
3. 不使用“您家”“贵家庭”“您的家庭资产”。
4. 必须结合现金比例、股票/基金持仓比例、最大单只持仓占比、主要风险和数据缺失情况。
5. {valuation_rule}
6. 报告控制在 500-800 字。
7. 固定五段结构，标题必须为：
   【整体判断】
   【主要风险】
   【数据缺失说明】
   【给爸妈重点看的地方】
   【免责声明】
8. 【免责声明】必须一字不改：{DISCLAIMER}
""".strip()

    user_prompt = (
        f"报告模式：{mode}\n\n"
        "请严格基于下面的 agent_context 生成报告，不允许自由发挥，不允许补充没有出现的数据。\n\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
    )

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=30.0)
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=1600,
    )
    content = _safe_text(response.choices[0].message.content).strip()
    if not content:
        raise RuntimeError("empty deepseek response")
    return _ensure_disclaimer(_sanitize_report_text(content))


def generate_local_agent_report(agent_context: dict[str, Any], mode: str = "爸妈版") -> str:
    """Generate the local fallback report strictly from agent_context fields."""
    if mode == "简洁版":
        return _ensure_disclaimer(_generate_brief_report(agent_context))
    if mode == "详细版":
        return _ensure_disclaimer(_generate_detailed_report(agent_context))
    return _ensure_disclaimer(_generate_parent_report(agent_context))


def generate_agent_report(agent_context: dict[str, Any], mode: str = "爸妈版") -> dict[str, str]:
    """Generate the one-click Agent report.

    DeepSeek is the primary report source. Local template generation is used only
    when the API key is missing or the API call is temporarily unavailable.
    """
    api_key = _get_deepseek_api_key()
    if api_key:
        try:
            return {
                "ai_report": _call_deepseek_agent_report(agent_context, mode, api_key),
                "report_source": "deepseek",
            }
        except Exception:  # noqa: BLE001
            pass
    return {
        "ai_report": generate_local_agent_report(agent_context, mode),
        "report_source": "local_fallback",
    }


UNRELATED_FOLLOWUP_TEXT = (
    "这个追问区主要回答本次投资体检相关问题。"
    "你可以问现金比例、持仓集中度、PE/PB、数据缺失或主要风险。"
)


def _followup_question_is_related(agent_context: dict[str, Any], question: str) -> bool:
    q = question.strip()
    if not q:
        return False
    keywords = [
        "现金", "备用金", "仓位", "持仓", "占比", "集中", "风险", "评分", "体检",
        "pe", "pb", "市盈率", "市净率", "估值", "数据", "缺失", "财务", "roe",
        "净利率", "毛利率", "负债", "利润", "营收", "行业", "组合", "股票",
        "基金", "标的", "公司", "波动", "备用", "主要问题", "主要风险",
        "值得", "买吗", "卖吗", "要不要", "能不能", "该不该", "适合",
    ]
    lower_q = q.lower()
    if any(keyword.lower() in lower_q for keyword in keywords):
        return True
    for item in agent_context.get("holdings", []) or []:
        code = str(item.get("code", "")).strip()
        name = str(item.get("name", "")).strip()
        if (code and code in q) or (name and name in q):
            return True
    return False


def _unrelated_followup_answer() -> str:
    return f"{UNRELATED_FOLLOWUP_TEXT}\n\n{DISCLAIMER}"


def _safe_followup_error(exc: Exception) -> str:
    text = str(exc).strip()
    if not text:
        text = type(exc).__name__
    if "timeout" in text.lower() or "timed out" in text.lower():
        return "DeepSeek API 调用超时"
    if "empty deepseek followup response" in text:
        return "DeepSeek 返回为空"
    return f"DeepSeek 调用异常：{text[:180]}"


def _call_deepseek_followup(agent_context: dict[str, Any], question: str, api_key: str) -> str:
    from openai import OpenAI

    context = _agent_context_for_prompt(agent_context)
    system_prompt = f"""
你是“家庭持仓风险体检 Agent”的追问助手。你只能回答和本次投资体检相关的问题。

必须遵守：
1. 必须围绕用户 question 回答，不能只输出通用总结。
2. 必须基于 agent_context，不能编造缺失数据。
3. 不荐股，不预测涨跌，不承诺收益。
4. 不给买入、卖出、加仓、减仓等操作指令。
5. 如果用户问题与本次投资体检无关，只回复：{UNRELATED_FOLLOWUP_TEXT}
6. 回答控制在 150-350 个中文字符。
7. 结尾必须保留免责声明：{DISCLAIMER}
""".strip()
    user_prompt = (
        "用户追问：\n"
        f"{question}\n\n"
        "本次体检 agent_context：\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
    )
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=30.0)
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=900,
    )
    content = _safe_text(response.choices[0].message.content).strip()
    if not content:
        raise RuntimeError("empty deepseek followup response")
    return _ensure_disclaimer(_sanitize_report_text(content))


# ─────────────────────────────────────────────────────────────────
# 追问回答：严格基于 agent_context，150-350 字
# ─────────────────────────────────────────────────────────────────

def _generate_local_followup_answer(agent_context: dict[str, Any], question: str) -> str:
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
    if not _followup_question_is_related(agent_context, q):
        return _unrelated_followup_answer()

    # ── 问题 1：现金相关（含动态变体） ──────────────────────────
    if "现金" in q or "备用金" in q:
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

    # ── 买卖类问题：不下结论，只回到风险体检维度 ───────────────
    elif any(term in q for term in ["值得买吗", "能买吗", "要不要买", "要不要卖", "该买吗", "该卖吗", "能不能买", "适合买", "可以买", "加仓", "减仓", "卖吗"]):
        primary = main_risks[0] if main_risks else "持仓结构暂无特别突出的风险点"
        body = (
            "这个问题不能直接回答成买或不买，因为本工具不提供买卖建议。"
            "基于本次体检，可以从持仓占比、估值、财务质量和数据完整性几个角度观察，"
            "而不是让 AI 直接替你做交易决定。\n\n"
            f"本次需要关注的是：{primary}；现金比例约 {_fmt_percent(cash_ratio)}，"
            f"最大单只占比约 {_fmt_percent(max_position_ratio)}。"
            f"{'估值数据暂缺，本次不评价估值高低。' if valuation_missing else ''}"
        )

    # ── 问题 2：持仓集中度相关（含动态变体） ────────────────────
    elif "哪只" in q or "集中" in q or ("占" in q and "%" in q) or ("标的" in q) or ("一只" in q):
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

    # ── 问题 4：数据完整性相关（含动态变体） ───────────────────
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

    # ── 问题 5a：评分偏低原因（动态变体） ──────────────────────
    elif "评分" in q and ("低" in q or "原因" in q or "分" in q):
        primary = main_risks[0] if main_risks else "持仓结构有待优化"
        if risk_score < 50:
            score_desc = "偏低"
            detail = (
                f"评分主要由三部分影响：持仓集中度、现金比例和财务数据质量。\n\n"
                f"这次评分 {risk_score}/100 属于{score_desc}，最主要的拉分项是：{primary}。\n\n"
                f"现金占比约 {_fmt_percent(cash_ratio)}，"
                f"最大单只占比约 {_fmt_percent(max_position_ratio)}——"
                f"{'这两项都给评分带来了一定压力。' if cash_ratio < 0.15 and max_position_ratio > 0.35 else '其中集中度是主要影响因素。'}"
                f"{'财务数据缺失也会让体检保守降分。' if finance_missing else ''}"
            )
        else:
            score_desc = "中等"
            detail = (
                f"评分 {risk_score}/100 属于{score_desc}，整体没有特别极端的问题。"
                f"主要关注点是：{primary}。"
                f"现金比例 {_fmt_percent(cash_ratio)}，最大单只占比 {_fmt_percent(max_position_ratio)}，"
                f"总体结构尚可，但仍有优化空间。"
            )
        body = detail

    # ── 问题 5b：重仓/仓位相关（动态变体） ─────────────────────
    elif "仓位" in q or "重仓" in q:
        if stock_ratio >= 0.85:
            vibe = "已经属于比较重的仓位"
            note = (
                f"股票/基金占比 {_fmt_percent(stock_ratio)}，{vibe}。"
                f"在这种情况下，市场整体波动时对家庭的影响会比较明显——"
                f"不只是单只标的的问题，而是整个资产的波动幅度都会比较大。\n\n"
                f"家庭的备用金只有 {_fmt_percent(cash_ratio)}，"
                f"{'这个比例偏低，遇到急用钱时可能比较被动。' if cash_ratio < 0.15 else '这个比例尚可，短期用钱压力相对可控。'}"
            )
        elif stock_ratio >= 0.70:
            vibe = "处于中等偏高水平"
            note = (
                f"股票/基金占比 {_fmt_percent(stock_ratio)}，{vibe}。"
                f"大部分资金在权益类资产里，遇到市场波动时感受会比较明显，"
                f"但只要家庭现金（{_fmt_percent(cash_ratio)}）够应急，整体还在可接受范围内。"
            )
        else:
            note = (
                f"当前股票/基金占比 {_fmt_percent(stock_ratio)}，整体仓位不算极端。"
                f"保持现金比例（{_fmt_percent(cash_ratio)}）充足是最重要的保障，"
                f"仓位本身不是越低越好，关键是结构合不合理。"
            )
        body = note

    # ── 问题 5c：为什么需要继续观察（原有+扩展） ────────────────
    elif "继续观察" in q or ("为什么" in q and "组合" in q) or ("需要" in q and "观察" in q):
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

    # ── 兜底：相关但未命中特定关键词，围绕原问题解释主要风险 ───
    else:
        return _unrelated_followup_answer()

    return _sanitize_report_text(f"{body}\n\n{DISCLAIMER}")


def answer_followup_question(agent_context: dict[str, Any], question: str) -> dict[str, str]:
    q = question.strip()
    if not q:
        return {"answer": _unrelated_followup_answer(), "source": "local_fallback", "error": "问题为空"}
    if not agent_context:
        return {"answer": _unrelated_followup_answer(), "source": "local_fallback", "error": "缺少本次体检上下文"}

    api_key = _get_deepseek_api_key()
    if api_key:
        try:
            return {
                "answer": _call_deepseek_followup(agent_context, q, api_key),
                "source": "deepseek",
                "error": "",
            }
        except Exception as exc:  # noqa: BLE001
            error = _safe_followup_error(exc)
            return {
                "answer": _generate_local_followup_answer(agent_context, q),
                "source": "local_fallback",
                "error": error,
            }
    return {
        "answer": _generate_local_followup_answer(agent_context, q),
        "source": "local_fallback",
        "error": "未配置 DEEPSEEK_API_KEY",
    }


# ─────────────────────────────────────────────────────────────────
# 以下为旧式 DeepSeek 接口（兼容保留；普通分析入口不再调用）
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
