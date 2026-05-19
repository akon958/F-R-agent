from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Callable

from analyzer import analyze_portfolio, detect_family_disagreement
try:
    from ai_report import generate_agent_report  # type: ignore
except ImportError:
    def generate_agent_report(agent_context: dict, mode: str = "爸妈版") -> dict[str, str]:  # type: ignore[misc]
        return {
            "ai_report": (
                "AI 报告模块需要重新部署最新版本。\n\n"
                "本工具只做家庭投资风险体检和学习参考，不构成任何投资建议，也不替任何人做交易决定。"
            ),
            "report_source": "local_fallback",
        }
from data_fetcher import get_stock_metrics, normalize_code
from storage import (
    format_datetime_for_display,
    get_last_analysis_save_status,
    load_recent_family_comments,
    load_recent_analysis_history,
    save_analysis_history,
)


def _safe_dinner_talk(text: str, agent_context: dict[str, Any] | None = None) -> str:
    try:
        from ai_report import sanitize_dinner_talk  # type: ignore

        return sanitize_dinner_talk(text, agent_context or {})
    except Exception:  # noqa: BLE001
        fallback = "这次结果主要提醒我们一起看看风险分布，不急着做决定，先把家里对风险的看法聊清楚。"
        return fallback[:80]


def _fallback_dinner_talk(agent_context: dict[str, Any]) -> str:
    disagreement = agent_context.get("family_disagreement") or {}
    if isinstance(disagreement, dict) and disagreement.get("has_conflict"):
        text = "这次主要不是谁对谁错，是家里对风险感受不太一样。要不要我们周末一起聊清楚？"
    elif float(agent_context.get("max_position_ratio", 0) or 0) >= 0.3:
        text = "这次主要有一只占比不低，波动起来家里感受会明显。要不要周末一起再看看？"
    else:
        text = "这次结果主要提醒我们一起看看风险分布，不急着做决定，先把家里对风险的看法聊清楚。"
    return _safe_dinner_talk(text, agent_context)


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _first_value(row: dict[str, Any], keys: list[str], default: Any = "") -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return default


def _normalize_holdings(holdings: Any) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    clean: list[dict[str, Any]] = []
    if not isinstance(holdings, list):
        return [], ["持仓数据格式不正确，请按列表填写。"]

    for index, row in enumerate(holdings, 1):
        if not isinstance(row, dict):
            warnings.append(f"第 {index} 行持仓格式不正确，已跳过。")
            continue
        raw_code = _first_value(row, ["code", "代码", "股票代码", "基金代码", "symbol"])
        name = str(_first_value(row, ["name", "名称", "股票名称", "基金名称"], "") or "").strip()
        amount = _to_float(_first_value(row, ["amount", "持仓金额", "金额", "市值", "value"], 0))
        code = normalize_code(str(raw_code))
        if not code:
            warnings.append(f"第 {index} 行缺少股票/基金代码，已跳过。")
            continue
        if amount <= 0:
            warnings.append(f"{code} {name or ''} 持仓金额不是正数，已跳过。")
            continue
        clean.append({"code": code, "name": name, "amount": amount})
    return clean, warnings


def _try_realtime_data(codes: list[str]) -> tuple[list[dict[str, Any]] | None, str]:
    try:
        import realtime_data  # type: ignore
    except Exception:  # noqa: BLE001
        return None, "当前数据来源：本地缓存。实时行情模块后续可接入。"

    for func_name in ("get_realtime_data", "get_stock_metrics", "fetch_realtime_quotes"):
        func = getattr(realtime_data, func_name, None)
        if not callable(func):
            continue
        try:
            data = func(codes)
            if isinstance(data, tuple):
                data = data[0]
            if isinstance(data, list) and data:
                return data, f"已尝试使用 realtime_data.py 的 {func_name}。"
        except Exception:  # noqa: BLE001
            continue
    return None, "当前数据来源：本地缓存。实时行情模块后续可接入。"


