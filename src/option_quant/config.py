# -*- coding: utf-8 -*-
"""
Configuration & Metadata Management Module
==========================================
Centralized configuration, credentials, directory path resolution, symbol
normalization, and thread-safe atomic file I/O operations.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, List, Optional, Set

# Base directory resolution (root of the workspace)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
DATA_DIR = os.path.join(BASE_DIR, "data")
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")

# Configuration paths
SCAN_CONFIG_PATH = os.path.join(CONFIG_DIR, "scan_config.json")
TICKER_METADATA_PATH = os.path.join(CONFIG_DIR, "ticker_metadata.json")
CREDENTIALS_PATH = os.path.join(CONFIG_DIR, "credentials.json")

# External InvestSkill paths
INVESTSKILL_DIR = os.environ.get("INVESTSKILL_DIR", os.path.expanduser("~/InvestSkill"))
INVESTSKILL_OUTPUT_DIR = os.environ.get("INVESTSKILL_OUTPUT_DIR", os.path.join(INVESTSKILL_DIR, "output"))

# Risk-free rate constant
RISK_FREE_RATE = 0.05

_FILE_LOCK = threading.Lock()


def load_json_config(path: str) -> Dict[str, Any]:
    """
    Safely load a JSON configuration file.
    If the file is the credentials file, enforces 0600 file permissions.

    Args:
        path: Absolute path to the JSON file.

    Returns:
        Parsed JSON object or an empty dictionary on failure.
    """
    if os.path.exists(path):
        if path == CREDENTIALS_PATH:
            try:
                os.chmod(path, 0o600)
            except Exception:
                pass
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


# Load initial configurations
_scan_config = load_json_config(SCAN_CONFIG_PATH)
_ticker_metadata = load_json_config(TICKER_METADATA_PATH)
_credentials = load_json_config(CREDENTIALS_PATH)


def get_robinhood_account_id() -> str:
    """
    Retrieve the configured Robinhood account ID.
    Prioritizes environment variable ROBINHOOD_ACCOUNT_ID over credentials.json.

    Returns:
        Account ID string or empty string if not configured.
    """
    return os.environ.get("ROBINHOOD_ACCOUNT_ID") or _credentials.get("robinhood_account_id", "")


def get_marketdata_token() -> str:
    """
    Retrieve the configured Market Data API token.
    Prioritizes environment variables (MARKETDATA_TOKEN / MARKETDATA_API_KEY) over credentials.json.

    Returns:
        Token string or empty string if not configured.
    """
    return (
        os.environ.get("MARKETDATA_TOKEN")
        or os.environ.get("MARKETDATA_API_KEY")
        or _credentials.get("marketdata_token", "")
        or _credentials.get("marketdata_api_key", "")
    )


def mask_account_id(acc_id: str) -> str:
    """
    Mask an account ID for secure display in logs or UI.

    Args:
        acc_id: Raw account ID.

    Returns:
        Masked account string, e.g. "1163******43".
    """
    if not acc_id or len(acc_id) <= 6:
        return "****"
    return acc_id[:4] + "*" * (len(acc_id) - 6) + acc_id[-2:]


# Global static metadata & pools
ROBINHOOD_ACCOUNT_ID = get_robinhood_account_id()
MARKETDATA_TOKEN = get_marketdata_token()

PRESELECTED_TICKERS: List[str] = _scan_config.get("preselected_tickers", [
    'IBIT', 'BRK-B', 'SPYM', 'ASHR', 'QQQM', 'IWM', 'VTV', 'TLT', 'XLV', 'XLP', 'XLE'
])
BROAD_TICKERS: List[str] = _scan_config.get("broad_tickers", [])
LONG_BULL_TICKERS: Set[str] = set(_scan_config.get("long_bull_tickers", []))
ETF_TICKERS: Set[str] = set(_scan_config.get("etf_tickers", []))
HIGH_VOL_GROWTH_TICKERS: Set[str] = set(_scan_config.get("high_vol_growth_tickers", []))

TICKER_EXCHANGE_MAP: Dict[str, str] = _ticker_metadata.get("ticker_exchange_map", {})
TICKER_INTROS: Dict[str, str] = _ticker_metadata.get("ticker_intros", {})
TICKER_RISKS: Dict[str, str] = _ticker_metadata.get("ticker_risks", {})
SECTOR_MAP: Dict[str, str] = _ticker_metadata.get("sector_map", {})
TICKER_FUNDAMENTALS: Dict[str, Any] = _ticker_metadata.get("ticker_fundamentals", {})


def normalize_symbol(symbol: Optional[str]) -> str:
    """
    Normalize stock symbol to standard display format.
    Converts variations like BRKB, BRK-B, BRK/B to standard BRK.B.

    Args:
        symbol: Input symbol string.

    Returns:
        Standardized uppercase symbol string.
    """
    if not symbol:
        return ""
    clean = str(symbol).strip().upper()
    if clean in ["BRKB", "BRK-B", "BRK/B"]:
        return "BRK.B"
    return clean


def to_yf_symbol(symbol: Optional[str]) -> str:
    """
    Convert symbol to Yahoo Finance compatible format (e.g. BRK.B -> BRK-B).

    Args:
        symbol: Input symbol.

    Returns:
        Yahoo Finance ticker string.
    """
    norm = normalize_symbol(symbol)
    return norm.replace('.', '-')


def to_display_symbol(symbol: Optional[str]) -> str:
    """
    Convert symbol to user-facing display format (e.g. BRK-B -> BRK.B).

    Args:
        symbol: Input symbol.

    Returns:
        Display symbol string.
    """
    norm = normalize_symbol(symbol)
    return norm.replace('-', '.')


def to_rh_symbol(symbol: Optional[str]) -> str:
    """
    Convert symbol to Robinhood options chain format (e.g. BRK.B -> BRKB).

    Args:
        symbol: Input symbol.

    Returns:
        Robinhood chain symbol string.
    """
    norm = normalize_symbol(symbol)
    if norm in ["BRK.B", "BRKB", "BRK-B", "BRK/B"]:
        return "BRKB"
    return norm


def is_long_bull(symbol: Optional[str]) -> bool:
    """Check if symbol is classified as a steady long bull or core index."""
    if not symbol:
        return False
    norm = normalize_symbol(symbol)
    return norm in LONG_BULL_TICKERS or str(symbol).upper() in LONG_BULL_TICKERS


def is_etf_symbol(symbol: Optional[str]) -> bool:
    """Check if symbol is an ETF fund."""
    if not symbol:
        return False
    norm = normalize_symbol(symbol)
    if norm in ETF_TICKERS or str(symbol).upper() in ETF_TICKERS:
        return True
    return norm in ['SPY', 'QQQ', 'IWM', 'VTV', 'TLT', 'XLV', 'XLP', 'XLE', 'XLU', 'ASHR', 'IBIT', 'SPYM', 'QQQM', 'CTA']


def is_high_vol_growth(symbol: Optional[str]) -> bool:
    """Check if symbol is classified as a high-volatility growth asset."""
    if not symbol:
        return False
    norm = normalize_symbol(symbol)
    return norm in HIGH_VOL_GROWTH_TICKERS or str(symbol).upper() in HIGH_VOL_GROWTH_TICKERS


def get_tradingview_url(symbol: Optional[str], exchange_hint: Optional[str] = None) -> str:
    """
    Generate the TradingView chart link for a given symbol with correct exchange prefix.

    Args:
        symbol: Stock symbol.
        exchange_hint: Optional hint for the stock exchange (NASDAQ, NYSE, AMEX).

    Returns:
        TradingView URL.
    """
    if not symbol:
        return "https://www.tradingview.com/"

    clean_sym = normalize_symbol(symbol).replace('-', '.')
    current_map = _ticker_metadata.get("ticker_exchange_map", {}) if _ticker_metadata else {}
    exch = current_map.get(clean_sym) or current_map.get(str(symbol).upper().strip()) or TICKER_EXCHANGE_MAP.get(clean_sym)

    if not exch:
        if exchange_hint:
            eh = exchange_hint.upper()
            if eh in ['NMS', 'NGM', 'NCM', 'NAS', 'NASDAQ']:
                exch = 'NASDAQ'
            elif eh in ['NYQ', 'NYSE', 'NYE']:
                exch = 'NYSE'
            elif eh in ['PCX', 'ASE', 'AMEX', 'ARCA', 'NYSEARCA']:
                exch = 'AMEX'
            else:
                exch = eh
        else:
            if clean_sym in [
                'SPY', 'IWM', 'DIA', 'GLD', 'SLV', 'USO', 'GDX', 'ASHR', 'SPYM', 'VTV',
                'XLK', 'XLF', 'XLV', 'XLE', 'XLI', 'XLY', 'XLP', 'XLRE', 'XLU', 'XLB',
                'XBI', 'KWEB', 'URA', 'CTA'
            ]:
                exch = 'AMEX'
            elif clean_sym in [
                'CMCSA', 'QQQ', 'QQQM', 'IBIT', 'TLT', 'SOXX', 'SMH', 'TSLA', 'HOOD',
                'SOFI', 'NFLX', 'MSFT', 'META', 'AMZN', 'INTU', 'SNPS', 'ISRG', 'PDD',
                'TCOM', 'UPST', 'VEEV', 'LULU', 'AAPL', 'NVDA', 'AVGO', 'AMD', 'QCOM',
                'ASML', 'AMAT', 'LRCX', 'KLAC', 'MRVL', 'TXN', 'ADI', 'CDNS', 'COST',
                'SBUX', 'PEP', 'ADBE', 'ABNB', 'CME', 'MU', 'ANET', 'CEG', 'PYPL',
                'ULTA', 'SKHY', 'CRWD', 'PANW', 'FTNT', 'DDOG', 'ZS', 'COIN'
            ]:
                exch = 'NASDAQ'
            else:
                exch = 'NYSE'

    return f"https://www.tradingview.com/symbols/{exch}-{clean_sym}/?timeframe=12M"


def atomic_write_json(filepath: str, data: Any, indent: int = 2) -> None:
    """
    Atomically write data to a JSON file using a process/thread-safe temporary file.
    Prevents file corruption or empty files during unexpected interruptions.

    Args:
        filepath: Absolute destination path.
        data: Serializable data structure.
        indent: JSON indentation (default 2).
    """
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    tmp_file = f"{filepath}.tmp_{os.getpid()}_{threading.get_ident()}"
    with _FILE_LOCK:
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
        os.replace(tmp_file, filepath)


def get_scan_parameters() -> Dict[str, Any]:
    """Retrieve full scanning and filtering parameters from scan_config.json."""
    cfg = load_json_config(SCAN_CONFIG_PATH)
    return {
        "dte_min": cfg.get("dte_min", 15),
        "dte_max": cfg.get("dte_max", 60),
        "cc_dte_max": cfg.get("cc_dte_max", 45),
        "batch_size": cfg.get("batch_size", 40),
        "long_bull_dev_threshold": cfg.get("long_bull_dev_threshold", 0.03),
        "high_vol_rp_threshold": cfg.get("high_vol_rp_threshold", 0.25),
        "oversold_drop_threshold": cfg.get("oversold_drop_threshold", -0.15),
        "oversold_dev_allowance": cfg.get("oversold_dev_allowance", 0.05),
        "oversold_rp_allowance": cfg.get("oversold_rp_allowance", 0.40),
        "low_position_put_bounds": cfg.get("low_position_put_bounds", [0.75, 0.99]),
        "normal_position_put_bounds": cfg.get("normal_position_put_bounds", [0.80, 0.98]),
        "high_vol_put_bounds": cfg.get("high_vol_put_bounds", [0.65, 0.96]),
        "cc_lower_bound_multiplier": cfg.get("cc_lower_bound_multiplier", 0.98),
        "cc_upper_bound_multiplier": cfg.get("cc_upper_bound_multiplier", 1.15),
    }
