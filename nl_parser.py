"""nl_parser.py – 自然语言持仓输入解析器。

用户可以用口语描述持仓：
  "我有茅台20万，招行10万，另外现金5万"
  "600519 茅台 200000元，000001 平安 100000"

优先调用 DeepSeek，失败时用正则兜底。

返回格式：
  {
    "holdings": [{"code": str, "name": str, "amount": float}],
    "cash":     float,
    "risk_preference": "保守/稳健/平衡/进取/积极/空字符串",
    "source":   "deepseek" | "regex",
    "confidence": "high" | "medium" | "low",
    "parse_note": str,
  }
"""
from __future__ import annotations

import json
import os
import re
from typing import Any


# 金额单位
_UNITS: dict[str, float] = {
    "亿": 1e8,
    "千万": 1e7,
    "百万": 1e6,
    "万": 1e4,
    "千": 1e3,
}

# 常见股票名 → 代码（仅辅助正则兜底；DeepSeek 不依赖这张表）
_NAME_TO_CODE: dict[str, str] = {
    "茅台": "600519", "贵州茅台": "600519",
    "平安银行": "000001", "平安": "000001",
    "招商银行": "600036", "招行": "600036",
    "宁德时代": "300750", "宁德": "300750",
    "中国平安": "601318",
    "工商银行": "601398", "工行": "601398",
    "建设银行": "601939", "建行": "601939",
    "中国银行": "601988",
    "农业银行": "601288", "农行": "601288",
    "格力电器": "000651", "格力": "000651",
    "美的集团": "000333", "美的": "000333",
    "比亚迪": "002594",
    "五粮液": "000858",
    "海天味业": "603288",
    "中信证券": "600030",
    "兴业银行": "601166",
    "万科": "000002", "万科A": "000002",
    "隆基绿能": "601012", "隆基": "601012",
    "三一重工": "600031",
    "迈瑞医疗": "300760",
}

_CASH_KEYWORDS = ("现金", "存款", "余额", "货币", "活期", "定期", "备用金", "存折")
_RISK_PREFERENCES = ("保守", "稳健", "平衡", "进取", "积极")


def _detect_risk_preference(text: str) -> str:
    """从口语输入里识别风险承受能力；识别不到时返回空字符串。"""
    for name in _RISK_PREFERENCES:
        if name in text:
            return name
    return ""


def _get_deepseek_key() -> str:
    try:
        import streamlit as st  # type: ignore
        key = str(st.secrets.get("DEEPSEEK_API_KEY", "")).strip()
        if key:
            return key
    except Exception:  # noqa: BLE001
        pass
    return os.getenv("DEEPSEEK_API_KEY", "").strip()


