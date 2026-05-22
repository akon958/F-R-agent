from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from analyzer import (
    analyze_history_changes,
    analyze_portfolio,
    assess_data_confidence,
    build_risk_factor_breakdown,
    detect_family_disagreement,
    detect_intent_action_gap,
)
from config import DEFAULT_REPORT_MODE, FIXED_DISCLAIMER
try:
    from ai_report import generate_agent_report  # type: ignore
except ImportError:
    def generate_agent_report(agent_context: dict, mode: str = DEFAULT_REPORT_MODE) -> dict[str, str]:  # type: ignore[misc]
        return {
            "ai_report": (
                "AI 报告模块需要重新部署最新版本。\n\n"
                f"{FIXED_DISCLAIMER}"
            ),
            "report_source": "local_fallback",
        }
from data_fetcher import get_stock_metrics, normalize_code
from delta_alert import compute_delta
from memory_agent import build_agent_memory_summary
from validator import cross_validate
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


_REVERSE_QA_DEFAULT = {
    "money_need_6m": "uncertain",
    "volatility_reaction": "discuss",
    "last_disagreement": "",
}


def _normalize_reverse_qa(raw: Any) -> dict[str, str]:
    data = dict(_REVERSE_QA_DEFAULT)
    if isinstance(raw, dict):
        data.update({key: str(value or "") for key, value in raw.items() if key in data})
    if data["money_need_6m"] not in ("possible", "uncertain", "unlikely"):
        data["money_need_6m"] = "uncertain"
    if data["volatility_reaction"] not in ("panic", "tolerate", "discuss"):
        data["volatility_reaction"] = "discuss"
    data["last_disagreement"] = str(data.get("last_disagreement", "") or "").strip()
    return data


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
    disclaimer = FIXED_DISCLAIMER
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
        f"【免责声明】\n{FIXED_DISCLAIMER}"
    )


