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
    
    # Dual-Damping Volatility Estimator:
    # 1. Base on realized HV (historical baseline)
    # 2. Bound sigma to at most 1.5x IV (prevents single-day gap-down spikes from distorting forward EV)
    raw_sigma = hv if hv > 0 else (iv if iv > 0 else 0.25)
    if iv > 0:
        sigma = min(raw_sigma, 1.5 * iv)
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
) -> Tuple[float, float, float, float, float, float]:
    """
    Calculate the Institutional Multi-Factor Quantitative Score for Sell Put (0-100 scale).

    Formula:
        Total Score = 0.50 * S_Price + 0.30 * S_Safety + 0.20 * S_OptionAlpha - Trend_Penalty + Bonuses

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

    trend_penalty = 0.0

    # 1. Option Alpha & Mathematical Expectation Factor (S_OptionAlpha - 20% Weight)
    # Blends 70% Pure EV APY (Square-Root Smooth Saturation Mapping) + 30% Volatility/Skew Structure
    if ev_apy is not None and not np.isnan(float(ev_apy)):
        valid_ev_apy = float(ev_apy)
        valid_ev_dollar = float(ev_dollar) if ev_dollar is not None and not np.isnan(float(ev_dollar)) else 0.0
        if valid_ev_dollar <= 0.0:
            s_ev = 0.0
            trend_penalty += 15.0  # Mathematical negative expectation penalty!
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

    # 2. Base Safety & Price Factors (S_Price - 50%, S_Safety - 30%)
    base_safety = (1.0 - abs(c_delta)) * 100.0
    if is_long_bull(ticker):
        s_sma = float(sma_200) if sma_200 is not None and not np.isnan(float(sma_200)) else c_price
        dev = (c_price - s_sma) / s_sma if s_sma > 0 else 0.0
        # Hard cap dev at -15%
        capped_dev = max(-0.15, dev)
        s_price = min(100.0, 70.0 - capped_dev * 600.0) if dev <= 0.00 else max(0.0, 70.0 - dev * 700.0)
        if dev <= 0.00:
            s_safety = 100.0
        elif dev <= 0.05:
            s_safety = max(base_safety, 100.0 - (dev / 0.05) * (100.0 - base_safety))
        else:
            s_safety = base_safety
    else:
        s_low = float(low_52w) if low_52w is not None and not np.isnan(float(low_52w)) else c_price * 0.8
        s_high = float(high_52w) if high_52w is not None and not np.isnan(float(high_52w)) else c_price * 1.2
        rp = (c_price - s_low) / (s_high - s_low) if (s_high - s_low) > 0 else 0.5
        s_price = min(100.0, 70.0 + (0.20 - rp) * 200.0) if rp <= 0.20 else max(0.0, 70.0 - (rp - 0.20) * 87.5)
        if rp <= 0.20:
            s_safety = 100.0
        elif rp <= 0.35:
            s_safety = max(base_safety, 100.0 - ((rp - 0.20) / 0.15) * (100.0 - base_safety))
        else:
            s_safety = base_safety

    # Max Pain gravitational adjustment (+4 / -4 pts) only if measured and valid
    if max_pain is not None and max_pain > 0 and not np.isnan(float(max_pain)) and c_price > 0:
        d_pain = (float(max_pain) - c_strike) / c_price * 100.0
        if d_pain >= 5.0:
            s_safety = float(np.clip(s_safety + 4.0, 0.0, 100.0))  # Pinning barrier provides extra protection
        elif d_pain <= -3.0:
            s_safety = float(np.clip(s_safety - 4.0, 0.0, 100.0))  # Pinning pulls spot below strike

    # Three-Pillars Base Score: 50% Price + 30% Safety + 20% Option Alpha
    base_score = 0.50 * s_price + 0.30 * s_safety + 0.20 * s_option_alpha

    # 3. Trend & Fundamental Penalties (trend_penalty accumulates without overwriting)
    is_etf = is_etf_symbol(ticker)
    if is_etf:
        if knife_level == 1:
            trend_penalty += 10.0  # Calibrated for ETF (10% drop)
        elif knife_level == 2:
            trend_penalty += 25.0  # Calibrated for ETF (16% drop)
        elif knife_level == 3:
            trend_penalty += 50.0  # Black swan ETF veto
    else:
        if knife_level == 1:
            trend_penalty += 15.0  # Individual stock (15% drop)
        elif knife_level == 2:
            trend_penalty += 30.0  # Individual stock (25% drop)
        elif knife_level == 3:
            trend_penalty += 50.0  # Individual stock veto

    if is_fcf_negative:
        trend_penalty += 10.0

    f_score_bonus = 0.0
    if f_score is not None and not is_etf:
        if f_score <= 3:
            trend_penalty += 50.0  # Bad financials veto
        elif f_score >= 7:
            f_score_bonus = 6.0   # Calibrated +6 pt reward for fortress quality

    insider_bonus = 0.0
    if not is_etf:
        if insider_sentiment == "heavy_selling":
            trend_penalty += 5.0
        elif insider_sentiment == "net_buying":
            insider_bonus = 5.0

    # Contrarian Sentiment (PCR) only if authentically measured
    pcr_bonus = 0.0
    if pcr_oi is not None and pcr_oi > 0 and not np.isnan(float(pcr_oi)):
        if pcr_oi >= 1.40:
            pcr_bonus = 3.0   # Extreme market fear -> contrarian bottoming bonus
        elif pcr_oi <= 0.50:
            trend_penalty += 3.0  # Extreme euphoria / complacency penalty

    # Earnings Expected Move Gatekeeper
    earnings_safety_bonus = 0.0
    if is_earnings_crosser and expected_move_pct is not None and expected_move_pct > 0 and not np.isnan(float(expected_move_pct)) and c_price > 0:
        cushion_pct = (c_price - c_strike) / c_price * 100.0
        m_earnings = cushion_pct / float(expected_move_pct)
        if m_earnings < 1.0:
            trend_penalty += 25.0  # Strike is inside the market 1-sigma expected earnings move
        elif m_earnings >= 1.50:
            earnings_safety_bonus = 3.0  # Mathematically deep beyond 1-sigma jump

    if is_heavy_debt:
        trend_penalty += 15.0

    pop_bonus = 0.0
    if pop is not None and not np.isnan(float(pop)):
        if float(pop) >= 86.0:
            pop_bonus = 2.0  # High mathematical win-rate reward

    total_score = max(0.0, base_score - trend_penalty + f_score_bonus + insider_bonus + pcr_bonus + earnings_safety_bonus + pop_bonus)
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

    liq_text = " <span style='color: #ef4444; font-weight: bold;'>[🚨极低流动性警告]</span>" if warning else ""

    knife_text = ""
    if mdata.get('is_falling_knife', False):
        ret_30 = mdata.get('return_30d', 0.0)
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
        wash_text = f" <span style='color: #f87171; font-weight: bold;'>[🚨Wash Sale 避税风险预警：该标在近30天内有平仓亏损记录，在 {unlock_dts} 解封前买入或卖Put将导致亏损无法当期抵税！]</span>"

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

    # Quant EV & POP badge
    pop = opt.get('pop')
    ev_dollar = opt.get('ev_dollar')
    trade_sharpe = opt.get('trade_sharpe')
    ev_badge = ""
    if pop is not None and ev_dollar is not None and ev_dollar > 0:
        ev_badge = f" <span style='color: #10b981; font-weight: bold; background: rgba(16, 185, 129, 0.12); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(16, 185, 129, 0.3);'>[🎯 POP {pop:.1f}% | EV +${ev_dollar:.0f} (夏普 {trade_sharpe:.1f})]</span>"
    elif ev_dollar is not None and ev_dollar <= 0:
        ev_badge = f" <span style='color: #ef4444; font-weight: bold; background: rgba(239, 68, 68, 0.12); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(239, 68, 68, 0.3);'>[⚠️ 负期望交易 EV -${abs(ev_dollar):.0f}]</span>"

    return f"{pos_text} {iv_text} {risk_text}{ev_badge}{pain_badge}{skew_badge}{pcr_badge}{quality_badge}{insider_badge}{earnings_cross_text}{debt_badge}{liq_text}{knife_text}{wash_text}"
