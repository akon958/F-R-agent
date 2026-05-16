from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from analyzer import analyze_portfolio
from data_fetcher import get_cache_summary
from data_fetcher import get_stock_metrics
from data_fetcher import normalize_code
from data_fetcher import refresh_current_holdings_cache
from data_fetcher import refresh_market_cache
from ai_report import generate_parent_friendly_report
from report_generator import generate_txt_report
from report_generator import money
from report_generator import percent


APP_TITLE = "家庭投资雷达 Agent"
DEFAULT_CODES = ["600519", "000001", "300750"]
DEFAULT_AMOUNTS = [20000.0, 10000.0, 0.0]

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

st.set_page_config(page_title=APP_TITLE, layout="centered", initial_sidebar_state="collapsed")

st.markdown(
    """
    <style>
    html, body, [class*="css"] {
        font-size: 18px;
    }
    .main .block-container {
        max-width: 760px;
        padding: 1rem 0.85rem 2.4rem;
    }
    h1 {
        font-size: 1.9rem !important;
        line-height: 1.2 !important;
        margin-bottom: 0.35rem !important;
    }
    h2, h3 {
        line-height: 1.28 !important;
    }
    p, li, label, .stMarkdown {
        font-size: 1.04rem !important;
        line-height: 1.65 !important;
    }
    div[data-testid="stNumberInput"] input,
    div[data-testid="stTextInput"] input,
    div[data-testid="stSelectbox"] div {
        min-height: 48px;
        font-size: 1.05rem !important;
    }
    div[data-testid="stFormSubmitButton"] button,
    div[data-testid="stButton"] button,
    div[data-testid="stDownloadButton"] button {
        min-height: 54px;
        border-radius: 12px;
        font-size: 1.08rem;
        font-weight: 800;
    }
    div[data-testid="stFormSubmitButton"] button {
        background: #0f766e;
        color: #fff;
        border: 0;
        box-shadow: 0 8px 18px rgba(15, 118, 110, 0.22);
    }
    div[data-testid="stMetric"] {
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 0.75rem;
        background: #ffffff;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.6rem;
    }
    .intro-card, .holding-card, .plain-card {
        border: 1px solid #e2e8f0;
        background: #f8fafc;
        border-radius: 14px;
        padding: 0.95rem 1rem;
        margin: 0.75rem 0;
    }
    .holding-card {
        background: #ffffff;
    }
    .risk-card {
        border-radius: 16px;
        padding: 1.05rem;
        margin: 1rem 0;
        border: 2px solid transparent;
    }
    .risk-card h2, .risk-card h3 {
        margin: 0 0 0.5rem;
    }
    .green {
        background: #ecfdf3;
        border-color: #86efac;
        color: #14532d;
    }
    .yellow {
        background: #fffbeb;
        border-color: #facc15;
        color: #713f12;
    }
    .red {
        background: #fef2f2;
        border-color: #fca5a5;
        color: #7f1d1d;
    }
    .notice {
        color: #475569;
        font-size: 0.95rem !important;
    }
    .mini {
        color: #64748b;
        font-size: 0.92rem !important;
    }
    @media (max-width: 640px) {
        html, body, [class*="css"] {
            font-size: 19px;
        }
        .main .block-container {
            padding-left: 0.72rem;
            padding-right: 0.72rem;
        }
        h1 {
            font-size: 1.72rem !important;
        }
        div[data-testid="column"] {
            width: 100% !important;
            flex: 1 1 100% !important;
        }
        div[data-testid="stMetric"] {
            margin-bottom: 0.65rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def init_state() -> None:
    if "holding_rows" not in st.session_state:
        st.session_state.holding_rows = 3


def clean_holdings(raw_rows: list[dict[str, float | str]]) -> list[dict[str, float | str]]:
    holdings: list[dict[str, float | str]] = []
    for row in raw_rows:
        code = normalize_code(str(row["code"]))
        amount = float(row["amount"])
        if code and amount > 0:
            holdings.append({"code": code, "amount": amount})
    return holdings


def show_disclaimer() -> None:
    st.markdown(
        '<p class="notice">本工具仅用于家庭投资风险体检和学习参考，不构成投资建议。市场有风险，投资需谨慎。</p>',
        unsafe_allow_html=True,
    )


init_state()

st.title(APP_TITLE)
st.markdown(
    """
    <div class="intro-card">
    给家人看的手机网页工具。输入现金和持仓后，它会用红、黄、绿三种颜色提示风险。
    它不荐股，不预测明天涨跌，不自动交易，也不承诺收益。
    </div>
    """,
    unsafe_allow_html=True,
)

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
        code_value = st.session_state.get(
            f"code_{idx}",
            DEFAULT_CODES[idx] if idx < len(DEFAULT_CODES) else "",
        )
        normalized_code = normalize_code(str(code_value))
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

if st.button("增加一行持仓", use_container_width=True):
    st.session_state.holding_rows += 1
    st.rerun()

with st.form("family_risk_form"):
    cash = st.number_input("家庭可用于投资的现金金额（元）", min_value=0.0, value=50000.0, step=1000.0)
    risk_profile = st.selectbox("家庭风险承受能力", ["稳健", "平衡", "积极"], index=1)

    st.markdown("### 持仓")
    st.markdown('<p class="mini">默认 3 行。只填写有持仓的股票或基金，金额填 0 的行会自动忽略。</p>', unsafe_allow_html=True)

    raw_holdings: list[dict[str, float | str]] = []
    for index in range(st.session_state.holding_rows):
        with st.container(border=True):
            st.markdown(f"**第 {index + 1} 只持仓**")
            code = st.text_input(
                "股票/基金代码",
                value=DEFAULT_CODES[index] if index < len(DEFAULT_CODES) else "",
                key=f"code_{index}",
                placeholder="例如 600519，支持任意 A 股代码",
            )
            amount = st.number_input(
                "持仓金额（元）",
                min_value=0.0,
                value=DEFAULT_AMOUNTS[index] if index < len(DEFAULT_AMOUNTS) else 0.0,
                step=1000.0,
                key=f"amount_{index}",
            )
            raw_holdings.append({"code": code, "amount": amount})

    submitted = st.form_submit_button("开始体检", use_container_width=True)

show_disclaimer()

if not submitted:
    st.markdown(
        """
        <div class="risk-card green"><h3>绿色：风险较低</h3><p>不是说一定赚钱，只是当前看起来没那么紧张。</p></div>
        <div class="risk-card yellow"><h3>黄色：需要注意</h3><p>有些地方要多看一眼，先别急着加钱。</p></div>
        <div class="risk-card red"><h3>红色：风险偏高</h3><p>先保护家庭现金和睡眠质量。</p></div>
        """,
        unsafe_allow_html=True,
    )

if submitted:
    holdings = clean_holdings(raw_holdings)
    if not holdings:
        st.error("请至少填写一只持仓，并填写大于 0 的持仓金额。")
        st.stop()

    try:
        with st.spinner("正在体检中，先查数据，再做保守判断..."):
            codes = [str(item["code"]) for item in holdings]
            stocks, fetch_warnings = get_stock_metrics(codes)
            analysis = analyze_portfolio(cash, risk_profile, holdings, stocks)
        st.session_state["analysis"] = analysis
        st.session_state["fetch_warnings"] = fetch_warnings
        st.session_state.pop("ai_report", None)
        st.session_state.pop("ai_report_failed", None)
    except Exception:  # noqa: BLE001
        st.error("体检时遇到问题，但页面没有崩。请稍后重试，或检查 stock_metrics.csv 是否存在。")
        st.stop()

if "analysis" in st.session_state:
    analysis = st.session_state["analysis"]
    fetch_warnings = st.session_state.get("fetch_warnings", [])

    for warning in fetch_warnings:
        st.warning(warning)

    st.markdown(
        f"""
        <div class="risk-card {analysis['color']}">
        <h2>{analysis['level']}：{analysis['level_text']}</h2>
        <p><strong>综合评分：{analysis['score']}/100</strong></p>
        <p>{analysis['advice'][0]}</p>
        <p class="mini">数据状态：{analysis['data_status']}｜分析时间：{analysis['analysis_time']}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)
    col1.metric("家庭总资产", money(analysis["total_assets"]))
    col2.metric("现金比例", percent(analysis["cash_ratio"]))
    col3, col4 = st.columns(2)
    col3.metric("股票/基金仓位", percent(analysis["stock_ratio"]))
    col4.metric("单只最大占比", percent(analysis["max_single_ratio"]))
    st.metric("行业集中度", f"{analysis['top_industry']} {percent(analysis['industry_concentration'])}")

    st.subheader("资产配置")
    if analysis["total_assets"] <= 0:
        st.info("现金和持仓都为 0，暂时没有可画的资产配置图。")
    else:
        fig, ax = plt.subplots(figsize=(4.6, 4.1))
        ax.pie(
            [analysis["cash"], analysis["stock_total"]],
            labels=["现金", "股票/基金"],
            autopct="%1.1f%%",
            startangle=90,
            colors=["#7dd3fc", "#fbbf24"],
            textprops={"fontsize": 13},
        )
        ax.axis("equal")
        st.pyplot(fig, clear_figure=True)

    st.subheader("四项得分")
    score_cols = st.columns(2)
    for idx, (name, score) in enumerate(analysis["module_scores"].items()):
        score_cols[idx % 2].metric(name, f"{score:.0f}/100")

    st.subheader("持仓明细")
    detail_rows = []
    for item in analysis["stock_results"]:
        detail_rows.append(
            {
                "代码": item["code"],
                "名称": item["name"],
                "金额": money(item["amount"]),
                "占比": percent(item["single_ratio"]),
                "行业": item["industry"],
                "数据": item["data_source"],
                "风险": item["level"],
            }
        )
    st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

    st.subheader("每只持仓怎么看")
    for item in analysis["stock_results"]:
        st.markdown(
            f"""
            <div class="risk-card {item['color']}">
            <h3>{item['code']} {item['name']}：{item['level']}</h3>
            <p>公司底子：{item['financial_text']}</p>
            <p>交易热度：{item['heat_text']}</p>
            <p>仓位提醒：{'；'.join(item['position_notes'])}</p>
            <p class="mini">数据来源：行情 {item['market_source']}；财务 {item['finance_source']}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.expander(f"查看 {item['name']} 的原因"):
            st.write("公司财务质量评价")
            for note in item["financial_notes"]:
                st.write(f"- {note}")
            st.write("交易热度评价")
            for note in item["heat_notes"]:
                st.write(f"- {note}")
            st.write("仓位风险评价")
            for note in item["position_notes"]:
                st.write(f"- {note}")

    st.subheader("主要风险提示")
    st.markdown('<div class="plain-card">', unsafe_allow_html=True)
    for note in analysis["risk_notes"]:
        st.write(f"- {note}")
    st.markdown("</div>", unsafe_allow_html=True)

    st.subheader("给家人的建议")
    st.markdown('<div class="plain-card">', unsafe_allow_html=True)
    for note in analysis["advice"]:
        st.write(f"- {note}")
    st.markdown("</div>", unsafe_allow_html=True)

    st.warning("本工具只做风险体检，不构成投资建议；不预测涨跌，不自动交易，不承诺收益。")

    st.subheader("AI 风险说明")
    st.caption("可选功能：只在点击按钮后调用 DeepSeek，用来把上面的体检结果改写成更适合家人看的话。")

    deepseek_api_key = st.secrets.get("DEEPSEEK_API_KEY", "")
    if "ai_report" in st.session_state:
        _ai_status = "已生成"
    elif st.session_state.get("ai_report_failed"):
        _ai_status = "调用失败"
    elif deepseek_api_key:
        _ai_status = "已配置"
    else:
        _ai_status = "未配置"
    st.caption(f"AI 分析状态：{_ai_status}")

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
        st.markdown(st.session_state["ai_report"])

    report_text = generate_txt_report(analysis)
    st.download_button(
        "下载 txt 报告",
        data=report_text.encode("utf-8"),
        file_name="家庭投资雷达体检报告.txt",
        mime="text/plain",
        use_container_width=True,
    )

show_disclaimer()
