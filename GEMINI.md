# The Sell Put King & InvestSkill — Unified Gemini CLI System Guide

This workspace combines **The Sell Put King** (Quantitative Options Strategy & Robinhood Portfolio Governance) and **InvestSkill** (25 Institutional Equity Research Frameworks). When you run Gemini CLI in this root directory, all quantitative options models and all 25 equity research frameworks are automatically available.

---

## 1. Quick Start & Command Triggers

### 🎯 Option & Stock Research Workflows
| User Command | Action & Pipeline | Deliverable |
|:---|:---|:---|
| `<TICKER>` or `research <TICKER>` | **Single-Ticker Deep Research**: Generate 15-module institutional report for `<TICKER>` (e.g., `NVDA`, `AAPL`, `分析 TSLA`, `MSFT 研报`) | `InvestSkill/output/{TICKER}_report_{DATE}.html` + embedded into `report.html` Tab 2 |
| `research` | **Full Master Pipeline**: Fetch Robinhood positions, scan targets, score Sell Put & Covered Call candidates, batch verify/generate 15-module reports, sync watchlist | `report.html` & Mobile Watchlist |
| `sync` | Synchronize InvestSkill reports and re-render dashboard | `python3 scripts/sync_investskill.py` |
| `commit` | **Precision Commit & Push**: Explicitly stage modified/new files, commit with semantic message, and immediately execute `git push` | GitHub Remote Sync |

### 🔍 InvestSkill Prompt Frameworks (25 Frameworks + 1 Output Tool)
You can directly invoke any prompt framework using `@InvestSkill/prompts/<name>.md` or `@prompts/<name>.md`:

```
> NVDA                                    # Direct ticker triggers full 15-module research report
> research AAPL                           # Explicit research command
> @InvestSkill/prompts/full-report.md NVDA # Full report framework
> @prompts/stock-valuation.md AAPL         # Valuation framework
> @prompts/dcf-valuation.md MSFT           # DCF framework
> @prompts/bear-case.md TSLA               # Bear case stress test
```

---

## 2. Available InvestSkill Analysis Frameworks

### 📊 Core Stock Analysis (6 Skills)
| Analysis Type | Prompt File | Usage Example |
|:---|:---|:---|
| Stock Evaluation | `@InvestSkill/prompts/stock-eval.md` | `Evaluate AAPL with Piotroski F-score` |
| Stock Valuation (DCF+) | `@InvestSkill/prompts/stock-valuation.md` | `Analyze MSFT using multi-method valuation` |
| Fundamental Analysis | `@InvestSkill/prompts/fundamental-analysis.md` | `Deep dive into NVDA financial health & margins` |
| Technical Analysis | `@InvestSkill/prompts/technical-analysis.md` | `Analyze TSLA chart levels & moving averages` |
| DCF Valuation | `@InvestSkill/prompts/dcf-valuation.md` | `Build 5-year DCF model for GOOGL` |
| Economics Analysis | `@InvestSkill/prompts/economics-analysis.md` | `Current macroeconomic outlook & yield curve` |

### 📑 Financial Report Analysis (3 Skills)
| Analysis Type | Prompt File | Usage Example |
|:---|:---|:---|
| Financial Report Analyst | `@InvestSkill/prompts/financial-report-analyst.md` | `[paste 10-K/10-Q] Extract accounting red flags` |
| 10-K Report Digest | `@InvestSkill/prompts/10k-digest.md` | `NVDA FY2024 --lang zh-TW` (EN / 繁中) |
| Earnings Call Analysis | `@InvestSkill/prompts/earnings-call-analysis.md` | `[paste transcript] Management tone & outlook` |

