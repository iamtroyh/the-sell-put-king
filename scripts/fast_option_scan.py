#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
High-Speed Market Data Option Scanner & Cache Builder
=====================================================
Fetches pre-filtered option chains for all scan targets concurrently in < 3 seconds
and updates data/robinhood_options_cache.json directly.
"""

import os
import sys
import json
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from option_quant.config import (
    DATA_DIR,
    atomic_write_json,
    normalize_symbol,
    load_json_config,
    get_marketdata_token,
)
from option_quant.marketdata_client import (
    MarketDataClient,
    get_filtered_csp_candidates,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fast_scan")


def run_fast_scan(symbols: List[str] = None) -> Dict[str, Any]:
    token = get_marketdata_token()
    if not token:
        logger.warning("No Market Data token configured. Skipping fast scan.")
        return {}

    client = MarketDataClient(token=token)

    if not symbols:
        targets_file = os.path.join(DATA_DIR, "scan_targets.json")
        if os.path.exists(targets_file):
            t_data = load_json_config(targets_file)
            symbols = list(t_data.get("sell_put", {}).keys())
        else:
            symbols = ["IBIT", "BRK.B", "SPYM", "ASHR", "QQQM", "IWM", "VTV", "TLT", "XLV", "XLP", "XLE", "AAPL", "NVDA", "MSFT", "GOOGL", "AMZN", "META", "TSLA"]

    symbols = list(set([normalize_symbol(s) for s in symbols if s]))
    logger.info(f"⚡ Starting Fast Parallel Option Scan for {len(symbols)} symbols...")
    start_t = time.time()

    cache_file = os.path.join(DATA_DIR, "robinhood_options_cache.json")
    existing_cache = load_json_config(cache_file) if os.path.exists(cache_file) else {}
    if not isinstance(existing_cache, dict):
        existing_cache = {}

    total_contracts_found = 0

    def fetch_symbol_options(sym: str):
        cands = get_filtered_csp_candidates(
            symbol=sym,
            min_dte=15,
            max_dte=100,
            delta_min=-0.40,
            delta_max=-0.08,
            min_oi=5,
            client=client,
        )
        return sym, cands

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(fetch_symbol_options, s) for s in symbols]
        for fut in as_completed(futures):
            try:
                sym, cands = fut.result()
                if not cands:
                    continue

                if sym not in existing_cache:
                    existing_cache[sym] = {}

                for c in cands:
                    exp = c["expiration"]
                    if exp not in existing_cache[sym]:
                        existing_cache[sym][exp] = {"puts": [], "calls": []}

                    # Upsert strike into puts (always overwrite with fresh live market data)
                    updated_puts = [p for p in existing_cache[sym][exp].get("puts", []) if p["strike"] != c["strike"]]
                    updated_puts.append({
                        "strike": c["strike"],
                        "bid": c["bid"],
                        "ask": c["ask"],
                        "openInterest": c["open_interest"],
                        "impliedVolatility": c["iv"] / 100.0,
                        "delta": c["delta"],
                        "gamma": c.get("gamma", 0.0),
                        "theta": c.get("theta", 0.0),
                        "vega": c.get("vega", 0.0),
                        "instrument_id": f"md_{sym}_{exp}_{c['strike']}_p",
                    })
                    existing_cache[sym][exp]["puts"] = updated_puts
                    total_contracts_found += 1

                for exp in existing_cache[sym]:
                    existing_cache[sym][exp]["puts"].sort(key=lambda x: x["strike"])

            except Exception as e:
                logger.error(f"Error processing options for {sym}: {e}")

    atomic_write_json(cache_file, existing_cache)
    elapsed = time.time() - start_t
    logger.info(f"✅ Fast scan finished in {elapsed:.2f}s! Added/Verified {total_contracts_found} contracts across {len(symbols)} symbols.")
    return existing_cache


if __name__ == "__main__":
    run_fast_scan()
