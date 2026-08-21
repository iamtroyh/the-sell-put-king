# -*- coding: utf-8 -*-
"""
Option Research & Automation Pipeline
=====================================
Master orchestrator for Robinhood data synchronization, market scanning,
multi-factor scoring, InvestSkill report integration, and HTML generation.
"""

from __future__ import annotations

import datetime
import html
import json
import logging
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

from option_quant.config import (
    BASE_DIR,
    DATA_DIR,
    INVESTSKILL_DIR,
    INVESTSKILL_OUTPUT_DIR,
    PRESELECTED_TICKERS,
    BROAD_TICKERS,
    RISK_FREE_RATE,
    SECTOR_MAP,
    TICKER_EXCHANGE_MAP,
    TICKER_FUNDAMENTALS,
    TICKER_INTROS,
    TICKER_RISKS,
    atomic_write_json,
    get_scan_parameters,
    get_tradingview_url,
    is_etf_symbol,
    is_high_vol_growth,
    is_long_bull,
    load_json_config,
    mask_account_id,
    normalize_symbol,
    to_display_symbol,
    to_rh_symbol,
    to_yf_symbol,
)
from option_quant.investskill import scan_investskill_reports
from option_quant.market_data import (
    batch_get_insider_sentiment,
    calculate_piotroski_f_score,
    check_eva_and_moat,
    check_is_low_position,
    check_macro_circuit_breaker,
    fetch_btc_price,
    fetch_chart_df,
    get_insider_sentiment,
)
from option_quant.mcp_client import RobinhoodMCPClient
from option_quant.portfolio import calculate_portfolio_delta_exposure, get_wash_sale_risks
from option_quant.scoring import (
    calculate_call_delta,
    calculate_covered_call_score,
    calculate_put_delta,
    calculate_sell_put_score,
    get_recommendation_reason,
)

logger = logging.getLogger("option_quant.pipeline")


# ==================== STEP 1: SYNC ACCOUNT DATA ====================

