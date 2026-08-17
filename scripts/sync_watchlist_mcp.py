#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sync Recommended Candidates to Robinhood Watchlist
==================================================
"""

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from option_quant.config import (
    TICKER_EXCHANGE_MAP,
    TICKER_METADATA_PATH,
    format_tradingview_ticker,
    load_json_config,
    to_rh_symbol,
)
from option_quant.mcp_client import RobinhoodMCPClient

def main():
    watchlist_file = os.path.join(BASE_DIR, "data", "watchlist_tickers.json")
    if not os.path.exists(watchlist_file):
        print(f"Error: {watchlist_file} not found.")
        return

    with open(watchlist_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    tickers = data.get("tickers", [])
    if not tickers:
        print("No tickers found in watchlist_tickers.json.")
        return

    print(f"Loaded {len(tickers)} tickers for Robinhood Watchlist sync: {tickers}")

    # Export TradingView watchlists
    tv_file = os.path.join(BASE_DIR, "data", "tradingview_watchlist.txt")
    tv_plain_file = os.path.join(BASE_DIR, "data", "tradingview_watchlist_plain.txt")

    tv_lines = [format_tradingview_ticker(t) for t in tickers]
    plain_lines = [to_rh_symbol(t) for t in tickers]

    with open(tv_file, "w", encoding="utf-8") as f:
        f.write("\n".join(tv_lines) + "\n")
    with open(tv_plain_file, "w", encoding="utf-8") as f:
        f.write("\n".join(plain_lines) + "\n")
    print(f"Exported TradingView watchlists to {tv_file} and {tv_plain_file}")

    target_name = "Sell Put Candidate"
    with RobinhoodMCPClient() as client:
        watchlists = client.get_watchlists()
        target_wl = None
        for w in watchlists:
            if isinstance(w, dict) and (w.get("name") == target_name or w.get("display_name") == target_name):
                target_wl = w
                break

        list_id = target_wl.get("id") if target_wl else client.create_watchlist(target_name)
        if not list_id:
            print(f"Error: Could not get or create Watchlist '{target_name}'.")
            return

        print(f"Target Watchlist '{target_name}' ID: {list_id}")

        existing = client.get_watchlist_items(list_id)
        if existing:
            print(f"Clearing {len(existing)} existing items...")
            client.remove_from_watchlist(list_id, existing)

        reversed_tickers = [to_rh_symbol(t) for t in tickers[::-1]]
        print(f"Adding {len(reversed_tickers)} symbols in reverse order (LIFO)...")
        for sym in reversed_tickers:
            client.add_to_watchlist(list_id, [sym])

    print(f"Successfully completed Watchlist '{target_name}' synchronization!")

if __name__ == "__main__":
    main()