### 📡 Market Monitoring (4 Skills)
| Analysis Type | Prompt File | Usage Example |
|:---|:---|:---|
| Insider Trading | `@InvestSkill/prompts/insider-trading.md` | `Track SEC Form 4 insider buying/selling in TSLA` |
| Institutional Ownership | `@InvestSkill/prompts/institutional-ownership.md` | `Track 13F smart money & top institutional holders` |
| Dividend Analysis | `@InvestSkill/prompts/dividend-analysis.md` | `Is JNJ dividend safe? Yield trap evaluation` |
| Short Interest | `@InvestSkill/prompts/short-interest.md` | `Short squeeze potential & days to cover in GME` |

### 🔬 Advanced Strategic Analysis (8 Skills)
| Analysis Type | Prompt File | Usage Example |
|:---|:---|:---|
| Competitor Analysis | `@InvestSkill/prompts/competitor-analysis.md` | `Analyze AAPL's economic moat & Porter's 5 Forces` |
| Industry Map | `@InvestSkill/prompts/industry-map.md` | `Map the AI semiconductor supply chain & value pools` |
| Options Analysis | `@InvestSkill/prompts/options-analysis.md` | `Options Greeks, IV Rank & strategic setups` |
| Portfolio Review | `@InvestSkill/prompts/portfolio-review.md` | `[paste holdings] Optimize asset allocation` |
| Sector Analysis | `@InvestSkill/prompts/sector-analysis.md` | `Sector rotation & relative valuation matrix` |
| Stock Screener | `@InvestSkill/prompts/stock-screener.md` | `Rank peer tickers across multi-factor models` |
| Catalyst Calendar | `@InvestSkill/prompts/catalyst-calendar.md` | `90-day upcoming catalysts & earnings dates` |
| Bear Case | `@InvestSkill/prompts/bear-case.md` | `Red-team bear case & downside stress test` |

### 📦 Full Research Bundle & Export (5 Skills)
| Analysis Type | Prompt File | Usage Example |
|:---|:---|:---|
| Full Report (HTML) | `@InvestSkill/prompts/full-report.md` | `Generate comprehensive 15-module HTML report for NVDA` |
| Research Bundle | `@InvestSkill/prompts/research-bundle.md` | `Complete multi-framework stock evaluation` |
| Report Generator | `@InvestSkill/prompts/report-generator.md` | `[paste analysis] Export as styled HTML report` |
| Chart Master | `@InvestSkill/prompts/chart-master.md` | `Generate revenue/margin charts` |
| Result Validator | `@InvestSkill/prompts/result-validator.md` | `Validate analysis logic & score confidence` |

---

## 3. Mandatory 15-Module Institutional Standard & Quality-Conditioned Scoring

Whenever executing `research <TICKER>` or `@InvestSkill/prompts/full-report.md`, strictly generate all 15 modules adhering to the **Quality-Conditioned Multi-Factor Architecture** (preventing momentum trap on tops and falling knife trap on distressed assets):

1. **执行摘要与核心投资逻辑 (Executive Summary & Thesis)**
2. **多因子量化评分雷达模型 (Multi-Factor Scorecard & Radar Chart)**:
   - **商业质量与护城河 (25%)**: 护城河深度、ROIC/ROE、FCF Margin、特许经营与轻资产指标。
   - **估值与双层安全垫 (25%)**: DCF 内在价值折现 + 历史倍数百分位 + Sell Put 净持仓成本折价。
   - **市场资金与机构动向 (20%)**: 13F 机构增减持、SEC Form 4 内部人态度、财报电话会前瞻。
   - **自适应技术与周期位置 (15%)**: 质量条件调制引擎（高质量宽护城河资产在 52 周底部 RP<0.20 判定为**左侧黄金坑 8.0-9.5 分**；劣质资产破位下行严惩为**毒飞刀 0.0-3.5 分**）。
   - **风险与非对称赔率 (15%)**: 偿债安全度、IV 时间价值下行吸收率、做空比例与轧空弹性。
