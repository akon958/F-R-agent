from __future__ import annotations

import functools
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd


# 国内网络访问东财接口偶发 SSL 解密失败，关闭证书校验可显著提升稳定性
_SSL_FIXED = False


def _apply_ssl_fix() -> None:
    global _SSL_FIXED
    if _SSL_FIXED:
        return
    try:
        import ssl

        ssl._create_default_https_context = ssl._create_unverified_context  # noqa: SLF001
    except Exception:  # noqa: BLE001
        pass
    try:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:  # noqa: BLE001
        pass
    _SSL_FIXED = True


_NETWORK_ERROR_KEYWORDS = (
    "SSL", "ssl", "Connection", "Timeout", "timeout",
    "RemoteDisconnected", "reset", "aborted", "EOF",
    "Max retries", "ProxyError", "ConnectError",
)


def _is_network_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}"
    return any(k in text for k in _NETWORK_ERROR_KEYWORDS)


def _retry(func: Callable[[], Any], retries: int = 3, wait: float = 3.0) -> Any:
    """网络错误时最多重试 retries 次，每次等待时间递增。"""
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < retries and _is_network_error(exc):
                time.sleep(wait * attempt)
                continue
            raise
    if last_err is not None:
        raise last_err
    return None


BASE_DIR = Path(__file__).resolve().parent
CACHE_FILE = BASE_DIR / "stock_metrics.csv"
CACHE_CANDIDATES = [
    BASE_DIR / "stock_metrics.csv",
    BASE_DIR / "data" / "stock_metrics.csv",
    Path.cwd() / "stock_metrics.csv",
]

HISTORY_PERIOD_LABELS = ("近1期", "近2期", "近3期")
CASHFLOW_HISTORY_COLUMNS = [f"经营现金流/净利润_{label}" for label in HISTORY_PERIOD_LABELS]
DIVIDEND_HISTORY_COLUMNS = [f"股息率_{label}" for label in HISTORY_PERIOD_LABELS]

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
    *CASHFLOW_HISTORY_COLUMNS,
    "股息率",
    *DIVIDEND_HISTORY_COLUMNS,
    "数据来源",
    "更新时间",
]

FIELD_MAP = {
    "code": "代码",
    "name": "名称",
    "price": "最新价",
    "pct_change": "涨跌幅",
    "turnover": "成交额",
    "pe": "市盈率-动态",
    "pb": "市净率",
    "turnover_rate": "换手率",
    "market_cap": "总市值",
    "float_market_cap": "流通市值",
    "industry": "所属行业",
    "volume_ratio": "量比",
    "amplitude": "振幅",
    "in_out_ratio": "内外盘比例",
    "roe": "ROE",
    "net_margin": "净利率",
    "gross_margin": "毛利率",
    "revenue_growth": "营收增长率",
    "profit_growth": "净利润增长率",
    "debt_ratio": "资产负债率",
    "cashflow_profit_ratio": "经营现金流/净利润",
    "dividend_yield": "股息率",
    "data_source": "数据来源",
    "updated_at": "更新时间",
}

FINANCIAL_COLUMNS = [
    "ROE",
    "净利率",
    "毛利率",
    "营收增长率",
    "净利润增长率",
    "资产负债率",
    "经营现金流/净利润",
]

COLUMN_FALLBACKS = {
    "经营现金流/净利润_近1期": ["经营现金流/净利润"],
    "股息率_近1期": ["股息率"],
}

