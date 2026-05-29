# CLAUDE.md

给 AI 协作者（Claude / Codex）的项目级说明。仓库根目录保留这一份即可。以后新对话可以先说：

```text
请先读 CLAUDE.md，所有改动遵守里面的约束。
本次任务：……
```

本文件是长期规则，不要因为单次任务临时违反。确实需要违反时，必须先向 akon958 说明原因并等待确认。

---

## 1. 项目定位

项目名：FamilyReader

产品名：FamilyReader / 家庭持仓读懂器

一句话定位：给不懂技术、不懂投资的父母使用的手机网页工具，用来读懂家庭持仓风险、风险解释、家庭沟通辅助和学习参考。

本项目不是：

- 荐股软件
- 诊股软件
- 涨跌预测工具
- 自动交易系统
- 东方财富 / 同花顺替代品
- 量化交易系统

本项目只做：

- 家庭持仓风险体检
- 公司质量、交易热度、仓位集中、现金比例等风险解释
- 家庭成员观察记录
- 家庭分歧检测
- AI 风险说明和追问
- 历史记录保存

所有输出必须保守、通俗、适合父母阅读。

---

## 2. 绝对安全边界

任何页面、报告、追问、总结、分歧检测、观察解释中都不能给确定性交易建议。

禁止输出或暗示：

- 买入
- 卖出
- 加仓
- 减仓
- 推荐
- 强烈买入
- 马上操作
- 抄底
- 必涨
- 一定赚钱
- 保证收益
- 预测明天涨跌
- 自动交易

允许的表达方向：

- 继续观察
- 重点关注
- 先沟通一致
- 定期复盘
- 保留现金备用
- 注意集中度
- 数据不足时不要下结论
- 本工具只做风险体检和学习参考

固定免责声明必须保留：

```text
本工具只做家庭投资风险体检和学习参考，不构成任何投资建议，也不替任何人做交易决定。
```

如果用户原文在家庭观察记录里写了交易相关词，可以保存原文；但 AI 总结和系统解释不能把它扩展成交易建议。

---

## 3. 技术栈和部署方式

- Python
- Streamlit 手机网页
- pandas / numpy / matplotlib
- AkShare：只用于本地手动更新缓存
- DeepSeek API：通过 OpenAI Python SDK 调用
- Supabase：用于云端保存历史、追问、反馈、家庭观察记录
- stock_metrics.csv：Streamlit Cloud 默认读取的本地缓存文件
- Streamlit Secrets：保存 `DEEPSEEK_API_KEY`、`SUPABASE_URL`、`SUPABASE_KEY`

数据更新工作流：

```text
本地运行 update_cache.py
↓
更新 stock_metrics.csv
↓
上传 / push 到 GitHub
↓
Streamlit Cloud 自动重新部署
↓
手机端读取更新后的 stock_metrics.csv
```

重要原则：

- 页面启动时不要自动抓 AkShare。
- Streamlit Cloud 运行时默认读 `stock_metrics.csv`。
- AkShare 抓取只在本地手动运行 `update_cache.py`。
- DeepSeek 不作为行情数据源。
- Supabase 不可用时必须回退本地 CSV，页面不能崩溃。

---

## 4. 文件职责

| 文件 | 职责 |
| --- | --- |
| `app.py` | Streamlit 页面入口，只负责界面、按钮、展示、调用其他模块 |
| `config.py` | 产品名、免责声明、报告模式、风险承受选项、合规替换词等统一配置 |
| `agent.py` | 一键智能体检主流程，核心入口是 `run_family_risk_agent()` |
| `data_fetcher.py` | 读取和标准化 `stock_metrics.csv`，处理缓存和字段映射 |
| `analyzer.py` | 风险评分、组合分析、家庭分歧检测 |
| `ai_report.py` | DeepSeek 主报告、追问、爸妈版说明、本地兜底 |
| `storage.py` | Supabase 优先、本地 CSV 兜底的存储层 |
| `report_generator.py` | 本地报告生成辅助 |
| `update_cache.py` | 本地手动更新 `stock_metrics.csv`，不要页面启动时调用 |
| `stock_metrics.csv` | 云端部署默认读取的数据缓存 |
| `requirements.txt` | Streamlit Cloud 依赖 |
| `README.md` | 本地运行和部署说明 |
| `supabase_schema.sql` | Supabase 建表 / 补字段 SQL |
| `CLAUDE.md` | 项目长期协作规则 |

