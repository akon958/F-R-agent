# FamilyReader 内部接口设计文档

本文件记录各模块对外暴露的接口契约、数据格式约定和降级策略，供开发和 AI 协作者参考。

---

## 行业分类基础设施

### 概述

为财务质量因子的行业横向对比功能提供稳定的 A 股行业归属数据。

### 分类标准

- **标准**：申万一级行业（Shenwan Level-1 Industry Classification）
- **版本**：2021 年修订版，共 31 个一级行业
- **31 个行业**：农林牧渔、基础化工、钢铁、有色金属、电子、汽车、家用电器、食品饮料、纺织服饰、轻工制造、医药生物、公用事业、交通运输、房地产、商贸零售、社会服务、银行、非银金融、建筑材料、建筑装饰、电力设备、国防军工、计算机、传媒、通信、煤炭、石油石化、环保、美容护理、机械设备、综合

### 数据来源（双源合并，申万优先）

| 优先级 | 来源 | AkShare 接口 | 覆盖范围 | CSV `source` 标记 |
|--------|------|-------------|---------|-----------------|
| 主     | 申万官方成分股 | `ak.sw_index_first_info()` + `ak.index_component_sw(symbol)` | 申万指数收录的全部成分股（约 4500 只） | `sw` |
| 兜底   | 东方财富个股信息 | `ak.stock_individual_info_em(symbol)` 的 `行业` 字段 | 申万未收录股票（新股、北交所等） | `em` |
| 缺失   | —   | —           | 两者均无数据 | `none` |

> **注意**：东方财富行业（`em`）与申万一级**不完全等价**，兜底数据仅作参考。

### 存储格式

文件路径：`industry_map.csv`（仓库根目录，随代码一起提交）

| 列名 | 类型 | 说明 |
|------|------|------|
| `code` | str | 6 位零填充股票代码 |
| `name` | str | 股票简称 |
| `sw_industry` | str / None | 申万一级行业名称，无法确定时为空 |
| `source` | str | 数据来源标记：`sw` / `em` / `none` |
| `last_updated` | str | 生成时间（ISO 8601） |

### 更新流程

```
本地 / GitHub Actions 运行 build_industry_map.py
  ↓
生成 industry_map.csv
  ↓
commit & push 到 GitHub
  ↓
Streamlit Cloud 重新部署，data_fetcher 在首次调用时加载最新 CSV
```

- **更新频率**：季度一次（申万成分股调整通常按季度生效）
- **触发方式**：GitHub Actions（计划中），也可在本地手动运行

### 主接口

**`data_fetcher.get_industry(stock_code: str) -> str | None`**

```python
from data_fetcher import get_industry

industry = get_industry("600519")   # → "食品饮料"
industry = get_industry("999999")   # → None（不存在）
```

- 首次调用时将 CSV 加载到内存，后续调用不再读盘
- 返回 `None` 不抛异常，调用方自行决定降级策略

**`data_fetcher.get_industry_meta() -> dict`**

```python
from data_fetcher import get_industry_meta

meta = get_industry_meta()
# {
#   "total_stocks": 5300,
#   "with_industry": 5100,
#   "last_updated": "2026-05-24T10:00:00"
# }
```

### 失败降级策略

| 场景 | 行为 |
|------|------|
| `industry_map.csv` 不存在 | 打印一次警告，`get_industry()` 始终返回 `None` |
| CSV 读取失败（编码 / 格式错误） | 打印一次警告，`get_industry()` 始终返回 `None` |
| 股票代码不在映射表中 | 静默返回 `None` |

警告只打印一次（通过 `_industry_warn_printed` 标志），不干扰正常运行日志。

### 已知限制

1. **跨界经营公司**：按主营业务归类，副业可能跨行业，存在偏差（如互联网公司涉及金融业务）
2. **申万分类标准会调整**：申万每几年会修订一次行业分类标准，届时需重新生成 `industry_map.csv`
3. **新股延迟收录**：申万正式将新股纳入成分股通常有数周延迟，这段时间兜底为东方财富行业（`source=em`）
4. **北交所覆盖较弱**：申万成分股以主板和创业板为主，北交所股票大多依赖东方财富兜底
5. **`em` 来源不等于申万一级**：东方财富行业分类体系与申万存在差异，兜底数据仅在申万数据缺失时使用，应视为近似值

---

*最后更新：2026-05-24*
