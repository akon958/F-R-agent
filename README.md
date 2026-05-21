# FamilyReader

FamilyReader（家庭持仓读懂器）是一个给父母使用的手机网页工具。它帮助家人读懂持仓风险、现金比例和不同看法，只做家庭投资风险体检和学习参考，不荐股，不预测明天涨跌，不自动交易，也不承诺收益。

## 主要功能

- 输入家庭现金、风险承受能力、多只股票或基金持仓。
- 默认支持 3 行持仓，可以继续增加持仓行。
- 页面默认优先读取 `stock_metrics.csv`，不会在 Streamlit Cloud 每次启动时自动抓全市场行情。
- 可以在“高级选项：数据缓存工具”里手动更新当前持仓数据。
- “更新全部 A 股行情缓存”也放在高级选项里，接口可能失败，失败时页面会继续使用本地缓存。
- 如果本地缓存没有该股票，会显示“数据缺失”，不会强行给绿色评级。
- 输出综合评分、红黄绿风险等级、数据状态、家庭仓位、资产配置饼图、持仓明细、风险提示、家人建议和 txt 报告。
- 可选接入 DeepSeek：只有点击“生成 AI 风险说明”时，才会把基础体检结果改写成更适合父母阅读的话。

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

## 免责声明

本工具仅用于家庭投资风险体检和学习参考，不构成投资建议。市场有风险，投资需谨慎。

本工具不预测明天涨跌，不自动交易，不承诺收益，也不会输出确定性的买卖建议。