def _safe_ai_text(text: str) -> str:
    disclaimer = "本工具只做家庭投资风险体检和学习参考，不构成任何投资建议，也不替任何人做交易决定。"
    disclaimer_token = "__FIXED_DISCLAIMER__"
    safe = text.replace(disclaimer, disclaimer_token)
    replacements = {
        "买入": "继续观察",
        "卖出": "重点复盘",
        "加仓": "增加关注",
        "减仓": "控制集中度",
        "推荐": "提示",
        "预测涨跌": "判断短期方向",
        "我们可能需要慢慢调整": "后续讨论时可以重点关注这一点",
    }
    for old, new in replacements.items():
        safe = safe.replace(old, new)
    return safe.replace(disclaimer_token, disclaimer)


def _has_any_value(stock: dict[str, Any], fields: list[str]) -> bool:
    return any(stock.get(field) is not None for field in fields)


def _collect_missing_data(stocks: list[dict[str, Any]]) -> dict[str, list[str]]:
    missing = {"行情数据缺失": [], "估值数据缺失": [], "财务数据缺失": []}
    market_fields = ["price", "pct_change", "turnover", "最新收盘价", "涨跌幅", "成交额"]
    valuation_fields = ["pe", "pb", "market_cap", "turnover_rate", "市盈率-动态", "市净率", "总市值", "换手率"]
    finance_fields = ["roe", "net_margin", "gross_margin", "debt_ratio", "ROE", "净利率", "毛利率", "资产负债率"]

    for stock in stocks:
        code = str(stock.get("code") or stock.get("股票代码") or "")
        name = str(stock.get("name") or stock.get("股票名称") or code)
        label = f"{code} {name}".strip()
        if stock.get("数据来源") == "数据缺失":
            missing["行情数据缺失"].append(label)
            missing["估值数据缺失"].append(label)
            missing["财务数据缺失"].append(label)
            continue
        if not _has_any_value(stock, market_fields):
            missing["行情数据缺失"].append(label)
        if not _has_any_value(stock, valuation_fields):
            missing["估值数据缺失"].append(label)
        if not _has_any_value(stock, finance_fields):
            missing["财务数据缺失"].append(label)
    return missing


def _get_deepseek_api_key() -> str:
    try:
        import streamlit as st

        key = str(st.secrets.get("DEEPSEEK_API_KEY", "")).strip()
        if key:
            return key
    except Exception:  # noqa: BLE001
        pass
    return os.getenv("DEEPSEEK_API_KEY", "").strip()


def _fallback_ai_report(analysis: dict[str, Any], missing_data: dict[str, list[str]]) -> str:
    missing_parts = [f"{name}：{len(items)} 只" for name, items in missing_data.items() if items]
    missing_text = "；".join(missing_parts) if missing_parts else "这次体检数据基本够用。"
    return (
        f"【整体感觉】\n当前组合综合评分 {analysis.get('score', 0)}/100，"
        f"风险等级为{analysis.get('level', '')}。这只是家庭投资风险体检，不代表未来一定涨跌。\n\n"
        f"【主要风险】\n{'; '.join(analysis.get('risk_notes', [])[:4]) or '暂时没有特别刺眼的问题，但仍要定期复盘。'}\n\n"
        f"【数据缺失说明】\n{missing_text}\n\n"
        "【爸妈重点看什么】\n先看现金够不够、单只股票会不会太集中，再看公司经营数据是否完整。不要因为短期涨跌冲动操作。\n\n"
        "【免责声明】\n本工具只做家庭投资风险体检和学习参考，不构成任何投资建议，也不替任何人做交易决定。"
    )


