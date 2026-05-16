"""data_fetcher.py
页面数据层——只读 stock_metrics.csv，绝不在页面启动时调用 AkShare。

AkShare 调用只在两处触发：
  1. 本地运行 update_cache.py
  2. 用户在高级选项里点击"手动更新当前持仓数据"按钮

缓存找不到某只股票时，返回带 "数据缺失" 标记的占位行，
允许用户在 app.py 里手动补充资产类型、行业和备注。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

# ── 常量 ────────────────────────────────────────────────────────────
CACHE_FILE = Path(__file__).with_name("stock_metrics.csv")

# 完整列定义（与 update_cache.py OUTPUT_COLUMNS 保持一致，再加财务列）
CACHE_COLUMNS = [
    "代码", "名称", "最新价", "涨跌幅", "成交额", "换手率",
    "市盈率-动态", "市净率", "总市值", "流通市值",
    "量比", "振幅", "所属行业",
    # 财务列（由 update_cache.py 的扩展版本或手动补充）
    "ROE", "净利率", "毛利率", "营收增长率", "净利润增长率",
    "资产负债率", "经营现金流/净利润",
    "数据来源", "更新时间",
]

FINANCIAL_COLUMNS = [
    "ROE", "净利率", "毛利率", "营收增长率", "净利润增长率",
    "资产负债率", "经营现金流/净利润",
]

# 列名别名（兼容旧版 CSV 或 AkShare 字段名变化）
ALIASES: dict[str, list[str]] = {
    "代码":       ["代码", "股票代码"],
    "名称":       ["名称", "股票名称", "公司名称"],
    "最新价":     ["最新价", "最新收盘价", "收盘"],
    "市盈率-动态": ["市盈率-动态", "市盈率动态", "动态市盈率", "市盈率(动态)"],
    "市净率":     ["市净率"],
    "总市值":     ["总市值"],
    "流通市值":   ["流通市值"],
}


# ── 工具函数 ────────────────────────────────────────────────────────
def normalize_code(code: str) -> str:
    text = str(code or "").strip().upper()
    if text.startswith(("SH", "SZ", "BJ")):
        text = text[2:]
    return text.zfill(6) if text else ""


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _to_float(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
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


def _first_present(row: pd.Series | dict, names: list[str]) -> Any:
    for name in names:
        if name in row:
            val = row[name]
            if val is not None and not (isinstance(val, float) and pd.isna(val)):
                return val
    return None


# ── 缓存读写 ────────────────────────────────────────────────────────
def _read_cache() -> pd.DataFrame:
    """读取 stock_metrics.csv，做列名标准化。缺列时补 None，不报错。"""
    if not CACHE_FILE.exists():
        return pd.DataFrame(columns=CACHE_COLUMNS)
    try:
        df = pd.read_csv(CACHE_FILE, dtype={"代码": str, "股票代码": str})
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=CACHE_COLUMNS)

    normalized = pd.DataFrame()
    for col in CACHE_COLUMNS:
        aliases = ALIASES.get(col, [col])
        src = next((a for a in aliases if a in df.columns), None)
        normalized[col] = df[src] if src else None

    normalized["代码"] = normalized["代码"].map(normalize_code)
    normalized = normalized[normalized["代码"] != ""].copy()
    return normalized


def _write_cache(df: pd.DataFrame) -> None:
    for col in CACHE_COLUMNS:
        if col not in df.columns:
            df[col] = None
    out = df[CACHE_COLUMNS].copy()
    out["代码"] = out["代码"].map(normalize_code)
    out = out[out["代码"] != ""]
    out = out.drop_duplicates(subset=["代码"], keep="last")
    out.to_csv(CACHE_FILE, index=False, encoding="utf-8-sig")


# ── 缓存查询 ────────────────────────────────────────────────────────
def _cache_row(df: pd.DataFrame, code: str) -> dict[str, Any] | None:
    matched = df[df["代码"] == normalize_code(code)]
    if matched.empty:
        return None
    return matched.iloc[0].to_dict()


def _cache_to_analyzer_row(
    row: dict[str, Any] | None,
    code: str,
    manual: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把缓存行转换为 analyzer 需要的字段格式。
    manual 是用户在页面手动填写的补充信息（资产类型、行业、备注）。
    """
    manual = manual or {}

    if row is None:
        # 缓存里没有这只标的——返回占位行，允许用户手动补充
        return {
            "股票代码":        normalize_code(code),
            "股票名称":        manual.get("name") or "数据缺失",
            "所属行业":        manual.get("industry") or "未知",
            "资产类型":        manual.get("asset_type") or "股票",
            "备注":            manual.get("note") or "",
            "最新收盘价":      None,
            "涨跌幅":          None,
            "换手率":          None,
            "量比":            None,
            "振幅":            None,
            "成交额":          None,
            "内外盘比例":      None,
            "市盈率-动态":     None,
            "市净率":          None,
            "总市值":          None,
            "流通市值":        None,
            "ROE":             None,
            "净利率":          None,
            "毛利率":          None,
            "营收增长率":      None,
            "净利润增长率":    None,
            "资产负债率":      None,
            "经营现金流/净利润": None,
            "数据来源":        "数据缺失",
            "市场数据来源":    "数据缺失",
            "财务数据来源":    "数据缺失",
            "更新时间":        _now_text(),
            "错误信息":        "本地缓存未找到该标的，已允许手动补充信息。",
        }

    has_finance = any(_to_float(row.get(c)) is not None for c in FINANCIAL_COLUMNS)
    src = row.get("数据来源") or "本地缓存"

    return {
        "股票代码":        normalize_code(row.get("代码", code)),
        "股票名称":        manual.get("name") or row.get("名称") or normalize_code(code),
        "所属行业":        manual.get("industry") or row.get("所属行业") or "未知",
        "资产类型":        manual.get("asset_type") or "股票",
        "备注":            manual.get("note") or "",
        "最新收盘价":      _to_float(row.get("最新价")),
        "涨跌幅":          _to_float(row.get("涨跌幅")),
        "换手率":          _to_float(row.get("换手率")),
        "量比":            _to_float(row.get("量比")),
        "振幅":            _to_float(row.get("振幅")),
        "成交额":          _to_float(row.get("成交额")),
        "内外盘比例":      _to_float(row.get("内外盘比例")),
        "市盈率-动态":     _to_float(row.get("市盈率-动态")),
        "市净率":          _to_float(row.get("市净率")),
        "总市值":          _to_float(row.get("总市值")),
        "流通市值":        _to_float(row.get("流通市值")),
        "ROE":             _to_float(row.get("ROE")),
        "净利率":          _to_float(row.get("净利率")),
        "毛利率":          _to_float(row.get("毛利率")),
        "营收增长率":      _to_float(row.get("营收增长率")),
        "净利润增长率":    _to_float(row.get("净利润增长率")),
        "资产负债率":      _to_float(row.get("资产负债率")),
        "经营现金流/净利润": _to_float(row.get("经营现金流/净利润")),
        "数据来源":        src,
        "市场数据来源":    src,
        "财务数据来源":    src if has_finance else "数据缺失",
        "更新时间":        row.get("更新时间") or _now_text(),
        "错误信息":        "",
    }


