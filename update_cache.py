from __future__ import annotations

import argparse
import concurrent.futures
import json
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


CACHE_FILE      = Path(__file__).with_name("stock_metrics.csv")
CHECKPOINT_FILE = CACHE_FILE.with_suffix(".csv.ckpt")
FAILED_FILE     = Path(__file__).with_name("failed_codes.csv")

pd: Any = None

# 单只股票财务请求的最长等待秒数
FINANCE_TIMEOUT = 12

# 随机暂停区间（秒）
SLEEP_MIN, SLEEP_MAX = 0.5, 2.0

# 连续失败超过此数后暂停
CONSEC_FAIL_LIMIT  = 20
CONSEC_FAIL_PAUSE  = 60   # 暂停秒数

CACHE_COLUMNS = [
    "代码", "名称", "最新价", "涨跌幅", "成交额",
    "市盈率-动态", "市净率", "换手率", "总市值", "流通市值",
    "所属行业", "量比", "振幅", "内外盘比例",
    "ROE", "净利率", "毛利率", "营收增长率", "净利润增长率",
    "资产负债率", "经营现金流/净利润",
    "数据来源", "更新时间",
]

FINANCIAL_COLUMNS = [
    "ROE", "净利率", "毛利率", "营收增长率", "净利润增长率",
    "资产负债率", "经营现金流/净利润",
]

COLUMN_ALIASES = {
    "代码":      ["代码", "股票代码", "证券代码", "symbol"],
    "名称":      ["名称", "股票名称", "证券简称", "简称", "name"],
    "最新价":    ["最新价", "最新价格", "最新收盘价", "收盘", "现价", "当前价格", "trade", "price"],
    "涨跌幅":    ["涨跌幅", "涨跌幅%", "涨幅", "changepercent", "pct_chg"],
    "成交额":    ["成交额", "成交金额", "amount"],
    # PE：覆盖全角连字符／括号／不带后缀等各种变体
    "市盈率-动态": [
        "市盈率-动态", "市盈率－动态", "市盈率动态",
        "市盈率（动态）", "市盈率(动态)",
        "动态市盈率", "市盈率TTM", "市盈率ttm",
        "市盈率", "per", "pe", "pe_ttm",
    ],
    # PB：覆盖常见变体
    "市净率": [
        "市净率", "市净率PB", "pb",
        "净资产倍率",
    ],
    "换手率":    ["换手率", "换手率%", "turnover", "turnoverrate"],
    "总市值":    ["总市值", "总市值(元)", "总市值(亿元)", "market_cap", "marketcap"],
    "流通市值":  ["流通市值", "流通市值(元)", "circulating_market_cap", "float_market_cap"],
    "量比":      ["量比", "volume_ratio", "volumeratio"],
    "振幅":      ["振幅", "振幅%", "amplitude"],
}

# stock_financial_abstract 宽表中各指标对应的精确行名
# （已通过 600519 实测确认，行名 = '指标' 列的值）
# 格式：目标字段 -> 按优先级排列的行名列表
FINANCIAL_ROW_NAMES: dict[str, list[str]] = {
    "ROE": [
        "净资产收益率(ROE)",          # 行11，优先用（含ROE标注最准确）
        "净资产收益率_平均",
        "摊薄净资产收益率",
    ],
    "净利率": [
        "销售净利率",                  # 行14
    ],
    "毛利率": [
        "毛利率",                      # 行13
    ],
    "营收增长率": [
        "营业总收入增长率",            # 行54
        "营业收入增长率",
    ],
    "净利润增长率": [
        "归属母公司净利润增长率",      # 行55
        "归母净利润增长率",
        "净利润增长率",
    ],
    "资产负债率": [
        "资产负债率",                  # 行16（或66），取先出现的
    ],
    "经营现金流/净利润": [
        "经营活动净现金/归属母公司的净利润",  # 行61，值为比率（~0.98），不需要 /100
        "经营活动净现金/销售收入",            # 备用（如果上面没找到）
    ],
}

# stock_financial_abstract 返回的值：
#   ROE、净利率、毛利率、资产负债率、营收增长率、净利润增长率 → 百分比形式（10.57 = 10.57%），需 /100
#   经营现金流/净利润 → 比率形式（0.988），直接使用，不 /100
PERCENT_FIELDS = {"ROE", "净利率", "毛利率", "资产负债率", "营收增长率", "净利润增长率"}


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def normalize_code(code: Any) -> str:
    text = str(code or "").strip().upper()
    if text.startswith(("SH", "SZ", "BJ")):
        text = text[2:]
    return text.zfill(6) if text else ""


