# InvestSkill Deep Research & Report Generation Rules (Institutional Standard)

This document defines the core engineering standards, quality gatekeepers, and execution rules for generating InvestSkill institutional stock research reports within the `InvestSkill/` workspace module.

---

## 1. Output Directory Index Rule (Mandatory)
- Whenever an AI agent generates or updates any `.html` report in `InvestSkill/output/`, the agent **MUST dynamically update `InvestSkill/output/index.html`** by running:
  ```bash
  node InvestSkill/scripts/generate-output-index.js
  ```
- `InvestSkill/output/index.html` serves as the single entry directory for all generated reports with direct clickable links (`<a href="./filename.html">`) and metadata (Ticker, Title, Signal & Score, Date, File Size).
- **Ground-Truth Signal Verdict Preservation Rule**: Index generator scripts and AI agents **MUST strictly respect and extract the exact investment verdict text from the HTML report** (`看多 (BULLISH)`, `强烈看多 (STRONG BUY)`, `中立 (NEUTRAL)`, `看空 (BEARISH)`, `强烈看空 (STRONG SELL)`).
- **Score-to-Verdict Deterministic Binding Iron Rule (分值与评级字面强绑定一致性铁律)**: All generated reports and subagent prompts MUST strictly adhere to the standardized score-to-verdict mapping without exception across all HTML elements (Hero Badge, Hero KPI subtitle, and Section 15 Signal Block):
  * **Score >= 8.0**: **MUST be `强力买入 (Strong Buy)` / `强烈看多 (Strong Buy)`**. Strictly prohibit using generic `买入 (BUY)` or `BULLISH` which creates tier ambiguity.
  * **6.5 <= Score < 8.0**: **MUST be `买入 (Buy)` / `看多 (Bullish)`**.
  * **5.0 <= Score < 6.5**: **MUST be `中立 (Neutral)` / `持有/观望 (Hold)`**.
  * **3.5 <= Score < 5.0**: **MUST be `减持 (Underweight)` / `谨慎看空 (Weak Bearish)`**.
  * **Score < 3.5**: **MUST be `卖出 (Sell)` / `强烈看空 (Strong Sell)`**.
- **Index Signal Badge Gradient & Score Display**: Badges on `InvestSkill/output/index.html` must display both the exact verdict text and score (e.g. `强烈看多 (STRONG BUY) • 8.6/10`), styled with continuous glowing gradients (Emerald for Bullish, Amber for Neutral, Red for Bearish).

---