# ── 公开接口 ────────────────────────────────────────────────────────
def get_cache_summary() -> dict[str, Any]:
    """返回缓存概况，供页面顶部展示。"""
    if not CACHE_FILE.exists():
        return {"exists": False, "count": 0, "message": "暂无缓存数据，请在本地运行 python update_cache.py"}

    try:
        df = _read_cache()
    except Exception:  # noqa: BLE001
        return {"exists": False, "count": 0, "message": "缓存读取失败，不影响风险体检"}

    if df.empty:
        return {"exists": True, "count": 0, "message": "缓存为空，请在本地运行 python update_cache.py"}

    finance_count = int(df[FINANCIAL_COLUMNS].notna().any(axis=1).sum())
    latest = df["更新时间"].dropna().astype(str).max() if "更新时间" in df.columns else "未知"
    count = len(df)

    return {
        "exists": True,
        "count": count,
        "finance_count": finance_count,
        "latest_update": latest or "未知",
        "message": f"缓存现有 {count} 只标的",
    }


def get_stock_metrics(
    codes: list[str],
    manual_overrides: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """从本地缓存读取股票数据。
    
    manual_overrides: {code: {"name": ..., "industry": ..., "asset_type": ..., "note": ...}}
    缓存找不到时返回占位行（数据缺失），不报错，不崩页面。
    """
    manual_overrides = manual_overrides or {}
    cache_df = _read_cache()
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []

    for code in codes:
        nc = normalize_code(code)
        if not nc:
            continue
        cached = _cache_row(cache_df, nc)
        manual = manual_overrides.get(nc) or manual_overrides.get(code) or {}
        row = _cache_to_analyzer_row(cached, nc, manual)
        if cached is None:
            warnings.append(
                f"⚠️ {nc} 在本地缓存中未找到。"
                "如需数据，请在本地运行 python update_cache.py 更新缓存后重新上传 stock_metrics.csv。"
            )
        rows.append(row)

    return rows, warnings


def refresh_current_holdings_cache(codes: list[str]) -> tuple[dict[str, Any], list[str]]:
    """用 AkShare 实时更新指定代码的行情（仅在用户点击按钮时调用）。"""
    clean_codes = list({normalize_code(c) for c in codes if normalize_code(c)})
    if not clean_codes:
        return get_cache_summary(), ["没有可更新的股票代码。"]

    try:
        import akshare as ak  # type: ignore
        spot = ak.stock_zh_a_spot_em()
        if spot is None or spot.empty or "代码" not in spot.columns:
            return get_cache_summary(), ["实时行情更新失败，已使用本地缓存数据。"]
        spot["代码"] = spot["代码"].astype(str).map(normalize_code)
    except Exception:  # noqa: BLE001
        return get_cache_summary(), ["实时行情更新失败，已使用本地缓存数据。"]

    cache_df = _read_cache()
    updates: list[dict[str, Any]] = []
    missing: list[str] = []
    now = _now_text()

    for code in clean_codes:
        matched = spot[spot["代码"] == code]
        if matched.empty:
            missing.append(code)
            continue
        r = matched.iloc[0]
        new_row: dict[str, Any] = {c: None for c in CACHE_COLUMNS}
        # 保留旧财务数据
        old = _cache_row(cache_df, code)
        if old:
            new_row.update(old)
        new_row["代码"]       = code
        new_row["名称"]       = str(r.get("名称", code))
        new_row["最新价"]     = _to_float(r.get("最新价"))
        new_row["涨跌幅"]     = _to_float(r.get("涨跌幅"))
        new_row["成交额"]     = _to_float(r.get("成交额"))
        new_row["换手率"]     = _to_float(r.get("换手率"))
        new_row["市盈率-动态"]= _to_float(_first_present(r, ["市盈率-动态", "市盈率动态", "动态市盈率"]))
        new_row["市净率"]     = _to_float(r.get("市净率"))
        new_row["总市值"]     = _to_float(r.get("总市值"))
        new_row["流通市值"]   = _to_float(r.get("流通市值"))
        new_row["量比"]       = _to_float(r.get("量比"))
        new_row["振幅"]       = _to_float(r.get("振幅"))
        new_row["数据来源"]   = "真实数据"
        new_row["更新时间"]   = now
        updates.append(new_row)

    if updates:
        _write_cache(pd.concat([cache_df, pd.DataFrame(updates)], ignore_index=True))

    messages = [f"已更新 {len(updates)} 只持仓的行情缓存。"]
    if missing:
        messages.append(f"以下代码在实时行情中未找到，已保留本地缓存：{', '.join(missing)}")
    return get_cache_summary(), messages