def _generate_watch_tasks(
    analysis: dict[str, Any],
    portfolio_summary: dict[str, Any],
    missing_data: dict[str, list[str]],
    reverse_qa: dict[str, Any],
    history_analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    """根据本次体检结果生成结构化待办任务，最多5条，按优先级排序。"""
    tasks: list[dict[str, Any]] = []
    cash_ratio    = float(portfolio_summary.get("cash_ratio", 0) or 0)
    max_single    = float(portfolio_summary.get("max_single_ratio", 0) or 0)
    score         = int(analysis.get("score", 0) or 0)
    top_industry  = str(analysis.get("top_industry") or "")
    industry_conc = float(analysis.get("industry_concentration", 0) or 0)
    stock_results = list(analysis.get("stock_results", []) or [])
    money_urgent  = reverse_qa.get("money_need_6m") == "possible"

    # ── 1. 现金 / 流动性 ──────────────────────────────────────────
    if money_urgent and cash_ratio < 0.20:
        tasks.append({
            "category": "cash", "priority": "high",
            "title": "确认6个月内资金安排并补足备用金",
            "desc": (
                f"半年内可能有资金需求，当前现金比例仅 {cash_ratio:.0%}，"
                "建议优先确保流动资金充足，避免被迫处置持仓。"
            ),
        })
    elif cash_ratio < 0.10:
        tasks.append({
            "category": "cash", "priority": "high",
            "title": "优先补足家庭备用金",
            "desc": (
                f"现金比例 {cash_ratio:.0%} 偏低，建议逐步补到 15% 以上，"
                "先保障家庭急用钱需求，再考虑其他安排。"
            ),
        })
    elif cash_ratio < 0.15:
        tasks.append({
            "category": "cash", "priority": "medium",
            "title": "留意现金是否足够应急",
            "desc": (
                f"现金比例 {cash_ratio:.0%} 处于偏低区间，"
                "下次体检时确认有没有补充。"
            ),
        })

    # ── 2. 单只集中度 ──────────────────────────────────────────
    if max_single > 0.30 and stock_results:
        top_h = max(stock_results, key=lambda x: float(x.get("single_ratio", 0) or 0))
        top_name = top_h.get("name") or top_h.get("code") or "最大持仓"
        tasks.append({
            "category": "concentration",
            "priority": "high" if max_single > 0.40 else "medium",
            "title": f"持续关注 {top_name} 的占比变化",
            "desc": (
                f"{top_name} 目前占家庭总资产 {max_single:.0%}，"
                "下次体检时确认占比有没有进一步集中。"
            ),
        })

    # ── 3. 行业集中 ──────────────────────────────────────────
    if top_industry and top_industry not in ("未知", "无") and industry_conc > 0.60:
        tasks.append({
            "category": "industry", "priority": "medium",
            "title": f"定期了解{top_industry}行业动态",
            "desc": (
                f"股票部分 {industry_conc:.0%} 集中在{top_industry}，"
                "建议留意该行业有没有重大政策或经营变化。"
            ),
        })

    # ── 4. 财务数据缺失 ──────────────────────────────────────
    finance_missing = list(missing_data.get("财务数据缺失", []) or [])
    if finance_missing:
        tasks.append({
            "category": "data", "priority": "medium",
            "title": "季报更新后重新体检",
            "desc": (
                f"本次 {len(finance_missing)} 只标的财务数据暂缺，"
                "建议下次季报发布后再跑一次体检，结论会更完整。"
            ),
        })

    # ── 5. 历史重复风险 ──────────────────────────────────────
    watch_pts = list(history_analysis.get("watch_points", []) or [])
    if watch_pts and len(tasks) < 5:
        snippet = "；".join(watch_pts[:2])[:60]
        tasks.append({
            "category": "history", "priority": "medium",
            "title": "跟踪连续出现的风险点",
            "desc": f"以下风险连续两次体检都存在：{snippet}。下次体检时重点确认是否改善。",
        })

    # ── 6. 评分偏低补充 ──────────────────────────────────────
    if score < 60 and len(tasks) < 5:
        tasks.append({
            "category": "general", "priority": "high",
            "title": "近期安排一次家庭复盘",
            "desc": (
                f"本次综合评分 {score}/100，风险偏高，"
                "建议家人近期一起回顾一次，不要等到下次定期体检。"
            ),
        })

    # 按优先级排序，最多5条
    _order = {"high": 0, "medium": 1, "low": 2}
    tasks.sort(key=lambda t: _order.get(t.get("priority", "low"), 2))
    return tasks[:5]


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


def _load_history_summary(history_records: list[dict[str, Any]] | None = None, limit: int = 3) -> str:
    rows = list(history_records or [])
    if not rows:
        return ""
    parts = []
    for row in rows[:limit]:
        time_text = format_datetime_for_display(row.get("created_at") or row.get("分析时间"))
        level = row.get("risk_level") or row.get("风险等级") or ""
        score = row.get("risk_score") or row.get("综合评分") or ""
        parts.append(f"{time_text} 评分 {score}，等级 {level}".strip())
    return "；".join(parts)


def _load_memory_inputs_parallel(
    comment_limit: int = 50,
    history_limit: int = 5,
) -> dict[str, Any]:
    """Load Supabase-backed memory inputs in parallel.

    family_comments and analysis_history are independent network calls. Running
    them in two threads saves one round-trip on Streamlit Cloud while keeping
    all storage access inside storage.py.
    """
    result: dict[str, Any] = {
        "family_comments": [],
        "history_records": [],
        "errors": {},
    }

    def _load_comments() -> None:
        try:
            result["family_comments"] = load_recent_family_comments(limit=comment_limit)
        except Exception as exc:  # noqa: BLE001
            result["family_comments"] = []
            result["errors"]["family_comments"] = f"{type(exc).__name__}: {str(exc)[:160]}"

    def _load_history() -> None:
        try:
            result["history_records"] = load_recent_analysis_history(limit=history_limit)
        except Exception as exc:  # noqa: BLE001
            result["history_records"] = []
            result["errors"]["history_records"] = f"{type(exc).__name__}: {str(exc)[:160]}"

    threads = [
        threading.Thread(target=_load_comments, name="family_comments_loader", daemon=True),
        threading.Thread(target=_load_history, name="analysis_history_loader", daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=8)

    for thread in threads:
        if thread.is_alive():
            result["errors"][thread.name] = "读取超时，已跳过，不影响本次体检。"

    return result


def _build_agent_context(
    clean_holdings: list[dict[str, Any]],
    cash: float,
    risk_preference: str,
    portfolio_summary: dict[str, Any],
    analysis: dict[str, Any],
    missing_data: dict[str, list[str]],
    main_risks: list[str],
    history_records: list[dict[str, Any]] | None = None,
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

    # 每只持仓的实际财务数据（仅包含非空字段），供 AI 追问时使用
    stock_details: list[dict[str, Any]] = []
    for sr in stock_results:
        detail: dict[str, Any] = {
            "code": sr.get("code", ""),
            "name": sr.get("name", ""),
        }
        for _field in ["pe", "pb", "roe", "net_margin", "gross_margin", "debt_ratio", "industry",
                       "financial_score", "heat_score"]:
            _val = sr.get(_field)
            if _val is not None:
                detail[_field] = _val
        stock_details.append(detail)

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
        "history_summary": _load_history_summary(history_records),
        "stock_details": stock_details,   # 个股实际财务数据，仅追问时用，不进入主报告 prompt
        "ai_report": "",  # 占位，由 run_family_risk_agent 生成后回填
    }


# ─────────────────────────────────────────────────────────────────
# 专职子 Agent：由 run_family_risk_agent() 统一编排调用
# ─────────────────────────────────────────────────────────────────

def _run_data_agent(
    clean_holdings: list[dict[str, Any]],
    cash: float,
    user_goal: str,
    reverse_qa_data: dict[str, Any],
    debug_steps: list[str],
    warnings: list[str],
    emit: Callable[[str, int], None],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, list[str]], bool]:
    """Data Agent：读取行情/财务缓存，计算组合指标，收集数据缺口。

    返回 (stocks, portfolio_summary, missing_data, realtime_used)
    """
    codes = [item["code"] for item in clean_holdings]
    emit("读取行情和财务缓存", 20)
    debug_steps.append("读取本地数据。")
    stocks, fetch_warnings = get_stock_metrics(codes)
    warnings.extend(fetch_warnings)

    debug_steps.append("检查实时行情模块；不可用时使用本地数据。")
    realtime_rows, realtime_message = _try_realtime_data(codes)
    warnings.append(realtime_message)
    if realtime_rows:
        stocks = realtime_rows
    realtime_used = bool(realtime_rows)

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
        "max_single_ratio": max(
            (item["amount"] / total_assets for item in clean_holdings), default=0
        ) if total_assets > 0 else 0,
    }

    emit("识别集中风险和数据缺失", 48)
    debug_steps.append("判断单只集中风险和现金压力")
    if portfolio_summary["max_single_ratio"] > 0.40:
        warnings.append("单只持仓超过家庭可投资资金的 40%，集中度偏高。")
    _money_urgent = reverse_qa_data.get("money_need_6m") == "possible"
    if _money_urgent and portfolio_summary["cash_ratio"] < 0.20:
        warnings.append(
            f"半年内可能有资金需求，当前现金比例仅 {portfolio_summary['cash_ratio']:.0%}，"
            "流动性风险需要优先关注。"
        )
    elif portfolio_summary["cash_ratio"] < 0.10:
        warnings.append("现金比例偏低，家庭备用金需要优先关注。")

    debug_steps.append("识别行情、估值和财务数据缺失")
    missing_data = _collect_missing_data(stocks)

    return stocks, portfolio_summary, missing_data, realtime_used