ALIASES = {
    "代码": ["代码", "股票代码", "code"],
    "名称": ["名称", "股票名称", "公司名称", "name"],
    "最新价": ["最新价", "最新收盘价", "收盘", "price"],
    "涨跌幅": ["涨跌幅", "pct_change"],
    "成交额": ["成交额", "turnover"],
    "市盈率-动态": ["市盈率-动态", "市盈率动态", "动态市盈率", "pe"],
    "市净率": ["市净率", "pb"],
    "换手率": ["换手率", "turnover_rate"],
    "总市值": ["总市值", "market_cap"],
    "流通市值": ["流通市值", "float_market_cap"],
    "所属行业": ["所属行业", "industry"],
    "量比": ["量比", "volume_ratio"],
    "振幅": ["振幅", "amplitude"],
    "内外盘比例": ["内外盘比例", "in_out_ratio"],
    "ROE": ["ROE", "roe"],
    "净利率": ["净利率", "net_margin"],
    "毛利率": ["毛利率", "gross_margin"],
    "营收增长率": ["营收增长率", "revenue_growth"],
    "净利润增长率": ["净利润增长率", "profit_growth"],
    "资产负债率": ["资产负债率", "debt_ratio"],
    "经营现金流/净利润": ["经营现金流/净利润", "cashflow_profit_ratio"],
    "经营现金流/净利润_近1期": ["经营现金流/净利润_近1期", "经营现金流/净利润"],
    "经营现金流/净利润_近2期": ["经营现金流/净利润_近2期"],
    "经营现金流/净利润_近3期": ["经营现金流/净利润_近3期"],
    "股息率": ["股息率", "dividend_yield"],
    "股息率_近1期": ["股息率_近1期", "股息率", "dividend_yield"],
    "股息率_近2期": ["股息率_近2期"],
    "股息率_近3期": ["股息率_近3期"],
    "数据来源": ["数据来源", "data_source"],
    "更新时间": ["更新时间", "updated_at"],
}


def normalize_code(code: str) -> str:
    text = str(code or "").strip().upper()
    if text.startswith(("SH", "SZ", "BJ")):
        text = text[2:]
    return text.zfill(6) if text else ""


@functools.lru_cache(maxsize=1)
def _build_name_lookup() -> dict[str, str]:
    """Build a name → code dict from stock_metrics.csv (cached for process lifetime).

    Keys are stripped names (e.g. "招商银行"); values are zero-padded 6-digit codes.
    Returns an empty dict if the CSV cannot be read.
    """
    try:
        path = _resolve_cache_file()
        df = pd.read_csv(path, encoding="utf-8-sig", usecols=["代码", "名称"])
        lookup: dict[str, str] = {}
        for _, row in df.iterrows():
            name = str(row.get("名称") or "").strip()
            raw_code = str(row.get("代码") or "").strip()
            if name and raw_code:
                lookup[name] = normalize_code(raw_code)
        return lookup
    except Exception:  # noqa: BLE001
        return {}


def resolve_code_or_name(text: str) -> str:
    """Return a normalised 6-digit code from either a code string or a stock name.

    Lookup order:
    1. If the input is already all digits (with optional SH/SZ/BJ prefix), normalise directly.
    2. Exact name match against stock_metrics.csv.
    3. Case-insensitive exact match (handles full-width / whitespace variations).
    Falls back to the raw normalize_code result (empty string) when nothing matches.
    """
    raw = str(text or "").strip()
    if not raw:
        return ""

    # Step 1: looks like a numeric code already
    stripped = raw.upper()
    if stripped.startswith(("SH", "SZ", "BJ")):
        stripped = stripped[3:] if stripped[3:4] == "" else stripped[2:]
    if stripped.isdigit():
        return normalize_code(raw)

    # Step 2 & 3: try name lookup
    lookup = _build_name_lookup()
    if raw in lookup:
        return lookup[raw]

    # Case-insensitive / whitespace-normalised fallback
    raw_lower = raw.lower().replace(" ", "").replace("　", "")
    for name, code in lookup.items():
        if name.lower().replace(" ", "").replace("　", "") == raw_lower:
            return code

    # Partial / nickname match: input is a substring of exactly one stock name
    # e.g. "茅台" → "贵州茅台"；若匹配多只则视为歧义，不自动解析
    partial = [code for name, code in lookup.items()
               if raw_lower in name.lower().replace(" ", "").replace("　", "")]
    if len(partial) == 1:
        return partial[0]

    # Last resort: only accept if normalised result is purely numeric (e.g. fund
    # codes entered without prefix).  Non-numeric strings that didn't match any
    # name should return "" so the caller can flag it as invalid input.
    normalised = normalize_code(raw)
    return normalised if normalised.isdigit() else ""


