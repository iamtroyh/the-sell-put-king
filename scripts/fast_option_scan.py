#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
High-Speed Option Scanner & Cache Builder (Robinhood Native + yfinance Fallback)
================================================================================
Fetches real-time option chains and clearinghouse Greeks directly via Robinhood MCP,
augmented by concurrent yfinance options engine for broad-universe coverage.
Completely replaces external third-party MarketData.app API dependencies.
"""

import datetime
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Set, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from option_quant.config import (
    DATA_DIR,
    atomic_write_json,
    load_json_config,
    normalize_symbol,
    to_display_symbol,
    to_yf_symbol,
)
from option_quant.mcp_client import RobinhoodMCPClient
from option_quant.scoring import calculate_call_delta, calculate_put_delta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fast_scan")

CORE_UNIVERSE = [
    "IBIT", "BRK.B", "SPYM", "ASHR", "QQQM", "IWM", "VTV", "TLT", "XLV", "XLP", "XLE",
    "AAPL", "NVDA", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AMD", "QCOM", "AVGO", "INTC",
]


def _is_monthly_exp_date(d: datetime.date) -> bool:
    """Standard US monthly expiration: 3rd Friday (days 15-21) or 3rd Thursday (days 14-20)."""
    return (d.weekday() == 4 and (15 <= d.day <= 21)) or (d.weekday() == 3 and (14 <= d.day <= 20))


def _is_monthly_exp_str(exp_str: str) -> bool:
    try:
        d = datetime.datetime.strptime(exp_str, "%Y-%m-%d").date()
        return _is_monthly_exp_date(d)
    except Exception:
        return False


def _fetch_yfinance_symbol_options(
    sym: str,
    target_exps: List[str],
    spot_price: float,
    dte_map: Dict[str, int],
    is_cc: bool = False,
    avg_buy_price: float = 0.0,
) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Fallback / fast parallel worker using yfinance."""
    import yfinance as yf

    puts_out: List[Dict[str, Any]] = []
    calls_out: List[Dict[str, Any]] = []

    try:
        yf_sym = to_yf_symbol(sym)
        t_obj = yf.Ticker(yf_sym)

        for exp in target_exps:
            dte = dte_map.get(exp, 30)
            if dte <= 0:
                continue

            try:
                chain = t_obj.option_chain(exp)
            except Exception:
                continue

            # Process Puts
            if chain.puts is not None and not chain.puts.empty:
                for _, row in chain.puts.iterrows():
                    strike = float(row.get("strike", 0.0))
                    bid = float(row.get("bid", 0.0) or 0.0)
                    ask = float(row.get("ask", 0.0) or 0.0)
                    oi = int(row.get("openInterest", 0) or 0)
                    iv = float(row.get("impliedVolatility", 0.0) or 0.0)

                    # Strike filter: 0.65x ~ 0.98x spot for Sell Put candidates, or near ATM
                    if spot_price > 0 and not (0.65 * spot_price <= strike <= 0.98 * spot_price or abs(strike - spot_price) / spot_price < 0.03):
                        continue

                    t_years = max(1, dte) / 365.0
                    delta = calculate_put_delta(spot_price, strike, t_years, sigma=iv if iv > 0 else 0.30)
                    if not (-0.50 <= delta <= -0.05):
                        continue

                    puts_out.append({
                        "strike": strike,
                        "expiration": exp,
                        "bid": bid,
                        "ask": ask,
                        "openInterest": oi,
                        "impliedVolatility": iv,
                        "delta": float(delta),
                        "gamma": 0.0,
                        "theta": 0.0,
                        "vega": 0.0,
                        "instrument_id": f"yf_{sym}_{exp}_{strike}_p",
                    })

            # Process Calls if Covered Call candidate
            if is_cc and chain.calls is not None and not chain.calls.empty:
                for _, row in chain.calls.iterrows():
                    strike = float(row.get("strike", 0.0))
                    bid = float(row.get("bid", 0.0) or 0.0)
                    ask = float(row.get("ask", 0.0) or 0.0)
                    oi = int(row.get("openInterest", 0) or 0)
                    iv = float(row.get("impliedVolatility", 0.0) or 0.0)

                    if strike < avg_buy_price or (spot_price > 0 and strike > spot_price * 1.30):
                        continue

                    t_years = max(1, dte) / 365.0
                    delta = calculate_call_delta(spot_price, strike, t_years, sigma=iv if iv > 0 else 0.30)
                    if not (0.05 <= delta <= 0.45):
                        continue

                    calls_out.append({
                        "strike": strike,
                        "expiration": exp,
                        "bid": bid,
                        "ask": ask,
                        "openInterest": oi,
                        "impliedVolatility": iv,
                        "delta": float(delta),
                        "gamma": 0.0,
                        "theta": 0.0,
                        "vega": 0.0,
                        "instrument_id": f"yf_{sym}_{exp}_{strike}_c",
                    })

    except Exception as e:
        logger.debug(f"yfinance options extraction failed for {sym}: {e}")

    return sym, puts_out, calls_out