def sync_account_data(client: Optional[RobinhoodMCPClient] = None) -> Dict[str, Any]:
    """
    Fetch live Robinhood balances, equity holdings, option positions, instruments, and quotes.
    Writes:
      - data/mcp_portfolio.json
      - data/mcp_equity_positions.json
      - data/mcp_option_positions.json
      - data/current_positions.json
      - data/current_equity_positions.json
      - data/account_info.json
    """
    logger.info("Starting Robinhood account & positions synchronization...")

    def _sync(c: RobinhoodMCPClient):
        # 1. Portfolio
        portfolio_res = c.get_portfolio()
        if portfolio_res:
            atomic_write_json(os.path.join(DATA_DIR, "mcp_portfolio.json"), portfolio_res)

        # 2. Equity Positions
        equity_res = c.get_equity_positions()
        if equity_res:
            atomic_write_json(os.path.join(DATA_DIR, "mcp_equity_positions.json"), equity_res)

        # 3. Option Positions
        options_res = c.get_option_positions(nonzero=True)
        if options_res:
            atomic_write_json(os.path.join(DATA_DIR, "mcp_option_positions.json"), options_res)

        # 4. Instruments & Quotes for active options
        option_ids = []
        positions = options_res.get("data", {}).get("positions", []) if options_res else []
        for pos in positions:
            opt_id = pos.get("option_id")
            if opt_id and float(pos.get("quantity", 0)) > 0:
                option_ids.append(opt_id)

        inst_res = None
        quotes_res = None
        if option_ids:
            inst_res = c.get_option_instruments(ids=option_ids)
            if inst_res:
                atomic_write_json(os.path.join(DATA_DIR, "mcp_active_instruments.json"), {"data": {"instruments": inst_res}})
            quotes_res = c.get_option_quotes(option_ids)
            if quotes_res:
                atomic_write_json(os.path.join(DATA_DIR, "mcp_active_quotes.json"), {"data": {"results": [{"quote": q} for q in quotes_res]}})

        # 5. Transform and normalize to current_positions.json & current_equity_positions.json
        inst_map = {inst["id"]: inst for inst in (inst_res or [])}
        quote_map = {q["instrument_id"]: q for q in (quotes_res or []) if q.get("instrument_id")}

        today = datetime.date.today()

        # Equity positions
        equity_positions = []
        num_potential_cc = 0
        eq_list = equity_res.get("data", {}).get("positions", []) if equity_res else []
        for pos in eq_list:
            symbol = normalize_symbol(pos.get("symbol"))
            qty = float(pos.get("quantity", 0.0))
            avg_buy = float(pos.get("average_buy_price", 0.0))
            if qty > 0:
                equity_positions.append({
                    "symbol": symbol,
                    "quantity": qty,
                    "average_buy_price": avg_buy,
                })
                if qty >= 100.0:
                    num_potential_cc += 1

        atomic_write_json(os.path.join(DATA_DIR, "current_equity_positions.json"), {"equity_positions": equity_positions})

        # Options positions
        detailed_positions = []
        total_collateral = 0.0
        portfolio_theta = 0.0
        num_short_puts = 0

        for pos in positions:
            opt_id = pos.get("option_id")
            qty = float(pos.get("quantity", 0.0))
            if qty <= 0.0 or not opt_id:
                continue

            avg_price = float(pos.get("average_price", 0.0))
            pos_type = pos.get("type", "short")
            multiplier = float(pos.get("trade_value_multiplier", 100.0))

            inst = inst_map.get(opt_id)
            if not inst:
                continue

            sym = normalize_symbol(inst.get("chain_symbol"))
            opt_type = inst.get("type")
            strike = float(inst.get("strike_price", 0.0))
            exp_str = inst.get("expiration_date", "")
            try:
                exp_date = datetime.datetime.strptime(exp_str, "%Y-%m-%d").date()
                dte = (exp_date - today).days
            except Exception:
                dte = 30

            open_price = abs(avg_price) / multiplier
            q = quote_map.get(opt_id, {})
            bid = float(q.get("bid_price", 0.0))
            ask = float(q.get("ask_price", 0.0))
            mark = (bid + ask) / 2.0 if (bid + ask) > 0 else float(q.get("last_trade_price", open_price))
            delta = float(q.get("delta", 0.0))
            theta = float(q.get("theta", 0.0))

            detailed_positions.append({
                "symbol": sym,
                "option_id": opt_id,
                "strike": strike,
                "expiration": exp_str,
                "type": opt_type,
                "quantity": qty,
                "open_price": open_price,
                "current_price": mark,
                "dte": dte,
                "delta": delta,
            })

            if pos_type == "short":
                if opt_type == "put":
                    total_collateral += strike * qty * multiplier
                    num_short_puts += int(qty)
                portfolio_theta += -theta * qty * multiplier
            else:
                portfolio_theta += theta * qty * multiplier

        detailed_positions.sort(key=lambda x: x["dte"])
        atomic_write_json(os.path.join(DATA_DIR, "current_positions.json"), {"positions": detailed_positions})

        portfolio = portfolio_res.get("data", {}) if portfolio_res else {}
        unleveraged_buying_power = float(portfolio.get("buying_power", {}).get("unleveraged_buying_power", 0.0))

        account_info = {
            "total_collateral": total_collateral,
            "cash_available": unleveraged_buying_power,
            "active_options": f"{num_short_puts} <span style=\"font-size: 13px; font-weight: normal; color: var(--text-secondary);\">Short Puts</span>",
            "active_options_sub": f"{num_potential_cc} 笔潜在 Covered Call",
            "portfolio_theta": portfolio_theta,
        }
        atomic_write_json(os.path.join(DATA_DIR, "account_info.json"), account_info)
        delta_exp = calculate_portfolio_delta_exposure()

        return {
            "account_info": account_info,
            "positions_count": len(detailed_positions),
            "equity_count": len(equity_positions),
            "delta_exposure": delta_exp,
        }

    if client:
        return _sync(client)
    else:
        with RobinhoodMCPClient() as c:
            return _sync(c)


# ==================== STEP 2: GET SCAN TARGETS ====================

