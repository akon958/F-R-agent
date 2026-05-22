from __future__ import annotations

from typing import Any


COMMAND_HELP = """/risk：看看当前组合主要风险
/parents：换成爸妈能听懂的话
/disagreement：看看家里意见不一致的地方
/cash：看看现金缓冲和短期用钱压力
/history：看看历次体检的风险变化趋势
/tasks：查看本次体检生成的优先待办任务
/confidence：了解本次数据置信度和缺口影响
/help：查看这些命令怎么用"""


_ROUTED_QUESTIONS = {
    "/risk": "请解释当前组合的主要风险，只基于本次体检结果，重点说明风险来自哪里。",
    "/parents": "请用爸妈能听懂的话重新解释本次体检结果，少用金融术语。",
    "/disagreement": "请只解释本次家庭分歧点和沟通重点，不判断谁对谁错，只提醒先沟通一致。",
    "/cash": "请重点解释现金缓冲、半年内可能用钱的问题，以及遇到波动时的承受能力。",
    "/history": (
        "请基于 agent_context 里的 history_analysis 和 agent_memory，"
        "简要说明这个家庭的风险变化趋势：与上次相比是改善、恶化还是基本稳定？"
        "如果历史记录不足，只说明本次体检结果，不要编造历史数据。"
    ),
    "/tasks": (
        "请列出并解释本次体检最优先需要处理的待办事项。"
        "结合 agent_context 中的现金比例、持仓集中度和数据缺失情况，"
        "说明每条任务的原因和紧迫程度，语言通俗，适合家人阅读。"
    ),
    "/confidence": (
        "请解释本次体检的数据置信度：哪些数据缺失（行情/估值/财务），"
        "各类缺失对结论可靠性有什么具体影响，以及家人应该怎么看待这份结论。"
        "语言通俗，不用技术术语。"
    ),
}


def slash_command_help_text() -> str:
    return COMMAND_HELP


def route_slash_command(question: str) -> dict[str, Any]:
    text = str(question or "").strip()
    if not text.startswith("/"):
        return {"is_command": False, "command": "", "direct": False, "routed_question": text, "answer": ""}

    command = text.split(maxsplit=1)[0].lower()
    if command == "/help":
        return {
            "is_command": True,
            "command": command,
            "direct": True,
            "routed_question": "",
            "answer": "可以用这些快捷命令继续追问：\n\n" + COMMAND_HELP,
        }

    routed = _ROUTED_QUESTIONS.get(command)
    if routed:
        return {
            "is_command": True,
            "command": command,
            "direct": False,
            "routed_question": routed,
            "answer": "",
        }

    return {
        "is_command": True,
        "command": command,
        "direct": True,
        "routed_question": "",
        "answer": "暂时不认识这个命令。\n\n" + COMMAND_HELP,
    }
