from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from analyzer import analyze_portfolio
from data_fetcher import (
    get_cache_summary,
    get_stock_metrics,
    normalize_code,
    refresh_current_holdings_cache,
)
from report_generator import generate_txt_report, money, percent
from ai_report import generate_ai_report, is_ai_available

APP_TITLE = "家庭投资雷达 Agent"
DEFAULT_CODES = ["600519", "000001", "300750"]
DEFAULT_AMOUNTS = [20000.0, 10000.0, 0.0]

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

st.set_page_config(page_title=APP_TITLE, layout="centered", initial_sidebar_state="collapsed")

st.markdown(
    """
<style>
html, body, [class*="css"] { font-size: 18px; }
.main .block-container { max-width: 760px; padding: 1rem 0.85rem 2.4rem; }
h1 { font-size: 1.9rem !important; line-height: 1.2 !important; margin-bottom: 0.35rem !important; }
h2, h3 { line-height: 1.28 !important; }
p, li, label, .stMarkdown { font-size: 1.04rem !important; line-height: 1.65 !important; }
div[data-testid="stNumberInput"] input,
div[data-testid="stTextInput"] input,
div[data-testid="stSelectbox"] div { min-height: 48px; font-size: 1.05rem !important; }
div[data-testid="stFormSubmitButton"] button,
div[data-testid="stButton"] button,
div[data-testid="stDownloadButton"] button {
    min-height: 54px; border-radius: 12px; font-size: 1.08rem; font-weight: 800;
}
div[data-testid="stFormSubmitButton"] button {
    background: #0f766e; color: #fff; border: 0;
    box-shadow: 0 8px 18px rgba(15,118,110,0.22);
}
div[data-testid="stMetric"] {
    border: 1px solid #e5e7eb; border-radius: 12px; padding: 0.75rem; background: #ffffff;
}
div[data-testid="stMetricValue"] { font-size: 1.6rem; }
.intro-card, .plain-card {
    border: 1px solid #e2e8f0; background: #f8fafc;
    border-radius: 14px; padding: 0.95rem 1rem; margin: 0.75rem 0;
}
.risk-card {
    border-radius: 16px; padding: 1.05rem; margin: 1rem 0; border: 2px solid transparent;
}
.risk-card h2, .risk-card h3 { margin: 0 0 0.5rem; }
.green  { background:#ecfdf3; border-color:#86efac; color:#14532d; }
.yellow { background:#fffbeb; border-color:#facc15; color:#713f12; }
.red    { background:#fef2f2; border-color:#fca5a5; color:#7f1d1d; }
.missing-card {
    border: 1.5px dashed #94a3b8; background: #f1f5f9;
    border-radius: 14px; padding: 0.9rem 1rem; margin: 0.5rem 0; color: #334155;
}
.notice { color: #475569; font-size: 0.95rem !important; }
.mini   { color: #64748b; font-size: 0.92rem !important; }
.ai-card {
    border: 1.5px solid #c7d2fe; background: #f5f3ff;
    border-radius: 14px; padding: 1rem 1.1rem; margin: 0.75rem 0;
    color: #1e1b4b; line-height: 1.8;
}
@media (max-width: 640px) {
    html, body, [class*="css"] { font-size: 19px; }
    .main .block-container { padding-left: 0.72rem; padding-right: 0.72rem; }
    h1 { font-size: 1.72rem !important; }
    div[data-testid="column"] { width:100% !important; flex:1 1 100% !important; }
    div[data-testid="stMetric"] { margin-bottom: 0.65rem; }
}
</style>
""",
    unsafe_allow_html=True,
)