## 2. Mandatory Comprehensive 15-Module Depth by Default (满血研报严禁偷懒缩水铁律)
- **严禁偷懒省略与凭空猜测 (Zero Guesswork & Anti-Laziness)**: 生成任何个股研报时，**永远一定必须生成 100% 满血版机构级深度研报**。绝对禁止使用几句简写敷衍概括代替完整数据！所有财务数据、期权报价、估值参数必须来自真实数据与模型推导。
- **权威规范唯一定义源**: 研报必须严格执行 [`InvestSkill/prompts/full-report.md`](file:///Users/yuezh/Option/InvestSkill/prompts/full-report.md) 定义的完整 15 模块全景架构，包含全部业务细分拆解、4年历史财务报表、杜邦分析、同行对标、WACC 6×5 交叉敏感性矩阵、3梯队期权合约、13F 机构表、电话会原话实录、熊市压力测试与 4 大 Chart.js 交互图表。

---

## 3. Report Language Requirement (中文报告规范)
- All generated stock research reports, HTML analysis documents, and summaries **MUST be rendered in Chinese (中文)** unless explicitly requested otherwise.

---

## 4. Report Signal Color Theme Rules (报告信号主题配色与背景刚性规范)
- **严禁提取企业 Logo 色作为主题背景 (Corporate Logo Colors Strictly Prohibited)**: 严禁将个股企业 VI 或 Logo 私有色（如 HDFC 银行深蓝、Alnylam 基因制药生物紫、携程天蓝等）作为研报的主题色或背景。所有研报的主题色与顶部横幅背景 **100% 服务于投资信号 (Investment Signal)**，实现跨标的视觉标准统一！
- **全页统一背景色**: 全文 `body` 背景色 **必须统一使用 `#F8FAFC`**（Slate-50 极浅柔和纸质灰白），严禁使用深色或带色背景。
- **三大法定信号调色板**:
  * **看多 / 强力买入 (Strong Buy / Bullish)**:
    ```css
    :root {
        --primary:       #059669;
        --primary-dark:  #064E3B;
        --primary-light: #ECFDF5;
        --accent:        #10B981;
        --accent-light:  #D1FAE5;
        --grad-hero:     linear-gradient(135deg, #064E3B 0%, #065F46 45%, #059669 80%, #10B981 100%);
        --grad-accent:   linear-gradient(90deg, #059669, #10B981);
    }
    ```
  * **中立 / 观望 (Neutral / Hold)**:
    ```css
    :root {
        --primary:       #D97706;
        --primary-dark:  #78350F;
        --primary-light: #FEF3C7;
        --accent:        #F59E0B;
        --accent-light:  #FDE68A;
        --grad-hero:     linear-gradient(135deg, #78350F 0%, #B45309 45%, #D97706 80%, #F59E0B 100%);
        --grad-accent:   linear-gradient(90deg, #D97706, #F59E0B);
    }
    ```
  * **看空 / 卖出 (Bearish / Sell)**:
    ```css
    :root {
        --primary:       #DC2626;
        --primary-dark:  #7F1D1D;
        --primary-light: #FEE2E2;
        --accent:        #EF4444;
        --accent-light:  #FECACA;
        --grad-hero:     linear-gradient(135deg, #7F1D1D 0%, #991B1B 45%, #DC2626 80%, #EF4444 100%);
        --grad-accent:   linear-gradient(90deg, #DC2626, #EF4444);
    }
    ```

---

## 5. Mandatory Dividend Disclosure Rule (股息披露规范)
- Whenever generating stock research, executive summaries, financial tables, key metrics cards, or HTML reports, the AI agent **MUST explicitly state the company's dividend status** (Dividend Yield, Annual Payout, Payout Ratio, Ex-Dividend Date).
- **If the company does not pay dividends (Zero Dividend)**, the AI agent **MUST explicitly write "无 / 没有 (无股息派发 / Dividend: None / N/A)"** and explain shareholder return alternatives if applicable (e.g. 股票回购 / Share Buybacks). Never omit or leave blank.

---

## 6. Price Integrity & Zero-Truncation Execution Rule (价格完整性与零截断防错规范)
- AI agents **MUST NEVER** execute double-quoted inline shell commands containing currency symbols (e.g. `python3 -c "..."` with `$125.00`).
- Always use dedicated script files, safe single-quoted heredocs (`cat << 'EOF' > ...`), or native safe file writing tools (`write_to_file`).
- Immediately after generating or modifying any HTML report, verify that price numbers are intact and uncorrupted.

---

## 7. Mobile Compatibility & Responsive Layout Rule (移动端兼容与响应式排版规范)
- Every generated HTML report MUST include `<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0, viewport-fit=cover">` and `<meta name="format-detection" content="telephone=no">`.
- Fluid responsive layout (`max-width: 1100px; width: 100%`) with adaptive padding.
- All data tables MUST be enclosed in `<div class="table-scroll" style="overflow-x: auto; -webkit-overflow-scrolling: touch;">`.
- Charts (`Chart.js`) MUST be configured with `responsive: true, maintainAspectRatio: false` inside a constrained-height canvas wrapper.

---

## 8. The 7 Deterministic DOM Formatting Contracts (研报 7 大 DOM 格式确定性契约)

All generated InvestSkill HTML reports MUST 100% strictly adhere to the following 7 standardized DOM structural contracts to ensure absolute programmatic consistency, perfect mobile rendering, and seamless catalog indexing:

### Contract 1: Title & Main Heading (<title> & <h1>)
- Strictly prohibit boilerplate suffixes (e.g., "15模块满血版", "全景机构版", "全模块深度研究").
- Standardized Format:
  - `<title>{标的名称} ({TICKER}) 深度投研报告 - InvestSkill</title>`
  - `<h1>{标的名称} ({TICKER}) 深度投研报告</h1>`

### Contract 2: Hero Badges (Exactly 5 Standard Badges)
The `.hero-badge-row` container MUST contain exactly 5 standard badges in this precise sequence:
1. `🏛️ {EXCHANGE}: {TICKER} · {公司中文或官方名}`
2. `📂 {GICS 一级行业} | {核心业务模式与护城河定位}`
3. `🚀 强力买入 (Strong Buy)` / `🟢 买入 (Buy)` / `🟡 中立 (Hold)` / `🔴 卖出 (Sell)` (100% strictly derived from Composite Score)
4. `📈 52周相对位置: XX.X% (RP 分位)` 或 `估值折让: XX.X%`
5. `📅 报告基准日: YYYY-MM-DD`

### Contract 3: 4-Grid Hero KPI Cards (Exactly 4 Cards)
The `.hero-kpis` container MUST strictly contain exactly 4 KPI cards with standard field names:
- **Card 1 (Price)**: `<div class="hero-kpi-lbl">当前市场现价</div>` $\to$ `<div class="hero-kpi-val">$XX.XX</div>` $\to$ `<div class="hero-kpi-sub">52周: $XX.XX ~ $XX.XX (RP: XX.X%)</div>`
- **Card 2 (Score)**: `<div class="hero-kpi-lbl">多因子综合评分</div>` $\to$ `<div class="hero-kpi-val">X.X / 10</div>` $\to$ `<div class="hero-kpi-sub">{法定评级} • {一句话核心逻辑}</div>`
- **Card 3 (Market Cap)**: `<div class="hero-kpi-lbl">总市值 (Market Cap)</div>` $\to$ `<div class="hero-kpi-val">$XX.XB</div>` $\to$ `<div class="hero-kpi-sub">企业价值 (EV): $XX.XB</div>`
- **Card 4 (Valuation)**: `<div class="hero-kpi-lbl">市盈率与估值中枢</div>` $\to$ `<div class="hero-kpi-val">P/E: XX.Xx</div>` $\to$ `<div class="hero-kpi-sub">DCF 公允价值: $XX.XX</div>`

### Contract 4: 15-Module Section IDs & Table of Contents (<section id="sec-N">)
- Every report MUST partition its content into exactly 15 sequential sections using standard HTML5 `<section>` tags:
  `<section id="sec-1" class="section">` through `<section id="sec-15" class="section">`.
- The Table of Contents (`<nav class="toc">`) MUST contain 15 clickable navigation links mapping 1-to-1 to `href="#sec-1"` through `href="#sec-15"`.

### Contract 5: Section 15 Standard Investment Signal Block (Signal Block DOM Contract)
Section 15 MUST conclude with the standardized investment signal block using exact CSS class names:
```html
<div class="signal-block">
    <div class="signal-label-top">INVESTMENT SIGNAL BLOCK (15-MODULE COMPREHENSIVE SYNTHESIS)</div>
    <div class="signal-header-row">
        <div class="signal-verdict">{法定评级} • {核心投资论点}</div>
        <div class="signal-score">X.X / 10</div>
    </div>
    <div class="signal-grid">
        <div class="signal-item"><div class="sig-label">投资信号 (Signal)</div><div class="sig-val">{法定评级}</div></div>
        <div class="signal-item"><div class="sig-label">置信度 (Confidence)</div><div class="sig-val">HIGH / MEDIUM / LOW</div></div>
        <div class="signal-item"><div class="sig-label">投资期限 (Horizon)</div><div class="sig-val">MEDIUM-TERM (6-18个月)</div></div>
        <div class="signal-item"><div class="sig-label">执行建议 (Action)</div><div class="sig-val">{具体操作如：CSP卖出看跌期权 / 现货分批吸筹}</div></div>
    </div>
</div>
```

### Contract 6: Section 10 Cash-Secured Put 3-Tier Table Schema (Options Table Contract)
Section 10's options recommendation table MUST be wrapped in `<div class="table-scroll">` and contain standard 10 columns:
`[策略梯队, 行权价 (Strike), 到期日 (Expiry), 剩余 DTE, Delta (Δ), 权利金 Mark (Bid/Ask), 年化收益率 (APY), 安全垫缓冲 (Cushion), 到期胜率 (POP), 单份现金担保需求]`
Presenting 3 graded tiers: **保守型 (Conservative)**, **平衡型 (Moderate)**, **激进型 (Aggressive)**.

### Contract 7: Chart.js Canvas ID Namespace (Canvas ID Contract)
All interactive Chart.js elements MUST use standardized semantic canvas IDs:
- `chart-radar`: Multi-factor scorecard radar chart
- `chart-financials`: 4-year revenue & net income trend chart
- `chart-valuation`: Historical valuation multiple percentile & DCF bridge chart
- `chart-options`: Options payoff / probability distribution chart

---

## 9. Epistemic Independence & Clean-Slate Analysis Iron Rule (独立思考与样式内容严格隔离铁律)
- **格式与样式可借鉴，内容绝对零污染**：在读取历史已有研报时，**仅学习其 CSS 视觉风格、Chart.js 交互图表骨架、HTML 布局与排版规范**；
- **严禁内容与逻辑互相影响**：每一只标的的深度投研必须基于第一性原理，从零开始抓取该公司的最新一手财务报表（10-K/10-Q）、实时市场行情、期权链、具体商业模式、护城河特征与精准 DCF/量化模型，**严格做到独立思考、实事求是，绝不套用、迁移或受任何其他标的研报观点的先入为主影响**。

---

## 10. Research Freedom & Intellectual Primacy Iron Rule (投研深度与思考自由度铁律 · 形式确定，实质自由)
- **形式确定，实质自由 (Deterministic Shell, Autonomous Reasoning)**:
  * **确定性的严格边界仅在外壳 (The Outer Shell)**：所有格式规则、CSS 变量、`<title>` 纯净化、DOM ID 仅作用于最外层视觉呈现与目录解析，**坚决不跨越到内文逻辑一步**；
  * **内文分析属于大模型的自主智慧 (Intellectual Primacy)**：研报的核心价值 100% 取决于大语言模型（LLM）的深度思考、长上下文推理与穿透性财务洞察。**绝对严禁将研报退化为脚本机械填词、八股文模板拼装或空洞套话**！
  * **深度挖掘标的独特商业灵魂 (Deep Specificity)**：每一份研报必须深入剖析该标的所独有的护城河、行业周期与异动归因（例如 HDB 的存贷比置换与印度国运、LULU 的品类扩展与库存周转、ACN 的生成式 AI 落地新签订单周期、FSLR 的 IRA 补贴与薄膜壁垒），确保每一篇研报都具备华尔街顶级 Buy-Side 机构的深度与实战穿透力；
  * **脚本零篡改正文铁律 (Zero Text Tampering by Scripts)**：任何下游门禁、构建或归一化脚本（如 `generate-output-index.js`），**绝对严禁修改、覆盖或篡改 HTML 正文中的任何一段财务分析文字、辩论论点或估值推导逻辑**，投研内容永远受大模型自主推理最高统辖！