def get_scan_targets(max_workers: int = 20) -> Dict[str, Any]:
    """
    Scan broad market and current positions to determine active candidate tickers and target expirations.
    Writes: data/scan_targets.json
    """
    today = datetime.date.today()
    params = get_scan_parameters()
    dte_min = params["dte_min"]
    dte_max = params["dte_max"]
    cc_dte_max = params["cc_dte_max"]
    max_stock_price = float(params.get("max_stock_price", 1000.0))

    # Load positions
    positions_file = os.path.join(DATA_DIR, "current_positions.json")
    equity_positions_file = os.path.join(DATA_DIR, "current_equity_positions.json")
    fund_cache_path = os.path.join(DATA_DIR, "fundamental_cache.json")

    current_positions = []
    if os.path.exists(positions_file):
        try:
            with open(positions_file, "r", encoding="utf-8") as f:
                current_positions = json.load(f).get("positions", [])
        except Exception:
            pass

    held_symbols: Set[str] = {to_display_symbol(pos["symbol"]) for pos in current_positions}

    equity_info_map: Dict[str, Dict[str, float]] = {}
    if os.path.exists(equity_positions_file):
        try:
            with open(equity_positions_file, "r", encoding="utf-8") as f:
                for pos in json.load(f).get("equity_positions", []):
                    equity_info_map[to_display_symbol(pos["symbol"])] = {
                        "average_buy_price": float(pos["average_buy_price"]),
                        "quantity": float(pos["quantity"]),
                    }
        except Exception:
            pass

    fund_cache = {}
    if os.path.exists(fund_cache_path):
        try:
            with open(fund_cache_path, "r", encoding="utf-8") as f:
                fund_cache = json.load(f)
        except Exception:
            pass

    active_tickers: Dict[str, str] = {}
    for pos in current_positions:
        active_tickers[to_display_symbol(pos["symbol"])] = to_yf_symbol(pos["symbol"])
    for pre in PRESELECTED_TICKERS:
        active_tickers[to_display_symbol(pre)] = to_yf_symbol(pre)

    ticker_history_cache: Dict[str, Tuple[Optional[yf.Ticker], Optional[pd.DataFrame], Tuple[str, ...]]] = {}

    def fetch_single_ticker(yf_symbol: str):
        try:
            ticker = yf.Ticker(yf_symbol)
            hist = ticker.history(period="1y").dropna(subset=['Close'])
            try:
                options = ticker.options
            except Exception:
                options = ()
            return yf_symbol, (ticker, hist, options)
        except Exception:
            return yf_symbol, (None, None, ())

    candidate_yf_symbols = list(set(list(active_tickers.values()) + [to_yf_symbol(s) for s in BROAD_TICKERS]))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_single_ticker, sym): sym for sym in candidate_yf_symbols}
        for future in as_completed(futures):
            sym, res_tuple = future.result()
            if res_tuple[0] is not None and res_tuple[1] is not None:
                ticker_history_cache[sym] = res_tuple

    def get_history_and_obj(yf_sym: str):
        if yf_sym not in ticker_history_cache:
            ticker_history_cache[yf_sym] = fetch_single_ticker(yf_sym)[1]
        return ticker_history_cache[yf_sym]

    ticker_prices: Dict[str, float] = {}
    for display_name, yf_symbol in list(active_tickers.items()):
        try:
            _, hist, _ = get_history_and_obj(yf_symbol)
            if hist is not None and not hist.empty:
                ticker_prices[display_name] = float(hist['Close'].iloc[-1])
        except Exception:
            pass

    for symbol in BROAD_TICKERS:
        display_name = to_display_symbol(symbol)
        if display_name in active_tickers:
            continue
        try:
            yf_symbol = to_yf_symbol(symbol)
            _, hist, _ = get_history_and_obj(yf_symbol)
            if hist is None or hist.empty:
                continue
            curr_p = float(hist['Close'].iloc[-1])
            # Filter out stocks with share price > max_stock_price ($1000)
            if curr_p > max_stock_price and display_name not in held_symbols:
                continue
            fund_info = fund_cache.get(display_name, {}).get("info")
            if check_is_low_position(display_name, hist, fund_info=fund_info):
                active_tickers[display_name] = yf_symbol
                ticker_prices[display_name] = curr_p
        except Exception:
            pass

    eligible_cc_tickers: Dict[str, str] = {}
    for symbol, info in equity_info_map.items():
        if info["quantity"] >= 100.0:
            eligible_cc_tickers[symbol] = to_yf_symbol(symbol)

    targets: Dict[str, Any] = {"sell_put": {}, "covered_call": {}}

    for display_name, yf_symbol in active_tickers.items():
        try:
            p = ticker_prices.get(display_name, 0.0)
            # Filter out single share price > max_stock_price ($1000) unless actively held
            if p > max_stock_price and display_name not in held_symbols:
                continue
            _, hist, expirations = get_history_and_obj(yf_symbol)
            valid_exps = []
            for exp in expirations:
                try:
                    exp_date = datetime.datetime.strptime(exp, "%Y-%m-%d").date()
                    dte = (exp_date - today).days
                    if dte_min <= dte <= dte_max:
                        valid_exps.append(exp)
                except Exception:
                    continue

            if valid_exps:
                fund_info = fund_cache.get(display_name, {}).get("info")
                is_low = check_is_low_position(display_name, hist, fund_info=fund_info) if hist is not None else False
                targets["sell_put"][display_name] = {
                    "current_price": p,
                    "is_low_position": is_low,
                    "expirations": valid_exps,
                }
        except Exception as e:
            logger.warning(f"Error getting expirations for {display_name}: {e}")

    for display_name, yf_symbol in eligible_cc_tickers.items():
        try:
            _, hist, expirations = get_history_and_obj(yf_symbol)
            valid_exps = []
            for exp in expirations:
                try:
                    exp_date = datetime.datetime.strptime(exp, "%Y-%m-%d").date()
                    dte = (exp_date - today).days
                    if dte_min <= dte <= cc_dte_max:
                        valid_exps.append(exp)
                except Exception:
                    continue

            if valid_exps:
                targets["covered_call"][display_name] = {
                    "current_price": ticker_prices.get(display_name, 0.0),
                    "average_buy_price": equity_info_map[display_name]["average_buy_price"],
                    "quantity": equity_info_map[display_name]["quantity"],
                    "expirations": valid_exps,
                }
        except Exception as e:
            logger.warning(f"Error getting CC expirations for {display_name}: {e}")

    targets_file = os.path.join(DATA_DIR, "scan_targets.json")
    atomic_write_json(targets_file, targets)
    logger.info(f"Wrote {len(targets['sell_put'])} Sell Put and {len(targets['covered_call'])} CC targets to {targets_file}")
    return targets


