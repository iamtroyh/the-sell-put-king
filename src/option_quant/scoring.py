# -*- coding: utf-8 -*-
"""
Option Quantitative Scoring Engine
==================================
Multi-factor scoring models for Sell Put (Cash Secured Put) and Covered Call
strategies, Black-Scholes Delta approximations, APY calculators, liquidity
gatekeeper validation, and earnings smart buffer defense.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from option_quant.config import (
    CYCLICAL_MACRO_ETF_TICKERS,
    RISK_FREE_RATE,
    SECTOR_MAP,
    is_etf_symbol,
    is_high_vol_growth,
    is_long_bull,
    normalize_symbol,
)
from option_quant.market_data import calculate_piotroski_f_score, check_eva_and_moat


def norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def calculate_put_delta(S: float, K: float, t: float, r: float = RISK_FREE_RATE, sigma: float = 0.30) -> float:
    """
    Calculate Black-Scholes European Put Delta.

    Args:
        S: Spot price.
        K: Strike price.
        t: Time to expiration in years (DTE / 365).
        r: Risk-free interest rate (default 0.05).
        sigma: Implied volatility (decimal, e.g. 0.30 for 30%).

    Returns:
        Put Delta (negative value between -1.0 and 0.0).
    """
    if t <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return -0.5 if S <= K else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * t) / (sigma * math.sqrt(t))
    return norm_cdf(d1) - 1.0


def calculate_call_delta(S: float, K: float, t: float, r: float = RISK_FREE_RATE, sigma: float = 0.30) -> float:
    """
    Calculate Black-Scholes European Call Delta.

    Args:
        S: Spot price.
        K: Strike price.
        t: Time to expiration in years (DTE / 365).
        r: Risk-free interest rate.
        sigma: Implied volatility.

    Returns:
        Call Delta (positive value between 0.0 and 1.0).
    """
    if t <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.5 if S >= K else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * t) / (sigma * math.sqrt(t))
    return norm_cdf(d1)


def calculate_apy(dte: float, strike: float, premium: float) -> Dict[str, float]:
    """
    Calculate simple and compounded APY for an option contract.

    Args:
        dte: Days to expiration (> 0).
        strike: Strike price (> 0).
        premium: Option premium / mark price (> 0).

    Returns:
        Dictionary with period_return, simple_apy, compound_apy, and net_simple_apy.
    """
    if dte <= 0:
        raise ValueError("Days to expiration (DTE) must be greater than 0")
    if strike <= 0:
        raise ValueError("Strike price must be greater than 0")
    if premium < 0:
        raise ValueError("Option premium cannot be negative")

    period_return = (premium / strike) * 100.0
    simple_apy = period_return * (365.0 / dte)
    compound_apy = (((1.0 + premium / strike) ** (365.0 / dte)) - 1.0) * 100.0 if (1.0 + premium / strike) > 0 else simple_apy
    net_collateral = strike - premium
    net_simple_apy = (premium / net_collateral) * (365.0 / dte) * 100.0 if net_collateral > 0 else simple_apy

    return {
        "period_return": period_return,
        "simple_apy": simple_apy,
        "compound_apy": compound_apy,
        "net_simple_apy": net_simple_apy,
    }


def calculate_multi_horizon_hv(
    returns: Any,
    min_periods: int = 15,
) -> Dict[str, float]:
    """
    Calculate Multi-Horizon Realized Historical Volatility (HV) and weighted blend.

    Eliminates single-month black swan gap distortions (e.g. post-earnings jumps or short-term anomalies)
    by smoothly blending 30-day, 60-day, 90-day, and 252-day annualized realized volatilities.

    Multi-Horizon Weighting:
        - 30-Day  (Short-term Horizon, ~1.5 Months): 50% (0.50)
        - 60-Day  (Medium Horizon, ~3 Months):      30% (0.30)
        - 90-Day  (Quarterly+ Horizon, ~4.5 Months): 20% (0.20)

    Effective HV Anchor:
        effective_hv = min(hv_blend, hv_252)

    Args:
        returns: Daily log returns (pandas Series, array-like, or DataFrame column).
        min_periods: Minimum valid return periods required.

    Returns:
        Dict containing:
            - 'hv_30': 30-day annualized realized volatility (%)
            - 'hv_60': 60-day annualized realized volatility (%)
            - 'hv_90': 90-day annualized realized volatility (%)
            - 'hv_252': 252-day (full year) annualized realized volatility (%)
            - 'hv_blend': Weighted multi-horizon blend volatility (%)
            - 'effective_hv': Final robust effective volatility (%)
    """
    import pandas as pd
    if returns is None:
        return {
            "hv_30": 30.0,
            "hv_60": 30.0,
            "hv_90": 30.0,
            "hv_252": 30.0,
            "hv_blend": 30.0,
            "effective_hv": 30.0,
        }

    if not isinstance(returns, pd.Series):
        s = pd.Series(returns).dropna()
    else:
        s = returns.dropna()

    n = len(s)
    if n < min_periods:
        fallback = 30.0
        return {
            "hv_30": fallback,
            "hv_60": fallback,
            "hv_90": fallback,
            "hv_252": fallback,
            "hv_blend": fallback,
            "effective_hv": fallback,
        }

    # Annualization factor: sqrt(252) * 100%
    ann_factor = math.sqrt(252.0) * 100.0

    # 1. 30-Day Rolling HV (or available sample)
    hv_30_s = s.iloc[-30:] if n >= 30 else s
    hv_30 = float(hv_30_s.std() * ann_factor) if len(hv_30_s) > 1 else 30.0

    # 2. 60-Day Rolling HV
    hv_60_s = s.iloc[-60:] if n >= 60 else s
    hv_60 = float(hv_60_s.std() * ann_factor) if len(hv_60_s) > 1 else hv_30

    # 3. 90-Day Rolling HV
    hv_90_s = s.iloc[-90:] if n >= 90 else s
    hv_90 = float(hv_90_s.std() * ann_factor) if len(hv_90_s) > 1 else hv_60

    # 4. 252-Day (Full year) Baseline HV
    hv_252_s = s.iloc[-252:] if n >= 252 else s
    hv_252 = float(hv_252_s.std() * ann_factor) if len(hv_252_s) > 1 else hv_90

    # 5. Multi-Horizon Smooth Weighted Blend
    if n >= 90:
        hv_blend = 0.50 * hv_30 + 0.30 * hv_60 + 0.20 * hv_90
    elif n >= 60:
        hv_blend = 0.60 * hv_30 + 0.40 * hv_60
    else:
        hv_blend = hv_30

    # 6. Effective HV (Anchored by long-term 252-day ceiling if valid)
    if hv_blend > 0 and hv_252 > 0:
        effective_hv = min(hv_blend, hv_252)
    else:
        effective_hv = hv_blend if hv_blend > 0 else 30.0

    return {
        "hv_30": round(hv_30, 2),
        "hv_60": round(hv_60, 2),
        "hv_90": round(hv_90, 2),
        "hv_252": round(hv_252, 2),
        "hv_blend": round(hv_blend, 2),
        "effective_hv": round(effective_hv, 2),
    }


def calculate_option_ev_and_pop(
    spot: float,
    strike: float,
    dte: int,
    premium: float,
    iv: float,
    hv: float,
    r: float = RISK_FREE_RATE,
) -> Dict[str, float]:
    """
    Calculate quantitative Probability of Profit (POP), Expected Value (EV),
    EV-adjusted Annualized APY, Trade Sharpe, and Kelly Fraction under lognormal distribution.

    Args:
        spot: Current spot price.
        strike: Option strike price.
        dte: Days to expiration.
        premium: Option premium / mark.
        iv: Implied volatility (decimal, e.g. 0.30).
        hv: Realized historical volatility (decimal, e.g. 0.22).
        r: Risk-free interest rate (default 0.05).

    Returns:
        Dict containing pop, ev_dollar, ev_apy, trade_sharpe, fair_put, breakeven, half_kelly_pct.
    """
    if spot <= 0 or strike <= 0 or dte <= 0:
        return {
            "pop": 50.0,
            "ev_dollar": 0.0,
            "ev_apy": 0.0,
            "trade_sharpe": 0.0,
            "fair_put": 0.0,
            "breakeven": strike,
            "half_kelly_pct": 0.0,
        }

    t = max(1, dte) / 365.0
    p = max(0.01, premium)
    s_be = strike - p  # Break-even price
    
    # Forward-Looking Damped Volatility Estimator:
    # 1. Base on realized HV (historical baseline)
    # 2. Bound sigma to at most 1.15x IV when IV has compressed below HV post-drop (panic cleared).
    #    This eliminates backward-looking drop spike distortion while preserving authentic downside tail risk.
    raw_sigma = hv if hv > 0 else (iv if iv > 0 else 0.25)
    if iv > 0:
        sigma = min(raw_sigma, 1.15 * iv)
    else:
        sigma = raw_sigma
    sigma = max(0.08, sigma)

    vol_t = sigma * math.sqrt(t)

    # 1. POP calculation (Cumulative probability of spot ending above break-even S_BE)
    if s_be > 0 and vol_t > 0:
        d_be = (math.log(spot / s_be) + (r - 0.5 * sigma ** 2) * t) / vol_t
        pop = norm_cdf(d_be) * 100.0
    else:
        pop = 50.0
    pop = float(np.clip(pop, 5.0, 99.5))

    # 2. Black-Scholes Put fair value under realized HV
    if vol_t > 0:
        d1 = (math.log(spot / strike) + (r + 0.5 * sigma ** 2) * t) / vol_t
        d2 = d1 - vol_t
        fair_put = strike * math.exp(-r * t) * norm_cdf(-d2) - spot * norm_cdf(-d1)
    else:
        fair_put = max(0.0, strike - spot)

    # 3. Pure EV in dollars per contract (100 shares)
    ev_dollar = 100.0 * (p - fair_put)

    # 4. EV APY (Annualized Expected Return on Collateral)
    net_collateral = max(100.0, (strike - p) * 100.0)
    ev_apy = (ev_dollar / net_collateral) * (365.0 / max(1, dte)) * 100.0

    # 5. Downside risk & Trade Sharpe ratio
    downside_risk = max(1.0, fair_put * 100.0)
    trade_sharpe = float(np.clip(max(0.0, ev_dollar) / downside_risk, 0.0, 10.0))

    # 6. Kelly position sizing fraction for options
    if ev_dollar > 0 and fair_put > 0:
        win_rate = pop / 100.0
        loss_rate = 1.0 - win_rate
        avg_win = p
        avg_loss = max(0.01, fair_put)
        b_ratio = avg_win / avg_loss
        kelly_f = max(0.0, (win_rate * b_ratio - loss_rate) / b_ratio) if b_ratio > 0 else 0.0
        half_kelly_pct = float(np.clip(kelly_f * 0.5 * 100.0, 0.0, 25.0))
    else:
        half_kelly_pct = 0.0

    return {
        "pop": round(pop, 1),
        "ev_dollar": round(ev_dollar, 2),
        "ev_apy": round(ev_apy, 2),
        "trade_sharpe": round(trade_sharpe, 2),
        "fair_put": round(fair_put, 2),
        "breakeven": round(s_be, 2),
        "half_kelly_pct": round(half_kelly_pct, 1),
    }


def calculate_sell_put_score(
    ticker: str,
    current_price: float,
    strike: float,
    delta: float,
    mark: float,
    annualized_yield: float,
    ivp: float,
    dte: int,
    sma_200: float,
    low_52w: float,
    high_52w: float,
    curr_hv: float,
    knife_level: int = 0,
    is_fcf_negative: bool = False,
    f_score: Optional[int] = None,
    insider_sentiment: str = "neutral",
    is_heavy_debt: bool = False,
    ivr: Optional[float] = None,
    put_skew: Optional[float] = None,
    max_pain: Optional[float] = None,
    pcr_oi: Optional[float] = None,
    expected_move_pct: Optional[float] = None,
    is_earnings_crosser: bool = False,
    ev_apy: Optional[float] = None,
    ev_dollar: Optional[float] = None,
    pop: Optional[float] = None,
    fcf_margin: Optional[float] = None,
    return_30d: Optional[float] = None,
    is_wash_sale_risk: bool = False,
) -> Tuple[float, float, float, float, float, float]:
    """
    Calculate the Institutional Multi-Factor Quantitative Score for Sell Put (0-100 scale).

    Formula:
        Total Score = 0.40 * S_Price + 0.30 * S_Safety + 0.30 * S_OptionAlpha - Trend_Penalty + Bonuses

    Returns:
        (total_score, s_price, s_safety, s_yield, s_iv, trend_penalty)
    """
    # 0. Defensive input sanitization
    c_price = float(current_price) if current_price is not None and not np.isnan(float(current_price)) else 100.0
    c_strike = float(strike) if strike is not None and not np.isnan(float(strike)) else c_price
    c_delta = float(delta) if delta is not None and not np.isnan(float(delta)) else -0.20
    c_yield = float(annualized_yield) if annualized_yield is not None and not np.isnan(float(annualized_yield)) else 0.0
    c_hv = float(curr_hv) if curr_hv is not None and not np.isnan(float(curr_hv)) else 20.0
    safe_ivp = float(ivp) if ivp is not None and not np.isnan(float(ivp)) else 50.0
    c_dte = max(1, int(dte)) if dte is not None else 30

    # DTE 30~45d Sweet Spot Efficiency Convex Curve:
    # 28 <= DTE <= 45: Golden Harvesting Zone (1.00x full efficiency)
    # DTE < 28: Ultra-short Gamma risk zone (smooth convex reduction down to 0.82 at DTE=15)
    # DTE > 45: Capital lockup zone (smooth linear reduction down to 0.90 at DTE=60)
    if 28 <= c_dte <= 45:
        dte_eff = 1.00
    elif c_dte < 28:
        dte_eff = 1.00 - (((28 - c_dte) / 13.0) ** 1.2) * 0.18
    else:
        dte_eff = max(0.85, 1.00 - ((c_dte - 45) / 15.0) * 0.10)

    c_yield = c_yield * dte_eff

    trend_penalty = 0.0
    if c_dte < 20:
        # Smooth Gamma spike penalty for ultra-short expirations (up to 3.0 pts at DTE=15)
        trend_penalty += ((20 - c_dte) / 5.0) * 3.0

    if is_wash_sale_risk:
        # Wash Sale Tax Loss Disallowance Penalty (10.0 pts)
        trend_penalty += 10.0

    is_etf = is_etf_symbol(ticker)
    is_high_quality = is_etf or (f_score is not None and f_score >= 7 and not is_fcf_negative) or (insider_sentiment == "net_buying")
    is_moderate_quality = (f_score is not None and f_score >= 5 and not is_fcf_negative)

    # 1. Option Alpha & Mathematical Expectation Factor (S_OptionAlpha - 30% Weight)
    # Blends 70% Pure EV APY (Square-Root Smooth Saturation Mapping) + 30% Volatility/Skew Structure
    if ev_apy is not None and not np.isnan(float(ev_apy)):
        valid_ev_apy = float(ev_apy) * dte_eff
        valid_ev_dollar = float(ev_dollar) if ev_dollar is not None and not np.isnan(float(ev_dollar)) else 0.0
        if valid_ev_dollar <= 0.0:
            if is_high_quality:
                # Quality moat assets: In a vol-compressed dip, assignment is equity accumulation, not a cash loss
                s_ev = min(60.0, max(15.0, 50.0 * math.sqrt(max(0.01, c_yield) / 20.0)))
            elif is_moderate_quality:
                # Moderate quality with positive cash flow: mild assignment discount value
                s_ev = min(40.0, max(10.0, 35.0 * math.sqrt(max(0.01, c_yield) / 20.0)))
            else:
                s_ev = 0.0
            # NOTE: Eliminated external trend_penalty += 15.0 double penalty.
            # Compressed EV naturally yields low s_ev (0~15) without artificial double-counting.
        else:
            # Square-root smooth saturation mapping: sqrt(EV_APY / 20.0%) * 100
            s_ev = min(100.0, max(0.0, 100.0 * math.sqrt(max(0.0, valid_ev_apy) / 20.0)))
    else:
        hv_factor = max(10.0, c_hv) / 100.0
        adj_annualized_yield = c_yield / (1.0 + 1.5 * hv_factor)
        s_ev = min(100.0, max(0.0, 100.0 * math.sqrt(max(0.0, adj_annualized_yield) / 20.0)))

    # Volatility / Skew sub-component (S_Vol)
    if put_skew is not None and put_skew > 0 and not np.isnan(float(put_skew)):
        s_skew = float(np.clip(50.0 + (float(put_skew) - 1.10) * 200.0, 0.0, 100.0))
    else:
        s_skew = None

    valid_ivr = float(ivr) if (ivr is not None and not np.isnan(float(ivr))) else None

    if valid_ivr is not None and s_skew is not None:
        s_vol = float(np.clip(0.50 * safe_ivp + 0.20 * valid_ivr + 0.30 * s_skew, 0.0, 100.0))
    elif valid_ivr is not None:
        s_vol = float(np.clip(0.70 * safe_ivp + 0.30 * valid_ivr, 0.0, 100.0))
    elif s_skew is not None:
        s_vol = float(np.clip(0.70 * safe_ivp + 0.30 * s_skew, 0.0, 100.0))
    else:
        s_vol = float(np.clip(safe_ivp, 0.0, 100.0))

    # Unified Option Alpha Factor
    s_option_alpha = float(np.clip(0.70 * s_ev + 0.30 * s_vol, 0.0, 100.0))

    # 2. Base Safety & Price Factors (S_Price - 40%, S_Safety - 30%, S_OptionAlpha - 30%)
    # Net Acquisition Basis = Strike - Premium (Actual net cost if assigned)
    net_basis = (c_strike - mark) if (mark is not None and mark > 0) else c_strike
    eval_price = min(c_price, net_basis)  # Reward OTM strike & premium discount

    base_safety = (1.0 - abs(c_delta)) * 100.0

    # ==================== Dual-Anchor Max-Discount Valuation Engine ====================
    # Simultaneously evaluates both Long-Cycle 200 SMA Deviation and 52-Week High-Low Relative Position,
    # fusing the maximum advantage discount to eliminate single-indicator blind spots (e.g. post-spike drops & bottom lag).

    # Anchor 1: 200-day Moving Average Deviation
    s_sma = float(sma_200) if sma_200 is not None and not np.isnan(float(sma_200)) else c_price
    dev = (eval_price - s_sma) / s_sma if s_sma > 0 else 0.0
    spot_dev = (c_price - s_sma) / s_sma if s_sma > 0 else 0.0

    if dev <= 0.00:
        s_price_sma = 50.0 + min(50.0, (abs(dev) / 0.35) * 50.0)
    else:
        s_price_sma = max(0.0, 50.0 - (dev / 0.30) * 50.0)

    if spot_dev <= 0.00:
        val_safety_bonus_sma = min(10.0, abs(spot_dev) * 50.0)
    elif spot_dev <= 0.05:
        val_safety_bonus_sma = max(0.0, (0.05 - spot_dev) * 200.0)
    else:
        val_safety_bonus_sma = 0.0

    # Anchor 2: 52-Week High-Low Relative Position (RP)
    s_low = float(low_52w) if low_52w is not None and not np.isnan(float(low_52w)) else c_price * 0.8
    s_high = float(high_52w) if high_52w is not None and not np.isnan(float(high_52w)) else c_price * 1.2
    rp = (eval_price - s_low) / (s_high - s_low) if (s_high - s_low) > 0 else 0.5
    spot_rp = (c_price - s_low) / (s_high - s_low) if (s_high - s_low) > 0 else 0.5

    if rp <= 0.50:
        s_price_rp = 50.0 + min(50.0, ((0.50 - rp) / 0.60) * 50.0)
    else:
        s_price_rp = max(0.0, 50.0 - ((rp - 0.50) / 0.50) * 50.0)

    if spot_rp <= 0.20:
        val_safety_bonus_rp = min(10.0, (0.20 - spot_rp) * 50.0)
    elif spot_rp <= 0.35:
        val_safety_bonus_rp = max(0.0, (0.35 - spot_rp) / 0.15 * 10.0)
    else:
        val_safety_bonus_rp = 0.0

    # Dual-Anchor Fusion: Maximize valuation & safety edge across both 200 SMA and 52w Range
    s_price = float(max(s_price_sma, s_price_rp))
    val_safety_bonus = float(max(val_safety_bonus_sma, val_safety_bonus_rp))
    s_safety = float(np.clip(base_safety + val_safety_bonus, 0.0, 100.0))

    # Max Pain gravitational adjustment (continuous smooth ramp between -5% and +5% deviation)
    if max_pain is not None and max_pain > 0 and not np.isnan(float(max_pain)) and c_price > 0:
        d_pain = (float(max_pain) - c_strike) / c_price * 100.0
        delta_pain = float(np.clip(d_pain / 5.0 * 4.0, -4.0, 4.0))
        s_safety = float(np.clip(s_safety + delta_pain, 0.0, 100.0))

    # Three-Pillars Base Score: 40% Price + 30% Safety + 30% Option Alpha
    base_score = 0.40 * s_price + 0.30 * s_safety + 0.30 * s_option_alpha

    # 3. Continuous Free Cash Flow (FCF) Margin Penalty
    fcf_penalty = 0.0
    if not is_etf:
        if fcf_margin is not None and not np.isnan(float(fcf_margin)):
            f_margin = float(fcf_margin)
            if f_margin < 0.0:
                m_pct = abs(f_margin) * 100.0 if abs(f_margin) <= 1.0 else abs(f_margin)
                # Smooth continuous linear ramp: from 0% loss to -20% loss linearly scales 0 to 15.0 pts
                fcf_penalty = min(15.0, (m_pct / 20.0) * 15.0)
        elif is_fcf_negative:
            fcf_penalty = 10.0
    trend_penalty += fcf_penalty

    # 4. Smart Drop Classifier & Continuous Falling Knife Defense
    contrarian_gold_bonus = 0.0
    is_toxic_knife = (
        (fcf_penalty >= 7.5)
        or (f_score is not None and f_score <= 3)
        or (insider_sentiment == "heavy_selling")
    )
    is_contrarian_candidate = is_etf or (
        (f_score is not None and f_score >= 7 and not is_toxic_knife)
        or (insider_sentiment == "net_buying")
    )

    # Resolve 30d drop percentage: prefer explicit return_30d if provided, else infer from knife_level
    if return_30d is not None and not np.isnan(float(return_30d)):
        raw_ret = float(return_30d)
        drop_pct = abs(raw_ret * 100.0) if abs(raw_ret) <= 1.0 else abs(raw_ret)
        is_negative_return = raw_ret < 0.0
    elif knife_level > 0:
        is_negative_return = True
        drop_pct = 36.0 if knife_level == 3 else (26.0 if knife_level == 2 else 16.0)
    else:
        is_negative_return = False
        drop_pct = 0.0

    if is_negative_return:
        black_swan_threshold = 22.0 if is_etf else 35.0
        if drop_pct >= black_swan_threshold:
            # ⛔ Black Swan Drop Circuit Breaker (>35% stock / >22% ETF): 50 pt veto
            trend_penalty += 50.0
        elif drop_pct > 10.0:
            if is_contrarian_candidate and not is_toxic_knife:
                # 🟢 Contrarian Golden Pit: 100% exempt from knife penalty + continuous smooth golden pit reward (up to +4.0 pts)
                contrarian_gold_bonus = min(4.0, ((drop_pct - 10.0) / 15.0) * 4.0)
            elif is_toxic_knife:
                # 🔴 Toxic Falling Knife: steep non-linear quadratic penalty for fundamentally deteriorating assets
                toxic_mult = 1.3 if not is_etf else 1.0
                trend_penalty += min(
                    30.0,
                    ((drop_pct - 10.0) / (black_swan_threshold - 10.0)) ** 1.3 * 30.0 * toxic_mult,
                )
            else:
                # 🟡 Pure Technical Normal Pullback: smooth continuous quadratic ramp (no 14.9% vs 15.1% step cliff)
                norm_mult = 1.0 if not is_etf else 0.7
                trend_penalty += min(
                    15.0,
                    ((drop_pct - 10.0) / (black_swan_threshold - 10.0)) ** 1.2 * 15.0 * norm_mult,
                )

    # Piotroski F-Score Multi-Tier Smooth Health Ladder
    f_score_bonus = 0.0
    if f_score is not None and not is_etf:
        try:
            f_val = int(f_score)
            if f_val <= 2:
                trend_penalty += 100.0  # Collapse / severe distress veto (hard elimination)
            elif f_val == 3:
                trend_penalty += 20.0  # High financial risk alert
            elif f_val == 4:
                trend_penalty += 5.0   # Sub-optimal health
            elif f_val == 5:
                pass                   # Neutral baseline
            elif f_val == 6:
                f_score_bonus = 2.5    # Good financial health
            elif f_val == 7:
                f_score_bonus = 5.0    # Fortress quality
            elif f_val >= 8:
                f_score_bonus = 7.0    # Supreme monopoly fortress quality
        except (ValueError, TypeError):
            pass

    insider_bonus = 0.0
    if not is_etf:
        if insider_sentiment == "heavy_selling":
            trend_penalty += 5.0
        elif insider_sentiment == "net_buying":
            insider_bonus = 5.0

    # Contrarian Sentiment (PCR) smooth continuous ramp
    pcr_bonus = 0.0
    if pcr_oi is not None and pcr_oi > 0 and not np.isnan(float(pcr_oi)):
        pcr_val = float(pcr_oi)
        if pcr_val >= 0.95:
            # Fear / bottoming bonus: smooth ramp up to +3.0 pts at PCR >= 1.55
            pcr_bonus = min(3.0, (pcr_val - 0.95) / 0.60 * 3.0)
        elif pcr_val <= 0.70:
            # Euphoria penalty: smooth ramp up to -3.0 pts at PCR <= 0.40
            trend_penalty += min(3.0, (0.70 - pcr_val) / 0.30 * 3.0)

    # Earnings Expected Move Gatekeeper (Continuous Smooth Ramp)
    earnings_safety_bonus = 0.0
    if is_earnings_crosser and expected_move_pct is not None and expected_move_pct > 0 and not np.isnan(float(expected_move_pct)) and c_price > 0:
        cushion_pct = (c_price - c_strike) / c_price * 100.0
        m_earnings = cushion_pct / float(expected_move_pct)
        if m_earnings < 0.60:
            trend_penalty += 20.0  # Deep inside earnings expected move
        elif m_earnings < 1.0:
            # Smooth linear transition from 15 pts at m=0.60 down to 5 pts at m=1.00
            trend_penalty += 5.0 + 10.0 * (1.0 - (m_earnings - 0.60) / 0.40)
        elif m_earnings >= 1.50:
            earnings_safety_bonus = 3.0  # Mathematically deep beyond 1.5-sigma jump

    # Extreme Debt continuous smooth ramp (Sector-Adapted & Cash Flow Protected)
    debt_penalty = 0.0
    CAPITAL_INTENSIVE_TICKERS = {
        "VST", "CEG", "NRG", "NEE", "DUK", "SO", "AEP", "SRE", "XEL", "ED",
        "PEG", "WEC", "ES", "D", "AMT", "CCI", "EQIX", "PLD", "PSA", "O",
        "SPG", "VICI", "WELL", "DLR", "SBAC", "XLU", "VNQ", "XLRE"
    }
    is_cap_intensive = ticker in CAPITAL_INTENSIVE_TICKERS or ticker in CYCLICAL_MACRO_ETF_TICKERS
    low_de_thresh = 300.0 if is_cap_intensive else 180.0
    high_de_thresh = 550.0 if is_cap_intensive else 320.0

    if isinstance(is_heavy_debt, (int, float)) and not isinstance(is_heavy_debt, bool):
        de_val = float(is_heavy_debt)
        if de_val > low_de_thresh:
            raw_debt_pen = min(15.0, (de_val - low_de_thresh) / (high_de_thresh - low_de_thresh) * 15.0)
            # Cash Flow & Solvency Protection: If FCF is positive and company is financially healthy (F >= 6), halve the penalty
            if not is_fcf_negative and (f_score is not None and f_score >= 6):
                debt_penalty = raw_debt_pen * 0.5
            else:
                debt_penalty = raw_debt_pen
    elif is_heavy_debt:
        debt_penalty = 7.5 if (not is_fcf_negative and is_cap_intensive) else 15.0
    trend_penalty += debt_penalty

    # High POP continuous smooth win-rate reward (in range 75% ~ 90% up to +3.0 pts)
    pop_bonus = 0.0
    if pop is not None and not np.isnan(float(pop)):
        pop_val = float(pop)
        if pop_val >= 75.0:
            pop_bonus = min(3.0, max(0.0, (pop_val - 75.0) / 15.0 * 3.0))

    # 5. Volatility Compression / Panic Cleared Bottoming Signal
    # Condition: Underlying has had a pullback (spot_dev <= -0.06, drop >= 8%, or spot_rp <= 0.25)
    # AND IV has compressed (safe_ivp <= 30.0% or IV is low while HV is high)
    # AND asset is fortress quality (is_high_quality and not is_toxic_knife)
    # -> Signals panic premium exhaustion and steady bottoming consolidation (+2.5 pts bonus)
    vol_bottom_bonus = 0.0
    has_pullback = (
        (is_long_bull(ticker, hv=curr_hv) and spot_dev <= -0.06)
        or (not is_long_bull(ticker, hv=curr_hv) and spot_rp <= 0.25)
        or (drop_pct >= 8.0)
    )
    is_vol_compressed = (safe_ivp <= 30.0) or (c_hv > 0 and (safe_ivp <= 40.0 and c_hv >= 35.0))
    if has_pullback and is_vol_compressed and is_high_quality and not is_toxic_knife:
        vol_bottom_bonus = min(3.5, max(1.5, ((30.0 - min(30.0, safe_ivp)) / 30.0) * 2.0 + 1.5))

    total_score = max(0.0, base_score - trend_penalty + f_score_bonus + insider_bonus + pcr_bonus + earnings_safety_bonus + pop_bonus + contrarian_gold_bonus + vol_bottom_bonus)
    return total_score, s_price, s_safety, s_option_alpha, s_ev, trend_penalty


def calculate_covered_call_score(
    ticker: str,
    current_price: float,
    avg_cost: float,
    strike: float,
    delta: float,
    mark: float,
    annualized_yield: float,
    ivp: float,
    dte: int,
    sma_200: float,
    low_52w: float,
    high_52w: float,
) -> Tuple[float, float, float, float, float]:
    """
    Calculate Covered Call Multi-Factor Score.

    Returns:
        (total_score, s_yield, s_safety, s_iv, s_price)
    """
    s_yield = min(100.0, annualized_yield * 4.0)
    s_safety = (1.0 - delta) * 100.0
    s_iv = float(ivp)

    if is_long_bull(ticker):
        dev = (current_price - sma_200) / sma_200 if sma_200 > 0 else 0.0
        s_price = 100.0 if dev >= 0.03 else max(0.0, dev * 1000.0)
    else:
        rp = (current_price - low_52w) / (high_52w - low_52w) if (high_52w - low_52w) > 0 else 0.5
        s_price = rp * 100.0

    total_score = 0.30 * s_yield + 0.35 * s_safety + 0.20 * s_iv + 0.15 * s_price
    return total_score, s_yield, s_safety, s_iv, s_price


def get_recommendation_reason(
    opt: Dict[str, Any],
    mdata: Dict[str, Any],
    wash_sale_history_map: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    insider_sentiment_map: Optional[Dict[str, Dict[str, Any]]] = None,
    fundamental_info: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate structured, badge-enriched recommendation text for an option candidate."""
    ticker = opt['ticker']
    strike = opt['strike']
    curr_price = opt['current_price']
    annualized_yield = opt['annualized_yield']
    ivp = opt['ivp']
    risk_profile = opt['risk_profile']
    warning = opt.get('warning', False)

    sma_200 = mdata.get('sma_200', curr_price)
    low_52w = mdata.get('low_52w', curr_price * 0.8)
    high_52w = mdata.get('high_52w', curr_price * 1.2)

    # 1. Price valuation position description
    pos_text = ""
    if is_long_bull(ticker):
        dev = (curr_price - sma_200) / sma_200 if sma_200 > 0 else 0.0
        if dev <= -0.05:
            pos_text = f"稳步长牛标的，当前股价已深跌至200日均线下方 {abs(dev)*100:.1f}%，处于极低黄金坑建仓区间。"
        elif dev <= 0.00:
            pos_text = f"稳步长牛标的，当前股价已回踩至200日均线下方 {abs(dev)*100:.1f}%，估值极具吸引力。"
        elif dev <= 0.03:
            pos_text = f"稳步长牛标的，当前股价距离200日均线仅高出 {dev*100:.1f}%，处于合理估值支撑位。"
        else:
            pos_text = f"稳步长牛标的，当前股价高于200日均线 {dev*100:.1f}%。"
    else:
        rp = (curr_price - low_52w) / (high_52w - low_52w) if (high_52w - low_52w) > 0 else 0.5
        if rp <= 0.10:
            pos_text = f"高波成长/周期标的，当前处于52周历史底部的 {rp*100:.0f}% 分位，极度超跌超卖。"
        elif rp <= 0.20:
            pos_text = f"高波成长/周期标的，当前处于52周相对低位 {rp*100:.0f}% 分位，下行空间有限。"
        else:
            pos_text = f"当前处于52周区间的 {rp*100:.0f}% 相对位置。"

    # 2. IV & VixFix description
    vixfix_tag = ""
    if mdata.get('vixfix_252d_ivp', 0.0) >= 80.0:
        vixfix_tag = "<span style='color: #ec4899; font-weight: bold; background: rgba(236, 72, 153, 0.15); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(236, 72, 153, 0.4); margin-left: 4px;'>[⚡VixFix 恐慌高波]</span>"

    iv_text = ""
    if ivp >= 80:
        iv_text = f"IVP达 {ivp:.0f}% <span style='color: #a855f7; font-weight: bold; background: rgba(168, 85, 247, 0.15); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(168, 85, 247, 0.4);'>[🚀 IV-Crush 爆发型]</span><span style='color: #f59e0b; font-weight: bold; background: rgba(245, 158, 11, 0.12); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(245, 158, 11, 0.3); margin-left: 4px;'>[🔥高IV权利金盛宴]</span>{vixfix_tag} 极其适合开仓后捕获 IV 暴跌极速止盈。"
    elif ivp >= 60:
        iv_text = f"IVP为 {ivp:.0f}% <span style='color: #a855f7; font-weight: bold; background: rgba(168, 85, 247, 0.15); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(168, 85, 247, 0.4);'>[🚀 IV-Crush 爆发型]</span>{vixfix_tag} 波动率溢价优异，容易获得 Vega 坍塌加速度。"
    elif ivp <= 25:
        iv_text = f"IVP仅 {ivp:.0f}% <span style='color: #3b82f6; font-weight: bold; background: rgba(59, 130, 246, 0.12); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(59, 130, 246, 0.3);'>[⏳ Theta-静水收租型]</span><span style='color: #ef4444; font-weight: bold; background: rgba(239, 68, 68, 0.1); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(239, 68, 68, 0.25); margin-left: 4px;'>[⚠️低IV权金微薄 (-10分)]</span>{vixfix_tag} 缺乏 IV Crush 红利，需做好买入防守或长线低价接股准备。"
    elif ivp >= 50:
        iv_text = f"IVP为 {ivp:.0f}%{vixfix_tag}，波动率溢价良好。"
    else:
        iv_text = f"IVP仅 {ivp:.0f}%{vixfix_tag}，权利金期权溢价普通。"

    # 3. Risk Profile & Strike Drop
    pct_drop = (curr_price - strike) / curr_price * 100.0 if curr_price > 0 else 0.0
    risk_text = ""
    if risk_profile == "保守":
        risk_text = f"【保守】行权距现价 {pct_drop:.1f}%，安全垫厚，稳收 {annualized_yield:.1f}% 年化收益。"
    elif risk_profile == "平衡":
        risk_text = f"【平衡】行权距现价 {pct_drop:.1f}%，攻守均衡，获取 {annualized_yield:.1f}% 年化收益。"
    elif risk_profile == "激进":
        risk_text = f"【激进】行权距现价仅 {pct_drop:.1f}%，极易接股，博取 {annualized_yield:.1f}% 高年化收益。"

    liq_warning_type = opt.get('liq_warning', '')
    if liq_warning_type == "中度点差":
        liq_text = " <span style='color: #f59e0b; font-weight: bold; background: rgba(245, 158, 11, 0.12); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(245, 158, 11, 0.3);'>[⚠️ 中度点差 (建议限价单)]</span>"
    elif liq_warning_type == "低流动性" or warning:
        liq_text = " <span style='color: #ef4444; font-weight: bold; background: rgba(239, 68, 68, 0.12); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(239, 68, 68, 0.3);'>[🚫 低流动性匮乏]</span>"
    else:
        liq_text = ""

    knife_text = ""
    if mdata.get('is_falling_knife', False):
        ret_30 = mdata.get('return_30d', 0.0)
        f_score_val, _ = calculate_piotroski_f_score(fundamental_info)
        is_contrarian_reason = is_etf_symbol(ticker) or (f_score_val is not None and f_score_val >= 7) or (insider_sentiment_map and insider_sentiment_map.get(ticker, {}).get('sentiment') == 'net_buying')
        if is_contrarian_reason:
            knife_text = f" <span style='color: #38bdf8; font-weight: bold; background: rgba(56, 189, 248, 0.15); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(56, 189, 248, 0.4);'>[💎 黄金坑错杀·近30天跌 {abs(ret_30)*100:.1f}% 逆向低吸 (+4分)]</span>"
        else:
            knife_text = f" <span style='color: #f87171; font-weight: bold; text-shadow: 0 0 10px rgba(248,113,113,0.25);'>[⚠️急跌飞刀：近30天跌幅达 {abs(ret_30)*100:.1f}%，请确认基本面]</span>"

    f_score, _ = calculate_piotroski_f_score(fundamental_info)
    is_eva, moat_label = check_eva_and_moat(ticker, fundamental_info)
    quality_badge = ""
    if f_score is not None and f_score >= 7:
        quality_badge += f" <span style='color: #34d399; font-weight: bold; background: rgba(52, 211, 153, 0.12); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(52, 211, 153, 0.3);'>[🛡️ F-Score {f_score}/9 极高质]</span>"
    elif f_score is not None and f_score <= 3 and not is_etf_symbol(ticker):
        quality_badge += f" <span style='color: #ef4444; font-weight: bold; background: rgba(239, 68, 68, 0.12); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(239, 68, 68, 0.3);'>[🚨 F-Score {f_score}/9 劣质财务否决]</span>"

    if is_eva and not is_etf_symbol(ticker):
        quality_badge += f" <span style='color: #c084fc; font-weight: bold; background: rgba(168, 85, 247, 0.12); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(168, 85, 247, 0.3);'>[🏰 {moat_label}]</span>"

    insider_badge = ""
    if insider_sentiment_map and ticker in insider_sentiment_map:
        ins = insider_sentiment_map[ticker]
        insider_badge = f" {ins.get('badge_html', '')}" if ins.get('badge_html') else ""

    earnings_cross_text = ""
    if opt.get('is_earnings_crosser', False):
        earnings_cross_text = " <span style='color: #f59e0b; font-weight: bold; background: rgba(245, 158, 11, 0.12); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(245, 158, 11, 0.3);'>[📅跨财报双重防守]</span>"

    debt_badge = ""
    if opt.get('extreme_debt', False):
        debt_badge = " <span style='color: #ef4444; font-weight: bold; background: rgba(239, 68, 68, 0.12); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(239, 68, 68, 0.3);'>[⚠️高杠杆负债 (-15分)]</span>"

    wash_text = ""
    if wash_sale_history_map and ticker in wash_sale_history_map:
        info_list = wash_sale_history_map[ticker]
        unlock_dts = ", ".join([f"{item['unlock_date']}" for item in info_list])
        wash_text = f" <span style='color: #f87171; font-weight: bold;'>[🚨Wash Sale 避税风险预警 (-10分)：该标在近30天内有平仓亏损记录，在 {unlock_dts} 解封前买入或卖Put将导致亏损无法当期抵税！]</span>"

    # Max Pain badge
    max_pain = opt.get('max_pain')
    pain_badge = ""
    if max_pain and curr_price > 0:
        d_pain = (max_pain - strike) / curr_price * 100.0
        if d_pain >= 5.0:
            pain_badge = f" <span style='color: #34d399; font-weight: bold; background: rgba(52, 211, 153, 0.12); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(52, 211, 153, 0.3);'>[🛡️ MaxPain 引力屏障 ${max_pain:.0f}]</span>"

    # Skew badge
    put_skew = opt.get('put_skew')
    skew_badge = ""
    if put_skew and put_skew >= 1.20:
        skew_badge = f" <span style='color: #f59e0b; font-weight: bold; background: rgba(245, 158, 11, 0.12); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(245, 158, 11, 0.3);'>[🔥 偏度恐慌溢价 Skew {put_skew:.2f}]</span>"

    # PCR badge
    pcr_oi = opt.get('pcr_oi')
    pcr_badge = ""
    if pcr_oi and pcr_oi >= 1.40:
        pcr_badge = f" <span style='color: #38bdf8; font-weight: bold; background: rgba(56, 189, 248, 0.12); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(56, 189, 248, 0.3);'>[📊 逆向超卖筑底 PCR {pcr_oi:.2f}]</span>"

    # Quant EV & POP badge (Option C: 4-Character Action Taxonomy)
    pop = opt.get('pop')
    ev_dollar = opt.get('ev_dollar')
    f_score_val = opt.get('f_score')
    if f_score_val is None and fundamental_info:
        f_score_val, _ = calculate_piotroski_f_score(fundamental_info)
    is_high_qual = bool(opt.get('is_high_qual')) or is_etf_symbol(ticker) or (f_score_val is not None and f_score_val >= 7) or (insider_sentiment_map and insider_sentiment_map.get(ticker, {}).get("sentiment") == "net_buying")
    ev_badge = ""
    if pop is not None and ev_dollar is not None:
        opt_ivp = opt.get('ivp', 50.0)
        if ev_dollar > 10 and (opt_ivp is None or opt_ivp >= 35.0):
            ev_badge = f" <span style='color: #10b981; font-weight: bold; background: rgba(16, 185, 129, 0.12); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(16, 185, 129, 0.3);'>[💰 溢价收租 +${ev_dollar:.0f} (POP {pop:.0f}%)]</span>"
        elif ev_dollar >= -150 or (ev_dollar > 10 and opt_ivp < 35.0):
            ev_badge = f" <span style='color: #0ea5e9; font-weight: bold; background: rgba(14, 165, 233, 0.12); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(14, 165, 233, 0.3);'>[🟢 稳健收租 (POP {pop:.0f}%)]</span>"
        else:
            # Deep negative EV (< -150)
            if is_high_qual or (f_score_val is not None and f_score_val >= 5 and not opt.get('is_fcf_negative')):
                ev_badge = f" <span style='color: #8b5cf6; font-weight: bold; background: rgba(139, 92, 246, 0.12); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(139, 92, 246, 0.3);'>[💎 折扣建仓 (POP {pop:.0f}%)]</span>"
            else:
                ev_badge = f" <span style='color: #f59e0b; font-weight: bold; background: rgba(245, 158, 11, 0.12); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(245, 158, 11, 0.3);'>[⚠️ 收益偏薄 (POP {pop:.0f}%)]</span>"

    # Panic Cleared / Vol-Compression Bottoming badge
    vol_bottom_badge = ""
    opt_ivp_val = opt.get('ivp', 50.0)
    ret_30_val = mdata.get('return_30d', 0.0)
    s_sma_val = mdata.get('sma_200')
    s_dev_val = (curr_price - s_sma_val) / s_sma_val if s_sma_val and s_sma_val > 0 else 0.0
    if (ret_30_val <= -0.08 or s_dev_val <= -0.06) and (opt_ivp_val is not None and opt_ivp_val <= 30.0) and is_high_qual:
        vol_bottom_badge = " <span style='color: #a78bfa; font-weight: bold; background: rgba(167, 139, 250, 0.15); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(167, 139, 250, 0.4);'>[🕊️ 恐慌出清·筑底信号]</span>"

    return f"{pos_text} {iv_text} {risk_text}{ev_badge}{vol_bottom_badge}{pain_badge}{skew_badge}{pcr_badge}{quality_badge}{insider_badge}{earnings_cross_text}{debt_badge}{liq_text}{knife_text}{wash_text}"
