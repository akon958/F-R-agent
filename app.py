from __future__ import annotations

import os
import secrets
from html import escape
from math import pi
from typing import Any

import pandas as pd
import streamlit as st

from analyzer import analyze_history_changes, analyze_portfolio, build_risk_factor_breakdown
from agent import run_family_risk_agent
from config import (
    APP_SUBTITLE,
    APP_TITLE,
    DEFAULT_AMOUNTS,
    DEFAULT_CODES,
    DEFAULT_FOLLOWUP_QUESTIONS,
    DEFAULT_REPORT_MODE,
    HOME_DISCLAIMER,
    REPORT_DISCLAIMER,
    REPORT_MODES,
    RISK_PROFILE_HINTS,
    RISK_PROFILE_OPTIONS,
    RISK_PROFILE_SHORT_HINTS,
)
from question_router import route_slash_command
from validator import sanitize_compliance_text

from ai_report import (
    answer_followup_question,
    generate_agent_report,
    get_dynamic_questions,
)
from ui_shell import site_header_html

FOLLOWUP_VERSION = "v5_single_ai_report_entry"
FOLLOWUP_ANSWER_IMPL = "ai_report.answer_followup_question"
_AI_REPORT_FALLBACK_MSG = (
    "AI 报告模块暂时不可用。\n\n"
    "本工具只做家庭投资风险体检和学习参考，不构成任何投资建议，也不替任何人做交易决定。"
)


_FALLBACK_QUESTIONS: list[str] = list(DEFAULT_FOLLOWUP_QUESTIONS)


from data_fetcher import (
    get_cache_diagnostics,
    get_cache_summary,
    get_stock_metrics,
    normalize_code,
    refresh_current_holdings_cache,
    refresh_market_cache,
    resolve_code_or_name,
)
from report_generator import generate_ai_txt_report, generate_txt_report, money, percent
from nl_parser import parse_holdings_nl
from report_exporter import export_text_report
from storage import (
    create_family_account,
    format_datetime_for_display,
    get_family_id,
    get_last_family_comment_read_status,
    get_last_family_comment_save_status,
    get_last_followup_save_status,
    get_storage,
    get_storage_status,
    load_recent_analysis_history,
    load_recent_family_comments,
    load_recent_followup_history,
    make_note,
    save_family_comment,
    save_followup_history,
    verify_family_account,
)




st.set_page_config(page_title=APP_TITLE, layout="wide", initial_sidebar_state="collapsed")


def render_html(html: str) -> None:
    if hasattr(st, "html"):
        st.html(html)
    else:
        st.markdown(html, unsafe_allow_html=True)


def _navigate_to(view: str) -> None:
    st.session_state["active_view"] = view
    st.rerun()


def render_subpage_nav(
    *,
    back_label: str,
    back_view: str,
    crumbs: list[tuple[str, str | None]],
    key_prefix: str,
) -> None:
    if st.button(back_label, use_container_width=True, key=f"{key_prefix}_back"):
        _navigate_to(back_view)

    crumb_targets = [
        (label, view)
        for label, view in crumbs[:-1]
        if view and view != back_view
    ]
    if crumb_targets:
        crumb_cols = st.columns(len(crumb_targets))
        for idx, (label, view) in enumerate(crumb_targets):
            with crumb_cols[idx]:
                if st.button(
                    label,
                    use_container_width=True,
                    key=f"{key_prefix}_crumb_{idx}",
                ):
                    _navigate_to(view)

    crumb_text = " › ".join(label for label, _ in crumbs)
    render_html(
        f'<p style="font-size:0.72rem;color:var(--text-3);margin:0.35rem 0 0.6rem;">'
        f"{html_escape(crumb_text)}</p>"
    )


