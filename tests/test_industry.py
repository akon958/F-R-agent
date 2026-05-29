#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_industry.py

手动运行一次，验证行业分类基础设施是否就绪。
不接入 CI，本地跑通即可。

用法：
  python test_industry.py
"""

import sys
from pathlib import Path

import pandas as pd

from data_fetcher import get_industry, get_industry_meta

INDUSTRY_MAP = Path(__file__).resolve().parent.parent / "data" / "industry_map.csv"

REQUIRED_COLUMNS = {"code", "name", "sw_industry", "last_updated"}

# 抽样股票：(代码, 名称, 预期非空申万行业)
SAMPLE_STOCKS = [
    ("600519", "贵州茅台"),
    ("000001", "平安银行"),
    ("002475", "立讯精密"),
    ("000651", "格力电器"),
    ("600036", "招商银行"),
]

PASS = "  ✓"
FAIL = "  ✗"


def main() -> int:
    """脚本式自检。返回退出码（0=全过，1=有失败）。

    注意：所有断言逻辑放在 main() 里，由 `if __name__ == "__main__"` 守卫触发。
    这样 `unittest discover` 导入本模块时不会执行脚本体（它本就不是 unittest 用例，
    没有 TestCase），避免在全套测试里报 ImportError。直接 `python tests/test_industry.py`
    运行的行为完全不变。
    """
    errors: list[str] = []

    def check(condition: bool, desc: str) -> None:
        if condition:
            print(f"{PASS}  {desc}")
        else:
            print(f"{FAIL}  {desc}")
            errors.append(desc)

    # ── 断言 1：文件存在且非空 ─────────────────────────────────────────────
    print("\n[1] 文件存在且非空")
    exists = INDUSTRY_MAP.exists()
    check(exists, f"industry_map.csv 存在（{INDUSTRY_MAP}）")
    if exists:
        size = INDUSTRY_MAP.stat().st_size
        check(size > 0, f"文件非空（{size} bytes）")

    # ── 断言 2：包含必要列 ────────────────────────────────────────────────
    print("\n[2] 列结构正确")
    df = None
    if exists:
        try:
            df = pd.read_csv(INDUSTRY_MAP, encoding="utf-8-sig", dtype=str)
            actual_cols = set(df.columns.tolist())
            missing_cols = REQUIRED_COLUMNS - actual_cols
            check(not missing_cols, f"包含必要列 {REQUIRED_COLUMNS}（缺失：{missing_cols or '无'}）")
        except Exception as e:
            check(False, f"读取 CSV 失败: {e}")

    # ── 断言 3：抽样股票 sw_industry 非空 ──────────────────────────────────
    print("\n[3] 抽样股票行业非空")
    code_map: dict[str, str] = {}
    if df is not None:
        code_map = {
            str(r["code"]).strip().zfill(6): str(r.get("sw_industry") or "")
            for _, r in df.iterrows()
        }
        for code, name in SAMPLE_STOCKS:
            industry = code_map.get(code.zfill(6), "")
            ok = bool(industry) and industry.lower() not in ("nan", "none", "")
            check(ok, f"{name}（{code}）→ {industry or '(空)'}")

    # ── 断言 4：get_industry 返回非 None ───────────────────────────────────
    print("\n[4] get_industry() 接口")
    result = get_industry("600519")
    check(result is not None, f'get_industry("600519") 返回非 None → {result!r}')

    # ── 断言 5：不存在的代码返回 None ─────────────────────────────────────
    result_fake = get_industry("XXXXXX")
    check(result_fake is None, f'get_industry("XXXXXX") 返回 None → {result_fake!r}')

    # ── 断言 6：get_industry_meta 格式正确 ────────────────────────────────
    print("\n[5] get_industry_meta() 格式")
    meta = get_industry_meta()
    check(isinstance(meta, dict), "返回 dict")
    check("total_stocks" in meta and isinstance(meta["total_stocks"], int),
          f'total_stocks: {meta.get("total_stocks")}')
    check("with_industry" in meta and isinstance(meta["with_industry"], int),
          f'with_industry: {meta.get("with_industry")}')
    check("last_updated" in meta and isinstance(meta["last_updated"], str),
          f'last_updated: {meta.get("last_updated")!r}')

    # ── 断言 7：覆盖率 ≥ 90% ──────────────────────────────────────────────
    print("\n[6] 覆盖率")
    if df is not None:
        total = len(df)
        with_industry = sum(
            1 for v in code_map.values()
            if v and v.lower() not in ("nan", "none", "")
        )
        ratio = with_industry / total if total else 0
        print(f"  覆盖率: {with_industry}/{total} = {ratio:.1%}")
        check(ratio >= 0.90, f"覆盖率 ≥ 90%（实际 {ratio:.1%}）")

    # ── 汇总 ──────────────────────────────────────────────────────────────
    print()
    if errors:
        print(f"❌ 失败 {len(errors)} 项：")
        for e in errors:
            print(f"   - {e}")
        return 1
    print("✅ 全部断言通过，行业分类基础设施就绪。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
