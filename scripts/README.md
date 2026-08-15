# The Sell Put King Strategy Research Scripts

本目录包含期权 Sell Put & Covered Call 策略研报与数据同步的核心 Python 调度与 CLI 脚本。底层核心算法与模型由 `src/option_quant` 包驱动。

## 📁 核心脚本分类与用途说明

### 1. 🚀 研报总调度与主入口
- **`run_research.py`**：研报总调度器，一键触发全套研报编译与 HTML 渲染生成（对应 `the-sell-put-king run`）。
- **`generate_report.py`**：多因子打分引擎、InvestSkill 研报索引融合与 HTML 看板生成器。

### 2. 🔄 数据 ETL 与缓存管线
- **`sync_data.py`**：提取 Robinhood 实时资产、现货持仓与未平仓期权数据，写入 `data/account_info.json` 与 `data/current_positions.json`。
- **`get_scan_targets.py`**：全市场扫描极低估/超跌长牛与高波标的，判定 DTE 15-60 天目标到期日，输出至 `data/scan_targets.json`。
- **`filter_instruments.py`**：按照估值位置与 Delta 动态区间（0.10~0.30/0.40）精细筛选合理的 CSP / CC 候选合约，写入 `data/filtered_instruments.json`。
- **`get_quote_batches.py`**：将筛选出的候选合约 ID 切分为 Max 40 个/批的小批次（防 API 静默丢包），生成 `data/quote_batches.json`。
- **`build_options_cache.py`**：编译完整的本地期权数据库，写入 `data/robinhood_options_cache.json` 供打分引擎使用。
- **`sync_watchlist_mcp.py`**：Robinhood `Sell Put Candidate` 自选股倒序同步器（LIFO 保证排名严格一致）。

### 3. 🛠️ 交互式计算与辅助工具
- **`option_apy_calculator.py`**：期权 APY / 年化收益率计算器（支持 CLI 参数单次计算与交互式控制台循环计算）。
- **`portfolio_delta.py`**：组合 Delta 名义市值敞口与净资产杠杆率监控工具。
- **`insider_sentiment.py`**：SEC Form 4 高管内幕交易排雷与增持奖励分析工具。
- **`sync_investskill.py`**：将 InvestSkill output 深度研报一键索引并刷新至交易看板。
- **`ticker_config.py`**：配置加载与标的代码规范化向后兼容适配器。

---

## 💻 快速运行指引

```bash
# 1. 运行一键全流程策略研报
python3 scripts/run_research.py

# 2. 计算期权 APY
python3 scripts/option_apy_calculator.py 15 100 2.5

# 3. 查看当前组合杠杆率
python3 scripts/portfolio_delta.py
```
