# -*- coding: utf-8 -*-
"""
Portfolio Risk & Position Management Engine
===========================================
Delta-adjusted notional exposure, leverage ratio monitoring, IRS Wash Sale
risk tracking, and InvestSkill-linked Assignment vs Exit Decision Matrix.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from option_quant.config import (
    BASE_DIR,
    DATA_DIR,
    atomic_write_json,
    is_etf_symbol,
    normalize_symbol,
    to_display_symbol,
)

logger = logging.getLogger("option_quant.portfolio")


def calculate_portfolio_delta_exposure(spot_prices: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """
    Calculates portfolio-wide delta-adjusted notional exposure and leverage ratio.

    Returns:
        Dictionary containing detailed exposures, total notional, net liquidity,
        leverage ratio, and risk status.
    """
    positions_file = os.path.join(DATA_DIR, "current_positions.json")
    equity_file = os.path.join(DATA_DIR, "current_equity_positions.json")
    account_file = os.path.join(DATA_DIR, "account_info.json")
    m_cache_file = os.path.join(DATA_DIR, "market_history_cache.json")
    portfolio_file = os.path.join(DATA_DIR, "mcp_portfolio.json")

    opt_positions: List[Dict[str, Any]] = []
    if os.path.exists(positions_file):
        try:
            with open(positions_file, "r", encoding="utf-8") as f:
                opt_positions = json.load(f).get("positions", [])
        except Exception:
            pass

    equity_positions: List[Dict[str, Any]] = []
    if os.path.exists(equity_file):
        try:
            with open(equity_file, "r", encoding="utf-8") as f:
                equity_positions = json.load(f).get("equity_positions", [])
        except Exception:
            pass

    account_info: Dict[str, Any] = {}
    if os.path.exists(account_file):
        try:
            with open(account_file, "r", encoding="utf-8") as f:
                account_info = json.load(f)
        except Exception:
            pass

    cached_m: Dict[str, Any] = {}
    if os.path.exists(m_cache_file):
        try:
            with open(m_cache_file, "r", encoding="utf-8") as f:
                cached_m = json.load(f)
        except Exception:
            pass

    if spot_prices is None:
        spot_prices = {}

    for p in opt_positions:
        sym = p.get("symbol")
        if sym and sym not in spot_prices:
            spot_prices[sym] = float(cached_m.get(sym, {}).get("current_price", p.get("strike", 100.0)))

    for ep in equity_positions:
        sym = ep.get("symbol")
        if sym and sym not in spot_prices:
            spot_prices[sym] = float(cached_m.get(sym, {}).get("current_price", ep.get("average_buy_price", 100.0)))

    detailed_results: List[Dict[str, Any]] = []
    total_delta_notional = 0.0
    total_full_notional = 0.0
    total_equity_value = 0.0
    total_gamma_notional = 0.0

    # 1. Process Options
    for p in opt_positions:
        sym = p.get("symbol", "")
        strike = float(p.get("strike", 0.0))
        qty = float(p.get("quantity", 1.0))
        opt_type = p.get("type", "put").lower()
        delta = float(p.get("delta", -0.25))
        gamma = float(p.get("gamma", 0.0))
        spot = float(spot_prices.get(sym, strike))

        # Position Delta for Short Option: -delta * qty * 100
        pos_delta_shares = -delta * qty * 100.0
        pos_delta_notional = pos_delta_shares * spot
        pos_full_notional = (strike * qty * 100.0) if opt_type == "put" else 0.0

        # Position Gamma Notional ($ Delta change per 1% spot move)
        pos_gamma_notional = abs(gamma) * qty * 100.0 * (spot ** 2) * 0.01

        total_delta_notional += pos_delta_notional
        total_full_notional += pos_full_notional
        total_gamma_notional += pos_gamma_notional

        detailed_results.append({
            "symbol": sym,
            "type": f"Short {opt_type.upper()}",
            "strike": strike,
            "expiration": p.get("expiration"),
            "quantity": qty,
            "delta": delta,
            "gamma": gamma,
            "spot_price": spot,
            "delta_shares": pos_delta_shares,
            "delta_notional": pos_delta_notional,
            "gamma_notional": pos_gamma_notional,
            "full_notional": pos_full_notional,
        })

    # 2. Process Equities (Delta = +1.0)
    for ep in equity_positions:
        sym = ep.get("symbol", "")
        qty = float(ep.get("quantity", 0.0))
        spot = float(spot_prices.get(sym, ep.get("average_buy_price", 100.0)))
        eq_val = qty * spot
        total_equity_value += eq_val
        total_delta_notional += eq_val
        total_full_notional += eq_val

        detailed_results.append({
            "symbol": sym,
            "type": "Stock (Long)",
            "strike": spot,
            "expiration": "N/A",
            "quantity": qty,
            "delta": 1.0,
            "spot_price": spot,
            "delta_shares": qty,
            "delta_notional": eq_val,
            "full_notional": eq_val,
        })

    # 3. Calculate Net Liquidity & Leverage Ratio
    unleveraged_cash = float(account_info.get("cash_available", 0.0))
    total_collateral = float(account_info.get("total_collateral", 0.0))
    net_liquidity = unleveraged_cash + total_collateral + total_equity_value

    if os.path.exists(portfolio_file):
        try:
            with open(portfolio_file, "r", encoding="utf-8") as f:
                port_data = json.load(f).get("data", {})
                equity_mkt = float(port_data.get("equity", 0.0))
                if equity_mkt > 0:
                    net_liquidity = equity_mkt
        except Exception:
            pass

    leverage_ratio = (total_delta_notional / net_liquidity) if net_liquidity > 0 else 0.0

    if leverage_ratio <= 0.40:
        status_label = "🟢 稳健防守"
        status_color = "#34d399"
    elif leverage_ratio <= 0.75:
        status_label = "🟢 标准健康"
        status_color = "#34d399"
    elif leverage_ratio <= 1.00:
        status_label = "🟡 接近满仓"
        status_color = "#fbbf24"
    else:
        status_label = "🔴 杠杆偏高"
        status_color = "#f87171"

    summary = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_delta_notional": total_delta_notional,
        "total_gamma_notional": total_gamma_notional,
        "total_full_notional": total_full_notional,
        "total_equity_value": total_equity_value,
        "net_liquidity": net_liquidity,
        "leverage_ratio": leverage_ratio,
        "status_label": status_label,
        "status_color": status_color,
        "positions": detailed_results,
    }

    out_file = os.path.join(DATA_DIR, "portfolio_delta_exposure.json")
    atomic_write_json(out_file, summary)
    return summary


def get_wash_sale_risks(today: Optional[datetime.date] = None) -> Tuple[Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
    """
    Parse trade PnL history to detect Wash Sale restrictions in the past 30 days.

    Returns:
        (wash_sale_history_map, floating_loss_positions)
    """
    if today is None:
        today = datetime.date.today()

    wash_sale_history_map: Dict[str, List[Dict[str, Any]]] = {}
    trade_pnl_file = os.path.join(DATA_DIR, "trade_pnl_history.json")

    if os.path.exists(trade_pnl_file):
        try:
            with open(trade_pnl_file, "r", encoding="utf-8") as f:
                pnl_data = json.load(f)
                for tr in pnl_data.get("trades", []):
                    sym = to_display_symbol(tr.get("symbol", ""))
                    rg = float(tr.get("realized_gain", 0.0))
                    ts_str = tr.get("timestamp", "")
                    if rg < 0 and ts_str:
                        tr_dt = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00")).date()
                        days_diff = (today - tr_dt).days
                        if 0 <= days_diff <= 30:
                            unlock_dt = tr_dt + datetime.timedelta(days=31)
                            if sym not in wash_sale_history_map:
                                wash_sale_history_map[sym] = []
                            wash_sale_history_map[sym].append({
                                "loss": rg,
                                "trade_date": tr_dt.strftime("%Y-%m-%d"),
                                "unlock_date": unlock_dt.strftime("%Y-%m-%d"),
                                "days_ago": days_diff,
                            })
        except Exception as e:
            logger.warning(f"Failed to parse trade_pnl_history.json: {e}")

    # Load floating loss positions
    floating_loss_positions: List[Dict[str, Any]] = []
    positions_file = os.path.join(DATA_DIR, "current_positions.json")
    if os.path.exists(positions_file):
        try:
            with open(positions_file, "r", encoding="utf-8") as f:
                for pos in json.load(f).get("positions", []):
                    open_p = float(pos.get("open_price", 0.0))
                    curr_p = float(pos.get("current_price", open_p))
                    pnl = open_p - curr_p
                    if pnl < 0:
                        floating_loss_positions.append(pos)
        except Exception:
            pass

    return wash_sale_history_map, floating_loss_positions
