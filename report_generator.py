from __future__ import annotations

from typing import Any


def money(value: float) -> str:
    return f"{value:,.2f} 元"


def percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def generate_txt_report(analysis: dict[str, Any]) -> str:
    lines = [
        "家庭投资雷达 Agent 体检报告",
        "",
        f"分析时间：{analysis['analysis_time']}",
        f"数据状态：{analysis['data_status']}",
        f"综合评分：{analysis['score']}/100",
        f"风险等级：{analysis['level']}（{analysis['level_text']}）",
        "",
        "家庭概况：",
        f"- 家庭总资产：{money(analysis['total_assets'])}",
        f"- 现金比例：{percent(analysis['cash_ratio'])}",
        f"- 股票/基金总仓位：{percent(analysis['stock_ratio'])}",
        f"- 单只最大占比：{percent(analysis['max_single_ratio'])}",
        f"- 行业集中度：{analysis['top_industry']} {percent(analysis['industry_concentration'])}",
        "",
        "四项得分：",
    ]

    for name, score in analysis["module_scores"].items():
        lines.append(f"- {name}：{score}/100")

    lines.extend(["", "持仓明细："])
    for item in analysis["stock_results"]:
        lines.extend(
            [
                f"- {item['code']} {item['name']}：{money(item['amount'])}，占家庭总资产 {percent(item['single_ratio'])}",
                f"  数据来源：行情 {item['market_source']}；财务 {item['finance_source']}",
                f"  公司底子：{item['financial_text']}",
                f"  交易热度：{item['heat_text']}",
                f"  仓位提醒：{'；'.join(item['position_notes'])}",
            ]
        )

    lines.extend(["", "主要风险提示："])
    for note in analysis["risk_notes"]:
        lines.append(f"- {note}")

    lines.extend(["", "给家人的建议："])
    for note in analysis["advice"]:
        lines.append(f"- {note}")

    lines.extend(
        [
            "",
            "免责声明：本工具仅用于家庭投资风险体检和学习参考，不构成投资建议。市场有风险，投资需谨慎。",
            "本工具不预测明天涨跌，不自动交易，不承诺收益。",
        ]
    )
    return "\n".join(lines)
