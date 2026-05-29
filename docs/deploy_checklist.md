# 部署上传清单（FamilyReader）

> 本地目录不是 git 仓库时，按**文件清单**用 GitHub 网页上传；有 clone 时用末尾的 git 命令。
> 部署目标：push 到 GitHub → Streamlit Cloud 自动重新部署。

最后更新：2026-05-29

### 变更记录
- 深化 agent：压力测试 / 家庭沟通卡 / 纵向洞察 / 历史回放四模块
- 结果页三标签重构 + 信息精简（分歧并入沟通卡、delta 非预警下沉、风险因子只显需关注）
- PWA 化（manifest + 图标 + head 注入），真机实测可"添加到主屏幕"
- 代码健康：抽 scenario_common 共享 util、validator.sanitize_structured 统一禁词兜底、合并情景卡渲染器
- 文案精简：4 模块 + scenario_common + app.py 结果页/输入页的父母面向文案逐句收紧
  （固定免责声明、合规措辞、测试钉死串全部保留）
- 修复：test_industry 的 unittest discover 报错；cross_validate 归因措辞

---

## 1. 必须上传/更新

### 🆕 新增模块（漏传则对应功能在云端**静默消失**，不会报错）
```
stress_test.py          极端情景压力测试
history_replay.py       历史风险回放
family_dialogue.py      家庭沟通卡
longitudinal_story.py   纵向洞察
scenario_common.py      上面 stress/replay 的共享工具，最容易漏
```

### ✏️ 改动的核心文件
```
agent.py        接入 4 模块 + sanitize_structured 兜底过滤
app.py          结果页三标签重构 + 各卡片 + 精简 + PWA 注入
validator.py    新增 sanitize_structured（结构化文案统一禁词过滤）
CLAUDE.md        §8 标签结构 / §3 PWA / §12 上传清单
```

### 📱 PWA 资产（必须成套，否则主屏无图标 / manifest 404）
```
.streamlit/config.toml      开启 enableStaticServing + 暖色主题
static/manifest.json
static/icon-192.png
static/icon-512.png
static/apple-touch-icon.png
```

### 🧪 测试（建议一起，保持可跑）
```
tests/test_stress_test.py
tests/test_family_dialogue.py
tests/test_longitudinal_story.py
tests/test_history_replay.py
tests/test_industry.py       已改为 main() 守卫，修了 unittest discover 报错
```

### 可选
```
scripts/generate_pwa_icons.py   不影响运行，留着方便重新生成图标
```

---

## 2. 不需要动
- `requirements.txt`：未加运行时依赖（Pillow 只本地生成图标用，云端不需要）。
- `stock_metrics.csv`：未改数据，不要为代码任务重新覆盖。
- Streamlit Secrets：未动任何 key。
- `config.py` / `analyzer.py` / `storage.py` / `ai_report.py`：本轮未改。
- `Family_Investment_Agent_code_display/`：保留，与主部署无关。

---

## 3. git 命令（有本地 clone 时）
```bash
git add stress_test.py history_replay.py family_dialogue.py longitudinal_story.py scenario_common.py \
        agent.py app.py validator.py CLAUDE.md \
        .streamlit/config.toml static/manifest.json static/icon-192.png static/icon-512.png static/apple-touch-icon.png \
        scripts/generate_pwa_icons.py tests/
git commit -m "深化agent(压力测试/沟通卡/纵向洞察/历史回放)+三标签重构+精简+PWA+代码健康"
git push
```

---

## 4. 部署后手机自查
1. 三标签（结论与沟通 / 分析详情 / 持仓明细）出现；做一次体检不报错；压力测试卡正常。
2. 浏览器"添加到主屏幕" → 有 FamilyReader 图标、点开全屏 standalone。
3. ≥2 次历史 → 纵向洞察卡出现；家人填了对立观察 → 家庭沟通卡出现。

> 注意：agent.py / app.py 用 `try/except ImportError` 兜底导入新模块。
> 只传 agent.py 却漏传某个模块时**不报错但卡片静默不出现**。务必按第 4 步第 1 项确认卡片真的出来了。
