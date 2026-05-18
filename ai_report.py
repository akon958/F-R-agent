from __future__ import annotations

import json
from typing import Any


DISCLAIMER = "本工具只做家庭投资风险体检和学习参考，不构成任何投资建议，也不提供买卖推荐。"


def _safe_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _build_ai_context(analysis: dict[str, Any]) -> dict[str, Any]:
    stock_items = []
    for item in analysis.get("stock_results", []):
        stock_items.append(
            {
                "code": item.get("code", ""),
                "name": item.get("name", ""),
                "amount": item.get("amount", 0),
                "single_ratio": item.get("single_ratio", 0),
                "level": item.get("level", ""),
                "industry": item.get("industry", ""),
                "financial_text": item.get("financial_text", ""),
                "heat_text": item.get("heat_text", ""),
                "position_notes": item.get("position_notes", []),
                "data_source": item.get("data_source", ""),
                "market_source": item.get("market_source", ""),
                "finance_source": item.get("finance_source", ""),
            }
        )

    return {
        "score": analysis.get("score", 0),
        "level": analysis.get("level", ""),
        "level_text": analysis.get("level_text", ""),
        "data_status": analysis.get("data_status", ""),
        "analysis_time": analysis.get("analysis_time", ""),
        "cash": analysis.get("cash", 0),
        "total_assets": analysis.get("total_assets", 0),
        "cash_ratio": analysis.get("cash_ratio", 0),
        "stock_ratio": analysis.get("stock_ratio", 0),
        "max_single_ratio": analysis.get("max_single_ratio", 0),
        "top_industry": analysis.get("top_industry", ""),
        "industry_concentration": analysis.get("industry_concentration", 0),
        "module_scores": analysis.get("module_scores", {}),
        "risk_notes": analysis.get("risk_notes", []),
        "advice": analysis.get("advice", []),
        "stocks": stock_items,
    }


def generate_parent_friendly_report(analysis: dict[str, Any], api_key: str) -> str:
    """Call DeepSeek to write a plain-language risk explanation for family users."""
    if not api_key:
        raise ValueError("missing api key")

    from openai import OpenAI

    context = _build_ai_context(analysis)
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    rules = [
        "1. 语气像在家庭微信群里回消息：用'我们''爸''妈'，偶尔用'其实''不过''另外'等口语连接词，"
        "读起来像真人在说话，不像在朗读报告。不用'您家''贵家庭''阁下'等疏远表达。",
        "2. 不推荐任何股票，不预测涨跌，不说'必涨''抄底''一定赚''马上卖'，"
        "不给买入/卖出/加仓/减仓的具体指令。",
        "3. 每次出现财务或交易指标，先写专业术语，括号里跟一句通俗说明，两者缺一不可。"
        "标准写法示例（格式不变）：\n"
        "   ROE（公司用自己的钱赚钱的能力）\n"
        "   净利率（每卖出100元最终留下多少利润）\n"
        "   毛利率（产品本身的赚钱空间）\n"
        "   营收增长率（公司收入有没有在增加）\n"
        "   净利润增长率（公司最终到手的钱有没有在增加）\n"
        "   资产负债率（公司借了多少钱相对自己的家底）\n"
        "   经营现金流（公司账面利润有多少真正变成了现金）\n"
        "   换手率（今天有多少人在买卖这只股票）\n"
        "   量比（今天成交量比平时多多少）\n"
        "   振幅（今天股价最高最低相差多少）\n"
        "   市盈率（按现在股价买，需要多少年回本）\n"
        "   市净率（股价相对公司账面资产贵不贵）",
        "4. 总字数控制在 600～700 字，内容要扎实，但不要凑字数，爸妈一口气能看完最好。",
        "5. 按下面五段结构输出，每段加标题，顺序不变，不增减段落：\n"
        "   【整体感觉】\n   【主要风险】\n   【数据缺失说明】\n   【爸妈重点看什么】\n   【免责声明】",
        "6. 【免责声明】那段原文照抄，一字不改：" + DISCLAIMER,
    ]

    system_prompt = (
        "你是家里懂一点投资的亲戚，正在用微信跟家人解释这次持仓风险体检的结果。\n"
        "你说话直接、温和，会把枯燥的数据翻译成家人听得懂的话，"
        "但绝不给任何买卖建议，因为你知道预测市场是不靠谱的。\n\n"
        "写作要求：\n"
        + "\n".join(rules)
    )

    data_note = (
        "数据缺失处理：\n"
        "- 某只持仓的 finance_source 是「数据缺失」→ 【数据缺失说明】里提一句：行情找到了，但财务数据暂时缺，"
        "对这只股票的公司质量判断不完整，要多留心。\n"
        "- 所有数据都完整 → 写：这次体检数据都找到了，没有明显缺失。"
    )

    user_prompt = (
        "下面是家庭投资风险体检的 JSON 结果，请按你的写作要求输出给爸妈看的说明。\n\n"
        + data_note
        + "\n\n体检数据：\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
    )

    # deepseek-reasoner (R1) 推理模型：分析更深入，响应约慢 3-5 倍，费用约贵 15 倍。
    # 如需切回快速版，把 model 改为 "deepseek-chat"，temperature 改回 0.35。
    response = client.chat.completions.create(
        model="deepseek-reasoner",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.6,   # R1 官方推荐区间 0.5-0.7
        max_tokens=2048,
    )

    content = _safe_text(response.choices[0].message.content).strip()
    if DISCLAIMER not in content:
        content = f"{content}\n\n{DISCLAIMER}"
    return content
