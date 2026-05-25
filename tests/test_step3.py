#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke tests for Step 3 financial comparison helpers."""

from __future__ import annotations

import sys

from analyzer import compute_trend, get_industry_mean, get_industry_rank, check_consistency
from validator import scan_financial_claims


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[OK] {message}")


stocks = [
    {
        "code": "600001",
        "name": "样本A",
        "industry": "银行",
        "roe": 0.12,
        "cashflow_profit_ratio": 1.1,
        "cashflow_profit_ratio_p1": 1.1,
        "cashflow_profit_ratio_p2": 0.9,
        "cashflow_profit_ratio_p3": 0.8,
        "dividend_yield": 0.035,
        "dividend_yield_p1": 0.035,
        "dividend_yield_p2": 0.03,
        "dividend_yield_p3": 0.028,
    },
    {
        "code": "600002",
        "name": "样本B",
        "industry": "银行",
        "roe": 0.09,
        "cashflow_profit_ratio": 0.7,
        "dividend_yield": 0.01,
    },
]


try:
    mean = get_industry_mean(stocks, "银行", "roe")
    check(mean is not None and mean > 0, "get_industry_mean returns a peer mean")

    rank = get_industry_rank(stocks, stocks[0], "roe")
    check(rank["available"] and rank["rank"] == 1, "get_industry_rank ranks same-industry peers")

    trend = compute_trend([1.1, 0.9, 0.8])
    check(trend["available"] and trend["direction"] == "up", "compute_trend detects improvement")

    consistency = check_consistency(stocks[0])
    check(consistency["available"] and consistency["status"] == "ok", "check_consistency returns ok for coherent data")

    scan = scan_financial_claims("股息率高所以买，趋势改善所以会上涨")
    check(not scan["passed"] and "所以买" not in scan["text"], "scan_financial_claims sanitizes risky wording")
except AssertionError as exc:
    print(f"[FAIL] {exc}")
    sys.exit(1)

print("[OK] Step 3 smoke tests passed.")