`app.py` 和 `agent.py` 不要直接操作 Supabase，必须通过 `storage.py`。

---

## 5. 当前核心功能

### 5.1 一键智能体检

主按钮是“一键智能体检”。点击后调用：

```python
run_family_risk_agent(...)
```

结果保存到：

```python
st.session_state["agent_result"]
```

页面 rerun 时不要重复调用 DeepSeek。只有用户再次点击“一键智能体检”或切换报告模式时，才重新生成报告。

### 5.2 DeepSeek 主报告

主报告由 `ai_report.generate_agent_report(agent_context, mode="爸妈版")` 生成。

要求：

- 优先调用 DeepSeek。
- DeepSeek 失败时才走本地兜底。
- 返回 `report_source`：`deepseek` 或 `local_fallback`。
- 不编造缺失数据。
- 不预测涨跌。
- 不给交易动作。

### 5.3 AI 追问

快捷追问和自定义追问都必须统一调用：

```python
answer_followup_question(agent_context, question)
```

返回格式：

```python
{
  "answer": "...",
  "source": "deepseek" 或 "local_fallback",
  "error": ""
}
```

主报告和追问必须共用 `ai_report.py` 中同一个底层 DeepSeek 调用函数：

```python
_call_deepseek(...)
```

不要给主报告和追问各写一套 DeepSeek 调用逻辑。

### 5.4 爸妈版报告与饭桌表达

当前决策：饭桌表达不再单独作为页面模块展示，而是合并进“爸妈版报告”。

实现方向：

- DeepSeek 仍然同一次请求生成正式报告和短口语句。
- `ai_report.py` 把短句合并进爸妈版正文。
- 爸妈版报告里使用类似：

```text
【给爸妈一句话】
这次看下来……要不要我们一起再看看？
```

- `app.py` 不再单独显示“今晚可以这样跟爸妈说”卡片。
- 不要额外增加 DeepSeek 调用次数。
- 简洁版、详细版不强制展示饭桌短句。

### 5.5 家庭观察记录

家庭观察记录用于后续家庭分歧检测。必须保存结构化字段，不要让 AI 猜。

字段：

- `member`
- `comment_type`
- `focus`
- `stance`
- `content`
- `run_id`
- `created_at`

`stance` 取值：

- `conservative`：偏谨慎
- `aggressive`：偏进取
- `neutral`：中性 / 只是记录

`focus` 取值：

- `cash`：现金比例
- `concentration`：持仓集中
- `valuation`：PE/PB 估值
- `financial`：财务数据
- `data_missing`：数据缺失
- `risk_tolerance`：风险承受
- `other`：其他

Supabase 不可用时回退到 `family_comments.csv`。

### 5.6 家庭分歧检测

函数位置：

```python
analyzer.detect_family_disagreement(comments)
```

逻辑：

- 按 `focus` 分组。
- 排除 `stance = neutral`。
- 同一 `focus` 下同时出现 `conservative` 和 `aggressive`，且来自不同 `member`，判定为冲突。
- 分歧提示只提醒家人先沟通一致，不评判谁对谁错，不给交易建议。

---

## 6. stock_metrics.csv 字段规则

`stock_metrics.csv` 是 Streamlit Cloud 的默认数据缓存。不要随便改字段名。

常见中文字段：

- `代码`
- `名称`
- `最新价`
- `涨跌幅`
- `成交额`
- `市盈率-动态`
- `市净率`
- `换手率`
- `总市值`
- `流通市值`
- `所属行业`
- `量比`
- `振幅`
- `内外盘比例`
- `ROE`
- `净利率`
- `毛利率`
- `营收增长率`
- `净利润增长率`
- `资产负债率`
- `经营现金流/净利润`
- `数据来源`
- `更新时间`

内部标准字段映射：

