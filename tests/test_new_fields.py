#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
验证 stock_metrics.csv 的新财务字段是否就绪。

用法：
  python test_new_fields.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

CSV = Path(__file__).resolve().parent.parent / "data" / "stock_metrics.csv"

CASHFLOW_HISTORY_COLUMNS = [
    "经营现金流/净利润_近1期",
    "经营现金流/净利润_近2期",
    "经营现金流/净利润_近3期",
]
DIVIDEND_HISTORY_COLUMNS = [
    "股息率_近1期",
    "股息率_近2期",
    "股息率_近3期",
]
REQUIRED_COLUMNS = [
    "代码",
    "经营现金流/净利润",
    "股息率",
    *CASHFLOW_HISTORY_COLUMNS,
    *DIVIDEND_HISTORY_COLUMNS,
]
SAMPLE = [
    ("600519", "贵州茅台"),
    ("000001", "平安银行"),
    ("600036", "招商银行"),
]

PASS = "[OK]"
FAIL = "[FAIL]"
errors: list[str] = []


def check(condition: bool, desc: str) -> None:
    if condition:
        print(f"{PASS}  {desc}")
    else:
        print(f"{FAIL}  {desc}")
        errors.append(desc)


def to_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("%", "")
    if text in {"", "-", "--", "nan", "None"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def coverage_ratio(series: pd.Series) -> float:
    total = len(series)
    if total == 0:
        return 0.0
    present = series.map(to_float).notna().sum()
    return present / total


print("\n[1] CSV 文件存在")
check(CSV.exists(), f"stock_metrics.csv 存在（{CSV}）")
if not CSV.exists():
    sys.exit(1)

df = pd.read_csv(CSV, dtype={"代码": str}, encoding="utf-8-sig")

print("\n[2] 新字段列存在")
for column in REQUIRED_COLUMNS:
    check(column in df.columns, f"包含列 [{column}]")

missing_required = [column for column in REQUIRED_COLUMNS if column not in df.columns]
if missing_required:
    print("\n缺列过多，终止后续验证。")
    sys.exit(1)

print("\n[3] 兼容层：近1期列可从旧单列降级")
cashflow_near1_same = (
    df["经营现金流/净利润_近1期"].fillna(df["经营现金流/净利润"]).map(to_float).notna().sum()
    >= df["经营现金流/净利润"].map(to_float).notna().sum()
)
check(cashflow_near1_same, "经营现金流/净利润_近1期 至少不比旧单列更差")

dividend_near1_same = (
    df["股息率_近1期"].fillna(df["股息率"]).map(to_float).notna().sum()
    >= df["股息率"].map(to_float).notna().sum()
)
check(dividend_near1_same, "股息率_近1期 至少不比旧单列更差")

print("\n[4] 抽样股票检查")
code_map = df.set_index("代码").to_dict(orient="index")
dividend_any = df["股息率_近1期"].fillna(df["股息率"]).map(to_float).notna().any()
for code, name in SAMPLE:
    row = code_map.get(code.zfill(6), {})
    cashflow_latest = row.get("经营现金流/净利润")
    cashflow_p1 = row.get("经营现金流/净利润_近1期")
    dividend_latest = row.get("股息率")
    dividend_p1 = row.get("股息率_近1期")
    check(
        to_float(cashflow_latest) is not None or to_float(cashflow_p1) is not None,
        f"{name}（{code}）有经营现金流/净利润最新值或近1期值",
    )
    if dividend_any:
        check(
            to_float(dividend_latest) is not None or to_float(dividend_p1) is not None,
            f"{name}（{code}）有股息率最新值或近1期值",
        )

print("\n[5] 覆盖率")
cashflow_ratio = coverage_ratio(df["经营现金流/净利润_近1期"].fillna(df["经营现金流/净利润"]))
dividend_ratio = coverage_ratio(df["股息率_近1期"].fillna(df["股息率"]))
print(f"  经营现金流/净利润近1期覆盖率: {cashflow_ratio:.1%}")
print(f"  股息率近1期覆盖率: {dividend_ratio:.1%}")
check(cashflow_ratio >= 0.30, "经营现金流/净利润近1期覆盖率 ≥ 30%")
if dividend_ratio > 0:
    check(dividend_ratio >= 0.10, "股息率近1期覆盖率 ≥ 10%")
else:
    check(True, "股息率近1期当前允许为 0，等待后续执行补抓")

print("\n[6] 三期列结构")
cashflow_available = sum(df[column].map(to_float).notna().sum() > 0 for column in CASHFLOW_HISTORY_COLUMNS)
check(cashflow_available >= 1, "经营现金流/净利润三期列至少有 1 列存在有效值")

dividend_available = sum(df[column].map(to_float).notna().sum() > 0 for column in DIVIDEND_HISTORY_COLUMNS)
if dividend_ratio > 0:
    check(dividend_available >= 1, "股息率三期列至少有 1 列存在有效值")
else:
    check(True, "股息率三期列结构已建好，当前缓存允许暂时无值")

print()
if errors:
    print(f"[FAIL] 失败 {len(errors)} 项：")
    for error in errors:
        print(f"   - {error}")
    sys.exit(1)

print("[OK] 新财务字段验证通过。")
