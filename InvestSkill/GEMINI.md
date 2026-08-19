# InvestSkill — Gemini CLI Setup & Usage Guide

This project contains professional investment analysis prompt frameworks for US stock markets. When you run Gemini CLI in this directory, all 25 analysis frameworks are automatically available.

## Installation & Setup

### Quick Start

```bash
# Navigate to the InvestSkill directory
cd /path/to/InvestSkill

# Start Gemini CLI (loads GEMINI.md automatically)
gemini
```

**That's it!** Gemini CLI automatically loads `GEMINI.md` and gives you access to all 25 analysis frameworks in the `prompts/` directory.

### Verify Setup

When you first run `gemini`, you should see context about InvestSkill loaded. Then in the chat:

```
> @prompts/stock-valuation.md AAPL

# This should invoke the stock valuation framework
```

---

## Available Analysis Prompts (25 frameworks + 1 output tool)

### Core Stock Analysis (6 skills)

| Analysis Type               | Prompt File                            | Usage Example                              |
|-----------------------------|----------------------------------------|--------------------------------------------|
| Stock Evaluation            | `@prompts/stock-eval.md`               | `Evaluate AAPL using this framework`      |
| Stock Valuation (DCF+)      | `@prompts/stock-valuation.md`          | `Analyze MSFT using all valuation methods` |
| Fundamental Analysis        | `@prompts/fundamental-analysis.md`     | `Deep dive on NVDA fundamentals`           |
| Technical Analysis          | `@prompts/technical-analysis.md`       | `Analyze TSLA chart patterns`              |
| DCF Valuation               | `@prompts/dcf-valuation.md`            | `Build DCF model for GOOGL`                |
| Economics Analysis          | `@prompts/economics-analysis.md`       | `What's the current economic outlook?`     |

### Financial Report Analysis (3 skills)

| Analysis Type               | Prompt File                            | Usage Example                              |
|-----------------------------|----------------------------------------|--------------------------------------------|
| Financial Report Analyst    | `@prompts/financial-report-analyst.md` | `[paste 10-K] Analyze this filing`        |
| 10-K Report Digest          | `@prompts/10k-digest.md`               | `NVDA FY2024 --lang zh-TW` (EN or 繁中)   |
| Earnings Call Analysis      | `@prompts/earnings-call-analysis.md`   | `[paste transcript] Analyze sentiment`     |

### Market Monitoring (4 skills)

| Analysis Type               | Prompt File                            | Usage Example                              |
|-----------------------------|----------------------------------------|--------------------------------------------|
| Insider Trading             | `@prompts/insider-trading.md`          | `Track insider activity in TSLA`           |
| Institutional Ownership     | `@prompts/institutional-ownership.md`  | `Monitor smart money in META`              |
| Dividend Analysis           | `@prompts/dividend-analysis.md`        | `Is JNJ dividend safe?`                    |
| Short Interest              | `@prompts/short-interest.md`           | `What's the squeeze potential in GME?`     |

### Advanced Analysis (8 skills)

| Analysis Type               | Prompt File                            | Usage Example                              |
|-----------------------------|----------------------------------------|--------------------------------------------|
| Competitor Analysis         | `@prompts/competitor-analysis.md`      | `Analyze AAPL's competitive moat`          |
| Industry Map                | `@prompts/industry-map.md`             | `Map the AI compute supply chain`          |
| Options Analysis            | `@prompts/options-analysis.md`         | `Find earnings play setups in NVDA`        |
| Portfolio Review            | `@prompts/portfolio-review.md`         | `[paste holdings] Review my allocation`    |
| Sector Analysis             | `@prompts/sector-analysis.md`          | `What sectors should rotate into?`         |
| Stock Screener              | `@prompts/stock-screener.md`           | `Rank NVDA, AMD, AVGO across all factors`  |
| Catalyst Calendar           | `@prompts/catalyst-calendar.md`        | `What catalysts are coming for TSLA?`      |
| Bear Case                   | `@prompts/bear-case.md`                | `Build the bear case against TSLA`         |

### Full Research Bundle (2 skills)