def market_paper_code(code: Any) -> tuple[str | None, str]:
    """Return the Eastmoney-style paperCode for A-share financial requests.

    Do not default unknown codes to Shanghai; a wrong market prefix silently
    produces missing finance data for Shenzhen stocks.
    """
    normalized = normalize_code(code)
    if not normalized:
        return None, "空股票代码，已跳过"
    if normalized.startswith(("000", "001", "002", "003", "300", "301")):
        return f"sz{normalized}", ""
    if normalized.startswith(("600", "601", "603", "605", "688", "689")):
        return f"sh{normalized}", ""
    if normalized.startswith(("8", "4")):
        return None, "北交所 8/4 开头股票，当前财务接口暂不支持，已跳过"
    return None, "无法判断市场前缀，已跳过"


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    if text in {"", "-", "--", "None", "nan"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def first_present(row: Any, names: list[str]) -> Any:
    for name in names:
        try:
            val = row[name]
            if val is not None and not pd.isna(val):
                return val
        except (KeyError, TypeError):
            pass
    return None


def _norm_col(s: str) -> str:
    """归一化列名：剥离空格、下划线、各种连字符和括号，全部转小写。
    让 "市盈率-动态" / "市盈率－动态" / "市盈率（动态）" 都映射到同一个 key。
    """
    return (
        str(s)
        .strip()
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")        # ASCII 连字符
        .replace("—", "")   # EM DASH —
        .replace("–", "")   # EN DASH –
        .replace("－", "")   # 全角连字符 －
        .replace("（", "")
        .replace("）", "")
        .replace("(", "")
        .replace(")", "")
        .lower()
    )


def first_present_by_alias(row: Any, names: list[str]) -> Any:
    """Return the first non-empty value, matching column names leniently.
    Uses aggressive normalization to handle AkShare version differences.
    """
    try:
        row_keys = list(row.index)
    except Exception:
        row_keys = []

    normalized_lookup = {_norm_col(key): key for key in row_keys}
    for name in names:
        actual_name = normalized_lookup.get(_norm_col(name))
        if actual_name is None:
            continue
        try:
            val = row[actual_name]
            if val is not None and not pd.isna(val):
                return val
        except (KeyError, TypeError):
            pass
    return first_present(row, names)


def prefer_new_value(new_value: Any, old_value: Any) -> Any:
    parsed = to_float(new_value)
    if parsed is not None:
        return parsed
    return old_value


def is_valid_frame(df: Any) -> bool:
    return df is not None and hasattr(df, "empty") and not df.empty


# ── 缓存读写 ──────────────────────────────────────────────────────────────────

def read_existing_cache() -> Any:
    if not CACHE_FILE.exists():
        return pd.DataFrame(columns=CACHE_COLUMNS)
    try:
        df = pd.read_csv(CACHE_FILE, dtype={"代码": str, "股票代码": str})
    except Exception as exc:  # noqa: BLE001
        print(f"读取旧缓存失败，将重新生成。原因：{exc}", flush=True)
        return pd.DataFrame(columns=CACHE_COLUMNS)
    if "代码" not in df.columns and "股票代码" in df.columns:
        df["代码"] = df["股票代码"]
    for col in CACHE_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df["代码"] = df["代码"].map(normalize_code)
    return df[df["代码"] != ""].drop_duplicates(subset=["代码"], keep="last")


def save_cache(df: Any, path: Path | None = None) -> None:
    target = path or CACHE_FILE
    for col in CACHE_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[CACHE_COLUMNS].copy()
    df["代码"] = df["代码"].map(normalize_code)
    df = df[df["代码"] != ""].drop_duplicates(subset=["代码"], keep="last")
    tmp = target.with_suffix(".csv.tmp")
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    tmp.replace(target)


# ── 行情抓取 ──────────────────────────────────────────────────────────────────

_NETWORK_KEYWORDS = (
    "SSL", "ssl", "Connection", "Timeout", "timeout",
    "RemoteDisconnected", "reset", "aborted", "EOF",
    "Max retries", "ProxyError", "ConnectError",
)


def _is_network_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}"
    return any(k in text for k in _NETWORK_KEYWORDS)


def fetch_market(
    label: str,
    fetcher: Callable[[], Any],
    retries: int = 3,
) -> Any | None:
    """带重试的接口调用：网络错误自动重试，每次等待时间递增。"""
    for attempt in range(1, retries + 1):
        try:
            df = fetcher()
        except Exception as exc:  # noqa: BLE001
            if attempt < retries and _is_network_error(exc):
                wait = attempt * 4
                print(
                    f"{label} 网络错误（第{attempt}/{retries}次），{wait}s 后重试…",
                    flush=True,
                )
                time.sleep(wait)
                continue
            print(f"{label} 获取失败：{exc}", flush=True)
            return None
        if not is_valid_frame(df):
            print(f"{label} 返回空数据。", flush=True)
            return None
        print(f"{label} 获取成功，共 {len(df)} 条", flush=True)
        return df
    return None


