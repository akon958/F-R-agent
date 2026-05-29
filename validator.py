from __future__ import annotations

from typing import Any

from config import COMPLIANCE_REPLACEMENTS


def sanitize_compliance_text(text: str) -> str:
    safe = str(text or "")
    for old, new in COMPLIANCE_REPLACEMENTS.items():
        safe = safe.replace(old, new)
    return safe


def sanitize_structured(obj: Any) -> Any:
    """递归地对结构化输出（dict/list/tuple/str）做合规词替换。

    stress_test / family_dialogue / longitudinal_story / history_replay 的结构化文案
    不经过 agent._safe_ai_text，agent 在组装结果时统一对它们调用本函数，形成
    defense-in-depth：即便某个增量模块的文案漏了禁词，这里也会按 COMPLIANCE_REPLACEMENTS
    兜底替换掉。对当前合规文案是无操作（不含禁词），只在未来改动引入禁词时才生效。
    """
    if isinstance(obj, str):
        return sanitize_compliance_text(obj)
    if isinstance(obj, dict):
        return {key: sanitize_structured(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [sanitize_structured(item) for item in obj]
    if isinstance(obj, tuple):
        return tuple(sanitize_structured(item) for item in obj)
    return obj


RISKY_REPORT_TERMS = {
    "行业第一所以可以买": "同业排名靠前，只能作为观察点",
    "排名靠后所以卖": "同业排名靠后，需要继续观察",
    "股息率高所以买": "股息率较高，只能说明分红回报这一项值得观察",
    "股息率高所以稳赚": "股息率较高不代表收益确定",
    "现金流好所以买": "现金流质量较好，只能作为公司质量观察点",
    "趋势改善所以会上涨": "趋势改善不代表未来股价会上涨",
    "分红会越来越高": "不能预测未来分红",
}


def scan_financial_claims(text: str) -> dict[str, Any]:
    """Scan report text for financial over-claims after model generation."""
    safe = str(text or "")
    issues: list[str] = []
    sanitized = safe
    for phrase, replacement in RISKY_REPORT_TERMS.items():
        if phrase in sanitized:
            issues.append(phrase)
            sanitized = sanitized.replace(phrase, replacement)
    return {
        "passed": len(issues) == 0,
        "issues": issues,
        "text": sanitized,
    }


def cross_validate(
    risk_score: int,
    risk_level: str,
    portfolio_summary: dict[str, Any],
    risk_factors: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """多重交叉验证：对体检各模块输出做内部一致性检查。

    三项检查：
    1. 评分数字与风险等级文字是否吻合
    2. 现金比例 + 持仓比例合计是否接近 100%
    3. 风险因子加权合成分与综合评分是否一致

    Returns
    -------
    {
        "passed":     bool,       # True = 无明显矛盾
        "issues":     list[str],  # 明显矛盾，需要提示用户
        "notes":      list[str],  # 轻微差异，仅记录
        "checks_run": int,        # 实际执行的检查项数
    }
    """
    issues: list[str] = []
    notes: list[str] = []
    checks_run = 0

    # ── 检查 1：评分与风险等级文字一致性 ──────────────────────────
    checks_run += 1
    level_text = str(risk_level or "")
    if risk_score > 0:
        is_high_label = any(kw in level_text for kw in ("红", "偏高"))
        is_low_label  = any(kw in level_text for kw in ("绿", "较低"))
        if risk_score >= 80 and is_high_label:
            issues.append(
                f"评分 {risk_score} 分，但风险等级标注为偏高；"
                "两者不一致，可能因为持仓数据与缓存有延迟"
            )
        elif risk_score < 60 and is_low_label:
            issues.append(
                f"评分 {risk_score} 分偏低，但风险等级标注为较低；"
                "两者不一致，建议重新检查持仓和缓存数据"
            )

    # ── 检查 2：现金 + 持仓比例是否自洽 ──────────────────────────
    checks_run += 1
    cash  = float(portfolio_summary.get("cash_ratio")  or 0)
    stock = float(portfolio_summary.get("stock_ratio") or 0)
    total = cash + stock
    if total > 0.01:
        if abs(total - 1.0) > 0.08:
            notes.append(
                f"现金 {cash * 100:.0f}% + 持仓 {stock * 100:.0f}% = {total * 100:.0f}%，"
                "合计与 100% 有出入，可能有未归类资产或录入误差"
            )

    # ── 检查 3：因子加权合成分与综合评分一致性 ──────────────────
    if risk_factors:
        checks_run += 1
        factors = list(risk_factors.get("factors") or [])
        if factors and risk_score > 0:
            try:
                weighted_sum = sum(
                    float(f.get("score") or 0) * float(f.get("weight") or 0) / 100
                    for f in factors
                )
                gap = abs(weighted_sum - risk_score)
                if gap > 15:
                    notes.append(
                        f"因子加权得分约 {weighted_sum:.0f} 分，与综合评分 {risk_score} 分"
                        f"相差 {gap:.0f} 分，可能因风险规则触发了保守限制"
                        "（如单只/行业过于集中、交易过热、现金过低或数据缺失等）"
                    )
            except Exception:  # noqa: BLE001
                pass

    return {
        "passed":     len(issues) == 0,
        "issues":     issues,
        "notes":      notes,
        "checks_run": checks_run,
    }