| Analysis Type               | Prompt File                            | Usage Example                              |
|-----------------------------|----------------------------------------|--------------------------------------------|
| Research Bundle             | `@prompts/research-bundle.md`          | `Complete analysis on AAPL`                |
| Full Report (HTML)          | `@prompts/full-report.md`              | `Generate full interactive report for NVDA`|

### Meta-Analysis & Visualization (3 skills)

| Analysis Type               | Prompt File                            | Usage Example                              |
|-----------------------------|----------------------------------------|--------------------------------------------|
| Result Validator            | `@prompts/result-validator.md`         | `[paste analysis] Score confidence`        |
| Chart Master                | `@prompts/chart-master.md`             | `[paste data] Generate revenue chart`      |
| Report Generator            | `@prompts/report-generator.md`         | `[paste analysis] Export as HTML report`   |

---

## Usage Examples

### Basic Single Analysis

```
# Stock evaluation
> @prompts/stock-eval.md Evaluate Apple with Piotroski scoring

# Fundamental analysis
> @prompts/fundamental-analysis.md Deep analysis of Microsoft's financials

# Technical analysis
> @prompts/technical-analysis.md What are the key chart levels for Tesla?

# Economics
> @prompts/economics-analysis.md Is a recession likely in the next 12 months?
```

### Financial Data & Filings

```
# Paste and analyze a 10-K for investment signals
> @prompts/financial-report-analyst.md
[paste 10-K text here]
Extract key accounting red flags and management quality indicators

# Generate a structured 10-K digest document (English or Traditional Chinese)
> @prompts/10k-digest.md
AAPL FY2024 --lang zh-TW --output aapl-10k-digest.md

# Analyze earnings call transcript
> @prompts/earnings-call-analysis.md
[paste earnings call transcript]
What's the management tone and guidance outlook?

# Upload or paste financial statements
> @prompts/fundamental-analysis.md
[paste balance sheet and income statement]
Analyze debt levels and cash flow quality
```

### Stock Comparison & Multiple Analyses

```
# Compare two stocks
> @prompts/stock-valuation.md Compare AAPL vs MSFT valuations

# Multiple frameworks on one stock
> I need:
> 1. @prompts/stock-eval.md for NVDA
> 2. @prompts/technical-analysis.md for NVDA
> 3. @prompts/institutional-ownership.md for NVDA

# Portfolio review
> @prompts/portfolio-review.md Here's my holdings:
AAPL: 30%
MSFT: 25%
NVDA: 20%
JNJ: 15%
TSLA: 10%
> Is my allocation optimal?
```

### Specialized Analysis

```
# Is this dividend safe?
> @prompts/dividend-analysis.md JNJ dividend analysis

# Short squeeze potential
> @prompts/short-interest.md Is GME a short squeeze candidate?

# Bear case / counterevidence
> @prompts/bear-case.md Argue why TSLA is a bad hold and give a downside target

# Options strategy selection
> @prompts/options-analysis.md Find bullish option setups for AAPL earnings

# Competitive advantage
> @prompts/competitor-analysis.md Does Microsoft have a defensible moat in cloud?

# Insider trading signals
> @prompts/insider-trading.md What are insiders buying at TSLA?

# Smart money tracking
> @prompts/institutional-ownership.md Which institutional investors are buying tech stocks?
```

### Export as Professional HTML Report

```
# After any analysis, export to a styled HTML/PDF report
> @prompts/report-generator.md
[paste analysis output]
Generate an HTML report for AAPL

# Specify report type
> @prompts/report-generator.md
[paste fundamental-analysis output]
Executive summary report, HTML format

# Full research bundle → HTML report
> @prompts/research-bundle.md Complete analysis on NVDA
> @prompts/report-generator.md Convert the above into a professional HTML report
```

### Full Research Bundle (Most Complete)

```
# Single command for comprehensive analysis
> @prompts/research-bundle.md Provide complete analysis on Apple (AAPL)

# Quick version (key metrics only)
> @prompts/research-bundle.md Quick analysis of Microsoft

# Comparison mode (multiple stocks)
> @prompts/research-bundle.md Compare AAPL, MSFT, and GOOGL
```

---

## Output Format & Standards

Every analysis follows this output structure:

### 1. Executive Summary
- Key findings and investment thesis
- Primary bullish or bearish drivers

