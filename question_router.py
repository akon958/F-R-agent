from __future__ import annotations

from typing import Any


COMMAND_HELP = """/risk：看看当前组合主要风险
/parents：换成爸妈能听懂的话
/disagreement：看看家里意见不一致的地方
/cash：看看现金缓冲和短期用钱压力
/help：查看这些命令怎么用"""


_ROUTED_QUESTIONS = {
    "/risk": "请解释当前组合的主要风险，只基于本次体检结果，重点说明风险来自哪里。",
    "/parents": "请用爸妈能听懂的话重新解释本次体检结果，少用金融术语。",
    "/disagreement": "请只解释本次家庭分歧点和沟通重点，不判断谁对谁错，只提醒先沟通一致。",
    "/cash": "请重点解释现金缓冲、半年内可能用钱的问题，以及遇到波动时的承受能力。",
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