```text
code = 代码
name = 名称
price = 最新价
pct_change = 涨跌幅
turnover = 成交额
pe = 市盈率-动态
pb = 市净率
turnover_rate = 换手率
market_cap = 总市值
float_market_cap = 流通市值
industry = 所属行业
volume_ratio = 量比
amplitude = 振幅
in_out_ratio = 内外盘比例
roe = ROE
net_margin = 净利率
gross_margin = 毛利率
revenue_growth = 营收增长率
profit_growth = 净利润增长率
debt_ratio = 资产负债率
cashflow_profit_ratio = 经营现金流/净利润
data_source = 数据来源
updated_at = 更新时间
```

如果 PE/PB 缺失，只能说：

```text
估值数据暂缺，本次不评价估值高低。
```

不要说行情数据全部缺失，也不要编造 PE/PB。

---

## 7. Supabase 规则

Secrets 名称固定：

```text
SUPABASE_URL
SUPABASE_KEY
DEEPSEEK_API_KEY
```

不要把任何 Key 写进代码、README、日志、报错信息或页面。

`storage.py` 负责：

- `get_storage_status()`
- `get_family_id()`
- `get_supabase_client()`
- `save_analysis_history()`
- `load_recent_analysis_history()`
- `save_followup_history()`
- `load_recent_followup_history()`
- `save_family_comment()`
- `load_recent_family_comments()`

Supabase 写入失败时：

- 不影响一键智能体检。
- 回退本地 CSV。
- 页面只显示简短中文原因。
- 不显示英文大段 traceback。
- 不显示密钥。

如果要改 Supabase 表结构，只能更新 `supabase_schema.sql`，不要 drop 表，不要清空数据。

---

## 8. Streamlit 页面原则

目标用户是父母，手机端优先。

页面应该：

- 字体清楚
- 按钮明显
- 首屏简洁
- 先给结论，再给原因
- 技术细节默认收起
- 调试信息放入“开发者信息 / 调试详情”
- 普通分析入口默认收起
- 历史记录默认收起

主流程顺序建议：

1. 项目标题
2. 输入区
3. 一键智能体检按钮
4. 智能体检完成状态
5. 家庭观察记录
6. 历史体检记录
7. 开发者信息 / 调试详情

**体检结果页（`app.py` 的 `agent_result_block`）已改为标签结构**（2026-05 重构，原本是 5 个并列折叠，父母不知点哪个）：

- 顶部常驻（不进标签）：完成横条 + 综合评分/风险灯 verdict-card
- `st.tabs(["结论与沟通", "分析详情", "持仓明细"])`
  1. **结论与沟通**：与上次相比预警 → 给家人一句话 → 家庭分歧 → 家庭沟通卡 → 极端情景压力测试 → 历史风险回放（单个折叠）→ 纵向洞察 → Agent 主动判断 → 查看 AI 风险说明 CTA
  2. **分析详情**：数据置信度 / 交叉验证 / Agent 记忆 / 长期画像 / 意图差距 / 任务回看 / 待办 / 风险因子拆解
  3. **持仓明细**：组合指标 + 逐只持仓 + 数据缺失说明

改这个标签结构或其内部顺序，仍属"改页面主流程顺序"，需先向 akon958 说明再动（见 §10）。
AI 风险说明、追问等是独立 view（`active_view`），不在结果页标签内。

不要让技术词出现在主界面，比如：

- `stock_metrics.csv`
- `analyzer.py`
- `ai_report.py`
- `agent_context`
- `analysis_history.csv`
- `realtime_data.py`

这些只能放开发者折叠区。

---

## 9. 重要 session_state 键

不要随便重命名或清空这些键：

```text
agent_result
analysis
stocks
fetch_warnings
followup_answers
followup_version
report_mode
family_comments
family_comment_last_save
last_agent_error
last_followup_error
```

关键原则：

- 一键智能体检结果必须保存到 `st.session_state["agent_result"]`。
- 页面 rerun 后不能丢结果。
- 展开 / 收起折叠区不能重复调用 DeepSeek。
- 只有用户主动点击按钮或切换报告模式时，才重新生成 AI 报告。

---

## 10. 改代码前的协作规则

改代码前必须先看实际文件内容，不要凭记忆写。

不要做：