def _save_history(agent_result: dict[str, Any], analysis: dict[str, Any]) -> bool:
    try:
        holdings = agent_result.get("holdings", []) or []
        holdings_summary = "；".join(
            f"{item.get('code', '')} {item.get('name', '')} {item.get('amount', 0)}元".strip()
            for item in holdings
        )
        agent_context = agent_result.get("agent_context", {}) or {}
        record = {
            "holdings_summary": holdings_summary,
            "family_cash": analysis.get("cash", agent_context.get("family_cash", 0)),
            "total_position_value": agent_context.get("total_position_value", analysis.get("stock_total", 0)),
            "cash_ratio": analysis.get("cash_ratio", agent_context.get("cash_ratio", 0)),
            "stock_ratio": analysis.get("stock_ratio", agent_context.get("stock_ratio", 0)),
            "max_position_ratio": analysis.get("max_single_ratio", agent_context.get("max_position_ratio", 0)),
            "risk_score": agent_result.get("risk_score", analysis.get("score", 0)),
            "risk_level": agent_result.get("risk_level", ""),
            "main_risks": agent_result.get("main_risks", []),
            "missing_data": agent_result.get("missing_data", {}),
            "data_status": agent_result.get("data_status", ""),
            "pe_pb_status": agent_context.get("pe_pb_status", ""),
            "financial_status": agent_context.get("financial_status", ""),
            "ai_report_summary": str(agent_result.get("ai_report", ""))[:500],
            "full_agent_result": agent_result,
            # 第 2 步新增字段
            "run_id": agent_result.get("run_id", ""),
            "watch_tasks": agent_result.get("watch_tasks", []),
            "industry_conc": agent_result.get("industry_conc"),
            "data_credit": agent_result.get("data_credit"),
        }
        return save_analysis_history(record)
    except Exception:  # noqa: BLE001
        return False


def _load_history_summary(limit: int = 3) -> str:
    try:
        rows = load_recent_analysis_history(limit=limit)
    except Exception:  # noqa: BLE001
        return ""
    if not rows:
        return ""
    parts = []
    for row in rows[:limit]:
        time_text = format_datetime_for_display(row.get("created_at") or row.get("分析时间"))
        level = row.get("risk_level") or row.get("风险等级") or ""
        score = row.get("risk_score") or row.get("综合评分") or ""
        parts.append(f"{time_text} 评分 {score}，等级 {level}".strip())
    return "；".join(parts)


def _build_agent_context(
    clean_holdings: list[dict[str, Any]],
    cash: float,
    risk_preference: str,
    portfolio_summary: dict[str, Any],
    analysis: dict[str, Any],
    missing_data: dict[str, list[str]],
    main_risks: list[str],
) -> dict[str, Any]:
    stock_results = analysis.get("stock_results", [])
    name_by_code = {item.get("code"): item.get("name") for item in stock_results}
    holdings_context = []
    for item in clean_holdings:
        code = item.get("code", "")
        holdings_context.append(
            {
                "code": code,
                "name": item.get("name") or name_by_code.get(code) or code,
                "amount": item.get("amount", 0),
                "position_ratio": (item.get("amount", 0) / portfolio_summary["total_assets"])
                if portfolio_summary.get("total_assets", 0) > 0
                else 0,
            }
        )

    # ── PE/PB 状态描述 ──────────────────────────────────────────
    valuation_missing_items = missing_data.get("估值数据缺失", [])
    if valuation_missing_items:
        pe_pb_status = f"PE/PB 数据暂缺（涉及 {len(valuation_missing_items)} 只标的）"
    else:
        pe_pb_status = "PE/PB 数据已匹配"

    # ── 财务数据状态描述 ────────────────────────────────────────
    finance_missing_items = missing_data.get("财务数据缺失", [])
    if finance_missing_items:
        financial_status = f"财务数据部分缺失（涉及 {len(finance_missing_items)} 只标的）"
    else:
        financial_status = "财务数据已匹配"

    return {
        "holdings": holdings_context,
        "family_cash": cash,
        "total_position_value": portfolio_summary.get("stock_total", 0),
        "cash_ratio": portfolio_summary.get("cash_ratio", 0),
        "stock_ratio": portfolio_summary.get("stock_ratio", 0),
        "max_position_ratio": portfolio_summary.get("max_single_ratio", 0),
        "risk_preference": risk_preference,
        "risk_score": analysis.get("score", 0),
        "risk_level": f"{analysis.get('level', '')}（{analysis.get('level_text', '')}）",
        "main_risks": main_risks,
        "missing_data": missing_data,
        "data_status": analysis.get("data_status", "本地缓存"),
        "pe_pb_status": pe_pb_status,
        "financial_status": financial_status,
        "history_summary": _load_history_summary(),
        "ai_report": "",  # 占位，由 run_family_risk_agent 生成后回填
    }


