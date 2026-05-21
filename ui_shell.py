from __future__ import annotations

from html import escape


def html_escape(value: object) -> str:
    return escape(str(value if value is not None else ""))


def site_header_html(app_title: str, app_subtitle: str) -> str:
    return f"""
    <div class="brand" style="padding: 0.2rem 0 0.05rem;">
        <div class="brand-mark">
            <svg width="40" height="40" viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
                <defs>
                    <radialGradient id="fi-bg" cx="50%" cy="40%" r="60%">
                        <stop offset="0%" stop-color="#fff8f5"/>
                        <stop offset="100%" stop-color="#edddd6"/>
                    </radialGradient>
                </defs>
                <circle cx="20" cy="20" r="18.5" fill="url(#fi-bg)" stroke="#7a3e2e" stroke-width="1.5"/>
                <path d="M5 20 L12 20 L13 22 L15 10 L17 28 L19 19 L21 20 L35 20"
                      stroke="#7a3e2e" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
        </div>
        <div>
            <div class="brand-cn">{html_escape(app_title)}<span class="brand-badge">AI</span></div>
            <div class="brand-en">{html_escape(app_subtitle)}</div>
        </div>
    </div>
    """


def agent_flow_html(home_disclaimer: str) -> str:
    return f"""
    <section class="agent-flow-card">
        <div class="agent-flow-head">
            <div class="eyebrow mini">Agent 流程</div>
            <p>填持仓，看风险，再追问和记录家人看法。</p>
        </div>
        <div class="agent-flow-steps">
            <span><b>1</b> 输入</span>
            <span><b>2</b> 体检</span>
            <span><b>3</b> 追问</span>
            <span><b>4</b> 记录</span>
        </div>
        <div class="agent-flow-note">{html_escape(home_disclaimer)}</div>
    </section>
    """
