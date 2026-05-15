from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


CACHE_FILE = Path(__file__).with_name("stock_metrics.csv")

CACHE_COLUMNS = [
    "代码",
    "名称",
    "最新价",
    "涨跌幅",
    "成交额",
    "市盈率-动态",
    "市净率",
    "换手率",
    "总市值",
    "流通市值",
    "所属行业",
    "量比",
    "振幅",
    "内外盘比例",
    "ROE",
    "净利率",
    "毛利率",
    "营收增长率",
    "净利润增长率",
    "资产负债率",
    "经营现金流/净利润",
    "数据来源",
    "更新时间",
]

FINANCIAL_COLUMNS = [
    "ROE",
    "净利率",
    "毛利率",
    "营收增长率",
    "净利润增长率",
    "资产负债率",
    "经营现金流/净利润",
]

ALIASES = {
    "代码": ["代码", "股票代码"],
    "名称": ["名称", "股票名称", "公司名称"],
    "最新价": ["最新价", "最新收盘价", "收盘"],
    "市盈率-动态": ["市盈率-动态", "市盈率动态", "动态市盈率"],
    "市净率": ["市净率"],
    "总市值": ["总市值"],
    "流通市值": ["流通市值"],
}


def normalize_code(code: str) -> str:
    text = str(code or "").strip().upper()
    if text.startswith(("SH", "SZ", "BJ")):
        text = text[2:]
    return text.zfill(6) if text else ""


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _to_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    if text in {"", "-", "--", "None", "nan"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _first_present(row: pd.Series | dict[str, Any], names: list[str]) -> Any:
    for name in names:
        if name in row:
            value = row[name]
            if value is not None and not pd.isna(value):
                return value
    return None


def _read_cache() -> pd.DataFrame:
    if not CACHE_FILE.exists():
        return pd.DataFrame(columns=CACHE_COLUMNS)

    df = pd.read_csv(CACHE_FILE, dtype={"代码": str, "股票代码": str})
    normalized = pd.DataFrame()
    for column in CACHE_COLUMNS:
        aliases = ALIASES.get(column, [column])
        source = next((alias for alias in aliases if alias in df.columns), None)
        normalized[column] = df[source] if source else None

    normalized["代码"] = normalized["代码"].map(normalize_code)
    normalized = normalized[normalized["代码"] != ""]
    return normalized


def _write_cache(df: pd.DataFrame) -> None:
    for column in CACHE_COLUMNS:
        if column not in df.columns:
            df[column] = None
    output = df[CACHE_COLUMNS].copy()
    output["代码"] = output["代码"].map(normalize_code)
    output = output[output["代码"] != ""]
    output = output.drop_duplicates(subset=["代码"], keep="last")
    output.to_csv(CACHE_FILE, index=False, encoding="utf-8-sig")


def get_cache_summary() -> dict[str, Any]:
    df = _read_cache()
    if df.empty:
        return {"count": 0, "latest_update": "无", "finance_count": 0}
    finance_count = df[FINANCIAL_COLUMNS].notna().any(axis=1).sum()
    latest_update = df["更新时间"].dropna().astype(str).max() if "更新时间" in df.columns else "无"
    return {"count": int(len(df)), "latest_update": latest_update or "无", "finance_count": int(finance_count)}


def _cache_row(df: pd.DataFrame, code: str) -> dict[str, Any] | None:
    matched = df[df["代码"] == normalize_code(code)]
    if matched.empty:
        return None
    return matched.iloc[0].to_dict()


def _spot_to_cache_row(spot_row: pd.Series, cached: dict[str, Any] | None = None) -> dict[str, Any]:
    row = {column: None for column in CACHE_COLUMNS}
    if cached:
        row.update(cached)

    row["代码"] = normalize_code(_first_present(spot_row, ["代码"]))
    row["名称"] = _first_present(spot_row, ["名称"]) or row["名称"] or row["代码"]
    row["最新价"] = _to_float(_first_present(spot_row, ["最新价", "收盘"]))
    row["涨跌幅"] = _to_float(_first_present(spot_row, ["涨跌幅"]))
    row["成交额"] = _to_float(_first_present(spot_row, ["成交额"]))
    row["市盈率-动态"] = _to_float(_first_present(spot_row, ["市盈率-动态", "市盈率动态", "动态市盈率"]))
    row["市净率"] = _to_float(_first_present(spot_row, ["市净率"]))
    row["换手率"] = _to_float(_first_present(spot_row, ["换手率"]))
    row["总市值"] = _to_float(_first_present(spot_row, ["总市值"]))
    row["流通市值"] = _to_float(_first_present(spot_row, ["流通市值"]))
    row["量比"] = _to_float(_first_present(spot_row, ["量比"]))
    row["振幅"] = _to_float(_first_present(spot_row, ["振幅"]))
    row["所属行业"] = row.get("所属行业") or "未知"
    row["数据来源"] = "真实数据"
    row["更新时间"] = _now_text()
    return row


def _cache_to_analyzer_row(row: dict[str, Any] | None, code: str) -> dict[str, Any]:
    if row is None:
        return {
            "股票代码": normalize_code(code),
            "股票名称": "数据缺失",
            "所属行业": "未知",
            "最新收盘价": None,
            "涨跌幅": None,
            "换手率": None,
            "量比": None,
            "振幅": None,
            "成交额": None,
            "内外盘比例": None,
            "市盈率-动态": None,
            "市净率": None,
            "总市值": None,
            "流通市值": None,
            "ROE": None,
            "净利率": None,
            "毛利率": None,
            "营收增长率": None,
            "净利润增长率": None,
            "资产负债率": None,
            "经营现金流/净利润": None,
            "数据来源": "数据缺失",
            "市场数据来源": "数据缺失",
            "财务数据来源": "数据缺失",
            "更新时间": _now_text(),
            "错误信息": "本地缓存没有找到这只标的。",
        }

    has_finance = any(_to_float(row.get(column)) is not None for column in FINANCIAL_COLUMNS)
    source = row.get("数据来源") or "本地缓存"
    return {
        "股票代码": normalize_code(row.get("代码")),
        "股票名称": row.get("名称") or normalize_code(code),
        "所属行业": row.get("所属行业") or "未知",
        "最新收盘价": _to_float(row.get("最新价")),
        "涨跌幅": _to_float(row.get("涨跌幅")),
        "换手率": _to_float(row.get("换手率")),
        "量比": _to_float(row.get("量比")),
        "振幅": _to_float(row.get("振幅")),
        "成交额": _to_float(row.get("成交额")),
        "内外盘比例": _to_float(row.get("内外盘比例")),
        "市盈率-动态": _to_float(row.get("市盈率-动态")),
        "市净率": _to_float(row.get("市净率")),
        "总市值": _to_float(row.get("总市值")),
        "流通市值": _to_float(row.get("流通市值")),
        "ROE": _to_float(row.get("ROE")),
        "净利率": _to_float(row.get("净利率")),
        "毛利率": _to_float(row.get("毛利率")),
        "营收增长率": _to_float(row.get("营收增长率")),
        "净利润增长率": _to_float(row.get("净利润增长率")),
        "资产负债率": _to_float(row.get("资产负债率")),
        "经营现金流/净利润": _to_float(row.get("经营现金流/净利润")),
        "数据来源": source,
        "市场数据来源": source,
        "财务数据来源": source if has_finance else "数据缺失",
        "更新时间": row.get("更新时间") or _now_text(),
        "错误信息": "",
    }


def _fetch_akshare_spot() -> pd.DataFrame | None:
    try:
        import akshare as ak  # type: ignore

        spot = ak.stock_zh_a_spot_em()
        if spot is None or spot.empty or "代码" not in spot.columns:
            return None
        spot["代码"] = spot["代码"].astype(str).map(normalize_code)
        return spot
    except Exception:  # noqa: BLE001
        return None


def get_stock_metrics(codes: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Read requested stock data from local cache only.

    Streamlit Cloud should be stable and fast by default, so the main page does
    not automatically fetch AkShare data. Use manual refresh buttons or
    update_cache.py to update stock_metrics.csv.
    """

    cache_df = _read_cache()
    rows: list[dict[str, Any]] = []
    for code in codes:
        normalized = normalize_code(code)
        if not normalized:
            continue
        rows.append(_cache_to_analyzer_row(_cache_row(cache_df, normalized), normalized))
    return rows, []


def refresh_current_holdings_cache(codes: list[str]) -> tuple[dict[str, Any], list[str]]:
    clean_codes = []
    for code in codes:
        normalized = normalize_code(code)
        if normalized and normalized not in clean_codes:
            clean_codes.append(normalized)

    if not clean_codes:
        return get_cache_summary(), ["没有可更新的股票代码。"]

    cache_df = _read_cache()
    spot_df = _fetch_akshare_spot()
    if spot_df is None:
        return get_cache_summary(), ["实时行情更新失败，已使用本地缓存数据。"]

    updates: list[dict[str, Any]] = []
    missing: list[str] = []
    for code in clean_codes:
        matched = spot_df[spot_df["代码"] == code]
        if matched.empty:
            missing.append(code)
            continue
        updates.append(_spot_to_cache_row(matched.iloc[0], _cache_row(cache_df, code)))

    if updates:
        _write_cache(pd.concat([cache_df, pd.DataFrame(updates)], ignore_index=True))

    messages = [f"已更新 {len(updates)} 只当前持仓的行情缓存。"]
    if missing:
        messages.append("部分代码实时行情未找到，已保留本地缓存数据。")
    return get_cache_summary(), messages


def refresh_market_cache() -> tuple[dict[str, Any], list[str]]:
    """Fetch all A-share spot data and save it as stock_metrics.csv."""

    cache_df = _read_cache()
    spot_df = _fetch_akshare_spot()
    if spot_df is None:
        return get_cache_summary(), ["实时行情更新失败，已使用本地缓存数据。"]

    rows = [_spot_to_cache_row(spot_row, _cache_row(cache_df, spot_row["代码"])) for _, spot_row in spot_df.iterrows()]
    _write_cache(pd.concat([cache_df, pd.DataFrame(rows)], ignore_index=True))
    return get_cache_summary(), [f"已更新 {len(rows)} 只 A 股行情缓存。"]
