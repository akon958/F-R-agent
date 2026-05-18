from __future__ import annotations

import os
from html import escape
from math import pi
from typing import Any

import pandas as pd
import streamlit as st

from analyzer import analyze_portfolio
from ai_report import generate_parent_friendly_report
from data_fetcher import (
    get_cache_summary,
    get_stock_metrics,
    normalize_code,
    refresh_current_holdings_cache,
    refresh_market_cache,
)
from report_generator import generate_txt_report, money, percent


APP_TITLE = "家庭投资助手"
APP_SUBTITLE = "Family Investment Agent"
DEFAULT_CODES = ["600519", "000001", "300750"]
DEFAULT_AMOUNTS = [20000.0, 10000.0, 0.0]
HOME_DISCLAIMER = "本工具只做家庭投资风险体检和学习参考，不构成任何投资建议，也不提供买卖推荐。"
REPORT_DISCLAIMER = "本报告由 AI 综合生成，仅供学习参考，不构成投资建议。投资有风险，决策需谨慎。"


MARKET_INDEXES = [
    {"name": "上证指数", "code": "000001.SH", "value": "3,154.03", "change": 0.42},
    {"name": "深证成指", "code": "399001.SZ", "value": "9,681.18", "change": -0.18},
    {"name": "沪深300", "code": "000300.SH", "value": "3,673.22", "change": 0.25},
]

WATCH_ITEMS = [
    {"code": "600519", "name": "贵州茅台", "price": "1,486.20", "change": 0.86, "owner": "妈妈关注", "industry": "白酒"},
    {"code": "000001", "name": "平安银行", "price": "11.42", "change": -0.35, "owner": "爸爸关注", "industry": "银行"},
    {"code": "300750", "name": "宁德时代", "price": "196.80", "change": 1.12, "owner": "家庭共同", "industry": "电池"},
    {"code": "600036", "name": "招商银行", "price": "35.61", "change": 0.24, "owner": "家庭共同", "industry": "银行"},
]

RECENT_ITEMS = [
    {"code": "600519", "name": "贵州茅台", "time": "今天 09:42", "verdict": "稳健"},
    {"code": "300750", "name": "宁德时代", "time": "昨天 19:15", "verdict": "中性"},
    {"code": "000001", "name": "平安银行", "time": "3 天前", "verdict": "警示"},
]


st.set_page_config(page_title=APP_TITLE, layout="wide", initial_sidebar_state="collapsed")


def render_html(html: str) -> None:
    if hasattr(st, "html"):
        st.html(html)
    else:
        st.markdown(html, unsafe_allow_html=True)