def _run_risk_agent(
    clean_holdings: list[dict[str, Any]],
    cash: float,
    risk_preference: str,
    portfolio_summary: dict[str, Any],
    stocks: list[dict[str, Any]],
    missing_data: dict[str, list[str]],
    reverse_qa_data: dict[str, Any],
    debug_steps: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any], list[str]]:
    """Risk Agent：四维评分、数据可信度、交叉验证、主要风险提取。

    返回 (analysis, risk_factors, data_confidence, cross_validation, main_risks)
    """
    debug_steps.append("完成风险计算。")
    analysis = analyze_portfolio(cash, risk_preference, clean_holdings, stocks)
    risk_factors = build_risk_factor_breakdown(analysis)
    data_confidence = assess_data_confidence(analysis, missing_data)

    _cv_score = int(analysis.get("score", 0) or 0)
    _cv_level = f"{analysis.get('level', '')}（{analysis.get('level_text', '')}）"
    cross_validation = cross_validate(_cv_score, _cv_level, portfolio_summary, risk_factors)

    debug_steps.append("整理体检上下文。")
    main_risks: list[str] = analysis.get("risk_notes", [])[:8]
    # 若用户表示半年内可能用钱且现金不足，将流动性风险前置
    if (
        reverse_qa_data.get("money_need_6m") == "possible"
        and portfolio_summary.get("cash_ratio", 1.0) < 0.20
    ):
        _liquidity_note = (
            f"半年内可能有资金需求，当前现金比例仅 {portfolio_summary['cash_ratio']:.0%}，"
            "流动性应作为首要关注。"
        )
        if _liquidity_note not in main_risks:
            main_risks = [_liquidity_note] + [r for r in main_risks if r != _liquidity_note]
            main_risks = main_risks[:8]

    return analysis, risk_factors, data_confidence, cross_validation, main_risks


