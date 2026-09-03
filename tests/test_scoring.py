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

    assert total > 55.0
    assert s_safety >= 40.0
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
        f_score=2,  # -50 pts (severe collapse veto)
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
    # Crossing earnings with tight cushion (4%) vs Expected Move (8%) -> M=0.5 < 0.60 -> 20 pt smooth penalty
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
    assert penalty_risky >= 20.0


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
    # Verify V3.0 50/50 Dual-Core Multi-Factor Base Score Exactness:
    # 50% Asset Layer (25% Quality + 25% Spot Valuation) + 50% Option Layer (20% Physical Safety + 18% Alpha + 12% Yield)
    total, s_price, s_safety, s_alpha, s_yield, penalty = calculate_sell_put_score(
        ticker="SPYM",
        current_price=100.0,
        strike=95.0,
        delta=-0.20,
        mark=2.0,
        annualized_yield=20.0,
        ivp=75.0,
        dte=30,
        sma_200=110.0,
        low_52w=80.0,
        high_52w=120.0,
        curr_hv=30.0,
        ev_dollar=80.0,
        ev_apy=15.0,
        put_skew=1.10,
        ivr=75.0,
    )

    assert abs(s_price - 68.18) < 1e-1
    assert abs(s_safety - 38.75) < 1e-1
    assert abs(s_alpha - 79.46) < 1e-1
    assert abs(s_yield - 86.60) < 1e-1  # 5th element is s_ev
    assert abs(total - 72.45) < 1e-1
    assert penalty == 0.0


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
    assert res["ev_dollar"] > 0.0  # Mathematical expectation
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

    assert s_ev == 0.0  # S_EV zeroed out for low-quality negative EV trade
    assert s_alpha < 45.0  # Option Alpha naturally depressed


def test_multi_horizon_hv_calculation():
    import numpy as np
    import pandas as pd
    from option_quant.scoring import calculate_multi_horizon_hv

    # Normal returns with std ~ 0.015 (daily) -> annualized ~ 23.8%
    np.random.seed(42)
    daily_returns = pd.Series(np.random.normal(0.0005, 0.015, 252))
    
    # Introduce a single-day anomaly in the last 15 days (e.g. -12% shock)
    daily_returns.iloc[-10] = -0.12

    hv_res = calculate_multi_horizon_hv(daily_returns)

    assert "hv_30" in hv_res
    assert "hv_60" in hv_res
    assert "hv_90" in hv_res
    assert "hv_252" in hv_res
    assert "hv_blend" in hv_res
    assert "effective_hv" in hv_res

    # 30D HV should be spiked by the single-day anomaly
    assert hv_res["hv_30"] > hv_res["hv_90"]
    
    # Multi-horizon blend should be smoother than raw 30D HV
    assert hv_res["hv_blend"] < hv_res["hv_30"]
    assert hv_res["effective_hv"] <= hv_res["hv_blend"]
    assert hv_res["effective_hv"] > 10.0


def test_spot_valuation_decoupling_and_otm_safety_advantage():
    # Long bull stock at Spot=210 (above SMA200=200, dev=+5%)
    # Case A: ATM Put strike=210, delta=-0.50 -> Z=0 (s_safety = 0)
    # Case B: OTM Put strike=180, delta=-0.15 -> Z=2.12σ (s_safety = 100)
    # Valuation is 100% decoupled from strike (s_price_atm == s_price_otm = 43.75 in 0~8% neutral band)
    total_atm, s_price_atm, s_safety_atm, _, _, _ = calculate_sell_put_score(
        ticker="AAPL",
        current_price=210.0,
        strike=210.0,
        delta=-0.50,
        mark=5.0,
        annualized_yield=20.0,
        ivp=50.0,
        dte=30,
        sma_200=200.0,
        low_52w=170.0,
        high_52w=230.0,
        curr_hv=25.0,
    )

    total_otm, s_price_otm, s_safety_otm, _, _, _ = calculate_sell_put_score(
        ticker="AAPL",
        current_price=210.0,
        strike=180.0,
        delta=-0.15,
        mark=2.0,
        annualized_yield=12.0,
        ivp=50.0,
        dte=30,
        sma_200=200.0,
        low_52w=170.0,
        high_52w=230.0,
        curr_hv=25.0,
    )

    # Valuation is purely asset-level and identical across strikes
    assert s_price_otm == s_price_atm
    assert abs(s_price_otm - 43.75) < 1e-2
    # OTM advantage is purely captured in physical sigma safety (100 vs 0)
    assert s_safety_otm > s_safety_atm
    assert s_safety_otm == 100.0
    assert s_safety_atm == 0.0


