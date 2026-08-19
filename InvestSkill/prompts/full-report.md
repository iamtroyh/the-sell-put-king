# Full Report — Comprehensive Stock Analysis Orchestrator

Orchestrate InvestSkill analysis modules on one ticker at your chosen depth, synthesize findings into a unified investment thesis with composite scoring, and produce a standalone professional HTML report with interactive Chart.js visualizations.

## Depth Flags

Select how many modules to run with `--depth`:

| Flag | Modules | Best For |
|------|---------|----------|
| `--depth quick` | 5 core modules | Rapid screen, time-constrained due diligence |
| `--depth standard` | 10 modules | Balanced research before initiating a position |
| `--depth comprehensive` | All 15 modules | Full pre-commitment due diligence (default) |

---

## Module Sets by Depth

### Quick (5 modules)

| # | Module | Focus |
|---|--------|-------|
| 1 | stock-eval | Company overview, competitive position, relative valuation |
| 2 | technical-analysis | MA, RSI, MACD, volume, support/resistance |
| 3 | dcf-valuation | DCF intrinsic value, bear/base/bull scenarios |
| 4 | insider-trading | SEC Form 4 patterns, net insider sentiment |
| 5 | earnings-call-analysis | Management tone, guidance quality, key themes |

### Standard (10 modules — Quick + 5 more)

| # | Module | Focus |
|---|--------|-------|
| 6 | institutional-ownership | 13F holdings, smart money flows |
| 7 | competitor-analysis | Moat, market share, Porter's Five Forces |
| 8 | sector-analysis | Sector rotation, relative strength |
| 9 | options-analysis | IV, Put/Call ratio, max pain, strategies |
| 10 | short-interest | Short ratio, squeeze risk, days-to-cover |

### Comprehensive (15 modules — Standard + 5 more)

| # | Module | Focus |
|---|--------|-------|
| 11 | fundamental-analysis | Income statement, balance sheet, cash flow |
| 12 | stock-valuation | P/E, P/S, EV/EBITDA, peer multiples |
| 13 | economics-analysis | Macro environment, rate sensitivity |
| 14 | financial-report-analyst | 10-K/10-Q deep dive, risk factors |
| 15 | dividend-analysis | Yield, payout ratio, sustainability |

---

## Research Process (5 Phases)

Modules are grouped into phases regardless of depth. Earlier phases inform later-phase assumptions.

### Phase 1 — Business & Competitive Foundation

Establish qualitative and quantitative foundation before attempting valuation.

- **stock-eval** — Company overview, competitive position, relative valuation vs. peers
- **competitor-analysis** *(standard+)* — Moat depth, Porter's Five Forces, pricing power
- **fundamental-analysis** *(comprehensive)* — Income statement, balance sheet, cash flow quality

Output: **Business Quality Score (0–10)**
Score reflects durability of competitive advantages, financial health, and consistency of returns.

### Phase 2 — Valuation & Dual-Anchor Margin of Safety

Determine intrinsic, relative, and options-discounted worth of the business.

- **dcf-valuation** — Intrinsic value with Bull/Base/Bear scenarios and WACC sensitivity
- **stock-valuation** *(comprehensive)* — P/E, EV/EBITDA, P/S, P/FCF peer multiples and 5-year historical percentile
- **Dual-Anchor Net Basis Floor** — Evaluates both spot discount and Cash-Secured Put net acquisition basis `min(Spot, Strike - Premium)` against DCF intrinsic value

Output: **Valuation & Margin of Safety Score (0–10)** — 10 = deep discount to intrinsic value (>40% margin of safety or net basis P/E < 15x on quality compounder); 5 = fair value; 0 = extreme overvaluation.

### Phase 3 — Market Signals

Understand what sophisticated market participants are signaling.

- **insider-trading** — SEC Form 4 patterns, net insider sentiment
- **institutional-ownership** *(standard+)* — Smart money 13F changes, concentration
- **earnings-call-analysis** — Management tone, guidance quality, forward signals

Output: **Market Signal Score (0–10)** — High = insider buying + institutional accumulation + positive management tone.

### Phase 4 — Technical Timing & Quality-Conditioned Regime Switch

Identify current technical setup and asymmetric payoff position using a **Quality-Conditioned Regime Switching Engine** (preventing momentum trap on tops and falling knife trap on distressed assets):

- **High-Quality Asset Regime (Business Quality >= 7.5 & Financial Health >= 7.0)**:
  - Switches to **Mean-Reversion & Value Floor Mode**:
  - Deep 52W Low test (RP < 0.20), 200 SMA negative deviation, and RSI oversold/bullish divergence are scored as **Strong Left-Side Accumulation / Golden Pit (8.0–9.5)**.
  - Overbought peaks (RP > 0.85, RSI > 75) without multiple expansion justification are penalized for chasing momentum (5.0–6.0).