# ── 申万一级行业映射 ──────────────────────────────────────────────────────

_INDUSTRY_MAP_FILE = BASE_DIR / "industry_map.csv"
_industry_cache: dict[str, str] | None = None   # None = 未加载, {} = 加载成功但文件空
_industry_meta: dict[str, Any] = {}
_industry_warn_printed = False


def _load_industry_map() -> dict[str, str]:
    """读取 industry_map.csv 到内存，进程生命周期内只读一次。"""
    global _industry_cache, _industry_meta, _industry_warn_printed
    if _industry_cache is not None:
        return _industry_cache

    if not _INDUSTRY_MAP_FILE.exists():
        if not _industry_warn_printed:
            print(f"[industry] 警告：{_INDUSTRY_MAP_FILE} 不存在，get_industry() 将始终返回 None。"
                  "请先运行 build_industry_map.py 生成该文件。")
            _industry_warn_printed = True
        _industry_cache = {}
        return _industry_cache

    try:
        import pandas as _pd
        df = _pd.read_csv(_INDUSTRY_MAP_FILE, encoding="utf-8-sig", dtype=str)
        mapping: dict[str, str] = {}
        last_updated = ""
        for _, row in df.iterrows():
            code = str(row.get("code") or "").strip().zfill(6)
            industry = str(row.get("sw_industry") or "").strip()
            if code and industry and industry.lower() != "nan" and industry.lower() != "none":
                mapping[code] = industry
            if not last_updated:
                last_updated = str(row.get("last_updated") or "").strip()
        _industry_meta = {
            "total_stocks": len(df),
            "with_industry": len(mapping),
            "last_updated": last_updated,
        }
        _industry_cache = mapping
        return _industry_cache
    except Exception as exc:  # noqa: BLE001
        if not _industry_warn_printed:
            print(f"[industry] 警告：读取 {_INDUSTRY_MAP_FILE} 失败（{exc}），get_industry() 将始终返回 None。")
            _industry_warn_printed = True
        _industry_cache = {}
        return _industry_cache


def get_industry(stock_code: str) -> str | None:
    """返回股票的申万一级行业名称，找不到或文件缺失则返回 None。"""
    code = normalize_code(str(stock_code or "").strip())
    if not code:
        return None
    return _load_industry_map().get(code)


def get_industry_meta() -> dict[str, Any]:
    """返回 industry_map.csv 的元信息，供调试和监控使用。"""
    _load_industry_map()   # 确保已加载
    return dict(_industry_meta)


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _cache_candidates() -> list[Path]:
    candidates: list[Path] = []
    for candidate in CACHE_CANDIDATES:
        resolved = candidate.resolve()
        if resolved not in candidates:
            candidates.append(resolved)
    return candidates


def _resolve_cache_file() -> Path:
    for candidate in _cache_candidates():
        if candidate.exists():
            return candidate
    checked = "；".join(str(path) for path in _cache_candidates())
    raise FileNotFoundError(
        f"未找到 stock_metrics.csv，请确认该文件已上传到 GitHub 仓库根目录或 data 目录。已检查路径：{checked}"
    )


def get_cache_diagnostics() -> dict[str, Any]:
    candidates = _cache_candidates()
    existing = [path for path in candidates if path.exists()]
    return {
        "cwd": str(Path.cwd()),
        "checked_paths": [str(path) for path in candidates],
        "found_path": str(existing[0]) if existing else "",
    }


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


def _coalesce_numeric_columns(df: pd.DataFrame, target: str, fallbacks: list[str]) -> None:
    if target not in df.columns:
        df[target] = None
    for fallback in fallbacks:
        if fallback not in df.columns:
            continue
        mask = df[target].map(_to_float).isna()
        if mask.any():
            df.loc[mask, target] = df.loc[mask, fallback]


