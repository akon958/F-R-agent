# Family_Investment_Agent

家庭投资雷达 Agent 是一个给父母使用的手机网页工具。  
只做家庭投资风险体检和学习参考，**不荐股，不预测涨跌，不给买卖建议，不自动交易，不承诺收益。**

---

## 数据更新流程（重要，请先读这里）

本项目采用"**本地更新数据 → 上传 GitHub → 手机端读取缓存**"的模式。

```
本地电脑                        GitHub                   手机 / Streamlit Cloud
─────────────────────          ──────────────────        ───────────────────────
python update_cache.py   →   上传 stock_metrics.csv  →  页面读取缓存，无需联网抓行情
```

### 第一步：在本地电脑更新数据

```bash
python update_cache.py
```

脚本调用 AkShare 的 `stock_zh_a_spot_em()` 接口，抓取全部 A 股实时行情，保存到 `stock_metrics.csv`。

输出示例：
```
✅ 获取到 5300 条行情记录。
✅ stock_metrics.csv 已更新
   股票数量：5312
   更新时间：2025-10-01 09:35:22

下一步：
  1. git add stock_metrics.csv
  2. git commit -m 'update cache'
  3. git push
```

如果 AkShare 接口失败，脚本报错退出，`stock_metrics.csv` 不会被修改。

### 第二步：把 stock_metrics.csv 提交到 GitHub

```bash
git add stock_metrics.csv
git commit -m "update cache $(date +%Y-%m-%d)"
git push
```

### 第三步：Streamlit Cloud 自动读取最新缓存

Streamlit Cloud 重新部署后，手机端打开页面即可读取最新数据，**无需每次实时抓行情**。

---

## 主要功能

- 输入家庭现金、风险承受能力、多只股票或基金持仓。
- 默认支持 3 行持仓，可点击"增加一行持仓"继续添加。
- 页面顶部显示缓存股票数量和数据更新时间。
- **缓存里没有的股票不报错**：允许手动填写名称、行业、资产类型和备注，体检照常进行。
- 输出综合评分、红黄绿风险等级、家庭仓位、资产配置饼图、持仓明细、风险提示和建议。
- 可选接入 DeepSeek AI，点击"生成 AI 风险说明"，AI 用通俗语言解释体检结果。
- AI 只分析缓存数据和用户输入，不编造行情，不荐股，不预测涨跌。

---

## 项目结构

```
Family_Investment_Agent/
├── app.py               # 主页面（Streamlit）
├── analyzer.py          # 风险评分逻辑
├── data_fetcher.py      # 数据读取层（只读缓存，不自动联网）
├── report_generator.py  # txt 报告生成
├── ai_report.py         # DeepSeek AI 风险说明（可选）
├── update_cache.py      # 本地数据更新脚本（只在本地电脑运行）
├── stock_metrics.csv    # 本地行情缓存（由 update_cache.py 生成）
├── requirements.txt
└── README.md
```

---

## 本地运行

### 安装依赖

```bash
pip install -r requirements.txt
```

### 更新数据缓存

```bash
python update_cache.py
```

### 启动页面

```bash
streamlit run app.py
```

浏览器打开 `http://localhost:8501`

Windows 下如果命令不可用：
```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

### 手机访问本地页面

手机和电脑连接同一 Wi-Fi，启动后终端会显示：
```
Network URL: http://192.168.x.x:8501
```
手机浏览器打开这个地址即可。如果打不开，请检查 Windows 防火墙是否允许 Python 访问局域网。

---

## 部署到 Streamlit Community Cloud

1. 在 GitHub 创建公开仓库，上传以下文件：
   ```
   app.py  analyzer.py  data_fetcher.py  report_generator.py
   ai_report.py  update_cache.py  stock_metrics.csv  requirements.txt  README.md
   ```
2. 打开 [share.streamlit.io](https://share.streamlit.io)，点击 `New app`。
3. 选择仓库，Main file path 填 `app.py`，点击 `Deploy`。

---

## AI 风险说明功能（可选）

本工具支持接入 DeepSeek API，点击"生成 AI 风险说明"后，AI 用通俗语言解释体检结果给父母看。

**AI 硬性原则：**
- 不荐股，不提任何股票的投资价值
- 不预测涨跌
- 不给买入、卖出、加仓、减仓指令
- 只根据缓存数据和用户输入分析，不编造行情
- 结尾必须附免责声明

### 在 Streamlit Cloud 配置 DEEPSEEK_API_KEY

1. 应用管理页 → **⋮ → Settings → Secrets**
2. 填入：
   ```toml
   DEEPSEEK_API_KEY = "sk-你的Key"
   ```
3. 点击 **Save**，应用自动重启。

未配置 Key 时，页面显示"未配置 AI 分析功能"，其他体检功能完全正常。

### 本地配置 AI Key

在项目根目录创建 `.streamlit/secrets.toml`（**不要提交到 GitHub**）：
```toml
DEEPSEEK_API_KEY = "sk-你的Key"
```

DeepSeek API Key 在 [platform.deepseek.com](https://platform.deepseek.com/) 注册后获取。

---

## stock_metrics.csv 字段说明

| 字段 | 说明 |
|---|---|
| 代码 | 6 位股票代码 |
| 名称 | 股票简称 |
| 最新价 | 当日最新成交价（元） |
| 涨跌幅 | 当日涨跌幅（%） |
| 成交额 | 当日成交额（元） |
| 换手率 | 当日换手率（%） |
| 市盈率-动态 | 动态市盈率（PE） |
| 市净率 | 市净率（PB） |
| 总市值 | 总市值（元） |
| 流通市值 | 流通市值（元） |
| 量比 | 当日量比 |
| 振幅 | 当日振幅（%） |
| 所属行业 | 申万一级行业（如能抓到） |
| 更新时间 | 本条数据的更新时间戳 |

---

## 免责声明

本工具仅用于家庭投资风险体检和学习参考，不构成投资建议。市场有风险，投资需谨慎。  
本工具不预测明天涨跌，不自动交易，不承诺收益，也不输出任何买卖建议。