### 2. Quantitative Analysis
- Specific numbers and metrics
- Year-over-year or period comparisons
- Industry/peer benchmarking

### 3. Qualitative Assessment
- Management quality
- Competitive position
- Market opportunity

### 4. Standardized Signal Block

All analyses end with this format:

```
╔══════════════════════════════════════════════╗
║              INVESTMENT SIGNAL               ║
╠══════════════════════════════════════════════╣
║ Signal:      BULLISH / NEUTRAL / BEARISH     ║
║ Confidence:  HIGH / MEDIUM / LOW             ║
║ Horizon:     SHORT / MEDIUM / LONG-TERM      ║
║ Score:       X.X / 10                        ║
╠══════════════════════════════════════════════╣
║ Action:      BUY / HOLD / SELL               ║
║ Conviction:  STRONG / MODERATE / WEAK        ║
╚══════════════════════════════════════════════╝
```

### 5. HTML Output Directory Index Rule & Signal Theme Rules (Mandatory)

Whenever generating or updating an HTML report in the `output/` directory:
- The agent **MUST** dynamically update `output/index.html` (by running `node scripts/generate-output-index.js` or `npm run update:index`).
- `output/index.html` serves as an interactive directory listing all generated HTML reports with direct clickable links, exact ground-truth signal text (e.g. `看多 (BULLISH)`, `强烈看多 (STRONG BUY)`), multi-factor score (e.g. `8.5/10`), and continuous green-to-red gradient signal badges.
- **Ground-Truth Signal Preservation**: The index script MUST strictly extract and respect the written verdict text in each HTML report and NEVER override verdict labels based on score thresholds.
- **Report Color Theme Rules**: HTML report CSS themes MUST match their signal: Green/Emerald for Bullish/Strong Buy (`#059669`, `#10B981`), Amber/Orange for Neutral (`#D97706`, `#F59E0B`), and Red/Crimson for Bearish/Strong Sell (`#DC2626`, `#EF4444`).
- **Price Integrity & Zero-Truncation Execution Rule (价格完整性与零截断防错规范)**:
  - **严禁双引号内联 Shell 执行**: 严禁在任何 Shell 命令中使用双引号字符串执行内联 Python/Node 脚本（如 `python3 -c "..."` 或 `node -e "..."`），避免 `$125.00`、`$268.70` 中的 `$125`、`$268` 被 Shell 误当成环境变量展开导致数字被截断为 `.00` 或 `.70`。
  - **强制安全生成方式**: 必须使用独立脚本文件（如 `cat << 'EOF' > ...`）、单引号安全传参或专用工具生成报告。
  - **强制后置自动化扫描与索引健康审查**: 生成后必须自动运行价格完整性扫描，并确保 `node scripts/generate-output-index.js` 输出零 Warning 报警。
- **Mobile Compatibility & Responsive Layout Rule (移动端兼容与响应式排版规范)**:
  - **移动端视口与 Meta 标配**: 所有生成的 HTML 报告必须包含 `<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0, viewport-fit=cover">` 及 `<meta name="format-detection" content="telephone=no">`。
  - **响应式流式布局**: 主容器使用流式最大宽度 (`width: 100%; max-width: 1100px;`)，移动端设置自适应内边距 (`padding: 16px;`)；多列卡片网格在 `@media (max-width: 768px)` 时自动降级为单列或双列，严禁出现固定像素宽度溢出。
  - **表格与图表移动端适配**: 所有宽数据表格必须包裹在横向滚动容器内 (`<div class="table-scroll" style="overflow-x: auto; -webkit-overflow-scrolling: touch;">`)；Chart.js 图表启用自适应渲染 (`responsive: true, maintainAspectRatio: false`)。
  - **自包含与移动端体验**: 样式全部采用内联 `<style>`，避免外部脆弱依赖导致 App 内置浏览器（微信、Safari 等）白屏，正文字号保持 `>= 14px` 确保清晰免缩放阅读。