def _ensure_cache_schema(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    for column in CACHE_COLUMNS:
        aliases = ALIASES.get(column, [column])
        source = next((alias for alias in aliases if alias in normalized.columns), None)
        if source is None:
            fallback = next((name for name in COLUMN_FALLBACKS.get(column, []) if name in normalized.columns), None)
            normalized[column] = normalized[fallback] if fallback else None
        elif source != column:
            normalized[column] = normalized[source]

    _coalesce_numeric_columns(normalized, "经营现金流/净利润_近1期", ["经营现金流/净利润"])
    _coalesce_numeric_columns(normalized, "股息率_近1期", ["股息率"])
    _coalesce_numeric_columns(normalized, "经营现金流/净利润", ["经营现金流/净利润_近1期"])
    _coalesce_numeric_columns(normalized, "股息率", ["股息率_近1期"])
    return normalized


def _read_cache() -> pd.DataFrame:
    cache_file = _resolve_cache_file()
    df = pd.read_csv(cache_file, dtype={"代码": str, "股票代码": str})
    normalized = _ensure_cache_schema(df)
    normalized["代码"] = normalized["代码"].map(normalize_code)
    normalized = normalized[normalized["代码"] != ""]
    return normalized


def _write_cache(df: pd.DataFrame) -> None:
    output = _ensure_cache_schema(df)[CACHE_COLUMNS].copy()
    output["代码"] = output["代码"].map(normalize_code)
    output = output[output["代码"] != ""]
    output = output.drop_duplicates(subset=["代码"], keep="last")
    output.to_csv(CACHE_FILE, index=False, encoding="utf-8-sig")


def get_cache_summary() -> dict[str, Any]:
    try:
        cache_file = _resolve_cache_file()
    except FileNotFoundError:
        return {"exists": False, "count": 0, "message": "暂无缓存数据"}
    try:
        df = _read_cache()
    except Exception:  # noqa: BLE001
        return {"exists": False, "count": 0, "message": "缓存读取失败，不影响风险体检"}
    if df.empty:
        return {"exists": True, "count": 0, "message": "暂无缓存数据"}
    finance_count = df[FINANCIAL_COLUMNS].notna().any(axis=1).sum()
    latest_update = df["更新时间"].dropna().astype(str).max() if "更新时间" in df.columns else "暂无缓存数据"
    count = int(len(df))
    return {
        "exists": True,
        "count": count,
        "message": f"缓存现有 {count} 只标的",
        "cache_file": str(cache_file),
        "latest_update": latest_update or "暂无缓存数据",
        "finance_count": int(finance_count),
    }


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
            "code": normalize_code(code),
            "name": "数据缺失",
            "industry": "未知",
            "price": None,
            "pct_change": None,
            "turnover": None,
            "pe": None,
            "pb": None,
            "turnover_rate": None,
            "market_cap": None,
            "float_market_cap": None,
            "volume_ratio": None,
            "amplitude": None,
            "in_out_ratio": None,
            "roe": None,
            "net_margin": None,
            "gross_margin": None,
            "revenue_growth": None,
            "profit_growth": None,
            "debt_ratio": None,
            "cashflow_profit_ratio": None,
            "cashflow_profit_ratio_p1": None,
            "cashflow_profit_ratio_p2": None,
            "cashflow_profit_ratio_p3": None,
            "dividend_yield": None,
            "dividend_yield_p1": None,
            "dividend_yield_p2": None,
            "dividend_yield_p3": None,
            "data_source": "数据缺失",
            "updated_at": _now_text(),
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
            "经营现金流/净利润_近1期": None,
            "经营现金流/净利润_近2期": None,
            "经营现金流/净利润_近3期": None,
            "股息率": None,
            "股息率_近1期": None,
            "股息率_近2期": None,
            "股息率_近3期": None,
            "数据来源": "数据缺失",
            "市场数据来源": "数据缺失",
            "财务数据来源": "数据缺失",
            "更新时间": _now_text(),
            "错误信息": "本地缓存没有找到这只标的。",
        }

    has_finance = any(_to_float(row.get(column)) is not None for column in FINANCIAL_COLUMNS)
    source = row.get("数据来源") or "本地缓存"
    cashflow_latest = _to_float(row.get("经营现金流/净利润"))
    if cashflow_latest is None:
        cashflow_latest = _to_float(row.get("经营现金流/净利润_近1期"))
    dividend_latest = _to_float(row.get("股息率"))
    if dividend_latest is None:
        dividend_latest = _to_float(row.get("股息率_近1期"))
    cashflow_p1 = _to_float(row.get("经营现金流/净利润_近1期"))
    if cashflow_p1 is None:
        cashflow_p1 = cashflow_latest
    dividend_p1 = _to_float(row.get("股息率_近1期"))
    if dividend_p1 is None:
        dividend_p1 = dividend_latest
    standard = {
        "code": normalize_code(row.get("代码")),
        "name": row.get("名称") or normalize_code(code),
        "industry": row.get("所属行业") or "未知",
        "price": _to_float(row.get("最新价")),
        "pct_change": _to_float(row.get("涨跌幅")),
        "turnover": _to_float(row.get("成交额")),
        "pe": _to_float(row.get("市盈率-动态")),
        "pb": _to_float(row.get("市净率")),
        "turnover_rate": _to_float(row.get("换手率")),
        "market_cap": _to_float(row.get("总市值")),
        "float_market_cap": _to_float(row.get("流通市值")),
        "volume_ratio": _to_float(row.get("量比")),
        "amplitude": _to_float(row.get("振幅")),
        "in_out_ratio": _to_float(row.get("内外盘比例")),
        "roe": _to_float(row.get("ROE")),
        "net_margin": _to_float(row.get("净利率")),
        "gross_margin": _to_float(row.get("毛利率")),
        "revenue_growth": _to_float(row.get("营收增长率")),
        "profit_growth": _to_float(row.get("净利润增长率")),
        "debt_ratio": _to_float(row.get("资产负债率")),
        "cashflow_profit_ratio": cashflow_latest,
        "cashflow_profit_ratio_p1": cashflow_p1,
        "cashflow_profit_ratio_p2": _to_float(row.get("经营现金流/净利润_近2期")),
        "cashflow_profit_ratio_p3": _to_float(row.get("经营现金流/净利润_近3期")),
        "dividend_yield": dividend_latest,
        "dividend_yield_p1": dividend_p1,
        "dividend_yield_p2": _to_float(row.get("股息率_近2期")),
        "dividend_yield_p3": _to_float(row.get("股息率_近3期")),
        "data_source": source,
        "updated_at": row.get("更新时间") or _now_text(),
    }
    return {
        **standard,
        "股票代码": standard["code"],
        "股票名称": standard["name"],
        "所属行业": standard["industry"],
        "最新收盘价": standard["price"],
        "涨跌幅": standard["pct_change"],
        "换手率": standard["turnover_rate"],
        "量比": standard["volume_ratio"],
        "振幅": standard["amplitude"],
        "成交额": standard["turnover"],
        "内外盘比例": standard["in_out_ratio"],
        "市盈率-动态": standard["pe"],
        "市净率": standard["pb"],
        "总市值": standard["market_cap"],
        "流通市值": standard["float_market_cap"],
        "ROE": standard["roe"],
        "净利率": standard["net_margin"],
        "毛利率": standard["gross_margin"],
        "营收增长率": standard["revenue_growth"],
        "净利润增长率": standard["profit_growth"],
        "资产负债率": standard["debt_ratio"],
        "经营现金流/净利润": standard["cashflow_profit_ratio"],
        "经营现金流/净利润_近1期": standard["cashflow_profit_ratio_p1"],
        "经营现金流/净利润_近2期": standard["cashflow_profit_ratio_p2"],
        "经营现金流/净利润_近3期": standard["cashflow_profit_ratio_p3"],
        "股息率": standard["dividend_yield"],
        "股息率_近1期": standard["dividend_yield_p1"],
        "股息率_近2期": standard["dividend_yield_p2"],
        "股息率_近3期": standard["dividend_yield_p3"],
        "数据来源": standard["data_source"],
        "市场数据来源": source,
        "财务数据来源": source if has_finance else "数据缺失",
        "更新时间": standard["updated_at"],
        "错误信息": "",
    }


