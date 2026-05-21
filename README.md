# FamilyReader

FamilyReader（家庭持仓读懂器）是一个给父母使用的手机网页工具。它帮助家人读懂持仓风险、现金比例和不同看法，只做家庭投资风险体检和学习参考，不荐股，不预测明天涨跌，不自动交易，也不承诺收益。

## 主要功能

**输入**
- 家庭现金、风险承受能力（保守 / 稳健 / 平衡 / 进取 / 积极）、多只股票或基金持仓金额
- 默认 3 行持仓，可动态增加；可补充家庭情况（近半年是否可能用到这笔钱、对波动的反应）

**体检输出（分步展示，手机端无需上下翻页）**
- 综合评分 0–100 + 红黄绿风险等级 + 数据置信度标签（Compliance Guard）
- 风险预警列表（最多 4 条，按重要性排序）
- 家庭分歧提示：同一关注点下不同成员立场不一致时自动标记
- 意图-行动差距镜：家人记录的立场与当前持仓数据对比，发现明显矛盾时提示
- 与上次体检的行为变化对比（有历史记录时显示）

**AI 说明（可选，需配置 DeepSeek API Key）**
- 爸妈版 / 简洁版 / 详细版三种报告模式，随时切换
- AI 追问：点击预设问题或自由输入，AI 基于本次体检数据回答
- 家庭情况补充：可在追问前更新家庭背景，重新生成报告

**家庭观察记录（云端持久化）**
- 向导式三步记录（谁 → 关注什么 → 偏谨慎 / 偏进取 / 中性）
- 记录保存到 Supabase，重新打开页面仍可读取
- 支持多位家庭成员分别记录，供分歧检测使用

**历史对比**
- 保存每次体检的评分、仓位比例、风险因子
- 下次体检时自动对比，显示评分变化和已改善 / 新增风险点
- 行为记忆：检测家人是否响应了上次的风险提示

**数据更新**
- 页面不会自动抓取行情；默认读取 `stock_metrics.csv` 本地缓存
- 可在”高级选项”里手动更新当前持仓数据或全量 A 股缓存
- 数据缺失时保守判断，不会强行给绿色评级

## 重要说明

这个项目不是完整行情软件，也不是投资决策助手。它的目标是帮助家庭读懂风险：

- 行情数据：默认读取 `stock_metrics.csv`。
- 手动更新：本地运行 `python update_cache.py` 或在页面高级选项里点击更新按钮。
- 财务数据：如果缓存里没有完整财务指标，会保守判断，最高不会轻易给绿色。
- 云端部署：Streamlit Cloud 会读取 GitHub 仓库中的 `stock_metrics.csv`。手机端使用时不依赖实时抓取。
- AI 说明：DeepSeek 只负责生成通俗说明，不作为行情数据源，不参与自动交易，也不修改本地缓存。

## 项目结构

```text
FamilyReader/
├── app.py
├── config.py
├── analyzer.py
├── data_fetcher.py
├── ai_report.py
├── report_generator.py
├── update_cache.py
├── stock_metrics.csv
├── requirements.txt
└── README.md
```

## 本地运行

进入项目目录：

```powershell
cd FamilyReader
```

安装依赖：

```powershell
pip install -r requirements.txt
```

启动网页：

```powershell
streamlit run app.py
```

浏览器打开：

```text
http://localhost:8501
```

如果 Windows 上 `pip` 或 `streamlit` 命令不可用，可以使用：

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## 配置 DeepSeek AI 说明

AI 功能是可选的。没有配置密钥时，页面会显示“未配置 AI 分析功能”，基础风险体检仍然可以正常使用。

本地运行时，可以在项目根目录创建 `.streamlit/secrets.toml`，内容如下：

```toml
DEEPSEEK_API_KEY = "你的 DeepSeek API Key"
```

不要把 `.streamlit/secrets.toml` 上传到 GitHub。

## 本地更新 A 股缓存

在上传 GitHub 前，建议先在本地运行一次：

```powershell
python update_cache.py
```

这个脚本会调用 AkShare 的 `stock_zh_a_spot_em()`，把沪深京 A 股行情保存到 `stock_metrics.csv`。缓存字段至少包括：

- 代码
- 名称
- 最新价
- 涨跌幅
- 成交额
- 市盈率-动态
- 市净率
- 换手率
- 总市值
- 流通市值

如果 AkShare 接口失败，脚本会提示：

```text
实时行情更新失败，已使用本地缓存数据。
```

这时页面仍然可以使用已有的 `stock_metrics.csv`，不会崩溃。

## 手机访问本地网页

手机和电脑连接同一个 Wi-Fi。启动 Streamlit 后，终端会显示类似下面的地址：

```text
Network URL: http://192.168.x.x:8501
```

