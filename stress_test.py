from __future__ import annotations

"""家庭持仓极端情景压力测试（Stress Test）。

定位：在几种历史上真实出现过的极端下跌情景下，估算家庭资产会账面缩水多少、
现金垫还够不够，帮助家人提前感受波动、把"半年内要不要用钱"聊清楚。

严格约束（遵守 CLAUDE.md）：
- 不预测涨跌：这里给的是"假设发生 X% 下跌"的情景演练，不是判断会不会跌。
- 不给交易建议：不出现买入/卖出/加仓/减仓/抄底等字眼。
- 不改评分：本模块只读 analysis，产出独立字段，绝不修改 score 或风险等级。
- 账面 ≠ 真实：账面波动只有在真正变现时才会成为实际盈亏，文案里必须说清楚。

⚠️ 合规警示：本模块产出的结构化文案【不经过】agent.py 的 _safe_ai_text() 中央禁词
过滤器。任何对本文件文案的改动，都必须先跑 `python -m unittest tests.test_stress_test`，
确保禁词回归测试通过后再提交，否则可能直接把违规措辞带到页面上。
"""

from typing import Any

from scenario_common import to_float as _f, money as _money, severity as _severity, cushion_note as _cushion_note


# ── 情景跌幅（取历史上出现过的、可解释的整数档，便于父母理解）──────────────
#   - 个股重挫 30%：A 股单只连续数个跌停即可达到，重仓股最直接的风险。
#   - 行业系统性回调 30%：单一行业遇政策/景气逆转时的常见量级。
#   - 全市场普跌 20%：参考 2018 全年沪深300 约 -25%、2015 股灾单段 -30%+ 的保守取值。
SINGLE_STOCK_SHOCK = 0.30
INDUSTRY_SHOCK = 0.30
MARKET_SHOCK = 0.20

_INVALID_INDUSTRY = {"", "未知", "无", "None", "none"}

_DISCLAIMER = (
    "以上均为假设性压力测试，不是涨跌预测；账面上的涨跌只有在真正变现时才会成为实际盈亏。"
    "本工具只做家庭投资风险体检和学习参考，不构成任何投资建议，也不替任何人做交易决定。"
)


def _build_scenario(
    *,
    key: str,
    title: str,
    shock: float,
    affected_value: float,
    affected_label: str,
    total_assets: float,
    cash: float,
) -> dict[str, Any]:
    loss = affected_value * shock
    assets_after = max(0.0, total_assets - loss)
    loss_ratio = loss / total_assets if total_assets > 0 else 0.0
    sev_code, sev_label = _severity(loss_ratio)

    plain = (
        f"假设{affected_label}短期下跌 {shock:.0%}，全家资产会账面缩水约 {_money(loss)}"
        f"（约占全家总资产的 {loss_ratio:.0%}），"
        f"从 {_money(total_assets)} 降到约 {_money(assets_after)}。"
    )
    return {
        "key": key,
        "title": title,
        "shock_pct": round(shock, 4),
        "affected_value": round(affected_value, 2),
        "loss": round(loss, 2),
        "assets_after": round(assets_after, 2),
        "loss_ratio": round(loss_ratio, 4),
        "severity": sev_code,
        "severity_label": sev_label,
        "plain": plain,
        "cushion_note": _cushion_note(loss, cash),
    }


def run_stress_test(analysis: dict[str, Any]) -> dict[str, Any]:
    """对一次体检结果做极端情景压力测试。

    输入：analyze_portfolio() 产出的 analysis（需含 total_assets / cash /
          stock_total / top_industry / industry_concentration / stock_results）。
    输出：结构化情景列表 + 最坏情景 + 一句话总结。永不抛异常。
    """
    empty = {
        "available": False,
        "reason": "本次没有股票或基金持仓，无需做下跌压力测试。",
        "scenarios": [],
        "worst_case": None,
        "summary": "",
        "disclaimer": _DISCLAIMER,
    }
    try:
        total_assets = _f(analysis.get("total_assets"))
        cash = _f(analysis.get("cash"))
        stock_total = _f(analysis.get("stock_total"))
        stock_results = list(analysis.get("stock_results") or [])

        if total_assets <= 0 or stock_total <= 0 or not stock_results:
            return empty

        scenarios: list[dict[str, Any]] = []

        # ── 情景 1：最大单只重仓重挫 ──────────────────────────────────
        largest = max(stock_results, key=lambda s: _f(s.get("amount")), default=None)
        if largest and _f(largest.get("amount")) > 0:
            name = str(largest.get("name") or largest.get("code") or "最大持仓")
            scenarios.append(_build_scenario(
                key="single_stock",
                title="最重的一只大跌",
                shock=SINGLE_STOCK_SHOCK,
                affected_value=_f(largest.get("amount")),
                affected_label=f"持仓最重的「{name}」",
                total_assets=total_assets,
                cash=cash,
            ))

        # ── 情景 2：最集中行业系统性回调 ──────────────────────────────
        top_industry = str(analysis.get("top_industry") or "").strip()
        if top_industry not in _INVALID_INDUSTRY:
            industry_holdings = [
                s for s in stock_results
                if str(s.get("industry") or "").strip() == top_industry
            ]
            industry_value = sum(_f(s.get("amount")) for s in industry_holdings)
            # 仅当该行业不止一只持仓时才单列，避免与"最大单只"完全重复
            if industry_value > 0 and len(industry_holdings) > 1:
                scenarios.append(_build_scenario(
                    key="industry",
                    title=f"{top_industry}行业系统性回调",
                    shock=INDUSTRY_SHOCK,
                    affected_value=industry_value,
                    affected_label=f"集中持有的{top_industry}行业（{len(industry_holdings)} 只）",
                    total_assets=total_assets,
                    cash=cash,
                ))

        # ── 情景 3：全市场普跌 ────────────────────────────────────────
        scenarios.append(_build_scenario(
            key="market",
            title="全市场普跌",
            shock=MARKET_SHOCK,
            affected_value=stock_total,
            affected_label="全部股票和基金持仓",
            total_assets=total_assets,
            cash=cash,
        ))

        worst = max(scenarios, key=lambda s: s.get("loss", 0), default=None)
        if worst:
            summary = (
                f"在假设的极端下跌情景里，全家资产最多可能账面缩水约 "
                f"{_money(worst['loss'])}（约占 {worst['loss_ratio']:.0%}），"
                f"对应情景：{worst['title']}。这是情景演练，不是预测。"
            )
        else:
            summary = ""

        return {
            "available": True,
            "reason": "",
            "scenarios": scenarios,
            "worst_case": worst,
            "summary": summary,
            "disclaimer": _DISCLAIMER,
        }
    except Exception:  # noqa: BLE001 — 压力测试是增量功能，任何异常都不应影响体检主流程
        return {
            "available": False,
            "reason": "压力测试本次未能计算，不影响其他体检结论。",
            "scenarios": [],
            "worst_case": None,
            "summary": "",
            "disclaimer": _DISCLAIMER,
        }
