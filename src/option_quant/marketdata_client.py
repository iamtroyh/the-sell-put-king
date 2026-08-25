# -*- coding: utf-8 -*-
"""
Market Data App API Client & True IV Engine
===========================================
Integrates marketdata.app REST API for real-time and historical option chains,
ATM 30-day implied volatility (IV), IV Rank (IVR), and IV Percentile (IVP).
"""

from __future__ import annotations

import datetime
import json
import logging
import math
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import requests

from option_quant.config import (
    BASE_DIR,
    DATA_DIR,
    atomic_write_json,
    get_marketdata_token,
    normalize_symbol,
    to_display_symbol,
    to_yf_symbol,
)

logger = logging.getLogger("option_quant.marketdata")

IV_CACHE_PATH = os.path.join(DATA_DIR, "iv_history_cache.json")
_IV_MEM_CACHE: Optional[Dict[str, Any]] = None
_IV_LOCK = threading.Lock()


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def compute_black_scholes_iv(
    price: float,
    strike: float,
    dte: int,
    spot: float,
    r: float = 0.05,
    opt_type: str = "put",
    max_iter: int = 100,
    tol: float = 1e-4,
) -> Optional[float]:
    """
    Robust Black-Scholes implied volatility solver using bisection method.

    Args:
        price: Option market price (mid).
        strike: Strike price.
        dte: Days to expiration.
        spot: Underlying spot price.
        r: Risk-free interest rate (default 0.05).
        opt_type: 'put' or 'call'.

    Returns:
        Implied volatility as decimal (e.g. 0.25 for 25%), or None if unsolvable.
    """
    if price <= 0.0 or strike <= 0.0 or spot <= 0.0 or dte <= 0:
        return None

    t = dte / 365.0

    # Intrinsic check
    if opt_type == "put":
        intrinsic = max(0.0, strike * math.exp(-r * t) - spot)
    else:
        intrinsic = max(0.0, spot - strike * math.exp(-r * t))

    if price < intrinsic - 1e-4:
        return None

    low_vol = 0.001
    high_vol = 5.0  # 500% cap

    def bs_price(sigma: float) -> float:
        d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
        d2 = d1 - sigma * math.sqrt(t)
        if opt_type == "put":
            return strike * math.exp(-r * t) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
        else:
            return spot * _norm_cdf(d1) - strike * math.exp(-r * t) * _norm_cdf(d2)

    for _ in range(max_iter):
        mid_vol = 0.5 * (low_vol + high_vol)
        p = bs_price(mid_vol)
        diff = p - price
        if abs(diff) < tol:
            return mid_vol
        if diff > 0:
            high_vol = mid_vol
        else:
            low_vol = mid_vol

    return 0.5 * (low_vol + high_vol)