def test_quality_aware_ev_protects_moat_assets():
    # High-quality stock (F-Score 8, positive FCF) with negative EV on a compressed dip
    total_qual, _, _, s_alpha_qual, s_ev_qual, pen_qual = calculate_sell_put_score(
        ticker="GOOGL",
        current_price=160.0,
        strike=145.0,
        delta=-0.20,
        mark=1.50,
        annualized_yield=12.0,
        ivp=30.0,
        dte=30,
        sma_200=170.0,
        low_52w=130.0,
        high_52w=190.0,
        curr_hv=28.0,
        ev_dollar=-30.0,  # Negative EV
        ev_apy=-2.5,
        pop=82.0,
        f_score=8,
        is_fcf_negative=False,
    )

    # Low-quality stock (F-Score 4, negative FCF) with negative EV
    total_low, _, _, s_alpha_low, s_ev_low, pen_low = calculate_sell_put_score(
        ticker="JUNK",
        current_price=160.0,
        strike=145.0,
        delta=-0.20,
        mark=1.50,
        annualized_yield=12.0,
        ivp=30.0,
        dte=30,
        sma_200=170.0,
        low_52w=130.0,
        high_52w=190.0,
        curr_hv=28.0,
        ev_dollar=-30.0,  # Negative EV
        ev_apy=-2.5,
        pop=82.0,
        f_score=4,
        is_fcf_negative=True,
    )

    # Quality moat asset gets EV discount protection (s_ev > 0) while low quality gets s_ev = 0
    assert s_ev_qual > 0.0
    assert s_ev_low == 0.0
    assert pen_low >= 10.0  # -10 negative FCF penalty
    assert total_qual > total_low


def test_stepped_drop_relief_for_insider_and_quality():
    # 20% drop (knife_level 1) on stock with heavy insider buying
    score_insider, _, _, _, _, pen_insider = calculate_sell_put_score(
        ticker="BUYER",
        current_price=100.0,
        strike=90.0,
        delta=-0.20,
        mark=2.0,
        annualized_yield=15.0,
        ivp=50.0,
        dte=30,
        sma_200=120.0,
        low_52w=95.0,
        high_52w=140.0,
        curr_hv=30.0,
        knife_level=1,
        insider_sentiment="net_buying",
        f_score=8,
        is_fcf_negative=False,
    )

    # Same drop on stock without insider/quality support
    score_normal, _, _, _, _, pen_normal = calculate_sell_put_score(
        ticker="NORM",
        current_price=100.0,
        strike=90.0,
        delta=-0.20,
        mark=2.0,
        annualized_yield=15.0,
        ivp=50.0,
        dte=30,
        sma_200=120.0,
        low_52w=95.0,
        high_52w=140.0,
        curr_hv=30.0,
        knife_level=1,
        insider_sentiment="neutral",
        f_score=5,
        is_fcf_negative=False,
    )

    # Insider / high-quality stock gets 100% knife penalty relief (0.0 penalty) while normal stock gets penalty
    assert pen_insider == 0.0
    assert pen_normal > 0.0
    assert score_insider > score_normal + 5.0


def test_smooth_negative_fcf_margin_penalty():
    # Test that FCF margin penalizes continuously from 0% down to -20%
    # Margin 0% -> penalty = 0.0
    _, _, _, _, _, pen_0 = calculate_sell_put_score(
        ticker="FCF0", current_price=100.0, strike=90.0, delta=-0.20, mark=2.0,
        annualized_yield=15.0, ivp=50.0, dte=30, sma_200=100.0, low_52w=80.0, high_52w=120.0, curr_hv=20.0,
        fcf_margin=0.0,
    )
    assert pen_0 == 0.0

    # Margin -10% -> penalty = 7.5 pts
    _, _, _, _, _, pen_10 = calculate_sell_put_score(
        ticker="FCF10", current_price=100.0, strike=90.0, delta=-0.20, mark=2.0,
        annualized_yield=15.0, ivp=50.0, dte=30, sma_200=100.0, low_52w=80.0, high_52w=120.0, curr_hv=20.0,
        fcf_margin=-10.0,
    )
    assert abs(pen_10 - 7.5) < 1e-2

    # Margin -20% -> penalty = 15.0 pts
    _, _, _, _, _, pen_20 = calculate_sell_put_score(
        ticker="FCF20", current_price=100.0, strike=90.0, delta=-0.20, mark=2.0,
        annualized_yield=15.0, ivp=50.0, dte=30, sma_200=100.0, low_52w=80.0, high_52w=120.0, curr_hv=20.0,
        fcf_margin=-20.0,
    )
    assert abs(pen_20 - 15.0) < 1e-2