def fetch_spot_data(ak: Any, fast_spot: bool = False) -> Any | None:
    if fast_spot:
        print("快速行情模式：跳过容易失败的东财全市场接口，直接使用新浪 HTTP 备用接口...", flush=True)
        df = fetch_sina_valuation_pages()
        if is_valid_frame(df):
            print(f"快速行情模式成功：获取 {len(df)} 条行情数据。", flush=True)
            return df

        print("新浪 HTTP 备用接口失败，改用 AkShare 备用接口 stock_zh_a_spot ...", flush=True)
        df = fetch_market("备用接口 stock_zh_a_spot", ak.stock_zh_a_spot, retries=1)
        if is_valid_frame(df):
            return df

        print("快速行情模式失败：备用行情接口均未返回有效数据。", flush=True)
        return None

    print("正在尝试获取沪深京 A 股全市场数据...", flush=True)
    df = fetch_market("全市场接口 stock_zh_a_spot_em", ak.stock_zh_a_spot_em)
    if is_valid_frame(df):
        return df

    print("全市场接口失败，分市场获取...", flush=True)
    frames = []
    for name, fn in [("沪A", ak.stock_sh_a_spot_em),
                     ("深A", ak.stock_sz_a_spot_em),
                     ("京A", ak.stock_bj_a_spot_em)]:
        sub = fetch_market(name, fn)
        if is_valid_frame(sub):
            frames.append(sub)
    if frames:
        combined = pd.concat(frames, ignore_index=True, sort=False)
        print(f"分市场合并完成，共 {len(combined)} 条。", flush=True)
        return combined

    print("东财接口全部失败，尝试备用接口 stock_zh_a_spot ...", flush=True)
    df = fetch_market("备用接口 stock_zh_a_spot", ak.stock_zh_a_spot)
    if is_valid_frame(df):
        return df

    print("更新失败：所有行情接口均无有效数据。", flush=True)
    return None


def normalize_spot_frame(spot_df: Any) -> Any:
    df = spot_df.copy()
    code_col = next(
        (c for c in COLUMN_ALIASES["代码"] if c in df.columns), None
    )
    if code_col is None:
        print(f"找不到代码字段，实际列：{list(df.columns)}", flush=True)
        return pd.DataFrame(columns=CACHE_COLUMNS)
    df["代码"] = df[code_col].map(normalize_code)
    return df[df["代码"] != ""].drop_duplicates(subset=["代码"], keep="last")


def print_spot_valuation_summary(spot_df: Any) -> None:
    print(f"AkShare 本次返回字段：{list(spot_df.columns)}", flush=True)
    alias_norm_map: dict[str, str] = {
        _norm_col(alias): alias
        for target in ["市盈率-动态", "市净率", "总市值", "换手率"]
        for alias in COLUMN_ALIASES[target]
    }
    for target in ["市盈率-动态", "市净率", "总市值", "换手率"]:
        matched_col = next(
            (col for col in spot_df.columns if _norm_col(col) in {_norm_col(a) for a in COLUMN_ALIASES[target]}),
            None,
        )
        if matched_col is None:
            print(f"  ⚠ {target}：未找到对应列（别名表：{COLUMN_ALIASES[target][:3]}…）", flush=True)
        else:
            count = int(spot_df[matched_col].map(to_float).notna().sum())
            print(f"  ✓ {target} → 实际列名 [{matched_col}]，非空 {count} 行", flush=True)


def fetch_eastmoney_valuation_pages() -> Any | None:
    """补抓 PE/PB/市值/换手率。

    AkShare 备用接口 stock_zh_a_spot 不包含估值字段；这里直接请求东财分页行情接口，
    只用于补全缓存里的估值和交易字段，不改变财务抓取逻辑。
    """
    print("正在尝试补抓 PE/PB/市值/换手率字段...", flush=True)
    try:
        import requests
    except Exception as exc:  # noqa: BLE001
        print(f"  补抓失败：无法导入 requests。原因：{exc}", flush=True)
        return None

    url = "https://push2.eastmoney.com/api/qt/clist/get"
    fields = "f12,f14,f2,f3,f6,f9,f23,f8,f20,f21,f10,f7"
    fs = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
    rows: list[dict[str, Any]] = []
    page_size = 200

    for page in range(1, 80):
        params = {
            "pn": page,
            "pz": page_size,
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": fs,
            "fields": fields,
        }
        try:
            resp = requests.get(url, params=params, timeout=15, verify=False)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            print(f"  补抓第 {page} 页失败：{exc}", flush=True)
            break

        diff = ((payload.get("data") or {}).get("diff") or [])
        if not diff:
            break
        rows.extend(diff)
        if len(diff) < page_size:
            break

    if not rows:
        print("  补抓 PE/PB 失败：接口没有返回有效数据。", flush=True)
        return None

    df = pd.DataFrame(rows)
    output = pd.DataFrame(
        {
            "代码": df.get("f12").map(normalize_code),
            "名称": df.get("f14"),
            "最新价": df.get("f2").map(to_float),
            "涨跌幅": df.get("f3").map(to_float),
            "成交额": df.get("f6").map(to_float),
            "市盈率-动态": df.get("f9").map(to_float),
            "市净率": df.get("f23").map(to_float),
            "换手率": df.get("f8").map(to_float),
            "总市值": df.get("f20").map(to_float),
            "流通市值": df.get("f21").map(to_float),
            "量比": df.get("f10").map(to_float),
            "振幅": df.get("f7").map(to_float),
        }
    )
    output = output[output["代码"] != ""].drop_duplicates(subset=["代码"], keep="last")
    pe_count = int(output["市盈率-动态"].notna().sum())
    pb_count = int(output["市净率"].notna().sum())
    print(f"  补抓完成：{len(output)} 只，PE 非空 {pe_count}，PB 非空 {pb_count}。", flush=True)
    return output


