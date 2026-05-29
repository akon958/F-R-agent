from __future__ import annotations

"""压力测试 / 历史回放共用的格式化与严重度工具。

`stress_test.py` 与 `history_replay.py` 是姊妹模块，原先各自复制了一份
to_float / money / severity / cushion_note。现统一到此，单点维护，避免改一处忘另一处。
"""

from typing import Any


def to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def money(value: float) -> str:
    """父母视角的金额：万元为主，小额回退到元。"""
    value = to_float(value)
    if abs(value) >= 10000:
        return f"{value / 10000:.1f} 万元"
    return f"{value:.0f} 元"


def severity(loss_ratio: float) -> tuple[str, str]:
    """按"占全家资产的比例"判断严重度，返回 (code, label)。"""
    if loss_ratio >= 0.15:
        return "severe", "影响重大"
    if loss_ratio >= 0.05:
        return "notable", "影响明显"
    return "mild", "影响有限"


def cushion_note(loss: float, cash: float, *, noun: str = "账面损失") -> str:
    """现金垫能否缓冲这笔账面损失/回撤。只描述事实，不给操作建议。

    noun：压力测试用"账面损失"，历史回放用"账面回撤"。
    """
    if cash <= 0:
        return "几乎没有现金垫，波动会直接压到本金，先确认家里短期是否要用钱。"
    cover = loss / cash if cash > 0 else None
    if cover is not None and cover > 1:
        return (
            f"这笔{noun}约为现金垫的 {cover:.1f} 倍（现金约 {money(cash)}），"
            "缓冲不够，建议先把用钱计划聊清楚。"
        )
    return f"现金垫能覆盖这笔{noun}（现金约 {money(cash)}），短期缓冲较从容。"