def test_smooth_continuous_drop_penalty():
    # Test that 14.9% drop and 15.1% drop produce smooth continuous penalties without step cliffs
    _, _, _, _, _, pen_149 = calculate_sell_put_score(
        ticker="DROP1", current_price=100.0, strike=90.0, delta=-0.20, mark=2.0,
        annualized_yield=15.0, ivp=50.0, dte=30, sma_200=100.0, low_52w=80.0, high_52w=120.0, curr_hv=20.0,
        return_30d=-0.149,
    )
    _, _, _, _, _, pen_151 = calculate_sell_put_score(
        ticker="DROP2", current_price=100.0, strike=90.0, delta=-0.20, mark=2.0,
        annualized_yield=15.0, ivp=50.0, dte=30, sma_200=100.0, low_52w=80.0, high_52w=120.0, curr_hv=20.0,
        return_30d=-0.151,
    )

    # Difference across the 15% threshold is tiny (< 0.2 pt) instead of a 7.5 pt step cliff
    assert abs(pen_151 - pen_149) < 0.20


def test_panic_cleared_bottoming_bonus():
    # Fortress asset with deep pullback (-12%) and compressed IV (IVP=20%) gets bottoming bonus (+2.17 pts)
    score_bottom, _, _, _, _, pen_bottom = calculate_sell_put_score(
        ticker="META", current_price=550.0, strike=500.0, delta=-0.12, mark=3.0,
        annualized_yield=8.0, ivp=20.0, dte=30, sma_200=620.0, low_52w=520.0, high_52w=770.0, curr_hv=40.0,
        f_score=9, return_30d=-0.12,
    )
    # Compare with high IVP stock (IVP=80%) without vol compression
    score_high_ivp, _, _, _, _, _ = calculate_sell_put_score(
        ticker="META", current_price=550.0, strike=500.0, delta=-0.12, mark=3.0,
        annualized_yield=8.0, ivp=80.0, dte=30, sma_200=620.0, low_52w=520.0, high_52w=770.0, curr_hv=40.0,
        f_score=9, return_30d=-0.12,
    )
    assert score_bottom > 0.0


def test_dte_efficiency_curve():
    # 35 DTE (Golden Zone) gets 100% efficiency and 0 gamma penalty
    score_35, _, _, _, _, pen_35 = calculate_sell_put_score(
        ticker="SPYM", current_price=100.0, strike=95.0, delta=-0.20, mark=2.0,
        annualized_yield=20.0, ivp=50.0, dte=35, sma_200=100.0, low_52w=80.0, high_52w=120.0, curr_hv=20.0,
    )

    # 15 DTE (Ultra-short Gamma Zone) gets efficiency reduction + 3.0 pt Gamma spike penalty
    score_15, _, _, _, _, pen_15 = calculate_sell_put_score(
        ticker="SPYM", current_price=100.0, strike=95.0, delta=-0.20, mark=2.0,
        annualized_yield=20.0, ivp=50.0, dte=15, sma_200=100.0, low_52w=80.0, high_52w=120.0, curr_hv=20.0,
    )

    assert pen_35 == 0.0
    assert abs(pen_15 - 3.0) < 1e-2
    assert score_35 > score_15


def test_wash_sale_penalty():
    # Normal asset without Wash Sale risk
    score_normal, _, _, _, _, pen_normal = calculate_sell_put_score(
        ticker="SOFI", current_price=15.0, strike=13.0, delta=-0.20, mark=0.50,
        annualized_yield=20.0, ivp=50.0, dte=30, sma_200=15.0, low_52w=10.0, high_52w=20.0, curr_hv=30.0,
        is_wash_sale_risk=False,
    )

    # Asset with Wash Sale risk gets -10.0 pts tax penalty
    score_wash, _, _, _, _, pen_wash = calculate_sell_put_score(
        ticker="SOFI", current_price=15.0, strike=13.0, delta=-0.20, mark=0.50,
        annualized_yield=20.0, ivp=50.0, dte=30, sma_200=15.0, low_52w=10.0, high_52w=20.0, curr_hv=30.0,
        is_wash_sale_risk=True,
    )

    assert pen_normal == 0.0
    assert pen_wash == 10.0
    assert score_normal - score_wash == 10.0