def decode_sina_json(text: str) -> Any:
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


def fetch_sina_valuation_pages() -> Any | None:
    """从新浪 HTTP 原始接口补抓 PE/PB/市值/换手率。

    AkShare 的 stock_zh_a_spot 会丢弃 per/pb/mktcap/nmc/turnoverratio，
    这里直接读原始 JSON，保留这些字段。
    """
    print("正在使用新浪 HTTP 原始接口获取行情和 PE/PB...", flush=True)
    try:
        import requests
    except Exception as exc:  # noqa: BLE001
        print(f"  新浪补抓失败：无法导入 requests。原因：{exc}", flush=True)
        return None

    count_url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeStockCount"
    data_url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    page_size = 80

    try:
        count_resp = requests.get(count_url, params={"node": "hs_a"}, timeout=15)
        count_resp.raise_for_status()
        match = re.search(r"\d+", count_resp.text)
        if not match:
            print(f"  新浪补抓失败：count 接口返回异常：{count_resp.text[:80]}", flush=True)
            return None
        total_count = int(match.group())
    except Exception as exc:  # noqa: BLE001
        print(f"  新浪补抓失败：无法获取股票总数。原因：{exc}", flush=True)
        return None

    total_pages = max(1, (total_count + page_size - 1) // page_size)
    rows: list[dict[str, Any]] = []
    failed_pages: list[int] = []

    for page in range(1, total_pages + 1):
        payload = {
            "page": str(page),
            "num": str(page_size),
            "sort": "symbol",
            "asc": "1",
            "node": "hs_a",
            "symbol": "",
            "_s_r_a": "page",
        }
        try:
            resp = requests.get(data_url, params=payload, timeout=20)
            resp.raise_for_status()
            data = decode_sina_json(resp.text.strip())
            if not isinstance(data, list):
                raise ValueError("返回格式不是列表")
            rows.extend(data)
        except Exception as exc:  # noqa: BLE001
            failed_pages.append(page)
            if len(failed_pages) <= 5:
                print(f"  新浪第 {page} 页失败：{exc}", flush=True)
            time.sleep(1.0)
            continue
        time.sleep(0.25)

    if not rows:
        print("  新浪补抓失败：接口没有返回有效数据。", flush=True)
        return None

    def ten_thousand_yuan_to_yuan(value: Any) -> float | None:
        number = to_float(value)
        return number * 10000 if number is not None else None

    output = pd.DataFrame(
        [
            {
                "代码": normalize_code(item.get("symbol") or item.get("code")),
                "名称": item.get("name"),
                "最新价": to_float(item.get("trade")),
                "涨跌幅": to_float(item.get("changepercent")),
                "成交额": to_float(item.get("amount")),
                "市盈率-动态": to_float(item.get("per")),
                "市净率": to_float(item.get("pb")),
                "换手率": to_float(item.get("turnoverratio")),
                "总市值": ten_thousand_yuan_to_yuan(item.get("mktcap")),
                "流通市值": ten_thousand_yuan_to_yuan(item.get("nmc")),
            }
            for item in rows
        ]
    )
    output = output[output["代码"] != ""].drop_duplicates(subset=["代码"], keep="last")
    pe_count = int(output["市盈率-动态"].notna().sum())
    pb_count = int(output["市净率"].notna().sum())
    failed_text = f"，失败页 {len(failed_pages)} 个" if failed_pages else ""
    print(f"  新浪补抓完成：{len(output)} 只，PE 非空 {pe_count}，PB 非空 {pb_count}{failed_text}。", flush=True)
    return output


def fetch_valuation_pages() -> Any | None:
    valuation_df = fetch_eastmoney_valuation_pages()
    if valuation_df is not None and not valuation_df.empty:
        pe_count = int(valuation_df["市盈率-动态"].notna().sum())
        pb_count = int(valuation_df["市净率"].notna().sum())
        if pe_count > 0 or pb_count > 0:
            return valuation_df
    return fetch_sina_valuation_pages()


def merge_valuation_fields(cache_df: Any, valuation_df: Any | None) -> Any:
    if valuation_df is None or valuation_df.empty:
        return cache_df

    value_columns = ["名称", "最新价", "涨跌幅", "成交额", "市盈率-动态", "市净率", "换手率", "总市值", "流通市值", "量比", "振幅"]
    valuation_idx = valuation_df.set_index("代码", drop=False).to_dict("index")
    updated = cache_df.copy()
    matched = 0

    for idx, row in updated.iterrows():
        code = normalize_code(row.get("代码"))
        values = valuation_idx.get(code)
        if not values:
            continue
        matched += 1
        for column in value_columns:
            new_value = values.get(column)
            if column == "名称":
                if new_value:
                    updated.at[idx, column] = new_value
                continue
            parsed = to_float(new_value)
            if parsed is not None:
                updated.at[idx, column] = parsed

    pe_count = int(updated["市盈率-动态"].map(to_float).notna().sum())
    pb_count = int(updated["市净率"].map(to_float).notna().sum())
    print(f"  估值字段已合并：匹配 {matched} 只，当前 PE 非空 {pe_count}，PB 非空 {pb_count}。", flush=True)
    return updated


def build_cache_rows(spot_df: Any, old_cache: Any) -> Any:
    old_idx = (
        old_cache.set_index("代码", drop=False).to_dict("index")
        if not old_cache.empty else {}
    )
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows: list[dict[str, Any]] = []

    for _, spot_row in spot_df.iterrows():
        code = normalize_code(first_present(spot_row, COLUMN_ALIASES["代码"]))
        if not code:
            continue
        old = old_idx.get(code, {})
        row: dict[str, Any] = {col: old.get(col) for col in CACHE_COLUMNS}
        row["代码"]       = code
        row["名称"]       = first_present(spot_row, COLUMN_ALIASES["名称"]) or old.get("名称") or code
        row["最新价"]     = prefer_new_value(first_present_by_alias(spot_row, COLUMN_ALIASES["最新价"]), old.get("最新价"))
        row["涨跌幅"]     = prefer_new_value(first_present_by_alias(spot_row, COLUMN_ALIASES["涨跌幅"]), old.get("涨跌幅"))
        row["成交额"]     = prefer_new_value(first_present_by_alias(spot_row, COLUMN_ALIASES["成交额"]), old.get("成交额"))
        row["市盈率-动态"] = prefer_new_value(first_present_by_alias(spot_row, COLUMN_ALIASES["市盈率-动态"]), old.get("市盈率-动态"))
        row["市净率"]     = prefer_new_value(first_present_by_alias(spot_row, COLUMN_ALIASES["市净率"]), old.get("市净率"))
        row["换手率"]     = prefer_new_value(first_present_by_alias(spot_row, COLUMN_ALIASES["换手率"]), old.get("换手率"))
        row["总市值"]     = prefer_new_value(first_present_by_alias(spot_row, COLUMN_ALIASES["总市值"]), old.get("总市值"))
        row["流通市值"]   = prefer_new_value(first_present_by_alias(spot_row, COLUMN_ALIASES["流通市值"]), old.get("流通市值"))
        row["量比"]       = prefer_new_value(first_present_by_alias(spot_row, COLUMN_ALIASES["量比"]), old.get("量比"))
        row["振幅"]       = prefer_new_value(first_present_by_alias(spot_row, COLUMN_ALIASES["振幅"]), old.get("振幅"))
        row["所属行业"]   = old.get("所属行业") or "未知"
        row["内外盘比例"] = old.get("内外盘比例")
        for col in FINANCIAL_COLUMNS:         # 保留旧财务数据
            row[col] = old.get(col)
        row["数据来源"]   = "真实数据"
        row["更新时间"]   = now_text
        rows.append(row)

    return pd.DataFrame(rows, columns=CACHE_COLUMNS)


# ── 财务数据抓取 ──────────────────────────────────────────────────────────────

def _extract_wide_table(df: Any) -> dict[str, float]:
    """解析 stock_financial_abstract 的宽表格式。
    表结构：行 = 指标名（'指标'列），列 = ['选项','指标', '20260331', '20251231', ...]
    取最新日期列的值，按 FINANCIAL_ROW_NAMES 映射到目标字段。
    """
    result: dict[str, float] = {}
    if not is_valid_frame(df) or "指标" not in df.columns:
        return result

    # 日期列：8位纯数字，按降序排列（最新在前）
    date_cols = sorted(
        [c for c in df.columns if isinstance(c, str) and c.isdigit() and len(c) == 8],
        reverse=True,
    )
    if not date_cols:
        return result

    # 建立 指标名 -> 行数据 的索引，方便快速查找
    indicator_index: dict[str, Any] = {}
    for _, row in df.iterrows():
        name = str(row.get("指标", "")).strip()
        if name and name not in indicator_index:
            indicator_index[name] = row

    # 按 FINANCIAL_ROW_NAMES 查找每个目标字段
    for target, row_names in FINANCIAL_ROW_NAMES.items():
        for row_name in row_names:
            if row_name not in indicator_index:
                continue
            row = indicator_index[row_name]
            # 从最新日期列找第一个有效值
            for col in date_cols:
                val = to_float(row.get(col))
                if val is not None:
                    # 百分比字段除以 100 转为小数
                    if target in PERCENT_FIELDS:
                        val = val / 100.0
                    result[target] = val
                    break
            if target in result:
                break   # 找到这个字段就停止尝试备用行名

    return result


def _fetch_one_financial(ak: Any, code: str, paper_code: str) -> tuple[dict[str, float], str]:
    """调用 stock_financial_abstract，返回 (财务数据字典, 错误信息)。
    错误信息为空字符串表示成功。
    在子线程中运行，由外部 timeout 控制最长等待时间。
    """
    try:
        df = ak.stock_financial_abstract(symbol=paper_code)
    except Exception as exc:  # noqa: BLE001
        return {}, f"{paper_code} {type(exc).__name__}: {exc}"

    if not is_valid_frame(df):
        return {}, "接口返回空表"

    if "指标" not in df.columns:
        return {}, f"返回表无'指标'列，实际列名: {list(df.columns[:5])}"

    result = _extract_wide_table(df)
    if not result:
        return {}, "宽表解析后未匹配到任何目标字段"

    return result, ""


def fetch_financial_with_timeout(
    ak: Any, code: str
) -> tuple[dict[str, float], str]:
    """在独立线程中执行财务抓取，超过 FINANCE_TIMEOUT 秒强制返回。
    返回 (数据字典, 错误信息)；超时时错误信息为 'TIMEOUT'。
    """
    paper_code, skip_reason = market_paper_code(code)
    if paper_code is None:
        return {}, skip_reason

    print(f"  请求财务数据 paperCode={paper_code}", flush=True)
    exe = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = exe.submit(_fetch_one_financial, ak, code, paper_code)
    try:
        return future.result(timeout=FINANCE_TIMEOUT)
    except concurrent.futures.TimeoutError:
        future.cancel()
        return {}, "TIMEOUT"
    except Exception as exc:  # noqa: BLE001
        return {}, f"线程异常: {type(exc).__name__}: {exc}"
    finally:
        exe.shutdown(wait=False, cancel_futures=True)


# ── 已成功股票集合（跳过用）────────────────────────────────────────────────────

def _load_already_done(df: Any) -> set[str]:
    """从 df 里找出财务字段已有数据的股票代码，下次运行时直接跳过。"""
    done: set[str] = set()
    for _, row in df.iterrows():
        if any(to_float(row.get(col)) is not None for col in FINANCIAL_COLUMNS):
            done.add(str(row["代码"]))
    return done


def _save_failed_codes(failed: list[tuple[str, str]]) -> None:
    """将 (代码, 失败原因) 写入 failed_codes.csv。"""
    if not failed:
        if FAILED_FILE.exists():
            FAILED_FILE.unlink()
        return
    with FAILED_FILE.open("w", encoding="utf-8-sig") as f:
        f.write("代码,失败原因\n")
        for code, reason in failed:
            safe_reason = reason.replace('"', "'").replace("\n", " ")
            f.write(f'{code},"{safe_reason}"\n')


def _load_failed_codes() -> list[str]:
    """读取 failed_codes.csv，返回待重试的股票代码列表。"""
    if not FAILED_FILE.exists():
        return []
    codes: list[str] = []
    with FAILED_FILE.open(encoding="utf-8-sig") as f:
        for i, line in enumerate(f):
            if i == 0:          # 跳过表头
                continue
            parts = line.strip().split(",", 1)
            if parts and parts[0]:
                codes.append(normalize_code(parts[0]))
    return [c for c in codes if c]


def _find_empty_finance_codes(df: Any) -> list[str]:
    """从 df 里找出财务字段全部为空/NaN/0 的股票代码。
    只要 7 个财务字段里没有任何一个有效非零值，就视为缺失，需要重新抓取。
    """
    codes: list[str] = []
    for _, row in df.iterrows():
        has_data = False
        for col in FINANCIAL_COLUMNS:
            val = to_float(row.get(col))
            if val is not None and val != 0.0:
                has_data = True
                break
        if not has_data:
            codes.append(str(row["代码"]))
    return codes


# ── 财务数据批量回填 ──────────────────────────────────────────────────────────

def enrich_with_financial(ak: Any, df: Any, limit: int = 0) -> Any:
    """逐只抓财务数据，回填 FINANCIAL_COLUMNS。

    行为：
    - 已有财务数据的股票自动跳过（断点续传）
    - 每只股票抓完后随机暂停 0.5~2 秒
    - 连续失败超过 20 次暂停 60 秒
    - 每 10 只打印一次进度
    - 每 100 只保存一次检查点
    - 全部完成后把失败代码写入 failed_codes.csv
    """
    all_codes: list[str] = df["代码"].tolist()
    if limit > 0:
        all_codes = all_codes[:limit]
        print(f"  --limit {limit}：仅对前 {limit} 只股票处理。", flush=True)

    # 跳过已成功的股票
    already_done = _load_already_done(df)
    codes = [c for c in all_codes if c not in already_done]
    skipped = len(all_codes) - len(codes)
    if skipped:
        print(f"  跳过已有财务数据的股票：{skipped} 只，待抓取：{len(codes)} 只。", flush=True)
    if not codes:
        print("  所有股票已有财务数据，无需重新抓取。", flush=True)
        return df

    total         = len(codes)
    success       = 0
    timeout_count = 0
    fail          = 0
    consec_fail   = 0          # 连续失败计数
    failed_list: list[tuple[str, str]] = []  # (代码, 原因)

    # 用列表缓存新财务值，最后批量写回
    new_fin: dict[str, list[Any]] = {col: [None] * len(df) for col in FINANCIAL_COLUMNS}
    code_to_idx: dict[str, int]   = {c: i for i, c in enumerate(df["代码"].tolist())}

    print(
        f"开始抓取财务数据：待处理 {total} 只"
        f"（timeout={FINANCE_TIMEOUT}s  sleep={SLEEP_MIN}~{SLEEP_MAX}s"
        f"  连续失败>{CONSEC_FAIL_LIMIT}次暂停{CONSEC_FAIL_PAUSE}s）",
        flush=True,
    )
    t_start = time.time()

    for seq, code in enumerate(codes, 1):
        fin, err = fetch_financial_with_timeout(ak, code)

        idx = code_to_idx.get(code)
        if fin and idx is not None:
            for col in FINANCIAL_COLUMNS:
                if col in fin:
                    new_fin[col][idx] = fin[col]
            success   += 1
            consec_fail = 0          # 成功则重置连续失败计数
        else:
            label = "超时" if err == "TIMEOUT" else "失败"
            if err == "TIMEOUT":
                timeout_count += 1
            else:
                fail += 1
            failed_list.append((code, err))
            consec_fail += 1
            print(f"  [{code}] {label}：{err}", flush=True)

            # 连续失败触发长暂停
            if consec_fail >= CONSEC_FAIL_LIMIT:
                print(
                    f"  ⚠ 连续失败 {consec_fail} 次，暂停 {CONSEC_FAIL_PAUSE}s ...",
                    flush=True,
                )
                time.sleep(CONSEC_FAIL_PAUSE)
                consec_fail = 0

        # 每 10 只打印进度
        if seq % 10 == 0 or seq == total:
            elapsed = time.time() - t_start
            rate = seq / elapsed if elapsed > 0 else 0
            eta  = (total - seq) / rate if rate > 0 else 0
            print(
                f"  [{seq:5d}/{total}] 成功 {success}  超时 {timeout_count}"
                f"  失败 {fail}  {rate:.2f}只/s  剩余≈{eta/60:.1f}min",
                flush=True,
            )

        # 每 100 只存检查点
        if seq % 100 == 0:
            _apply_fin_to_df(df, new_fin)
            save_cache(df, CHECKPOINT_FILE)
            _save_failed_codes(failed_list)
            print(f"  ✓ 检查点 {seq}/{total}，失败列表已更新 → {FAILED_FILE.name}", flush=True)

        # 随机暂停（成功或失败都暂停，避免频繁请求）
        time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))

    # 最终写回
    _apply_fin_to_df(df, new_fin)
    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
    _save_failed_codes(failed_list)

    if failed_list:
        print(f"  失败股票已保存 → {FAILED_FILE.name}（共 {len(failed_list)} 只）", flush=True)
    else:
        print("  所有股票财务数据抓取成功，failed_codes.csv 已清空。", flush=True)

    print(
        f"财务数据完成：成功 {success} 只 / 超时 {timeout_count} 只 / 失败 {fail} 只"
        f"（跳过已有数据 {skipped} 只）。",
        flush=True,
    )
    return df