def _run_memory_agent(
    clean_holdings: list[dict[str, Any]],
    cash: float,
    risk_preference: str,
    portfolio_summary: dict[str, Any],
    analysis: dict[str, Any],
    missing_data: dict[str, list[str]],
    main_risks: list[str],
    reverse_qa_data: dict[str, Any],
    risk_factors: list[dict[str, Any]],
    debug_steps: list[str],
    warnings: list[str],
    emit: Callable[[str, int], None],
) -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any],
    dict[str, Any], dict[str, Any], dict[str, str], list[dict[str, Any]],
]:
    """Memory Agent：并行读 Supabase，组装 agent_context，检测家庭分歧与历史变化。

    返回 (agent_context, family_disagreement, intent_action_gap,
            history_analysis, agent_memory, memory_errors, history_records)
    """
    emit("读取历史和家庭观察", 56)
    debug_steps.append("并行读取家庭观察记录和历史体检记录。")
    memory_inputs = _load_memory_inputs_parallel(comment_limit=50, history_limit=5)
    family_comments = list(memory_inputs.get("family_comments") or [])
    history_records = list(memory_inputs.get("history_records") or [])
    memory_errors: dict[str, str] = dict(memory_inputs.get("errors") or {})

    emit("组装 agent_context", 60)
    agent_context = _build_agent_context(
        clean_holdings=clean_holdings,
        cash=cash,
        risk_preference=risk_preference,
        portfolio_summary=portfolio_summary,
        analysis=analysis,
        missing_data=missing_data,
        main_risks=main_risks,
        history_records=history_records,
    )

    # ── Disagreement Detector ────────────────────────────────────
    try:
        family_disagreement = detect_family_disagreement(family_comments)
        intent_action_gap = detect_intent_action_gap(family_comments, portfolio_summary)
    except Exception:  # noqa: BLE001
        family_disagreement = {"has_conflict": False, "conflicts": [], "summary": ""}
        intent_action_gap = {"has_gap": False, "gaps": [], "summary": ""}
    agent_context["family_comments"] = family_comments[:20]
    agent_context["family_disagreement"] = family_disagreement
    agent_context["intent_action_gap"] = intent_action_gap
    agent_context["reverse_qa"] = reverse_qa_data

    # ── History Analyzer ─────────────────────────────────────────
    try:
        history_analysis = analyze_history_changes(history_records)
    except Exception:  # noqa: BLE001
        history_analysis = {
            "has_history": False, "records_count": 0, "latest_date": "", "previous_date": "",
            "score_change": None, "risk_factor_changes": [], "family_focus_changes": [],
            "watch_points": [], "summary": "历史记录还不够，先完成几次体检后，这里会显示风险变化。",
        }
    agent_memory = build_agent_memory_summary(
        history_records=history_records,
        family_comments=family_comments,
        history_analysis=history_analysis,
        portfolio_summary=portfolio_summary,
        risk_factors=risk_factors,
    )
    agent_context["history_analysis"] = history_analysis
    agent_context["risk_factors"] = risk_factors
    agent_context["agent_memory"] = agent_memory

    if memory_errors:
        agent_context["memory_load_warnings"] = memory_errors
        for _mem_key, _mem_msg in memory_errors.items():
            if "超时" in _mem_msg:
                _label = "家庭观察记录" if "comment" in _mem_key else "历史体检记录"
                warnings.append(f"{_label}读取较慢，本次体检不含该数据，不影响风险评估。")

    return (
        agent_context, family_disagreement, intent_action_gap,
        history_analysis, agent_memory, memory_errors, history_records,
    )