- **Terminal & Python Non-Blocking Execution & Token Diet Rule (终端防假死与低延迟执行规范)**:
  - **强制最大同步等待时间**: AI agent 在调用终端命令工具（如 `run_command`）时，**必须强制设置 `WaitMsBeforeAsync: 10000` (10,000 ms)**，防止耗时 5-8 秒的数据脚本过早被系统推入后台任务导致界面陷入 `working...` 挂起状态。
  - **强制 Python 无缓冲运行**: 执行 Python 脚本必须显式使用 `python3 -u ...` 或 `PYTHONUNBUFFERED=1`，确保 stdout 输出实时推送到终端与上下文。
  - **数据抓取与本地 Scratch 缓存解耦**: 将耗时网络拉取（如 yfinance、Polymarket API）解耦并将结果缓存至 Scratch 目录 JSON，本地 HTML 报告渲染直接读缓存，实现毫秒级（< 0.2s）极速二次生成。
  - **显式网络超时控制**: 网络爬取脚本中显式配置超时参数（如 `timeout=5`），杜绝因上游财经 API 慢响应引发死等。
  - **终端命令限流与 Token 瘦身**: 终端命令必须使用 `head`、`tail`、`-n` 或 `--silent` 限制输出体量（如 `git log -n 5`），大文件必须通过 `grep_search` 切片读取，严禁将数千行原始日志或超大 JSON 灌入模型上下文，降低 40%+ 推理首字延迟。
- **Mandatory Dividend Disclosure Rule (股息披露规范 - 必须写明股息，无则明确标注“无/没有”)**:
  - 所有个股研报、执行摘要、财务数据卡片与汇总表格中，**必须明确写出股息指标 (Dividend Yield、派息金额、派息率与除息日)**。
  - **若公司不派发股息 (Zero Dividend)**，**必须明确标注为“无 / 没有 (无股息派发 / Dividend: None / N/A)”**，并说明其他股东回报方式（如股票回购 Share Buybacks），严禁遗漏或静默跳过股息字段。
- **Workspace Cleanliness & Zero Intermediate Artifacts Rule (工作区零中间代码与数据污染规范)**:
  - **唯一产物白名单**: 项目工作区内仅允许保存 `output/` 目录下的最终 HTML 分析报告及更新后的 `output/index.html`。
  - **严禁中间代码与缓存数据污染仓库**: 严禁在 `scripts/`、`data/` 或根目录生成临时数据抓取脚本、中间分析脚本、临时 JSON 缓存或报告生成器。所有中间代码与临时数据必须严格写入 Scratch 目录（如 `<appDataDir>/brain/<conversation-id>/scratch/` 或 `/tmp/`）。
  - **即时清理保证**: 运行过程中产生的任何临时文件必须在任务结束前移至 Scratch 目录或彻底清理，确保项目工作区绝对纯净。