def _apply_fin_to_df(df: Any, new_fin: dict[str, list[Any]]) -> None:
    """将 new_fin 里非 None 的值合并回 df（已有旧值的字段不覆盖为 None）。"""
    for col in FINANCIAL_COLUMNS:
        existing = df[col].tolist()
        merged = [
            nv if nv is not None else ev
            for nv, ev in zip(new_fin[col], existing)
        ]
        df[col] = merged


# ── 主流程 ────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="更新 stock_metrics.csv：先抓行情，再抓财务数据。"
    )
    parser.add_argument(
        "--skip-finance",
        action="store_true",
        help="跳过财务数据抓取，只更新行情数据（速度快，适合日常刷新）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        metavar="N",
        help="只处理前 N 只股票（财务数据部分），0 表示不限制（默认）",
    )
    parser.add_argument(
        "--fast-spot",
        action="store_true",
        help="跳过东财全市场接口，直接使用新浪 HTTP 备用接口更新行情（适合 GitHub Actions 日常快速刷新）",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="只重试 failed_codes.csv 里的失败股票，跳过重新拉取行情",
    )
    parser.add_argument(
        "--retry-empty-finance",
        action="store_true",
        help="从 stock_metrics.csv 找出财务字段全空的股票并重新抓取，不重新拉取行情",
    )
    return parser.parse_args()


