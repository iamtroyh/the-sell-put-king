#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Market Data True Options IV / IVP / IVR CLI Tool
================================================
Fetches 30-day ATM implied volatility, calculates 252-day True IV Percentile
and True IV Rank via Market Data API, and inspects local volatility cache.
"""

import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from option_quant.marketdata_client import get_true_ivp_and_ivr, MarketDataClient, _load_iv_cache
from option_quant.config import DATA_DIR, load_json_config, normalize_symbol
from concurrent.futures import ThreadPoolExecutor, as_completed

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 scripts/fetch_true_iv.py <TICKER> [--refresh]")
        print("  python3 scripts/fetch_true_iv.py --all [--workers 16]")
        return

    if "--all" in sys.argv:
        targets_file = os.path.join(DATA_DIR, "scan_targets.json")
        targets_data = load_json_config(targets_file) if os.path.exists(targets_file) else {}
        symbols = list(targets_data.get("sell_put", {}).keys())
        if not symbols:
            symbols = ["IBIT", "BRK.B", "SPYM", "ASHR", "QQQM", "IWM", "VTV", "TLT", "XLV", "XLP", "XLE"]

        print(f"\n⚡ Starting Parallel True IV 252d Backfill for {len(symbols)} symbols...")
        client = MarketDataClient()
        completed = 0
        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = {pool.submit(get_true_ivp_and_ivr, s, client, True, 10, True): s for s in symbols}
            for fut in as_completed(futures):
                s = futures[fut]
                try:
                    res = fut.result()
                    completed += 1
                    print(f"[{completed:2d}/{len(symbols)}] {s:6s} -> 30D IV: {res['current_iv']*100:.1f}%, IVP: {res['ivp']:.1f}%, IVR: {res['ivr']:.1f}% ({res['sample_count']} samples)")
                except Exception as e:
                    print(f"Error on {s}: {e}")
        print("\n✅ All symbols backfilled successfully!")
        return

    sym = normalize_symbol(sys.argv[1])
    force_refresh = "--refresh" in sys.argv

    print(f"\n============================================================")
    print(f" 📊 MARKET DATA TRUE IV & VOLATILITY RANKING: {sym}")
    print(f"============================================================\n")

    res = get_true_ivp_and_ivr(sym, force_refresh=force_refresh, auto_backfill=True)

    if res.get("has_true_iv"):
        print(f"✅ Symbol:               {res['symbol']}")
        print(f"⚡ Current 30D ATM IV:   {res['current_iv'] * 100:.2f}%")
        print(f"📈 True 252d IVP:        {res['ivp']:.1f}%")
        print(f"🎯 True 252d IVR:        {res['ivr']:.1f}%")
        print(f"⭐ Composite S_IV:       {res['composite_s_iv']:.1f} / 100")
        print(f"📉 52w IV Min:           {res['min_iv'] * 100:.2f}%")
        print(f"📈 52w IV Max:           {res['max_iv'] * 100:.2f}%")
        print(f"📦 Samples in Dist:      {res['sample_count']} historical points")
        print(f"\n💡 Summary: {res['summary_text']}")
        print(f"🏷️  Badge:   {res['badge_html']}\n")
    else:
        print(f"⚠️ Could not retrieve live option chain IV for {sym}.")
        print(f"Reason: {res.get('summary_text')}")
        print("Note: Ensure Market Data token is configured in config/credentials.json or MARKETDATA_TOKEN env variable.\n")

if __name__ == "__main__":
    main()
