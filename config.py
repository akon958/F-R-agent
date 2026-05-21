from __future__ import annotations

APP_TITLE = "FamilyReader"
APP_SUBTITLE = "家庭持仓读懂器"
PRODUCT_FULL_NAME = "FamilyReader 家庭持仓读懂器"

FIXED_DISCLAIMER = "本工具只做家庭投资风险体检和学习参考，不构成任何投资建议，也不替任何人做交易决定。"
HOME_DISCLAIMER = FIXED_DISCLAIMER
REPORT_DISCLAIMER = "本报告由 AI 综合生成，仅供学习参考，不构成投资建议。投资有风险，决策需谨慎。"

DEFAULT_CODES = ["600519", "000001", "300750"]
DEFAULT_AMOUNTS = [20000.0, 10000.0, 0.0]

DEFAULT_REPORT_MODE = "标准版"
REPORT_MODES = ["标准版", "简洁版", "详细版"]

RISK_PROFILE_OPTIONS = ["保守", "稳健", "平衡", "进取", "积极"]
RISK_PROFILE_HINTS = {
    "保守": "更看重本金波动小，现金垫要厚，单只占比会更严格。",
    "稳健": "可以接受小幅波动，但家庭安全垫仍放在前面。",
    "平衡": "能接受一定波动，重点看现金、仓位和集中度是否匹配。",
    "进取": "能承受较大波动，但仍要避免过度集中。",
    "积极": "波动承受能力较强，也不鼓励满仓或把钱压在少数标的上。",
}
RISK_PROFILE_SHORT_HINTS = {
    "保守": "现金优先，少波动",
    "稳健": "留足备用金",
    "平衡": "兼顾现金和仓位",
    "进取": "能承受较大波动",
    "积极": "承受力强，也防集中",
}

DEFAULT_FOLLOWUP_QUESTIONS = [
    "现金比例怎么看？",
    "哪只标的最需要关注？",
    "PE/PB 对这次判断有什么帮助？",
    "数据缺失会影响判断吗？",
    "为什么这个组合还需要继续观察？",
    "给爸妈一句话怎么说？",
]

COMPLIANCE_REPLACEMENTS = {
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

REVERSE_QA_DEFAULT = {
    "money_need_6m": "uncertain",
    "volatility_reaction": "discuss",
    "last_disagreement": "",
}