def _fetch_pe_pb_for_code(code: str) -> dict[str, Any]:
    """从乐咕乐股（legulegu.com）获取单只股票的 PE/PB。
    服务器与东财完全不同，东财 SSL 失败时仍可使用。
    """
    _apply_ssl_fix()
    result: dict[str, Any] = {}
    try:
        import akshare as ak  # type: ignore

        def _call() -> Any:
            df = ak.stock_a_indicator_lg(symbol=code)
            if df is None or df.empty:
                raise ValueError("返回空数据")
            return df

        df = _retry(_call, retries=2, wait=2.0)
        latest = df.iloc[-1]
        for col in df.columns:
            col_s = str(col)
            val = _to_float(latest[col])
            if val is None or val <= 0:
                continue
            if "市盈率" in col_s:
                result["市盈率-动态"] = val
            elif "市净率" in col_s:
                result["市净率"] = val
    except Exception:  # noqa: BLE001
        pass
    return result


def _decode_sina_json(text: str) -> Any:
    try:
        from akshare.utils import demjson  # type: ignore

        return demjson.decode(text)
    except Exception:  # noqa: BLE001
        pass

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        quoted = re.sub(r"([{,]\s*)([A-Za-z_]\w*)(\s*:)", r'\1"\2"\3', text)
        return json.loads(quoted)


