from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from analyzer import analyze_portfolio
from ai_report import generate_parent_friendly_report
from data_fetcher import get_stock_metrics, normalize_code


HISTORY_FILE = Path(__file__).with_name("analysis_history.csv")


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
    replacements = {
        "买入": "继续观察",
        "卖出": "重点复盘",
        "加仓": "增加关注",
        "减仓": "控制集中度",
        "推荐": "提示",
        "预测涨跌": "判断短期方向",
        "我们可能需要慢慢调整": "后续讨论时可以重点关注这一点",
    }
    safe = text
    for old, new in replacements.items():
        safe = safe.replace(old, new)
    return safe


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
        "【免责声明】\n本工具只做家庭投资风险体检和学习参考，不构成任何投资建议，也不提供买卖推荐。"
    )


def _save_history(agent_result: dict[str, Any], analysis: dict[str, Any]) -> bool:
    if not Path(__file__).with_name("storage.py").exists():
        return False
    try:
        row = {
            "分析时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "综合评分": agent_result.get("risk_score", ""),
            "风险等级": agent_result.get("risk_level", ""),
            "数据状态": agent_result.get("data_status", ""),
            "家庭总资产": analysis.get("total_assets", 0),
            "现金比例": analysis.get("cash_ratio", 0),
            "股票仓位": analysis.get("stock_ratio", 0),
            "持仓数量": len(analysis.get("stock_results", [])),
            "主要风险": "；".join(agent_result.get("main_risks", [])[:5]),
        }
        exists = HISTORY_FILE.exists()
        with HISTORY_FILE.open("a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(row.keys()))
            if not exists:
                writer.writeheader()
            writer.writerow(row)
        return True
    except Exception:  # noqa: BLE001
        return False


def run_family_risk_agent(
    holdings: Any,
    family_cash: float,
    risk_preference: str = "稳健",
    user_goal: str = "检查家庭持仓风险",
) -> dict[str, Any]:
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

    debug_steps.append("检查用户输入是否完整")
    clean_holdings, input_warnings = _normalize_holdings(holdings)
    warnings.extend(input_warnings)
    cash = _to_float(family_cash)
    if cash < 0:
        warnings.append("现金金额不能为负数，已按 0 处理。")
        cash = 0.0
    if not clean_holdings:
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
            "saved_history": False,
        }

    codes = [item["code"] for item in clean_holdings]
    debug_steps.append("读取 stock_metrics.csv 中已有行情/财务缓存")
    stocks, fetch_warnings = get_stock_metrics(codes)
    warnings.extend(fetch_warnings)

    debug_steps.append("尝试读取 realtime_data.py，失败则回退 stock_metrics.csv")
    realtime_file_exists = Path(__file__).with_name("realtime_data.py").exists()
    realtime_rows, realtime_message = _try_realtime_data(codes)
    warnings.append(realtime_message)
    if realtime_rows:
        stocks = realtime_rows

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

    debug_steps.append("判断单只集中风险和现金压力")
    if portfolio_summary["max_single_ratio"] > 0.40:
        warnings.append("单只持仓超过家庭可投资资金的 40%，集中度偏高。")
    if portfolio_summary["cash_ratio"] < 0.10:
        warnings.append("现金比例偏低，家庭备用金需要优先关注。")

    debug_steps.append("识别行情、估值和财务数据缺失")
    missing_data = _collect_missing_data(stocks)

    debug_steps.append("调用 analyzer.py 生成风险分析结果")
    analysis = analyze_portfolio(cash, risk_preference, clean_holdings, stocks)

    debug_steps.append("组装 agent_context")
    data_status = analysis.get("data_status", "本地缓存")
    main_risks = analysis.get("risk_notes", [])[:8]

    debug_steps.append("调用 ai_report.py 生成给爸妈看的风险说明")
    api_key = _get_deepseek_api_key()
    if api_key:
        try:
            ai_report = _safe_ai_text(generate_parent_friendly_report(analysis, api_key))
            ai_report_success = True
        except Exception:  # noqa: BLE001
            ai_report = "AI 分析暂时不可用，基础风险体检结果不受影响。"
            ai_report_success = False
    else:
        ai_report = "未配置 AI 分析功能。\n\n" + _safe_ai_text(_fallback_ai_report(analysis, missing_data))
        ai_report_success = False

    agent_result = {
        "success": True,
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
        "saved_history": False,
        "debug_info": {
            "使用本地缓存": not bool(realtime_rows),
            "发现 realtime_data.py": realtime_file_exists,
            "保存历史记录": False,
            "analyzer.py 调用成功": True,
            "ai_report.py 调用成功": ai_report_success,
            "saved_history": False,
            "data_status 原始值": data_status,
        },
        "analysis": analysis,
        "stocks": stocks,
        "holdings": clean_holdings,
    }

    debug_steps.append("保存 analysis_history.csv（如本地 storage.py 可用）")
    agent_result["saved_history"] = _save_history(agent_result, analysis)
    agent_result["debug_info"]["保存历史记录"] = agent_result["saved_history"]
    agent_result["debug_info"]["saved_history"] = agent_result["saved_history"]
    return agent_result
