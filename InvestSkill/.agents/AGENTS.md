# InvestSkill Agent Rules

These rules apply to all AI agents (Gemini, Claude Code, Cursor, Copilot, etc.) working in the InvestSkill repository.

## Output Directory Index Rule (Mandatory)

1. **Dynamic HTML Index (`output/index.html`)**:
   - Whenever an AI agent generates, exports, or updates any `.html` report in the `output/` directory (e.g. via `full-report`, `report-generator`, or direct script execution), the agent **MUST dynamically update `output/index.html`**.
   - Update can be performed by running `node scripts/generate-output-index.js` or `npm run update:index`, or by executing equivalent scanning and rendering logic.

2. **Report Link Accessibility**:
   - `output/index.html` acts as the single entry directory for all generated reports.
   - All `.html` reports in `output/` must be listed with direct clickable links (`<a href="./filename.html">`) and metadata (Ticker, Title, Signal & Score, Date, File Size).

3. **Ground-Truth Signal Verdict Preservation Rule (尊重报告原始结论原则)**:
   - Index generator scripts (`generate-output-index.js`) and AI agents **MUST strictly respect and extract the exact investment verdict text from the HTML report** (e.g. `看多 (BULLISH)`, `强烈看多 (STRONG BUY)`, `中立 (NEUTRAL)`, `看空 (BEARISH)`, `强烈看空 (STRONG SELL)`).
   - **NEVER override or alter the report's verdict based on numeric score thresholds**. The HTML report's written verdict is the ground truth.

4. **Index Signal Badge Gradient & Score Display Rule (动态索引信号与分值渐变规范)**:
   - `output/index.html` MUST display both the exact verdict text and the multi-factor score (e.g. `看多 (BULLISH) • 8.5/10`, `强烈看多 (STRONG BUY) • 8.6/10`).
   - Signal badges on `output/index.html` MUST use continuous gradient color styling:
     - **强烈看多 (STRONG BUY / 强烈买入)**: 深翡翠绿发光渐变 (`linear-gradient(135deg, rgba(4,120,87,0.45), rgba(16,185,129,0.3))`, `#34D399` 文字, `#10B981` 边框及发光阴影).
     - **看多 (BULLISH / BUY / 买入)**: 中等青绿色 (`rgba(16,185,129,0.18)`, `#6EE7B7` 文字, `#059669` 边框).
     - **中立 (NEUTRAL / HOLD / 持有)**: 琥珀金黄色 (`rgba(245,158,11,0.2)`, `#FBBF24` 文字, `#D97706` 边框).
     - **看空 (BEARISH / SELL / 卖出)**: 橙红色 (`rgba(239,68,68,0.2)`, `#FCA5A5` 文字, `#DC2626` 边框).
     - **强烈看空 (STRONG SELL / 强烈卖出)**: 深红发光渐变 (`linear-gradient(135deg, rgba(185,28,28,0.45), rgba(239,68,68,0.3))`, `#F87171` 文字, `#EF4444` 边框及红光阴影).

5. **Cash-Secured Sell Put Strategy Inclusion Rule**:
   - Whenever generating stock research, full reports, or valuation reports, the AI agent **MUST include a Cash-Secured Sell Put Strategy breakdown under Investment Thesis & Strategy**.
   - Provide recommended DTE (typically 30–45 days) and 3 specific Strike Price tiers:
     - **Conservative**: Strike placed 5–10% below spot / below recent key support (Delta ~0.20–0.25).
     - **Moderate**: Strike placed near primary support / fair value entry (Delta ~0.30–0.35).
     - **Aggressive**: Strike placed ATM / near spot for active accumulation (Delta ~0.45–0.50).

6. **Report Language Requirement (中文报告规范)**:
   - All generated stock research reports, HTML analysis documents, and summaries **MUST be rendered in Chinese (中文)** unless explicitly requested otherwise by the user.

7. **Report Signal Color Theme Rules (报告信号主题配色规范)**:
   - All generated HTML reports MUST align their internal CSS theme (`:root` `--primary`, `--grad-hero`, accent borders, badges, table highlights) to match their Signal:
     - **Bullish (看多 / BUY / STRONG BUY)**: Primary theme, hero gradient, accent borders, badges, table highlights, and key links **MUST use a Green / Emerald color palette** (e.g., `#059669`, `#10B981`, `#047857`, emerald gradients).
     - **Neutral (中立 / HOLD)**: Primary theme, hero gradient, accent borders, badges, table highlights, and key links **MUST use an Amber / Orange color palette** (e.g., `#D97706`, `#F59E0B`, `#B45309`, amber/orange gradients).
     - **Bearish (看空 / SELL / STRONG SELL)**: Primary theme, hero gradient, accent borders, badges, table highlights, and key links **MUST use a Red / Crimson color palette** (e.g., `#DC2626`, `#EF4444`, `#991B1B`, red gradients).