# ==================== STEP 3: FILTER INSTRUMENTS ====================

def filter_instruments() -> List[Dict[str, Any]]:
    """
    Filter raw option instruments by dynamic strike price bounds.
    Writes: data/filtered_instruments.json
    """
    targets_file = os.path.join(DATA_DIR, "scan_targets.json")
    raw_inst_file = os.path.join(DATA_DIR, "raw_instruments.json")
    filtered_inst_file = os.path.join(DATA_DIR, "filtered_instruments.json")

    if not os.path.exists(targets_file) or not os.path.exists(raw_inst_file):
        logger.error("Missing targets or raw instruments file.")
        return []

    targets = load_json_config(targets_file)
    raw_instruments = load_json_config(raw_inst_file)
    if not isinstance(raw_instruments, list):
        raw_instruments = []

    params = get_scan_parameters()
    low_put_bounds = params["low_position_put_bounds"]
    norm_put_bounds = params["normal_position_put_bounds"]
    high_vol_put_bounds = params["high_vol_put_bounds"]
    cc_lb_mult = params["cc_lower_bound_multiplier"]
    cc_ub_mult = params["cc_upper_bound_multiplier"]

    sell_put_targets = targets.get("sell_put", {})
    covered_call_targets = targets.get("covered_call", {})

    filtered: List[Dict[str, Any]] = []

    for inst in raw_instruments:
        ticker = normalize_symbol(inst.get("chain_symbol"))
        inst_type = inst.get("type")
        strike = float(inst.get("strike_price", 0.0))
        exp_date = inst.get("expiration_date")

        if inst_type == "put" and ticker in sell_put_targets:
            t_info = sell_put_targets[ticker]
            curr_p = float(t_info.get("current_price", 0.0))
            is_low = t_info.get("is_low_position", False)
            expirations = t_info.get("expirations", [])

            if exp_date in expirations and curr_p > 0:
                bounds = high_vol_put_bounds if is_high_vol_growth(ticker) else (low_put_bounds if is_low else norm_put_bounds)
                if bounds[0] * curr_p <= strike <= bounds[1] * curr_p:
                    filtered.append(inst)

        elif inst_type == "call" and ticker in covered_call_targets:
            t_info = covered_call_targets[ticker]
            curr_p = float(t_info.get("current_price", 0.0))
            avg_buy = float(t_info.get("average_buy_price", 0.0))
            expirations = t_info.get("expirations", [])

            if exp_date in expirations and curr_p > 0:
                lb = max(avg_buy, cc_lb_mult * curr_p)
                ub = cc_ub_mult * curr_p
                if lb <= strike <= ub:
                    filtered.append(inst)

    atomic_write_json(filtered_inst_file, filtered)
    logger.info(f"Filtered down to {len(filtered)} instruments.")
    return filtered


# ==================== STEP 4: PREPARE QUOTE BATCHES ====================