def run_fast_scan(symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Execute high-speed option scan:
      1. Primary: Robinhood MCP clearinghouse data (exact quotes, Delta, and COP).
      2. Secondary: Parallel yfinance engine for broader market targets.
      3. Compiles directly to data/robinhood_options_cache.json.
    """
    start_t = time.time()
    today = datetime.date.today()

    targets_file = os.path.join(DATA_DIR, "scan_targets.json")
    positions_file = os.path.join(DATA_DIR, "current_positions.json")
    equity_positions_file = os.path.join(DATA_DIR, "current_equity_positions.json")
    cache_file = os.path.join(DATA_DIR, "robinhood_options_cache.json")

    t_data = load_json_config(targets_file) if os.path.exists(targets_file) else {}
    sell_put_targets = t_data.get("sell_put", {}) if isinstance(t_data, dict) else {}
    covered_call_targets = t_data.get("covered_call", {}) if isinstance(t_data, dict) else {}

    # Load active held positions (Mandatory inclusion)
    held_symbols: Set[str] = set()
    if os.path.exists(positions_file):
        try:
            pos_data = load_json_config(positions_file).get("positions", [])
            for p in pos_data:
                s = normalize_symbol(p.get("symbol"))
                if s:
                    held_symbols.add(s)
        except Exception:
            pass

    cc_symbols: Dict[str, float] = {}
    if os.path.exists(equity_positions_file):
        try:
            eq_data = load_json_config(equity_positions_file).get("equity_positions", [])
            for eq in eq_data:
                s = normalize_symbol(eq.get("symbol"))
                qty = float(eq.get("quantity", 0.0))
                avg_b = float(eq.get("average_buy_price", 0.0))
                if s and qty >= 100.0:
                    cc_symbols[s] = avg_b
                    held_symbols.add(s)
        except Exception:
            pass

    # Resolve target symbols
    if symbols:
        target_symbols = list(set([normalize_symbol(s) for s in symbols if s]))
    else:
        all_syms = set(held_symbols)
        all_syms.update(sell_put_targets.keys())
        all_syms.update(covered_call_targets.keys())
        all_syms.update(CORE_UNIVERSE)
        target_symbols = list(all_syms)

    # Filter out single share price > $1000 USD (unless held)
    filtered_symbols: List[str] = []
    for s in target_symbols:
        p = float(sell_put_targets.get(s, {}).get("current_price", 0.0))
        if p > 1000.0 and s not in held_symbols:
            continue
        filtered_symbols.append(s)

    logger.info(f"⚡ Starting Robinhood Native Option Scan for {len(filtered_symbols)} symbols...")

    existing_cache = load_json_config(cache_file) if os.path.exists(cache_file) else {}
    if not isinstance(existing_cache, dict):
        existing_cache = {}

    total_contracts_found = 0
    rh_scanned_symbols: Set[str] = set()

    # Prioritize top symbols for Robinhood MCP clearinghouse data:
    # All held symbols + Core Universe + top 25 candidate targets
    rh_priority_symbols = list(held_symbols)
    for s in CORE_UNIVERSE:
        if s not in rh_priority_symbols and s in filtered_symbols:
            rh_priority_symbols.append(s)
    for s in filtered_symbols:
        if s not in rh_priority_symbols:
            rh_priority_symbols.append(s)
        if len(rh_priority_symbols) >= 40:
            break

    # ==================== STAGE 1: ROBINHOOD MCP CLEARING ENGINE ====================
    try:
        with RobinhoodMCPClient(request_timeout=25.0) as rh_client:
            inst_to_meta: Dict[str, Dict[str, Any]] = {}

            for sym in rh_priority_symbols:
                t_info = sell_put_targets.get(sym, {})
                exps = t_info.get("expirations", [])
                spot = float(t_info.get("current_price", 0.0))

                # Find candidate monthly expirations in 15~65 DTE range
                valid_exps: List[str] = []
                for e in exps:
                    try:
                        ed = datetime.datetime.strptime(e, "%Y-%m-%d").date()
                        dte = (ed - today).days
                        if 15 <= dte <= 65 and _is_monthly_exp_date(ed):
                            valid_exps.append(e)
                    except Exception:
                        pass

                if not valid_exps:
                    # Fallback to any valid 15~65 DTE expirations
                    for e in exps:
                        try:
                            ed = datetime.datetime.strptime(e, "%Y-%m-%d").date()
                            if 15 <= (ed - today).days <= 65:
                                valid_exps.append(e)
                        except Exception:
                            pass

                target_exps = valid_exps[:2] if valid_exps else None
                if not target_exps:
                    continue

                # Query Put instruments
                try:
                    puts_insts = rh_client.get_option_instruments(
                        chain_symbol=sym,
                        expiration_dates=target_exps,
                        opt_type="put",
                    )
                    for it in puts_insts:
                        inst_id = it.get("id")
                        k = float(it.get("strike_price", 0.0))
                        exp = it.get("expiration_date")
                        if not inst_id or k <= 0:
                            continue

                        # Strike filter: roughly 0.68x ~ 0.98x spot or ATM
                        if spot > 0:
                            is_target_strike = (0.68 * spot <= k <= 0.98 * spot) or (abs(k - spot) / spot < 0.03)
                            if not is_target_strike:
                                continue

                        inst_to_meta[inst_id] = {
                            "symbol": sym,
                            "expiration": exp,
                            "strike": k,
                            "type": "put",
                        }
                except Exception as e:
                    logger.debug(f"RH instrument lookup error for {sym} puts: {e}")

                # Query Call instruments if eligible for Covered Call
                if sym in cc_symbols:
                    avg_b = cc_symbols[sym]
                    try:
                        calls_insts = rh_client.get_option_instruments(
                            chain_symbol=sym,
                            expiration_dates=target_exps,
                            opt_type="call",
                        )
                        for it in calls_insts:
                            inst_id = it.get("id")
                            k = float(it.get("strike_price", 0.0))
                            exp = it.get("expiration_date")
                            if not inst_id or k < avg_b:
                                continue
                            if spot > 0 and k > spot * 1.30:
                                continue

                            inst_to_meta[inst_id] = {
                                "symbol": sym,
                                "expiration": exp,
                                "strike": k,
                                "type": "call",
                            }
                    except Exception as e:
                        logger.debug(f"RH instrument lookup error for {sym} calls: {e}")

                rh_scanned_symbols.add(sym)

            # Batch fetch quotes in chunks of 40
            all_ids = list(inst_to_meta.keys())
            if all_ids:
                logger.info(f"📥 Querying live Robinhood quotes for {len(all_ids)} candidate instruments across {len(rh_scanned_symbols)} symbols...")
                batch_size = 40
                batches = [all_ids[i:i + batch_size] for i in range(0, len(all_ids), batch_size)]

                for b in batches:
                    quotes = rh_client.get_option_quotes(b)
                    for q in quotes:
                        inst_id = q.get("instrument_id")
                        meta = inst_to_meta.get(inst_id)
                        if not meta:
                            continue

                        sym = meta["symbol"]
                        exp = meta["expiration"]
                        k = meta["strike"]
                        opt_type = meta["type"]

                        bid = float(q.get("bid_price", 0.0) or 0.0)
                        ask = float(q.get("ask_price", 0.0) or 0.0)
                        mark = float(q.get("mark_price", 0.0) or 0.0)
                        oi = int(q.get("open_interest", 0) or 0)
                        iv = float(q.get("implied_volatility", 0.0) or 0.0)
                        delta = float(q.get("delta", 0.0) or 0.0)
                        gamma = float(q.get("gamma", 0.0) or 0.0)
                        theta = float(q.get("theta", 0.0) or 0.0)
                        vega = float(q.get("vega", 0.0) or 0.0)
                        cop = float(q.get("chance_of_profit_short", 0.0) or 0.0)

                        if sym not in existing_cache:
                            existing_cache[sym] = {}
                        if exp not in existing_cache[sym]:
                            existing_cache[sym][exp] = {"puts": [], "calls": []}

                        entry = {
                            "strike": k,
                            "bid": bid,
                            "ask": ask,
                            "mark": mark,
                            "openInterest": oi,
                            "impliedVolatility": iv,
                            "delta": delta,
                            "gamma": gamma,
                            "theta": theta,
                            "vega": vega,
                            "chance_of_profit_short": cop,
                            "instrument_id": inst_id,
                        }

                        target_list = existing_cache[sym][exp]["puts"] if opt_type == "put" else existing_cache[sym][exp]["calls"]
                        # Upsert strike
                        updated = [item for item in target_list if item["strike"] != k]
                        updated.append(entry)
                        if opt_type == "put":
                            existing_cache[sym][exp]["puts"] = updated
                        else:
                            existing_cache[sym][exp]["calls"] = updated

                        total_contracts_found += 1

    except Exception as e:
        logger.warning(f"Robinhood MCP scanning encountered non-fatal error: {e}")

    # ==================== STAGE 2: PARALLEL YFINANCE BROAD SCANNER ====================
    remaining_symbols = [s for s in filtered_symbols if s not in rh_scanned_symbols]
    if remaining_symbols:
        logger.info(f"🌐 Supplementing remaining {len(remaining_symbols)} universe symbols via parallel yfinance engine...")
        yf_futures = []

        with ThreadPoolExecutor(max_workers=12) as pool:
            for s in remaining_symbols:
                t_info = sell_put_targets.get(s, {})
                exps = t_info.get("expirations", [])
                spot = float(t_info.get("current_price", 0.0))

                valid_exps = []
                dte_map: Dict[str, int] = {}
                for e in exps:
                    try:
                        ed = datetime.datetime.strptime(e, "%Y-%m-%d").date()
                        dte = (ed - today).days
                        if 15 <= dte <= 65:
                            valid_exps.append(e)
                            dte_map[e] = dte
                    except Exception:
                        pass

                # Monthly first
                monthlies = [e for e in valid_exps if _is_monthly_exp_str(e)]
                target_exps = monthlies[:2] if monthlies else valid_exps[:2]

                if target_exps:
                    is_cc = s in cc_symbols
                    avg_b = cc_symbols.get(s, 0.0)
                    yf_futures.append(pool.submit(
                        _fetch_yfinance_symbol_options,
                        s,
                        target_exps,
                        spot,
                        dte_map,
                        is_cc,
                        avg_b,
                    ))

            for fut in as_completed(yf_futures):
                try:
                    s, puts_out, calls_out = fut.result()
                    if not puts_out and not calls_out:
                        continue

                    if s not in existing_cache:
                        existing_cache[s] = {}

                    for p in puts_out:
                        exp = p["expiration"]
                        if exp not in existing_cache[s]:
                            existing_cache[s][exp] = {"puts": [], "calls": []}
                        existing_cache[s][exp]["puts"] = [
                            item for item in existing_cache[s][exp]["puts"] if item["strike"] != p["strike"]
                        ] + [p]
                        total_contracts_found += 1

                    for c in calls_out:
                        exp = c["expiration"]
                        if exp not in existing_cache[s]:
                            existing_cache[s][exp] = {"puts": [], "calls": []}
                        existing_cache[s][exp]["calls"] = [
                            item for item in existing_cache[s][exp]["calls"] if item["strike"] != c["strike"]
                        ] + [c]
                        total_contracts_found += 1

                except Exception as e:
                    logger.debug(f"Error merging yfinance options: {e}")

    # Sort strikes in cache
    for sym in existing_cache:
        for exp in existing_cache[sym]:
            if "puts" in existing_cache[sym][exp]:
                existing_cache[sym][exp]["puts"].sort(key=lambda x: x["strike"])
            if "calls" in existing_cache[sym][exp]:
                existing_cache[sym][exp]["calls"].sort(key=lambda x: x["strike"])

    atomic_write_json(cache_file, existing_cache)
    elapsed = time.time() - start_t
    logger.info(
        f"✅ Fast option scan complete in {elapsed:.2f}s! Synchronized {total_contracts_found} contracts across "
        f"{len(existing_cache)} tickers into {cache_file}."
    )
    return existing_cache


if __name__ == "__main__":
    run_fast_scan()