def _apply_ssl_fix() -> None:
    """国内网络访问东财接口偶发 SSL 解密失败，关闭证书校验可显著提升稳定性。"""
    try:
        import ssl

        ssl._create_default_https_context = ssl._create_unverified_context  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        print(f"  SSL 修复未生效（不影响功能）：{exc}", flush=True)
    try:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    args = parse_args()
    print("正在启动 update_cache.py...", flush=True)

    _apply_ssl_fix()

    global pd
    try:
        import pandas as _pd  # type: ignore
        pd = _pd
    except Exception as exc:  # noqa: BLE001
        print(f"无法导入 pandas：{exc}", flush=True)
        return

    try:
        import akshare as ak  # type: ignore
    except Exception as exc:  # noqa: BLE001
        print(f"无法导入 akshare：{exc}", flush=True)
        return

    # ── --retry-failed 模式：直接读现有 CSV，只重试失败股票 ───────────────────
    if args.retry_failed:
        retry_codes = _load_failed_codes()
        if not retry_codes:
            print("failed_codes.csv 不存在或为空，没有需要重试的股票。", flush=True)
            return
        print(f"  模式：--retry-failed，从 failed_codes.csv 读取 {len(retry_codes)} 只股票。", flush=True)

        output = read_existing_cache()
        if output.empty:
            print("stock_metrics.csv 为空，请先完整运行一次。", flush=True)
            return

        # 临时把 df 限制为只含待重试代码，enrich 完后合并回全量
        retry_set = set(retry_codes)
        retry_df  = output[output["代码"].isin(retry_set)].copy().reset_index(drop=True)
        other_df  = output[~output["代码"].isin(retry_set)].copy().reset_index(drop=True)

        print(f"  CSV 中匹配到 {len(retry_df)} 只，其余 {len(other_df)} 只保持不变。", flush=True)

        # 强制清空 retry_df 的财务字段，让 enrich 重新抓（不跳过）
        for col in FINANCIAL_COLUMNS:
            retry_df[col] = None

        retry_df = enrich_with_financial(ak, retry_df, limit=args.limit)

        # 合并回全量并保存
        output = pd.concat([other_df, retry_df], ignore_index=True)
        try:
            save_cache(output)
        except Exception as exc:  # noqa: BLE001
            print(f"保存 stock_metrics.csv 失败：{exc}", flush=True)
            return

        fin_count = int(output[FINANCIAL_COLUMNS].notna().any(axis=1).sum())
        print(
            f"\n完成！stock_metrics.csv 已更新：{len(output)} 只 A 股，"
            f"其中 {fin_count} 只含财务数据。",
            flush=True,
        )
        return

    # ── --retry-empty-finance 模式：找财务字段全空的股票重新抓取 ────────────────
    if args.retry_empty_finance:
        output = read_existing_cache()
        if output.empty:
            print("stock_metrics.csv 为空，请先完整运行一次。", flush=True)
            return

        empty_codes = _find_empty_finance_codes(output)
        if not empty_codes:
            print("所有股票均已有财务数据，无需重新抓取。", flush=True)
            return

        print(
            f"  模式：--retry-empty-finance\n"
            f"  共 {len(output)} 只股票，其中财务字段全空 {len(empty_codes)} 只，开始补抓...",
            flush=True,
        )

        empty_set  = set(empty_codes)
        retry_df   = output[output["代码"].isin(empty_set)].copy().reset_index(drop=True)
        other_df   = output[~output["代码"].isin(empty_set)].copy().reset_index(drop=True)

        # 确保财务字段干净（理论上已全空，但显式清空避免残留 0）
        for col in FINANCIAL_COLUMNS:
            retry_df[col] = None

        retry_df = enrich_with_financial(ak, retry_df, limit=args.limit)

        # 合并：other_df 原封不动，retry_df 更新后拼回
        output = pd.concat([other_df, retry_df], ignore_index=True)
        # 按原始顺序排（以代码排序，保持 CSV 整洁）
        output = output.sort_values("代码").reset_index(drop=True)

        try:
            save_cache(output)
        except Exception as exc:  # noqa: BLE001
            print(f"保存 stock_metrics.csv 失败：{exc}", flush=True)
            return

        fin_count = int(output[FINANCIAL_COLUMNS].notna().any(axis=1).sum())
        print(
            f"\n完成！stock_metrics.csv 共 {len(output)} 只 A 股，"
            f"其中 {fin_count} 只含财务数据。",
            flush=True,
        )
        return

    # ── 正常模式 ──────────────────────────────────────────────────────────────
    if args.skip_finance:
        print("  模式：--skip-finance，只更新行情数据。", flush=True)
    if args.limit > 0:
        print(f"  模式：--limit {args.limit}，财务数据只处理前 {args.limit} 只。", flush=True)

    # 第一步：行情
    spot_df = fetch_spot_data(ak, fast_spot=args.fast_spot)
    if not is_valid_frame(spot_df):
        return

    try:
        spot_df = normalize_spot_frame(spot_df)
        if spot_df.empty:
            print("行情数据没有有效股票代码，中止。", flush=True)
            return
        print_spot_valuation_summary(spot_df)
        old_cache = read_existing_cache()
        output = build_cache_rows(spot_df, old_cache)
        if output.empty:
            print("生成的缓存数据为空，中止。", flush=True)
            return
        if args.fast_spot:
            print("快速行情模式已包含 PE/PB 等字段，跳过额外估值补抓。", flush=True)
        else:
            output = merge_valuation_fields(output, fetch_valuation_pages())
    except Exception as exc:  # noqa: BLE001
        print(f"处理行情数据出错：{exc}", flush=True)
        return

    print(f"行情数据处理完成，共 {len(output)} 只股票。", flush=True)

    # 第二步：财务数据
    if args.skip_finance:
        print("已跳过财务数据抓取（--skip-finance）。", flush=True)
    else:
        output = enrich_with_financial(ak, output, limit=args.limit)

    # 第三步：保存
    try:
        save_cache(output)
    except Exception as exc:  # noqa: BLE001
        print(f"保存 stock_metrics.csv 失败：{exc}", flush=True)
        return

    fin_count = int(output[FINANCIAL_COLUMNS].notna().any(axis=1).sum())
    print(
        f"\n完成！stock_metrics.csv 已更新：{len(output)} 只 A 股，"
        f"其中 {fin_count} 只含财务数据。",
        flush=True,
    )


if __name__ == "__main__":
    main()
