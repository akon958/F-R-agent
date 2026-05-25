#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
build_industry_map.py

一次性脚本：构建 A 股 code -> 申万一级行业 映射表，输出到 industry_map.csv。

策略（双源合并，申万优先）：
  1. 主数据源：申万一级成分股（ak.index_component_sw），权威标准
  2. 兜底数据源：东方财富行业（ak.stock_individual_info_em），覆盖申万未收录股票
  output 新增 source 列标记来源：sw / em / none

用法：
  python build_industry_map.py

注意：
  - 全量约 5000 只股票，兜底部分每只需网络请求，预计耗时 20-40 分钟
  - 所有 AkShare 调用均在函数体内，不在模块加载时执行
"""

import csv
import os
import ssl
import time
from datetime import datetime
from pathlib import Path

# ── SSL 修复（必须在 import akshare 之前执行）────────────────────────────────
# 中国金融网站（bse.cn / szse.cn / swsresearch.com）使用旧 TLS 1.0/1.1，
# OpenSSL 3.x 默认禁止旧版本，导致 UNEXPECTED_EOF_WHILE_READING。
import requests
import urllib3
from requests.adapters import HTTPAdapter

os.environ['PYTHONHTTPSVERIFY'] = '0'
urllib3.disable_warnings()


def _make_ssl_ctx() -> ssl.SSLContext:
    """创建最宽松的 SSL 上下文：跳过证书验证 + 允许 TLS 1.0+ + 降低密码安全级别。"""
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS)  # type: ignore[attr-defined]
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    # 允许旧版 TLS（1.0 / 1.1），OpenSSL 3.x 默认只允许 1.2+
    try:
        ctx.minimum_version = ssl.TLSVersion.TLSv1  # type: ignore[attr-defined]
    except Exception:
        pass
    # OP_LEGACY_SERVER_CONNECT 允许 EOF 后继续（OpenSSL 3.x 严格模式的兜底）
    ctx.options |= getattr(ssl, 'OP_LEGACY_SERVER_CONNECT', 0x4)
    # SECLEVEL=1 允许较弱的密码套件（部分旧站点需要）
    try:
        ctx.set_ciphers('DEFAULT:@SECLEVEL=1')
    except Exception:
        pass
    return ctx


ssl._create_default_https_context = _make_ssl_ctx


class _LegacySSLAdapter(HTTPAdapter):
    """为所有 HTTPS 请求注入宽松 SSL 配置。"""
    def init_poolmanager(self, *args, **kwargs):
        kwargs['ssl_context'] = _make_ssl_ctx()
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        proxy_kwargs['ssl_context'] = _make_ssl_ctx()
        return super().proxy_manager_for(proxy, **proxy_kwargs)


# 同时 patch __init__ 和 send，双重保险
_orig_init = requests.Session.__init__
def _patched_init(self, *args, **kwargs):
    _orig_init(self, *args, **kwargs)
    self.mount('https://', _LegacySSLAdapter())
    self.verify = False
requests.Session.__init__ = _patched_init

_orig_send = requests.Session.send
def _patched_send(self, request, **kwargs):
    kwargs.setdefault('verify', False)
    return _orig_send(self, request, **kwargs)
requests.Session.send = _patched_send

import akshare as ak  # noqa: E402（intentionally after SSL patch）


# ── 进度条工具 ────────────────────────────────────────────────────────────
def _progress_bar(current: int, total: int, width: int = 40) -> None:
    """在同一行打印 ASCII 进度条，末尾换行前不会新建行。"""
    pct = current / total if total else 0.0
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    print(f"\r  [{bar}] {current}/{total} ({pct:.1%})", end="", flush=True)

OUTPUT_FILE = Path(__file__).resolve().parent / "data" / "industry_map.csv"


def normalize_code(raw: str) -> str:
    return str(raw).strip().zfill(6)


# ── Step 1：申万一级成分股 → 主映射 ─────────────────────────────────────

def fetch_sw_industry_map() -> dict[str, str]:
    """
    遍历申万一级所有行业，拉取成分股列表，返回 {stock_code: industry_name}。
    单个行业失败时跳过，不中断整体流程。
    """
    print("=== Step 1: 拉取申万一级行业列表 ===")
    try:
        info_df = ak.sw_index_first_info()
    except Exception as e:
        print(f"  [ERROR] sw_index_first_info 调用失败: {e}")
        return {}

    # 第一列是行业代码（如 "801010.SI"），第二列是行业名称
    col_code = info_df.columns[0]
    col_name = info_df.columns[1]

    industries: list[tuple[str, str]] = []
    for _, row in info_df.iterrows():
        raw_code = str(row[col_code]).strip()
        name = str(row[col_name]).strip()
        idx_code = raw_code.split(".")[0]   # "801010.SI" -> "801010"
        if idx_code.isdigit():
            industries.append((idx_code, name))

    print(f"  共 {len(industries)} 个申万一级行业\n")

    total_ind = len(industries)
    sw_map: dict[str, str] = {}
    for i, (idx_code, industry_name) in enumerate(industries, 1):
        prefix = f"  [{i:2d}/{total_ind}]"
        try:
            cons_df = ak.index_component_sw(symbol=idx_code)
            code_col = cons_df.columns[1]
            for _, row in cons_df.iterrows():
                stock_code = normalize_code(str(row[code_col]))
                sw_map[stock_code] = industry_name
            print(f"{prefix} {industry_name}（{idx_code}）: {len(cons_df)} 只")
        except Exception as e:
            print(f"{prefix} [WARN] {industry_name}（{idx_code}）失败: {e}")
            time.sleep(1)
        time.sleep(0.5)

    print(f"\n  申万成分股映射完成，共 {len(sw_map)} 只\n")
    return sw_map


# ── Step 2：全 A 股列表 ───────────────────────────────────────────────────

def fetch_all_a_stocks() -> list[tuple[str, str]]:
    """返回 [(code, name), ...] 全 A 股列表。"""
    print("=== Step 2: 拉取全 A 股列表 ===")
    try:
        df = ak.stock_info_a_code_name()
    except Exception as e:
        print(f"  [ERROR] stock_info_a_code_name 调用失败: {e}")
        return []

    col_code = df.columns[0]
    col_name = df.columns[1]
    stocks = [
        (normalize_code(str(r[col_code])), str(r[col_name]).strip())
        for _, r in df.iterrows()
    ]
    print(f"  全 A 股共 {len(stocks)} 只\n")
    return stocks


# ── Step 3：东方财富行业板块批量兜底 ─────────────────────────────────────────

def fetch_em_industry_map(
    missing_stocks: list[tuple[str, str]],
) -> dict[str, str]:
    """
    用东方财富行业板块接口批量拉取，替代逐股查询。
    东方财富约 100 个行业板块，每板块一次请求，耗时 1-2 分钟（原逐股方案需 20 分钟）。
    """
    missing_codes = {code for code, _ in missing_stocks}
    print(f"=== Step 3: 东方财富批量行业查询（目标覆盖 {len(missing_codes)} 只）===")

    # 获取东方财富行业板块列表
    try:
        board_df = ak.stock_board_industry_name_em()
    except Exception as e:
        print(f"  [ERROR] 获取东方财富行业列表失败: {e}")
        return {}

    name_col = board_df.columns[0]   # 通常是 "板块名称"
    industry_names: list[str] = board_df[name_col].tolist()
    total = len(industry_names)
    print(f"  共 {total} 个东方财富行业板块\n")

    em_map: dict[str, str] = {}

    for i, industry_name in enumerate(industry_names, 1):
        prefix = f"  [{i:3d}/{total}]"
        try:
            cons_df = ak.stock_board_industry_cons_em(symbol=industry_name)
            # 代码列通常名为 "代码"，取第一列作为兜底
            code_col = "代码" if "代码" in cons_df.columns else cons_df.columns[0]
            for _, row in cons_df.iterrows():
                code = normalize_code(str(row[code_col]))
                if code in missing_codes and code not in em_map:
                    em_map[code] = industry_name
            print(f"{prefix} {industry_name}: {len(cons_df)} 只")
        except Exception as e:
            print(f"{prefix} [WARN] {industry_name} 失败: {e}")
            time.sleep(1)
        time.sleep(0.3)

    found = len(em_map)
    print(f"\n  批量查询完成：覆盖 {found}/{len(missing_codes)} 只\n")
    return em_map


# ── Step 4：合并写入 CSV ──────────────────────────────────────────────────

def write_csv(
    all_stocks: list[tuple[str, str]],
    sw_map: dict[str, str],
    em_map: dict[str, str],
    now_str: str,
) -> None:
    print("=== Step 4: 写入 industry_map.csv ===")
    rows = []
    for code, name in all_stocks:
        if code in sw_map:
            rows.append({"code": code, "name": name, "sw_industry": sw_map[code],
                         "source": "sw", "last_updated": now_str})
        elif code in em_map:
            rows.append({"code": code, "name": name, "sw_industry": em_map[code],
                         "source": "em", "last_updated": now_str})
        else:
            rows.append({"code": code, "name": name, "sw_industry": None,
                         "source": "none", "last_updated": now_str})

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=["code", "name", "sw_industry", "source", "last_updated"]
        )
        writer.writeheader()
        writer.writerows(rows)

    total = len(rows)
    sw_n  = sum(1 for r in rows if r["source"] == "sw")
    em_n  = sum(1 for r in rows if r["source"] == "em")
    none_n = sum(1 for r in rows if r["source"] == "none")

    print(f"  已写入 {OUTPUT_FILE}")
    print()
    print("=" * 40)
    print("  汇总")
    print("=" * 40)
    print(f"  总数:          {total}")
    print(f"  申万覆盖:      {sw_n}  ({sw_n/total:.1%})")
    print(f"  东财兜底覆盖:  {em_n}  ({em_n/total:.1%})")
    print(f"  未覆盖 (None): {none_n}  ({none_n/total:.1%})")
    print("=" * 40)


# ── 主流程 ────────────────────────────────────────────────────────────────

def build_industry_map() -> None:
    now_str = datetime.now().isoformat(timespec="seconds")

    sw_map    = fetch_sw_industry_map()
    all_stocks = fetch_all_a_stocks()
    if not all_stocks:
        print("[ERROR] 无法获取全 A 股列表，终止。")
        return

    missing = [(c, n) for c, n in all_stocks if c not in sw_map]
    em_map  = fetch_em_industry_map(missing)

    write_csv(all_stocks, sw_map, em_map, now_str)


if __name__ == "__main__":
    build_industry_map()
