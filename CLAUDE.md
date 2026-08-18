# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this unified quantitative options & equity research repository.

## Commands

### Option Quant Strategy & Dashboard
```bash
python3 -u scripts/run_research.py         # Run full master strategy pipeline
python3 -u scripts/generate_report.py      # Re-render report.html dashboard
python3 -u scripts/sync_investskill.py     # Sync InvestSkill reports to dashboard
pytest tests/ -q                          # Run Option Quant unit tests
```

### InvestSkill Deep Research & Validation
```bash
node InvestSkill/scripts/generate-output-index.js   # Rebuild InvestSkill/output/index.html
node InvestSkill/scripts/test-skills.js             # Run 270+ InvestSkill prompt structure tests
node InvestSkill/scripts/validate-prompts.js        # Validate prompt file contents and format
```

## Architecture

This workspace contains two integrated subsystems:
1. **The Sell Put King (`src/option_quant/`, `scripts/`)**: Quantitative Cash Secured Put & Covered Call screening engine, 40/30/30 multi-factor scoring, Robinhood portfolio risk governance, and live interactive dashboard (`report.html`).
2. **InvestSkill (`InvestSkill/`)**: 25 prompt-engineering analysis frameworks for US stock markets (`InvestSkill/prompts/`), generating 15-module institutional deep dive reports into `InvestSkill/output/`.

## Key Execution Rules

1. **InvestSkill 15-Module Standard & Direct Ticker Trigger**: Directly typing a ticker symbol (e.g. `NVDA`, `AAPL`, `TSLA`, `分析 MSFT`) automatically triggers the full 15-module institutional deep dive (`research <TICKER>`), exporting to `InvestSkill/output/{TICKER}_report_{YYYY-MM-DD}.html` in Chinese with proper color themes (Emerald for Bullish, Amber for Neutral, Red for Bearish).
2. **Output Index Sync**: Immediately run `node InvestSkill/scripts/generate-output-index.js` upon generating any HTML report.
3. **Dividend Disclosure**: Must explicitly state dividend status (or write "无 / 没有 (无股息派发 / Dividend: None / N/A)").
4. **Zero-Truncation Price Integrity**: Never execute double-quoted inline shell commands with `$125.00`. Use dedicated Python scripts or safe heredocs.
5. **Intermediate File Hygiene**: Ad-hoc scratch scripts and temporary cache must stay in scratch directory, never polluting repository folders.