# ── session_state 初始化 ────────────────────────────────────────────
def init_state() -> None:
    defaults: dict = {
        "holding_rows":    3,
        "analysis_result": None,
        "fetch_warnings":  [],
        "ai_report":       None,
        "ai_report_error": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()


def show_disclaimer() -> None:
    st.markdown(
        '<p class="notice">本工具仅用于家庭投资风险体检和学习参考，不构成投资建议。市场有风险，投资需谨慎。</p>',
        unsafe_allow_html=True,
    )


def clean_holdings(raw_rows: list[dict]) -> list[dict]:
    result = []
    for row in raw_rows:
        code = normalize_code(str(row["code"]))
        amount = float(row["amount"])
        if code and amount > 0:
            result.append({"code": code, "amount": amount})
    return result


# ── 页面头部 ────────────────────────────────────────────────────────
st.title(APP_TITLE)
st.markdown(
    """
<div class="intro-card">
给家人看的手机网页工具。输入现金和持仓后，用红黄绿提示风险。
不荐股，不预测涨跌，不自动交易，不承诺收益。
</div>
""",
    unsafe_allow_html=True,
)

# ── 缓存状态（始终可见）────────────────────────────────────────────
try:
    _summary = get_cache_summary()
except Exception:  # noqa: BLE001
    _summary = {"count": 0, "latest_update": "未知", "finance_count": 0,
                "message": "缓存读取失败，不影响体检。"}

_cache_count = _summary.get("count", 0)
_cache_time  = _summary.get("latest_update", "未知")
if _cache_count > 0:
    st.caption(f"📦 本地缓存：{_cache_count} 只股票｜数据时间：{_cache_time}")
else:
    st.warning(
        "本地缓存为空。请在本地电脑运行 `python update_cache.py`，"
        "再把 stock_metrics.csv 上传到 GitHub。"
    )

# ── 高级选项（默认收起）────────────────────────────────────────────
with st.expander("高级选项：手动更新当前持仓数据", expanded=False):
    st.caption(
        "以下操作会尝试联网调用 AkShare，只更新当前填写的股票。"
        "推荐在本地运行 python update_cache.py 做全量更新。"
    )
    _current_codes: list[str] = []
    for _idx in range(st.session_state.holding_rows):
        _raw = st.session_state.get(
            f"code_{_idx}",
            DEFAULT_CODES[_idx] if _idx < len(DEFAULT_CODES) else "",
        )
        _nc = normalize_code(str(_raw))
        if _nc:
            _current_codes.append(_nc)

    if st.button("手动更新当前持仓数据", use_container_width=True):
        with st.spinner("正在尝试联网更新..."):
            _upd_summary, _upd_msgs = refresh_current_holdings_cache(_current_codes)
        for _msg in _upd_msgs:
            st.info(_msg)
        st.success(f"缓存现有 {_upd_summary.get('count', 0)} 只标的。")

    if st.button("增加一行持仓", use_container_width=True):
        st.session_state.holding_rows += 1
        st.rerun()

# ── 输入表单 ────────────────────────────────────────────────────────
with st.form("family_risk_form"):
    cash = st.number_input(
        "家庭可用于投资的现金金额（元）", min_value=0.0, value=50000.0, step=1000.0
    )
    risk_profile = st.selectbox("家庭风险承受能力", ["稳健", "平衡", "积极"], index=1)

    st.markdown("### 持仓")
    st.markdown(
        '<p class="mini">默认 3 行，金额填 0 的行自动忽略。'
        "缓存里没有的股票，可展开下方补充信息。</p>",
        unsafe_allow_html=True,
    )

    raw_holdings: list[dict] = []
    manual_overrides: dict[str, dict] = {}   # {normalized_code: {name, industry, ...}}

    for index in range(st.session_state.holding_rows):
        with st.container(border=True):
            st.markdown(f"**第 {index + 1} 只持仓**")
            code = st.text_input(
                "股票/基金代码",
                value=DEFAULT_CODES[index] if index < len(DEFAULT_CODES) else "",
                key=f"code_{index}",
                placeholder="例如 600519",
            )
            amount = st.number_input(
                "持仓金额（元）",
                min_value=0.0,
                value=DEFAULT_AMOUNTS[index] if index < len(DEFAULT_AMOUNTS) else 0.0,
                step=1000.0,
                key=f"amount_{index}",
            )
            raw_holdings.append({"code": code, "amount": amount})

            # 手动补充（缓存缺失时使用）
            nc = normalize_code(str(code))
            if nc:
                with st.expander(f"手动补充 {nc} 的信息（缓存没有时使用）", expanded=False):
                    ca, cb = st.columns(2)
                    m_name = ca.text_input(
                        "股票/基金名称",
                        key=f"mname_{index}",
                        placeholder="例如 贵州茅台",
                    )
                    m_industry = cb.text_input(
                        "所属行业",
                        key=f"mind_{index}",
                        placeholder="例如 食品饮料",
                    )
                    cc, cd = st.columns(2)
                    m_asset_type = cc.selectbox(
                        "资产类型",
                        ["股票", "基金", "ETF", "债券", "其他"],
                        key=f"masset_{index}",
                    )
                    m_note = cd.text_input(
                        "备注",
                        key=f"mnote_{index}",
                        placeholder="可选",
                    )
                    if any([m_name, m_industry, m_note]):
                        manual_overrides[nc] = {
                            "name":       m_name,
                            "industry":   m_industry,
                            "asset_type": m_asset_type,
                            "note":       m_note,
                        }

    submitted = st.form_submit_button("开始体检", use_container_width=True)

show_disclaimer()

# ── 体检计算 ────────────────────────────────────────────────────────
if submitted:
    holdings = clean_holdings(raw_holdings)
    if not holdings:
        st.error("请至少填写一只持仓，并填写大于 0 的持仓金额。")
        st.stop()

    try:
        with st.spinner("正在体检中..."):
            codes = [h["code"] for h in holdings]
            stocks, fetch_warnings = get_stock_metrics(codes, manual_overrides)
            analysis = analyze_portfolio(cash, risk_profile, holdings, stocks)
    except Exception:  # noqa: BLE001
        st.error("体检时遇到问题，页面没有崩。请稍后重试，或检查 stock_metrics.csv 是否存在。")
        st.stop()

    st.session_state.analysis_result = analysis
    st.session_state.fetch_warnings  = fetch_warnings
    st.session_state.ai_report       = None
    st.session_state.ai_report_error = None

# ── 结果渲染 ────────────────────────────────────────────────────────
analysis: dict | None = st.session_state.analysis_result

if analysis is None:
    st.markdown(
        """
<div class="risk-card green"><h3>绿色：风险较低</h3><p>不是说一定赚钱，只是当前看起来没那么紧张。</p></div>
<div class="risk-card yellow"><h3>黄色：需要注意</h3><p>有些地方要多看一眼，先别急着加钱。</p></div>
<div class="risk-card red"><h3>红色：风险偏高</h3><p>先保护家庭现金和睡眠质量。</p></div>
""",
        unsafe_allow_html=True,
    )
else:
    for w in st.session_state.fetch_warnings:
        st.warning(w)

    # 1. 综合评分卡
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

    # 2. 核心指标
    c1, c2 = st.columns(2)
    c1.metric("家庭总资产", money(analysis["total_assets"]))
    c2.metric("现金比例",   percent(analysis["cash_ratio"]))
    c3, c4 = st.columns(2)
    c3.metric("股票/基金仓位", percent(analysis["stock_ratio"]))
    c4.metric("单只最大占比",  percent(analysis["max_single_ratio"]))
    st.metric("行业集中度", f"{analysis['top_industry']} {percent(analysis['industry_concentration'])}")

    # 3. 数据缺失提示
    missing_items = [
        item for item in analysis.get("stock_results", [])
        if item.get("data_source") == "数据缺失"
    ]
    if missing_items:
        missing_codes = "、".join(item["code"] for item in missing_items)
        st.markdown(
            f'<div class="missing-card">⚠️ <strong>{missing_codes}</strong> 在本地缓存中未找到。'
            "AI 说明只会根据用户手动填写的信息分析，不会编造行情数据。<br>"
            "如需完整数据：本地运行 <code>python update_cache.py</code> 后上传 stock_metrics.csv。</div>",
            unsafe_allow_html=True,
        )

    # 4. 主要风险提示
    st.subheader("主要风险提示")
    st.markdown('<div class="plain-card">', unsafe_allow_html=True)
    for note in analysis["risk_notes"]:
        st.write(f"- {note}")
    st.markdown("</div>", unsafe_allow_html=True)

    # 5. 给家人的建议
    st.subheader("给家人的建议")
    st.markdown('<div class="plain-card">', unsafe_allow_html=True)
    for note in analysis["advice"]:
        st.write(f"- {note}")
    st.markdown("</div>", unsafe_allow_html=True)

    st.warning("本工具只做风险体检，不构成投资建议；不预测涨跌，不自动交易，不承诺收益。")

    # 6. AI 风险说明
    st.subheader("AI 风险说明（给父母看）")

    if not is_ai_available():
        st.caption("未配置 AI 分析功能。")
    else:
        if st.session_state.ai_report:
            st.markdown('<div class="ai-card">', unsafe_allow_html=True)
            st.write(st.session_state.ai_report)
            st.markdown("</div>", unsafe_allow_html=True)
            st.caption("以上为 AI 生成的风险说明，仅供家庭参考，不构成投资建议。市场有风险，投资需谨慎。")
            if st.button("重新生成 AI 风险说明", use_container_width=True):
                st.session_state.ai_report = None
                st.session_state.ai_report_error = None

        elif st.session_state.ai_report_error:
            st.warning(st.session_state.ai_report_error)
            if st.button("重试 AI 风险说明", use_container_width=True):
                st.session_state.ai_report_error = None

        else:
            st.caption("点击下方按钮，AI 会用通俗语言解释这份体检结果，方便发给父母阅读。")
            if st.button("生成 AI 风险说明", use_container_width=True):
                with st.spinner("AI 正在生成说明，大约需要几秒钟..."):
                    report_text, error_msg = generate_ai_report(analysis)
                if report_text:
                    st.session_state.ai_report = report_text
                    st.session_state.ai_report_error = None
                else:
                    st.session_state.ai_report = None
                    st.session_state.ai_report_error = (
                        error_msg or "AI 分析暂时不可用，基础风险体检结果不受影响。"
                    )
                st.rerun()

    # 7. 资产配置饼图（默认收起）
    with st.expander("查看资产配置饼图", expanded=False):
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

    # 8. 四项得分（默认收起）
    with st.expander("查看四项得分明细", expanded=False):
        sc = st.columns(2)
        for i, (name, score) in enumerate(analysis["module_scores"].items()):
            sc[i % 2].metric(name, f"{score:.0f}/100")

    # 9. 持仓明细表格（默认收起）
    with st.expander("查看持仓明细表格", expanded=False):
        detail_rows = [
            {
                "代码": item["code"],
                "名称": item["name"],
                "金额": money(item["amount"]),
                "占比": percent(item["single_ratio"]),
                "行业": item["industry"],
                "类型": item.get("asset_type", "股票"),
                "数据": item["data_source"],
                "风险": item["level"],
            }
            for item in analysis["stock_results"]
        ]
        st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

    # 10. 每只持仓详情卡
    st.subheader("每只持仓怎么看")
    for item in analysis["stock_results"]:
        note_str = item.get("note") or ""
        note_html = f"<p>备注：{note_str}</p>" if note_str else ""
        st.markdown(
            f"""
<div class="risk-card {item['color']}">
<h3>{item['code']} {item['name']}：{item['level']}</h3>
<p>公司底子：{item['financial_text']}</p>
<p>交易热度：{item['heat_text']}</p>
<p>仓位提醒：{'；'.join(item['position_notes'])}</p>
{note_html}
<p class="mini">数据来源：行情 {item['market_source']}；财务 {item['finance_source']}</p>
</div>
""",
            unsafe_allow_html=True,
        )
        with st.expander(f"查看 {item['name']}（{item['level']}）详情"):
            st.write("公司财务质量评价")
            for n in item["financial_notes"]:
                st.write(f"- {n}")
            st.write("交易热度评价")
            for n in item["heat_notes"]:
                st.write(f"- {n}")
            st.write("仓位风险评价")
            for n in item["position_notes"]:
                st.write(f"- {n}")

    # 11. 下载报告
    report_text = generate_txt_report(analysis)
    st.download_button(
        "下载 txt 报告",
        data=report_text.encode("utf-8"),
        file_name="家庭投资雷达体检报告.txt",
        mime="text/plain",
        use_container_width=True,
    )

    show_disclaimer()