8. **Price Integrity & Zero-Truncation Execution Rule (价格完整性与零截断防错规范)**:
   - **Strictly Prohibited Command Patterns (严禁双引号内联执行)**: AI agents **MUST NEVER** execute double-quoted inline shell commands containing currency symbols (e.g. `python3 -c "..."` or `node -e "..."` with embedded `$125.00`, `$268.70`). In zsh/bash, `$125` or `$268` is expanded as an empty environment variable, corrupting numbers into `.00` or `.70`.
   - **Mandatory Safe Generation Methods (强制安全文件生成方案)**:
     - Always use dedicated script files created via single-quoted heredoc (`cat << 'EOF' > scripts/build_report.py`), dedicated python modules, or native safe file writing tools (`write_to_file`).
     - Never allow unescaped dollar signs in shell string interpolations.
   - **Mandatory Post-Generation Automated Verification (强制后置自动化价格扫描)**:
     - Immediately after generating or modifying any HTML or Markdown report, the agent **MUST automatically run a price integrity verification script** to scan for truncated price patterns (e.g. `>\s*\.\d{2}`, `Strike\s*\.\d{2}`, `\$\.\d{2}`).
     - Any detected truncation must be fixed immediately before concluding the turn.
   - **Mandatory Output Index Health Check (索引健康度双重审查)**:
     - Run `node scripts/generate-output-index.js` and verify that the console outputs **zero warnings**.

9. **Mobile Compatibility & Responsive Layout Rule (移动端兼容与响应式排版规范)**:
   - **Mandatory Mobile Viewport & Meta Configuration**: Every generated HTML report MUST include `<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0, viewport-fit=cover">` and `<meta name="format-detection" content="telephone=no">`.
   - **Responsive Fluid Layout & Breakpoint Optimization**:
     - Main container must be fluid (`width: 100%; max-width: 1100px;`) with adaptive padding (`padding: 16px;` on mobile vs `padding: 40px 24px;` on desktop).
     - Metric cards, grid blocks, and signal widgets MUST use fluid grid/flex systems (`repeat(auto-fit, minmax(...))` or `@media (max-width: 768px)`) that collapse gracefully to 1 or 2 columns on small screens without horizontal clipping.
   - **Scrollable Data Tables & Flexible Charts**:
     - All data tables MUST be enclosed in `<div class="table-scroll" style="overflow-x: auto; -webkit-overflow-scrolling: touch;">` to prevent wide tables from breaking mobile viewports.
     - Charts (`Chart.js`) MUST be configured with `responsive: true, maintainAspectRatio: false` inside a constrained-height canvas wrapper.
   - **Self-Contained & Mobile WebView Portability**:
     - Keep styles self-contained (inline `<style>`) and avoid brittle external font/icon dependencies that fail in mobile in-app WebViews (e.g. WeChat, Feishu).
     - Ensure text remains legible without zooming (body font size `>= 14px`, `line-height >= 1.5`), and touch targets have sufficient spacing.

10. **Terminal & Python Non-Blocking Execution & Token Diet Rule (终端防假死与低延迟执行规范)**:
    - **Mandatory Maximum Wait Time (强制最大同步等待时间)**: Whenever calling `run_command`, AI agents **MUST set `WaitMsBeforeAsync: 10000` (10,000 ms)** to prevent fast Python/Node scripts from prematurely falling back to background tasks and causing UI "working..." hangs.
    - **Mandatory Unbuffered Execution (强制 Python 无缓冲运行)**: AI agents **MUST ALWAYS** run Python scripts with `-u` (e.g. `python3 -u script.py`) or prepend `PYTHONUNBUFFERED=1` so that stdout is streamed immediately to the system without subshell buffering delays.
    - **Decoupled Data Fetching & Local Scratch Caching (数据抓取与本地渲染解耦)**:
      - Separate long network fetches (e.g., yfinance, APIs) into dedicated fast data extraction steps that cache to JSON in scratch.
      - Keep HTML/Report generation purely local and synchronous (< 0.2s runtime) reading from scratch cache.
    - **Explicit HTTP Request Timeouts (显式网络超时控制)**: In data fetch scripts, configure reasonable timeouts (e.g. `timeout=5`) to avoid hanging on slow upstream finance APIs.
    - **Terminal Output Throttling & Token Diet (终端命令限流与 Token 瘦身)**:
      - Always throttle long command outputs using `head`, `tail`, `-n`, `--silent`, or `-q` (e.g. `git log -n 5`, `head -n 30`, `pytest -q`).
      - Avoid viewing full massive files (> 300 lines) into context; use `grep_search` and slice reading (`StartLine`/`EndLine`).