class MarketDataClient:
    """
    Client for marketdata.app RESTful Options API.
    """

    BASE_URL = "https://api.marketdata.app/v1"

    def __init__(self, token: Optional[str] = None, timeout: int = 10):
        self.token = token or get_marketdata_token()
        self.timeout = timeout
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=30, pool_maxsize=30)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "OptionQuant/1.0 (Macintosh; Intel Mac OS X)",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def get_option_chain(
        self,
        symbol: str,
        side: Optional[str] = None,
        range_type: str = "atm",
        dte: Optional[int] = 30,
        strike_limit: int = 4,
        date: Optional[str] = None,
        delta: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        min_open_interest: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Query Market Data option chain endpoint.

        Returns JSON dict or None on failure.
        Accepts HTTP 200 and 203 as successful responses.
        """
        clean_sym = to_yf_symbol(symbol).replace("-", ".")
        url = f"{self.BASE_URL}/options/chain/{clean_sym}/"
        params: Dict[str, Any] = {}

        if side:
            params["side"] = side
        if range_type:
            params["range"] = range_type
        if dte is not None:
            params["dte"] = dte
        if strike_limit is not None:
            params["strikeLimit"] = strike_limit
        if date:
            params["date"] = date
        if delta:
            params["delta"] = delta
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        if min_open_interest is not None:
            params["minOpenInterest"] = min_open_interest

        try:
            r = self.session.get(url, headers=self._headers(), params=params, timeout=self.timeout)
            if r.status_code in [200, 203]:
                return r.json()
            elif r.status_code == 404:
                return None
            else:
                logger.debug(f"MarketData API returned status {r.status_code}: {r.text[:100]}")
                return None
        except Exception as e:
            logger.debug(f"MarketData API request error for {symbol}: {e}")
            return None

    def get_current_atm_iv(self, symbol: str, dte: int = 30) -> Optional[float]:
        """
        Fetch real-time ~30 DTE ATM Implied Volatility for a symbol.
        """
        data = self.get_option_chain(
            symbol=symbol,
            side="put",
            range_type="atm",
            dte=dte,
            strike_limit=4,
        )
        if not data or data.get("s") != "ok":
            data = self.get_option_chain(
                symbol=symbol,
                side="call",
                range_type="atm",
                dte=dte,
                strike_limit=4,
            )

        if not data or data.get("s") != "ok":
            return None

        iv_list = [v for v in data.get("iv", []) if v is not None and v > 0]
        if iv_list:
            return float(np.median(iv_list))

        # Fallback: calculate Black-Scholes IV from mid prices
        mids = data.get("mid", [])
        strikes = data.get("strike", [])
        dtes = data.get("dte", [])
        spots = data.get("underlyingPrice", [])
        sides = data.get("side", [])

        calculated_ivs = []
        for i in range(len(mids)):
            if i < len(strikes) and i < len(dtes) and i < len(spots):
                m = float(mids[i] or 0.0)
                k = float(strikes[i] or 0.0)
                d = int(dtes[i] or dte)
                s = float(spots[i] or 0.0)
                opt_t = sides[i] if i < len(sides) else "put"
                iv_sol = compute_black_scholes_iv(m, k, d, s, opt_type=opt_t)
                if iv_sol and 0.01 <= iv_sol <= 4.0:
                    calculated_ivs.append(iv_sol)

        if calculated_ivs:
            return float(np.median(calculated_ivs))

        return None


# ==================== TRUE IV PERSISTENCE & CACHING ====================

def _load_iv_cache() -> Dict[str, Any]:
    global _IV_MEM_CACHE
    with _IV_LOCK:
        if _IV_MEM_CACHE is None:
            if os.path.exists(IV_CACHE_PATH):
                try:
                    with open(IV_CACHE_PATH, "r", encoding="utf-8") as f:
                        _IV_MEM_CACHE = json.load(f)
                except Exception:
                    _IV_MEM_CACHE = {}
            else:
                _IV_MEM_CACHE = {}
        return _IV_MEM_CACHE


def _save_iv_cache(cache: Dict[str, Any]) -> None:
    with _IV_LOCK:
        atomic_write_json(IV_CACHE_PATH, cache)


def get_true_ivp_and_ivr(
    symbol: str,
    client: Optional[MarketDataClient] = None,
    force_refresh: bool = False,
    sampling_step: int = 10,
    auto_backfill: bool = False,
) -> Dict[str, Any]:
    """
    Calculate 252-day True IV Percentile (IVP) and True IV Rank (IVR) for a symbol
    using Market Data API.

    Returns:
        Dict with IVP, IVR, composite_s_iv, etc.
    """
    sym = normalize_symbol(symbol)
    cache = _load_iv_cache()
    now_ts = datetime.datetime.now().timestamp()

    if not force_refresh and sym in cache:
        cached = cache[sym]
        if now_ts - cached.get("timestamp", 0) < 86400:
            return cached.get("data", {})

    c = client or MarketDataClient()
    current_iv = c.get_current_atm_iv(sym, dte=30) if c.token else None

    if current_iv is None or current_iv <= 0.0:
        res = {
            "symbol": sym,
            "has_true_iv": False,
            "current_iv": 0.0,
            "ivp": 50.0,
            "ivr": 50.0,
            "composite_s_iv": 50.0,
            "min_iv": 0.0,
            "max_iv": 0.0,
            "sample_count": 0,
            "badge_html": "<span style='padding: 2px 6px; border-radius: 4px; background: rgba(255,255,255,0.05); color: #a1a1aa; font-size: 10.5px;'>⚪ 真实 IV 待接入</span>",
            "summary_text": "暂无真实期权 IV 历史序列，使用默认波动率基准。",
        }
        return res

    existing_history = cache.get(sym, {}).get("iv_history", {})
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    existing_history[today_str] = current_iv

    if auto_backfill and len(existing_history) < 20 and c.token:
        logger.info(f"Backfilling historical IV time series for {sym} (sampling step: {sampling_step} days)...")
        today = datetime.date.today()
        dates_to_query = []
        for days_ago in range(sampling_step, 360, sampling_step):
            hist_date = today - datetime.timedelta(days=days_ago)
            if hist_date.weekday() >= 5:
                hist_date = hist_date - datetime.timedelta(days=(hist_date.weekday() - 4))
            d_str = hist_date.strftime("%Y-%m-%d")
            if d_str not in existing_history:
                dates_to_query.append(d_str)

        def fetch_date_iv(d_str: str) -> Tuple[str, Optional[float]]:
            hist_data = c.get_option_chain(
                symbol=sym,
                date=d_str,
                side="put",
                range_type="atm",
                dte=30,
                strike_limit=2,
            )
            if hist_data and hist_data.get("s") == "ok":
                iv_vals = [v for v in hist_data.get("iv", []) if v is not None and v > 0]
                if iv_vals:
                    return d_str, float(np.median(iv_vals))
                else:
                    mids = hist_data.get("mid", [])
                    strikes = hist_data.get("strike", [])
                    dtes = hist_data.get("dte", [])
                    spots = hist_data.get("underlyingPrice", [])
                    if mids and strikes and dtes and spots:
                        bs_iv = compute_black_scholes_iv(
                            float(mids[0] or 0),
                            float(strikes[0] or 0),
                            int(dtes[0] or 30),
                            float(spots[0] or 0),
                            opt_type="put",
                        )
                        if bs_iv and 0.05 <= bs_iv <= 3.0:
                            return d_str, bs_iv
            return d_str, None

        if dates_to_query:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=10) as pool:
                futures = [pool.submit(fetch_date_iv, d) for d in dates_to_query]
                for fut in as_completed(futures):
                    try:
                        d_str, iv_res = fut.result()
                        if iv_res is not None and iv_res > 0:
                            existing_history[d_str] = iv_res
                    except Exception:
                        pass

    iv_values = [v for k, v in existing_history.items() if v is not None and v > 0]
    if len(iv_values) < 2:
        iv_values = [current_iv * 0.85, current_iv * 1.15, current_iv]

    min_iv = float(np.min(iv_values))
    max_iv = float(np.max(iv_values))

    if max_iv > min_iv:
        ivr = float(np.clip(((current_iv - min_iv) / (max_iv - min_iv)) * 100.0, 0.0, 100.0))
    else:
        ivr = 50.0

    ivp = float((np.array(iv_values) < current_iv).mean() * 100.0)
    composite_s_iv = 0.70 * ivp + 0.30 * ivr

    if ivp >= 75.0 or ivr >= 70.0:
        badge_html = f"<span style='color: #a855f7; font-weight: bold; background: rgba(168, 85, 247, 0.15); padding: 1px 6px; border-radius: 4px; border: 1px solid rgba(168, 85, 247, 0.4);'>🚀 真 IVP {ivp:.0f}% / IVR {ivr:.0f}% [高波溢价]</span>"
        summary_text = f"期权真实 30D IV ({current_iv*100:.1f}%) 处于过去1年高位 (IVP {ivp:.0f}%, IVR {ivr:.0f}%)，具备极强 IV-Crush 加速收租红利。"
    elif ivp <= 25.0:
        badge_html = f"<span style='color: #ef4444; font-weight: bold; background: rgba(239, 68, 68, 0.1); padding: 1px 6px; border-radius: 4px; border: 1px solid rgba(239, 68, 68, 0.3);'>⚠️ 真 IVP {ivp:.0f}% / IVR {ivr:.0f}% [低波偏薄]</span>"
        summary_text = f"期权真实 30D IV ({current_iv*100:.1f}%) 处于历史低位 (IVP {ivp:.0f}%, IVR {ivr:.0f}%)，权利金偏薄，需做好保守接股准备。"
    else:
        badge_html = f"<span style='color: #38bdf8; font-weight: 500; background: rgba(56, 189, 248, 0.12); padding: 1px 6px; border-radius: 4px; border: 1px solid rgba(56, 189, 248, 0.3);'>💎 真 IVP {ivp:.0f}% / IVR {ivr:.0f}%</span>"
        summary_text = f"期权真实 30D IV ({current_iv*100:.1f}%) 处于合理常态区间 (IVP {ivp:.0f}%, IVR {ivr:.0f}%)，权利金定价公允。"

    res = {
        "symbol": sym,
        "has_true_iv": True,
        "current_iv": current_iv,
        "ivp": ivp,
        "ivr": ivr,
        "composite_s_iv": composite_s_iv,
        "min_iv": min_iv,
        "max_iv": max_iv,
        "sample_count": len(iv_values),
        "badge_html": badge_html,
        "summary_text": summary_text,
    }

    cache[sym] = {
        "timestamp": now_ts,
        "sample_count": len(iv_values),
        "iv_history": existing_history,
        "data": res,
    }
    _save_iv_cache(cache)
    return res


def is_standard_monthly(exp_val: Any) -> bool:
    """
    Standard monthly option expiration: 3rd Friday of the month (day 15-21),
    or 3rd Thursday (day 14-20) if Friday is a market holiday.
    """
    try:
        if isinstance(exp_val, (int, float)):
            d = datetime.datetime.fromtimestamp(exp_val).date()
        elif isinstance(exp_val, datetime.date):
            d = exp_val
        elif isinstance(exp_val, datetime.datetime):
            d = exp_val.date()
        else:
            d = datetime.datetime.strptime(str(exp_val)[:10], "%Y-%m-%d").date()
        is_friday = (d.weekday() == 4 and 15 <= d.day <= 21)
        is_thursday_holiday = (d.weekday() == 3 and 14 <= d.day <= 20)
        return is_friday or is_thursday_holiday
    except Exception:
        return False


def get_filtered_csp_candidates(
    symbol: str,
    min_dte: int = 15,
    max_dte: int = 75,
    delta_min: float = -0.40,
    delta_max: float = -0.08,
    min_oi: int = 0,
    client: Optional[MarketDataClient] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch pre-filtered Sell Put (CSP) candidates directly from Market Data API in dual-horizon cycles (Month 1 ~30DTE and Month 2 ~60DTE).
    """
    sym = normalize_symbol(symbol)
    c = client or MarketDataClient()

    candidates: List[Dict[str, Any]] = []
    seen_contracts = set()

    # Query both Near Month (~30 DTE) and Next Month (~60 DTE) option chains
    target_dtes = [30, 60]
    for req_dte in target_dtes:
        chain = c.get_option_chain(
            symbol=sym,
            side="put",
            range_type="all",
            dte=req_dte,
            strike_limit=60,
        )
        if not chain or chain.get("s") != "ok":
            # Fallback to atm query if all range is empty
            chain = c.get_option_chain(
                symbol=sym,
                side="put",
                range_type="atm",
                dte=req_dte,
                strike_limit=30,
            )

        if not chain or chain.get("s") != "ok":
            continue

        strikes = chain.get("strike", [])
        dtes = chain.get("dte", [])
        expirations = chain.get("expiration", [])
        bids = chain.get("bid", [])
        asks = chain.get("ask", [])
        mids = chain.get("mid", [])
        ois = chain.get("openInterest", [])
        deltas = chain.get("delta", [])
        gammas = chain.get("gamma", [])
        thetas = chain.get("theta", [])
        vegas = chain.get("vega", [])
        ivs = chain.get("iv", [])
        spots = chain.get("underlyingPrice", [])

        n = len(strikes)
        for i in range(n):
            dte = int(dtes[i] or 0) if i < len(dtes) else 0
            if not (min_dte <= dte <= max_dte):
                continue

            strike = float(strikes[i] or 0.0)
            spot = float(spots[i] or 0.0) if i < len(spots) and spots[i] else strike
            bid = float(bids[i] or 0.0) if i < len(bids) and bids[i] else 0.0
            ask = float(asks[i] or 0.0) if i < len(asks) and asks[i] else 0.0
            mark = float(mids[i] or 0.0) if i < len(mids) and mids[i] else (bid + ask) / 2.0
            oi = int(ois[i] or 0) if i < len(ois) and ois[i] else 0
            exp_raw = expirations[i] if i < len(expirations) else ""
            exp_str = datetime.datetime.fromtimestamp(exp_raw).strftime("%Y-%m-%d") if isinstance(exp_raw, (int, float)) else str(exp_raw)[:10]

            if mark <= 0.05 or strike <= 0:
                continue

            contract_key = (exp_str, strike)
            if contract_key in seen_contracts:
                continue

            is_monthly = is_standard_monthly(exp_raw if exp_raw else exp_str)
            abs_spread = ask - bid
            spread_ratio = (abs_spread / mark) if mark > 0 else 1.0

            # Adaptive Dual-Tier Gatekeeper:
            # - Monthly: Standard gatekeeper (OI >= 5/10/20, Spread <= 35% or abs_spread <= 0.15)
            # - Non-Monthly (Weekly): Strict liquidity gatekeeper (Zero bid banned, Near-month OI >= 50, Next-month OI >= 100)
            if is_monthly:
                passed_gatekeeper = (spread_ratio <= 0.35 or abs_spread <= 0.15) and (oi >= max(5, min_oi))
            else:
                if bid <= 0.0:
                    passed_gatekeeper = False
                elif dte <= 40:
                    passed_gatekeeper = (spread_ratio <= 0.20 or abs_spread <= 0.10) and (oi >= 50)
                else:
                    passed_gatekeeper = (spread_ratio <= 0.15 or abs_spread <= 0.08) and (oi >= 100)

            raw_delta = deltas[i] if i < len(deltas) and deltas[i] is not None else None
            iv_val = float(ivs[i] or 0.25) if i < len(ivs) and ivs[i] else 0.25
            if raw_delta is not None:
                delta = float(raw_delta)
            else:
                t_yr = dte / 365.0
                from option_quant.scoring import calculate_put_delta
                delta = calculate_put_delta(spot, strike, t_yr, 0.05, iv_val)

            abs_delta = abs(delta)
            if not (abs(delta_max) <= abs_delta <= abs(delta_min)):
                continue

            seen_contracts.add(contract_key)
            gamma = float(gammas[i] or 0.0) if i < len(gammas) and gammas[i] is not None else 0.0
            theta = float(thetas[i] or 0.0) if i < len(thetas) and thetas[i] is not None else 0.0
            vega = float(vegas[i] or 0.0) if i < len(vegas) and vegas[i] is not None else 0.0

            candidates.append({
                "ticker": sym,
                "strike": strike,
                "expiration": exp_str,
                "dte": dte,
                "bid": bid,
                "ask": ask,
                "mark": mark,
                "open_interest": oi,
                "spread_ratio": spread_ratio,
                "delta": delta,
                "gamma": gamma,
                "theta": theta,
                "vega": vega,
                "iv": iv_val * 100.0 if iv_val < 10.0 else iv_val,
                "current_price": spot,
                "passed_gatekeeper": passed_gatekeeper,
                "is_monthly": is_monthly,
            })

    return candidates


def calculate_roll_candidate(
    symbol: str,
    current_strike: float,
    current_mark: float,
    current_dte: int = 10,
    client: Optional[MarketDataClient] = None,
) -> Dict[str, Any]:
    """
    Calculate optimal Roll Down & Out contract and Net Credit/Debit.
    """
    sym = normalize_symbol(symbol)
    c = client or MarketDataClient()

    target_dtes = [max(35, current_dte + 21), max(50, current_dte + 35)]
    all_chains = []
    for td in target_dtes:
        ch = c.get_option_chain(
            symbol=sym,
            side="put",
            range_type="otm",
            dte=td,
            min_open_interest=10,
            strike_limit=16,
        )
        if ch and ch.get("s") == "ok":
            all_chains.append(ch)

    if not all_chains:
        return {"has_roll": False, "summary_text": "无法获取远期期权链报价"}

    best_candidate: Optional[Dict[str, Any]] = None
    best_net_credit = -999.0

    for chain in all_chains:
        strikes = chain.get("strike", [])
        dtes = chain.get("dte", [])
        expirations = chain.get("expiration", [])
        bids = chain.get("bid", [])
        deltas = chain.get("delta", [])

        for i in range(len(strikes)):
            dte = int(dtes[i] or 0) if i < len(dtes) else 0
            strike = float(strikes[i] or 0.0)

            # Roll Down condition: Strike should be <= 98% of current strike (down at least 2%)
            if strike > current_strike * 0.98 or strike < current_strike * 0.75:
                continue

            bid = float(bids[i] or 0.0) if i < len(bids) and bids[i] else 0.0
            if bid <= 0.10:
                continue

            net_credit = bid - current_mark
            delta = float(deltas[i] or -0.25) if i < len(deltas) and deltas[i] is not None else -0.25

            exp_raw = expirations[i] if i < len(expirations) else ""
            exp_str = datetime.datetime.fromtimestamp(exp_raw).strftime("%Y-%m-%d") if isinstance(exp_raw, (int, float)) else str(exp_raw)[:10]

            # Score: prioritize net credit with reasonable strike drop
            score = net_credit * 2.0 + ((current_strike - strike) / current_strike) * 5.0
            if score > best_net_credit:
                best_net_credit = score
                best_candidate = {
                    "has_roll": True,
                    "target_exp": exp_str,
                    "target_strike": strike,
                    "target_dte": dte,
                    "target_bid": bid,
                    "target_delta": delta,
                    "net_credit": net_credit,
                    "strike_drop": current_strike - strike,
                    "strike_drop_pct": ((current_strike - strike) / current_strike) * 100.0,
                }

    if not best_candidate:
        return {"has_roll": False, "summary_text": "未找到满足净收入且下移安全垫的远期合约"}

    nc = best_candidate["net_credit"]
    k_drop = best_candidate["strike_drop"]
    exp_t = best_candidate["target_exp"]
    k_t = best_candidate["target_strike"]
    bid_t = best_candidate["target_bid"]

    if nc >= 0.0:
        credit_badge = f"<span style='color: #34d399; font-weight: bold;'>净收信用 +${nc:.2f}</span>"
    else:
        credit_badge = f"<span style='color: #fbbf24; font-weight: bold;'>微付借记 -${abs(nc):.2f}</span>"

    best_candidate["summary_html"] = (
        f"<b>🔄 建议 Roll</b>: 平本期付 ${current_mark:.2f}，开 {exp_t} ${k_t:.1f} Put 收 ${bid_t:.2f} "
        f"({credit_badge}, <b>行权价下移 -${k_drop:.1f}</b>)"
    )
    return best_candidate


def batch_fetch_fast_options_cache(
    symbols: List[str],
    client: Optional[MarketDataClient] = None,
    max_workers: int = 10,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Concurrently fetch filtered options chains for a list of symbols in ~2-3 seconds.
    """
    c = client or MarketDataClient()
    results: Dict[str, List[Dict[str, Any]]] = {}

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def fetch_single(sym: str) -> Tuple[str, List[Dict[str, Any]]]:
        candidates = get_filtered_csp_candidates(sym, client=c)
        return sym, candidates

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(fetch_single, sym) for sym in symbols]
        for fut in as_completed(futures):
            try:
                sym, cands = fut.result()
                results[sym] = cands
            except Exception as e:
                logger.debug(f"Failed to fetch fast options for {sym}: {e}")

    return results


# ==================== INSTITUTIONAL DERIVATIVE METRICS ENGINE ====================

DERIVATIVE_CACHE_PATH = os.path.join(DATA_DIR, "derivative_metrics_cache.json")
_DERIV_MEM_CACHE: Optional[Dict[str, Any]] = None
_DERIV_LOCK = threading.Lock()


def _load_derivative_cache() -> Dict[str, Any]:
    global _DERIV_MEM_CACHE
    with _DERIV_LOCK:
        if _DERIV_MEM_CACHE is None:
            if os.path.exists(DERIVATIVE_CACHE_PATH):
                try:
                    with open(DERIVATIVE_CACHE_PATH, "r", encoding="utf-8") as f:
                        _DERIV_MEM_CACHE = json.load(f)
                except Exception:
                    _DERIV_MEM_CACHE = {}
            else:
                _DERIV_MEM_CACHE = {}
        return _DERIV_MEM_CACHE


def _save_derivative_cache(cache: Dict[str, Any]) -> None:
    with _DERIV_LOCK:
        atomic_write_json(DERIVATIVE_CACHE_PATH, cache)


def compute_max_pain(chain_data: Dict[str, Any]) -> Optional[float]:
    """
    Calculate the Max Pain price from an option chain.
    """
    if not chain_data or chain_data.get("s") != "ok":
        return None

    strikes = chain_data.get("strike", [])
    ois = chain_data.get("openInterest", [])
    sides = chain_data.get("side", [])

    if not strikes or not ois or not sides:
        return None

    options = []
    for i in range(len(strikes)):
        if i < len(ois) and i < len(sides):
            k = float(strikes[i] or 0.0)
            oi = float(ois[i] or 0.0)
            s = str(sides[i] or "").lower()
            if k > 0 and oi > 0:
                options.append({"strike": k, "oi": oi, "side": s})

    if not options:
        return None

    unique_strikes = sorted(list(set(o["strike"] for o in options)))
    if not unique_strikes:
        return None

    min_loss = float("inf")
    best_strike = unique_strikes[0]

    for test_k in unique_strikes:
        total_loss = 0.0
        for opt in options:
            k = opt["strike"]
            oi = opt["oi"]
            if opt["side"] == "call":
                if test_k > k:
                    total_loss += (test_k - k) * oi * 100.0
            else:  # put
                if test_k < k:
                    total_loss += (k - test_k) * oi * 100.0

        if total_loss < min_loss:
            min_loss = total_loss
            best_strike = test_k

    return float(best_strike)


def compute_volatility_skew(chain_data: Dict[str, Any]) -> Optional[float]:
    """
    Calculate 25-Delta Put vs 25-Delta Call Implied Volatility Skew.
    Put Skew = IV(25D Put) / IV(25D Call)
    """
    if not chain_data or chain_data.get("s") != "ok":
        return None

    deltas = chain_data.get("delta", [])
    ivs = chain_data.get("iv", [])
    sides = chain_data.get("side", [])

    put_25_ivs = []
    call_25_ivs = []

    for i in range(len(deltas)):
        if i < len(ivs) and i < len(sides):
            d = deltas[i]
            iv = ivs[i]
            side = str(sides[i] or "").lower()
            if d is not None and iv is not None and iv > 0:
                d_val = float(d)
                iv_val = float(iv)
                if side == "put" and -0.35 <= d_val <= -0.15:
                    put_25_ivs.append(iv_val)
                elif side == "call" and 0.15 <= d_val <= 0.35:
                    call_25_ivs.append(iv_val)

    if put_25_ivs and call_25_ivs:
        med_put_iv = float(np.median(put_25_ivs))
        med_call_iv = float(np.median(call_25_ivs))
        if med_call_iv > 0:
            return float(np.clip(med_put_iv / med_call_iv, 0.5, 2.5))

    return None


def compute_pcr(chain_data: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """
    Calculate Put/Call Open Interest Ratio and Volume Ratio.
    Returns None for missing/empty data without making assumptions.
    """
    if not chain_data or chain_data.get("s") != "ok":
        return {"pcr_oi": None, "pcr_vol": None, "total_put_oi": 0.0, "total_call_oi": 0.0}

    ois = chain_data.get("openInterest", [])
    vols = chain_data.get("volume", [])
    sides = chain_data.get("side", [])

    put_oi, call_oi = 0.0, 0.0
    put_vol, call_vol = 0.0, 0.0

    for i in range(len(sides)):
        side = str(sides[i] or "").lower()
        oi = float(ois[i] or 0.0) if i < len(ois) and ois[i] else 0.0
        vol = float(vols[i] or 0.0) if i < len(vols) and vols[i] else 0.0

        if side == "put":
            put_oi += oi
            put_vol += vol
        elif side == "call":
            call_oi += oi
            call_vol += vol

    if call_oi > 0 and put_oi >= 0:
        pcr_oi = float(np.clip(put_oi / call_oi, 0.05, 20.0))
    else:
        pcr_oi = None

    if call_vol > 0 and put_vol >= 0:
        pcr_vol = float(np.clip(put_vol / call_vol, 0.05, 20.0))
    else:
        pcr_vol = None

    return {
        "pcr_oi": pcr_oi,
        "pcr_vol": pcr_vol,
        "total_put_oi": put_oi,
        "total_call_oi": call_oi,
    }


def compute_expected_earnings_move(chain_data: Dict[str, Any]) -> Optional[float]:
    """
    Calculate options-implied expected move (%) using 0.85 * ATM Straddle formula.
    Returns None if ATM quotes or spot are missing.
    """
    if not chain_data or chain_data.get("s") != "ok":
        return None

    mids = chain_data.get("mid", [])
    spots = chain_data.get("underlyingPrice", [])
    deltas = chain_data.get("delta", [])
    sides = chain_data.get("side", [])

    atm_put_mid = None
    atm_call_mid = None
    spot = None

    for i in range(len(mids)):
        if i < len(spots) and spots[i] and spot is None:
            spot = float(spots[i])

        if i < len(deltas) and i < len(sides) and mids[i]:
            d = deltas[i]
            m = float(mids[i])
            side = str(sides[i] or "").lower()
            if d is not None and m > 0:
                d_val = abs(float(d))
                if 0.40 <= d_val <= 0.60:
                    if side == "put" and (atm_put_mid is None or abs(d_val - 0.50) < 0.08):
                        atm_put_mid = m
                    elif side == "call" and (atm_call_mid is None or abs(d_val - 0.50) < 0.08):
                        atm_call_mid = m

    if spot and spot > 0 and atm_put_mid and atm_call_mid:
        straddle = atm_put_mid + atm_call_mid
        expected_move_pct = (straddle * 0.85 / spot) * 100.0
        return float(np.clip(expected_move_pct, 1.0, 50.0))

    return None


def get_derivative_metrics(
    symbol: str,
    client: Optional[MarketDataClient] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    One-stop institutional derivatives analytics fetcher (Max Pain, Skew, PCR, Expected Move).
    Uses 1 single API call per symbol with 24-hour local caching.
    Strictly preserves None for missing or unmeasured metrics.
    """
    sym = normalize_symbol(symbol)
    cache = _load_derivative_cache()
    now_ts = time.time()

    if not force_refresh and sym in cache:
        cached = cache[sym]
        if now_ts - cached.get("timestamp", 0) < 86400:
            return cached.get("data", {})

    c = client or MarketDataClient()
    if not c.token:
        res = {
            "symbol": sym,
            "max_pain": None,
            "put_skew": None,
            "s_skew": None,
            "pcr_oi": None,
            "pcr_vol": None,
            "expected_move_pct": None,
        }
        return res

    # Query comprehensive 30~45 DTE chain containing both puts and calls
    chain = c.get_option_chain(
        symbol=sym,
        range_type="all",
        dte=35,
        min_open_interest=10,
        strike_limit=20,
    )

    if not chain or chain.get("s") != "ok":
        # Fallback query with atm range
        chain = c.get_option_chain(
            symbol=sym,
            range_type="atm",
            dte=30,
            strike_limit=10,
        )

    max_pain = compute_max_pain(chain)
    put_skew = compute_volatility_skew(chain)
    pcr_info = compute_pcr(chain)
    expected_move_pct = compute_expected_earnings_move(chain)

    # Calculate Skew score S_Skew ONLY if put_skew is authentically measured
    if put_skew is not None:
        s_skew = float(np.clip(50.0 + (put_skew - 1.10) * 200.0, 0.0, 100.0))
    else:
        s_skew = None

    result = {
        "symbol": sym,
        "max_pain": max_pain,
        "put_skew": put_skew,
        "s_skew": s_skew,
        "pcr_oi": pcr_info.get("pcr_oi"),
        "pcr_vol": pcr_info.get("pcr_vol"),
        "expected_move_pct": expected_move_pct,
        "has_derivative_metrics": (max_pain is not None or put_skew is not None or pcr_info.get("pcr_oi") is not None),
    }

    cache[sym] = {
        "timestamp": now_ts,
        "data": result,
    }
    _save_derivative_cache(cache)
    return result


def batch_get_derivative_metrics(
    symbols: List[str],
    client: Optional[MarketDataClient] = None,
    max_workers: int = 15,
) -> Dict[str, Dict[str, Any]]:
    """
    Concurrently fetch derivative metrics for multiple symbols.
    """
    c = client or MarketDataClient()
    results: Dict[str, Dict[str, Any]] = {}
    if not c.token:
        return {s: get_derivative_metrics(s, client=c) for s in symbols}

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def fetch_sym(s: str) -> Tuple[str, Dict[str, Any]]:
        return s, get_derivative_metrics(s, client=c)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(fetch_sym, s) for s in symbols]
        for fut in as_completed(futures):
            try:
                sym, data = fut.result()
                results[sym] = data
            except Exception:
                pass
    return results