def init_state() -> None:
    defaults = {
        "holding_rows": 3,
        "font_size": 14,
        "dark_mode": False,
        "fit_open": False,
        "notes": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    for idx, code in enumerate(DEFAULT_CODES):
        st.session_state.setdefault(f"code_{idx}", code)
    for idx, amount in enumerate(DEFAULT_AMOUNTS):
        st.session_state.setdefault(f"amount_{idx}", amount)


def css_vars() -> dict[str, str]:
    if st.session_state.dark_mode:
        return {
            "bg": "#1a1714",
            "bg_2": "#211d19",
            "surface": "#25211d",
            "surface_2": "#2c2823",
            "border": "#3a3530",
            "border_strong": "#514940",
            "text": "#ede5d8",
            "text_2": "#a89e8e",
            "text_3": "#6f675c",
            "accent": "#d18a73",
            "accent_soft": "#3a2923",
            "accent_2": "#7ea892",
            "accent_2_soft": "#26382f",
            "gold": "#d0b083",
            "gold_soft": "#3a3125",
            "up": "#e57878",
            "up_soft": "#432525",
            "down": "#6eb89c",
            "down_soft": "#213a30",
            "warn": "#d39a62",
            "warn_soft": "#3b2f21",
        }
    return {
        "bg": "#fbf7f2",
        "bg_2": "#f5efe6",
        "surface": "#ffffff",
        "surface_2": "#faf6ef",
        "border": "#e8dfd0",
        "border_strong": "#d4c6b0",
        "text": "#2a2520",
        "text_2": "#6b6357",
        "text_3": "#9a9085",
        "accent": "#7a3e2e",
        "accent_soft": "#f1e3db",
        "accent_2": "#3a5a4a",
        "accent_2_soft": "#e3ece7",
        "gold": "#b8956a",
        "gold_soft": "#f3e9d8",
        "up": "#c14545",
        "up_soft": "#f7e7e3",
        "down": "#2d7d5e",
        "down_soft": "#e2efe7",
        "warn": "#a05a25",
        "warn_soft": "#f5e6d2",
    }


def inject_css() -> None:
    v = css_vars()
    render_html(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Noto+Sans+SC:wght@400;500;600;700&family=Noto+Serif+SC:wght@500;600;700&display=swap');

        :root {{
            --bg: {v["bg"]};
            --bg-2: {v["bg_2"]};
            --surface: {v["surface"]};
            --surface-2: {v["surface_2"]};
            --border: {v["border"]};
            --border-strong: {v["border_strong"]};
            --text: {v["text"]};
            --text-2: {v["text_2"]};
            --text-3: {v["text_3"]};
            --accent: {v["accent"]};
            --accent-soft: {v["accent_soft"]};
            --accent-2: {v["accent_2"]};
            --accent-2-soft: {v["accent_2_soft"]};
            --gold: {v["gold"]};
            --gold-soft: {v["gold_soft"]};
            --up: {v["up"]};
            --up-soft: {v["up_soft"]};
            --down: {v["down"]};
            --down-soft: {v["down_soft"]};
            --warn: {v["warn"]};
            --warn-soft: {v["warn_soft"]};
            --font-display: "Noto Serif SC", "Source Han Serif SC", Georgia, serif;
            --font-body: "Noto Sans SC", "PingFang SC", system-ui, sans-serif;
            --font-num: "Inter", "Noto Sans SC", system-ui, sans-serif;
        }}

        html, body, [class*="css"], [data-testid="stAppViewContainer"] {{
            font-size: {st.session_state.font_size}px;
            font-family: var(--font-body);
            color: var(--text);
            background: var(--bg);
            font-feature-settings: "tnum" on, "lnum" on;
        }}
        [data-testid="stAppViewContainer"] > .main {{
            background: var(--bg);
        }}
        .main .block-container {{
            max-width: 960px;
            padding: 1.25rem 1.5rem 90px;
        }}
        header[data-testid="stHeader"], [data-testid="stToolbar"], #MainMenu, footer {{
            visibility: hidden;
            height: 0;
        }}
        h1, h2, h3 {{
            font-family: var(--font-display);
            color: var(--text);
            letter-spacing: -0.01em;
            line-height: 1.28;
        }}
        p, li, label, .stMarkdown {{
            color: var(--text);
            line-height: 1.7;
            text-wrap: pretty;
        }}
        a {{
            color: var(--accent);
        }}
        .stButton button, .stDownloadButton button, .stFormSubmitButton button {{
            min-height: 2.2rem;
            border-radius: 999px;
            border: 1px solid var(--border-strong);
            background: var(--surface);
            color: var(--accent);
            font-weight: 600;
            font-size: 0.88rem;
            font-family: var(--font-body);
            box-shadow: none;
            transition: all 160ms ease;
        }}
        .stButton button:hover, .stDownloadButton button:hover, .stFormSubmitButton button:hover {{
            border-color: var(--accent);
            color: var(--accent);
            transform: translateY(-1px);
        }}
        .stFormSubmitButton button {{
            background: var(--accent);
            color: #fff;
            border-color: var(--accent);
        }}
        .stFormSubmitButton button:hover {{
            color: #fff;
            background: var(--accent);
        }}
        div[data-testid="stTextInput"] input,
        div[data-testid="stNumberInput"] input,
        div[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
        textarea {{
            background: var(--bg-2) !important;
            color: var(--text) !important;
            border: 1px solid var(--border) !important;
            border-radius: 14px !important;
            min-height: 3rem;
            font-size: 1rem !important;
        }}
        div[data-testid="stTextInput"] input:focus,
        div[data-testid="stNumberInput"] input:focus,
        textarea:focus {{
            border-color: var(--accent) !important;
            box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 15%, transparent) !important;
        }}
        [data-testid="stExpander"] {{
            border: 1px solid var(--border);
            border-radius: 14px;
            background: var(--surface);
            overflow: hidden;
        }}
        [data-testid="stExpander"] details summary {{
            color: var(--text);
            font-family: var(--font-display);
            font-weight: 600;
        }}
        div[data-testid="stMetric"] {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 1.1rem;
        }}
        div[data-testid="stMetricLabel"] p {{
            color: var(--text-2);
            font-size: 0.86rem;
        }}
        div[data-testid="stMetricValue"] {{
            color: var(--accent);
            font-family: var(--font-num);
            font-size: 1.55rem;
        }}
        [data-testid="stDataFrame"] {{
            border: 1px solid var(--border);
            border-radius: 14px;
            overflow: hidden;
        }}

        .site-header {{
            position: sticky;
            top: 0;
            z-index: 20;
            margin: -1.25rem -2rem 2rem;
            padding: 0.8rem 2rem;
            display: grid;
            grid-template-columns: 1fr auto 1fr;
            gap: 1rem;
            align-items: center;
            background: color-mix(in srgb, var(--bg) 92%, transparent);
            border-bottom: 1px solid var(--border);
            backdrop-filter: blur(12px);
        }}
        .brand {{
            display: flex;
            align-items: center;
            gap: 0.7rem;
        }}
        .brand-mark {{
            width: 28px;
            height: 28px;
            border-radius: 9px;
            display: grid;
            place-items: center;
            color: #fff;
            background: var(--accent);
            font-family: var(--font-display);
            font-weight: 700;
        }}
        .brand-cn {{
            font-family: var(--font-display);
            font-weight: 700;
            color: var(--text);
            line-height: 1.05;
        }}
        .brand-en {{
            font-size: 0.72rem;
            color: var(--text-3);
            font-family: var(--font-num);
            line-height: 1.1;
        }}
        .site-nav {{
            display: flex;
            align-items: center;
            gap: 1.7rem;
            justify-content: center;
            color: var(--text-2);
            font-size: 0.92rem;
        }}
        .site-nav span:first-child {{
            color: var(--accent);
            border-bottom: 2px solid var(--accent);
            padding-bottom: 0.35rem;
        }}
        .family-chip {{
            justify-self: end;
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            border: 1px solid var(--border);
            border-radius: 999px;
            background: var(--surface);
            padding: 0.38rem 0.65rem 0.38rem 0.42rem;
            color: var(--text-2);
            font-size: 0.86rem;
            white-space: nowrap;
        }}
        .family-avatar {{
            width: 1.7rem;
            height: 1.7rem;
            border-radius: 999px;
            display: grid;
            place-items: center;
            color: var(--accent);
            background: var(--accent-soft);
            font-weight: 700;
        }}

        .settings-strip {{
            display: flex;
            justify-content: flex-end;
            align-items: center;
            gap: 0.65rem;
            margin: -0.8rem 0 1.2rem;
            color: var(--text-2);
            font-size: 0.85rem;
        }}
        .settings-strip .pill {{
            border: 1px solid var(--border);
            background: var(--surface);
            border-radius: 999px;
            padding: 0.28rem 0.65rem;
            color: var(--text-2);
        }}

        .hero-grid {{
            display: grid;
            grid-template-columns: 1.65fr 1fr;
            gap: 1.5rem;
            align-items: stretch;
            margin-bottom: 2.5rem;
        }}
        .card, .hero-card, .market-card, .guide-block, .list-shell, .stock-head, .verdict-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 14px;
            box-shadow: 0 14px 35px rgba(42, 37, 32, 0.04);
        }}
        .hero-card {{
            padding: 2.2rem;
        }}
        .eyebrow {{
            display: inline-flex;
            width: fit-content;
            border-radius: 999px;
            background: var(--accent-soft);
            color: var(--accent);
            padding: 0.42rem 0.8rem;
            font-size: 0.82rem;
            font-weight: 700;
        }}
        .hero-title {{
            margin: 0.6rem 0 0.65rem;
            font-family: var(--font-display);
            font-size: 1.5rem;
            font-weight: 600;
            line-height: 1.28;
            color: var(--text);
            letter-spacing: -0.01em;
        }}
        .hero-subtitle {{
            color: var(--text-2);
            max-width: 47rem;
            font-size: 1.02rem;
            margin-bottom: 1.5rem;
        }}
        .search-shell {{
            border: 1px solid var(--border);
            border-radius: 999px;
            background: var(--bg-2);
            padding: 0.45rem;
            margin: 0.25rem 0 1rem;
        }}
        .search-shell:focus-within {{
            border-color: var(--accent);
            background: var(--surface);
        }}
        .quick-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.55rem;
            align-items: center;
            color: var(--text-2);
            font-size: 0.9rem;
        }}
        .chip {{
            display: inline-flex;
            gap: 0.35rem;
            align-items: center;
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 0.4rem 0.75rem;
            color: var(--text);
            background: var(--surface);
            font-weight: 700;
        }}
        .chip small {{
            color: var(--text-3);
            font-family: var(--font-num);
            font-weight: 500;
        }}
        .market-card {{
            padding: 1.5rem;
        }}
        .market-title {{
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            margin-bottom: 0.65rem;
        }}
        .market-title h3 {{
            margin: 0;
            font-size: 1.2rem;
        }}
        .market-row {{
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            padding: 1rem 0;
            border-bottom: 1px dashed var(--border);
        }}
        .market-row:last-of-type {{
            border-bottom: 0;
        }}
        .market-name {{
            color: var(--text);
            font-weight: 700;
        }}
        .market-code, .muted {{
            color: var(--text-3);
            font-size: 0.84rem;
        }}
        .market-value {{
            font-family: var(--font-num);
            color: var(--text);
            font-weight: 700;
            text-align: right;
        }}
        .up {{ color: var(--up); }}
        .down {{ color: var(--down); }}
        .flat {{ color: var(--text-2); }}
        .delay {{
            display: flex;
            align-items: center;
            gap: 0.45rem;
            color: var(--text-3);
            font-size: 0.84rem;
            padding-top: 0.6rem;
        }}
        .delay-dot {{
            width: 0.45rem;
            height: 0.45rem;
            border-radius: 999px;
            background: var(--accent-2);
        }}

        .block {{
            margin: 2.8rem 0;
        }}
        .block-head {{
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            align-items: end;
            margin-bottom: 1.1rem;
        }}
        .block-title {{
            font-family: var(--font-display);
            font-size: 1.55rem;
            font-weight: 600;
            color: var(--text);
            margin: 0;
        }}
        .block-subtitle {{
            color: var(--text-2);
            margin: 0.25rem 0 0;
        }}
        .ghost-btn {{
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 0.5rem 0.85rem;
            color: var(--accent);
            background: var(--surface);
            font-weight: 700;
            white-space: nowrap;
        }}
        .watch-grid, .metric-grid, .risk-grid, .news-grid {{
            display: grid;
            gap: 1.5rem;
        }}
        .watch-grid {{
            grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
        }}
        .watch-card {{
            border: 1px solid var(--border);
            border-radius: 14px;
            background: var(--surface);
            padding: 0.9rem 1.1rem;
            transition: all 160ms ease;
        }}
        .watch-card:hover {{
            border-color: var(--accent);
            transform: translateY(-1px);
        }}
        .watch-top, .price-line, .risk-card-head, .note-head {{
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            align-items: start;
        }}
        .watch-name {{
            font-family: var(--font-display);
            font-size: 1.2rem;
            font-weight: 700;
            color: var(--text);
        }}
        .owner-pill, .verdict-pill, .tag {{
            display: inline-flex;
            align-items: center;
            width: fit-content;
            border-radius: 999px;
            font-size: 0.78rem;
            padding: 0.28rem 0.6rem;
            font-weight: 700;
            white-space: nowrap;
        }}
        .owner-pill {{
            color: var(--gold);
            background: var(--gold-soft);
        }}
        .price-line {{
            margin: 1.2rem 0 0.9rem;
            align-items: baseline;
        }}
        .big-number {{
            font-family: var(--font-num);
            font-size: 1.65rem;
            font-weight: 700;
            color: var(--text);
        }}
        .change-text {{
            font-family: var(--font-num);
            font-weight: 700;
        }}
        .watch-link {{
            border-top: 1px dashed var(--border);
            padding-top: 0.9rem;
            color: var(--accent);
            font-weight: 700;
            font-size: 0.9rem;
        }}
        .list-shell {{
            overflow: hidden;
        }}
        .recent-row {{
            display: grid;
            grid-template-columns: 1fr auto auto;
            gap: 1rem;
            align-items: center;
            padding: 1rem 1.25rem;
            border-bottom: 1px solid var(--border);
        }}
        .recent-row:last-child {{
            border-bottom: 0;
        }}
        .recent-row:hover {{
            background: var(--surface-2);
        }}
        .verdict-pill {{
            color: var(--accent-2);
            background: var(--accent-2-soft);
        }}
        .guide-block {{
            background: var(--surface-2);
            padding: 2.2rem;
        }}
        .guide-list {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1.4rem;
        }}
        .guide-step {{
            display: grid;
            grid-template-columns: auto 1fr;
            gap: 0.9rem;
        }}
        .step-num {{
            width: 2.2rem;
            height: 2.2rem;
            border-radius: 999px;
            border: 1px solid var(--border-strong);
            background: var(--surface);
            color: var(--accent);
            display: grid;
            place-items: center;
            font-family: var(--font-num);
            font-weight: 800;
        }}
        .step-title {{
            color: var(--text);
            font-weight: 800;
            margin-bottom: 0.2rem;
        }}
        .guide-foot, .page-foot {{
            margin-top: 1.6rem;
            padding-top: 1rem;
            border-top: 1px dashed var(--border);
            color: var(--text-2);
            font-size: 0.9rem;
        }}

        .breadcrumb {{
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            align-items: center;
            color: var(--text-2);
            font-size: 0.88rem;
            margin-bottom: 1.1rem;
        }}
        .crumb-link {{
            color: var(--accent);
            font-weight: 700;
        }}
        .stock-head {{
            display: grid;
            grid-template-columns: 1.5fr 1fr;
            gap: 1.6rem;
            padding: 2.2rem;
            margin-bottom: 2.4rem;
        }}
        .tag-row {{
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
        }}
        .tag-code {{
            background: var(--accent-soft);
            color: var(--accent);
        }}
        .tag-exchange {{
            background: var(--accent-2-soft);
            color: var(--accent-2);
        }}
        .tag-industry {{
            background: var(--bg-2);
            color: var(--text-2);
        }}
        .stock-title {{
            margin: 0.6rem 0 0.2rem;
            font-family: var(--font-display);
            font-size: 1.7rem;
            font-weight: 600;
        }}
        .basic-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1rem;
            border-top: 1px solid var(--border);
            margin-top: 1.4rem;
            padding-top: 1.2rem;
        }}
        .kv dt {{
            color: var(--text-2);
            font-size: 0.84rem;
            margin-bottom: 0.28rem;
        }}
        .kv dd {{
            margin: 0;
            color: var(--text);
            font-family: var(--font-num);
            font-weight: 700;
            font-size: 1.35rem;
        }}
        .spark-card {{
            height: 100%;
            min-height: 245px;
            border-radius: 14px;
            background: var(--bg-2);
            padding: 1.2rem;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }}
        .spark-svg {{
            width: 100%;
            height: 120px;
            margin: 1rem 0;
        }}

        .verdict-card {{
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 1.5rem;
            align-items: center;
            padding: 1.7rem;
            background: linear-gradient(180deg, var(--accent-soft), var(--surface) 70%);
            margin-bottom: 1rem;
        }}
        .kicker {{
            color: var(--accent);
            font-size: 0.75rem;
            font-weight: 800;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }}
        .verdict-title {{
            font-family: var(--font-display);
            font-size: 1.85rem;
            font-weight: 700;
            margin: 0.3rem 0;
        }}
        .score-dial {{
            width: 104px;
            text-align: center;
        }}
        .score-caption {{
            color: var(--text-2);
            font-size: 0.84rem;
            margin-top: 0.2rem;
        }}
        .ai-detail-note {{
            border: 1px solid var(--border);
            border-radius: 14px;
            background: var(--surface);
            padding: 1rem 1.2rem;
            margin: 0.75rem 0;
        }}
        .tone-accent {{
            border-left: 3px solid var(--accent);
        }}
        .tone-warn {{
            border-left: 3px solid var(--warn);
        }}
        .tone-neutral {{
            border-left: 3px solid var(--accent-2);
        }}
        .bullet-list {{
            margin: 0.4rem 0 0;
            padding-left: 1.2rem;
        }}
        .bullet-list li::marker {{
            color: var(--accent);
        }}
        .metric-grid {{
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        }}
        .metric-card {{
            border: 1px solid var(--border);
            border-radius: 14px;
            background: var(--surface);
            padding: 1.6rem;
        }}
        .metric-label {{
            color: var(--text-2);
            font-size: 0.92rem;
        }}
        .metric-value {{
            color: var(--text);
            font-family: var(--font-num);
            font-size: 1.85rem;
            font-weight: 700;
            margin: 0.45rem 0;
        }}
        .metric-note {{
            color: var(--text-3);
            font-size: 0.85rem;
        }}
        .risk-grid {{
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        }}
        .risk-card-new {{
            border: 1px solid var(--border);
            border-left-width: 4px;
            border-radius: 14px;
            background: var(--surface);
            padding: 1.25rem;
        }}
        .r-hi {{
            border-left-color: var(--up);
        }}
        .r-mid {{
            border-left-color: var(--gold);
        }}
        .r-lo {{
            border-left-color: var(--accent-2);
        }}
        .risk-title-pill {{
            border-radius: 999px;
            background: var(--bg-2);
            color: var(--text);
            padding: 0.28rem 0.55rem;
            font-weight: 700;
            font-size: 0.82rem;
        }}
        .news-grid {{
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
        }}
        .news-card, .note-card {{
            border: 1px solid var(--border);
            border-radius: 14px;
            background: var(--surface);
            padding: 1.1rem;
        }}
        .note-avatar {{
            width: 2rem;
            height: 2rem;
            border-radius: 999px;
            display: grid;
            place-items: center;
            color: var(--accent);
            background: var(--accent-soft);
            font-weight: 800;
        }}
        .allocation-bar {{
            height: 0.8rem;
            border-radius: 999px;
            overflow: hidden;
            background: var(--bg-2);
            display: flex;
            border: 1px solid var(--border);
        }}
        .allocation-cash {{
            background: var(--accent-2);
        }}
        .allocation-stock {{
            background: var(--gold);
        }}
        .page-foot {{
            text-align: center;
            border-top-style: solid;
        }}

        @media (max-width: 1000px) {{
            .site-header {{
                grid-template-columns: 1fr auto;
            }}
            .site-nav {{
                display: none;
            }}
            .hero-grid, .stock-head {{
                grid-template-columns: 1fr;
            }}
            .basic-grid {{
                grid-template-columns: repeat(2, 1fr);
            }}
            .guide-list {{
                grid-template-columns: 1fr;
            }}
        }}
        @media (max-width: 640px) {{
            .main .block-container {{
                padding: 1rem 0.85rem 90px;
            }}
            .site-header {{
                margin-left: -0.85rem;
                margin-right: -0.85rem;
                padding-left: 0.85rem;
                padding-right: 0.85rem;
            }}
            .family-chip {{
                display: none;
            }}
            .hero-card, .stock-head, .guide-block {{
                padding: 1.45rem;
            }}
            .hero-title, .stock-title {{
                font-size: 1.25rem;
            }}
            .block-head, .breadcrumb, .watch-top, .price-line {{
                align-items: start;
                flex-direction: column;
            }}
            .basic-grid {{
                grid-template-columns: 1fr;
            }}
            .recent-row {{
                grid-template-columns: 1fr auto;
            }}
            .recent-row .recent-time {{
                display: none;
            }}
            .verdict-card {{
                grid-template-columns: 1fr;
            }}
        }}
        </style>
        """
    )


def html_escape(value: Any) -> str:
    return escape(str(value if value is not None else ""))


def init_controls() -> None:
    _, c1, c2, c3 = st.columns([8, 1, 1, 1])
    if c1.button("A-", use_container_width=True):
        st.session_state.font_size = max(14, int(st.session_state.font_size) - 1)
        st.rerun()
    if c2.button("A+", use_container_width=True):
        st.session_state.font_size = min(22, int(st.session_state.font_size) + 1)
        st.rerun()
    label = "浅色" if st.session_state.dark_mode else "暗色"
    if c3.button(label, use_container_width=True):
        st.session_state.dark_mode = not st.session_state.dark_mode
        st.rerun()


def site_header() -> None:
    brand_col, c1, c2, c3 = st.columns([7, 0.7, 0.7, 0.7])
    with brand_col:
        render_html(
            """
            <div class="brand" style="padding: 0.35rem 0 0.15rem;">
                <div class="brand-mark">家</div>
                <div>
                    <div class="brand-cn">家庭投资助手</div>
                    <div class="brand-en">Family Investment Agent</div>
                </div>
            </div>
            """
        )
    if c1.button("A−", use_container_width=True, help="缩小字号"):
        st.session_state.font_size = max(14, int(st.session_state.font_size) - 1)
        st.rerun()
    if c2.button("A＋", use_container_width=True, help="放大字号"):
        st.session_state.font_size = min(22, int(st.session_state.font_size) + 1)
        st.rerun()
    theme_label = "☀" if st.session_state.dark_mode else "☾"
    if c3.button(theme_label, use_container_width=True, help="切换深色/浅色"):
        st.session_state.dark_mode = not st.session_state.dark_mode
        st.rerun()


def signed_change(value: float) -> str:
    arrow = "▲" if value >= 0 else "▼"
    return f"{arrow} {abs(value):.2f}%"


def change_class(value: float | None) -> str:
    if value is None:
        return "flat"
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"


def market_aside() -> None:
    rows = []
    for item in MARKET_INDEXES:
        cls = change_class(float(item["change"]))
        rows.append(
            f"""
            <div class="market-row">
                <div>
                    <div class="market-name">{html_escape(item["name"])}</div>
                    <div class="market-code">{html_escape(item["code"])}</div>
                </div>
                <div>
                    <div class="market-value">{html_escape(item["value"])}</div>
                    <div class="change-text {cls}">{signed_change(float(item["change"]))}</div>
                </div>
            </div>
            """
        )
    render_html(
        f"""
        <aside class="market-card">
            <div class="market-title">
                <h3>今日大盘</h3>
                <span class="muted">A 股</span>
            </div>
            {''.join(rows)}
            <div class="delay"><span class="delay-dot"></span>行情延迟 15 分钟 · 仅供参考</div>
        </aside>
        """
    )


def set_first_code(code: str) -> None:
    st.session_state["pending_code"] = normalize_code(code)


def home_hero() -> None:
    render_html(
        """
        <div class="hero-card" style="padding: 1.3rem 1.3rem 0.6rem; margin-bottom: 0.5rem;">
            <div class="eyebrow">家庭投资风险体检工具</div>
            <h1 class="hero-title">输入持仓，看清风险。</h1>
            <p class="hero-subtitle">帮助家人看清这只标的的风险、数据是否完整，以及是否需要继续观察。不预测涨跌，不构成买卖建议。</p>
        </div>
        """
    )
    portfolio_form()


def portfolio_form() -> None:
    pending_code = st.session_state.pop("pending_code", "")
    if pending_code:
        st.session_state["code_0"] = pending_code
        if float(st.session_state.get("amount_0", 0) or 0) <= 0:
            st.session_state["amount_0"] = 20000.0

    st.markdown('<div class="search-shell">', unsafe_allow_html=True)
    with st.form("family_risk_form"):
        code_col, amount_col = st.columns([1.4, 1])
        with code_col:
            first_code = st.text_input(
                "股票/基金代码",
                key="code_0",
                placeholder="例如：600519、贵州茅台、招商银行",
            )
        with amount_col:
            first_amount = st.number_input(
                "持仓金额（元）",
                min_value=0.0,
                step=1000.0,
                key="amount_0",
            )

        cash_col, risk_col = st.columns([1, 1])
        with cash_col:
            cash = st.number_input("家庭可用于投资的现金金额（元）", min_value=0.0, value=50000.0, step=1000.0)
        with risk_col:
            risk_profile = st.selectbox("家庭风险承受能力", ["稳健", "平衡", "积极"], index=1)

        with st.expander("添加更多持仓", expanded=False):
            st.markdown('<p class="muted">默认先分析第一只标的，也可以继续加入家庭账户里已有的其他持仓。</p>', unsafe_allow_html=True)
            raw_more: list[dict[str, float | str]] = []
            for index in range(1, st.session_state.holding_rows):
                cols = st.columns([1.4, 1])
                code = cols[0].text_input(
                    f"第 {index + 1} 只股票/基金代码",
                    key=f"code_{index}",
                    placeholder="例如 000001",
                )
                amount = cols[1].number_input(
                    f"第 {index + 1} 只持仓金额（元）",
                    min_value=0.0,
                    step=1000.0,
                    key=f"amount_{index}",
                )
                raw_more.append({"code": code, "amount": amount})

        submitted = st.form_submit_button("一键智能体检", use_container_width=True)

    if st.button("增加一行持仓", use_container_width=True):
        st.session_state.holding_rows += 1
        st.rerun()

    if submitted:
        raw_rows: list[dict[str, float | str]] = [{"code": first_code, "amount": first_amount}]
        for idx in range(1, st.session_state.holding_rows):
            raw_rows.append(
                {
                    "code": st.session_state.get(f"code_{idx}", ""),
                    "amount": st.session_state.get(f"amount_{idx}", 0.0),
                }
            )
        run_analysis(cash, risk_profile, raw_rows)
    st.markdown("</div>", unsafe_allow_html=True)


def clean_holdings(raw_rows: list[dict[str, float | str]]) -> list[dict[str, float | str]]:
    holdings: list[dict[str, float | str]] = []
    for row in raw_rows:
        code = normalize_code(str(row.get("code", "")))
        amount = float(row.get("amount", 0) or 0)
        if code and amount > 0:
            holdings.append({"code": code, "amount": amount})
    return holdings


def loading_card(code: str) -> None:
    render_html(
        f"""
        <div class="card" style="padding: 2.2rem; margin: 1rem 0;">
            <div class="kicker">Generating report</div>
            <h3 style="margin: .35rem 0;">正在生成 {html_escape(code)} 的分析报告…</h3>
            <p class="muted">✓ 获取公司基础信息<br>✓ 拉取最近财报数据<br>○ AI 综合分析中<br>○ 整理风险提示</p>
        </div>
        """
    )


def run_analysis(cash: float, risk_profile: str, raw_rows: list[dict[str, float | str]]) -> None:
    holdings = clean_holdings(raw_rows)
    if not holdings:
        st.error("请至少填写一只持仓，并填写大于 0 的持仓金额。")
        st.stop()

    try:
        codes = [str(item["code"]) for item in holdings]
        loading_card(codes[0])
        with st.spinner("正在查数据并做家庭长期持有视角分析..."):
            stocks, fetch_warnings = get_stock_metrics(codes)
            analysis = analyze_portfolio(cash, risk_profile, holdings, stocks)
        st.session_state["analysis"] = analysis
        st.session_state["stocks"] = stocks
        st.session_state["holdings"] = holdings
        st.session_state["fetch_warnings"] = fetch_warnings
        st.session_state.pop("ai_report", None)
        st.session_state.pop("ai_report_failed", None)
        st.rerun()
    except Exception:  # noqa: BLE001
        st.error("体检时遇到问题，但页面没有崩。请稍后重试，或检查 stock_metrics.csv 是否存在。")
        st.stop()


def watchlist_block() -> None:
    cards = []
    for item in WATCH_ITEMS:
        cls = change_class(float(item["change"]))
        cards.append(
            f"""
            <article class="watch-card">
                <div class="watch-top">
                    <div>
                        <div class="watch-name">{html_escape(item["name"])}</div>
                        <div class="muted">{html_escape(item["code"])} · {html_escape(item["industry"])}</div>
                    </div>
                    <div class="owner-pill">{html_escape(item["owner"])}</div>
                </div>
                <div class="price-line">
                    <div class="big-number">{html_escape(item["price"])}</div>
                    <div class="change-text {cls}">{signed_change(float(item["change"]))}</div>
                </div>
            </article>
            """
        )
    render_html(
        f"""
        <section class="block">
            <div class="block-head">
                <div>
                    <h2 class="block-title">我的关注列表</h2>
                    <p class="block-subtitle">常看的公司放在一起，快速触发分析。接入云数据库后可多人共享。</p>
                </div>
                <div class="ghost-btn">＋ 添加关注</div>
            </div>
            <div class="watch-grid">{''.join(cards)}</div>
        </section>
        """
    )
    cols = st.columns(len(WATCH_ITEMS))
    for idx, item in enumerate(WATCH_ITEMS):
        if cols[idx].button(f"分析 {item['name']}", key=f"watch_{item['code']}", use_container_width=True):
            set_first_code(item["code"])
            st.rerun()


def recent_block() -> None:
    rows = []
    for item in RECENT_ITEMS:
        rows.append(
            f"""
            <div class="recent-row">
                <div>
                    <strong>{html_escape(item["name"])}</strong>
                    <div class="muted">{html_escape(item["code"])}</div>
                </div>
                <div class="muted recent-time">{html_escape(item["time"])}</div>
                <div><span class="verdict-pill">{html_escape(item["verdict"])}</span> <span class="muted">→</span></div>
            </div>
            """
        )
    render_html(
        f"""
        <section class="block">
            <div class="block-head">
                <div>
                    <h2 class="block-title">最近分析过的股票</h2>
                    <p class="block-subtitle">保留最近看过的公司，方便家人继续接着聊。</p>
                </div>
            </div>
            <div class="list-shell">{''.join(rows)}</div>
        </section>
        """
    )


def guide_block() -> None:
    render_html(
        f"""
        <section class="block guide-block">
            <div class="block-head">
                <div>
                    <h2 class="block-title">第一次使用？三步看懂</h2>
                    <p class="block-subtitle">不用懂复杂行情软件，也能先把家庭账户风险讲清楚。</p>
                </div>
            </div>
            <div class="guide-list">
                <div class="guide-step">
                    <div class="step-num">1</div>
                    <div><div class="step-title">输入想了解的股票</div><div class="muted">直接输入股票或基金代码（如 600519），填入持仓金额和家庭现金，点击一键智能体检。</div></div>
                </div>
                <div class="guide-step">
                    <div class="step-num">2</div>
                    <div><div class="step-title">查看体检结果</div><div class="muted">报告给出综合评分和风险等级；下方展开风险提示、财务数据、持仓明细。</div></div>
                </div>
                <div class="guide-step">
                    <div class="step-num">3</div>
                    <div><div class="step-title">和家人一起讨论</div><div class="muted">在分析页底部的"家庭讨论"中留言，家人都能看到，方便共同决策。</div></div>
                </div>
            </div>
            <div class="guide-foot">{HOME_DISCLAIMER}</div>
        </section>
        """
    )


def cache_tools() -> None:
    with st.expander("高级选项：数据缓存工具", expanded=False):
        try:
            summary = get_cache_summary()
            st.info(summary.get("message", "缓存状态未知"))
        except Exception:  # noqa: BLE001
            summary = {"count": 0, "latest_update": "未知", "finance_count": 0}
            st.info("缓存状态暂时无法读取，不影响风险体检。")
        st.caption(
            f"当前本地缓存约 {summary.get('count', 0)} 只标的，其中 {summary.get('finance_count', 0)} 只有财务数据；"
            f"最近更新时间：{summary.get('latest_update', '未知')}。"
        )
        st.caption("页面默认读取 stock_metrics.csv，本地和云端都更稳定。下面的按钮会尝试联网更新，接口可能失败。")
        cache_col1, cache_col2 = st.columns(2)
        if cache_col1.button("更新全部 A 股行情缓存", use_container_width=True):
            with st.spinner("正在拉取全部 A 股行情，可能需要几十秒..."):
                update_summary, messages = refresh_market_cache()
            for message in messages:
                st.info(message)
            st.success(f"缓存现有 {update_summary.get('count', 0)} 只标的。")

        current_input_codes = []
        for idx in range(st.session_state.holding_rows):
            normalized_code = normalize_code(str(st.session_state.get(f"code_{idx}", "")))
            if normalized_code:
                current_input_codes.append(normalized_code)

        if cache_col2.button("手动更新当前持仓数据", use_container_width=True):
            with st.spinner("正在尝试更新当前填写代码的行情数据..."):
                update_summary, messages = refresh_current_holdings_cache(current_input_codes)
            for message in messages:
                st.info(message)
            st.success(
                f"缓存现有 {update_summary.get('count', 0)} 只标的，"
                f"{update_summary.get('finance_count', 0)} 只有财务数据。"
            )


def home_page() -> None:
    home_hero()
    cache_tools()
    guide_block()
    with st.expander("开发中功能（暂未接入实时数据 / 云数据库，后续开放）", expanded=False):
        st.info("以下功能正在开发中，当前展示为静态演示数据，不代表真实行情或真实账户。")
        st.markdown("#### 今日大盘")
        market_aside()
        st.markdown("---")
        watchlist_block()
        st.markdown("---")
        recent_block()


def to_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
    except Exception:
        if value is None:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fmt_optional(value: Any, suffix: str = "", default: str = "暂无") -> str:
    number = to_float(value)
    if number is None:
        return default
    if abs(number) >= 10000:
        return f"{number:,.0f}{suffix}"
    if abs(number) >= 100:
        return f"{number:,.1f}{suffix}"
    return f"{number:.2f}{suffix}"


def fmt_market_cap(value: Any) -> str:
    number = to_float(value)
    if number is None:
        return "暂无"
    return f"{number / 100000000:.1f} 亿"


def exchange_name(code: str) -> str:
    if code.startswith(("600", "601", "603", "605", "688", "689")):
        return "上海证券交易所"
    if code.startswith(("000", "001", "002", "003", "300", "301")):
        return "深圳证券交易所"
    if code.startswith(("8", "4")):
        return "北京证券交易所"
    return "交易所待确认"


def first_stock() -> dict[str, Any]:
    stocks = st.session_state.get("stocks", [])
    if stocks:
        return stocks[0]
    return {}


def spark_svg(change: float | None, score: int) -> str:
    base = 54
    points = []
    for idx in range(12):
        direction = 1 if (change or 0) >= 0 else -1
        wobble = ((idx * 7 + score) % 13) - 6
        y = base - direction * idx * 2.3 + wobble * 0.9
        x = 8 + idx * 20
        points.append((x, max(18, min(94, y))))
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area = f"8,108 {line} 228,108"
    cls = "var(--up)" if (change or 0) >= 0 else "var(--down)"
    return f"""
    <svg class="spark-svg" viewBox="0 0 236 120" role="img" aria-label="近 30 日走势">
        <polygon points="{area}" fill="{cls}" opacity="0.10"></polygon>
        <polyline points="{line}" fill="none" stroke="{cls}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></polyline>
    </svg>
    """


def score_dial(score: int) -> str:
    radius = 42
    circumference = 2 * pi * radius
    offset = circumference * (1 - score / 100)
    return f"""
    <div class="score-dial">
        <svg width="104" height="104" viewBox="0 0 104 104" aria-label="综合评分 {score}/100">
            <circle cx="52" cy="52" r="{radius}" stroke="var(--border)" stroke-width="9" fill="none"></circle>
            <circle cx="52" cy="52" r="{radius}" stroke="var(--accent)" stroke-width="9" fill="none"
                    stroke-linecap="round" transform="rotate(-90 52 52)"
                    stroke-dasharray="{circumference:.2f}" stroke-dashoffset="{offset:.2f}"></circle>
            <text x="52" y="50" text-anchor="middle" font-size="25" font-weight="700" fill="var(--text)" font-family="var(--font-num)">{score}</text>
            <text x="52" y="71" text-anchor="middle" font-size="13" fill="var(--text-3)" font-family="var(--font-num)">/100</text>
        </svg>
        <div class="score-caption">综合评分</div>
    </div>
    """


def verdict_headline(score: int) -> str:
    if score >= 80:
        return "稳健 · 适合长期观察"
    if score >= 60:
        return "中性 · 需观察"
    if score >= 45:
        return "谨慎 · 不建议作为家庭主仓"
    return "不适合 · 风险与家庭账户不匹配"


def stock_header(analysis: dict[str, Any]) -> None:
    stock = first_stock()
    first_result = analysis["stock_results"][0]
    code = first_result["code"]
    name = first_result["name"]
    industry = first_result.get("industry") or stock.get("所属行业") or "行业待补充"
    change = to_float(stock.get("涨跌幅"))
    change_amount = to_float(stock.get("最新收盘价"))
    price = fmt_optional(stock.get("最新收盘价"))
    change_label = "暂无" if change is None else signed_change(change)
    change_cls = change_class(change)
    render_html(
        f"""
        <div class="breadcrumb">
            <div><span class="crumb-link">← 返回首页</span> <span class="muted">/</span> <strong>分析报告</strong></div>
            <div class="muted">报告生成于 {html_escape(analysis["analysis_time"])} · 数据延迟约 15 分钟</div>
        </div>
        <section class="stock-head">
            <div>
                <div class="tag-row">
                    <span class="tag tag-code">{html_escape(code)}</span>
                    <span class="tag tag-exchange">{html_escape(exchange_name(code))}</span>
                    <span class="tag tag-industry">{html_escape(industry)}</span>
                </div>
                <h1 class="stock-title">{html_escape(name)}</h1>
                <div class="muted">{html_escape(name)} · 上市日期待补充</div>
                <dl class="basic-grid">
                    <div class="kv"><dt>当前股价</dt><dd>{price}</dd></div>
                    <div class="kv"><dt>今日变动</dt><dd class="{change_cls}">{change_label}</dd></div>
                    <div class="kv"><dt>总市值</dt><dd>{fmt_market_cap(stock.get("总市值"))}</dd></div>
                    <div class="kv"><dt>市盈率 PE</dt><dd>{fmt_optional(stock.get("市盈率-动态"))}</dd></div>
                    <div class="kv"><dt>市净率 PB</dt><dd>{fmt_optional(stock.get("市净率"))}</dd></div>
                    <div class="kv"><dt>股息率</dt><dd>暂无</dd></div>
                </dl>
            </div>
            <div class="spark-card">
                <div>
                    <div class="kicker">近 30 日走势</div>
                    {spark_svg(change, int(analysis["score"]))}
                </div>
                <div class="muted">30 日走势仅作视觉提示 · 1 年数据待后端补充</div>
            </div>
        </section>
        """
    )


def ai_report_block(analysis: dict[str, Any]) -> None:
    score = int(analysis["score"])
    headline = verdict_headline(score)
    summary = analysis["advice"][0]
    pros = [
        f"家庭仓位安全得分 {analysis['module_scores']['家庭仓位安全']:.0f}/100，可作为讨论的第一层参考。",
        f"风险承受匹配得分 {analysis['module_scores']['风险承受匹配']:.0f}/100，用来衡量这笔钱是否放得舒服。",
        "报告重点看现金、仓位、公司底子和短期交易热度，不鼓励追逐短线涨跌。",
    ]
    risks = analysis["risk_notes"][:4] or ["当前没有明显刺眼的问题，但仍建议定期复盘。"]
    render_html(
        f"""
        <section class="block ai-report">
            <div class="block-head">
                <div>
                    <h2 class="block-title">综合体检结论</h2>
                    <p class="block-subtitle">根据缓存数据自动评分 · 无需 AI 接口 · 不构成买卖建议</p>
                </div>
                <div class="muted">报告版本 v2026-05-17</div>
            </div>
            <div class="verdict-card">
                <div>
                    <div class="kicker">综合判断</div>
                    <div class="verdict-title">{html_escape(headline)}</div>
                    <p class="muted">{html_escape(summary)}</p>
                </div>
                {score_dial(score)}
            </div>
            <div class="ai-detail-note tone-accent">
                <strong>为什么说"适合长期"——优势</strong>
                <ul class="bullet-list">{''.join(f'<li>{html_escape(item)}</li>' for item in pros)}</ul>
            </div>
            <div class="ai-detail-note tone-warn">
                <strong>需要留意的风险</strong>
                <ul class="bullet-list">{''.join(f'<li>{html_escape(item)}</li>' for item in risks)}</ul>
            </div>
        </section>
        """
    )
    with st.expander('适合 / 不适合放进哪种账户', expanded=bool(st.session_state.fit_open)):
        fit_col, not_fit_col = st.columns(2)
        fit_col.markdown(
            """
            **适合**
            - 家庭已经有足够现金备用金
            - 愿意按季度或半年复盘
            - 能接受短期波动，不把它当作急用钱
            """
        )
        not_fit_col.markdown(
            """
            **不适合**
            - 未来 6 个月有大额刚性支出
            - 单只持仓已经占家庭资金过高
            - 只因为短期上涨而临时冲动
            """
        )


def metric_grid(analysis: dict[str, Any]) -> None:
    stock = first_stock()
    metrics = [
        ("PE", fmt_optional(stock.get("市盈率-动态")), "估值指标，越高越需要解释增长来源"),
        ("PB", fmt_optional(stock.get("市净率")), "股价相对账面资产的倍数"),
        ("ROE", fmt_optional((to_float(stock.get("ROE")) or 0) * 100, "%") if to_float(stock.get("ROE")) is not None else "暂无", "公司用自己的钱赚钱的能力"),
        ("现金比例", percent(analysis["cash_ratio"]), "家庭备用金厚度"),
        ("股票/基金仓位", percent(analysis["stock_ratio"]), "家庭资金暴露在权益资产里的比例"),
        ("单只最大占比", percent(analysis["max_single_ratio"]), "用于判断是否过度集中"),
    ]
    cards = "".join(
        f"""
        <article class="metric-card">
            <div class="metric-label">{html_escape(label)}</div>
            <div class="metric-value">{html_escape(value)}</div>
            <div class="metric-note">{html_escape(note)}</div>
        </article>
        """
        for label, value, note in metrics
    )
    render_html(
        f"""
        <section class="block">
            <div class="block-head">
                <div>
                    <h2 class="block-title">核心财务指标</h2>
                    <p class="block-subtitle">数据来源：公司公告 · 最近报告期</p>
                </div>
            </div>
            <div class="metric-grid">{cards}</div>
        </section>
        """
    )


def allocation_block(analysis: dict[str, Any]) -> None:
    cash_ratio = max(0, min(1, float(analysis["cash_ratio"])))
    stock_ratio = max(0, min(1, float(analysis["stock_ratio"])))
    render_html(
        f"""
        <section class="block">
            <div class="block-head">
                <div>
                    <h2 class="block-title">家庭账户概况</h2>
                    <p class="block-subtitle">先看钱放在哪里，再讨论某一只股票合不合适。</p>
                </div>
            </div>
            <div class="metric-grid">
                <article class="metric-card"><div class="metric-label">家庭总资产</div><div class="metric-value">{money(analysis["total_assets"])}</div><div class="metric-note">现金 + 股票/基金持仓</div></article>
                <article class="metric-card"><div class="metric-label">现金比例</div><div class="metric-value">{percent(cash_ratio)}</div><div class="metric-note">备用金越薄，越要保守</div></article>
                <article class="metric-card"><div class="metric-label">行业集中度</div><div class="metric-value">{html_escape(analysis["top_industry"])} {percent(analysis["industry_concentration"])}</div><div class="metric-note">行业过于集中时要多留意</div></article>
            </div>
            <div style="margin-top: 1.2rem;">
                <div class="allocation-bar" aria-label="资产配置">
                    <div class="allocation-cash" style="width:{cash_ratio * 100:.1f}%"></div>
                    <div class="allocation-stock" style="width:{stock_ratio * 100:.1f}%"></div>
                </div>
                <p class="muted">沉松绿代表现金，暖金代表股票/基金。</p>
            </div>
        </section>
        """
    )


def holdings_detail(analysis: dict[str, Any]) -> None:
    detail_rows = []
    for item in analysis["stock_results"]:
        detail_rows.append(
            {
                "代码": item["code"],
                "名称": item["name"],
                "金额": money(item["amount"]),
                "占比": percent(item["single_ratio"]),
                "行业": item["industry"],
                "行情": "已匹配" if item["market_source"] != "数据缺失" else "缺失",
                "财务": "已匹配" if item["finance_source"] != "数据缺失" else "暂缺",
                "风险": item["level"],
            }
        )
    render_html(
        """
        <section class="block">
            <div class="block-head">
                <div>
                    <h2 class="block-title">持仓明细</h2>
                    <p class="block-subtitle">每只标的都按数据状态、仓位和风险提示单独列出。</p>
                </div>
            </div>
        </section>
        """
    )
    st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

    for item in analysis["stock_results"]:
        with st.expander(f"查看 {item['name']} 的原因", expanded=False):
            st.write("公司财务质量评价")
            for note in item["financial_notes"]:
                st.write(f"- {note}")
            st.write("交易热度评价")
            for note in item["heat_notes"]:
                st.write(f"- {note}")
            st.write("仓位风险评价")
            for note in item["position_notes"]:
                st.write(f"- {note}")


def risk_grid(analysis: dict[str, Any]) -> None:
    notes = analysis["risk_notes"][:3] or ["当前组合没有明显刺眼的问题，但仍不代表一定赚钱。"]
    levels = [("中", "仓位与现金", "r-mid"), ("中", "公司与数据", "r-mid"), ("低", "短期波动", "r-lo")]
    if analysis["score"] < 60:
        levels[0] = ("高", "家庭承受度", "r-hi")
    cards = []
    for idx, note in enumerate(notes):
        level, title, cls = levels[min(idx, len(levels) - 1)]
        cards.append(
            f"""
            <article class="risk-card-new {cls}">
                <div class="risk-card-head">
                    <div class="muted">风险等级 · {level}</div>
                    <div class="risk-title-pill">{html_escape(title)}</div>
                </div>
                <p class="muted">{html_escape(note)}</p>
            </article>
            """
        )
    render_html(
        f"""
        <section class="block">
            <div class="block-head">
                <div>
                    <h2 class="block-title">风险提示</h2>
                    <p class="block-subtitle">这些不是"会发生"，而是"需要心里有数"。</p>
                </div>
            </div>
            <div class="risk-grid">{''.join(cards)}</div>
        </section>
        """
    )


def news_block() -> None:
    news = [
        {"date": "今天", "source": "公告", "title": "近期公告摘要待后端接入", "tag": "公告"},
        {"date": "本周", "source": "行业", "title": "行业新闻字段暂用前端占位", "tag": "行业"},
        {"date": "最近", "source": "新闻", "title": "后续可补充 news 接口返回内容", "tag": "新闻"},
    ]
    cards = "".join(
        f"""
        <article class="news-card">
            <div class="tag tag-industry">{html_escape(item["tag"])}</div>
            <h3 style="font-size:1.05rem;">{html_escape(item["title"])}</h3>
            <div class="muted">{html_escape(item["date"])} · {html_escape(item["source"])}</div>
        </article>
        """
        for item in news
    )
    render_html(
        f"""
        <section class="block">
            <div class="block-head">
                <div>
                    <h2 class="block-title">近期新闻与公告</h2>
                    <p class="block-subtitle">当前后端未返回新闻字段，先用前端占位，后续可接真实数据。</p>
                </div>
            </div>
            <div class="news-grid">{cards}</div>
        </section>
        """
    )


def discussion_block() -> None:
    render_html(
        """
        <section class="block">
            <div class="block-head">
                <div>
                    <h2 class="block-title">家庭观察记录</h2>
                    <p class="block-subtitle">记录家人对这只标的的看法，方便回顾和共同决策。云端同步开发中。</p>
                </div>
            </div>
        </section>
        """
    )
    note_text = st.text_area(
        "新增观察记录",
        placeholder="记录你的看法，例如：觉得估值偏高，先观察一个季度再说。",
        label_visibility="collapsed",
    )
    btn_col, tip_col = st.columns([2, 5])
    if btn_col.button("发布记录", use_container_width=True) and note_text.strip():
        st.session_state.notes.insert(0, {"who": "我", "when": "刚刚", "body": note_text.strip(), "avatar": "我"})
        st.rerun()
    tip_col.caption("记录仅保存在当前会话 · 关闭页面后清除 · 云端同步开发中")
    if not st.session_state.notes:
        st.info("暂无观察记录。")
    else:
        note_cards = []
        for note in st.session_state.notes:
            note_cards.append(
                f"""
                <article class="note-card">
                    <div class="note-head">
                        <div style="display:flex; gap:.7rem; align-items:center;">
                            <div class="note-avatar">{html_escape(note["avatar"])}</div>
                            <div><strong>{html_escape(note["who"])}</strong><div class="muted">{html_escape(note["when"])}</div></div>
                        </div>
                    </div>
                    <p class="muted">{html_escape(note["body"])}</p>
                </article>
                """
            )
        render_html(f'<div class="news-grid">{"".join(note_cards)}</div>')


def get_deepseek_api_key() -> str:
    key = ""
    try:
        key = str(st.secrets.get("DEEPSEEK_API_KEY", "")).strip()
    except Exception:  # noqa: BLE001
        key = ""
    return key or os.getenv("DEEPSEEK_API_KEY", "").strip()


def deepseek_block(analysis: dict[str, Any]) -> None:
    render_html(
        """
        <section class="block">
            <div class="block-head">
                <div>
                    <h2 class="block-title">AI 通俗说明（可选）</h2>
                    <p class="block-subtitle">点击后调用 DeepSeek，把上面的体检结论改写成更适合父母阅读的话。需配置 API Key。</p>
                </div>
            </div>
        </section>
        """
    )
    deepseek_api_key = get_deepseek_api_key()
    if "ai_report" in st.session_state:
        ai_status = "已生成"
    elif st.session_state.get("ai_report_failed"):
        ai_status = "调用失败"
    elif deepseek_api_key:
        ai_status = "已配置"
    else:
        ai_status = "未配置"
    st.caption(f"AI 分析状态：{ai_status}")

    if st.button("生成 AI 风险说明", use_container_width=True):
        if not deepseek_api_key:
            st.info("未配置 AI 分析功能。")
        else:
            try:
                with st.spinner("正在生成给家人看的风险说明..."):
                    ai_text = generate_parent_friendly_report(analysis, deepseek_api_key)
                st.session_state["ai_report"] = ai_text
                st.session_state.pop("ai_report_failed", None)
                st.rerun()
            except Exception:  # noqa: BLE001
                st.session_state["ai_report_failed"] = True
                st.info("AI 分析暂时不可用，基础风险体检结果不受影响。")

    if "ai_report" in st.session_state:
        render_html('<div class="card" style="padding:1.4rem;">')
        st.markdown(st.session_state["ai_report"])
        render_html("</div>")

    report_text = generate_txt_report(analysis)
    st.download_button(
        "下载 txt 报告",
        data=report_text.encode("utf-8"),
        file_name="家庭投资雷达体检报告.txt",
        mime="text/plain",
        use_container_width=True,
    )


def analysis_page() -> None:
    analysis = st.session_state["analysis"]
    fetch_warnings = st.session_state.get("fetch_warnings", [])
    if st.button("← 返回首页"):
        st.session_state.pop("analysis", None)
        st.session_state.pop("stocks", None)
        st.session_state.pop("fetch_warnings", None)
        st.rerun()
    stock_header(analysis)
    for warning in fetch_warnings:
        st.warning(warning)
    ai_report_block(analysis)
    allocation_block(analysis)
    metric_grid(analysis)
    risk_grid(analysis)
    with st.expander("持仓明细与数据来源", expanded=False):
        holdings_detail(analysis)
    with st.expander("近期新闻与公告（开发中）", expanded=False):
        st.info("暂未接入新闻接口，后续开放。")
        news_block()
    discussion_block()
    deepseek_block(analysis)
    render_html(f'<div class="page-foot">{REPORT_DISCLAIMER}</div>')


init_state()
inject_css()
site_header()

if "analysis" in st.session_state:
    analysis_page()
else:
    home_page()
