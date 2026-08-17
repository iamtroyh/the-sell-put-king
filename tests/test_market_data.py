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


def test_black_scholes_iv_solver():
    from option_quant.marketdata_client import compute_black_scholes_iv
    # Test ATM Put: Spot=100, Strike=100, DTE=30, Price=3.0, r=0.05
    iv = compute_black_scholes_iv(price=3.0, strike=100.0, dte=30, spot=100.0, r=0.05, opt_type="put")
    assert iv is not None
    assert 0.20 <= iv <= 0.35


def test_true_ivp_and_ivr_calculation():
    from option_quant.marketdata_client import get_true_ivp_and_ivr
    res = get_true_ivp_and_ivr("AAPL")
    assert isinstance(res, dict)
    assert "symbol" in res
    assert "has_true_iv" in res
    assert "ivp" in res
    assert "ivr" in res
    assert "composite_s_iv" in res
    assert 0.0 <= res["ivp"] <= 100.0
    assert 0.0 <= res["ivr"] <= 100.0


def test_derivative_metrics_computation():
    from option_quant.marketdata_client import (
        compute_max_pain,
        compute_volatility_skew,
        compute_pcr,
        compute_expected_earnings_move,
    )

    mock_chain = {
        "s": "ok",
        "underlyingPrice": [100.0] * 6,
        "strike": [90.0, 100.0, 110.0, 90.0, 100.0, 110.0],
        "side": ["put", "put", "put", "call", "call", "call"],
        "openInterest": [500, 1000, 200, 150, 1200, 600],
        "volume": [50, 100, 20, 15, 120, 60],
        "delta": [-0.15, -0.50, -0.85, 0.85, 0.50, 0.15],
        "iv": [0.28, 0.25, 0.22, 0.22, 0.24, 0.20],
        "mid": [1.2, 3.5, 10.5, 10.5, 3.8, 1.1],
    }

    max_pain = compute_max_pain(mock_chain)
    assert max_pain == 100.0

    skew = compute_volatility_skew(mock_chain)
    assert skew is not None
    assert skew > 1.0  # 25D Put IV (0.28) / 25D Call IV (0.20) = 1.4

    pcr = compute_pcr(mock_chain)
    assert pcr["pcr_oi"] > 0.5

    exp_move = compute_expected_earnings_move(mock_chain)
    assert exp_move is not None
    assert exp_move > 0.0
