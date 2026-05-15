from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


CACHE_FILE = Path(__file__).with_name("stock_metrics.csv")

CACHE_COLUMNS = [
    "股票代码",
    "股票名称",
    "所属行业",
    "最新收盘价",
    "涨跌幅",
    "换手率",
    "量比",
    "振幅",
    "成交额",
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

MARKET_COLUMNS = ["最新收盘价", "涨跌幅", "换手率", "量比", "振幅", "成交额", "内外盘比例"]


def normalize_code(code: str) -> str:
    return str(code or "").strip().upper().zfill(6)


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


def _read_cache() -> pd.DataFrame:
    if not CACHE_FILE.exists():
        return pd.DataFrame(columns=CACHE_COLUMNS)

    df = pd.read_csv(CACHE_FILE, dtype={"股票代码": str})
    if "公司名称" in df.columns and "股票名称" not in df.columns:
        df = df.rename(columns={"公司名称": "股票名称"})

    for column in CACHE_COLUMNS:
        if column not in df.columns:
            df[column] = None

    df = df[CACHE_COLUMNS]
    df["股票代码"] = df["股票代码"].map(normalize_code)
    return df


def _write_cache(df: pd.DataFrame) -> None:
    for column in CACHE_COLUMNS:
        if column not in df.columns:
            df[column] = None
    df = df[CACHE_COLUMNS].copy()
    df["股票代码"] = df["股票代码"].map(normalize_code)
    df = df.drop_duplicates(subset=["股票代码"], keep="last")
    df.to_csv(CACHE_FILE, index=False, encoding="utf-8-sig")


def _cache_row(df: pd.DataFrame, code: str) -> dict[str, Any] | None:
    matched = df[df["股票代码"] == normalize_code(code)]
    if matched.empty:
        return None
    return matched.iloc[0].to_dict()


def _empty_row(code: str) -> dict[str, Any]:
    row = {column: None for column in CACHE_COLUMNS}
    row["股票代码"] = normalize_code(code)
    row["股票名称"] = "数据缺失"
    row["所属行业"] = "未知"
    row["数据来源"] = "数据缺失"
    row["更新时间"] = _now_text()
    row["市场数据来源"] = "数据缺失"
    row["财务数据来源"] = "数据缺失"
    row["错误信息"] = "真实接口和本地缓存都没有找到这只标的。"
    return row


def _fetch_akshare_spot() -> tuple[pd.DataFrame | None, str | None]:
    try:
        import akshare as ak  # type: ignore

        spot = ak.stock_zh_a_spot_em()
        if spot is None or spot.empty:
            return None, "AkShare 返回了空数据。"
        spot["代码"] = spot["代码"].astype(str).map(normalize_code)
        return spot, None
    except Exception as exc:  # noqa: BLE001
        return None, f"AkShare 获取失败：{exc}"


def _pick_market_value(row: pd.Series, *names: str) -> float | None:
    for name in names:
        if name in row.index:
            value = _to_float(row[name])
            if value is not None:
                return value
    return None


def _spot_to_row(spot_row: pd.Series, cached: dict[str, Any] | None, code: str) -> dict[str, Any]:
    row = {column: None for column in CACHE_COLUMNS}
    if cached:
        row.update(cached)

    row["股票代码"] = normalize_code(code)
    row["股票名称"] = spot_row.get("名称") or (cached or {}).get("股票名称") or code
    row["所属行业"] = (cached or {}).get("所属行业") or "未知"
    row["最新收盘价"] = _pick_market_value(spot_row, "最新价", "收盘")
    row["涨跌幅"] = _pick_market_value(spot_row, "涨跌幅")
    row["换手率"] = _pick_market_value(spot_row, "换手率")
    row["量比"] = _pick_market_value(spot_row, "量比")
    row["振幅"] = _pick_market_value(spot_row, "振幅")
    row["成交额"] = _pick_market_value(spot_row, "成交额")
    row["内外盘比例"] = (cached or {}).get("内外盘比例")
    row["数据来源"] = "真实数据"
    row["更新时间"] = _now_text()
    row["市场数据来源"] = "真实数据"

    has_finance = any(_to_float(row.get(column)) is not None for column in FINANCIAL_COLUMNS)
    row["财务数据来源"] = "本地缓存" if has_finance and cached else "数据缺失"
    row["错误信息"] = ""
    return row


def _normalize_output_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = {column: row.get(column) for column in CACHE_COLUMNS}
    normalized["股票代码"] = normalize_code(normalized.get("股票代码"))
    normalized["股票名称"] = normalized.get("股票名称") or normalized["股票代码"]
    normalized["所属行业"] = normalized.get("所属行业") or "未知"

    for column in MARKET_COLUMNS + FINANCIAL_COLUMNS:
        normalized[column] = _to_float(normalized.get(column))

    source = normalized.get("数据来源") or "本地缓存"
    normalized["数据来源"] = source
    normalized["市场数据来源"] = row.get("市场数据来源") or source

    has_finance = any(normalized.get(column) is not None for column in FINANCIAL_COLUMNS)
    normalized["财务数据来源"] = row.get("财务数据来源") or ("本地缓存" if has_finance else "数据缺失")
    normalized["更新时间"] = normalized.get("更新时间") or _now_text()
    normalized["错误信息"] = row.get("错误信息", "")
    return normalized


def get_stock_metrics(codes: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Get stock data with AkShare first, then local CSV cache.

    Returns a tuple of rows and friendly warning messages. Every requested code
    returns one row, including a "数据缺失" row when no source has data.
    """

    clean_codes = []
    for code in codes:
        normalized = normalize_code(code)
        if normalized and normalized not in clean_codes:
            clean_codes.append(normalized)

    cache_df = _read_cache()
    spot_df, ak_error = _fetch_akshare_spot()
    warnings: list[str] = []
    if ak_error:
        warnings.append("真实行情接口暂时不可用，已优先使用本地缓存。")

    result_rows: list[dict[str, Any]] = []
    cache_updates: list[dict[str, Any]] = []

    for code in clean_codes:
        cached = _cache_row(cache_df, code)
        output_row: dict[str, Any] | None = None

        if spot_df is not None:
            spot_match = spot_df[spot_df["代码"] == code]
            if not spot_match.empty:
                output_row = _spot_to_row(spot_match.iloc[0], cached, code)
                cache_updates.append(output_row)

        if output_row is None and cached is not None:
            output_row = dict(cached)
            source = output_row.get("数据来源") or "本地缓存"
            output_row["数据来源"] = "示例数据" if source == "示例数据" else "本地缓存"
            output_row["市场数据来源"] = output_row["数据来源"]
            output_row["财务数据来源"] = output_row["数据来源"]
            output_row["错误信息"] = ""

        if output_row is None:
            output_row = _empty_row(code)

        result_rows.append(_normalize_output_row(output_row))

    if cache_updates:
        merged = pd.concat([cache_df, pd.DataFrame(cache_updates)], ignore_index=True)
        try:
            _write_cache(merged)
        except Exception:  # noqa: BLE001
            warnings.append("真实数据已获取，但写入本地缓存失败；本次页面仍可继续使用。")

    return result_rows, warnings