- **Distressed / Low-Quality Asset Regime (Business Quality < 5.0 or Solvency Risk High)**:
  - Locks into **Strict Trend-Following & Breakdown Penalty Mode**:
  - Downtrends and 200 SMA breakdowns are scored as **Weak / Toxic Falling Knife (0.0–3.5)** to prevent catching falling knives on deteriorating businesses.
- **Classic Indicators**: MA30/60/90/200/365 alignment, RSI(14), MACD momentum, Volume profile, Key Support/Resistance.

Output: **Technical & Position Score (0–10)** — 8.0–10.0 = Prime entry (Golden Pit floor or confirmed breakout); 4.0–7.0 = Consolidating / Neutral; 0.0–3.9 = Toxic breakdown or high-risk topping pattern.

### Phase 5 — Risk Assessment & Asymmetric Payoff

Quantify downside risks, positioning pressure, and option-implied buffer.

- **short-interest** *(standard+)* — Short positioning, days-to-cover, squeeze risk (bullish catalyst for quality assets, danger sign for low-quality)
- **options-analysis** *(standard+)* — Implied volatility percentile (IVP), options skew, put/call ratios, Theta cushion rate
- **economics-analysis** *(comprehensive)* — Macro environment, rate sensitivity
- **financial-report-analyst** *(comprehensive)* — 10-K/10-Q risk factors and debt maturity schedule

Output: **Risk & Asymmetric Payoff Score (0–10)** — High score (8–10) = Low solvency risk + High IV cushion (>30% APY protection) + Asymmetric upside (>1:3 risk-reward); Low score (0–3) = Structural insolvency or downside tail risk.

---

## Composite Scoring Framework

```
Full Report Score = Weighted Composite

Component                         Weight    Sub-Score (0-10)
─────────────────────────────────────────────────────────────────────────────
1. Business Quality & Moat         25%      [Phase 1: Franchise, ROIC, FCF]
2. Valuation & Margin of Safety    25%      [Phase 2: DCF, Multiples, Net Basis]
3. Market & Institutional Signals  20%      [Phase 3: 13F, Insider, Guidance]
4. Technical & Regime Position     15%      [Phase 4: Golden Pit vs Trend]
5. Risk & Asymmetric Payoff        15%      [Phase 5: Solvency, IV Buffer, Squeeze]
─────────────────────────────────────────────────────────────────────────────
COMPOSITE SCORE                   100%      X.X / 10

Composite Interpretation:
8.0–10.0  → Strong Buy   (all signals aligned / prime golden pit or breakout)
6.5–7.9   → Buy          (strong fundamentals, favorable risk-reward)
5.0–6.4   → Hold/Watch   (fairly valued or consolidating)
3.5–4.9   → Underweight  (elevated valuation or weakening moat)
0.0–3.4   → Sell/Avoid   (structural deterioration or severe solvency distress)
```

Sub-score derivation:
- **Business Quality (25%)**: Average of economic moat rating (0-10) + capital return efficiency (ROIC/ROE/FCF Margin).
- **Valuation & Margin of Safety (25%)**: Weighted blend of DCF base-case discount + 5-year historical multiple percentile + Sell Put net basis discount.
- **Market Signals (20%)**: Weighted average of SEC Form 4 insider sentiment + 13F institutional accumulation + management earnings call tone.
- **Technical & Regime Position (15%)**: Conditioned on business quality. High quality + 52W bottom (RP < 0.20) = 8.0~9.5 (Golden Pit); Low quality + breakdown = 0.0~3.5 (Falling Knife).
- **Risk & Asymmetric Payoff (15%)**: Solvency safety (Interest coverage, Net debt/EBITDA) + IV time-decay downside cushion rate + Short squeeze asymmetry.

When running quick or standard depth, scores for missing modules default to neutral (5.0) and are flagged as "not assessed" in the scorecard.

---

## Conflict Resolution & Epistemic Rigor

When signals conflict across modules, apply these rules:

- **Quality & Solvency Gatekeeper**: If Interest Coverage < 2.0x or structural FCF is negative on non-growth assets, cap the overall rating at Hold (<= 6.0) regardless of how cheap valuation appears.
- **Quality-Conditioned Technical Interpretation**: Never penalize high-quality, cash-generating compounders merely for being in a left-side cyclical pullback. Recognize that deep 200 SMA negative deviation on wide-moat assets represents maximal margin of safety.
- **Fundamental overrides technical**: Business quality and intrinsic value take precedence over short-term price action.
- **Consensus overrides outlier**: When 4 of 5 phases agree on direction, document the outlier but do not let it dominate the composite score.
- **Document all conflicts explicitly**: Never suppress conflicting signals. Present the full bull and bear case and explain how the weighting resolves the conflict.
- **Flag unresolvable conflicts**: When signals are deeply contradictory (e.g., strong fundamentals + extreme overvaluation + heavy insider selling), flag as "Conflicted — Monitor Only" until resolution.

