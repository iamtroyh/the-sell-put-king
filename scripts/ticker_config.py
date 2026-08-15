# -*- coding: utf-8 -*-
"""
Ticker Configuration & Classification Adapter
=============================================
Maintains backward compatibility with legacy scripts while delegating
to the centralized option_quant.config module.
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from option_quant.config import (  # noqa: E402
    BASE_DIR,
    BROAD_TICKERS,
    CONFIG_DIR,
    CREDENTIALS_PATH,
    DATA_DIR,
    ETF_TICKERS,
    HIGH_VOL_GROWTH_TICKERS,
    INVESTSKILL_DIR,
    INVESTSKILL_OUTPUT_DIR,
    LONG_BULL_TICKERS,
    PRESELECTED_TICKERS,
    RISK_FREE_RATE,
    ROBINHOOD_ACCOUNT_ID,
    SCAN_CONFIG_PATH,
    SECTOR_MAP,
    TICKER_EXCHANGE_MAP,
    TICKER_FUNDAMENTALS,
    TICKER_INTROS,
    TICKER_METADATA_PATH,
    TICKER_RISKS,
    atomic_write_json,
    get_robinhood_account_id,
    get_scan_parameters,
    get_tradingview_url,
    is_etf_symbol,
    is_high_vol_growth,
    is_long_bull,
    load_json_config,
    mask_account_id,
    normalize_symbol,
    to_display_symbol,
    to_rh_symbol,
    to_yf_symbol,
)
