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
        ivp=20.0,
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

    assert penalty >= 95.0
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


def test_sell_put_derivative_enhancements():
    # Test that Max Pain, Skew, and PCR add quantitative edge
    total_base, _, s_safety_base, s_alpha_base, _, _ = calculate_sell_put_score(
        ticker="AAPL",
        current_price=215.0,
        strike=195.0,
        delta=-0.18,
        mark=3.0,
        annualized_yield=16.0,
        ivp=70.0,
        dte=35,
        sma_200=200.0,
        low_52w=170.0,
        high_52w=235.0,
        curr_hv=25.0,
    )

    total_enhanced, _, s_safety_enh, s_alpha_enh, _, _ = calculate_sell_put_score(
        ticker="AAPL",
        current_price=215.0,
        strike=195.0,
        delta=-0.18,
        mark=3.0,
        annualized_yield=16.0,
        ivp=70.0,
        dte=35,
        sma_200=200.0,
        low_52w=170.0,
        high_52w=235.0,
        curr_hv=25.0,
        ivr=65.0,
        put_skew=1.35,  # High panic skew
        max_pain=210.0,  # Strike 195 is >6% below Max Pain 210 (+4 safety)
        pcr_oi=1.55,  # Contrarian extreme fear (+3 sentiment)
    )

    assert s_alpha_enh > s_alpha_base  # S_Skew boost in Option Alpha
    assert s_safety_enh > s_safety_base  # Max Pain cushion boost
    assert total_enhanced > total_base


def test_earnings_expected_move_gatekeeper():
    # Crossing earnings with tight cushion (4%) vs Expected Move (8%) -> M=0.5 < 1.0 -> -25 pt penalty
    total_risky, _, _, _, _, penalty_risky = calculate_sell_put_score(
        ticker="NVDA",
        current_price=200.0,
        strike=192.0,  # 4% cushion
        delta=-0.28,
        mark=4.0,
        annualized_yield=22.0,
        ivp=70.0,
        dte=35,
        sma_200=180.0,
        low_52w=140.0,
        high_52w=220.0,
        curr_hv=35.0,
        is_earnings_crosser=True,
        expected_move_pct=8.0,  # 8% expected move
    )
    assert penalty_risky >= 25.0


def test_scoring_missing_data_compatibility():
    # Verify that when ALL optional parameters are None/missing/NaN, calculation runs without error
    # and strictly refuses to guess non-existent numbers
    total, s_price, s_safety, s_alpha, s_ev, penalty = calculate_sell_put_score(
        ticker="SPYM",
        current_price=100.0,
        strike=95.0,
        delta=-0.20,
        mark=1.5,
        annualized_yield=15.0,
        ivp=50.0,
        dte=30,
        sma_200=98.0,
        low_52w=85.0,
        high_52w=105.0,
        curr_hv=15.0,
        knife_level=0,
        is_fcf_negative=False,
        f_score=None,
        insider_sentiment="neutral",
        is_heavy_debt=False,
        ivr=None,
        put_skew=None,
        max_pain=None,
        pcr_oi=None,
        expected_move_pct=None,
        is_earnings_crosser=False,
    )

    import math
    assert not math.isnan(total)
    assert 0.0 <= total <= 100.0
    assert not math.isnan(s_price)
    assert not math.isnan(s_safety)
    assert not math.isnan(s_alpha)
    assert not math.isnan(s_ev)
    assert 0.0 <= s_alpha <= 100.0
    assert penalty == 0.0


def test_three_pillars_weighting_distribution():
    # Verify 50% Price + 30% Safety + 20% Option Alpha base score exactness
    # Long bull SPYM at valuation trough Dev <= 0: Price=100, Safety=100
    # s_ev = 100 * sqrt(15/20) = 86.6025, s_vol = 0.5(75) + 0.2(75) + 0.3(50) = 67.5 -> s_alpha = 0.7(86.6025) + 0.3(67.5) = 80.8718
    # Base = 0.50(100) + 0.30(100) + 0.20(80.8718) = 50 + 30 + 16.1744 = 96.17
    total, s_price, s_safety, s_alpha, _, penalty = calculate_sell_put_score(
        ticker="SPYM",
        current_price=100.0,
        strike=95.0,
        delta=-0.20,
        mark=2.0,
        annualized_yield=20.0,
        ivp=75.0,
        dte=30,
        sma_200=110.0,  # Dev = -9.09% <= 0 -> Price = 100.0, Safety = 100.0
        low_52w=80.0,
        high_52w=120.0,
        curr_hv=30.0,
        ev_dollar=80.0,
        ev_apy=15.0,
        put_skew=1.10,  # s_skew = 50.0
        ivr=75.0,
    )

    assert s_price == 100.0
    assert s_safety == 100.0
    assert abs(s_alpha - 80.87) < 1e-1
    assert abs(total - 96.17) < 1e-1


def test_option_ev_and_pop_calculation():
    from option_quant.scoring import calculate_option_ev_and_pop

    # Safe blue chip: Spot=200, Strike=185 (7.5% cushion), DTE=35, Mark=3.20, IV=0.30, HV=0.20
    res = calculate_option_ev_and_pop(
        spot=200.0,
        strike=185.0,
        dte=35,
        premium=3.20,
        iv=0.30,
        hv=0.20,
    )

    assert res["pop"] > 80.0  # Probability of profit > 80%
    assert res["ev_dollar"] > 0.0  # Positive mathematical expectation
    assert res["ev_apy"] > 0.0
    assert res["trade_sharpe"] > 0.5
    assert res["half_kelly_pct"] > 0.0


def test_ev_driven_scoring_penalizes_negative_ev():
    # Negative EV trade: High nominal APY (40%) but huge HV (80%) resulting in negative EV
    total, s_price, s_safety, s_alpha, s_ev, penalty = calculate_sell_put_score(
        ticker="TRAP",
        current_price=50.0,
        strike=45.0,
        delta=-0.25,
        mark=3.0,
        annualized_yield=40.0,
        ivp=80.0,
        dte=30,
        sma_200=48.0,
        low_52w=40.0,
        high_52w=60.0,
        curr_hv=75.0,
        ev_dollar=-150.0,  # Negative EV
        ev_apy=-12.0,
        pop=65.0,
    )

    assert s_ev == 0.0  # S_EV zeroed out
    assert penalty >= 15.0  # Mathematical negative expectation penalty triggered