在手机浏览器打开这个 `Network URL` 即可。如果打不开，请检查 Windows 防火墙是否允许 Python 或 Streamlit 访问局域网。

## 部署到 Streamlit Community Cloud

1. 打开 [GitHub](https://github.com/) 并登录。
2. 点击右上角 `+`，选择 `New repository`。
3. Repository name 填：

```text
FamilyReader
```

4. 选择 `Public`，然后点击 `Create repository`。
5. 上传本项目根目录中的文件：

```text
app.py
requirements.txt
analyzer.py
data_fetcher.py
ai_report.py
report_generator.py
update_cache.py
stock_metrics.csv
README.md
```

6. 打开 [Streamlit Community Cloud](https://share.streamlit.io/) 并登录。
7. 点击 `New app`。
8. 选择刚创建的 GitHub 仓库。
9. 部署参数填写：

```text
Repository: 你的用户名/FamilyReader
Branch: main
Main file path: app.py
```

10. 点击 `Deploy`。

### 在 Streamlit Cloud 配置 DeepSeek

如果需要使用“生成 AI 风险说明”按钮，请在 Streamlit Cloud 中配置密钥：

1. 打开你的 Streamlit Cloud 应用。
2. 点击右下角 `Manage app`。
3. 进入 `Settings` 或 `Secrets`。
4. 填入：

```toml
DEEPSEEK_API_KEY = "你的 DeepSeek API Key"
```

5. 保存后点击 `Reboot app` 或等待应用自动重启。

如果不配置这个密钥，应用不会报错，只是 AI 说明按钮会提示“未配置 AI 分析功能”。

## 上传 GitHub 后的数据逻辑

上传 GitHub 后，Streamlit Cloud 会直接读取仓库里的 `stock_metrics.csv`。因此：

- 手机端打开云端链接时，不需要每次实时抓 AkShare。
- 如果想更新缓存，先在本地运行 `python update_cache.py`。
- 然后把更新后的 `stock_metrics.csv` 再上传或提交到 GitHub。
- Streamlit Cloud 重新部署后，就会读取新的缓存。

## 系统架构

本项目采用多 Agent 协作架构，各 Agent 职责明确、顺序调用：

```text
用户输入（持仓 + 风险偏好）
         ↓
   Data Agent        — 读取本地缓存，标准化字段，标记数据缺失
         ↓
   Risk Agent        — 四维评分（仓位安全 / 财务质量 / 交易热度 / 风险匹配）
         ↓
Compliance Guard     — 检查评分依据，数据不足时自动降级，过滤不合规措辞
         ↓
Family Translator    — DeepSeek 将体检结论改写为爸妈版 / 简洁版 / 详细版
         ↓
Disagreement Detector — 对比多位家庭成员的立场记录，检测分歧与意图-行动差距
         ↓
     输出层          — 风险等级 + AI 说明 + 分歧提示 + 历史对比 + 追问
```

当前五个 Agent 为顺序调用；未来展望一节描述了演化为真正多智能体协作的方向。

## 设计理念

本项目坚持**反预测**原则：AI 不替家庭做决定，而是帮家庭做出经过深思的决定。

市面上大多数 AI 工具在卷"预测得多准"。本项目从立项起就主动放弃预测和荐股，原因不是技术限制，而是一个判断：**家庭投资最大的风险往往不是选错股票，而是家人之间从没把钱的问题聊清楚过**。因此，本工具的全部设计都围绕"解释"和"沟通"，而非"决策"和"操作"。

## 未来展望

本项目目前是单次体检 + 持续记忆的模式。未来可扩展方向包括：

1. **Long-running Agent**：定期主动观察，仅在风险发生明显变化时主动推送给家庭，从被动工具演化为陪伴型 Agent。
2. **Agent 间相互质询**：Risk Agent 给出结论后，Compliance Guard 主动追问"数据支撑是否充分"，Family Translator 翻译后 Disagreement Detector 检查"这话会不会让某个家庭成员觉得被针对"。
3. **家庭金融共识工具**：把"意图-行动差距镜"做成完整闭环，每季度自动生成家庭金融会议议程，记录分歧是否已解决。
4. **多代际翻译层**：在爸妈版之外增加祖辈版（更口语、用生活类比）和青少年版（用家里真实持仓做金融教育素材）。
5. **记忆层级化**：从当前的"事实记忆"（Supabase 历史数据），演化出"偏好记忆"（这家人怎么做决策）和"情绪记忆"（上次大跌时全家怎么反应），让 Agent 真正"懂这家人"。

## 免责声明

本工具仅用于家庭投资风险体检和学习参考，不构成投资建议。市场有风险，投资需谨慎。

本工具不预测明天涨跌，不自动交易，不承诺收益，也不会输出确定性的买卖建议。