---

## Investment Thesis Narrative

Every full-report output must include a narrative investment thesis structured as:

1. **Investment Thesis** (2–3 paragraphs): What does the company do, why is it a compelling or poor investment now, and what is the key insight driving the thesis?
2. **Bull Case** (3–5 quantifiable reasons with supporting evidence from phase outputs)
3. **Bear Case** (3–5 specific risks with probability assessment and potential intrinsic value impact)
4. **Composite Score Card** (visual table with all component scores, weighted scores, and interpretation)
5. **Valuation Summary** (intrinsic value per share, current price, margin of safety, upside/downside % per scenario)
6. **Entry & Options Strategy** (technical setup description, ideal spot entry range, position sizing, plus **Cash-Secured Sell Put strike price recommendations**: Conservative, Moderate, and Aggressive tiers with 30–45 DTE)
7. **Exit Strategy** (base/bull/bear price targets, stop-loss level, time horizon)
8. **Monitoring Plan** (key metrics to track quarterly, thesis-changing events, early warning signals, next catalyst dates)

---

## HTML Report Structure

The output file is a standalone HTML document (no external dependencies except CDN Chart.js):

- **Cover page** — ticker, price, date, depth flag used, overall composite score, recommendation
- **Sidebar TOC** — sticky navigation linking to each section
- **Analysis sections** — one per executed module plus final synthesis
- **Interactive charts** — MA overlay, RSI, MACD, volume, composite score radar, phase score bar
- **Composite Score Card** — weighted multi-factor scorecard with color coding
- **Signal block** — standardized investment signal at report end

### Design Principles

- Clean, minimal design — white background, navy accents, Inter/system font
- Data-dense tables with clear visual hierarchy
- Color coding: green = bullish, amber = neutral, red = bearish
- Print-friendly (no fixed sidebars when printing)
- Self-contained: one `.html` file, no local assets

---

## Usage

```
full-report AAPL
full-report NVDA --depth quick
full-report MSFT --depth standard
full-report TSLA --depth comprehensive --lang zh-TW
full-report AMZN --output ~/Desktop/
```

**Arguments:**
- `<TICKER>` — required, any US-listed stock
- `--depth` — `quick` | `standard` | `comprehensive` (default: `comprehensive`)
- `--lang` — output language, default `en`, supports `zh-TW`, `zh-CN`, `ja`
- `--output` — custom save path, default `output/`

---

## Output File Naming

```
output/<TICKER>_report_<YYYY-MM-DD>.html
```

Example: `output/AAPL_report_2025-06-19.html`

---

## Workflow

1. Parse `--depth` flag and determine which modules to run
2. Gather all available data for `<TICKER>` (financials, price, filings, macro)
3. Execute modules in phase order; each phase's output informs the next
4. Compute composite weighted score (0–10) using framework above
5. Build investment thesis narrative with bull/bear case
6. Render complete HTML with all sections, charts, and scorecard
7. Write file to output path, dynamically update `output/index.html` (e.g. `node scripts/generate-output-index.js` or `npm run update:index`), and confirm location

---

## Data Verification

**Open the report with a `Data & Sources` header** so provenance is explicit:

```
Data & Sources
  As of:      <date the figures represent>
  Source:     <primary docs — SEC EDGAR 10-K/10-Q, company IR, FRED, …>
  Retrieval:  <pasted by user | web/tool retrieval | model memory>
  Confidence: <HIGH | MEDIUM | LOW>
```

Before rendering the final report, verify:
- The `Data & Sources` header is present and the Retrieval/Confidence are honest (flag "model memory" as LOW)
- All executed modules returned scores (not blank)
- Scores are within 0–10 range
- Weighted composite arithmetic is correct (weights sum to 100%)
- Missing modules for quick/standard depth are flagged as "not assessed"
- No data older than 90 days used without explicit warning

**Then run `result-validator`** on the composite result and include its confidence score in the report footer — a composite thesis should never ship without this validation pass.

---

## Output Format

End with the standard signal block after the final synthesis section:

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

Score Guide: 8.0–10.0 Strongly Bullish | 6.0–7.9 Moderately Bullish | 4.0–5.9 Neutral | 2.0–3.9 Moderately Bearish | 0.0–1.9 Strongly Bearish
Confidence: HIGH (strong data, clear signals) | MEDIUM (mixed signals) | LOW (limited data, conflicting signals)
Horizon: SHORT-TERM (1 week–3 months) | MEDIUM-TERM (3 months–1 year) | LONG-TERM (1+ years)

**Disclaimer:** Educational analysis only. Not financial advice.