- 大规模重构
- 顺手新增复杂功能
- 删除已有功能
- 修改 `stock_metrics.csv`
- 修改 `update_cache.py`
- 重新爬取全市场数据
- 改 DeepSeek Key 读取方式
- 在 `app.py` / `agent.py` 里直接写 Supabase 逻辑
- 新增登录系统
- 新增自动交易功能

除非用户明确要求，否则不要改：

- 函数签名
- Supabase 表结构
- CSV 字段结构
- DeepSeek 主调用链
- 评分规则
- 页面主流程顺序

如果确实需要改，先说明：

```text
我打算改 X，原因是 Y，会影响 Z。可以吗？
```

---

## 11. 每次修改后的检查

每次修改后至少运行：

```powershell
python -m py_compile app.py agent.py ai_report.py analyzer.py data_fetcher.py storage.py report_generator.py
```

如果本机没有 `python` 命令，可以使用 Codex 自带 Python：

```powershell
& "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m py_compile app.py agent.py ai_report.py analyzer.py data_fetcher.py storage.py report_generator.py
```

如果以下文件存在，也一起检查：

```powershell
python -m py_compile config.py question_router.py validator.py evolution.py realtime_data.py stress_test.py
```

如果改了 AI 调用链，额外检查：

1. 主报告是否仍能调用 DeepSeek。
2. AI 追问是否仍能调用 DeepSeek。
3. 失败时是否正确显示 `local_fallback` 和中文原因。
4. 是否没有重复调用 DeepSeek。
5. 是否没有交易建议和涨跌预测。

如果改了 Supabase 存储，额外检查：

1. 云端保存是否成功。
2. 本地 CSV 兜底是否仍可用。
3. 刷新页面后是否能读取历史。
4. 页面是否显示真实存储方式。
5. 是否没有泄露 Key。

---

## 12. GitHub 上传提醒

常规需要上传：

```text
app.py
agent.py
ai_report.py
analyzer.py
data_fetcher.py
storage.py
report_generator.py
requirements.txt
README.md
stock_metrics.csv
supabase_schema.sql
CLAUDE.md
```

通常不建议上传：

```text
__pycache__/
*.log
streamlit_out.txt
streamlit_run.log
analysis_history.csv
family_comments.csv
failed_codes.csv
stock_metrics_backup.csv
*.zip
```

这些应放入 `.gitignore`。

`stock_metrics.csv` 是部署缓存，通常需要上传；但如果本次没有改数据，就不要为了代码任务重新爬取或覆盖它。

---

## 13. 当前已知重点

当前项目重点：

- 一键智能体检稳定运行
- DeepSeek 主报告稳定生成
- AI 追问真正调用 DeepSeek
- Supabase 历史、追问、家庭观察记录可长期保存
- 家庭分歧检测可用
- 饭桌表达并入爸妈版报告，不单独占页面模块
- 手机端信息层级清晰

当前容易踩坑：

- `CLAUDE.md` 必须是真正 UTF-8 Markdown，不要用 Word 文档另存后改后缀。
- Streamlit Cloud 上看不到本地 CSV 长期保存，长期历史必须靠 Supabase。
- Supabase insert 成功时不一定返回 `response.data`，不要只用 `response.data` 判断失败。
- 如果主报告能调用 DeepSeek、追问却走本地兜底，优先检查是否共用 `_call_deepseek()`。
- 如果页面刷新后回首页，优先检查 `st.session_state["agent_result"]`。
- 如果出现 ImportError，优先检查被 import 文件里是否有 SyntaxError。

---

## Agent skills

### Issue tracker

This repo uses local markdown files under `.scratch/` as the default issue tracker for agent workflows. See `docs/agents/issue-tracker.md`.

### Triage labels

This repo uses the default mattpocock/skills triage labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Treat this repo as a single-context codebase. Read `CLAUDE.md` first for project constraints, then read `CONTEXT.md` and `docs/adr/` if they exist. See `docs/agents/domain.md`.

---

## 14. 最后原则

这个项目不是为了功能越多越好，而是为了：

- 让爸妈看得懂
- 让家庭能沟通
- 让风险能被解释
- 让工具稳定可用

不确定时，先问 akon958，不要硬猜。
