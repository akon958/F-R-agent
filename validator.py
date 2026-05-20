from __future__ import annotations


_REPLACEMENTS = {
    "买入": "继续观察",
    "卖出": "重点复盘",
    "加仓": "先一起商量",
    "减仓": "控制集中度",
    "推荐": "风险提示",
    "预测上涨": "不判断短期方向",
    "稳赚": "不承诺收益",
    "保证收益": "不承诺收益",
    "必涨": "不判断短期方向",
    "一定赚钱": "不承诺收益",
}


def sanitize_compliance_text(text: str) -> str:
    safe = str(text or "")
    for old, new in _REPLACEMENTS.items():
        safe = safe.replace(old, new)
    return safe
