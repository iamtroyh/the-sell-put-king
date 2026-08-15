# -*- coding: utf-8 -*-
"""
The Sell Put King Strategy & Research Platform
==============================================
Production-grade quantitative options trading, portfolio risk management,
multi-factor scoring engine, and Robinhood integration.
"""

__version__ = "1.0.0"
__author__ = "Antigravity Quant Team"

from option_quant.config import (
    BASE_DIR,
    CONFIG_DIR,
    DATA_DIR,
    normalize_symbol,
    get_tradingview_url,
    atomic_write_json,
    load_json_config,
    is_long_bull,
    is_etf_symbol,
    is_high_vol_growth,
)

__all__ = [
    "BASE_DIR",
    "CONFIG_DIR",
    "DATA_DIR",
    "normalize_symbol",
    "get_tradingview_url",
    "atomic_write_json",
    "load_json_config",
    "is_long_bull",
    "is_etf_symbol",
    "is_high_vol_growth",
]