def _parse_amount_text(text: str) -> float | None:
    """从文字段中提取数字金额（支持中文单位）。"""
    text = text.strip().replace(",", "").replace("，", "")
    for unit, mult in _UNITS.items():
        pattern = rf"([\d.]+)\s*{unit}"
        m = re.search(pattern, text)
        if m:
            try:
                return float(m.group(1)) * mult
            except ValueError:
                pass
    # 纯数字（元）
    m = re.search(r"([\d.]+)\s*元?", text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def _resolve_code_hint(text: str) -> str:
    """Resolve a 6-digit stock code from either a code-like string or a stock name."""
    raw = str(text or "").strip()
    if not raw:
        return ""

    digits = re.sub(r"\D", "", raw)
    if len(digits) == 6:
        return digits

    if raw in _NAME_TO_CODE:
        return _NAME_TO_CODE[raw]

    try:
        from data_fetcher import resolve_code_or_name  # local import to avoid startup coupling

        return str(resolve_code_or_name(raw) or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _normalize_risk_preference(value: Any) -> str:
    text = str(value or "").strip()
    return text if text in _RISK_PREFERENCES else ""


def _post_process_result(parsed: dict[str, Any]) -> dict[str, Any]:
    """Repair parsed holdings by filling stock codes from names when possible."""
    holdings: list[dict[str, Any]] = []
    repaired_count = 0
    unresolved_count = 0
    seen: set[tuple[str, str]] = set()

    for item in parsed.get("holdings") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        raw_code = str(item.get("code") or "").strip()
        try:
            amount = float(item.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue

        resolved_code = _resolve_code_hint(raw_code) or _resolve_code_hint(name)
        if not raw_code and resolved_code:
            repaired_count += 1
        if not resolved_code:
            unresolved_count += 1

        dedupe_key = (resolved_code, name) if resolved_code else ("", name)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        holdings.append({"code": resolved_code, "name": name, "amount": amount})

    note_parts: list[str] = []
    base_note = str(parsed.get("parse_note") or "").strip()
    if base_note:
        note_parts.append(base_note)
    if repaired_count:
        note_parts.append(f"已根据名称补全 {repaired_count} 只持仓的股票代码。")
    if unresolved_count:
        note_parts.append(f"仍有 {unresolved_count} 只持仓未识别股票代码。")

    result = dict(parsed)
    result["holdings"] = holdings
    result["cash"] = float(parsed.get("cash") or 0)
    result["risk_preference"] = _normalize_risk_preference(parsed.get("risk_preference"))
    result["parse_note"] = " ".join(note_parts).strip()
    if holdings:
        if unresolved_count == 0:
            result["confidence"] = "high"
        elif str(parsed.get("confidence") or "") == "low":
            result["confidence"] = "medium"
    else:
        result["confidence"] = "low"
    return result


def _iter_known_name_code_pairs() -> list[tuple[str, str]]:
    pairs: dict[str, str] = dict(_NAME_TO_CODE)
    try:
        from data_fetcher import _build_name_lookup  # type: ignore[attr-defined]

        for name, code in dict(_build_name_lookup() or {}).items():
            clean_name = str(name or "").strip()
            clean_code = str(code or "").strip()
            if clean_name and clean_code:
                pairs.setdefault(clean_name, clean_code)
    except Exception:  # noqa: BLE001
        pass
    return sorted(pairs.items(), key=lambda x: -len(x[0]))


def _regex_parse(text: str) -> dict[str, Any]:
    """正则兜底解析器：适合格式较规范的中文描述。"""
    holdings: list[dict[str, Any]] = []
    cash = 0.0

    clean = (
        text.replace("，", " ").replace("、", " ").replace("。", " ")
            .replace("；", " ").replace(";", " ").replace("\n", " ")
    )

    # 识别现金
    for kw in _CASH_KEYWORDS:
        pattern = kw + r"\s*([\d.]+)\s*([亿千万]*)(?:元|块)?"
        for m in re.finditer(pattern, clean):
            try:
                num = float(m.group(1))
                unit = m.group(2)
                mult = _UNITS.get(unit, 1.0)
                cash = max(cash, num * mult)
            except (TypeError, ValueError):
                pass

    # 识别持仓：可选代码 + 名称 + 金额
    # 模式1: "600519 茅台 20万" / "600519 贵州茅台 200000元"
    code_pattern = r"(\d{6})\s+([^\d\s，。；,\n]{1,12}?)\s+([\d.]+)\s*([亿千万]?)(?:元|块)?"
    for m in re.finditer(code_pattern, clean):
        code, name = m.group(1), m.group(2).strip()
        try:
            amount = float(m.group(3)) * _UNITS.get(m.group(4), 1.0)
        except (TypeError, ValueError):
            continue
        if amount > 0 and not any(kw in name for kw in _CASH_KEYWORDS):
            holdings.append({"code": code, "name": name, "amount": amount})

    # 模式2: "茅台20万" / "招行 10万元"（仅匹配已知名称）
    # 长名称优先排序，防止"平安"在"中国平安"之前命中导致代码错误
    _sorted_names = _iter_known_name_code_pairs()
    for name, code in _sorted_names:
        # 跳过已通过代码或名称匹配到的（双重去重：code 和 name 均检查）
        if any(h["code"] == code or h["name"] == name for h in holdings):
            continue
        # 允许"我有茅台 2 万"这类口语前缀，同时避免"平安"误匹配"中国平安"。
        prefix = r"(?:^|[\s,，。；、:：]|有|持有|拿着|买了|买|持仓)"
        pattern = prefix + r"\s*" + re.escape(name) + r"(?![^\W\d_])\s*([\d.]+)\s*([亿千万]?)(?:元|块)?"
        m = re.search(pattern, clean)
        if m:
            try:
                amount = float(m.group(1)) * _UNITS.get(m.group(2), 1.0)
            except (TypeError, ValueError):
                continue
            if amount > 0:
                holdings.append({"code": code, "name": name, "amount": amount})

    confidence: str
    if holdings:
        confidence = "medium"
        note = "已用规则解析，建议确认代码和金额是否正确。"
    else:
        confidence = "low"
        note = "未识别到持仓，请检查格式或改用手动填写。"

    return {
        "holdings": holdings,
        "cash": cash,
        "risk_preference": _detect_risk_preference(clean),
        "source": "regex",
        "confidence": confidence,
        "parse_note": note,
    }


_SYSTEM_PROMPT = """你是持仓数据解析助手。将用户的自然语言输入解析为结构化 JSON。

严格输出以下格式（不加多余文字）：
{
  "holdings": [
    {"code": "6位股票代码字符串，不确定时填空字符串", "name": "名称", "amount": 金额数字(单位:元)}
  ],
  "cash": 现金金额(数字,单位元,没有填0),
  "risk_preference": "保守/稳健/平衡/进取/积极；没有识别到就填空字符串",
  "parse_note": "一句话说明哪些识别成功、哪些未识别"
}

规则：
- 金额统一换算成元（"20万"→200000）
- 现金/存款/余额宝等归入cash字段，不计入holdings
- 代码必须是6位数字，不确定时留空字符串""
- 不确定的持仓宁缺勿滥，在parse_note里注明"""


def _deepseek_parse(text: str) -> dict[str, Any] | None:
    """调用 DeepSeek 解析自然语言持仓，失败返回 None。"""
    api_key = _get_deepseek_key()
    if not api_key:
        return None
    try:
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=20.0)
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"请解析以下持仓描述：\n{text}"},
            ],
            temperature=0.0,
            max_tokens=600,
        )
        raw = str(resp.choices[0].message.content or "").strip()
        # 提取 JSON（可能被包在 ```json ... ``` 中）
        json_match = re.search(r"\{[\s\S]*\}", raw)
        if not json_match:
            return None
        parsed = json.loads(json_match.group())
        holdings = [
            h for h in (parsed.get("holdings") or [])
            if isinstance(h, dict) and float(h.get("amount") or 0) > 0
        ]
        cash = float(parsed.get("cash") or 0)
        note = str(parsed.get("parse_note") or "")
        return {
            "holdings": holdings,
            "cash": cash,
            "risk_preference": str(parsed.get("risk_preference") or "").strip(),
            "source": "deepseek",
            "confidence": "high" if holdings else "low",
            "parse_note": note,
        }
    except Exception:  # noqa: BLE001
        return None


def parse_holdings_nl(text: str) -> dict[str, Any]:
    """将自然语言持仓描述解析为结构化数据。

    DeepSeek 优先，失败时用正则兜底。
    """
    text = str(text or "").strip()
    if not text:
        return {
            "holdings": [], "cash": 0.0,
            "risk_preference": "",
            "source": "regex", "confidence": "low",
            "parse_note": "输入为空，请填写持仓描述。",
        }

    ds = _deepseek_parse(text)
    if ds is not None:
        return _post_process_result(ds)

    return _post_process_result(_regex_parse(text))
