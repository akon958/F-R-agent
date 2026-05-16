"""update_cache.py
本地运行脚本，用 AkShare 抓取全 A 股行情并生成 stock_metrics.csv。

使用方法：
    python update_cache.py

运行完成后把生成的 stock_metrics.csv 提交到 GitHub，
Streamlit Cloud 会自动读取最新缓存，手机端无需实时联网抓行情。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# ── 依赖检查 ────────────────────────────────────────────────────────
try:
    import akshare as ak
except ImportError:
    print("❌ 未安装 akshare，请先执行：pip install akshare")
    sys.exit(1)

try:
    import pandas as pd
except ImportError:
    print("❌ 未安装 pandas，请先执行：pip install pandas")
    sys.exit(1)

# ── 常量 ────────────────────────────────────────────────────────────
CACHE_FILE = Path(__file__).with_name("stock_metrics.csv")

# 最终输出列（顺序固定，供 data_fetcher.py 读取）
OUTPUT_COLUMNS = [
    "代码",
    "名称",
    "最新价",
    "涨跌幅",
    "成交额",
    "换手率",
    "市盈率-动态",
    "市净率",
    "总市值",
    "流通市值",
    "量比",
    "振幅",
    "所属行业",
    "更新时间",
]

# AkShare spot 列名到标准列名的映射
SPOT_COLUMN_MAP = {
    "代码":       "代码",
    "名称":       "名称",
    "最新价":     "最新价",
    "涨跌幅":     "涨跌幅",
    "成交额":     "成交额",
    "换手率":     "换手率",
    "市盈率-动态": "市盈率-动态",
    "市净率":     "市净率",
    "总市值":     "总市值",
    "流通市值":   "流通市值",
    "量比":       "量比",
    "振幅":       "振幅",
}


def _normalize_code(code: str) -> str:
    text = str(code or "").strip().upper()
    if text.startswith(("SH", "SZ", "BJ")):
        text = text[2:]
    return text.zfill(6) if text else ""


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _fetch_spot() -> pd.DataFrame | None:
    """调用 ak.stock_zh_a_spot_em() 获取全 A 股实时行情。"""
    print("📡 正在调用 AkShare stock_zh_a_spot_em()，请稍候...")
    try:
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            print("⚠️  AkShare 返回空数据。")
            return None
        print(f"✅ 获取到 {len(df)} 条行情记录。")
        return df
    except Exception as e:  # noqa: BLE001
        print(f"❌ AkShare 调用失败：{e}")
        return None


def _fetch_industry() -> dict[str, str]:
    """尝试获取行业分类（Shenwan L1），失败时返回空字典。"""
    print("📡 正在获取行业分类（申万一级）...")
    try:
        df = ak.stock_board_industry_name_em()
        if df is None or df.empty:
            return {}
        industry_map: dict[str, str] = {}
        for _, row in df.iterrows():
            board_name = str(row.get("板块名称", ""))
            try:
                stocks = ak.stock_board_industry_cons_em(symbol=board_name)
                if stocks is not None and not stocks.empty and "代码" in stocks.columns:
                    for code in stocks["代码"].astype(str):
                        industry_map[_normalize_code(code)] = board_name
            except Exception:  # noqa: BLE001
                continue
        print(f"✅ 获取到 {len(industry_map)} 只股票的行业分类。")
        return industry_map
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  行业分类获取失败（{e}），将跳过行业字段。")
        return {}


def _build_cache(spot_df: pd.DataFrame, industry_map: dict[str, str]) -> pd.DataFrame:
    """把原始 spot 数据整理为标准格式。"""
    result = pd.DataFrame()

    # 代码标准化
    result["代码"] = spot_df["代码"].astype(str).map(_normalize_code)

    # 逐列映射
    for src, dst in SPOT_COLUMN_MAP.items():
        if src in spot_df.columns:
            result[dst] = pd.to_numeric(spot_df[src], errors="coerce") if dst != "代码" else result["代码"]
        else:
            result[dst] = None

    # 补名称（字符串列单独处理）
    if "名称" in spot_df.columns:
        result["名称"] = spot_df["名称"].astype(str)

    # 行业
    result["所属行业"] = result["代码"].map(industry_map).fillna("未知")

    # 更新时间
    result["更新时间"] = _now_text()

    # 去掉代码为空的行，去重
    result = result[result["代码"] != ""]
    result = result.drop_duplicates(subset=["代码"], keep="last")

    # 保证列顺序一致
    for col in OUTPUT_COLUMNS:
        if col not in result.columns:
            result[col] = None
    result = result[OUTPUT_COLUMNS]

    return result


def _merge_with_existing(new_df: pd.DataFrame) -> pd.DataFrame:
    """把新数据和已有缓存合并，新数据优先覆盖旧数据。"""
    if not CACHE_FILE.exists():
        return new_df

    try:
        old_df = pd.read_csv(CACHE_FILE, dtype={"代码": str})
        old_df["代码"] = old_df["代码"].astype(str).map(_normalize_code)
        # 以新数据为主，旧缓存只补充新数据里没有的股票
        old_missing = old_df[~old_df["代码"].isin(new_df["代码"])]
        merged = pd.concat([new_df, old_missing], ignore_index=True)
        merged = merged.drop_duplicates(subset=["代码"], keep="first")
        return merged
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  读取旧缓存失败（{e}），将直接写入新数据。")
        return new_df


def main() -> None:
    print("=" * 55)
    print("家庭投资雷达 Agent — 本地数据缓存更新工具")
    print("=" * 55)

    # 1. 抓实时行情（必须成功）
    spot_df = _fetch_spot()
    if spot_df is None:
        print("\n❌ 行情数据获取失败，stock_metrics.csv 未更新。")
        print("   请检查网络连接或 AkShare 版本（pip install -U akshare）。")
        sys.exit(1)

    # 2. 尝试抓行业分类（可失败，不阻塞）
    industry_map = _fetch_industry()

    # 3. 整理数据
    print("🔧 正在整理数据格式...")
    new_df = _build_cache(spot_df, industry_map)

    # 4. 与旧缓存合并（保留旧缓存里有但今天停牌的股票）
    final_df = _merge_with_existing(new_df)

    # 5. 写入文件
    final_df.to_csv(CACHE_FILE, index=False, encoding="utf-8-sig")
    print(f"\n✅ stock_metrics.csv 已更新")
    print(f"   路径：{CACHE_FILE.resolve()}")
    print(f"   股票数量：{len(final_df)}")
    print(f"   更新时间：{_now_text()}")
    print()
    print("下一步：")
    print("  1. git add stock_metrics.csv")
    print("  2. git commit -m 'update cache'")
    print("  3. git push")
    print("  → Streamlit Cloud 重新部署后手机端即可读取最新数据。")
    print("=" * 55)


if __name__ == "__main__":
    main()