def prepare_quote_batches(batch_size: int = 40) -> List[List[str]]:
    """
    Split filtered instrument IDs into batches of maximum size (default 40).
    Writes: data/quote_batches.json
    """
    filtered_file = os.path.join(DATA_DIR, "filtered_instruments.json")
    batches_file = os.path.join(DATA_DIR, "quote_batches.json")

    instruments = load_json_config(filtered_file)
    if not isinstance(instruments, list):
        instruments = []

    unique_ids = sorted(list(set(inst["id"] for inst in instruments if "id" in inst)))
    batches = [unique_ids[i:i + batch_size] for i in range(0, len(unique_ids), batch_size)]

    atomic_write_json(batches_file, batches)
    logger.info(f"Generated {len(batches)} quote batches ({len(unique_ids)} IDs) to {batches_file}")
    return batches


# ==================== STEP 5: BUILD OPTIONS CACHE ====================

def build_options_cache() -> Dict[str, Any]:
    """
    Compile filtered instruments and raw quotes into local option database.
    Writes: data/robinhood_options_cache.json
    """
    filtered_inst_file = os.path.join(DATA_DIR, "filtered_instruments.json")
    raw_quotes_file = os.path.join(DATA_DIR, "raw_quotes.json")
    cache_file = os.path.join(DATA_DIR, "robinhood_options_cache.json")

    instruments = load_json_config(filtered_inst_file)
    quotes_data = load_json_config(raw_quotes_file)
    if not isinstance(instruments, list):
        instruments = []
    if not isinstance(quotes_data, list):
        quotes_data = []

    quote_map: Dict[str, Dict[str, Any]] = {}
    for item in quotes_data:
        if isinstance(item, dict):
            if "quote" in item:
                q = item["quote"]
                if q.get("instrument_id"):
                    quote_map[q["instrument_id"]] = q
            elif "instrument_id" in item:
                quote_map[item["instrument_id"]] = item
            else:
                for res in item.get("data", {}).get("results", []):
                    q = res.get("quote", {})
                    if q.get("instrument_id"):
                        quote_map[q["instrument_id"]] = q

    cache: Dict[str, Dict[str, Dict[str, List[Dict[str, Any]]]]] = {}

    for inst in instruments:
        ticker = normalize_symbol(inst.get("chain_symbol"))
        exp_date = inst.get("expiration_date")
        inst_id = inst.get("id")
        inst_type = inst.get("type")
        strike = float(inst.get("strike_price", 0.0))

        if not ticker or not exp_date or not inst_id:
            continue

        if ticker not in cache:
            cache[ticker] = {}
        if exp_date not in cache[ticker]:
            cache[ticker][exp_date] = {"puts": [], "calls": []}

        q = quote_map.get(inst_id, {})
        bid = float(q.get("bid_price", 0.0) or 0.0)
        ask = float(q.get("ask_price", 0.0) or 0.0)
        oi = int(q.get("open_interest", 0) or 0)
        iv = float(q.get("implied_volatility", 0.0) or 0.0)
        delta = float(q.get("delta", 0.0) or 0.0)

        entry = {
            "strike": strike,
            "bid": bid,
            "ask": ask,
            "openInterest": oi,
            "impliedVolatility": iv,
            "delta": delta,
            "instrument_id": inst_id,
        }

        if inst_type == "put":
            cache[ticker][exp_date]["puts"].append(entry)
        elif inst_type == "call":
            cache[ticker][exp_date]["calls"].append(entry)

    for ticker in cache:
        for exp_date in cache[ticker]:
            cache[ticker][exp_date]["puts"].sort(key=lambda x: x["strike"])
            cache[ticker][exp_date]["calls"].sort(key=lambda x: x["strike"])

    atomic_write_json(cache_file, cache)
    logger.info(f"Built options cache for {len(cache)} tickers to {cache_file}")
    return cache


# ==================== STEP 6: GENERATE REPORT ====================

def generate_report() -> None:
    """
    Run multi-factor scoring engine, InvestSkill integration, and HTML dashboard rendering.
    Writes: report.html and data/watchlist_tickers.json
    """
    # Simply invoke scripts/generate_report.py to preserve identical visual formatting and data integrity
    gen_script = os.path.join(BASE_DIR, "scripts", "generate_report.py")
    res = subprocess.run(["python3", gen_script], capture_output=True, text=True)
    print(res.stdout)
    if res.stderr:
        print(res.stderr, file=sys.stderr)
    if res.returncode != 0:
        raise RuntimeError(f"generate_report.py failed with code {res.returncode}")


# ==================== STEP 7: SYNC WATCHLIST ====================

