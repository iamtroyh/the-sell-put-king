# -*- coding: utf-8 -*-
"""Unit tests for option_quant.config module."""

import os
import tempfile
import pytest

from option_quant.config import (
    atomic_write_json,
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


def test_normalize_symbol():
    assert normalize_symbol("BRKB") == "BRK.B"
    assert normalize_symbol("BRK-B") == "BRK.B"
    assert normalize_symbol("BRK/B") == "BRK.B"
    assert normalize_symbol("  aapl  ") == "AAPL"
    assert normalize_symbol("") == ""
    assert normalize_symbol(None) == ""


def test_symbol_conversions():
    assert to_yf_symbol("BRK.B") == "BRK-B"
    assert to_yf_symbol("AAPL") == "AAPL"

    assert to_display_symbol("BRK-B") == "BRK.B"
    assert to_display_symbol("AAPL") == "AAPL"

    assert to_rh_symbol("BRK.B") == "BRKB"
    assert to_rh_symbol("BRK-B") == "BRKB"
    assert to_rh_symbol("NVDA") == "NVDA"


def test_classification():
    assert is_long_bull("BRK.B") is True
    assert is_long_bull("AAPL") is True
    assert is_etf_symbol("SPY") is True
    assert is_etf_symbol("QQQM") is True
    assert is_etf_symbol("IBIT") is True
    assert is_etf_symbol("AAPL") is False


def test_mask_account_id():
    assert mask_account_id("123456789012") == "1234******12"
    assert mask_account_id("123") == "****"
    assert mask_account_id("") == "****"


def test_tradingview_url():
    url_aapl = get_tradingview_url("AAPL")
    assert "NASDAQ-AAPL" in url_aapl
    url_spy = get_tradingview_url("SPY")
    assert "AMEX-SPY" in url_spy


def test_atomic_write_json():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        data = {"status": "ok", "value": 42}
        atomic_write_json(tmp_path, data)
        loaded = load_json_config(tmp_path)
        assert loaded == data
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