- **Mandatory Comprehensive 15-Module Depth by Default (默认强制 15 模块全景全量研报规范)**:
  - 所有个股研报与 HTML 分析产物**必须默认执行全部 15 个全景核心模块 (Comprehensive Depth)**，严禁默认退化为 Quick 或 Standard 模式。
  - **15 模块全景标准清单**：
    1. 执行摘要与投资核心逻辑 (Executive Summary & Thesis)
    2. 多因子量化评分雷达模型 (Multi-Factor Quantitative Scorecard & Radar Chart)
    3. 商业模式、垂直整合与波特五力护城河评级 (Business Model & Porter's 5 Forces)
    4. 核心财务报表与盈利质量深度剖析 (Financial Statements, Margins & Cash Flow Quality)
    5. 杜邦三因子拆解与资本运营效率 (DuPont Analysis: Margin × Turnover × Leverage)
    6. 行业竞争格局与同行全景对标矩阵 (Peer Comparison Matrix with Multiples, Margins, Market Share)
    7. DCF 现金流折现、研发资本化成长模型与多维估值公允中枢 (DCF Valuation: Conservative Floor, Growth & R&D Capitalized DCF, Multiples-Implied Fair Value & Premium Decomposition Bridge)
    8. 技术面量化、均线系统与关键筹码位 (Technical Analysis: SMA20/50/200, RSI, MACD, S/R)
    9. 资本配置、股息政策与股东回报披露 (Capital Allocation & Dividend: explicit "无/没有" if zero dividend)
    10. 现金担保卖出看跌期权 (Cash-Secured Sell Put) 收益增强策略 (Conservative, Moderate, Aggressive 3 Tiers)
    11. 机构持仓与主力资金动向 (Institutional Ownership: Top 13F Holders Table)
    12. 内部人交易、管理层语气与财报电话会洞察 (Insider Trading Form 4 & Earnings Call Tone)
    13. 做空比例、平仓天数与轧空风险评估 (Short Interest, Days to Cover & Options P/C Ratio)
    14. 核心风险矩阵与熊市压力测试 (Risk Matrix & Bear Case Downside Stress Test)
    15. 未来关键催化剂日历与增长路线图 (Catalyst Calendar & Strategic Milestones)
    16. 最终投资评级与执行建议 (Final Verdict & Standardized Signal Block)

---

## Tips for Best Results

### 1. Use File References
```
# Good: explicit file reference
> @prompts/stock-valuation.md Analyze AAPL

# Also works: natural language (Gemini understands the context)
> What's a good valuation for Apple?
```

### 2. Paste Financial Data Directly
```
# Paste balance sheet, income statement, or SEC filings
> @prompts/fundamental-analysis.md
[paste your financial statements]

# Gemini will extract and analyze the data
```

### 3. Combine Multiple Analyses
```
# Run multiple frameworks on the same stock
> First: @prompts/stock-eval.md for NVDA
> Then: @prompts/technical-analysis.md for NVDA
> Finally: @prompts/institutional-ownership.md for NVDA
```

### 4. Provide Context
```
# More specific = better results
> @prompts/dcf-valuation.md
> Stock: MSFT
> Time horizon: 5 years
> Target market growth: 15% CAGR
> Assume WACC of 8.5%
```

### 5. Ask Follow-Up Questions
```
# Gemini remembers the conversation context
> @prompts/stock-valuation.md Value AAPL

# Then follow up:
> What if iPhone sales growth slows to 5%?
> How sensitive is the valuation to margin assumptions?
> What's the downside scenario?
```

---

## Project Structure

```
InvestSkill/
├── prompts/                    # 25 analysis frameworks
│   ├── stock-eval.md
│   ├── stock-valuation.md
│   ├── fundamental-analysis.md
│   ├── technical-analysis.md
│   ├── dcf-valuation.md
│   ├── economics-analysis.md
│   ├── financial-report-analyst.md
│   ├── 10k-digest.md
│   ├── earnings-call-analysis.md
│   ├── insider-trading.md
│   ├── institutional-ownership.md
│   ├── competitor-analysis.md
│   ├── dividend-analysis.md
│   ├── short-interest.md
│   ├── options-analysis.md
│   ├── portfolio-review.md
│   ├── sector-analysis.md
│   ├── bear-case.md
│   ├── research-bundle.md
│   ├── result-validator.md
│   ├── chart-master.md
│   └── report-generator.md     # HTML/PDF report design system
├── plugins/                    # Claude Code plugin (optional)
│   └── us-stock-analysis/
├── GEMINI.md                   # This file
├── README.md
└── CHANGELOG.md
```

---

## Troubleshooting

### Issue: Prompts not loading
```
# Make sure you're in the correct directory
pwd  # should be /path/to/InvestSkill

# Try starting Gemini again
gemini

# Reference the file with full path
@prompts/stock-valuation.md
```

### Issue: Need more detail
```
# Be specific with your request
@prompts/stock-valuation.md Analyze AAPL with:
- 3-year DCF projection
- Comparable company multiples
- Sensitivity analysis
```

### Issue: Want different output format
```
# Ask Gemini to reformat
@prompts/stock-valuation.md Analyze AAPL, then format as:
1. Executive summary (1 paragraph)
2. Key metrics (table)
3. Investment signal
```

---

## Additional Resources

- **README.md** — Complete project overview and all platforms
- **prompts/** directory — All 25 analysis frameworks
- **plugins/** — Claude Code plugin configuration (if using Claude Code)
- **GitHub Issues** — Report bugs or suggest improvements

---

## Disclaimer

All analyses are for educational purposes only and do **not** constitute financial advice. Always consult a qualified financial advisor before making investment decisions. Past performance does not guarantee future results.