3. **商业模式、垂直整合与波特五力护城河评级 (Business Model & Porter's 5 Forces)**
4. **核心财务报表与盈利质量深度剖析 (Financial Statements, Margins & Cash Flow Quality)**
5. **杜邦三因子拆解与资本运营效率 (DuPont Analysis: Margin × Turnover × Leverage)**
6. **行业竞争格局与同行全景对标矩阵 (Peer Comparison Matrix with Multiples, Margins, Market Share)**
7. **DCF 现金流折现与内在价值三情景敏感性模型 (DCF Valuation: Bear/Base/Bull & WACC Sensitivity)**
8. **技术面量化、均线系统与关键筹码位 (Technical Analysis: SMA20/50/200, RSI, MACD, S/R)**
9. **资本配置、股息政策与股东回报披露 (Capital Allocation & Dividend: explicit "无/没有" if zero dividend)**
10. **现金担保卖出看跌期权 (Cash-Secured Sell Put) 收益增强策略 (Conservative, Moderate, Aggressive 3 Tiers)**
11. **机构持仓与主力资金动向 (Institutional Ownership: Top 13F Holders Table)**
12. **内部人交易、管理层语气与财报电话会洞察 (Insider Trading Form 4 & Earnings Call Tone)**
13. **做空比例、平仓天数与轧空风险评估 (Short Interest, Days to Cover & Options P/C Ratio)**
14. **核心风险矩阵与熊市压力测试 (Risk Matrix & Bear Case Downside Stress Test)**
15. **未来关键催化剂日历与增长路线图 (Catalyst Calendar & Strategic Milestones)**
16. **最终投资评级与执行建议 (Final Verdict & Standardized Signal Block)**

---

## 4. Report Output & Dynamic Index Protocol

1. **File Destination**: Save all generated reports to `InvestSkill/output/{TICKER}_report_{YYYY-MM-DD}.html`.
2. **Index Dynamic Update**: Immediately run:
   ```bash
   node InvestSkill/scripts/generate-output-index.js
   ```
3. **Dashboard Sync**: Re-render master options dashboard:
   ```bash
   python3 scripts/generate_report.py
   ```
4. **Color Themes**:
   - **Bullish (看多 / BUY / STRONG BUY)**: Green / Emerald (`#059669`, `#10B981`)
   - **Neutral (中立 / HOLD)**: Amber / Gold (`#D97706`, `#F59E0B`)
   - **Bearish (看空 / SELL / STRONG SELL)**: Red / Crimson (`#DC2626`, `#EF4444`)
5. **Dividend Disclosure**: Must explicitly state dividend status. If zero dividend, write `"无 / 没有 (无股息派发 / Dividend: None / N/A)"`.
6. **Mobile Layout**: Enclose tables in `.table-scroll`, set viewport meta, and ensure responsive fluid charts.
7. **Title Conciseness & Minimalist Professional Language Style (报告标题精炼与极简专业语言风格规范)**:
   - **Zero Boilerplate Titles (严禁模板化废话标题)**: Strictly prohibit long, redundant boilerplate in `<title>` and `<h1>` (e.g. NEVER use "15模块全景深度投研与多因子量化评估", "全模块深度研究与多因子量化评估报告", "深度投资研究与多因子评估报告").
   - **Standardized Concise Title Format**: Use `{Company} ({TICKER}) 深度投研报告 - InvestSkill` for `<title>` and `{Company} ({TICKER}) 深度投研报告` for `<h1>`.
   - **Concise & Direct Institutional Tone (极简、专业、客观、零废话风格)**: Language style must be clean, rigorous, data-dense, and professional. Eliminate conversational filler, redundant padding, and verbose rhetorical phrases.
8. **Auto Commit & Push on InvestSkill Output (研报输出自动提交与推送规范)**:
   - 凡是仅涉及 `InvestSkill/output/` 目录内的文件变更（新增/更新研报 HTML 或重新生成 `index.html`），且工作区无其他代码文件变动时，AI Agent **无需等待用户手动输入 `commit`，直接自动执行 `git add InvestSkill/output/`、精准语义 Commit 并立即执行 `git push`** 同步至远程仓库。