def _run_report_agent(
    agent_context: dict[str, Any],
    analysis: dict[str, Any],
    missing_data: dict[str, list[str]],
    emit: Callable[[str, int], None],
    debug_steps: list[str],
) -> tuple[str, str, str]:
    """Report Agent：调用 DeepSeek 生成家庭风险报告，失败时本地兜底。

    返回 (ai_report, dinner_talk, report_source)
    """
    emit("调用 DeepSeek 生成 AI 风险说明", 72)
    debug_steps.append("生成家庭说明。")
    try:
        report_result = generate_agent_report(agent_context, mode=DEFAULT_REPORT_MODE)
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
        report_source = "local_fallback"
    if not ai_report:
        ai_report = _safe_ai_text(_fallback_ai_report(analysis, missing_data))
        report_source = "local_fallback"
    if not dinner_talk:
        dinner_talk = _fallback_dinner_talk(agent_context)
    return ai_report, dinner_talk, report_source


# ─────────────────────────────────────────────────────────────────
# 主入口：编排四个专职子 Agent
# ─────────────────────────────────────────────────────────────────

def run_family_risk_agent(
    holdings: Any,
    family_cash: float,
    risk_preference: str = "稳健",
    user_goal: str = "检查家庭持仓风险",
    reverse_qa: dict[str, Any] | None = None,
    progress_callback: Callable[[str, int], None] | None = None,
) -> dict[str, Any]:
    """家庭风险体检主入口。

    编排四个专职子 Agent：
      _run_data_agent   → 行情 / 组合指标
      _run_risk_agent   → 四维评分 / 交叉验证
      _run_memory_agent → Supabase 记忆 / 家庭分歧
      _run_report_agent → DeepSeek 家庭报告
    """
    run_id: str = uuid.uuid4().hex
    reverse_qa_data = _normalize_reverse_qa(reverse_qa)

    def emit(step: str, percent: int) -> None:
        if progress_callback:
            try:
                progress_callback(step, percent)
            except Exception:  # noqa: BLE001
                pass

    agent_steps = [
        {"title": "识别家庭持仓", "description": "已读取持仓金额、家庭现金和风险承受能力。", "status": "已完成"},
        {"title": "检查数据完整性", "description": "已检查行情、估值和财务数据是否完整。", "status": "已完成"},
        {"title": "评估家庭风险", "description": "已计算持仓占比、现金比例、集中度风险和数据缺口。", "status": "已完成"},
        {"title": "生成家庭说明", "description": "已生成适合家人阅读的风险说明。", "status": "已完成"},
    ]
    debug_steps: list[str] = []
    warnings: list[str] = []

    # ── Input Guard ─────────────────────────────────────────────
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
            "reverse_qa": reverse_qa_data,
            "family_disagreement": no_disagreement,
            "intent_action_gap": {"has_gap": False, "gaps": [], "summary": ""},
            "data_confidence": {"level": "低", "level_code": "low", "summary": "输入不完整", "issues": []},
            "cross_validation": {"passed": True, "issues": [], "notes": [], "checks_run": 0},
            "saved_history": False,
            "storage_status": {
                "backend": "local_csv",
                "connected": False,
                "saved": False,
                "message": "输入不完整，未保存历史记录。",
            },
        }

    # ── Data Agent ──────────────────────────────────────────────
    stocks, portfolio_summary, missing_data, realtime_used = _run_data_agent(
        clean_holdings, cash, user_goal, reverse_qa_data, debug_steps, warnings, emit,
    )

    # ── Risk Agent ──────────────────────────────────────────────
    analysis, risk_factors, data_confidence, cross_validation, main_risks = _run_risk_agent(
        clean_holdings, cash, risk_preference, portfolio_summary,
        stocks, missing_data, reverse_qa_data, debug_steps,
    )

    # ── Memory Agent ────────────────────────────────────────────
    (
        agent_context, family_disagreement, intent_action_gap,
        history_analysis, agent_memory, memory_errors, history_records,
    ) = _run_memory_agent(
        clean_holdings, cash, risk_preference, portfolio_summary,
        analysis, missing_data, main_risks, reverse_qa_data,
        risk_factors, debug_steps, warnings, emit,
    )

    # ── Report Agent ────────────────────────────────────────────
    ai_report, dinner_talk, report_source = _run_report_agent(
        agent_context, analysis, missing_data, emit, debug_steps,
    )
    agent_context["ai_report"] = ai_report
    agent_context["dinner_talk"] = dinner_talk
    agent_context["report_source"] = report_source
    agent_context["report_mode"] = DEFAULT_REPORT_MODE
    agent_context["run_id"] = run_id

    # ── Result Assembly ─────────────────────────────────────────
    data_status = analysis.get("data_status", "本地缓存")
    agent_result: dict[str, Any] = {
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
        "report_mode": DEFAULT_REPORT_MODE,
        "reverse_qa": reverse_qa_data,
        "family_disagreement": family_disagreement,
        "intent_action_gap": intent_action_gap,
        "data_confidence": data_confidence,
        "cross_validation": cross_validation,
        "risk_factors": risk_factors,
        "agent_memory": agent_memory,
        "watch_tasks": _generate_watch_tasks(
            analysis=analysis,
            portfolio_summary=portfolio_summary,
            missing_data=missing_data,
            reverse_qa=reverse_qa_data,
            history_analysis=history_analysis,
        ),
        "industry_conc": analysis.get("industry_concentration"),
        "data_credit": round(
            (len(clean_holdings) - len(missing_data.get("行情数据缺失", [])))
            / len(clean_holdings) * 100
        ) if clean_holdings else 0,
        "history_analysis": history_analysis,
        "saved_history": False,
        "agent_context": agent_context,
        "debug_info": {
            "使用本地缓存": not realtime_used,
            "发现 realtime_data.py": Path(__file__).with_name("realtime_data.py").exists(),
            "保存历史记录": False,
            "analyzer.py 调用成功": True,
            "ai_report.py 调用成功": True,
            "报告来源": report_source,
            "Agent Memory": agent_memory.get("summary", ""),
            "saved_history": False,
            "data_status 原始值": data_status,
            "memory_load_warnings": memory_errors,
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

    # ── Delta Alert：对比本次与上次体检，检测关键指标变化 ──────────
    try:
        _delta_input = {
            "risk_score": agent_result.get("risk_score", 0),
            "portfolio_summary": portfolio_summary,
        }
        agent_result["delta_alert"] = compute_delta(_delta_input, history_records)
    except Exception:  # noqa: BLE001
        agent_result["delta_alert"] = {"has_alert": False, "level": "stable", "changes": [], "summary": ""}

    emit("准备智能追问建议", 96)
    emit("完成体检", 100)
    return agent_result