def sync_watchlist(client: Optional[RobinhoodMCPClient] = None) -> bool:
    """
    Sync recommended Sell Put candidates to Robinhood 'Sell Put Candidate' Watchlist.
    """
    watchlist_file = os.path.join(DATA_DIR, "watchlist_tickers.json")
    if not os.path.exists(watchlist_file):
        logger.error("watchlist_tickers.json not found.")
        return False

    with open(watchlist_file, "r", encoding="utf-8") as f:
        tickers = json.load(f).get("tickers", [])

    if not tickers:
        logger.warning("No tickers in watchlist_tickers.json.")
        return False

    def _sync(c: RobinhoodMCPClient) -> bool:
        watchlists = c.get_watchlists()
        target_name = "Sell Put Candidate"
        target_wl = None
        for w in watchlists:
            if isinstance(w, dict) and (w.get("name") == target_name or w.get("display_name") == target_name):
                target_wl = w
                break

        list_id = target_wl.get("id") if target_wl else c.create_watchlist(target_name)
        if not list_id:
            logger.error(f"Failed to get or create watchlist '{target_name}'.")
            return False

        existing = c.get_watchlist_items(list_id)
        if existing:
            c.remove_from_watchlist(list_id, existing)
            time.sleep(0.5)

        # Reverse order for LIFO insertion
        reversed_tickers = [to_rh_symbol(t) for t in tickers[::-1]]
        for sym in reversed_tickers:
            c.add_to_watchlist(list_id, [sym])
            time.sleep(0.2)

        logger.info(f"Successfully synced {len(tickers)} tickers to Robinhood '{target_name}'.")
        return True

    if client:
        return _sync(client)
    else:
        with RobinhoodMCPClient() as c:
            return _sync(c)


# ==================== MASTER ORCHESTRATOR ====================

def run_pipeline(skip_mcp: bool = False, skip_sync: bool = False) -> None:
    """
    Execute the complete end-to-end quant options research and synchronization workflow.
    Ensures 100% fresh live market data, option chains, account balances, and scores.
    """
    print("\n============================================================")
    print(" 🚀 OPTION QUANT STRATEGY RESEARCH & AUTOMATION PIPELINE")
    print("============================================================\n")
    start_time = time.time()

    # Step 1: Live Robinhood Account & Position Synchronization
    if not skip_mcp:
        print("📥 [1/6] Syncing live Robinhood account, cash, and option positions...")
        try:
            sync_account_data()
            # Sync 30-day PnL history for wash sale detection
            pnl_history_file = os.path.join(DATA_DIR, "trade_pnl_history.json")
            with RobinhoodMCPClient() as c:
                trades = c.get_pnl_trade_history(span="month")
                atomic_write_json(pnl_history_file, {"trades": trades})
        except Exception as e:
            logger.warning(f"Account sync encountered non-fatal error: {e}")

    # Step 2: Live Market Target Scanning
    print("🎯 [2/6] Scanning active market targets and valid expiration horizons...")
    get_scan_targets()

    # Step 3: High-Speed Live Option Chains Scanner
    print("⚡ [3/6] Fetching live option chains and quotes for all scan targets...")
    try:
        fast_scan_script = os.path.join(BASE_DIR, "scripts", "fast_option_scan.py")
        if os.path.exists(fast_scan_script):
            subprocess.run(["python3", "-u", fast_scan_script], check=False)
    except Exception as e:
        logger.warning(f"Fast option scan encountered non-fatal error: {e}")

    # Step 4: Sync InvestSkill reports
    investskill_script = os.path.join(INVESTSKILL_DIR, "scripts", "generate-output-index.js")
    if os.path.exists(investskill_script):
        print("📑 [4/6] Syncing InvestSkill institutional reports index...")
        subprocess.run(["node", investskill_script], check=False)

    # Step 5: Multi-Factor Scoring & Report Generation
    print("📈 [5/6] Executing multi-factor scoring engine and generating report.html...")
    generate_report()

    # Step 6: Watchlist Sync
    if not skip_sync and not skip_mcp:
        print("🔄 [6/6] Syncing Sell Put Candidate watchlist to Robinhood...")
        try:
            sync_watchlist()
        except Exception as e:
            logger.warning(f"Watchlist sync encountered non-fatal error: {e}")

    # Summary
    elapsed = time.time() - start_time
    print(f"\n🎉 Complete research pipeline finished in {elapsed:.2f}s!")
    print(f"👉 View interactive dashboard: file://{os.path.join(BASE_DIR, 'report.html')}\n")