def init_state() -> None:
    defaults = {
        "holding_rows": 2,
        "font_size": 14,
        "dark_mode": False,
        "fit_open": False,
        "notes": [],
        "notes_loaded": False,  # 用于只在 session 首次启动时从文件加载一次
        "report_mode": DEFAULT_REPORT_MODE,
        "followup_answers": [],
        "followup_questions": [],  # 每次体检生成一次，rerun 时保持不变
        "followup_version": FOLLOWUP_VERSION,
        "family_comments_cache": None,
        "family_comments": [],
        "family_comments_last_count": 0,
        "family_comment_last_save": {},
        "active_view": "analysis",
        "reverse_qa": dict(_REVERSE_QA_DEFAULT),
        "last_followup_save": {},
        "risk_profile": "平衡",
        "nl_input_mode": False,
        "nl_parsed_result": {},
        "agent_intake_result": {},
        "agent_intake_text": "",
        "agent_intake_money_need_label": "不确定",
        "agent_intake_risk_profile": "平衡",
        "agent_intake_cash_override": 0.0,
        "family_logged_in": False,
        "family_id": "",
        "family_account_name": "",
        "family_account_backend": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    for idx, code in enumerate(DEFAULT_CODES):
        st.session_state.setdefault(f"code_{idx}", code)
    for idx, amount in enumerate(DEFAULT_AMOUNTS):
        st.session_state.setdefault(f"amount_{idx}", amount)
    if st.session_state.get("followup_version") != FOLLOWUP_VERSION:
        st.session_state["followup_version"] = FOLLOWUP_VERSION
    # 每个 session 只从本地文件读取一次，之后以 session_state 为准
    if not st.session_state.notes_loaded:
        try:
            st.session_state.notes = get_storage().load_notes()
        except Exception:  # noqa: BLE001
            st.session_state.notes = []
        st.session_state.notes_loaded = True


def _clear_user_runtime_state() -> None:
    """Clear per-family page state when switching accounts."""
    for key in (
        "analysis",
        "agent_result",
        "stocks",
        "fetch_warnings",
        "family_comments_cache",
        "family_comments",
        "family_comments_last_count",
        "family_comment_last_save",
        "last_followup_save",
        "notes",
        "guided_step",
        "guided_member",
        "guided_focus",
        "guided_focus_label",
        "guided_stance",
        "guided_stance_label",
        "guided_text",
        "guided_save_result",
        # Keys omitted in original — would leak prior user's risk profile and Q&A state
        "nl_input_mode",
        "nl_parsed_result",
        "agent_intake_result",
        "agent_intake_text",
        "agent_intake_money_need_label",
        "agent_intake_risk_profile",
        "agent_intake_cash_override",
        "reverse_qa",
        "risk_profile",
        "risk_profile_segment",  # segmented_control widget state for risk_profile
        "report_mode",
    ):
        st.session_state.pop(key, None)
    # Reset to safe defaults (these are always written, so no need to pop first)
    st.session_state["active_view"] = "analysis"
    st.session_state["notes_loaded"] = False
    st.session_state["followup_answers"] = []
    st.session_state["followup_questions"] = []
    st.session_state["followup_version"] = FOLLOWUP_VERSION


def _apply_family_login(result: dict[str, Any]) -> None:
    family_id = str(result.get("family_id") or "").strip()
    if not family_id:
        # Guard: a missing/corrupt family_id would silently fall back to
        # "default_family" in get_family_id(), routing all reads/writes to the
        # shared default bucket.  Refuse the login instead.
        raise ValueError(f"登录结果中缺少有效的 family_id，登录被拒绝（账号：{result.get('account_name')}）")
    _clear_user_runtime_state()
    st.session_state["family_logged_in"] = True
    st.session_state["family_id"] = family_id
    st.session_state["family_account_name"] = str(result.get("account_name") or "")
    st.session_state["family_account_backend"] = str(result.get("backend") or "")


def _apply_guest_login() -> None:
    _clear_user_runtime_state()
    st.session_state["family_logged_in"] = True
    st.session_state["family_id"] = f"guest_{secrets.token_hex(6)}"
    st.session_state["family_account_name"] = "游客模式"
    st.session_state["family_account_backend"] = "guest_local"


def _logout_family() -> None:
    for key in ("family_logged_in", "family_id", "family_account_name", "family_account_backend"):
        st.session_state.pop(key, None)
    _clear_user_runtime_state()


def auth_gate() -> bool:
    """Small account gate so each family reads and writes its own records."""
    if st.session_state.get("family_logged_in") and st.session_state.get("family_id"):
        is_guest_mode = st.session_state.get("family_account_backend") == "guest_local"
        c1, c2 = st.columns([4, 1])
        with c1:
            if is_guest_mode:
                st.caption("当前模式：游客入口（仅本地保存，不上传云端）")
            else:
                st.caption(
                    f"当前家庭账号：{st.session_state.get('family_account_name') or get_family_id()}"
                )
        with c2:
            button_label = "退出游客模式" if is_guest_mode else "退出"
            if st.button(button_label, key="family_logout_btn", use_container_width=True):
                _logout_family()
                st.rerun()
        return True

    render_html(
        """
        <div class="fr-card" style="margin-top:1rem;">
            <div class="fr-eyebrow">Family Account</div>
            <h2 style="margin:0.15rem 0 0.35rem;">进入 FamilyReader</h2>
            <p style="margin:0;color:var(--text-2);">
                可以登录家庭账号，也可以先用游客入口收集意见。游客模式只保存在本地，不上传云端。
            </p>
        </div>
        """
    )
    tab_login, tab_create, tab_guest = st.tabs(["登录", "创建账号", "游客入口"])
    with tab_login:
        login_name = st.text_input("家庭账号", key="login_family_name")
        login_password = st.text_input("密码", key="login_family_password", type="password")
        if st.button("登录 FamilyReader", key="family_login_btn", use_container_width=True, type="primary"):
            result = verify_family_account(login_name, login_password)
            if result.get("success"):
                try:
                    _apply_family_login(result)
                    st.rerun()
                except ValueError as exc:
                    st.error(f"登录失败：{exc}")
            else:
                st.warning(result.get("message") or "登录失败，请检查账号或密码。")
    with tab_create:
        create_name = st.text_input("新家庭账号", key="create_family_name")
        create_password = st.text_input("设置密码", key="create_family_password", type="password")
        create_password2 = st.text_input("再输入一次密码", key="create_family_password2", type="password")
        if st.button("创建并进入", key="family_create_btn", use_container_width=True):
            if create_password != create_password2:
                st.warning("两次输入的密码不一致。")
            else:
                result = create_family_account(create_name, create_password)
                if result.get("success"):
                    try:
                        _apply_family_login(result)
                        st.rerun()
                    except ValueError as exc:
                        st.error(f"账号创建成功但无法登录：{exc}")
                else:
                    st.warning(result.get("message") or "账号创建失败，请稍后再试。")
    with tab_guest:
        st.caption("适合临时体验或收集家人意见。游客模式只写本地文件，不写入 Supabase 云端。")
        if st.button("以游客身份进入", key="family_guest_btn", use_container_width=True):
            _apply_guest_login()
            st.rerun()
    st.caption("密码只用于区分家庭数据；不要使用银行卡、支付软件等重要密码。")
    return False


def css_vars(dark_mode: bool | None = None) -> dict[str, str]:
    _dark = dark_mode if dark_mode is not None else st.session_state.dark_mode
    if _dark:
        # ── 深色模式：安静夜读，不使用高饱和科技蓝 ──────────────────
        return {
            "bg": "#11100e",
            "bg_2": "#191713",
            "surface": "#1f1c18",
            "surface_2": "#28231e",
            "border": "#3b332b",
            "border_strong": "#58483b",
            "text": "#eee7dc",
            "text_2": "#c1b3a3",
            "text_3": "#8e8173",
            "accent": "#b06f4f",
            "accent_soft": "#2d211b",
            "accent_2": "#77a98a",
            "accent_2_soft": "#17251d",
            "gold": "#d7ad5f",
            "gold_soft": "#302716",
            "up": "#d36b5f",
            "up_soft": "#321b18",
            "down": "#77a98a",
            "down_soft": "#17251d",
            "warn": "#d69b56",
            "warn_soft": "#302316",
            "glass": "rgba(31,28,24,0.86)",
            "glow_accent": "none",
            "glow_up": "none",
            "glow_down": "none",
            "glow_warn": "none",
        }
    # ── 浅色模式：温润纸面 + 克制陶土色，适合家庭阅读 ─────────────
    return {
        "bg": "#f6f1ea",
        "bg_2": "#eee7dd",
        "surface": "#fbf8f3",
        "surface_2": "#f3ece2",
        "border": "#ddd0c0",
        "border_strong": "#c9b6a4",
        "text": "#282019",
        "text_2": "#65584b",
        "text_3": "#9a8d7f",
        "accent": "#8d5039",
        "accent_soft": "#f0dfd5",
        "accent_2": "#4f8466",
        "accent_2_soft": "#e0ece4",
        "gold": "#a9782a",
        "gold_soft": "#f5ead2",
        "up": "#b64b42",
        "up_soft": "#f5ddd8",
        "down": "#4f8466",
        "down_soft": "#e0ece4",
        "warn": "#a9782a",
        "warn_soft": "#f5ead2",
        "glass": "rgba(251,248,243,0.9)",
        "glow_accent": "none",
        "glow_up": "none",
        "glow_down": "none",
        "glow_warn": "none",
    }


@st.cache_data(show_spinner=False)
def _css_block(dark_mode: bool, font_size: int) -> str:
    v = css_vars(dark_mode)
    return (
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&family=Noto+Sans+SC:wght@400;500;600;700&family=Noto+Serif+SC:wght@500;600;700&display=swap');

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
            --font-display: "Noto Sans SC", "PingFang SC", system-ui, sans-serif;
            --font-body: "Noto Sans SC", "PingFang SC", system-ui, sans-serif;
            --font-num: "JetBrains Mono", "Inter", "SF Mono", monospace;
            --font-code: "JetBrains Mono", "Fira Code", monospace;
            --radius-sm: 8px;
            --radius-md: 14px;
            --radius-lg: 20px;
            --transition: 160ms cubic-bezier(0.4,0,0.2,1);
            --glow-accent: {v.get("glow_accent","none")};
            --glow-up: {v.get("glow_up","none")};
            --glow-down: {v.get("glow_down","none")};
            --glow-warn: {v.get("glow_warn","none")};
        }}

        html, body, [class*="css"], [data-testid="stAppViewContainer"] {{
            font-size: {font_size}px;
            font-family: var(--font-body);
            color: var(--text);
            background: var(--bg);
            font-feature-settings: "tnum" on, "lnum" on;
        }}
        [data-testid="stAppViewContainer"] > .main {{
            background: var(--bg);
        }}
        .main .block-container,
        [data-testid="stAppViewContainer"] .main .block-container {{
            width: min(100% - 2rem, 920px) !important;
            max-width: 920px !important;
            margin-left: auto !important;
            margin-right: auto !important;
            padding: 1.25rem 0 90px !important;
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
            color: var(--text);
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
            box-shadow: 0 8px 18px rgba(78, 62, 48, 0.10);
        }}
        .stFormSubmitButton button {{
            min-height: 3.05rem;
            background: linear-gradient(135deg, #7b4937 0%, var(--accent) 58%, #a46a47 100%);
            color: #fff;
            border-color: var(--accent);
            font-size: 1rem;
            font-weight: 800;
            box-shadow: 0 14px 28px rgba(124, 73, 55, 0.20);
        }}
        .stFormSubmitButton button:hover {{
            color: #fff;
            background: linear-gradient(135deg, #6f4030 0%, var(--accent) 58%, #9c6140 100%);
            box-shadow: 0 16px 32px rgba(124, 73, 55, 0.25);
        }}
        .stButton button[kind="primary"] {{
            min-height: 3.05rem;
            background: linear-gradient(135deg, #7b4937 0%, var(--accent) 58%, #a46a47 100%);
            color: #fff;
            border-color: var(--accent);
            font-size: 1rem;
            font-weight: 800;
            box-shadow: 0 14px 28px rgba(124, 73, 55, 0.20);
        }}
        .stButton button[kind="primary"]:hover {{
            color: #fff;
            background: linear-gradient(135deg, #6f4030 0%, var(--accent) 58%, #9c6140 100%);
            box-shadow: 0 16px 32px rgba(124, 73, 55, 0.25);
        }}
        div[data-testid="stTextInput"] input,
        div[data-testid="stNumberInput"] input,
        div[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
        textarea {{
            background: var(--bg-2) !important;
            color: #2b211b !important;
            border: 1px solid var(--border) !important;
            border-radius: 14px !important;
            min-height: 3rem;
            font-size: 1rem !important;
        }}
        div[data-testid="stTextInput"] input::placeholder,
        div[data-testid="stNumberInput"] input::placeholder,
        textarea::placeholder {{
            color: #c4bbb3 !important;
            opacity: 1 !important;
        }}
        div[data-testid="stTextInput"] input,
        div[data-testid="stNumberInput"] input,
        textarea {{
            -webkit-text-fill-color: #2b211b !important;
        }}
        div[data-testid="stTextInput"] input:focus,
        div[data-testid="stNumberInput"] input:focus,
        textarea:focus {{
            border-color: var(--accent) !important;
            box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 15%, transparent) !important;
        }}
        div[data-testid="stRadio"] > label {{
            font-weight: 800;
            color: var(--text);
        }}
        div[data-testid="stRadio"] div[role="radiogroup"] {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.48rem;
        }}
        div[data-testid="stRadio"] div[role="radiogroup"] label {{
            min-height: 2.35rem;
            margin: 0 !important;
            padding: 0.35rem 0.68rem;
            border: 1px solid var(--border);
            border-radius: 999px;
            background: var(--surface);
            color: var(--text-2);
            transition: all 160ms ease;
        }}
        div[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) {{
            border-color: var(--accent);
            background: var(--accent-soft);
            color: var(--accent);
            box-shadow: 0 8px 18px rgba(78, 62, 48, 0.08);
        }}
        div[data-testid="stRadio"] div[role="radiogroup"] label:hover {{
            border-color: var(--accent);
        }}
        .risk-hint-grid {{
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 0.35rem;
            margin: 0.45rem 0 0.2rem;
        }}
        .risk-hint {{
            border: 1px solid var(--border);
            border-radius: 12px;
            background: color-mix(in srgb, var(--surface) 88%, var(--bg-2));
            padding: 0.42rem 0.48rem;
            color: var(--text-2);
            font-size: 0.72rem;
            line-height: 1.35;
        }}
        .risk-hint strong {{
            display: block;
            color: var(--text);
            font-size: 0.78rem;
            margin-bottom: 0.12rem;
        }}
        .risk-hint.active {{
            border-color: var(--accent);
            background: var(--accent-soft);
            color: var(--accent);
        }}
        .risk-hint.active strong {{
            color: var(--accent);
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
            width: 40px;
            height: 40px;
            flex-shrink: 0;
            display: grid;
            place-items: center;
            filter: drop-shadow(0 2px 6px rgba(122,62,46,0.28));
        }}
        .brand-cn {{
            font-family: var(--font-display);
            font-weight: 700;
            font-size: 1.08rem;
            color: var(--text);
            line-height: 1.1;
            letter-spacing: 0.01em;
        }}
        .brand-en {{
            font-size: 0.68rem;
            color: var(--text-3);
            font-family: var(--font-num);
            line-height: 1.2;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }}
        .brand-badge {{
            display: inline-block;
            font-size: 0.55rem;
            font-family: var(--font-num);
            font-weight: 600;
            letter-spacing: 0.06em;
            color: var(--accent);
            background: var(--accent-soft);
            border-radius: 4px;
            padding: 1px 5px;
            margin-left: 5px;
            vertical-align: middle;
            line-height: 1.6;
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
            padding: 1.25rem 1.35rem;
        }}
        .compact-guide {{
            margin: 1.1rem 0 1.35rem;
            background: linear-gradient(180deg, color-mix(in srgb, var(--surface) 86%, var(--accent-soft)), var(--surface));
        }}
        .compact-guide .block-head {{
            margin-bottom: 0.65rem;
        }}
        .compact-guide .block-title {{
            font-size: 1.08rem;
        }}
        .compact-guide .block-subtitle {{
            font-size: 0.9rem;
        }}
        .guide-list {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 0.75rem;
        }}
        .guide-step {{
            display: grid;
            grid-template-columns: auto 1fr;
            gap: 0.65rem;
            align-items: start;
        }}
        .step-num {{
            width: 1.55rem;
            height: 1.55rem;
            border-radius: 999px;
            border: 1px solid var(--border-strong);
            background: var(--surface);
            color: var(--accent);
            display: grid;
            place-items: center;
            font-family: var(--font-num);
            font-weight: 800;
            font-size: 0.86rem;
        }}
        .step-title {{
            color: var(--text);
            font-weight: 800;
            margin-bottom: 0.08rem;
            font-size: 0.98rem;
        }}
        .guide-step .muted {{
            font-size: 0.88rem;
            line-height: 1.55;
        }}
        .guide-foot, .page-foot {{
            margin-top: 0.85rem;
            padding-top: 0.75rem;
            border-top: 1px dashed var(--border);
            color: var(--text-2);
            font-size: 0.82rem;
        }}
        .agent-flow-card {{
            margin: 0.75rem 0 1.05rem;
            border: 1px solid var(--border);
            border-radius: 14px;
            background: color-mix(in srgb, var(--surface) 92%, var(--accent-soft));
            padding: 0.85rem 0.95rem;
            box-shadow: 0 10px 24px rgba(42, 37, 32, 0.035);
        }}
        .agent-flow-head {{
            display: flex;
            justify-content: space-between;
            gap: 0.75rem;
            align-items: center;
            margin-bottom: 0.65rem;
        }}
        .agent-flow-head p {{
            margin: 0;
            color: var(--text-2);
            font-size: 0.88rem;
            line-height: 1.45;
            text-align: right;
        }}
        .eyebrow.mini {{
            padding: 0.25rem 0.58rem;
            font-size: 0.72rem;
            white-space: nowrap;
        }}
        .agent-flow-steps {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 0.35rem;
        }}
        .agent-flow-steps span {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 0.28rem;
            border: 1px solid var(--border);
            border-radius: 999px;
            background: var(--surface);
            color: var(--text);
            font-size: 0.82rem;
            font-weight: 700;
            padding: 0.34rem 0.42rem;
            min-width: 0;
        }}
        .agent-flow-steps b {{
            width: 1.15rem;
            height: 1.15rem;
            display: inline-grid;
            place-items: center;
            border-radius: 999px;
            background: var(--accent-soft);
            color: var(--accent);
            font-family: var(--font-num);
            font-size: 0.72rem;
        }}
        .agent-flow-note {{
            margin-top: 0.6rem;
            color: var(--text-3);
            font-size: 0.76rem;
            line-height: 1.45;
            border-top: 1px dashed var(--border);
            padding-top: 0.55rem;
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
        .risk-signal {{
            display: flex;
            gap: 1rem;
            align-items: center;
        }}
        .risk-light {{
            width: 3.25rem;
            height: 3.25rem;
            border-radius: 999px;
            flex: 0 0 auto;
            border: 4px solid rgba(255, 255, 255, 0.72);
            box-shadow: 0 12px 30px rgba(42, 37, 32, 0.14), inset 0 0 0 1px rgba(0, 0, 0, 0.06);
        }}
        .risk-green .risk-light {{
            background: radial-gradient(circle at 35% 30%, #eefaf1 0, #4e9f68 48%, #247a45 100%);
        }}
        .risk-yellow .risk-light {{
            background: radial-gradient(circle at 35% 30%, #fff8dc 0, #dfb844 52%, #aa8422 100%);
        }}
        .risk-red .risk-light {{
            background: radial-gradient(circle at 35% 30%, #ffe8e3 0, #c85a4a 52%, #933123 100%);
        }}
        .risk-neutral .risk-light {{
            background: radial-gradient(circle at 35% 30%, #f3f1ee 0, #9b9288 54%, #6f665e 100%);
        }}
        .risk-status {{
            font-family: var(--font-display);
            font-size: 1.8rem;
            font-weight: 700;
            margin: 0.22rem 0;
        }}
        .risk-score-line {{
            color: var(--text-2);
            font-size: 0.92rem;
        }}
        .score-dial {{
            width: 136px;
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
        /* ── 两列紧凑指标网格 ─────────────────────────────────── */
        .metric-grid-2 {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 0.65rem;
        }}
        .metric-card-sm {{
            border: 1px solid var(--border);
            border-radius: 12px;
            background: var(--surface);
            padding: 0.8rem 0.9rem 0.75rem;
            min-width: 0;
        }}
        .metric-value-sm {{
            color: var(--text);
            font-family: var(--font-num);
            font-size: 1.25rem;
            font-weight: 700;
            margin: 0.2rem 0 0.12rem;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .metric-note-sm {{
            color: var(--text-3);
            font-size: 0.72rem;
            line-height: 1.3;
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
            .main .block-container,
            [data-testid="stAppViewContainer"] .main .block-container {{
                width: min(100% - 1.5rem, 820px) !important;
            }}
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
            .main .block-container,
            [data-testid="stAppViewContainer"] .main .block-container {{
                width: 100% !important;
                max-width: 100% !important;
                padding: 1rem 0.85rem 90px !important;
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
            .hero-card, .stock-head {{
                padding: 1.45rem;
            }}
            .guide-block {{
                padding: 1.05rem;
            }}
            .guide-list {{
                gap: 0.85rem;
            }}
            .risk-hint-grid {{
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }}
            .agent-flow-head {{
                display: block;
            }}
            .agent-flow-head p {{
                text-align: left;
                margin-top: 0.35rem;
            }}
            .agent-flow-steps {{
                grid-template-columns: repeat(2, 1fr);
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
            .score-dial {{
                margin: 0 auto;
            }}
        }}
        /* ── 顶部导航 pill 样式 ──────────────────────────────── */
        [data-testid="stMarkdownContainer"]:has(#fi-top-nav) ~ [data-testid="stHorizontalBlock"] .stButton button {{
            min-height: 1.7rem !important;
            font-size: 0.76rem !important;
            font-weight: 500 !important;
            padding: 0.12rem 0.65rem !important;
            background: transparent !important;
            border: 1px solid rgba(122,62,46,0.22) !important;
            color: var(--text-3) !important;
            box-shadow: none !important;
            transform: none !important;
        }}
        [data-testid="stMarkdownContainer"]:has(#fi-top-nav) ~ [data-testid="stHorizontalBlock"] .stButton button:hover {{
            border-color: var(--accent) !important;
            color: var(--accent) !important;
            box-shadow: none !important;
            transform: none !important;
        }}
        /* ── 体检进度：步骤转圈动画 ──────────────────────────── */
        @keyframes fi-spin {{
            to {{ transform: rotate(360deg); }}
        }}
        .fi-spinner {{
            display: inline-block;
            width: 0.85em; height: 0.85em;
            border: 2px solid rgba(122,62,46,0.18);
            border-top-color: #7a3e2e;
            border-radius: 50%;
            animation: fi-spin 0.75s linear infinite;
            vertical-align: middle;
            flex-shrink: 0;
        }}
        /* ── 持仓删除按钮：手机端紧凑化 ─────────────────────── */
        [data-testid="stExpander"] [data-testid="column"]:last-child button {{
            padding: 0 0.45rem !important;
            min-height: 1.85rem !important;
            height: 1.85rem !important;
            font-size: 0.78rem !important;
            line-height: 1 !important;
            margin-top: 1.65rem !important;
            opacity: 0.55;
            background: transparent !important;
            border-color: var(--border) !important;
            color: var(--text-2) !important;
            border-radius: 6px !important;
            box-shadow: none !important;
        }}

        /* ══════════════════════════════════════════════════════
           科技感增强层  ·  Muse Design Tokens + Palette UX
           ══════════════════════════════════════════════════════ */

        /* ── 关键帧动画 ─────────────────────────────────────── */
        @keyframes scan-line {{
            0%   {{ transform: translateY(-100%); opacity: 0; }}
            15%  {{ opacity: 1; }}
            85%  {{ opacity: 1; }}
            100% {{ transform: translateY(200%); opacity: 0; }}
        }}
        @keyframes shimmer {{
            0%   {{ transform: translateX(-100%); }}
            100% {{ transform: translateX(200%); }}
        }}
        @keyframes pulse-ring {{
            0%   {{ box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 55%, transparent); }}
            70%  {{ box-shadow: 0 0 0 8px transparent; }}
            100% {{ box-shadow: 0 0 0 0 transparent; }}
        }}
        @keyframes led-blink {{
            0%, 100% {{ opacity: 1; }}
            50%       {{ opacity: 0.55; }}
        }}
        @keyframes data-in {{
            from {{ opacity: 0; transform: translateY(6px); }}
            to   {{ opacity: 1; transform: translateY(0); }}
        }}

        /* ── 背景：深色模式点阵纹理 ─────────────────────────── */
        [data-testid="stAppViewContainer"] > .main {{
            background-image:
                radial-gradient(circle at 1px 1px,
                    color-mix(in srgb, var(--accent) 7%, transparent) 1px,
                    transparent 0);
            background-size: 32px 32px;
        }}

        /* ── 数字字体全局覆盖（JetBrains Mono）─────────────── */
        .big-number, .metric-value, .metric-value-sm,
        .kv dd, .score-num, .risk-score-line,
        div[data-testid="stMetricValue"] {{
            font-family: var(--font-num) !important;
            font-feature-settings: "tnum" on, "lnum" on, "calt" on;
            letter-spacing: -0.02em;
        }}
        /* 股票代码等宽显示 */
        .tag-code, .market-code {{
            font-family: var(--font-code) !important;
            font-size: 0.78rem;
            letter-spacing: 0.04em;
        }}

        /* ── 主色调调整：从暖棕→科技蓝 ───────────────────────── */
        .fi-spinner {{
            border-color: color-mix(in srgb, var(--accent) 20%, transparent) !important;
            border-top-color: var(--accent) !important;
        }}
        .eyebrow {{
            letter-spacing: 0.04em;
            text-transform: uppercase;
            font-size: 0.74rem;
        }}

        /* ── 卡片升级：边框 + 悬停光晕 ─────────────────────── */
        .card, .hero-card, .market-card, .watch-card,
        .metric-card, .metric-card-sm, .news-card, .note-card,
        .risk-card-new, .ai-detail-note {{
            border-radius: var(--radius-md);
            transition: border-color var(--transition), box-shadow var(--transition), transform var(--transition);
        }}
        .card:hover, .watch-card:hover,
        .metric-card:hover, .risk-card-new:hover {{
            border-color: color-mix(in srgb, var(--accent) 50%, transparent);
            box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 18%, transparent),
                        0 12px 28px color-mix(in srgb, var(--accent) 8%, transparent);
            transform: translateY(-2px);
        }}

        /* ── 判决卡：扫描线动效 ─────────────────────────────── */
        .verdict-card {{
            position: relative;
            overflow: hidden;
            background: linear-gradient(135deg,
                color-mix(in srgb, var(--accent-soft) 80%, var(--surface)),
                var(--surface) 65%) !important;
            border-color: color-mix(in srgb, var(--accent) 35%, transparent) !important;
        }}
        .verdict-card::after {{
            content: '';
            position: absolute;
            top: 0; left: 0;
            width: 100%; height: 60px;
            background: linear-gradient(
                180deg,
                transparent 0%,
                color-mix(in srgb, var(--accent) 6%, transparent) 50%,
                transparent 100%
            );
            animation: scan-line 5s ease-in-out infinite;
            pointer-events: none;
        }}

        /* ── 风险灯升级：LED 光晕 ───────────────────────────── */
        .risk-green .risk-light {{
            background: radial-gradient(circle at 35% 30%, #b6f5d4 0, #22c55e 48%, #15803d 100%);
            box-shadow: 0 0 0 3px rgba(34,197,94,0.18), 0 0 18px rgba(34,197,94,0.35) !important;
        }}
        .risk-yellow .risk-light {{
            background: radial-gradient(circle at 35% 30%, #fef9c3 0, #eab308 52%, #a16207 100%);
            box-shadow: 0 0 0 3px rgba(234,179,8,0.18), 0 0 18px rgba(234,179,8,0.35) !important;
        }}
        .risk-red .risk-light {{
            background: radial-gradient(circle at 35% 30%, #ffe4e4 0, #ef4444 52%, #b91c1c 100%);
            box-shadow: 0 0 0 3px rgba(239,68,68,0.18), 0 0 18px rgba(239,68,68,0.35) !important;
            animation: pulse-ring 2.2s ease-in-out infinite;
        }}
        .risk-neutral .risk-light {{
            background: radial-gradient(circle at 35% 30%, #e2e8f0 0, #64748b 54%, #334155 100%);
            box-shadow: 0 0 0 3px rgba(100,116,139,0.15), 0 0 10px rgba(100,116,139,0.22) !important;
        }}

        /* ── 评分数字：重点高亮 ─────────────────────────────── */
        .score-num {{
            font-size: 2.8rem;
            font-weight: 700;
            color: var(--accent);
            line-height: 1;
            text-shadow: var(--glow-accent);
        }}

        /* ── 风险因子左边线升级：发光条 ─────────────────────── */
        .risk-card-new {{
            border-left-width: 3px;
        }}
        .r-hi {{
            border-left-color: var(--up);
            box-shadow: -3px 0 12px color-mix(in srgb, var(--up) 25%, transparent);
        }}
        .r-mid {{
            border-left-color: var(--gold);
            box-shadow: -3px 0 12px color-mix(in srgb, var(--gold) 25%, transparent);
        }}
        .r-lo {{
            border-left-color: var(--accent-2);
            box-shadow: -3px 0 12px color-mix(in srgb, var(--accent-2) 22%, transparent);
        }}

        /* ── 持仓分配条：渐变 + 微光 ───────────────────────── */
        .allocation-bar {{
            height: 10px;
            border-radius: 999px;
            overflow: hidden;
            background: var(--bg-2);
            border: 1px solid var(--border);
            position: relative;
        }}
        .allocation-cash {{
            background: linear-gradient(90deg, var(--accent-2), color-mix(in srgb, var(--accent-2) 80%, var(--accent)));
            position: relative;
            overflow: hidden;
        }}
        .allocation-cash::after {{
            content: '';
            position: absolute;
            top: 0; left: 0;
            width: 60%; height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
            animation: shimmer 2.5s ease-in-out infinite;
        }}
        .allocation-stock {{
            background: linear-gradient(90deg, var(--gold), color-mix(in srgb, var(--gold) 80%, var(--accent)));
            position: relative;
            overflow: hidden;
        }}
        .allocation-stock::after {{
            content: '';
            position: absolute;
            top: 0; left: 0;
            width: 60%; height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.25), transparent);
            animation: shimmer 2.5s ease-in-out 0.8s infinite;
        }}

        /* ── LED 状态圆点 ────────────────────────────────────── */
        .led {{
            display: inline-block;
            width: 7px; height: 7px;
            border-radius: 50%;
            flex-shrink: 0;
        }}
        .led-green  {{ background: var(--down);  box-shadow: 0 0 6px var(--down); }}
        .led-yellow {{ background: var(--gold);  box-shadow: 0 0 6px var(--gold); }}
        .led-red    {{ background: var(--up);    box-shadow: 0 0 6px var(--up); animation: led-blink 1.8s ease-in-out infinite; }}
        .led-blue   {{ background: var(--accent); box-shadow: 0 0 6px var(--accent); }}

        /* ── 指标值：数据加载入场动画 ──────────────────────── */
        .metric-value, .metric-value-sm, .score-num, .big-number {{
            animation: data-in 0.35s ease both;
        }}

        /* ── Agent Flow 步骤：科技感升级 ───────────────────── */
        .agent-flow-card {{
            background: color-mix(in srgb, var(--surface) 92%, var(--accent-soft)) !important;
            border-color: color-mix(in srgb, var(--accent) 22%, transparent) !important;
        }}
        .agent-flow-steps span {{
            border-radius: 6px !important;
            border-color: color-mix(in srgb, var(--border) 80%, var(--accent)) !important;
        }}
        .agent-flow-steps b {{
            background: color-mix(in srgb, var(--accent-soft) 90%, transparent) !important;
            color: var(--accent) !important;
            font-family: var(--font-num) !important;
        }}

        /* ── 主按钮：科技蓝渐变 ─────────────────────────────── */
        .stFormSubmitButton button,
        .stButton button[kind="primary"] {{
            background: linear-gradient(135deg,
                color-mix(in srgb, var(--accent) 70%, #0c4a6e),
                var(--accent) 58%,
                color-mix(in srgb, var(--accent) 80%, #38bdf8)) !important;
            border-color: var(--accent) !important;
            box-shadow: 0 6px 24px color-mix(in srgb, var(--accent) 30%, transparent) !important;
        }}
        .stFormSubmitButton button:hover,
        .stButton button[kind="primary"]:hover {{
            box-shadow: 0 8px 32px color-mix(in srgb, var(--accent) 45%, transparent) !important;
            filter: brightness(1.08);
        }}

        /* ── 输入框 focus：科技蓝光圈 ───────────────────────── */
        div[data-testid="stTextInput"] input:focus,
        div[data-testid="stNumberInput"] input:focus,
        textarea:focus {{
            border-color: var(--accent) !important;
            box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent),
                        var(--glow-accent) !important;
        }}

        /* ── expander 头部：科技感边框 ─────────────────────── */
        [data-testid="stExpander"] {{
            border-color: var(--border) !important;
            border-radius: var(--radius-md) !important;
        }}
        [data-testid="stExpander"]:focus-within,
        [data-testid="stExpander"][open] {{
            border-color: color-mix(in srgb, var(--accent) 35%, transparent) !important;
        }}

        /* ── 指标卡左侧装饰条 ───────────────────────────────── */
        .metric-card, .metric-card-sm {{
            position: relative;
            overflow: hidden;
        }}
        .metric-card::before, .metric-card-sm::before {{
            content: '';
            position: absolute;
            top: 0; left: 0;
            width: 3px; height: 100%;
            background: linear-gradient(180deg, var(--accent), transparent);
            border-radius: 3px 0 0 3px;
            opacity: 0.7;
        }}

        /* ── 顶部导航 pill 颜色跟随主色 ─────────────────────── */
        [data-testid="stMarkdownContainer"]:has(#fi-top-nav) ~ [data-testid="stHorizontalBlock"] .stButton button {{
            border-color: color-mix(in srgb, var(--accent) 25%, transparent) !important;
        }}
        [data-testid="stMarkdownContainer"]:has(#fi-top-nav) ~ [data-testid="stHorizontalBlock"] .stButton button:hover {{
            border-color: var(--accent) !important;
            color: var(--accent) !important;
            box-shadow: 0 0 8px color-mix(in srgb, var(--accent) 20%, transparent) !important;
        }}

        /* ── 深色模式专属：玻璃态卡片 ──────────────────────── */
        @media (prefers-color-scheme: dark) {{
            .card, .hero-card, .market-card, .verdict-card,
            .metric-card, .metric-card-sm, .watch-card {{
                backdrop-filter: blur(12px);
            }}
        }}

        /* ══════════════════════════════════════════════════════
           FamilyReader polish pass · quiet intelligent product UI
           ══════════════════════════════════════════════════════ */

        [data-testid="stAppViewContainer"] > .main {{
            background-image: none !important;
        }}
        .main .block-container,
        [data-testid="stAppViewContainer"] .main .block-container {{
            width: min(100% - 2rem, 760px) !important;
            max-width: 760px !important;
            padding-top: 1.05rem !important;
        }}
        .brand {{
            justify-content: center;
            margin: 0.55rem 0 1.1rem;
        }}
        .brand-mark {{
            display: none;
        }}
        .brand-cn {{
            font-family: var(--font-display);
            font-size: 1.18rem;
            letter-spacing: -0.01em;
        }}
        .brand-en {{
            font-size: 0.78rem;
            color: var(--text-3);
        }}
        .brand-badge {{
            margin-left: 0.35rem;
            padding: 0.08rem 0.28rem;
            border-radius: 999px;
            background: var(--accent-soft);
            color: var(--accent);
            font-size: 0.62rem;
            vertical-align: middle;
        }}
        .card, .hero-card, .market-card, .guide-block, .list-shell,
        .stock-head, .verdict-card, .watch-card, .metric-card,
        .metric-card-sm, .news-card, .note-card, .risk-card-new,
        .ai-detail-note {{
            border-radius: 16px !important;
            border: 1px solid var(--border) !important;
            background: var(--surface) !important;
            box-shadow: 0 10px 28px rgba(48, 38, 28, 0.055) !important;
            transform: none !important;
        }}
        .card:hover, .watch-card:hover, .metric-card:hover,
        .risk-card-new:hover {{
            border-color: var(--border-strong) !important;
            box-shadow: 0 12px 30px rgba(48, 38, 28, 0.075) !important;
            transform: none !important;
        }}
        .fr-hero {{
            padding: 1.25rem 1.18rem 1.05rem;
            margin: 0 0 0.8rem;
            position: relative;
            overflow: hidden;
        }}
        .fr-hero::before {{
            content: "";
            position: absolute;
            inset: 0 0 auto;
            height: 3px;
            background: linear-gradient(90deg, var(--accent), var(--accent-2), var(--gold));
            opacity: 0.72;
        }}
        .fr-hero-kicker {{
            display: inline-flex;
            align-items: center;
            gap: 0.34rem;
            color: var(--accent);
            background: var(--accent-soft);
            border-radius: 999px;
            padding: 0.28rem 0.58rem;
            font-size: 0.72rem;
            font-weight: 800;
            margin-bottom: 0.72rem;
        }}
        .fr-hero-title {{
            margin: 0 0 0.34rem;
            font-size: 1.38rem;
            font-weight: 750;
            line-height: 1.28;
            color: var(--text);
        }}
        .fr-hero-subtitle {{
            margin: 0;
            color: var(--text-2);
            font-size: 0.92rem;
            line-height: 1.58;
            max-width: 54ch;
        }}
        .fr-agent-strip {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 0.38rem;
            margin-top: 0.86rem;
        }}
        .fr-agent-strip span {{
            border: 1px solid var(--border);
            border-radius: 10px;
            background: color-mix(in srgb, var(--surface) 88%, var(--bg-2));
            padding: 0.42rem 0.48rem;
            color: var(--text-2);
            font-size: 0.75rem;
            font-weight: 700;
            text-align: center;
        }}
        .fr-disclaimer {{
            margin: 0.7rem 0 0;
            color: var(--text-3);
            font-size: 0.72rem;
            line-height: 1.48;
        }}
        .fr-field-label {{
            margin: 0.62rem 0 0.34rem;
            font-size: 0.88rem;
            font-weight: 800;
            color: var(--text);
        }}
        .fr-risk-note {{
            margin: 0.56rem 0 0.72rem;
            padding: 0.58rem 0.72rem;
            border-radius: 12px;
            border: 1px solid var(--border);
            background: color-mix(in srgb, var(--accent-soft) 42%, var(--surface));
            color: var(--text-2);
            font-size: 0.82rem;
            line-height: 1.55;
        }}
        .fr-risk-note b {{
            color: var(--accent);
            margin-right: 0.35rem;
        }}
        .fr-step-card {{
            margin: 0.35rem 0 0.5rem;
            padding: 0.86rem 0.95rem;
            border-radius: 16px;
            border: 1px solid var(--border);
            background:
                linear-gradient(135deg,
                    color-mix(in srgb, var(--surface) 92%, var(--accent-soft)),
                    var(--surface));
            box-shadow: 0 10px 26px rgba(48, 38, 28, 0.05);
        }}
        .fr-step-kicker {{
            margin: 0 0 0.22rem;
            color: var(--accent);
            font-size: 0.68rem;
            font-weight: 850;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }}
        .fr-step-title {{
            margin: 0 0 0.18rem;
            color: var(--text);
            font-size: 0.98rem;
            font-weight: 850;
            line-height: 1.38;
        }}
        .fr-step-sub {{
            margin: 0;
            color: var(--text-3);
            font-size: 0.78rem;
            line-height: 1.55;
        }}
        .fr-mini-nav {{
            display: flex;
            gap: 0.45rem;
            flex-wrap: wrap;
            margin: 0.2rem 0 0.72rem;
        }}
        .fr-mini-nav span {{
            display: inline-flex;
            align-items: center;
            border: 1px solid var(--border);
            border-radius: 999px;
            background: var(--surface);
            color: var(--text-2);
            padding: 0.24rem 0.62rem;
            font-size: 0.74rem;
            font-weight: 750;
        }}
        .hero-title {{
            font-size: 1.38rem;
        }}
        .hero-subtitle {{
            font-size: 0.94rem;
            margin-bottom: 0.8rem;
        }}
        .search-shell {{
            border-radius: 16px !important;
            background: transparent !important;
            border: 0 !important;
            padding: 0 !important;
            margin: 0.55rem 0 0.9rem !important;
        }}
        .stButton button, .stDownloadButton button, .stFormSubmitButton button {{
            min-height: 2.6rem;
            border-radius: 999px !important;
            background: var(--surface) !important;
            color: var(--text) !important;
            border: 1px solid var(--border-strong) !important;
            box-shadow: none !important;
            font-weight: 700;
        }}
        .stButton button:hover, .stDownloadButton button:hover,
        .stFormSubmitButton button:hover {{
            color: var(--accent) !important;
            border-color: var(--accent) !important;
            box-shadow: 0 8px 18px rgba(48, 38, 28, 0.08) !important;
            filter: none !important;
        }}
        .stFormSubmitButton button,
        .stButton button[kind="primary"] {{
            min-height: 3rem !important;
            background: var(--accent) !important;
            color: #fdf8f1 !important;
            border-color: var(--accent) !important;
            box-shadow: 0 12px 22px color-mix(in srgb, var(--accent) 22%, transparent) !important;
        }}
        .stFormSubmitButton button *,
        .stButton button[kind="primary"] * {{
            color: #fdf8f1 !important;
            opacity: 1 !important;
        }}
        .stFormSubmitButton button:hover,
        .stButton button[kind="primary"]:hover {{
            color: #fdf8f1 !important;
            background: color-mix(in srgb, var(--accent) 88%, #3b271e) !important;
            box-shadow: 0 14px 26px color-mix(in srgb, var(--accent) 26%, transparent) !important;
        }}
        div[data-testid="stTextInput"] input,
        div[data-testid="stNumberInput"] input,
        div[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
        textarea {{
            background: var(--surface) !important;
            border-color: var(--border) !important;
            border-radius: 12px !important;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.22) !important;
        }}
        div[data-testid="stTextInput"] input:focus,
        div[data-testid="stNumberInput"] input:focus,
        textarea:focus {{
            border-color: var(--accent) !important;
            box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 16%, transparent) !important;
        }}
        [data-testid="stExpander"] {{
            border-radius: 14px !important;
            border-color: var(--border) !important;
            background: color-mix(in srgb, var(--surface) 82%, var(--bg)) !important;
            box-shadow: none !important;
            margin: 0.55rem 0 !important;
        }}
        [data-testid="stExpander"] summary {{
            min-height: 2.75rem;
            color: var(--text) !important;
            font-weight: 750 !important;
        }}
        /* ── 风险承受能力 segmented_control：覆盖 Streamlit 内部深色背景 ── */
        [data-testid="stSegmentedControl"] {{
            margin-bottom: 0.2rem;
            background: var(--surface) !important;
            border: 1px solid var(--border) !important;
            border-radius: 999px !important;
            padding: 3px !important;
            gap: 2px !important;
        }}
        [data-testid="stSegmentedControl"] > div,
        [data-testid="stSegmentedControl"] > div > div {{
            background: transparent !important;
        }}
        [data-testid="stSegmentedControl"] button {{
            min-height: 2.2rem !important;
            border-radius: 999px !important;
            font-weight: 700 !important;
            background: transparent !important;
            color: var(--text-2) !important;
            border: none !important;
            box-shadow: none !important;
            opacity: 1 !important;
            font-size: 0.9rem !important;
        }}
        [data-testid="stSegmentedControl"] button *,
        [data-testid="stSegmentedControl"] button p,
        [data-testid="stSegmentedControl"] button span {{
            color: var(--text-2) !important;
            opacity: 1 !important;
            background: transparent !important;
        }}
        [data-testid="stSegmentedControl"] button[aria-pressed="true"],
        [data-testid="stSegmentedControl"] button[data-selected="true"],
        [data-testid="stSegmentedControl"] button[aria-selected="true"] {{
            background: var(--accent) !important;
            color: #fff !important;
            border: none !important;
            box-shadow: 0 2px 8px color-mix(in srgb, var(--accent) 30%, transparent) !important;
        }}
        [data-testid="stSegmentedControl"] button[aria-pressed="true"] *,
        [data-testid="stSegmentedControl"] button[data-selected="true"] *,
        [data-testid="stSegmentedControl"] button[aria-selected="true"] *,
        [data-testid="stSegmentedControl"] button[aria-pressed="true"] p,
        [data-testid="stSegmentedControl"] button[aria-selected="true"] p {{
            color: #fff !important;
            background: transparent !important;
        }}
        .verdict-card {{
            padding: 1.15rem !important;
            margin-bottom: 0.85rem !important;
            background: linear-gradient(180deg, var(--surface), color-mix(in srgb, var(--surface) 72%, var(--accent-soft))) !important;
        }}
        .verdict-card::after,
        .allocation-cash::after,
        .allocation-stock::after {{
            display: none !important;
            animation: none !important;
        }}
        .risk-status {{
            font-size: 1.45rem !important;
        }}
        .risk-light {{
            width: 2.65rem !important;
            height: 2.65rem !important;
            border-width: 3px !important;
            animation: none !important;
        }}
        .score-num {{
            color: var(--text) !important;
            text-shadow: none !important;
            font-size: 2.25rem !important;
        }}
        .metric-card::before, .metric-card-sm::before {{
            display: none !important;
        }}
        .risk-card-new {{
            border-left-width: 1px !important;
            box-shadow: 0 10px 28px rgba(48, 38, 28, 0.055) !important;
        }}
        .r-hi, .r-mid, .r-lo {{
            border-left-color: var(--border) !important;
        }}
        .agent-flow-card {{
            padding: 0.75rem !important;
            background: var(--surface) !important;
            border-color: var(--border) !important;
        }}
        .agent-flow-steps {{
            gap: 0.32rem !important;
        }}
        .agent-flow-steps span {{
            border-radius: 10px !important;
            background: var(--bg-2) !important;
            color: var(--text-2) !important;
            border-color: var(--border) !important;
            padding: 0.36rem 0.4rem !important;
        }}
        .agent-flow-steps b {{
            background: var(--surface) !important;
            color: var(--accent) !important;
        }}
        @media (max-width: 640px) {{
            .main .block-container,
            [data-testid="stAppViewContainer"] .main .block-container {{
                padding: 0.82rem 0.78rem 86px !important;
            }}
            .brand {{
                margin: 0.35rem 0 0.9rem;
            }}
            .fr-hero {{
                padding: 1.08rem 1rem 0.92rem;
            }}
            .fr-hero-title {{
                font-size: 1.22rem;
            }}
            .fr-hero-subtitle {{
                font-size: 0.88rem;
            }}
            .fr-agent-strip {{
                grid-template-columns: 1fr 1fr 1fr;
            }}
            .fr-agent-strip span {{
                font-size: 0.68rem;
                padding: 0.34rem 0.28rem;
            }}
            .risk-status {{
                font-size: 1.28rem !important;
            }}
            .score-dial {{
                display: none;
            }}
            .stButton button, .stDownloadButton button, .stFormSubmitButton button {{
                min-height: 2.75rem;
            }}
            [data-testid="stExpander"] summary {{
                min-height: 2.55rem;
            }}
        }}
        </style>
        """
    )


def inject_css() -> None:
    """Inject global CSS. String is cached per (dark_mode, font_size) pair."""
    render_html(_css_block(st.session_state.dark_mode, st.session_state.font_size))


def html_escape(value: Any) -> str:
    return escape(str(value if value is not None else ""))


def _hesc(d: dict, key: str, default: str = "") -> str:
    """html_escape a single key from a dict, with a safe default."""
    return html_escape(str(d.get(key, default) or default))


def _safe_ai_text(text: Any, max_len: int = 200) -> str:
    """Strip HTML/script from AI-generated strings before rendering in UI.

    Prevents prompt-injection echo (OWASP LLM01/LLM02): if a user crafts
    malicious input that makes DeepSeek reflect it back as parse_note or
    similar fields, this caps length and removes tags before display.
    """
    cleaned = str(text if text is not None else "")
    # Remove any HTML/script tags that DeepSeek might echo back
    import re as _re
    cleaned = _re.sub(r"<[^>]{0,200}>", "", cleaned)
    return cleaned[:max_len]


def site_header() -> None:
    render_html(site_header_html(APP_TITLE, APP_SUBTITLE))

@st.fragment
def display_settings() -> None:
    c1, c2, c3 = st.columns(3)
    if c1.button("A-", use_container_width=True, help="字号减小", key="toolbar_font_minus"):
        st.session_state.font_size = max(14, int(st.session_state.font_size) - 1)
    if c2.button("A+", use_container_width=True, help="字号增大", key="toolbar_font_plus"):
        st.session_state.font_size = min(22, int(st.session_state.font_size) + 1)
    label = "浅色" if st.session_state.dark_mode else "暗色"
    if c3.button(label, use_container_width=True, help="切换深色/浅色", key="toolbar_theme_toggle"):
        st.session_state.dark_mode = not st.session_state.dark_mode
    # 在 fragment 内重新注入 CSS，主题/字号立即生效，无需全页 rerun
    inject_css()


def top_toolbar() -> None:
    """全局顶部工具栏：紧凑的显示设置入口（字号/主题），所有页面都可见。

    放在 site_header 之后、页面主体之前。默认折叠，不抢占手机首屏。"""
    with st.expander("⚙️ 显示设置", expanded=False):
        display_settings()



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


def set_first_code(code: str) -> None:
    st.session_state["pending_code"] = normalize_code(code)


def risk_profile_hint_grid(selected: str) -> str:
    items = []
    for name in RISK_PROFILE_OPTIONS:
        cls = "risk-hint active" if name == selected else "risk-hint"
        items.append(
            f"""
            <div class="{cls}">
                <strong>{html_escape(name)}</strong>
                {html_escape(RISK_PROFILE_SHORT_HINTS.get(name, ""))}
            </div>
            """
        )
    return f'<div class="risk-hint-grid">{"".join(items)}</div>'


def _compact_amount(value: Any) -> str:
    amount = to_float(value)
    if amount is None or amount <= 0:
        return "未识别"
    if amount >= 10000:
        return f"{amount / 10000:.1f} 万"
    return f"{amount:,.0f} 元"


def _agent_intake_rows(parsed: dict[str, Any]) -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    for item in parsed.get("holdings") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("code") or item.get("name") or "").strip()
        amount = float(item.get("amount") or 0)
        if label and amount > 0:
            rows.append({"code": label, "amount": amount})
    return rows


def _agent_intake_summary_html(parsed: dict[str, Any]) -> str:
    holdings = _agent_intake_rows(parsed)
    if holdings:
        holding_items = "".join(
            f"<li>{html_escape(row['code'])}：{html_escape(_compact_amount(row['amount']))}</li>"
            for row in holdings[:5]
        )
        if len(holdings) > 5:
            holding_items += f"<li>另有 {len(holdings) - 5} 条持仓</li>"
    else:
        holding_items = "<li>还没有识别到持仓</li>"
    cash = float(parsed.get("cash") or 0)
    risk = str(parsed.get("risk_preference") or "").strip() or "未说明，暂按平衡"
    source = "DeepSeek 解析" if parsed.get("source") == "deepseek" else "本地规则解析"
    confidence = str(parsed.get("confidence") or "medium")
    confidence_label = {"high": "较高", "medium": "中等", "low": "较低"}.get(confidence, "中等")
    note = _safe_ai_text(parsed.get("parse_note", ""), 120)
    note_html = f"<p class='muted' style='margin:0.35rem 0 0;'>解析说明：{html_escape(note)}</p>" if note else ""
    return f"""
    <div class="card" style="padding:1rem;margin:0.75rem 0;background:var(--surface);">
        <div class="kicker">Agent 已识别</div>
        <ul style="margin:0.45rem 0 0.2rem;padding-left:1.15rem;color:var(--text);">{holding_items}</ul>
        <p style="margin:0.35rem 0;color:var(--text);">现金：<b>{html_escape(_compact_amount(cash))}</b></p>
        <p class="muted" style="margin:0.2rem 0 0;">来源：{html_escape(source)}，识别把握：{html_escape(confidence_label)}</p>
        {note_html}
    </div>
    """


def agent_intake_block() -> None:
    """Natural-language first intake: ask only the one missing family question."""
    render_html(
        """
        <div class="card" style="padding:1rem;margin:1rem 0 0.75rem;">
            <div class="kicker">Agent 入口</div>
            <h3 style="margin:0.25rem 0 0;font-size:1.05rem;">直接说一句，Agent 先帮你读</h3>
        </div>
        """
    )
    text = st.text_area(
        "一句话描述家庭持仓",
        placeholder="我家有茅台 2 万，现金 5 万，风险稳健，帮我看看。",
        height=96,
        key="agent_intake_text",
        label_visibility="collapsed",
    )
    parse_col, reset_col = st.columns([1.6, 1])
    with parse_col:
        if st.button("让 Agent 识别持仓", type="primary", use_container_width=True, key="agent_intake_parse"):
            if not str(text or "").strip():
                st.warning("先写一句持仓和现金情况，Agent 才能识别。")
            else:
                with st.spinner("Agent 正在识别股票、金额和现金..."):
                    parsed = parse_holdings_nl(str(text).strip())
                st.session_state["agent_intake_result"] = parsed
                risk = str(parsed.get("risk_preference") or "").strip()
                if risk in RISK_PROFILE_OPTIONS:
                    st.session_state["agent_intake_risk_profile"] = risk
                    st.session_state["risk_profile"] = risk
                cash = float(parsed.get("cash") or 0)
                if cash > 0:
                    st.session_state["agent_intake_cash_override"] = cash
                st.rerun()
    with reset_col:
        if st.button("清空重写", use_container_width=True, key="agent_intake_reset"):
            for key in ("agent_intake_result", "agent_intake_text", "agent_intake_cash_override"):
                st.session_state.pop(key, None)
            st.session_state["agent_intake_money_need_label"] = "不确定"
            st.rerun()

    parsed = st.session_state.get("agent_intake_result") or {}
    if not parsed:
        return

    render_html(_agent_intake_summary_html(parsed))
    rows = _agent_intake_rows(parsed)
    cash_value = float(parsed.get("cash") or 0)
    if cash_value <= 0:
        cash_value = float(st.session_state.get("agent_intake_cash_override") or 0)
        cash_value = st.number_input(
            "没有识别到现金，请补充账户现金余额（元）",
            min_value=0.0,
            step=1000.0,
            key="agent_intake_cash_override",
        )

    risk_default = str(parsed.get("risk_preference") or st.session_state.get("risk_profile") or "平衡")
    if risk_default not in RISK_PROFILE_OPTIONS:
        risk_default = "平衡"
    if st.session_state.get("agent_intake_risk_profile") not in RISK_PROFILE_OPTIONS:
        st.session_state["agent_intake_risk_profile"] = risk_default
    st.markdown('<div class="fr-field-label">风险偏好识别结果（可以改）</div>', unsafe_allow_html=True)
    if hasattr(st, "segmented_control"):
        _seg = st.segmented_control(
            "风险偏好",
            options=RISK_PROFILE_OPTIONS,
            key="agent_intake_risk_profile",
            label_visibility="collapsed",
        )
        # segmented_control 在用户主动取消选择时会返回 None，此时回退到 session_state 里上一次的值
        risk_profile = str(_seg) if _seg else str(
            st.session_state.get("agent_intake_risk_profile") or risk_default
        )
    else:
        risk_profile = str(st.selectbox(
            "风险偏好识别结果（可以改）",
            RISK_PROFILE_OPTIONS,
            index=RISK_PROFILE_OPTIONS.index(st.session_state.get("agent_intake_risk_profile", risk_default)),
            key="agent_intake_risk_profile",
            label_visibility="collapsed",
        ) or risk_default)
    st.caption(RISK_PROFILE_HINTS.get(risk_profile, ""))

    st.markdown("**关键追问**")
    st.caption("Agent 只补问一个问题：这笔钱半年内是否可能要用？")
    money_label = st.radio(
        "这笔钱半年内有没有可能要用？",
        _MONEY_NEED_LABELS,
        horizontal=True,
        key="agent_intake_money_need_label",
        label_visibility="collapsed",
    )

    if st.button("生成本次智能体检报告", type="primary", use_container_width=True, key="agent_intake_run"):
        if not rows:
            st.error("还没有识别到有效持仓。可以改写一句话，或展开下方手动填写。")
            return
        if float(cash_value or 0) <= 0:
            st.error("请补充账户现金余额（股票以外的钱）。")
            return
        reverse_qa = _normalize_reverse_qa(st.session_state.get("reverse_qa"))
        reverse_qa["money_need_6m"] = _MONEY_NEED_MAP.get(money_label, "uncertain")
        st.session_state["reverse_qa"] = reverse_qa
        st.session_state["risk_profile"] = risk_profile
        run_analysis(float(cash_value), risk_profile, rows)


def home_hero() -> None:
    render_html(
        f"""
        <div class="hero-card fr-hero">
            <div class="fr-hero-kicker">FamilyReader · AI</div>
            <h1 class="fr-hero-title">读懂家庭持仓风险</h1>
            <p class="fr-hero-subtitle">输入持仓和现金，Agent 会检查仓位、集中度、数据完整性，并生成家人能看懂的说明。</p>
            <div class="fr-agent-strip">
                <span>看结构</span>
                <span>讲清楚</span>
                <span>留记录</span>
            </div>
            <p class="fr-disclaimer">{HOME_DISCLAIMER}</p>
        </div>
        """
    )
    agent_intake_block()
    with st.expander("📝 手动逐项填写（AI 识别有误时使用）", expanded=False):
        portfolio_form()


def portfolio_form() -> None:
    pending_code = st.session_state.pop("pending_code", "")
    if pending_code:
        st.session_state["code_0"] = pending_code

    st.markdown('<div class="search-shell">', unsafe_allow_html=True)
    code_col, amount_col = st.columns([1.4, 1])
    with code_col:
        first_code = st.text_input(
            "股票代码或名称",
            key="code_0",
            placeholder="600519 或 贵州茅台",
        )
    with amount_col:
        first_amount = st.number_input(
            "持仓金额（元）",
            min_value=0.0,
            step=1000.0,
            key="amount_0",
        )

    # Handle row deletion before widgets render (must precede the expander)
    if "pending_delete_row" in st.session_state:
        _del = st.session_state.pop("pending_delete_row")
        for _j in range(_del, st.session_state.holding_rows - 1):
            st.session_state[f"code_{_j}"] = st.session_state.get(f"code_{_j + 1}", "")
            st.session_state[f"amount_{_j}"] = st.session_state.get(f"amount_{_j + 1}", 0.0)
        st.session_state.holding_rows = max(1, st.session_state.holding_rows - 1)

    with st.expander("＋ 添加更多持仓（可选）", expanded=False):
        st.markdown('<p class="muted">填写第 2 只及之后的持仓；不填也可以直接体检。</p>', unsafe_allow_html=True)
        for index in range(1, st.session_state.holding_rows):
            cols = st.columns([1.4, 1, 0.25])
            cols[0].text_input(
                f"第 {index + 1} 只股票",
                key=f"code_{index}",
                placeholder="代码或名称",
            )
            cols[1].number_input(
                f"第 {index + 1} 只金额（元）",
                min_value=0.0,
                step=1000.0,
                key=f"amount_{index}",
            )
            if cols[2].button("×", key=f"del_row_{index}", help="删除这条持仓"):
                st.session_state.pending_delete_row = index
                st.rerun()
        if st.button("＋ 继续添加一只", use_container_width=True, key="add_holding_row"):
            st.session_state.holding_rows += 1
            st.rerun()

    cash = st.number_input("账户现金余额（元）", min_value=0.0, value=0.0, step=1000.0)
    current_risk = str(st.session_state.get("risk_profile", "平衡") or "平衡")
    if current_risk not in RISK_PROFILE_OPTIONS:
        current_risk = "平衡"
        st.session_state["risk_profile"] = current_risk
    risk_profile = current_risk
    st.markdown('<div class="fr-field-label">家庭风险承受能力</div>', unsafe_allow_html=True)
    if hasattr(st, "segmented_control"):
        if st.session_state.get("risk_profile_segment") not in RISK_PROFILE_OPTIONS:
            st.session_state["risk_profile_segment"] = current_risk
        selected_risk = st.segmented_control(
            "家庭风险承受能力",
            options=RISK_PROFILE_OPTIONS,
            key="risk_profile_segment",
            label_visibility="collapsed",
        )
        if selected_risk and selected_risk != current_risk:
            st.session_state["risk_profile"] = selected_risk
            risk_profile = str(selected_risk)
            current_risk = str(selected_risk)
    else:
        _rc1 = st.columns(3)
        _rc2 = st.columns([1, 1, 2])
        for _i, _n in enumerate(RISK_PROFILE_OPTIONS[:3]):
            with _rc1[_i]:
                if st.button(_n, key=f"risk_btn_{_n}", use_container_width=True,
                             type="primary" if _n == current_risk else "secondary"):
                    st.session_state["risk_profile"] = _n
                    st.rerun()
        for _i, _n in enumerate(RISK_PROFILE_OPTIONS[3:]):
            with _rc2[_i]:
                if st.button(_n, key=f"risk_btn_{_n}", use_container_width=True,
                             type="primary" if _n == current_risk else "secondary"):
                    st.session_state["risk_profile"] = _n
                    st.rerun()
    st.markdown(
        f'<div class="fr-risk-note"><b>{html_escape(current_risk)}</b>'
        f'{html_escape(RISK_PROFILE_HINTS.get(current_risk, ""))}</div>',
        unsafe_allow_html=True,
    )

    submitted = st.button("开始一键智能体检", type="primary", use_container_width=True)

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
        # resolve_code_or_name handles both numeric codes and Chinese stock names
        label = str(row.get("code", "")).strip()
        code = resolve_code_or_name(label)
        # If name lookup fails but we have a non-empty label (e.g. unlisted stock),
        # keep the label as-is — agent's missing_data path handles it gracefully.
        if not code and label:
            code = label
        amount = float(row.get("amount", 0) or 0)
        if code and amount > 0:
            holdings.append({"code": code, "amount": amount})
    return holdings


AGENT_PROGRESS_STEPS = [
    "检查输入是否完整",
    "读取行情和财务缓存",
    "计算持仓比例和现金比例",
    "识别集中风险和数据缺失",
    "读取历史和家庭观察",
    "组装 agent_context",
    "调用 DeepSeek 生成 AI 风险说明",
    "保存历史记录到 Supabase",
    "准备智能追问建议",
    "完成体检",
]

# 对用户展示的友好文案（与 AGENT_PROGRESS_STEPS 一一对应）
_STEP_LABELS = [
    "检查持仓输入是否完整",
    "读取行情和财务数据",
    "计算持仓比例和现金比例",
    "识别集中风险和数据缺失",
    "读取历史体检记录和家庭观察",
    "整理本次体检数据",
    "AI 正在生成风险说明（需几秒）",
    "保存本次记录",
    "准备追问建议",
    "体检完成 ✓",
]


def render_agent_progress(
    card_placeholder: Any,
    detail_placeholder: Any,
    current_step: str,
    percent_value: int,
) -> None:
    percent_value = max(0, min(100, int(percent_value)))

    # ── 顶部进度卡（极简）──────────────────────────────────────
    with card_placeholder.container():
        st.markdown("**智能体检进行中…**")
        st.progress(percent_value)

    # ── 步骤列表：按进度逐条揭示 ───────────────────────────────
    try:
        current_index = AGENT_PROGRESS_STEPS.index(current_step)
    except ValueError:
        current_index = 0

    done_all = percent_value >= 100
    rows_html = ""
    for idx in range(current_index + 1):          # 只显示已到达的步骤
        label = _STEP_LABELS[idx] if idx < len(_STEP_LABELS) else AGENT_PROGRESS_STEPS[idx]
        if idx < current_index or done_all:
            # 已完成：细小勾 + 灰色文字
            rows_html += (
                f'<div style="display:flex;align-items:center;gap:0.55rem;padding:0.25rem 0;">'
                f'<span style="color:#7a3e2e;font-size:0.78rem;width:1em;text-align:center;flex-shrink:0;">✓</span>'
                f'<span style="font-size:0.82rem;color:var(--text-3);">{html_escape(label)}</span>'
                f'</div>'
            )
        else:
            # 进行中：转圈 + 正常色粗体
            rows_html += (
                f'<div style="display:flex;align-items:center;gap:0.55rem;padding:0.28rem 0;">'
                f'<span class="fi-spinner"></span>'
                f'<span style="font-size:0.87rem;color:var(--text);font-weight:600;">{html_escape(label)}</span>'
                f'</div>'
            )

    with detail_placeholder.container():
        render_html(
            f'<div style="padding:0.1rem 0 0.3rem;">{rows_html}</div>'
        )


def _safe_error_text(value: Any) -> str:
    text = str(value or "")
    for secret_name in ("DEEPSEEK_API_KEY", "SUPABASE_KEY", "SUPABASE_URL"):
        secret_value = ""
        try:
            secret_value = str(st.secrets.get(secret_name, "")).strip()
        except Exception:  # noqa: BLE001
            secret_value = ""
        env_value = os.getenv(secret_name, "").strip()
        for raw in (secret_value, env_value):
            if raw:
                text = text.replace(raw, "***")
    return text[:800]


def _build_agent_error_info(exc: Exception) -> dict[str, Any]:
    diagnostics = get_cache_diagnostics()
    return {
        "错误类型": type(exc).__name__,
        "错误信息": _safe_error_text(exc),
        "当前工作目录": diagnostics.get("cwd", os.getcwd()),
        "stock_metrics.csv 检查路径": diagnostics.get("checked_paths", []),
        "已找到缓存文件": diagnostics.get("found_path", "") or "未找到",
    }


def render_error_debug(error_info: dict[str, Any] | None) -> None:
    if not error_info:
        return
    with st.expander("开发者信息 / 调试详情", expanded=False):
        st.write(f"- 错误类型：{error_info.get('错误类型', '')}")
        st.write(f"- 错误信息：{error_info.get('错误信息', '')}")
        st.write(f"- 当前工作目录：{error_info.get('当前工作目录', '')}")
        st.write("- stock_metrics.csv 检查过的路径：")
        for path in error_info.get("stock_metrics.csv 检查路径", []) or []:
            st.write(f"  - {path}")
        st.write(f"- 已找到缓存文件：{error_info.get('已找到缓存文件', '')}")


def run_analysis(cash: float, risk_profile: str, raw_rows: list[dict[str, float | str]]) -> None:
    holdings = clean_holdings(raw_rows)
    if not holdings:
        st.error("请至少填写一只持仓，并填写大于 0 的持仓金额。")
        st.stop()

    try:
        progress_card = st.empty()
        progress_detail = st.empty()
        render_agent_progress(progress_card, progress_detail, "检查输入是否完整", 0)

        def update_progress(step: str, percent_value: int) -> None:
            render_agent_progress(progress_card, progress_detail, step, percent_value)

        agent_result = run_family_risk_agent(
            holdings=holdings,
            family_cash=cash,
            risk_preference=risk_profile,
            user_goal="检查家庭持仓风险",
            reverse_qa=_normalize_reverse_qa(st.session_state.get("reverse_qa")),
            progress_callback=update_progress,
        )
        if agent_result.get("report_source") == "local_fallback":
            st.info("DeepSeek 暂时不可用，已使用本地规则兜底生成。")
        storage_status = agent_result.get("storage_status", {})
        if agent_result.get("saved_history") and storage_status.get("backend") == "local_csv":
            st.info("云端保存失败，已使用本地兜底。")
        render_agent_progress(progress_card, progress_detail, "完成体检", 100)
        if not agent_result.get("success"):
            for warning in agent_result.get("warnings", []):
                st.warning(warning)
            st.error("智能体检没有完成，请检查持仓代码和金额。")
            st.stop()

        analysis = agent_result["analysis"]
        stocks = agent_result["stocks"]
        st.session_state["analysis"] = analysis
        st.session_state["stocks"] = stocks
        st.session_state["holdings"] = holdings
        st.session_state["fetch_warnings"] = agent_result.get("warnings", [])
        st.session_state["agent_result"] = agent_result
        st.session_state.pop("ai_report", None)
        st.session_state.pop("ai_report_failed", None)
        st.session_state.pop("followup_answers", None)
        st.session_state.pop("followup_questions", None)  # 新一次体检，重新随机生成问题
        st.session_state.pop("last_agent_error", None)
        st.session_state["report_mode"] = DEFAULT_REPORT_MODE
        st.session_state["active_view"] = "analysis"
        st.rerun()
    except Exception as exc:  # noqa: BLE001
        error_info = _build_agent_error_info(exc)
        st.session_state["last_agent_error"] = error_info
        st.error("体检时遇到问题，但页面没有崩。请稍后重试，或检查 stock_metrics.csv 是否存在。")
        render_error_debug(error_info)
        st.stop()


def cache_tools() -> None:
    with st.expander("数据缓存（可选）", expanded=False):
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
        st.caption("日常使用不需要点这里。页面默认读取本地缓存，更新接口可能受网络影响。")
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
    # 显示设置已移到全局 top_toolbar()，所有页面都能调整字号/主题


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


STOCK_FIELD_ALIASES = {
    "code": "股票代码",
    "name": "股票名称",
    "industry": "所属行业",
    "price": "最新收盘价",
    "pct_change": "涨跌幅",
    "turnover": "成交额",
    "pe": "市盈率-动态",
    "pb": "市净率",
    "turnover_rate": "换手率",
    "market_cap": "总市值",
    "float_market_cap": "流通市值",
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
    "data_source": "数据来源",
    "updated_at": "更新时间",
}


def stock_field(stock: dict[str, Any], field: str) -> Any:
    value = stock.get(field)
    if value is not None:
        return value
    legacy_name = STOCK_FIELD_ALIASES.get(field)
    if legacy_name:
        return stock.get(legacy_name)
    return None


def fmt_ratio(value: Any, default: str = "财务数据暂缺") -> str:
    number = to_float(value)
    if number is None:
        return default
    return f"{number * 100:.2f}%"


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


def score_dial(score: int, ring_color: str = "var(--accent)") -> str:
    radius = 52
    circumference = 2 * pi * radius
    offset = circumference * (1 - max(0, min(100, score)) / 100)
    # 双圈：底部虚线轨道 + 顶部实心进度弧
    return f"""
    <div class="score-dial">
        <svg width="136" height="136" viewBox="0 0 136 136" aria-label="综合评分 {score}/100">
            <!-- 背景轨道 -->
            <circle cx="68" cy="68" r="{radius}" stroke="var(--border)" stroke-width="8"
                    fill="none" stroke-dasharray="4 3"
                    transform="rotate(-90 68 68)"></circle>
            <!-- 进度弧（带圆角）-->
            <circle cx="68" cy="68" r="{radius}" stroke="{ring_color}" stroke-width="9" fill="none"
                    stroke-linecap="round" transform="rotate(-90 68 68)"
                    stroke-dasharray="{circumference:.2f}" stroke-dashoffset="{offset:.2f}"
                    style="filter:drop-shadow(0 0 6px {ring_color})"></circle>
            <!-- 评分数字 -->
            <text x="68" y="64" text-anchor="middle" dominant-baseline="middle"
                  font-size="40" font-weight="700" fill="{ring_color}"
                  font-family="JetBrains Mono,Inter,monospace">{score}</text>
            <!-- 单位 -->
            <text x="68" y="86" text-anchor="middle"
                  font-size="12" fill="var(--text-3)"
                  font-family="JetBrains Mono,Inter,monospace" letter-spacing="1">/100</text>
        </svg>
        <div class="score-caption">综合评分</div>
    </div>
    """


def risk_signal_info(score: int, raw_level: str = "") -> dict[str, str]:
    text = str(raw_level or "")
    if "无法" in text or score <= 0:
        return {
            "class": "risk-neutral",
            "status": "暂无法判断",
            "caption": "请先确认持仓和缓存数据",
            "color": "#9b9288",
        }
    if "红" in text or score < 60:
        return {
            "class": "risk-red",
            "status": "风险偏高",
            "caption": "先看现金、单只占比和家庭承受能力",
            "color": "#c85a4a",
        }
    if "黄" in text or score < 80:
        return {
            "class": "risk-yellow",
            "status": "需要注意",
            "caption": "有风险点需要持续观察",
            "color": "#dfb844",
        }
    return {
        "class": "risk-green",
        "status": "风险较低",
        "caption": "结构相对可控，但仍需定期复盘",
        "color": "#4e9f68",
    }


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
    industry = first_result.get("industry") or stock_field(stock, "industry") or "行业待补充"
    change = to_float(stock_field(stock, "pct_change"))
    price = fmt_optional(stock_field(stock, "price"))
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
                    <div class="kv"><dt>总市值</dt><dd>{fmt_market_cap(stock_field(stock, "market_cap"))}</dd></div>
                    <div class="kv"><dt>市盈率 PE</dt><dd>{fmt_optional(stock_field(stock, "pe"), default="估值数据暂缺")}</dd></div>
                    <div class="kv"><dt>市净率 PB</dt><dd>{fmt_optional(stock_field(stock, "pb"), default="估值数据暂缺")}</dd></div>
                    <div class="kv"><dt>更新时间</dt><dd>{html_escape(stock_field(stock, "updated_at") or "暂无")}</dd></div>
                </dl>
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
        ("PE", fmt_optional(stock_field(stock, "pe"), default="估值数据暂缺"), "估值指标，越高越需要解释增长来源"),
        ("PB", fmt_optional(stock_field(stock, "pb"), default="估值数据暂缺"), "股价相对账面资产的倍数"),
        ("ROE", fmt_ratio(stock_field(stock, "roe")), "公司用自己的钱赚钱的能力"),
        ("净利率", fmt_ratio(stock_field(stock, "net_margin")), "每卖出100元最终留下多少利润"),
        ("毛利率", fmt_ratio(stock_field(stock, "gross_margin")), "产品本身的赚钱空间"),
        ("资产负债率", fmt_ratio(stock_field(stock, "debt_ratio")), "公司借了多少钱相对自己的家底"),
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


def watch_tasks_block(agent_result: dict[str, Any]) -> None:
    """体检后待办卡：展示 agent 生成的结构化观察任务。"""
    tasks: list[dict[str, Any]] = list(agent_result.get("watch_tasks") or [])
    if not tasks:
        return

    _PRIORITY_STYLE = {
        "high":   ("高", "#b94040", "#fff5f5"),
        "medium": ("中", "#b97a1a", "#fff9f0"),
        "low":    ("低", "#666",    "#f5f5f5"),
    }
    _CATEGORY_ICON = {
        "cash":          "💰",
        "concentration": "📊",
        "industry":      "🏭",
        "data":          "📋",
        "history":       "🔄",
        "general":       "⚠️",
    }

    rows_html = ""
    for task in tasks:
        priority = task.get("priority", "medium")
        label, color, bg = _PRIORITY_STYLE.get(priority, _PRIORITY_STYLE["medium"])
        icon = _CATEGORY_ICON.get(task.get("category", "general"), "⚠️")
        title = html_escape(str(task.get("title", "")))
        desc  = html_escape(str(task.get("desc", "")))
        status = html_escape(str(task.get("status", "待观察") or "待观察"))
        rows_html += f"""
        <li style="display:flex;gap:0.65rem;padding:0.55rem 0.9rem;
                   border-bottom:1px solid var(--border);align-items:flex-start;">
            <span style="flex-shrink:0;font-size:1rem;margin-top:0.05rem;">{icon}</span>
            <div style="min-width:0;flex:1;">
                <div style="display:flex;align-items:center;gap:0.45rem;margin-bottom:0.18rem;">
                    <span style="font-size:0.82rem;font-weight:700;color:var(--text);">{title}</span>
                    <span style="font-size:0.65rem;font-weight:700;color:{color};
                                 background:{bg};padding:0.1rem 0.45rem;border-radius:10px;
                                 white-space:nowrap;">{label}</span>
                    <span style="font-size:0.65rem;color:var(--text-3);white-space:nowrap;">{status}</span>
                </div>
                <p style="font-size:0.78rem;color:var(--text-2);margin:0;line-height:1.5;">{desc}</p>
            </div>
        </li>"""

    render_html(f"""
    <section style="margin:0.8rem 0;border-radius:12px;
                    border:1px solid var(--border);background:var(--surface);overflow:hidden;">
        <div style="padding:0.5rem 0.9rem;display:flex;align-items:center;
                    justify-content:space-between;border-bottom:1px solid var(--border);">
            <span style="font-size:0.9rem;font-weight:700;color:var(--text);">📌&nbsp;体检后待办</span>
            <span style="font-size:0.72rem;color:var(--text-3);">共 {len(tasks)} 项</span>
        </div>
        <ul style="margin:0;padding:0;list-style:none;">{rows_html}</ul>
    </section>
    """)


def stress_test_block(agent_result: dict[str, Any]) -> None:
    """极端情景压力测试卡：让家人直观感受"最坏情况下全家会缩水多少"。

    纯展示 agent 已算好的结构化情景，不做任何预测，不给交易建议。
    """
    stress = agent_result.get("stress_test") or {}
    if not stress.get("available"):
        return
    scenarios = list(stress.get("scenarios") or [])
    if not scenarios:
        return

    _SEV_STYLE = {
        "severe":  ("影响重大", "#b91c1c", "#fef2f2"),
        "notable": ("影响明显", "#92400e", "#fffbeb"),
        "mild":    ("影响有限", "#15803d", "#f0fdf4"),
    }

    rows_html = ""
    for sc in scenarios:
        sev = str(sc.get("severity") or "mild")
        sev_label, fg, bg = _SEV_STYLE.get(sev, _SEV_STYLE["mild"])
        title = html_escape(str(sc.get("title", "")))
        shock = float(sc.get("shock_pct", 0) or 0)
        plain = html_escape(str(sc.get("plain", "")))
        cushion = html_escape(str(sc.get("cushion_note", "")))
        rows_html += f"""
        <li style="padding:0.6rem 0.9rem;border-bottom:1px solid var(--border);
                   border-left:4px solid {fg};">
            <div style="display:flex;align-items:center;gap:0.45rem;margin-bottom:0.25rem;
                        flex-wrap:wrap;">
                <span style="font-size:0.84rem;font-weight:700;color:var(--text);">{title}</span>
                <span style="font-size:0.65rem;font-weight:700;color:#fff;background:{fg};
                             padding:0.1rem 0.45rem;border-radius:10px;white-space:nowrap;">
                    假设跌 {shock:.0%}
                </span>
                <span style="font-size:0.65rem;font-weight:700;color:{fg};background:{bg};
                             padding:0.1rem 0.45rem;border-radius:10px;white-space:nowrap;">{sev_label}</span>
            </div>
            <p style="font-size:0.8rem;color:var(--text);margin:0 0 0.2rem;line-height:1.55;">{plain}</p>
            <p style="font-size:0.74rem;color:var(--text-2);margin:0;line-height:1.5;">{cushion}</p>
        </li>"""

    worst = stress.get("worst_case") or {}
    worst_loss = float(worst.get("loss", 0) or 0)
    worst_loss_text = f"{worst_loss / 10000:.1f} 万元" if abs(worst_loss) >= 10000 else f"{worst_loss:.0f} 元"
    summary = html_escape(str(stress.get("summary", "")))
    disclaimer = html_escape(str(stress.get("disclaimer", "")))

    render_html(f"""
    <section style="margin:0.8rem 0;border-radius:12px;
                    border:1px solid var(--border);background:var(--surface);overflow:hidden;">
        <div style="padding:0.55rem 0.9rem;display:flex;align-items:center;
                    justify-content:space-between;border-bottom:1px solid var(--border);
                    gap:0.6rem;flex-wrap:wrap;">
            <span style="font-size:0.9rem;font-weight:700;color:var(--text);">🌧️&nbsp;极端情景压力测试</span>
            <span style="font-size:0.72rem;color:var(--text-3);">最坏约缩水 {html_escape(worst_loss_text)}</span>
        </div>
        <ul style="margin:0;padding:0;list-style:none;">{rows_html}</ul>
        <div style="padding:0.5rem 0.9rem;border-top:1px solid var(--border);">
            <p style="font-size:0.72rem;color:var(--text-3);margin:0;line-height:1.5;">{disclaimer}</p>
        </div>
    </section>
    """)
    if summary:
        st.caption(summary)


def agent_focus_block(agent_result: dict[str, Any]) -> None:
    """Agent 主动选择本次最值得先看的 1-2 个重点。"""
    risk_factors = agent_result.get("risk_factors") or {}
    top_focus = [item for item in list(risk_factors.get("top_focus") or []) if isinstance(item, dict)]
    confidence = agent_result.get("data_confidence") or {}
    missing_data = agent_result.get("missing_data") or {}
    if not top_focus and not confidence:
        return

    chips = "".join(
        f"""
        <div style="border:1px solid var(--border);border-radius:12px;background:var(--surface);
                    padding:0.65rem 0.75rem;">
            <div style="display:flex;justify-content:space-between;gap:0.5rem;align-items:center;">
                <strong style="font-size:0.88rem;color:var(--text);">{html_escape(str(item.get("name") or ""))}</strong>
                <span style="font-size:0.68rem;color:#7a3e2e;background:rgba(122,62,46,0.08);
                             border-radius:999px;padding:0.12rem 0.42rem;white-space:nowrap;">
                    {html_escape(str(item.get("status") or "继续观察"))}
                </span>
            </div>
            <p style="font-size:0.76rem;color:var(--text-2);line-height:1.45;margin:0.32rem 0 0;">
                {html_escape(str(item.get("why") or item.get("plain") or ""))}
            </p>
        </div>
        """
        for item in top_focus[:2]
    )
    conf_text = str(confidence.get("summary") or "")
    confidence_issues = [
        str(item).strip()
        for item in list(confidence.get("issues") or [])
        if str(item).strip()
    ]
    missing_sections: list[str] = []
    for title, items in missing_data.items():
        valid_items = [str(item).strip() for item in list(items or []) if str(item).strip()]
        if not valid_items:
            continue
        preview = "、".join(html_escape(item) for item in valid_items[:3])
        remainder = len(valid_items) - 3
        if remainder > 0:
            preview = f"{preview} 等 {len(valid_items)} 只"
        note = "本次不评价估值高低" if "估值" in str(title) else "已按保守口径处理"
        missing_sections.append(
            f"""
            <li style="margin:0.18rem 0;line-height:1.5;">
                <strong style="color:var(--text);">{html_escape(str(title))}</strong>
                <span style="color:var(--text-2);">：{preview}</span>
                <span style="color:var(--text-3);">（{html_escape(note)}）</span>
            </li>
            """
        )
    missing_html = (
        f"""
        <div style="margin-top:0.55rem;padding:0.58rem 0.7rem;border-radius:10px;
                    border:1px solid rgba(185,122,26,0.22);background:rgba(185,122,26,0.07);">
            <div style="font-size:0.73rem;font-weight:700;color:var(--text);margin-bottom:0.16rem;">
                这次缺失的数据
            </div>
            <ul style="margin:0;padding-left:1rem;font-size:0.74rem;color:var(--text-2);">
                {''.join(missing_sections)}
            </ul>
        </div>
        """
    ) if missing_sections else ""
    # 外层 expander 标题已包含 "Agent 主动判断" 和数据可信度，此处不再重复显示
    _conf_inline_html = (
        f'<p style="font-size:0.74rem;color:var(--text-3);margin:0.5rem 0 0;">'
        f'{html_escape(conf_text)}</p>'
    ) if conf_text else ""
    issue_html = (
        f"""
        <ul style="margin:0.42rem 0 0;padding-left:1rem;font-size:0.73rem;color:var(--text-3);">
            {''.join(f'<li style="margin:0.14rem 0;">{html_escape(item)}</li>' for item in confidence_issues[:3])}
        </ul>
        """
    ) if confidence_issues else ""
    render_html(
        f"""
        <section style="margin:0 0 0.55rem;border:1.5px solid var(--border);
                        background:var(--surface);border-radius:14px;padding:0.8rem 0.9rem;">
            <h3 style="font-size:1rem;color:var(--text);margin:0 0 0.55rem;">这次最该先看什么</h3>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:0.5rem;">
                {chips}
            </div>
            {_conf_inline_html}
            {issue_html}
            {missing_html}
        </section>
        """
    )


def task_review_block(agent_result: dict[str, Any]) -> None:
    review = agent_result.get("task_review") or {}
    if not review.get("has_review"):
        return
    items = [item for item in list(review.get("items") or []) if isinstance(item, dict)]
    if not items:
        return
    rows = "".join(
        f"""
        <li style="padding:0.45rem 0;border-bottom:1px solid var(--border);">
            <div style="display:flex;gap:0.5rem;align-items:center;">
                <strong style="font-size:0.82rem;color:var(--text);">{html_escape(str(item.get("title") or ""))}</strong>
                <span style="font-size:0.68rem;color:var(--text-3);margin-left:auto;white-space:nowrap;">
                    {html_escape(str(item.get("status") or ""))}
                </span>
            </div>
            <p style="font-size:0.76rem;color:var(--text-2);line-height:1.45;margin:0.22rem 0 0;">
                {html_escape(str(item.get("note") or ""))}
            </p>
        </li>
        """
        for item in items[:4]
    )
    render_html(
        f"""
        <section style="margin:0.6rem 0;border:1px solid var(--border);
                        background:var(--surface);border-radius:12px;padding:0.7rem 0.9rem;">
            <div style="font-size:0.9rem;font-weight:800;color:var(--text);">上次观察任务回看</div>
            <p style="font-size:0.74rem;color:var(--text-3);margin:0.18rem 0 0.35rem;">
                {html_escape(str(review.get("summary") or ""))}
            </p>
            <ul style="list-style:none;margin:0;padding:0;">{rows}</ul>
        </section>
        """
    )


def _portfolio_fin_metrics(stock_results: list[dict]) -> dict[str, Any]:
    """按持仓金额加权汇总财务指标。
    PE / PB 用调和加权平均（行业标准，避免高值标的过度拉高）。
    ROE / 净利率 / 毛利率 / 资产负债率 用算术加权平均。
    任一指标在所有持仓中均缺失时返回 None，供调用方显示"暂缺"。
    """
    if not stock_results:
        return {}

    def _harm(key: str) -> float | None:
        """调和加权平均：只纳入正值持仓。"""
        pairs: list[tuple[float, float]] = []
        for s in stock_results:
            v = s.get(key)
            w = float(s.get("amount") or 0)
            if v is None or w <= 0:
                continue
            try:
                fv = float(v)
                if fv > 0:
                    pairs.append((fv, w))
            except (TypeError, ValueError):
                pass
        if not pairs:
            return None
        total_w = sum(w for _, w in pairs)
        denom = sum(w / v for v, w in pairs)
        return total_w / denom if denom > 0 else None

    def _wt(key: str) -> float | None:
        """算术加权平均：纳入有有效数值的持仓。"""
        pairs: list[tuple[float, float]] = []
        for s in stock_results:
            v = s.get(key)
            w = float(s.get("amount") or 0)
            if v is None or w <= 0:
                continue
            try:
                pairs.append((float(v), w))
            except (TypeError, ValueError):
                pass
        if not pairs:
            return None
        total_w = sum(w for _, w in pairs)
        return sum(v * w for v, w in pairs) / total_w if total_w > 0 else None

    return {
        "pe":            _harm("pe"),
        "pb":            _harm("pb"),
        "roe":           _wt("roe"),
        "dividend_yield": _wt("dividend_yield"),
        # 净利率 / 毛利率 / 资产负债率 跨行业平均无意义，不在概览卡展示
    }


def portfolio_metrics_block(summary: dict[str, Any], analysis: dict[str, Any]) -> None:
    """合并版指标卡：持仓结构 + 核心财务，两列紧凑布局，去除重复。"""
    if not analysis:
        return
    stock_results = list(analysis.get("stock_results") or [])
    fin = _portfolio_fin_metrics(stock_results)
    n_stocks = len(stock_results)
    # 多只持仓时注明这是加权平均值，让家人理解数字来源
    fin_note_pe = "持仓加权平均（调和）" if n_stocks > 1 else "估值高低参考"
    block_subtitle = (
        "持仓结构 · 核心财务 · 财务指标按持仓金额加权平均"
        if n_stocks > 1
        else "持仓结构 · 核心财务 · 数据来源：最近报告期"
    )

    cash_ratio  = max(0.0, min(1.0, float(summary.get("cash_ratio",  0) or 0)))
    stock_ratio = max(0.0, min(1.0, float(summary.get("stock_ratio", 0) or 0)))
    top_industry = str(analysis.get("top_industry") or "")
    ind_conc     = float(analysis.get("industry_concentration") or 0)

    rows = [
        ("家庭总资产",   money(float(summary.get("total_assets", 0) or 0)),                      "现金 + 持仓合计"),
        ("现金比例",     percent(cash_ratio),                                                      "备用金厚度"),
        ("股息率",        fmt_ratio(fin.get("dividend_yield"), default="暂缺"),                   "持仓加权分红回报率"),
        ("单只最大占比", percent(float(summary.get("max_single_ratio", 0) or 0)),                 "集中度风险参考"),
        ("行业集中度",   f"{html_escape(top_industry)}&nbsp;{percent(ind_conc)}" if top_industry else "暂无", "行业分布是否过于集中"),
        ("PE 市盈率",    fmt_optional(fin.get("pe"),  default="暂缺"),  fin_note_pe),
        ("PB 市净率",    fmt_optional(fin.get("pb"),  default="暂缺"),  fin_note_pe),
        # ROE 保留：衡量持仓公司整体赚钱效率，加权平均有意义
        # 净利率 / 毛利率 / 资产负债率 已移至各持仓详细卡，跨行业平均无意义
        ("ROE",          fmt_ratio(fin.get("roe")),                      "持仓加权：公司赚钱效率"),
    ]
    cards = "".join(
        f'<article class="metric-card-sm">'
        f'<div class="metric-label">{label}</div>'
        f'<div class="metric-value-sm">{value}</div>'
        f'<div class="metric-note-sm">{note}</div>'
        f'</article>'
        for label, value, note in rows
    )
    render_html(
        f"""
        <section class="block">
            <div class="block-head" style="margin-bottom:.6rem;">
                <div>
                    <h2 class="block-title">体检数据一览</h2>
                    <p class="block-subtitle">{block_subtitle}</p>
                </div>
            </div>
            <div class="metric-grid-2">{cards}</div>
            <div style="margin-top:.9rem;">
                <div class="allocation-bar" aria-label="资产配置">
                    <div class="allocation-cash"  style="width:{cash_ratio  * 100:.1f}%"></div>
                    <div class="allocation-stock" style="width:{stock_ratio * 100:.1f}%"></div>
                </div>
                <p class="muted" style="margin-top:.3rem;">沉松绿代表现金，暖金代表股票/基金。</p>
            </div>
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


def financial_insight_card(item: dict[str, Any]) -> None:
    """为单只持仓渲染公司底子说明卡、交易热度卡和仓位说明卡。"""

    def _tone(score: float) -> tuple[str, str, str]:
        """返回 (标签, 文字色, 背景色)。"""
        if score >= 75:
            return "稳", "#3f7d55", "rgba(63,125,85,0.10)"
        if score >= 55:
            return "看", "#b97a1a", "rgba(185,122,26,0.10)"
        return "紧", "#b94040", "rgba(185,64,64,0.10)"

    def _badge(label: str, fg: str, bg: str, score: float) -> str:
        return (
            f'<span style="font-size:0.68rem;font-weight:700;color:{fg};'
            f'background:{bg};border-radius:6px;padding:0.1rem 0.48rem;">'
            f'{label}&nbsp;{score:.0f}</span>'
        )

    def _notes_html(notes: list[str], limit: int = 3) -> str:
        return "".join(
            f'<li style="font-size:0.8rem;color:var(--text);'
            f'margin:0.1rem 0;line-height:1.45;">{html_escape(n)}</li>'
            for n in notes[:limit]
        )

    def _card(icon: str, title: str, badge_html: str, subtitle: str,
              notes_html: str) -> str:
        return (
            f'<div style="border:1px solid rgba(0,0,0,0.08);border-radius:10px;'
            f'padding:0.65rem 0.9rem;margin:0.3rem 0;">'
            f'<div style="display:flex;align-items:center;gap:0.45rem;margin-bottom:0.3rem;">'
            f'<span style="font-size:0.88rem;">{icon}</span>'
            f'<span style="font-size:0.85rem;font-weight:700;color:var(--text);">{title}</span>'
            f'{badge_html}'
            f'</div>'
            f'<p style="font-size:0.73rem;color:var(--text-3);margin:0 0 0.28rem;">{subtitle}</p>'
            f'<ul style="margin:0;padding-left:0.9rem;list-style:disc;">{notes_html}</ul>'
            f'</div>'
        )

    # ── 公司底子 ────────────────────────────────────────────────
    fin_score = float(item.get("financial_score") or 0)
    fin_label, fin_fg, fin_bg = _tone(fin_score)
    fin_text  = str(item.get("financial_text") or "")
    fin_notes = list(item.get("financial_notes") or [])

    _FIN_METRICS = [
        ("roe",        "ROE",    100, "%"),
        ("net_margin", "净利率", 100, "%"),
        ("debt_ratio", "负债率", 100, "%"),
        ("pe",         "PE",     1,   ""),
        ("pb",         "PB",     1,   ""),
    ]
    metrics: list[str] = []
    for raw_key, display, mult, unit in _FIN_METRICS:
        val = item.get(raw_key)
        if val is not None:
            try:
                metrics.append(f"{display} {float(val) * mult:.1f}{unit}")
            except (TypeError, ValueError):
                pass
    metrics_str = "　".join(metrics) if metrics else "核心指标暂缺"

    fin_sub_notes = ([fin_text] if fin_text else []) + fin_notes
    render_html(_card(
        "📊", "公司底子",
        _badge(fin_label, fin_fg, fin_bg, fin_score),
        metrics_str,
        _notes_html(fin_sub_notes, limit=3),
    ))

    # ── 交易热度 ────────────────────────────────────────────────
    heat_score = float(item.get("heat_score") or 0)
    heat_label, heat_fg, heat_bg = _tone(heat_score)
    heat_text  = str(item.get("heat_text") or "")
    heat_notes = list(item.get("heat_notes") or [])
    heat_sub   = ([heat_text] if heat_text else []) + heat_notes
    render_html(_card(
        "🌡", "交易热度",
        _badge(heat_label, heat_fg, heat_bg, heat_score),
        "换手率 / 量比 / 振幅 / 涨跌幅",
        _notes_html(heat_sub, limit=2),
    ))

    # ── 仓位占比 ────────────────────────────────────────────────
    pos_notes    = list(item.get("position_notes") or [])
    single_ratio = float(item.get("single_ratio") or 0)
    render_html(_card(
        "⚖️", "持仓占比",
        f'<span style="font-size:0.72rem;color:var(--text-3);">'
        f'占家庭总资产 {single_ratio * 100:.1f}%</span>',
        "单只集中度 / 整体仓位 / 风险承受匹配",
        _notes_html(pos_notes, limit=2),
    ))


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
        with st.expander(f"📊 {item['name']} 底子说明", expanded=False):
            financial_insight_card(item)


def risk_grid(analysis: dict[str, Any]) -> None:
    notes = analysis["risk_notes"][:3] or ["当前组合没有明显刺眼的问题，但仍不代表没有风险。"]
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


_MEMBER_OPTIONS = ["我", "爸爸", "妈妈", "其他"]
_TYPE_OPTIONS = ["疑问", "担心", "观察", "备注", "已讨论"]
_FOCUS_LABELS = ["现金比例", "持仓集中", "PE/PB估值", "财务数据", "数据缺失", "风险承受", "其他"]
_FOCUS_MAP = {
    "现金比例": "cash",
    "持仓集中": "concentration",
    "PE/PB估值": "valuation",
    "财务数据": "financial",
    "数据缺失": "data_missing",
    "风险承受": "risk_tolerance",
    "其他": "other",
}
_STANCE_LABELS = ["偏谨慎", "偏进取", "中性 / 只是记录"]
_STANCE_MAP = {
    "偏谨慎": "conservative",
    "偏进取": "aggressive",
    "中性 / 只是记录": "neutral",
}
# ── 向导式家庭看法记录选项 ────────────────────────────────────────
_GW_MEMBER_OPTIONS: list[str] = ["爸爸", "妈妈", "我", "全家一致"]
_GW_FOCUS_OPTIONS: list[tuple[str, str]] = [
    ("现金比例",  "cash"),
    ("持仓集中",  "concentration"),
    ("估值高低",  "valuation"),
    ("财务数据",  "financial"),
    ("整体风险",  "risk_tolerance"),
    ("其他",     "other"),
]
_GW_STANCE_OPTIONS: list[tuple[str, str]] = [
    ("偏谨慎",   "conservative"),
    ("中性观察",  "neutral"),
    ("偏进取",   "aggressive"),
]
_REVERSE_QA_DEFAULT = {
    "money_need_6m": "uncertain",
    "volatility_reaction": "discuss",
    "last_disagreement": "",
}
_MONEY_NEED_LABELS = ["可能要用", "不确定", "基本不会用"]
_MONEY_NEED_MAP = {
    "可能要用": "possible",
    "不确定": "uncertain",
    "基本不会用": "unlikely",
}
_VOLATILITY_LABELS = ["会比较慌，想马上处理", "能接受波动，先观察", "看情况，需要一起商量"]
_VOLATILITY_MAP = {
    "会比较慌，想马上处理": "panic",
    "能接受波动，先观察": "tolerate",
    "看情况，需要一起商量": "discuss",
}


def _normalize_reverse_qa(raw: Any) -> dict[str, str]:
    data = dict(_REVERSE_QA_DEFAULT)
    if isinstance(raw, dict):
        data.update({k: str(v or "") for k, v in raw.items() if k in data})
    if data["money_need_6m"] not in set(_MONEY_NEED_MAP.values()):
        data["money_need_6m"] = _REVERSE_QA_DEFAULT["money_need_6m"]
    if data["volatility_reaction"] not in set(_VOLATILITY_MAP.values()):
        data["volatility_reaction"] = _REVERSE_QA_DEFAULT["volatility_reaction"]
    data["last_disagreement"] = str(data.get("last_disagreement", "") or "").strip()
    return data


def _reverse_label(value: str, mapping: dict[str, str]) -> str:
    reverse = {v: k for k, v in mapping.items()}
    return reverse.get(value, value or "不确定")


def _comment_stance_label(stance: str) -> str:
    reverse = {v: k for k, v in _STANCE_MAP.items()}
    return reverse.get(stance, stance)


def _comment_focus_label(focus: str) -> str:
    reverse = {v: k for k, v in _FOCUS_MAP.items()}
    return reverse.get(focus, focus)


def discussion_block(run_id: str = "") -> None:
    storage_status = get_storage_status()
    render_html(
        """
        <section class="block">
            <div class="block-head">
                <div>
                    <h2 class="block-title">家庭观察记录</h2>
                    <p class="block-subtitle">记录家人对这次体检的看法，方便回顾和共同讨论。不作为任何操作建议。</p>
                </div>
            </div>
        </section>
        """
    )

    with st.form("family_comment_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            member = st.selectbox("成员", _MEMBER_OPTIONS, key="comment_member")
            comment_type = st.selectbox("类型", _TYPE_OPTIONS, key="comment_type")
        with col2:
            focus_label = st.selectbox("关注点", _FOCUS_LABELS, key="comment_focus")
            stance_label = st.selectbox("立场", _STANCE_LABELS, key="comment_stance")
        submitted = st.form_submit_button("保存立场记录", use_container_width=True)

    if submitted:
        comment = {
            "member": member,
            "comment_type": comment_type,
            "focus": _FOCUS_MAP.get(focus_label, "other"),
            "stance": _STANCE_MAP.get(stance_label, "neutral"),
            "content": "",
            "run_id": run_id,
        }
        result: dict[str, Any] = {"success": False, "backend": "local_csv", "error": ""}
        try:
            result = save_family_comment(comment)
            st.session_state["family_comment_last_save"] = get_last_family_comment_save_status()
        except Exception as exc:  # noqa: BLE001
            st.session_state["family_comment_last_save"] = {
                "success": False,
                "backend": "local_csv",
                "connected": False,
                "saved": False,
                "message": "观察记录保存失败，不影响体检结果。",
                "error": f"{type(exc).__name__}: {str(exc)[:160]}",
            }
            result = {"success": False, "backend": "local_csv", "error": st.session_state["family_comment_last_save"]["error"]}
        if result.get("success") and result.get("backend") == "supabase":
            for stale_key in ("comment_error", "save_error", "family_comment_error"):
                st.session_state.pop(stale_key, None)
        # 也写旧版 note（保持 session_state.notes 展示兼容）
        note_body = f"{focus_label}｜{stance_label}"
        note = make_note(note_body, who=member)
        try:
            get_storage().save_note(note)
        except Exception:  # noqa: BLE001
            pass
        st.session_state.notes.insert(0, note)
        try:
            st.session_state["family_comments"] = load_recent_family_comments(limit=20)
            st.session_state["family_comments_cache"] = st.session_state["family_comments"]
            st.session_state["family_comments_last_count"] = len(st.session_state["family_comments"])
            read_status = get_last_family_comment_read_status()
            if not result.get("success") and read_status.get("backend") == "supabase":
                saved_row_seen = any(
                    str(row.get("member", "")) == str(comment["member"])
                    and str(row.get("focus", "")) == str(comment["focus"])
                    and str(row.get("stance", "")) == str(comment["stance"])
                    and str(row.get("content", "") or "") == str(comment["content"])
                    and (not comment.get("run_id") or str(row.get("run_id", "")) == str(comment["run_id"]))
                    for row in st.session_state["family_comments"]
                )
                if saved_row_seen:
                    result = {"success": True, "backend": "supabase", "error": ""}
                    st.session_state["family_comment_last_save"] = {
                        "success": True,
                        "backend": "supabase",
                        "connected": True,
                        "saved": True,
                        "message": "观察记录已保存到 Supabase 云数据库",
                        "error": "",
                    }
        except Exception as exc:  # noqa: BLE001
            save_status_for_fallback = st.session_state.get("family_comment_last_save", {})
            locally_available = bool(save_status_for_fallback.get("saved"))
            st.session_state["family_comments"] = [comment] if locally_available else []
            st.session_state["family_comments_cache"] = st.session_state["family_comments"]
            st.session_state["family_comments_last_count"] = len(st.session_state["family_comments"])
            st.session_state["family_comment_last_save"] = {
                **st.session_state.get("family_comment_last_save", {}),
                "error": f"保存后重新读取失败：{type(exc).__name__}",
            }
        save_status = st.session_state.get("family_comment_last_save", {})
        if result.get("success") and result.get("backend") == "supabase":
            st.session_state["family_comment_notice"] = "观察记录已保存到云端"
            st.session_state["family_comment_notice_detail"] = ""
        elif result.get("success") and result.get("backend") == "guest_local":
            st.session_state["family_comment_notice"] = "观察记录已保存到本地（游客模式）"
            st.session_state["family_comment_notice_detail"] = ""
        elif result.get("backend") == "local_csv" and save_status.get("saved"):
            st.session_state["family_comment_notice"] = "观察记录已保存到本地，云端同步失败"
            st.session_state["family_comment_notice_detail"] = str(save_status.get("error", "") or result.get("error", ""))
        else:
            st.session_state["family_comment_notice"] = "观察记录保存失败，不影响体检结果。"
            st.session_state["family_comment_notice_detail"] = str(save_status.get("error", "") or result.get("error", ""))
        st.rerun()

    notice = st.session_state.pop("family_comment_notice", "")
    notice_detail = st.session_state.pop("family_comment_notice_detail", "")
    if notice:
        if "游客模式" in notice:
            st.success(notice)
        elif "失败" in notice or "本地" in notice:
            st.warning(notice)
            if notice_detail:
                with st.expander("查看云端同步失败原因", expanded=False):
                    st.caption(notice_detail[:400])
        else:
            st.success(notice)

    st.caption(storage_status.get("message", "当前使用本地 CSV 兜底"))

    # 读取并展示最近观察记录
    comments: list[dict[str, Any]] = (
        st.session_state.get("family_comments")
        or st.session_state.get("family_comments_cache")
        or []
    )
    if not comments:
        try:
            comments = load_recent_family_comments(limit=20)
        except Exception:  # noqa: BLE001
            comments = []
        st.session_state["family_comments"] = comments
        st.session_state["family_comments_cache"] = comments
        st.session_state["family_comments_last_count"] = len(comments)

    if not comments:
        st.info("暂无观察记录。选择上方立场即可新增。")
        return

    def _render_comment(c: dict[str, Any]) -> None:
        member_disp = html_escape(c.get("member") or "我")
        ctype = html_escape(c.get("comment_type") or "备注")
        focus_disp = html_escape(_comment_focus_label(c.get("focus") or "other"))
        stance_disp = html_escape(_comment_stance_label(c.get("stance") or "neutral"))
        text = html_escape(c.get("content") or c.get("comment_text") or "")
        when = format_datetime_for_display(c.get("created_at"))
        content_line = f'<p class="muted" style="margin:0;">"{text}"</p>' if text else ""
        render_html(
            f"""
            <article class="note-card" style="margin-bottom:.7rem;">
                <div class="note-head" style="margin-bottom:.3rem;">
                    <span style="font-weight:600;">{member_disp}</span>
                    <span class="muted">｜{ctype}｜{focus_disp}｜{stance_disp}</span>
                    <span class="muted" style="float:right;font-size:.78rem;">{when}</span>
                </div>
                {content_line}
            </article>
            """
        )

    recent = comments[:3]
    for c in recent:
        _render_comment(c)

    if len(comments) > 3:
        with st.expander(f"查看全部 {len(comments)} 条观察记录", expanded=False):
            for c in comments[3:]:
                _render_comment(c)


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
                    <h2 class="block-title">数据报告下载</h2>
                    <p class="block-subtitle">普通分析入口只保留规则分析和调试信息，不再单独调用 DeepSeek。</p>
                </div>
            </div>
        </section>
        """
    )
    report_text = generate_txt_report(analysis)
    st.download_button(
        "↓ 数据分析报告",
        data=report_text.encode("utf-8"),
        file_name="FamilyReader_体检数据报告.txt",
        mime="text/plain",
        use_container_width=True,
        help="包含评分、持仓明细、风险提示的结构化报告",
    )


def followup_source_label(source: str) -> str:
    if source == "deepseek":
        return "DeepSeek AI"
    if source == "local_command":
        return "本地命令"
    return "本地规则兜底"


def followup_save_label(item: dict[str, Any]) -> str:
    if item.get("saved") == "true":
        backend = item.get("save_backend", "local_csv")
        if backend == "supabase":
            return "已保存到云端"
        if backend == "guest_local":
            return "仅游客本地保存"
        return "已保存到本地"
    if item.get("saved") == "false":
        return "保存失败"
    return "保存状态未知"


def unpack_followup_result(result: Any) -> tuple[str, str, str, str, str]:
    """Return (answer, source, error, raw_error, call_path)."""
    if isinstance(result, dict):
        answer = str(result.get("answer", "") or "")
        source = str(result.get("source", "local_fallback") or "local_fallback")
        error = str(result.get("error", "") or "")
        raw_error = str(result.get("raw_error", "") or "")
        call_path = str(result.get("call_path", "") or "")
        return answer or _AI_REPORT_FALLBACK_MSG, source, error, raw_error, call_path
    return (
        str(result or _AI_REPORT_FALLBACK_MSG),
        "local_fallback",
        "追问函数返回旧字符串格式",
        "ai_report.answer_followup_question returned a str instead of dict",
        "(unknown — legacy return shape)",
    )


def save_followup_answer(agent_context: dict[str, Any], question: str) -> None:
    clean_question = question.strip()
    if not clean_question:
        return

    # 构建多轮对话历史（最旧在前，最多取最近3条）
    _existing: list[dict[str, Any]] = list(st.session_state.get("followup_answers", []))
    # followup_answers 是新插到最前，所以需要反转取最旧的先
    _chat_history: list[dict[str, str]] = [
        {"question": str(a.get("question") or ""), "answer": str(a.get("answer") or "")}
        for a in reversed(_existing[-3:])
        if a.get("question") and a.get("answer")
    ]

    routed = route_slash_command(clean_question)
    effective_question = clean_question
    command = ""
    try:
        if routed.get("is_command"):
            command = str(routed.get("command", "") or "")
            if routed.get("direct"):
                answer = sanitize_compliance_text(str(routed.get("answer", "") or ""))
                source = "local_command"
                error = ""
                raw_error = ""
                call_path = "app.save_followup_answer -> question_router.route_slash_command"
            else:
                effective_question = str(routed.get("routed_question", "") or clean_question)
                answer, source, error, raw_error, call_path = unpack_followup_result(
                    answer_followup_question(agent_context, effective_question, _chat_history)
                )
                answer = sanitize_compliance_text(answer)
        else:
            answer, source, error, raw_error, call_path = unpack_followup_result(
                answer_followup_question(agent_context, clean_question, _chat_history)
            )
            answer = sanitize_compliance_text(answer)
    except Exception as exc:  # noqa: BLE001
        answer = _AI_REPORT_FALLBACK_MSG
        source = "local_fallback"
        error = f"追问调用异常：{type(exc).__name__}"
        raw_error = f"{type(exc).__name__}: {exc}"[:500]
        call_path = "save_followup_answer caught top-level exception"

    answers: list[dict[str, str]] = list(st.session_state.get("followup_answers", []))
    existing = next((a for a in answers if a["question"] == clean_question), None)
    record = {
        "question": clean_question,
        "answer": answer,
        "source": source,
        "error": error,
        "raw_error": raw_error,
        "call_path": call_path,
    }
    if command:
        record["command"] = command
    if effective_question != clean_question:
        record["routed_question"] = effective_question
    if source == "local_fallback":
        st.session_state["last_followup_error"] = {
            "question": clean_question,
            "source": source,
            "error": error or "DeepSeek 未返回可用结果",
            "raw_error": raw_error,
            "call_path": call_path,
        }
    else:
        st.session_state.pop("last_followup_error", None)
    try:
        saved = save_followup_history(question=clean_question, answer=answer, source=source, error=error)
        save_status = get_last_followup_save_status()
    except Exception:  # noqa: BLE001
        saved = False
        save_status = {
            "backend": "local_csv",
            "saved": False,
            "message": "追问记录保存失败",
            "error": "保存函数调用异常",
        }
    record["saved"] = "true" if saved else "false"
    record["save_backend"] = str(save_status.get("backend", "local_csv"))
    record["save_message"] = str(save_status.get("message", ""))
    record["save_error"] = str(save_status.get("error", ""))
    st.session_state["last_followup_save"] = save_status
    if existing:
        existing.update(record)
    else:
        answers.insert(0, record)
    st.session_state["followup_answers"] = answers


def followup_block(agent_context: dict[str, Any]) -> None:
    """继续追问区域：动态问题按钮（每次体检结果不同，问题随之变化） + 保留回答历史。"""
    existing_answers = list(st.session_state.get("followup_answers", []))
    migrated_count = 0
    for item in existing_answers:
        if not isinstance(item, dict):
            continue
        if "source" not in item:
            item["source"] = "local_fallback"
            migrated_count += 1
        if "error" not in item:
            item["error"] = ""
            migrated_count += 1
        if "raw_error" not in item:
            item["raw_error"] = ""
            migrated_count += 1
        if "call_path" not in item:
            item["call_path"] = "legacy followup record migrated in app.followup_block"
        if "saved" not in item:
            item["saved"] = "false"
    if migrated_count:
        st.session_state["followup_answers"] = existing_answers
        st.info("已保留旧版追问记录，并补齐诊断字段。")

    render_html(
        """
        <section class="block ai-report" style="padding:0.95rem 1rem;margin-bottom:0.7rem;">
            <div class="block-head" style="margin-bottom:.35rem;">
                <div>
                    <h2 class="block-title" style="font-size:1.12rem;">继续追问</h2>
                    <p class="block-subtitle">问题来自本次体检结果，回答只解释风险，不替家人做交易决定。</p>
                </div>
            </div>
        </section>
        """
    )
    # 从缓存读取问题——每次体检只随机生成一次，rerun 时保持稳定
    cached: list[str] = st.session_state.get("followup_questions", [])
    if not cached:
        try:
            cached = get_dynamic_questions(agent_context) if agent_context else _FALLBACK_QUESTIONS
            if not cached:
                cached = _FALLBACK_QUESTIONS
        except Exception:  # noqa: BLE001
            cached = _FALLBACK_QUESTIONS
        st.session_state["followup_questions"] = cached
    questions: list[str] = cached

    st.caption("点一个问题，或自己输入：")
    col_a, col_b = st.columns(2)
    for qi, question in enumerate(questions):
        col = col_a if qi % 2 == 0 else col_b
        if col.button(question, use_container_width=True, key=f"fq_{qi}"):
            save_followup_answer(agent_context, question)
            st.rerun()

    custom_question = st.text_input(
        "自定义追问",
        placeholder="也可以自己输入问题，例如：这次主要风险到底是什么？",
        label_visibility="collapsed",
        key="custom_followup_question",
    )
    if st.button("发送追问", use_container_width=True):
        if custom_question.strip():
            save_followup_answer(agent_context, custom_question)
            st.rerun()

    # ── 对话历史气泡（最新在上）────────────────────────────────
    followup_answers: list[dict[str, str]] = st.session_state.get("followup_answers", [])
    if followup_answers:
        _ans_n = len(followup_answers)
        render_html(
            f'<p style="font-size:0.78rem;color:var(--text-3);margin:0.6rem 0 0.3rem;">'
            f'本次已追问 {_ans_n} 条，AI 回答已记住上下文</p>'
        )
        # 气泡式展示（最新的在最上方）
        for item in followup_answers:
            q_text = html_escape(str(item.get("question") or ""))
            a_text = str(item.get("answer") or "")
            source = item.get("source", "local_fallback")
            src_label = followup_source_label(source)
            src_color = "#15803d" if source == "deepseek" else "#6b7280"
            render_html(
                f"""
                <div style="margin-bottom:1rem;">
                  <div style="display:flex;justify-content:flex-end;margin-bottom:0.3rem;">
                    <div style="background:var(--accent-soft);border:1px solid var(--border);
                                border-radius:14px 14px 4px 14px;padding:0.5rem 0.85rem;
                                max-width:88%;font-size:0.88rem;color:var(--text);font-weight:600;">
                      {q_text}
                    </div>
                  </div>
                  <div style="display:flex;align-items:flex-start;gap:0.45rem;">
                    <div style="width:1.6rem;height:1.6rem;border-radius:999px;flex-shrink:0;
                                background:var(--accent);display:grid;place-items:center;
                                color:#fff;font-size:0.7rem;font-weight:800;margin-top:0.15rem;">AI</div>
                    <div style="background:var(--surface);border:1px solid var(--border);
                                border-radius:4px 14px 14px 14px;padding:0.6rem 0.9rem;
                                max-width:92%;font-size:0.85rem;line-height:1.65;color:var(--text);">
                """
            )
            st.markdown(a_text)
            render_html(
                f"""
                    <p style="font-size:0.68rem;color:{src_color};margin:0.3rem 0 0;">
                        {src_label} · {followup_save_label(item)}
                    </p>
                    </div>
                  </div>
                </div>
                """
            )



def followup_entry_block(agent_result: dict[str, Any], agent_context: dict[str, Any]) -> None:
    followup_answers: list[dict[str, Any]] = list(st.session_state.get("followup_answers", []))
    saved_count = sum(1 for item in followup_answers if item.get("saved") == "true")
    subtitle = (
        f"本次已追问 {len(followup_answers)} 条，已保存 {saved_count} 条。"
        if followup_answers
        else "点击进入后可以继续问 AI，回答会尝试保存到历史记录。"
    )
    render_html(
        f"""
        <section class="block ai-report" style="padding:1rem 1.1rem;">
            <div class="block-head" style="margin-bottom:.35rem;">
                <div>
                    <h2 class="block-title" style="font-size:1.18rem;">继续追问这次体检</h2>
                    <p class="block-subtitle">{html_escape(subtitle)}</p>
                </div>
            </div>
        </section>
        """
    )
    if st.button("继续追问这次体检 →", use_container_width=True, key="open_followup_view"):
        st.session_state["active_view"] = "followup"
        st.rerun()
    if followup_answers:
        latest = followup_answers[0]
        st.caption(f"最近一次：{latest.get('question', '')}")
        st.caption(f"保存状态：{followup_save_label(latest)}")


def _unpack_agent_report(report_result: Any) -> tuple[str, str, str]:
    if isinstance(report_result, dict):
        text = str(report_result.get("ai_report", "") or report_result.get("report", "") or "")
        dinner = str(report_result.get("dinner_talk", "") or "")
        source = str(report_result.get("report_source", "local_fallback") or "local_fallback")
        return text or _AI_REPORT_FALLBACK_MSG, source, dinner
    return str(report_result or _AI_REPORT_FALLBACK_MSG), "local_fallback", ""


def _report_source_label(report_source: str) -> str:
    return "DeepSeek AI 生成" if report_source == "deepseek" else "本地规则兜底生成"


def reverse_qa_block(agent_result: dict[str, Any], agent_context: dict[str, Any], mode: str) -> None:
    current = _normalize_reverse_qa(
        agent_result.get("reverse_qa")
        or agent_context.get("reverse_qa")
        or st.session_state.get("reverse_qa")
    )
    render_html(
        """
        <section class="block ai-report" style="padding:0.95rem 1rem;margin-bottom:0.7rem;">
            <div class="block-head" style="margin-bottom:.35rem;">
                <div>
                    <h2 class="block-title" style="font-size:1.12rem;">补充家庭情况，让报告更贴近实际</h2>
                    <p class="block-subtitle">这是可选项；填写后会重新生成本次 AI 风险说明。</p>
                </div>
            </div>
        </section>
        """
    )
    with st.form("reverse_qa_form"):
        money_label = st.selectbox(
            "这笔钱半年内有没有可能要用？",
            _MONEY_NEED_LABELS,
            index=_MONEY_NEED_LABELS.index(_reverse_label(current["money_need_6m"], _MONEY_NEED_MAP)),
            key="reverse_money_need_6m",
        )
        volatility_label = st.selectbox(
            "如果最大那只持仓短期波动比较大，你第一反应更可能是？",
            _VOLATILITY_LABELS,
            index=_VOLATILITY_LABELS.index(_reverse_label(current["volatility_reaction"], _VOLATILITY_MAP)),
            key="reverse_volatility_reaction",
        )
        last_disagreement = st.text_input(
            "你们上一次因为投资有不同意见，是关于什么？",
            value=current.get("last_disagreement", ""),
            placeholder="例如：现金留多少、某只股票占比高不高、要不要继续观察等",
            key="reverse_last_disagreement",
        )
        submitted = st.form_submit_button("更新本次 AI 风险说明", use_container_width=True)

    if submitted:
        reverse_qa = {
            "money_need_6m": _MONEY_NEED_MAP.get(money_label, "uncertain"),
            "volatility_reaction": _VOLATILITY_MAP.get(volatility_label, "discuss"),
            "last_disagreement": str(last_disagreement or "").strip(),
        }
        st.session_state["reverse_qa"] = reverse_qa
        agent_context["reverse_qa"] = reverse_qa
        agent_result["reverse_qa"] = reverse_qa
        with st.spinner("正在根据补充情况更新报告..."):
            report_text, report_source, dinner_talk = _unpack_agent_report(
                generate_agent_report(agent_context, mode)
            )
        agent_result["ai_report"] = report_text
        agent_result["dinner_talk"] = dinner_talk
        agent_result["report_source"] = report_source
        agent_result["report_mode"] = mode
        agent_context["ai_report"] = report_text
        agent_context["dinner_talk"] = dinner_talk
        agent_context["report_source"] = report_source
        agent_context["report_mode"] = mode
        agent_result["agent_context"] = agent_context
        st.session_state["agent_result"] = agent_result
        st.session_state.pop("followup_questions", None)
        st.success("已根据补充家庭情况更新本次报告。")
        st.rerun()


def family_disagreement_block(disagreement: dict[str, Any]) -> None:
    if not isinstance(disagreement, dict) or not disagreement.get("has_conflict"):
        return
    conflicts = disagreement.get("conflicts") or []
    if not conflicts:
        return
    first = conflicts[0]
    focus_label = html_escape(first.get("focus_label") or first.get("focus") or "风险关注点")
    members = first.get("members") or {}
    conservative = [name for name, stance in members.items() if stance == "conservative"]
    aggressive = [name for name, stance in members.items() if stance == "aggressive"]
    if conservative and aggressive:
        line = f"{html_escape(conservative[0])}在「{focus_label}」上偏谨慎，{html_escape(aggressive[0])}在同一问题上偏进取。"
    else:
        line = html_escape(disagreement.get("summary") or "家庭成员在同一个风险关注点上存在不同看法。")
    render_html(
        f"""
        <div style="display:flex;align-items:flex-start;gap:0.5rem;
                    padding:0.45rem 0.85rem;margin:0.3rem 0 0.35rem;
                    background:#fff7ed;border-radius:10px;border:1.5px solid #d08a2d;">
            <span style="font-size:0.9rem;flex-shrink:0;line-height:1.6;">⚠️</span>
            <div style="min-width:0;">
                <span style="font-size:0.86rem;font-weight:700;color:#7a3e2e;">
                    家庭风险看法不一致
                </span>
                <span style="font-size:0.8rem;color:#7a3e2e;margin-left:0.3rem;">{line}</span>
                <p style="font-size:0.72rem;color:#9a6a2a;margin:0.1rem 0 0;">
                    建议这次体检先围绕这一点聊清楚。
                </p>
            </div>
        </div>
        """
    )


def intent_action_gap_block(gap_data: dict[str, Any]) -> None:
    """意图-行动差距镜：把家人立场记录和当前持仓数据对比，提示明显差距。"""
    if not isinstance(gap_data, dict) or not gap_data.get("has_gap"):
        return
    gaps = list(gap_data.get("gaps") or [])
    if not gaps:
        return

    notable = [g for g in gaps if g.get("severity") == "notable"]
    show_gaps = notable if notable else gaps[:2]   # 最多显示 2 条

    rows_html = ""
    for g in show_gaps:
        member      = _hesc(g, "member")
        focus_label = _hesc(g, "focus_label")
        stated      = _hesc(g, "stated")
        current     = _hesc(g, "current_desc")
        gap_desc    = _hesc(g, "gap_desc")
        rows_html += (
            f'<li style="padding:0.22rem 0;border-bottom:1px solid rgba(122,62,46,0.08);'
            f'display:flex;align-items:flex-start;gap:0.45rem;">'
            f'<span style="flex-shrink:0;font-size:0.72rem;font-weight:700;color:#7a3e2e;'
            f'background:rgba(122,62,46,0.1);border-radius:999px;padding:0.1rem 0.45rem;'
            f'white-space:nowrap;">{member}</span>'
            f'<span style="font-size:0.82rem;color:var(--text);line-height:1.45;">'
            f'{gap_desc}'
            f'<span style="font-size:0.7rem;color:var(--text-3);margin-left:0.25rem;">'
            f'立场：{stated}／{focus_label}／{current}</span>'
            f'</span></li>'
        )
    extra = len(gaps) - len(show_gaps)
    extra_html = (
        f'<p style="font-size:0.72rem;color:var(--text-3);margin:0.35rem 0 0;">'
        f'另有 {extra} 处细微差距，可在追问时进一步了解。</p>'
        if extra > 0 else ""
    )
    render_html(
        f"""
        <section style="margin:0.3rem 0 0.45rem;border-radius:10px;
                        border:1.5px solid rgba(122,62,46,0.3);
                        background:rgba(122,62,46,0.04);overflow:hidden;">
            <div style="padding:0.35rem 0.85rem 0.25rem;display:flex;align-items:center;
                        gap:0.4rem;border-bottom:1px solid rgba(122,62,46,0.1);">
                <span style="font-size:0.85rem;">🪞</span>
                <span style="font-size:0.85rem;font-weight:700;color:#7a3e2e;">意图与持仓差距</span>
                <span style="font-size:0.7rem;color:var(--text-3);margin-left:auto;">
                    家人立场 vs 当前持仓
                </span>
            </div>
            <ul style="margin:0;padding:0.1rem 0.85rem 0.35rem;list-style:none;">
                {rows_html}
            </ul>
            {extra_html}
        </section>
        """
    )



def agent_memory_block(memory: dict[str, Any]) -> None:
    """Show a compact Agent memory card based on previous checks and family notes."""
    if not isinstance(memory, dict) or not memory.get("has_memory"):
        return
    summary = str(memory.get("summary") or "").strip()
    watch_points = [str(item) for item in (memory.get("next_watch_points") or []) if str(item or "").strip()]
    focus_items = memory.get("recurring_focus") or []
    focus_text = ""
    if focus_items and isinstance(focus_items[0], dict):
        focus_text = str(focus_items[0].get("focus_label") or "")
    chips = "".join(
        f'<span style="font-size:0.68rem;color:#7a3e2e;background:rgba(122,62,46,0.08);'
        f'border-radius:999px;padding:0.14rem 0.46rem;margin-right:0.28rem;display:inline-block;">'
        f'{html_escape(item)}</span>'
        for item in watch_points[:3]
    )
    focus_html = (
        f'<p style="font-size:0.72rem;color:var(--text-3);margin:0.12rem 0 0;">'
        f'家庭记录里较常出现：{html_escape(focus_text)}</p>'
        if focus_text else ""
    )
    render_html(
        f"""
        <section style="margin:0.25rem 0 0.45rem;border:1px solid var(--border);
                        background:var(--surface);border-radius:12px;padding:0.7rem 0.85rem;">
            <div style="display:flex;align-items:center;gap:0.45rem;margin-bottom:0.28rem;">
                <span style="width:1.55rem;height:1.55rem;border-radius:999px;background:var(--accent-soft);
                             display:inline-flex;align-items:center;justify-content:center;color:#7a3e2e;
                             font-weight:800;font-size:0.78rem;flex-shrink:0;">M</span>
                <div style="min-width:0;">
                    <div style="font-size:0.9rem;font-weight:800;color:var(--text);line-height:1.2;">Agent 记忆</div>
                    <div style="font-size:0.68rem;color:var(--text-3);">来自历史体检和家庭观察，不替家人做决定</div>
                </div>
            </div>
            <p style="font-size:0.8rem;color:var(--text-2);line-height:1.55;margin:0;">
                {html_escape(summary)}
            </p>
            {focus_html}
            <div style="margin-top:0.45rem;line-height:1.75;">{chips}</div>
        </section>
        """
    )


def family_profile_memory_block(profile: dict[str, Any], followup_memory: dict[str, Any]) -> None:
    """Show the persistent family profile that the Agent will reuse next time."""
    if not isinstance(profile, dict) and not isinstance(followup_memory, dict):
        return
    profile = profile if isinstance(profile, dict) else {}
    followup_memory = followup_memory if isinstance(followup_memory, dict) else {}
    focus_topics = profile.get("focus_topics") or {}
    if not isinstance(focus_topics, dict):
        focus_topics = {}
    top_focus = [
        str(item.get("label") or item.get("focus") or "")
        for item in (focus_topics.get("top_focus") or [])
        if isinstance(item, dict) and (item.get("label") or item.get("focus"))
    ]
    followup_topics = [
        str(item.get("label") or item.get("topic") or "")
        for item in (followup_memory.get("top_topics") or [])
        if isinstance(item, dict) and (item.get("label") or item.get("topic"))
    ]
    if not top_focus and not followup_topics and not profile.get("risk_preference"):
        return
    chips = "".join(
        f'<span style="font-size:0.68rem;color:#7a3e2e;background:rgba(122,62,46,0.08);'
        f'border-radius:999px;padding:0.14rem 0.46rem;margin-right:0.28rem;display:inline-block;">'
        f'{html_escape(item)}</span>'
        for item in (top_focus[:3] + followup_topics[:2])
    )
    render_html(
        f"""
        <section style="margin:0.25rem 0 0.45rem;border:1px solid var(--border);
                        background:var(--surface);border-radius:12px;padding:0.7rem 0.85rem;">
            <div style="font-size:0.9rem;font-weight:800;color:var(--text);line-height:1.2;">长期记忆</div>
            <div style="font-size:0.68rem;color:var(--text-3);margin-top:0.12rem;">
                下次体检会继续参考这些家庭关注点
            </div>
            <p style="font-size:0.78rem;color:var(--text-2);line-height:1.55;margin:0.45rem 0 0;">
                风险偏好：{html_escape(profile.get("risk_preference") or "暂未形成")}；
                解释风格：{html_escape(profile.get("explanation_level") or "简明解释")}；
                追问记忆：{html_escape(followup_memory.get("summary") or "暂无明显追问主题")}。
            </p>
            <div style="margin-top:0.45rem;line-height:1.75;">{chips}</div>
        </section>
        """
    )


def risk_factor_breakdown_block(analysis: dict[str, Any], factor_data: dict[str, Any] | None = None) -> None:
    """把现有评分拆成父母能看懂的风险因子，不改变分析逻辑。"""
    factor_data = factor_data or build_risk_factor_breakdown(analysis or {})
    factors = list((factor_data or {}).get("factors") or [])
    weakest = (factor_data or {}).get("weakest_factor") or {}
    if not factors:
        return

    color_by_tone = {
        "steady": "#3f7d55",
        "watch": "#b97a1a",
        "tight": "#b94040",
    }

    cards = []
    for item in factors:
        name = str(item.get("name", ""))
        score = float(item.get("score", 0) or 0)
        weight = float(item.get("weight", 0) or 0)
        tone_label = str(item.get("tone_label", "看") or "看")
        color = color_by_tone.get(str(item.get("tone", "")), "#b97a1a")
        status = str(item.get("status", "") or "需要继续观察")
        plain = str(item.get("plain", "") or name)
        cards.append(
            f"""
            <article style="border:1px solid var(--border);border-radius:12px;background:var(--surface);
                            padding:0.72rem 0.82rem;min-width:0;">
                <div style="display:flex;align-items:center;gap:0.45rem;margin-bottom:0.28rem;">
                    <span style="width:1.45rem;height:1.45rem;border-radius:999px;background:{color};
                                 color:#fff;display:inline-flex;align-items:center;justify-content:center;
                                 font-size:0.7rem;font-weight:800;flex-shrink:0;">{html_escape(tone_label)}</span>
                    <div style="font-size:0.88rem;font-weight:800;color:var(--text);line-height:1.2;flex:1;min-width:0;">
                        {html_escape(name)}
                    </div>
                    <div style="font-size:0.82rem;font-weight:800;color:{color};white-space:nowrap;flex-shrink:0;">
                        {score:.0f}<span style="font-size:0.62rem;color:var(--text-3);font-weight:400;">/100</span>
                    </div>
                </div>
                <div style="height:0.38rem;border-radius:999px;background:var(--bg-2);overflow:hidden;margin:0 0 0.28rem;">
                    <div style="width:{max(0, min(100, score)):.1f}%;height:100%;background:{color};border-radius:999px;"></div>
                </div>
                <div style="font-size:0.72rem;color:{color};font-weight:600;">
                    {html_escape(status)} · 权重 {weight:.0f}%
                </div>
                <div style="font-size:0.72rem;color:var(--text-3);line-height:1.45;margin-top:0.28rem;">
                    {html_escape(plain)}
                </div>
            </article>
            """
        )

    top_focus = [item for item in list((factor_data or {}).get("top_focus") or []) if isinstance(item, dict)]
    focus_item = top_focus[0] if top_focus else weakest
    focus_name = str(focus_item.get("name", factors[0].get("name", "")) or "")
    focus_score = float(focus_item.get("score", factors[0].get("score", 0)) or 0)
    focus_plain = str(focus_item.get("plain", focus_name) or focus_name)
    focus_extra = ""
    if len(top_focus) > 1:
        focus_extra = "；另一个重点是：" + "、".join(html_escape(str(item.get("name") or "")) for item in top_focus[1:2])

    render_html(
        f"""
        <section class="block" style="padding:1rem 1rem 0.95rem;">
            <div class="block-head" style="margin-bottom:0.65rem;">
                <div>
                    <h2 class="block-title" style="font-size:1.15rem;">风险因子拆解</h2>
                    <p class="block-subtitle">这不是额外预测，只是把综合评分拆开看清楚。</p>
                </div>
            </div>
            <div style="border:1px solid #e8c4b2;background:#fff9f6;border-radius:12px;
                        padding:0.75rem 0.85rem;margin-bottom:0.75rem;">
                <p style="font-size:0.82rem;color:var(--text);line-height:1.55;margin:0;">
                    本次最需要先看的因子是：
                    <strong>{html_escape(focus_name)}</strong>（{focus_score:.0f}/100）。
                    简单说，就是{html_escape(focus_plain)}{focus_extra}。
                </p>
            </div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:0.5rem;">
                {''.join(cards)}
            </div>
        </section>
        """
    )
def _cross_validation_html(cv: dict[str, Any]) -> str:
    """多重交叉验证结果的紧凑 HTML 片段。"""
    if not cv or not cv.get("checks_run"):
        return ""
    issues = list(cv.get("issues") or [])
    notes  = list(cv.get("notes")  or [])
    passed = cv.get("passed", True)

    if issues:
        items = "".join(
            f'<li style="margin:0.1rem 0;font-size:0.72rem;color:#b94040;">'
            f'⚠ {html_escape(i)}</li>'
            for i in issues
        )
        return (
            f'<div style="margin:0 0 0.4rem;padding:0.35rem 0.7rem;'
            f'background:rgba(185,64,64,0.07);border-radius:8px;'
            f'border:1px solid rgba(185,64,64,0.18);">'
            f'<ul style="margin:0;padding-left:0.1rem;list-style:none;">{items}</ul>'
            f'</div>'
        )
    if notes:
        items = "".join(
            f'<li style="margin:0.08rem 0;font-size:0.7rem;color:var(--text-3);">'
            f'· {html_escape(n)}</li>'
            for n in notes
        )
        return (
            f'<div style="margin:0 0 0.4rem;">'
            f'<ul style="margin:0;padding-left:0.1rem;list-style:none;">{items}</ul>'
            f'</div>'
        )
    n = int(cv.get("checks_run") or 0)
    return (
        f'<p style="margin:0 0 0.4rem;font-size:0.68rem;color:var(--text-3);">'
        f'✓ {n} 项交叉校验通过</p>'
    )


def _confidence_badge_html(level: str, level_code: str, summary: str) -> str:
    """Compliance Guard 置信度标签 HTML 片段。无数据时返回空字符串。"""
    if not level:
        return ""
    colors = {
        "high":   ("#3f7d55", "rgba(63,125,85,0.10)"),
        "medium": ("#b97a1a", "rgba(185,122,26,0.10)"),
        "low":    ("#b94040", "rgba(185,64,64,0.10)"),
    }
    fg, bg = colors.get(level_code, ("#888", "rgba(0,0,0,0.06)"))
    return (
        f'<p style="margin:0 0 0.45rem;padding-left:0.2rem;">'
        f'<span style="font-size:0.68rem;font-weight:700;color:{fg};'
        f'background:{bg};border-radius:6px;padding:0.1rem 0.5rem;">'
        f'数据置信度：{html_escape(level)}</span>'
        f'<span style="font-size:0.68rem;color:var(--text-3);margin-left:0.4rem;">'
        f'{html_escape(summary)}</span>'
        f'</p>'
    )


def agent_result_block(agent_result: dict[str, Any]) -> None:
    if not agent_result:
        return

    summary = agent_result.get("portfolio_summary", {})
    missing_data = agent_result.get("missing_data", {})
    data_status = agent_result.get("data_status", "未知")
    agent_context = agent_result.get("agent_context", {})
    _confidence = agent_result.get("data_confidence") or {}
    _conf_level   = str(_confidence.get("level") or "")
    _conf_code    = str(_confidence.get("level_code") or "")
    _conf_summary = str(_confidence.get("summary") or "")
    _cross_val    = agent_result.get("cross_validation") or {}
    _history_analysis = agent_result.get("history_analysis") or {}
    _behavior_note = str(_history_analysis.get("behavior_note") or "")
    _analysis = st.session_state.get("analysis") or agent_result.get("analysis") or {}

    # ── 完成提示（轻量横条）──────────────────────────────────
    render_html(
        """
        <div style="display:flex;align-items:center;gap:0.5rem;
                    padding:0.45rem 0.85rem;margin-bottom:0.6rem;
                    background:var(--accent-soft);border-radius:10px;">
            <svg width="18" height="18" viewBox="0 0 22 22" fill="none" style="flex-shrink:0;">
                <circle cx="11" cy="11" r="11" fill="#7a3e2e" opacity="0.14"/>
                <path d="M6.5 11.5 L9.5 14.5 L15.5 8" stroke="#7a3e2e"
                      stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <span style="font-size:0.85rem;font-weight:700;color:var(--text);">体检完成</span>
            <span style="font-size:0.72rem;color:var(--text-3);margin-left:0.15rem;">
                ·&nbsp;已检查持仓结构、现金比例与集中风险
            </span>
        </div>
        """
    )

    # ── Part 1：核心结果卡片 ─────────────────────────────────

    # 1a. 综合评分 + 风险等级（verdict-card 保留原样式）
    risk_score = int(agent_result.get("risk_score", 0) or 0)
    risk_info = risk_signal_info(risk_score, str(agent_result.get("risk_level", "") or ""))
    render_html(
        f"""
        <section class="block ai-report" style="margin-bottom:0.45rem;">
            <div class="verdict-card">
                <div class="risk-signal {html_escape(risk_info["class"])}">
                    <div class="risk-light" aria-hidden="true"></div>
                    <div>
                        <div class="kicker">综合风险等级</div>
                        <div class="risk-status">{html_escape(risk_info["status"])}</div>
                        <div class="risk-score-line">综合评分 {risk_score}/100 · {html_escape(risk_info["caption"])}</div>
                        <p class="muted">{html_escape(data_status)}</p>
                    </div>
                </div>
                {score_dial(risk_score, risk_info.get("color", "var(--accent)"))}
            </div>
        </section>
        """
    )

    # 1b. 与上次体检相比（主动预警）
    _delta = agent_result.get("delta_alert") or {}
    if _delta.get("has_alert"):
        _dlevel = str(_delta.get("level") or "caution")
        _dbg, _dfg = {
            "warning":  ("#fef2f2", "#b91c1c"),
            "caution":  ("#fffbeb", "#92400e"),
            "improved": ("#f0fdf4", "#15803d"),
        }.get(_dlevel, ("#f8fafc", "#475569"))
        _dicon = {"warning": "⬇️", "caution": "⚠️", "improved": "⬆️"}.get(_dlevel, "△")
        _dlabel = {"warning": "风险上升", "caution": "有变化", "improved": "有改善"}.get(_dlevel, "有变化")
        _changes_html = "".join(
            f'<span style="display:block;font-size:0.78rem;color:{_dfg};'
            f'padding:0.1rem 0;">{html_escape(c)}</span>'
            for c in (_delta.get("changes") or [])
        )
        with st.expander(f"综合评分变化：{_dlabel}", expanded=(_dlevel == "warning")):
            render_html(
                f"""
                <div style="margin:0 0 0.4rem;padding:0.5rem 0.85rem;
                            background:{_dbg};border-radius:10px;
                            border:1.5px solid color-mix(in srgb,{_dfg} 30%,transparent);">
                    <div style="display:flex;align-items:center;gap:0.35rem;margin-bottom:0.15rem;">
                        <span style="font-size:0.8rem;">{_dicon}</span>
                        <span style="font-size:0.83rem;font-weight:700;color:{_dfg};">与上次体检相比</span>
                    </div>
                    {_changes_html}
                </div>
                """
            )

    # 1c. 给家人的一句话（dinner_talk，有才显示）
    _dinner = str(agent_result.get("dinner_talk") or agent_context.get("dinner_talk") or "")
    if _dinner:
        render_html(
            f"""
            <div style="padding:0.55rem 0.85rem;margin:0 0 0.4rem;
                        background:var(--gold-soft);border-radius:10px;
                        border:1.5px solid color-mix(in srgb,var(--gold) 30%,transparent);">
                <p style="font-size:0.68rem;font-weight:700;letter-spacing:.06em;
                          color:var(--gold);text-transform:uppercase;margin:0 0 0.18rem;">
                    给家人的一句话
                </p>
                <p style="font-size:0.87rem;color:var(--text);margin:0;line-height:1.55;">
                    {html_escape(_dinner)}
                </p>
            </div>
            """
        )

    # 1d. 家庭分歧（有则显示）
    family_disagreement_block(agent_result.get("family_disagreement", {}))

    # 1d-2. 极端情景压力测试（最坏情况演练；重大影响时自动展开）
    _stress = agent_result.get("stress_test") or {}
    if _stress.get("available") and _stress.get("scenarios"):
        _worst_sev = str((_stress.get("worst_case") or {}).get("severity") or "mild")
        with st.expander("最坏情况下，全家会缩水多少？", expanded=(_worst_sev == "severe")):
            stress_test_block(agent_result)

    # 1e. Agent 主动抓重点（结果页唯一的重点风险入口）
    with st.expander(f"Agent 主动判断 · 数据可信度：{_conf_level or '未知'}", expanded=True):
        agent_focus_block(agent_result)

    # 1f. 下一步 CTA：查看 AI 风险说明
    render_html("""
    <div class="fr-step-card">
        <p class="fr-step-kicker">Next</p>
        <p class="fr-step-title">让 AI 把风险讲给家人听</p>
        <p class="fr-step-sub">基于本次体检数据生成，重点解释为什么要关注这些风险。</p>
    </div>
    """)
    if st.button("查看 AI 风险说明 →", use_container_width=True,
                 key="goto_ai_report_btn", type="primary"):
        st.session_state["active_view"] = "ai_report"
        st.rerun()

    # ── Part 2：Agent 智能分析详情（默认折叠）────────────────
    with st.expander("Agent 智能分析详情", expanded=False):
        render_html(_confidence_badge_html(_conf_level, _conf_code, _conf_summary))
        render_html(_cross_validation_html(_cross_val))
        if _behavior_note:
            render_html(
                f'<p style="font-size:0.78rem;color:var(--text-3);'
                f'margin:0 0 0.4rem;padding:0.35rem 0.75rem;'
                f'background:var(--accent-soft);border-radius:8px;">'
                f'记忆&nbsp;{html_escape(_behavior_note)}</p>'
            )
        agent_memory_block(agent_result.get("agent_memory", {}))
        family_profile_memory_block(
            agent_result.get("family_profile", {}),
            agent_result.get("followup_memory", {}),
        )
        intent_action_gap_block(agent_result.get("intent_action_gap", {}))
        task_review_block(agent_result)
        watch_tasks_block(agent_result)
        if _analysis:
            risk_factor_breakdown_block(_analysis, agent_result.get("risk_factors"))

    # ── Part 3：体检数据一览（直接展示，核心指标不折叠）─────────────
    if _analysis:
        portfolio_metrics_block(summary, _analysis)

    # ── Part 4：持仓明细与数据来源（折叠）────────────────────────────
    with st.expander("持仓明细 · 数据来源", expanded=False):
        if _analysis:
            holdings_detail(_analysis)
        has_missing = any(bool(v) for v in missing_data.values())
        if has_missing:
            st.markdown("**数据缺失说明**")
            for title, items in missing_data.items():
                if items:
                    labels = [str(item).strip() for item in items if str(item).strip()]
                    names = "、".join(labels)
                    if "估值" in title:
                        st.caption(f"· {title}：{names}")
                        st.caption("  影响：估值数据暂缺，本次不评价估值高低。")
                    else:
                        st.caption(f"· {title}：{names}")
                        st.caption("  影响：这部分已按保守口径处理。")


def history_replay_block(agent_result: dict[str, Any] | None) -> None:
    """历史体检回放：对比最近两次体检的风险变化。"""
    try:
        rows = load_recent_analysis_history(limit=5)
    except Exception:  # noqa: BLE001
        rows = []

    history_analysis: dict[str, Any] = {}
    if rows:
        history_analysis = analyze_history_changes(rows)
    elif agent_result:
        history_analysis = agent_result.get("history_analysis") or {}

    count = int(history_analysis.get("records_count", 0) or len(rows) or 0)
    summary = str(history_analysis.get("summary", "") or "")

    render_html(
        """
        <section class="block" style="padding:1rem 1rem 0.85rem;margin-bottom:0.9rem;">
            <div class="block-head" style="margin-bottom:.45rem;">
                <div>
                    <h2 class="block-title" style="font-size:1.15rem;">历史体检回放</h2>
                    <p class="block-subtitle">看最近几次体检里，分数、现金和主要风险有没有变化。</p>
                </div>
            </div>
        </section>
        """
    )

    if count == 0:
        st.info("历史记录还不够，先完成几次体检后，这里会显示风险变化。")
        return

    latest_date = format_datetime_for_display(history_analysis.get("latest_date", ""))
    if count == 1:
        st.info("目前只有一次体检记录，暂时无法比较变化。")
        st.caption(f"最近一次体检：{latest_date}")
        return

    previous_date = format_datetime_for_display(history_analysis.get("previous_date", ""))
    score_change = history_analysis.get("score_change")

    if score_change is None:
        trend_title = "评分变化暂时无法判断"
        trend_note = "历史记录里缺少完整评分，后续新体检会自动补齐。"
        trend_color = "#7a3e2e"
    elif score_change > 5:
        trend_title = f"评分比上次上升 {score_change:+.1f} 分"
        trend_note = "整体风险压力比上次低一些，但仍要看具体风险点。"
        trend_color = "#3f7d55"
    elif score_change < -5:
        trend_title = f"评分比上次下降 {score_change:.1f} 分"
        trend_note = "这次比上次更需要留意，先看新增风险和仓位变化。"
        trend_color = "#b94040"
    else:
        trend_title = f"评分基本持平（{score_change:+.1f} 分）"
        trend_note = "整体变化不大，重点看哪些风险仍然反复出现。"
        trend_color = "#8a6a2a"

    def _ratio_change_text(key: str, label: str) -> str:
        val = history_analysis.get(key)
        if val is None:
            return f"{label}：暂无对比"
        sign = "+" if float(val) >= 0 else ""
        return f"{label}：{sign}{float(val) * 100:.1f} 个百分点"

    change_lines = [
        _ratio_change_text("cash_ratio_change", "现金比例"),
        _ratio_change_text("stock_ratio_change", "股票/基金仓位"),
        _ratio_change_text("max_position_ratio_change", "最大单只占比"),
    ]

    render_html(
        f"""
        <div style="border:1px solid var(--border);border-radius:14px;background:var(--surface);
                    padding:1rem 1rem 0.85rem;margin-bottom:0.85rem;">
            <div style="display:flex;align-items:flex-start;gap:0.75rem;">
                <div style="width:0.7rem;height:0.7rem;border-radius:999px;background:{trend_color};
                            margin-top:0.35rem;flex-shrink:0;"></div>
                <div style="min-width:0;">
                    <div style="font-size:1rem;font-weight:800;color:var(--text);line-height:1.35;">
                        {html_escape(trend_title)}
                    </div>
                    <p style="margin:0.25rem 0 0;color:var(--text-2);font-size:0.82rem;line-height:1.55;">
                        {html_escape(trend_note)}
                    </p>
                    <p style="margin:0.45rem 0 0;color:var(--text-3);font-size:0.74rem;">
                        本次：{html_escape(latest_date)}　上次：{html_escape(previous_date)}
                    </p>
                </div>
            </div>
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:0.45rem;margin-top:0.85rem;">
                {''.join(
                    f'<div style="border:1px solid var(--border);border-radius:10px;padding:0.55rem 0.5rem;background:var(--bg-2);">'
                    f'<div style="font-size:0.72rem;color:var(--text-3);line-height:1.35;">{html_escape(line.split("：")[0])}</div>'
                    f'<div style="font-size:0.85rem;font-weight:700;color:var(--text);line-height:1.4;">{html_escape(line.split("：", 1)[1])}</div>'
                    f'</div>'
                    for line in change_lines
                )}
            </div>
        </div>
        """
    )

    risk_changes = history_analysis.get("risk_factor_changes") or []
    new_risks = [str(c.get("text", "")) for c in risk_changes if c.get("type") == "new" and c.get("text")]
    resolved_risks = [str(c.get("text", "")) for c in risk_changes if c.get("type") == "resolved" and c.get("text")]
    watch_points = [str(wp) for wp in (history_analysis.get("watch_points") or []) if wp]
    family_changes = [str(fc) for fc in (history_analysis.get("family_focus_changes") or []) if fc]

    focus_items: list[tuple[str, str, str]] = []
    if new_risks:
        focus_items.append(("新出现", new_risks[0][:100], "#b94040"))
    if resolved_risks:
        focus_items.append(("已改善", resolved_risks[0][:100], "#3f7d55"))
    if watch_points:
        focus_items.append(("仍需关注", watch_points[0][:100], "#8a6a2a"))
    if family_changes:
        focus_items.append(("家庭沟通", family_changes[0][:100], "#7a3e2e"))
    if not focus_items and summary:
        focus_items.append(("回放结论", summary[:120], "#7a3e2e"))

    if focus_items:
        rows_html = "".join(
            f"""
            <li style="display:flex;gap:0.6rem;align-items:flex-start;padding:0.55rem 0;
                       border-bottom:1px solid var(--border);">
                <span style="font-size:0.72rem;font-weight:800;color:#fff;background:{color};
                             border-radius:999px;padding:0.14rem 0.55rem;white-space:nowrap;">{html_escape(label)}</span>
                <span style="font-size:0.84rem;color:var(--text);line-height:1.55;">{html_escape(text)}</span>
            </li>
            """
            for label, text, color in focus_items
        )
        render_html(
            f"""
            <div style="border:1px solid var(--border);border-radius:14px;background:var(--surface);
                        padding:0.45rem 0.9rem;margin-bottom:0.85rem;">
                <div style="font-size:0.9rem;font-weight:800;color:var(--text);padding:0.35rem 0 0.15rem;">
                    这次回放重点
                </div>
                <ul style="list-style:none;margin:0;padding:0;">{rows_html}</ul>
            </div>
            """
        )

    timeline_rows = rows[:5]
    if timeline_rows:
        with st.expander("最近 5 次体检轨迹", expanded=False):
            for row in timeline_rows:
                full = row.get("full_agent_result") if isinstance(row.get("full_agent_result"), dict) else {}
                portfolio = full.get("portfolio_summary") if isinstance(full.get("portfolio_summary"), dict) else {}
                created_at = format_datetime_for_display(row.get("created_at") or row.get("分析时间"))
                score = row.get("risk_score") or row.get("综合评分") or ""
                level = str(row.get("risk_level") or row.get("风险等级") or "")
                cash_ratio = float(row.get("cash_ratio") or portfolio.get("cash_ratio") or 0)
                stock_ratio = float(row.get("stock_ratio") or portfolio.get("stock_ratio") or 0)
                max_ratio = float(row.get("max_position_ratio") or portfolio.get("max_single_ratio") or 0)
                st.caption(
                    f"{created_at}｜评分 {score}｜{level}｜现金 {percent(cash_ratio)}｜"
                    f"持仓 {percent(stock_ratio)}｜最大单只 {percent(max_ratio)}"
                )

    if summary:
        st.info(summary)


def _level_icon(level: str) -> str:
    s = str(level)
    if "红" in s:
        return "🔴"
    if "黄" in s:
        return "🟡"
    if "绿" in s:
        return "🟢"
    return "⚪"


def history_records_block() -> None:
    with st.expander("历史体检记录", expanded=False):
        status = get_storage_status()
        st.caption(status.get("message", "当前使用本地 CSV 兜底"))
        try:
            rows = load_recent_analysis_history(limit=10)
        except Exception:  # noqa: BLE001
            rows = []
        if not rows:
            st.info("暂无历史体检记录。完成一次一键智能体检后，这里会显示最近记录。")
            return
        for idx, row in enumerate(rows):
            created_at = format_datetime_for_display(row.get("created_at") or row.get("分析时间"))
            score = row.get("risk_score") or row.get("综合评分") or ""
            level = str(row.get("risk_level") or row.get("风险等级") or "")
            cash_ratio = float(row.get("cash_ratio") or row.get("现金比例") or 0)
            stock_ratio = float(row.get("stock_ratio") or row.get("股票仓位") or 0)
            holdings_summary = str(row.get("holdings_summary") or "")

            # full_agent_result is already a dict (deserialized by storage._normalize_analysis_row)
            full: dict[str, Any] = row.get("full_agent_result") or {}
            if not isinstance(full, dict):
                full = {}

            ai_report = str(full.get("ai_report") or row.get("ai_report_summary") or "").strip()
            main_risks_raw = full.get("main_risks") or row.get("main_risks") or []
            if isinstance(main_risks_raw, str):
                try:
                    import json as _json
                    main_risks_raw = _json.loads(main_risks_raw)
                except Exception:  # noqa: BLE001
                    main_risks_raw = [main_risks_raw] if main_risks_raw else []
            main_risks: list[str] = [str(r) for r in (main_risks_raw or []) if r]

            icon = _level_icon(level)
            label = f"{icon} {created_at or '体检记录'}｜评分 {score}｜{level}"
            with st.expander(label, expanded=False):
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.metric("综合评分", f"{score} 分")
                with c2:
                    st.metric("现金比例", percent(cash_ratio))
                with c3:
                    st.metric("股票仓位", percent(stock_ratio))

                if holdings_summary:
                    st.caption(f"持仓：{holdings_summary[:160]}")

                if main_risks:
                    st.markdown("**主要风险**")
                    for risk in main_risks[:6]:
                        st.caption(f"• {risk[:120]}")

                if ai_report:
                    st.markdown("---")
                    st.markdown("**AI 风险说明**")
                    st.markdown(ai_report)
                elif idx == 0:
                    st.caption("此次记录未保存完整 AI 说明（可能是旧格式记录）。")


def discussion_entry_block(run_id: str = "") -> None:
    """家庭观察记录入口卡片（主结果页显示，点击跳入专属子页）。"""
    try:
        comments: list[dict[str, Any]] = st.session_state.get("family_comments_cache") or []
        if not comments:
            comments = load_recent_family_comments(limit=5)
            st.session_state["family_comments_cache"] = comments
    except Exception:  # noqa: BLE001
        comments = []
    count = len(comments)
    subtitle = (
        f"已有 {count} 条家庭观察，点击进入查看或新增。"
        if count
        else "记录家人对这次体检的看法，方便沟通和分歧检测。"
    )
    render_html(
        f"""
        <section class="block" style="padding:1rem 1.1rem;">
            <div class="block-head" style="margin-bottom:.35rem;">
                <div>
                    <h2 class="block-title" style="font-size:1.18rem;">家庭观察记录</h2>
                    <p class="block-subtitle">{html_escape(subtitle)}</p>
                </div>
            </div>
        </section>
        """
    )
    if st.button("记录家人看法 →", use_container_width=True, key="open_comments_view"):
        st.session_state["_comments_run_id"] = run_id
        st.session_state["active_view"] = "comments"
        st.rerun()


def comments_page(agent_result: dict[str, Any]) -> None:
    """家庭观察记录专属子页。"""
    _bc1, _bc2 = st.columns(2)
    with _bc1:
        if st.button("← 返回追问", use_container_width=True, key="back_from_comments_view"):
            st.session_state["active_view"] = "followup"
            st.rerun()
    with _bc2:
        if st.button("↑ 体检结论", use_container_width=True, key="comments_to_root"):
            st.session_state["active_view"] = "analysis"
            st.rerun()
    run_id = str(st.session_state.get("_comments_run_id", "") or
                 (agent_result.get("run_id", "") if agent_result else ""))
    discussion_block(run_id=run_id)


def ai_report_page(agent_result: dict[str, Any]) -> None:
    """第 2 步：AI 风险说明页（从体检结论点进来，报告 + 模式切换 + 进入追问）。"""
    agent_context = agent_result.get("agent_context", {}) if agent_result else {}

    if st.button("← 体检结论", key="back_from_ai_report"):
        st.session_state["active_view"] = "analysis"
        st.rerun()
    render_html(
        '<p style="font-size:0.72rem;color:var(--text-3);margin:0 0 0.6rem;">'
        '体检结论 &rsaquo; AI 风险说明</p>'
    )

    if not agent_result:
        st.info("请先完成一次一键智能体检，再查看 AI 风险说明。")
        return

    render_html("""
    <div style="padding:0.1rem 0 0.8rem;">
        <h2 style="font-size:1.2rem;font-weight:700;color:var(--text);margin:0 0 0.12rem;">
            本次 AI 风险说明
        </h2>
        <p style="font-size:0.82rem;color:var(--text-3);margin:0;">
            基于本次体检数据生成，不构成买卖建议。
        </p>
    </div>
    """)

    mode = st.radio(
        "报告模式",
        options=REPORT_MODES,
        horizontal=True,
        key="report_mode",
    )
    display_report = str(agent_result.get("ai_report", "") or "暂无风险说明。")
    report_source = str(agent_result.get("report_source", "local_fallback") or "local_fallback")
    cached_mode = str(agent_result.get("report_mode", DEFAULT_REPORT_MODE) or DEFAULT_REPORT_MODE)
    if agent_context and mode != cached_mode:
        with st.spinner("正在按新的报告模式生成说明..."):
            report_text, report_source, dinner_talk = _unpack_agent_report(
                generate_agent_report(agent_context, mode)
            )
        display_report = report_text
        agent_result["ai_report"] = display_report
        agent_result["dinner_talk"] = dinner_talk
        agent_result["report_source"] = report_source
        agent_result["report_mode"] = mode
        agent_context["ai_report"] = display_report
        agent_context["dinner_talk"] = dinner_talk
        agent_context["report_source"] = report_source
        agent_context["report_mode"] = mode
        agent_result["agent_context"] = agent_context
        st.session_state["agent_result"] = agent_result
    st.caption(f"报告来源：{_report_source_label(report_source)}")

    # 报告导出按钮
    try:
        _export_text = export_text_report(agent_result)
        st.download_button(
            "下载本次报告",
            data=_export_text.encode("utf-8"),
            file_name="family_risk_report.txt",
            mime="text/plain",
            use_container_width=True,
            help="下载本次体检完整报告（纯文本格式，可发给家人）",
            key="export_report_btn",
        )
    except Exception:  # noqa: BLE001
        pass

    render_html('<div class="card" style="padding:1.4rem;margin-top:0.6rem;">')
    st.markdown(display_report)
    render_html("</div>")

    if st.button("读完了，继续问 AI →", use_container_width=True,
                 key="goto_followup_from_report", type="primary"):
        st.session_state["active_view"] = "followup"
        st.rerun()


def followup_page(agent_result: dict[str, Any]) -> None:
    agent_context = agent_result.get("agent_context", {}) if agent_result else {}
    # 2 级深度页面：提供"返回上一级"和"直达体检结论"两个导航选项
    _bc1, _bc2 = st.columns(2)
    with _bc1:
        if st.button("← AI 风险说明", use_container_width=True, key="back_to_analysis_view"):
            st.session_state["active_view"] = "ai_report"
            st.rerun()
    with _bc2:
        if st.button("↑ 体检结论", use_container_width=True, key="followup_to_root"):
            st.session_state["active_view"] = "analysis"
            st.rerun()
    render_html(
        '<p style="font-size:0.72rem;color:var(--text-3);margin:0 0 0.6rem;">'
        '体检结论 &rsaquo; AI 风险说明 &rsaquo; AI 追问</p>'
    )
    if not agent_context:
        st.info("请先完成一次一键智能体检，再继续追问。")
        return

    _fup_mode = agent_result.get("report_mode", DEFAULT_REPORT_MODE) or DEFAULT_REPORT_MODE
    reverse_qa_block(agent_result, agent_context, _fup_mode)
    followup_block(agent_context)

    _fup_answers = list(st.session_state.get("followup_answers", []))
    _has_followup = bool(_fup_answers)
    _fup_ans_n = len(_fup_answers)
    _fup_run_id = str(agent_result.get("run_id", "") if agent_result else "")
    _cta_label = (
        f"完成追问（{_fup_ans_n} 条），记录家人看法 →"
        if _has_followup
        else "不追问了，直接记录家人看法 →"
    )
    render_html(
        '<div style="margin:1rem 0 0.45rem;color:var(--text-3);font-size:0.8rem;">'
        '下一步会用 30 秒记录家人的关注点，方便以后对比家庭看法变化。</div>'
    )
    if st.button(
        _cta_label,
        use_container_width=True,
        key="fup_to_guided_comment",
        type="primary",
    ):
        st.session_state["_comments_run_id"] = _fup_run_id
        st.session_state["active_view"] = "comments"
        st.rerun()
    with st.expander("追问历史保存情况", expanded=False):
        latest_status = st.session_state.get("last_followup_save") or get_last_followup_save_status()
        backend = latest_status.get("backend", "local_csv")
        backend_label = (
            "Supabase 云数据库"
            if backend == "supabase"
            else "游客本地模式"
            if backend == "guest_local"
            else "本地 CSV"
        )
        saved_label = "已保存" if latest_status.get("saved") else "未保存"
        st.write(f"- 最近一次保存状态：{saved_label}")
        st.write(f"- 保存位置：{backend_label}")
        if latest_status.get("error"):
            st.write(f"- 保存说明：{latest_status.get('error')}")
        try:
            recent = load_recent_followup_history(limit=5)
        except Exception:  # noqa: BLE001
            recent = []
        st.write(f"- 最近读取到的追问记录数量：{len(recent)}")
        if recent:
            st.caption("最近保存的追问：")
        for row in recent[:3]:
            created_at = format_datetime_for_display(row.get("created_at"))
            st.write(f"- {created_at}｜{row.get('question', '')}")


def history_page(agent_result: dict[str, Any]) -> None:
    if st.button("← 体检结论", key="back_from_history_view"):
        st.session_state["active_view"] = "analysis"
        st.rerun()
    render_html(
        """
        <div style="padding:0.25rem 0 0.85rem;">
            <p style="font-size:0.72rem;color:var(--text-3);margin:0 0 0.25rem;">
                体检结论 &rsaquo; 历史
            </p>
            <h2 style="font-size:1.2rem;font-weight:700;color:var(--text);margin:0 0 0.12rem;">
                历史体检
            </h2>
            <p style="font-size:0.82rem;color:var(--text-3);margin:0;">
                回看最近记录、评分变化和仍需关注的风险点。
            </p>
        </div>
        """
    )
    history_replay_block(agent_result)
    history_records_block()


def next_steps_entry_block(agent_result: dict[str, Any]) -> None:
    """智能引导卡 — 体检结论底部，感知上下文，引导进入追问/记录/历史子页。"""
    followup_answers = list(st.session_state.get("followup_answers", []))
    followup_count = len(followup_answers)
    try:
        comments: list[dict[str, Any]] = st.session_state.get("family_comments_cache") or []
        if not comments:
            comments = load_recent_family_comments(limit=5)
            st.session_state["family_comments_cache"] = comments
    except Exception:  # noqa: BLE001
        comments = []
    comment_count = len(comments)

    followup_chip = f"{followup_count} 条追问" if followup_count else "可追问 AI"
    comment_chip  = f"{comment_count} 条记录" if comment_count else "记录家人看法"

    render_html(f"""
    <div class="fr-step-card">
        <p class="fr-step-kicker">Agent · Next</p>
        <p class="fr-step-title">结论已生成，继续读懂这次风险</p>
        <div class="fr-mini-nav">
            <span>AI 风险说明</span>
            <span>{html_escape(followup_chip)}</span>
            <span>{html_escape(comment_chip)}</span>
        </div>
        <p class="fr-step-sub">建议先看 AI 说明，再追问一个问题，最后记录家人看法。</p>
    </div>
    """)
    if st.button("查看 AI 风险说明 →", use_container_width=True,
                 key="open_ai_report_from_next", type="primary"):
        st.session_state["active_view"] = "ai_report"
        st.rerun()


def guided_comment_page(agent_result: dict[str, Any]) -> None:
    comments_page(agent_result)


def analysis_page() -> None:
    agent_result = st.session_state.get("agent_result", {})
    active_view = st.session_state.get("active_view", "analysis")

    if active_view == "followup":
        followup_page(agent_result)
    elif active_view == "history":
        history_page(agent_result)
    elif active_view == "comments":
        comments_page(agent_result)
    elif active_view == "guided_comment":
        guided_comment_page(agent_result)
    elif active_view == "ai_report":
        ai_report_page(agent_result)
    else:
        agent_result_block(agent_result)

    render_html(f'<div class="page-foot">{REPORT_DISCLAIMER}</div>')

init_state()
inject_css()
site_header()

if not auth_gate():
    render_html(f'<div class="page-foot">{REPORT_DISCLAIMER}</div>')
    st.stop()

top_toolbar()

if "analysis" in st.session_state:
    analysis_page()
else:
    home_page()
