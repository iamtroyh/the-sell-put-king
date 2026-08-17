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

# Risk-free rate constant and dynamic resolver
RISK_FREE_RATE = 0.05
_DYNAMIC_RFR: Optional[float] = None
_DYNAMIC_RFR_LOCK = threading.Lock()


def get_dynamic_risk_free_rate() -> float:
    """
    Dynamically fetch real-time 3-Month US Treasury Bill rate (^IRX),
    caching in memory and falling back gracefully to 0.045 / RISK_FREE_RATE.
    """
    global _DYNAMIC_RFR
    with _DYNAMIC_RFR_LOCK:
        if _DYNAMIC_RFR is not None:
            return _DYNAMIC_RFR
        try:
            import yfinance as yf
            irx = yf.Ticker("^IRX")
            hist = irx.history(period="5d")
            if not hist.empty:
                rate_pct = float(hist['Close'].iloc[-1])
                if 0.0 < rate_pct < 20.0:
                    _DYNAMIC_RFR = rate_pct / 100.0
                    return _DYNAMIC_RFR
        except Exception:
            pass
        _DYNAMIC_RFR = RISK_FREE_RATE
        return _DYNAMIC_RFR


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


def is_long_bull(symbol: Optional[str], hv: Optional[float] = None, beta: Optional[float] = None) -> bool:
    """
    Check if symbol is classified as a steady long bull or core index.
    Combines whitelist override with dynamic statistical volatility & beta profiling.
    """
    if not symbol:
        return False
    norm = normalize_symbol(symbol)
    if norm in LONG_BULL_TICKERS or str(symbol).upper() in LONG_BULL_TICKERS or is_etf_symbol(symbol):
        return True
    if norm in HIGH_VOL_GROWTH_TICKERS or str(symbol).upper() in HIGH_VOL_GROWTH_TICKERS:
        return False
    # Dynamic Statistical Profiling: Steady asset with HV <= 35%
    if hv is not None:
        try:
            val_hv = float(hv)
            if val_hv <= 35.0 and (beta is None or float(beta) <= 1.25):
                return True
            return False
        except Exception:
            pass
    return False


def is_etf_symbol(symbol: Optional[str]) -> bool:
    """Check if symbol is an ETF fund."""
    if not symbol:
        return False
    norm = normalize_symbol(symbol)
    if norm in ETF_TICKERS or str(symbol).upper() in ETF_TICKERS:
        return True
    return norm in ['SPY', 'QQQ', 'IWM', 'VTV', 'TLT', 'XLV', 'XLP', 'XLE', 'XLU', 'ASHR', 'IBIT', 'SPYM', 'QQQM', 'CTA']


def is_high_vol_growth(symbol: Optional[str], hv: Optional[float] = None, beta: Optional[float] = None) -> bool:
    """
    Check if symbol is classified as a high-volatility growth asset.
    Combines whitelist override with dynamic statistical volatility & beta profiling.
    """
    if not symbol:
        return False
    norm = normalize_symbol(symbol)
    if norm in HIGH_VOL_GROWTH_TICKERS or str(symbol).upper() in HIGH_VOL_GROWTH_TICKERS:
        return True
    if norm in LONG_BULL_TICKERS or str(symbol).upper() in LONG_BULL_TICKERS or is_etf_symbol(symbol):
        return False
    # Dynamic Statistical Profiling: Volatile asset with HV > 35% or Beta > 1.30
    if hv is not None:
        try:
            val_hv = float(hv)
            return val_hv > 35.0 or (beta is not None and float(beta) > 1.30)
        except Exception:
            pass
    return False


def get_ticker_exchange(symbol: Optional[str]) -> str:
    """
    Dynamically and reliably resolve the authentic exchange (NYSE, NASDAQ, AMEX)
    for any US symbol, with dynamic yfinance auto-discovery and automatic persistence.
    """
    if not symbol:
        return "NYSE"

    clean_sym = normalize_symbol(symbol)
    current_map = _ticker_metadata.get("ticker_exchange_map", {}) if _ticker_metadata else {}
    exch = current_map.get(clean_sym) or current_map.get(str(symbol).upper().strip()) or TICKER_EXCHANGE_MAP.get(clean_sym)
    if exch:
        return exch

    # Dynamic discovery via yfinance
    try:
        import yfinance as yf
        yf_sym = to_yf_symbol(clean_sym)
        t = yf.Ticker(yf_sym)
        raw_exch = t.fast_info.get("exchange", "")
        if raw_exch in ["NMS", "NGM", "NCM", "NAS", "NASDAQ", "NasdaqNM", "Nasdaq"]:
            discovered = "NASDAQ"
        elif raw_exch in ["PCX", "ASE", "BATS", "AMEX", "ARCA", "NYSEArca", "BATS Exchange"]:
            discovered = "AMEX"
        elif raw_exch in ["NYQ", "NYSE", "NYE"]:
            discovered = "NYSE"
        else:
            discovered = "NYSE"

        # Persist to ticker_metadata.json
        if _ticker_metadata and "ticker_exchange_map" in _ticker_metadata:
            _ticker_metadata["ticker_exchange_map"][clean_sym] = discovered
            TICKER_EXCHANGE_MAP[clean_sym] = discovered
            meta_path = os.path.join(CONFIG_DIR, "ticker_metadata.json")
            if os.path.exists(meta_path):
                atomic_write_json(meta_path, _ticker_metadata)
        return discovered
    except Exception:
        # Static fallback
        if clean_sym in ETF_TICKERS or clean_sym in [
            'SPY', 'IWM', 'DIA', 'GLD', 'SLV', 'USO', 'GDX', 'ASHR', 'SPYM', 'VTV',
            'XLK', 'XLF', 'XLV', 'XLE', 'XLI', 'XLY', 'XLP', 'XLRE', 'XLU', 'XLB',
            'XBI', 'KWEB', 'URA', 'CTA'
        ]:
            return 'AMEX'
        return 'NASDAQ' if clean_sym in [
            'CMCSA', 'QQQ', 'QQQM', 'IBIT', 'TLT', 'SOXX', 'SMH', 'TSLA', 'HOOD',
            'SOFI', 'NFLX', 'MSFT', 'META', 'AMZN', 'INTU', 'SNPS', 'ISRG', 'PDD',
            'TCOM', 'UPST', 'VEEV', 'LULU', 'AAPL', 'NVDA', 'AVGO', 'AMD', 'QCOM',
            'ASML', 'AMAT', 'LRCX', 'KLAC', 'MRVL', 'TXN', 'ADI', 'CDNS', 'COST',
            'SBUX', 'PEP', 'ADBE', 'ABNB', 'CME', 'MU', 'ANET', 'CEG', 'PYPL',
            'ULTA', 'SKHY', 'CRWD', 'PANW', 'FTNT', 'DDOG', 'ZS', 'COIN', 'WMT',
            'MARA', 'DKNG', 'FSLR', 'IDXX', 'HON', 'LIN', 'DUOL', 'GOOGL', 'BTDR'
        ] else 'NYSE'


def format_tradingview_ticker(symbol: Optional[str]) -> str:
    """Format symbol as EXACT TradingView format (e.g. NASDAQ:SKHY, NYSE:BRK.B, AMEX:KWEB)."""
    if not symbol:
        return ""
    clean_sym = normalize_symbol(symbol)
    exch = get_ticker_exchange(clean_sym)
    return f"{exch}:{clean_sym}"


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

    clean_sym = normalize_symbol(symbol)
    exch = exchange_hint if exchange_hint else get_ticker_exchange(clean_sym)
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
