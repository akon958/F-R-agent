"""report_exporter.py – 报告导出：将体检结果转换为可下载的纯文本报告。

调用方式（在 app.py 中）：
    from report_exporter import export_text_report
    text = export_text_report(agent_result)
    st.download_button("下载体检报告", data=text.encode("utf-8"), file_name="family_risk_report.txt")
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _money(value: Any) -> str:
    try:
        v = float(value)
        if v >= 1e8:
            return f"{v / 1e8:.1f} 亿元"
        if v >= 1e4:
            return f"{v / 1e4:.1f} 万元"
        return f"{v:,.0f} 元"
    except (TypeError, ValueError):
        return "—"


def _priority_label(p: str) -> str:
    return {"high": "● 高优先", "medium": "◎ 中优先", "low": "○ 低优先"}.get(p, "◎ 中优先")


def export_text_report(agent_result: dict[str, Any]) -> str:
    """生成纯文本格式的体检报告，供用户下载。"""
    if not agent_result:
        return "暂无体检记录，请先完成一次一键智能体检。"

    now = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    run_id = str(agent_result.get("run_id") or "")[:8]

    score       = agent_result.get("risk_score", 0)
    level       = agent_result.get("risk_level", "")
    data_status = agent_result.get("data_status", "本地缓存")

    portfolio    = agent_result.get("portfolio_summary") or {}
    total_assets = portfolio.get("total_assets", 0)
    cash_ratio   = portfolio.get("cash_ratio", 0)
    stock_ratio  = portfolio.get("stock_ratio", 0)
    max_single   = portfolio.get("max_single_ratio", 0)

    holdings    = agent_result.get("holdings") or []
    main_risks  = agent_result.get("main_risks") or []
    watch_tasks = agent_result.get("watch_tasks") or []
    ai_report   = str(agent_result.get("ai_report") or "")

    # 主动预警摘要
    delta = agent_result.get("delta_alert") or {}
    delta_line = ""
    if delta.get("has_alert") and delta.get("summary"):
        delta_line = f"△ 与上次相比：{delta['summary']}\n"

    # 交叉验证警告
    cross_val  = agent_result.get("cross_validation") or {}
    cv_issues  = list(cross_val.get("issues") or [])
    cv_section = ""
    if cv_issues:
        cv_section = "\n【一致性警告】\n" + "\n".join(f"• {i}" for i in cv_issues) + "\n"

    # 数据置信度
    confidence    = agent_result.get("data_confidence") or {}
    conf_level    = str(confidence.get("level") or "")
    conf_summary  = str(confidence.get("summary") or "")
    conf_line     = f"数据置信度：{conf_level}（{conf_summary}）\n" if conf_level else ""

    sep = "=" * 52

    lines: list[str] = [
        sep,
        "FamilyReader  家庭持仓风险体检报告",
        sep,
        f"生成时间：{now}",
        f"体检编号：{run_id or '—'}",
        f"数据来源：{data_status}",
        conf_line.rstrip(),
        "",
        "【体检概要】",
        f"  综合评分：{score}/100",
        f"  风险等级：{level}",
        f"  家庭总资产：{_money(total_assets)}",
        f"  现金比例：{_pct(cash_ratio)}",
        f"  股票/基金比例：{_pct(stock_ratio)}",
        f"  最大单只占比：{_pct(max_single)}",
    ]

    if delta_line:
        lines.append(delta_line.rstrip())

    lines += ["", "【持仓明细】"]
    if holdings:
        for h in holdings:
            code   = str(h.get("code") or "")
            name   = str(h.get("name") or code)
            amount = _money(h.get("amount", 0))
            ratio  = _pct(h.get("position_ratio", 0))
            lines.append(f"  {code}  {name}  {amount}  占比 {ratio}")
    else:
        lines.append("  （暂无持仓明细）")

    lines += ["", "【主要风险】"]
    if main_risks:
        for r in main_risks[:6]:
            lines.append(f"• {r}")
    else:
        lines.append("本次体检未发现特别突出的风险。")

    if cv_section:
        lines.append(cv_section.rstrip())

    if watch_tasks:
        lines += ["", "【近期待办任务】"]
        for t in watch_tasks:
            pri   = _priority_label(t.get("priority", "medium"))
            title = t.get("title", "")
            desc  = t.get("desc", "")
            lines.append(f"{pri}  {title}")
            if desc:
                lines.append(f"   {desc}")

    if ai_report:
        lines += ["", "【AI 风险说明】", "（由 DeepSeek AI 生成，仅供学习参考）", ""]
        # 去掉多余空行
        for part in ai_report.split("\n"):
            lines.append(part)

    lines += [
        "",
        sep,
        "本工具只做家庭投资风险体检和学习参考，不构成任何投资建议，也不替任何人做交易决定。",
        sep,
    ]

    return "\n".join(lines)
