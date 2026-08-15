# -*- coding: utf-8 -*-
"""Unit tests for option_quant.scoring module."""

import pytest
from option_quant.scoring import (
    calculate_apy,
    calculate_call_delta,
    calculate_covered_call_score,
    calculate_put_delta,
    calculate_sell_put_score,
    norm_cdf,
)


def test_norm_cdf():
    assert abs(norm_cdf(0.0) - 0.5) < 1e-5
    assert norm_cdf(10.0) > 0.999
    assert norm_cdf(-10.0) < 0.001


def test_delta_calculation():
    # ATM Put Delta should be approximately -0.5
    put_d = calculate_put_delta(S=100.0, K=100.0, t=0.1, r=0.05, sigma=0.20)
    assert -0.6 < put_d < -0.4

    # ATM Call Delta should be approximately +0.5
    call_d = calculate_call_delta(S=100.0, K=100.0, t=0.1, r=0.05, sigma=0.20)
    assert 0.4 < call_d < 0.6

    # OTM Put Delta should be small negative (-0.25)
    otm_put_d = calculate_put_delta(S=100.0, K=90.0, t=0.1, r=0.05, sigma=0.20)
    assert -0.35 < otm_put_d < 0.0


def test_calculate_apy():
    res = calculate_apy(dte=36.5, strike=100.0, premium=2.0)
    assert abs(res["period_return"] - 2.0) < 1e-5
    assert abs(res["simple_apy"] - 20.0) < 1e-5
    assert res["compound_apy"] > 20.0
    assert res["net_simple_apy"] > 20.0

    with pytest.raises(ValueError):
        calculate_apy(dte=0, strike=100.0, premium=1.0)
    with pytest.raises(ValueError):
        calculate_apy(dte=30, strike=-10.0, premium=1.0)


def test_sell_put_scoring():
    # Healthy, oversold long-bull stock
    total, s_price, s_safety, s_yield, s_iv, penalty = calculate_sell_put_score(
        ticker="AAPL",
        current_price=200.0,
        strike=190.0,
        delta=-0.20,
        mark=3.5,
        annualized_yield=18.0,
        ivp=70.0,
        dte=35,
        sma_200=210.0,
        low_52w=170.0,
        high_52w=235.0,
        curr_hv=25.0,
        knife_level=0,
        is_fcf_negative=False,
        f_score=8,
        insider_sentiment="neutral",
    )

    assert total > 60.0
    assert s_safety >= 80.0
    assert penalty == 0.0


def test_sell_put_trend_and_fundamental_penalties():
    # Deteriorated stock with falling knife and negative FCF
    total, _, _, _, _, penalty = calculate_sell_put_score(
        ticker="XYZ",
        current_price=50.0,
        strike=45.0,
        delta=-0.25,
        mark=1.0,
        annualized_yield=15.0,
        ivp=20.0,  # Low IV penalty
        dte=30,
        sma_200=70.0,
        low_52w=48.0,
        high_52w=90.0,
        curr_hv=40.0,
        knife_level=2,  # -30 pts
        is_fcf_negative=True,  # -10 pts
        f_score=3,  # -50 pts (bad financials veto)
        insider_sentiment="heavy_selling",  # -5 pts
    )

    assert penalty >= 100.0
    assert total == 0.0  # Floor at 0.0


def test_covered_call_scoring():
    total, s_yield, s_safety, s_iv, s_price = calculate_covered_call_score(
        ticker="AAPL",
        current_price=200.0,
        avg_cost=195.0,
        strike=210.0,
        delta=0.25,
        mark=2.5,
        annualized_yield=12.0,
        ivp=60.0,
        dte=30,
        sma_200=190.0,
        low_52w=160.0,
        high_52w=215.0,
    )
    assert total > 50.0
    assert s_safety == 75.0