def run_family_risk_agent(
    holdings: Any,
    family_cash: float,
    risk_preference: str = "稳健",
    user_goal: str = "检查家庭持仓风险",
    progress_callback: Callable[[str, int], None] | None = None,
) -> dict[str, Any]:
    run_id: str = uuid.uuid4().hex  # 本次体检唯一编号

    def emit(step: str, percent: int) -> None:
        if progress_callback:
            try:
                progress_callback(step, percent)
            except Exception:  # noqa: BLE001
                pass

    agent_steps = [
        {
            "title": "识别家庭持仓",
            "description": "已读取持仓金额、家庭现金和风险承受能力。",
            "status": "已完成",
        },
        {
            "title": "检查数据完整性",
            "description": "已检查行情、估值和财务数据是否完整。",
            "status": "已完成",
        },
        {
            "title": "评估家庭风险",
            "description": "已计算持仓占比、现金比例、集中度风险和数据缺口。",
            "status": "已完成",
        },
        {
            "title": "生成家庭说明",
            "description": "已生成适合家人阅读的风险说明。",
            "status": "已完成",
        },
    ]
    debug_steps: list[str] = []
    warnings: list[str] = []

    emit("检查输入是否完整", 8)
    debug_steps.append("检查用户输入是否完整")
    clean_holdings, input_warnings = _normalize_holdings(holdings)
    warnings.extend(input_warnings)
    cash = _to_float(family_cash)
    if cash < 0:
        warnings.append("现金金额不能为负数，已按 0 处理。")
        cash = 0.0
    if not clean_holdings:
        no_disagreement = {"has_conflict": False, "conflicts": [], "summary": ""}
        return {
            "success": False,
            "agent_steps": agent_steps,
            "debug_steps": debug_steps,
            "portfolio_summary": {},
            "data_status": "输入不完整",
            "risk_score": 0,
            "risk_level": "无法判断",
            "main_risks": ["请至少填写一只持仓，并填写大于 0 的持仓金额。"],
            "missing_data": {},
            "warnings": warnings,
            "ai_report": "",
            "report_source": "local_fallback",
            "agent_context": {},
            "family_disagreement": no_disagreement,
            "saved_history": False,
            "storage_status": {
                "backend": "local_csv",
                "connected": False,
                "saved": False,
                "message": "输入不完整，未保存历史记录。",
            },
        }

    codes = [item["code"] for item in clean_holdings]
    emit("读取行情和财务缓存", 20)
    debug_steps.append("读取本地数据。")
    stocks, fetch_warnings = get_stock_metrics(codes)
    warnings.extend(fetch_warnings)

    debug_steps.append("检查实时行情模块；不可用时使用本地数据。")
    realtime_file_exists = Path(__file__).with_name("realtime_data.py").exists()
    realtime_rows, realtime_message = _try_realtime_data(codes)
    warnings.append(realtime_message)
    if realtime_rows:
        stocks = realtime_rows

    emit("计算持仓比例和现金比例", 35)
    debug_steps.append("计算持仓比例、整体仓位和现金比例")
    stock_total = sum(item["amount"] for item in clean_holdings)
    total_assets = cash + stock_total
    portfolio_summary = {
        "user_goal": user_goal,
        "family_cash": cash,
        "stock_total": stock_total,
        "total_assets": total_assets,
        "cash_ratio": cash / total_assets if total_assets > 0 else 0,
        "stock_ratio": stock_total / total_assets if total_assets > 0 else 0,
        "holding_count": len(clean_holdings),
        "max_single_ratio": max((item["amount"] / total_assets for item in clean_holdings), default=0) if total_assets > 0 else 0,
    }

    emit("识别集中风险和数据缺失", 48)
    debug_steps.append("判断单只集中风险和现金压力")
    if portfolio_summary["max_single_ratio"] > 0.40:
        warnings.append("单只持仓超过家庭可投资资金的 40%，集中度偏高。")
    if portfolio_summary["cash_ratio"] < 0.10:
        warnings.append("现金比例偏低，家庭备用金需要优先关注。")

    debug_steps.append("识别行情、估值和财务数据缺失")
    missing_data = _collect_missing_data(stocks)

    debug_steps.append("完成风险计算。")
    analysis = analyze_portfolio(cash, risk_preference, clean_holdings, stocks)

    emit("组装 agent_context", 60)
    debug_steps.append("整理体检上下文。")
    data_status = analysis.get("data_status", "本地缓存")
    main_risks = analysis.get("risk_notes", [])[:8]
    agent_context = _build_agent_context(
        clean_holdings=clean_holdings,
        cash=cash,
        risk_preference=risk_preference,
        portfolio_summary=portfolio_summary,
        analysis=analysis,
        missing_data=missing_data,
        main_risks=main_risks,
    )
    try:
        family_comments = load_recent_family_comments(limit=50)
        family_disagreement = detect_family_disagreement(family_comments)
    except Exception:  # noqa: BLE001
        family_comments = []
        family_disagreement = {"has_conflict": False, "conflicts": [], "summary": ""}
    agent_context["family_comments"] = family_comments[:20]
    agent_context["family_disagreement"] = family_disagreement

    emit("调用 DeepSeek 生成 AI 风险说明", 72)
    debug_steps.append("生成家庭说明。")
    report_source = "local_fallback"
    try:
        report_result = generate_agent_report(agent_context, mode="爸妈版")
    except Exception:  # noqa: BLE001
        report_result = {
            "ai_report": _fallback_ai_report(analysis, missing_data),
            "report_source": "local_fallback",
        }
    if isinstance(report_result, dict):
        ai_report = _safe_ai_text(str(report_result.get("ai_report", "") or ""))
        dinner_talk = _safe_dinner_talk(str(report_result.get("dinner_talk", "") or ""), agent_context)
        report_source = str(report_result.get("report_source", "local_fallback") or "local_fallback")
    else:
        ai_report = _safe_ai_text(str(report_result or ""))
        dinner_talk = _fallback_dinner_talk(agent_context)
    if not ai_report:
        ai_report = _safe_ai_text(_fallback_ai_report(analysis, missing_data))
        report_source = "local_fallback"
    if not dinner_talk:
        dinner_talk = _fallback_dinner_talk(agent_context)
    agent_context["ai_report"] = ai_report  # 回填，让追问函数可读取本次报告内容
    agent_context["dinner_talk"] = dinner_talk
    agent_context["report_source"] = report_source
    agent_context["report_mode"] = "爸妈版"
    agent_context["run_id"] = run_id  # 每次体检唯一编号
    ai_report_success = True

    agent_result = {
        "success": True,
        "run_id": run_id,
        "agent_steps": agent_steps,
        "debug_steps": debug_steps,
        "portfolio_summary": portfolio_summary,
        "data_status": data_status,
        "risk_score": analysis.get("score", 0),
        "risk_level": f"{analysis.get('level', '')}（{analysis.get('level_text', '')}）",
        "main_risks": main_risks,
        "missing_data": missing_data,
        "warnings": warnings,
        "ai_report": ai_report,
        "dinner_talk": dinner_talk,
        "report_source": report_source,
        "report_mode": "爸妈版",
        "family_disagreement": family_disagreement,
        "watch_tasks": [],       # 第 6/8 步生成结构化任务，先占位
        "industry_conc": None,   # 后续行业集中度计算
        "data_credit": None,     # 后续数据可信度评分
        "saved_history": False,
        "agent_context": agent_context,
        "debug_info": {
            "使用本地缓存": not bool(realtime_rows),
            "发现 realtime_data.py": realtime_file_exists,
            "保存历史记录": False,
            "analyzer.py 调用成功": True,
            "ai_report.py 调用成功": ai_report_success,
            "报告来源": report_source,
            "saved_history": False,
            "data_status 原始值": data_status,
        },
        "analysis": analysis,
        "stocks": stocks,
        "holdings": clean_holdings,
    }

    debug_steps.append("保存本次体检记录。")
    emit("保存历史记录到 Supabase", 88)
    agent_result["saved_history"] = _save_history(agent_result, analysis)
    agent_result["storage_status"] = get_last_analysis_save_status()
    agent_result["debug_info"]["保存历史记录"] = agent_result["saved_history"]
    agent_result["debug_info"]["存储方式"] = agent_result["storage_status"].get("backend")
    agent_result["debug_info"]["saved_history"] = agent_result["saved_history"]
    emit("准备智能追问建议", 96)
    emit("完成体检", 100)
    return agent_result
