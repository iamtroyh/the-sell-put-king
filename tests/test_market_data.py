# -*- coding: utf-8 -*-
"""Unit tests for option_quant.market_data module."""

import pandas as pd
from option_quant.market_data import (
    calculate_piotroski_f_score,
    check_eva_and_moat,
    check_is_low_position,
    check_macro_circuit_breaker,
)


def test_piotroski_f_score():
    healthy_info = {
        "returnOnAssets": 0.08,
        "freeCashflow": 5_000_000_000,
        "returnOnEquity": 0.25,
        "netIncomeToCommon": 4_000_000_000,
        "debtToEquity": 60.0,
        "currentRatio": 1.5,
        "grossMargins": 0.45,
        "revenueGrowth": 0.12,
        "operatingMargins": 0.28,
    }
    score, checks = calculate_piotroski_f_score(healthy_info)
    assert score == 9
    assert len(checks) == 9

    weak_info = {
        "returnOnAssets": -0.05,
        "freeCashflow": -1_000_000,
        "debtToEquity": 300.0,
    }
    weak_score, _ = calculate_piotroski_f_score(weak_info)
    assert weak_score == 0


def test_check_eva_and_moat():
    is_conviction, label = check_eva_and_moat("AAPL", {"returnOnEquity": 0.30, "debtToEquity": 100.0})
    assert is_conviction is True

    etf_conviction, _ = check_eva_and_moat("SPY", {})
    assert etf_conviction is True


def test_macro_circuit_breaker():
    crisis, deep, macro, reasons = check_macro_circuit_breaker()
    assert isinstance(crisis, bool)
    assert isinstance(deep, bool)
    assert isinstance(macro, bool)
    assert isinstance(reasons, list)
