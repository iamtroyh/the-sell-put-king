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
) -> Tuple[float, float, float, float, float, float]:
    """
    Calculate the Sell Put Multi-Factor Score (0-100 scale).

    Formula:
        Total Score = 0.30 * S_Price + 0.30 * S_Safety + 0.25 * S_Yield + 0.15 * S_IV - Trend_Penalty

    Returns:
        (total_score, s_price, s_safety, s_yield, s_iv, trend_penalty)
    """
    # 1. Yield Factor (S_Yield - 25%) with volatility haircut
    hv_factor = max(10.0, curr_hv) / 100.0
    adj_annualized_yield = annualized_yield / (1.0 + 1.5 * hv_factor)
    s_yield = min(100.0, adj_annualized_yield * 4.0)

    # 2. Implied Volatility Factor (S_IV - 15%)
    s_iv = float(ivp)

    # 3. Base Safety & Price Factors (S_Price - 30%, S_Safety - 30%)
    base_safety = (1.0 - abs(delta)) * 100.0
    if is_long_bull(ticker):
        dev = (current_price - sma_200) / sma_200 if sma_200 > 0 else 0.0
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
        rp = (current_price - low_52w) / (high_52w - low_52w) if (high_52w - low_52w) > 0 else 0.5
        s_price = min(100.0, 70.0 + (0.20 - rp) * 200.0) if rp <= 0.20 else max(0.0, 70.0 - (rp - 0.20) * 87.5)
        if rp <= 0.20:
            s_safety = 100.0
        elif rp <= 0.35:
            s_safety = max(base_safety, 100.0 - ((rp - 0.20) / 0.15) * (100.0 - base_safety))
        else:
            s_safety = base_safety

    base_score = 0.30 * s_price + 0.30 * s_safety + 0.25 * s_yield + 0.15 * s_iv

    # 4. Trend & Fundamental Penalties
    trend_penalty = 0.0
    if knife_level == 1:
        trend_penalty += 15.0
    elif knife_level == 2:
        trend_penalty += 30.0
    elif knife_level == 3:
        trend_penalty += 50.0

    if is_fcf_negative:
        trend_penalty += 10.0

    if ivp <= 25.0:
        trend_penalty += 10.0

    f_score_bonus = 0.0
    if f_score is not None and not is_etf_symbol(ticker):
        if f_score <= 3:
            trend_penalty += 50.0
        elif f_score >= 7:
            f_score_bonus = 10.0

    insider_bonus = 0.0
    if not is_etf_symbol(ticker):
        if insider_sentiment == "heavy_selling":
            trend_penalty += 5.0
        elif insider_sentiment == "net_buying":
            insider_bonus = 5.0

    if is_heavy_debt:
        trend_penalty += 15.0

    total_score = max(0.0, base_score - trend_penalty + f_score_bonus + insider_bonus)
    return total_score, s_price, s_safety, s_yield, s_iv, trend_penalty


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

    wash_text = ""
    if wash_sale_history_map and ticker in wash_sale_history_map:
        info_list = wash_sale_history_map[ticker]
        unlock_dts = ", ".join([f"{item['unlock_date']}" for item in info_list])
        wash_text = f" <span style='color: #f87171; font-weight: bold;'>[🚨Wash Sale 避税风险预警：该标在近30天内有平仓亏损记录，在 {unlock_dts} 解封前买入或卖Put将导致亏损无法当期抵税！]</span>"

    earnings_cross_text = ""
    if opt.get('is_earnings_crosser', False):
        earnings_cross_text = " <span style='color: #fbbf24; font-weight: bold; background: rgba(251, 191, 36, 0.12); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(251, 191, 36, 0.3);'>[📅财报延展防守：智能跨越财报并锁死低Delta]</span>"

    insider_badge = ""
    if insider_sentiment_map and not is_etf_symbol(ticker):
        i_data = insider_sentiment_map.get(ticker, {})
        i_sent = i_data.get("sentiment")
        if i_sent == "net_buying":
            insider_badge = " <span style='color: #34d399; font-weight: bold; background: rgba(52, 211, 153, 0.12); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(52, 211, 153, 0.3);'>[👔 高管增持自购]</span>"
        elif i_sent == "heavy_selling":
            insider_badge = " <span style='color: #f87171; font-weight: bold; background: rgba(239, 68, 68, 0.12); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(239, 68, 68, 0.3);'>[🚨 高管大额减持]</span>"

    debt_badge = ""
    if opt.get('is_heavy_debt', False):
        debt_badge = " <span style='color: #f87171; font-weight: bold; background: rgba(239, 68, 68, 0.12); padding: 1px 5px; border-radius: 4px; border: 1px solid rgba(239, 68, 68, 0.3);'>[🚨 极端高负债风险 D/E>250%]</span>"

    return f"{pos_text} {iv_text} {risk_text}{quality_badge}{insider_badge}{earnings_cross_text}{debt_badge}{liq_text}{knife_text}{wash_text}"
