# Strategy Execution & Data Pipeline Scripts

This directory contains executable Python dispatch scripts and standalone CLI tools for quantitative Sell Put & Covered Call options screening, portfolio risk ETL, and report compilation. Core scoring algorithms and data models are powered by the `src/option_quant` package as the single source of truth.

## Core Scripts & Functional Breakdown

### 1. Research Pipeline & Report Generation
- **`run_research.py`**: Master workflow runner executing the full screening, review, scoring, and HTML dashboard compilation (equivalent to `the-sell-put-king run`).
- **`generate_report.py`**: Multi-factor scoring engine, InvestSkill institutional research synthesizer, and HTML report generator. Fully modularized to call `src/option_quant/` algorithms.

### 2. Data ETL & High-Speed Options Pipeline
- **`fast_option_scan.py`**: High-speed concurrent option chain scanner fetching pre-filtered candidate contracts across all universe targets in < 3 seconds.
- **`fetch_true_iv.py`**: Fetches true 252-day historical implied volatility (IVP / IVR), 25-Delta panic put skew, Max Pain pinning levels, and expected earnings jump moves.
- **`sync_data.py`**: Ingests Robinhood balances, equity holdings, and open options positions into `data/account_info.json` and `data/current_positions.json`.
- **`get_scan_targets.py`**: Scans market-wide universe for 200-SMA and 52-week valuation troughs across DTE 15-60 expiration cycles, outputting to `data/scan_targets.json`.
- **`filter_instruments.py`**: Filters option contracts based on dynamic Delta bounds (0.10~0.30/0.40) and moneyness, writing to `data/filtered_instruments.json`.
- **`get_quote_batches.py`**: Slices filtered candidate contract IDs into batches of up to 40 items to prevent silent API packet drops, writing to `data/quote_batches.json`.
- **`build_options_cache.py`**: Compiles structured local options database into `data/robinhood_options_cache.json`.
- **`sync_watchlist_mcp.py`**: Synchronizes ranked candidates to the Robinhood mobile App `Sell Put Candidate` Watchlist via LIFO reverse insertion.

### 3. Quantitative Utilities & Diagnostic CLI Tools
- **`option_apy_calculator.py`**: Annualized yield (APY) calculator supporting both CLI argument execution and interactive console loops.
- **`portfolio_delta.py`**: Portfolio Delta notional exposure and net liquidity leverage ratio analyzer.
- **`insider_sentiment.py`**: SEC Form 4 insider trading sentiment analyzer over 90-day transaction windows.
- **`sync_investskill.py`**: Indexes and refreshes local InvestSkill institutional reports into the interactive trading dashboard.
- **`ticker_config.py`**: Backward-compatible configuration loader and ticker symbol normalizer forwarding to `option_quant.config`.

---

## Quick Command Examples

```bash
# 1. Run full strategy pipeline
python3 scripts/run_research.py

# 2. Run fast parallel option scan (<3s)
python3 scripts/fast_option_scan.py

# 3. Calculate option APY
python3 scripts/option_apy_calculator.py 15 100 2.5

# 4. Inspect portfolio Delta leverage
python3 scripts/portfolio_delta.py

# 5. Fetch SEC Form 4 insider sentiment
python3 scripts/insider_sentiment.py LULU
```