11. **Workspace Cleanliness & Zero Intermediate Artifacts Rule (工作区零中间代码与数据污染规范)**:
    - **Only Final HTML Reports in `output/` (唯一产物白名单)**: The ONLY files that may be created or stored in the project workspace are the final generated HTML research reports in `output/` (and their corresponding entry update in `output/index.html`).
    - **All Intermediate Scripts & Data in Scratch/Brain (严禁中间代码与缓存数据污染仓库)**: ALL ad-hoc fetch scripts, data processing scripts, temporary JSON cache files, and intermediate Python/Node artifacts **MUST NEVER** be created or left inside the project workspace directory (including `scripts/`, `data/`, root, etc.).
    - **Mandatory Scratch Storage**: All temporary and ad-hoc code/data MUST strictly be written to the scratch directory (`<appDataDir>/brain/<conversation-id>/scratch/` or `/tmp/`), completely isolated from the project repository.
    - **Immediate Cleanup Guarantee**: If any temporary files are created during execution, they must be cleaned up or saved exclusively in the scratch directory before concluding the turn.

12. **Mandatory Dividend Disclosure Rule (股息披露规范 - 必须写明股息，无则明确标注“无/没有”)**:
    - Whenever generating stock research, executive summaries, financial tables, key metrics cards, or HTML reports, the AI agent **MUST explicitly state the company's dividend status** (Dividend Yield, Annual Payout, Payout Ratio, Ex-Dividend Date).
    - **If the company does not pay dividends (Zero Dividend)**, the AI agent **MUST explicitly write "无 / 没有 (无股息派发 / Dividend: None / N/A)"** and explain shareholder return alternatives if applicable (e.g. 股票回购 / Share Buybacks).
    - AI agents must **NEVER omit or silently skip the dividend field**.

13. **Mandatory Comprehensive 15-Module Depth by Default (默认强制 15 模块全景全量研报规范)**:
    - Whenever generating stock research, full reports, or HTML analysis documents for any ticker, the AI agent **MUST ALWAYS default to Comprehensive Depth (全部 15 个全景核心模块)**.
    - **Strictly Prohibited**: Never default to Quick (5-7 modules) or Standard (8-10 modules) unless explicitly requested by the user.
    - **Mandatory 15-Module Checklist**:
      1. 执行摘要与核心投资逻辑 (Executive Summary & Thesis)
      2. 多因子量化评分雷达模型 (Multi-Factor Quantitative Scorecard & Radar Chart)
      3. 商业模式、垂直整合与波特五力护城河评级 (Business Model & Porter's 5 Forces)
      4. 核心财务报表与盈利质量深度剖析 (Financial Statements, Margins & Cash Flow Quality)
      5. 杜邦三因子拆解与资本运营效率 (DuPont Analysis: Margin × Turnover × Leverage)
      6. 行业竞争格局与同行全景对标矩阵 (Peer Comparison Matrix with Multiples, Margins, Market Share)
      7. DCF 现金流折现与内在价值三情景敏感性模型 (DCF Valuation: Bear/Base/Bull & WACC Sensitivity)
      8. 技术面量化、均线系统与关键筹码位 (Technical Analysis: SMA20/50/200, RSI, MACD, S/R)
      9. 资本配置、股息政策与股东回报披露 (Capital Allocation & Dividend: explicit "无/没有" if zero dividend)
      10. 现金担保卖出看跌期权 (Cash-Secured Sell Put) 收益增强策略 (Conservative, Moderate, Aggressive 3 Tiers)
      11. 机构持仓与主力资金动向 (Institutional Ownership: Top 13F Holders Table)
      12. 内部人交易、管理层语气与财报电话会洞察 (Insider Trading Form 4 & Earnings Call Tone)
      13. 做空比例、平仓天数与轧空风险评估 (Short Interest, Days to Cover & Options P/C Ratio)
      14. 核心风险矩阵与熊市压力测试 (Risk Matrix & Bear Case Downside Stress Test)
      15. 未来关键催化剂日历与增长路线图 (Catalyst Calendar & Strategic Milestones)
      16. 最终投资评级与执行建议 (Final Verdict & Standardized Signal Block)
