from __future__ import annotations

"""家庭持仓历史风险回放（History Replay）。

定位：把家庭【当前这套持仓】原样放回 A 股历史上几段真实发生过的大幅下跌里，
估算账面会回撤多少、现金垫够不够，帮父母用"真实发生过的事"理解波动，
把"半年内要不要用钱"聊清楚。是 stress_test.py 的姊妹模块——压力测试用的是
假设档位，本模块用的是历史上真实出现过的区间。

严格约束（遵守 CLAUDE.md）：
- 不预测涨跌：这里讲的是"如果原样经历过去那段下跌会怎样"，不是判断未来会不会跌。
- 不给交易建议：不出现买入/卖出/加仓/减仓/抄底等字眼。
- 不改评分：本模块只读 analysis，产出独立字段，绝不修改 score 或风险等级。
- 近似声明：我们没有每只个股的历史日 K，统一用【大盘同期回撤】做近似，
  个股实际涨跌可能更大或更小，文案里必须说清楚，绝不编造个股历史跌幅。
- 账面 ≠ 真实：账面回撤只有在真正变现时才会成为实际盈亏，文案里必须说清楚。

⚠️ 合规警示：本模块产出的结构化文案【不经过】agent.py 的 _safe_ai_text() 中央禁词
过滤器。任何对本文件文案的改动，都必须先跑 `python -m unittest tests.test_history_replay`，
确保禁词回归测试通过后再提交，否则可能直接把违规措辞带到页面上。

数据来源：HISTORICAL_SCENARIOS 是硬编码的静态历史回撤系数表，纯查表、零网络依赖，
契合"页面启动不抓行情"的原则。各区间取沪深300（大盘）高点→低点的保守整数档，
口径统一为"大盘同期回撤"。如需调整区间或数值，只改这张表即可。
"""

from typing import Any


# ── 历史下跌区间（口径：沪深300 区间内峰谷最大回撤，实测后四舍五入到整数档）──────
#   数值来源：东方财富 push2his 日线（沪深300，2007-01 至 2022-12），按"区间内
#   最高点 → 之后最低点"计算峰谷最大回撤，即原样持有经历该区间时账面最深的缩水。
#   只收录"全市场广基下跌"的区间——这类下跌对各类持仓影响相对一致，用单一
#   大盘系数套到全部股票/基金才站得住脚。结构性、分化型行情（如 2024 年初
#   小微盘流动性冲击，大盘仅回撤个位数而小盘 -30%+）不收录，避免用单一系数误导。
#   如需重新核对或扩充区间：拉东财 push2his 日线（secid=1.000300，klt=101），
#   对目标区间按"区间内最高点→之后最低点"算峰谷回撤，再更新本表即可。
HISTORICAL_SCENARIOS: list[dict[str, Any]] = [
    {
        "key": "crisis_2008",
        "title": "2008 年全球金融危机",
        "period": "2008 年 1–11 月",
        "market_drawdown": 0.72,   # 沪深300 峰谷 -72.1%（2008-01-14 → 2008-11-04）
        "context": "次贷危机引发全球股市重挫，A 股全年单边下行，是近十几年最深的一段。",
    },
    {
        "key": "bear_2011",
        "title": "2011 年熊市",
        "period": "2011 年全年",
        "market_drawdown": 0.33,   # 沪深300 峰谷 -32.9%（2011-04-11 → 2011-12-28）
        "context": "紧缩与经济放缓叠加，全年震荡下行、缺乏像样反弹。",
    },
    {
        "key": "crash_2015",
        "title": "2015 年股灾",
        "period": "2015 年 6 月–2016 年 1 月",
        "market_drawdown": 0.47,   # 沪深300 峰谷 -47.2%（2015-06-09 → 2016-01-27）
        "context": "杠杆资金集中去化，半年内大盘从高点回落近五成。",
    },
    {
        "key": "circuit_2016",
        "title": "2016 年初熔断",
        "period": "2016 年 1 月",
        "market_drawdown": 0.24,   # 沪深300 峰谷 -23.8%（2016-01-04 → 2016-01-27）
        "context": "熔断机制实施后短短数日内连续触发，月内快速回撤。",
    },
    {
        "key": "bear_2018",
        "title": "2018 年全年下跌",
        "period": "2018 年全年",
        "market_drawdown": 0.33,   # 沪深300 峰谷 -32.7%（2018-01-26 → 2018-12-25）
        "context": "贸易摩擦叠加去杠杆，全年单边下行、缺乏反弹。",
    },
    {
        "key": "pullback_2022",
        "title": "2022 年回调",
        "period": "2022 年初–4 月底",
        "market_drawdown": 0.24,   # 沪深300 峰谷 -24.3%（2022-01-04 → 2022-04-27）
        "context": "加息与外部冲击下，年内一度回撤约两成半。",
    },
]