def _fetch_sina_spot_full() -> pd.DataFrame | None:
    """Fetch A-share spot data from Sina HTTP JSON without losing PE/PB fields."""

    count_url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeStockCount"
    data_url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    page_size = 80

    try:
        import requests

        def _fetch_count() -> int:
            response = requests.get(count_url, params={"node": "hs_a"}, timeout=15)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or "utf-8"
            match = re.search(r"\d+", response.text)
            if not match:
                raise ValueError("新浪 count 接口没有返回数字")
            return int(match.group())

        total_count = _retry(_fetch_count, retries=3, wait=2.0)
        total_pages = max(1, (int(total_count) + page_size - 1) // page_size)

        all_rows: list[dict[str, Any]] = []
        failed_pages: list[int] = []
        for page in range(1, total_pages + 1):
            def _fetch_page(page_no: int = page) -> list[dict[str, Any]]:
                payload = {
                    "page": str(page_no),
                    "num": str(page_size),
                    "sort": "symbol",
                    "asc": "1",
                    "node": "hs_a",
                    "symbol": "",
                    "_s_r_a": "page",
                }
                response = requests.get(data_url, params=payload, timeout=20)
                response.raise_for_status()
                response.encoding = response.apparent_encoding or "utf-8"
                data = _decode_sina_json(response.text.strip())
                if not isinstance(data, list):
                    raise ValueError("新浪分页接口返回格式不是列表")
                return data

            try:
                rows = _retry(_fetch_page, retries=6, wait=3.0)
            except Exception:  # noqa: BLE001
                failed_pages.append(page)
                continue
            if not rows:
                continue
            all_rows.extend(rows)
            time.sleep(0.35)

        if not all_rows:
            return None

        def _market_cap_to_yuan(value: Any) -> float | None:
            number = _to_float(value)
            return number * 10000 if number is not None else None

        output_rows: list[dict[str, Any]] = []
        for item in all_rows:
            output_rows.append(
                {
                    "代码": normalize_code(item.get("symbol") or item.get("code")),
                    "名称": item.get("name"),
                    "最新价": _to_float(item.get("trade")),
                    "涨跌幅": _to_float(item.get("changepercent")),
                    "成交额": _to_float(item.get("amount")),
                    "市盈率-动态": _to_float(item.get("per")),
                    "市净率": _to_float(item.get("pb")),
                    "总市值": _market_cap_to_yuan(item.get("mktcap")),
                    "流通市值": _market_cap_to_yuan(item.get("nmc")),
                    "换手率": _to_float(item.get("turnoverratio")),
                }
            )

        output = pd.DataFrame(output_rows)
        output = output[output["代码"] != ""].drop_duplicates(subset=["代码"], keep="last")
        return output if not output.empty else None
    except Exception:  # noqa: BLE001
        return None


def _fetch_akshare_spot() -> pd.DataFrame | None:
    _apply_ssl_fix()
    try:
        import akshare as ak  # type: ignore

        def _call() -> pd.DataFrame:
            df = ak.stock_zh_a_spot_em()
            if df is None or df.empty or "代码" not in df.columns:
                raise ValueError("接口返回空数据")
            return df

        spot = _retry(_call, retries=3, wait=3.0)
        spot["代码"] = spot["代码"].astype(str).map(normalize_code)
        return spot
    except Exception:  # noqa: BLE001
        return _fetch_sina_spot_full()


@functools.lru_cache(maxsize=128)
def _get_metrics_cached(codes_tuple: tuple[str, ...]) -> tuple[list[dict[str, Any]], list[str]]:
    """Per-process cache of stock metrics CSV reads.

    Keyed by the exact codes tuple; cache survives across Streamlit reruns within
    the same process. Call get_stock_metrics.cache_clear() after a manual CSV
    refresh to invalidate.
    """
    cache_df = _read_cache()
    rows: list[dict[str, Any]] = []
    for code in codes_tuple:
        normalized = normalize_code(code)
        if not normalized:
            continue
        rows.append(_cache_to_analyzer_row(_cache_row(cache_df, normalized), normalized))
    return rows, []


def get_stock_metrics(codes: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Read requested stock data from local cache only.

    Streamlit Cloud should be stable and fast by default, so the main page does
    not automatically fetch AkShare data. Use manual refresh buttons or
    update_cache.py to update stock_metrics.csv.

    Results are memoized per codes tuple for the process lifetime.
    Call ``_get_metrics_cached.cache_clear()`` after a manual CSV refresh.
    """
    return _get_metrics_cached(tuple(codes))


def refresh_current_holdings_cache(codes: list[str]) -> tuple[dict[str, Any], list[str]]:
    clean_codes = []
    for code in codes:
        normalized = normalize_code(code)
        if normalized and normalized not in clean_codes:
            clean_codes.append(normalized)

    if not clean_codes:
        return get_cache_summary(), ["没有可更新的股票代码。"]

    cache_df = _read_cache()
    spot_df = _fetch_akshare_spot()  # 可能失败（东财SSL），返回 None 时降级

    updates: list[dict[str, Any]] = []
    missing: list[str] = []
    pe_pb_enriched: int = 0

    for code in clean_codes:
        cached = _cache_row(cache_df, code)

        if spot_df is not None:
            matched = spot_df[spot_df["代码"] == code]
            if not matched.empty:
                row = _spot_to_cache_row(matched.iloc[0], cached)
            else:
                missing.append(code)
                row = {col: (cached.get(col) if cached else None) for col in CACHE_COLUMNS}
                row["代码"] = code
        else:
            # 行情接口全部失败时，以旧缓存为基础
            row = {col: (cached.get(col) if cached else None) for col in CACHE_COLUMNS}
            row["代码"] = code

        # 若 PE/PB 仍缺失，从乐咕乐股补充（不同服务器，不受东财 SSL 影响）
        need_pe = _to_float(row.get("市盈率-动态")) is None
        need_pb = _to_float(row.get("市净率")) is None
        if need_pe or need_pb:
            extra = _fetch_pe_pb_for_code(code)
            if extra:
                row.update({k: v for k, v in extra.items() if v is not None})
                pe_pb_enriched += 1

        updates.append(row)

    if updates:
        _write_cache(pd.concat([cache_df, pd.DataFrame(updates)], ignore_index=True))

    messages = [f"已更新 {len(updates)} 只当前持仓的行情缓存。"]
    if pe_pb_enriched:
        messages.append(f"通过备用源（乐咕乐股）补充了 {pe_pb_enriched} 只股票的 PE/PB 数据。")
    if spot_df is None:
        messages.append("东财行情暂时不可用，已保留本地价格缓存。")
    if missing:
        messages.append("部分代码在行情接口中未找到，已保留本地缓存数据。")
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