_DISCLAIMER = (
    "以上是把当前持仓放回历史区间的回放，不是对未来的预测；"
    "这里统一用大盘同期回撤做近似，个股实际涨跌可能更大或更小；"
    "账面上的回撤只有在真正变现时才会成为实际盈亏。"
    "本工具只做家庭投资风险体检和学习参考，不构成任何投资建议，也不替任何人做交易决定。"
)


def _f(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _money(value: float) -> str:
    """父母视角的金额：万元为主，小额回退到元。"""
    value = _f(value)
    if abs(value) >= 10000:
        return f"{value / 10000:.1f} 万元"
    return f"{value:.0f} 元"


def _severity(loss_ratio: float) -> tuple[str, str]:
    """按"占全家资产的比例"判断严重度，返回 (code, label)。"""
    if loss_ratio >= 0.15:
        return "severe", "影响重大"
    if loss_ratio >= 0.05:
        return "notable", "影响明显"
    return "mild", "影响有限"


def _cushion_note(loss: float, cash: float) -> str:
    """现金垫能否缓冲这笔账面回撤。只描述事实，不给操作建议。"""
    if cash <= 0:
        return "目前几乎没有现金垫，这类波动会直接压到本金，建议先确认家里短期是否要用钱。"
    cover = loss / cash if cash > 0 else None
    if cover is not None and cover > 1:
        return (
            f"这笔账面回撤约为家庭现金垫的 {cover:.1f} 倍（现金约 {_money(cash)}），"
            "现金垫不足以完全缓冲，适合提前把用钱计划聊清楚。"
        )
    return f"家庭现金垫约能覆盖这笔账面回撤（现金约 {_money(cash)}），短期缓冲相对从容。"


def _build_scenario(
    *,
    scenario: dict[str, Any],
    stock_total: float,
    total_assets: float,
    cash: float,
) -> dict[str, Any]:
    drawdown = _f(scenario.get("market_drawdown"))
    loss = stock_total * drawdown
    assets_after = max(0.0, total_assets - loss)
    loss_ratio = loss / total_assets if total_assets > 0 else 0.0
    sev_code, sev_label = _severity(loss_ratio)

    plain = (
        f"如果现在这套持仓原样经历{scenario.get('title')}（{scenario.get('period')}），"
        f"股票和基金部分按大盘同期约回撤 {drawdown:.0%} 估算，"
        f"全家资产会账面缩水约 {_money(loss)}（约占全家总资产的 {loss_ratio:.0%}），"
        f"从 {_money(total_assets)} 降到约 {_money(assets_after)}。"
    )
    return {
        "key": str(scenario.get("key") or ""),
        "title": str(scenario.get("title") or ""),
        "period": str(scenario.get("period") or ""),
        "drawdown_pct": round(drawdown, 4),
        "loss": round(loss, 2),
        "assets_after": round(assets_after, 2),
        "loss_ratio": round(loss_ratio, 4),
        "severity": sev_code,
        "severity_label": sev_label,
        "plain": plain,
        "cushion_note": _cushion_note(loss, cash),
        "context": str(scenario.get("context") or ""),
    }


def run_history_replay(analysis: dict[str, Any]) -> dict[str, Any]:
    """把一次体检的当前持仓放回历史下跌区间做回放。

    输入：analyze_portfolio() 产出的 analysis（需含 total_assets / cash / stock_total）。
    输出：结构化历史区间列表（按时间顺序）+ 回撤最深区间 + 一句话总结。永不抛异常。
    """
    empty = {
        "available": False,
        "reason": "本次没有股票或基金持仓，无需做历史回放。",
        "scenarios": [],
        "worst_case": None,
        "summary": "",
        "disclaimer": _DISCLAIMER,
    }
    try:
        total_assets = _f(analysis.get("total_assets"))
        cash = _f(analysis.get("cash"))
        stock_total = _f(analysis.get("stock_total"))

        if total_assets <= 0 or stock_total <= 0:
            return empty

        scenarios = [
            _build_scenario(
                scenario=scenario,
                stock_total=stock_total,
                total_assets=total_assets,
                cash=cash,
            )
            for scenario in HISTORICAL_SCENARIOS
        ]

        worst = max(scenarios, key=lambda s: s.get("loss", 0), default=None)
        if worst:
            summary = (
                f"把当前持仓放回过去这几段真实下跌里，账面回撤最深的一次约为 "
                f"{worst['loss_ratio']:.0%}（缩水约 {_money(worst['loss'])}），"
                f"对应{worst['title']}。这是历史回放，不是预测未来。"
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
    except Exception:  # noqa: BLE001 — 历史回放是增量功能，任何异常都不应影响体检主流程
        return {
            "available": False,
            "reason": "历史回放本次未能计算，不影响其他体检结论。",
            "scenarios": [],
            "worst_case": None,
            "summary": "",
            "disclaimer": _DISCLAIMER,
        }
