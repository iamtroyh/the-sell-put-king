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

from option_quant.marketdata_client import get_true_ivp_and_ivr, MarketDataClient
from option_quant.config import normalize_symbol

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/fetch_true_iv.py <TICKER> [--refresh]")
        print("Example: python3 scripts/fetch_true_iv.py AAPL")
        return

    sym = normalize_symbol(sys.argv[1])
    force_refresh = "--refresh" in sys.argv

    print(f"\n============================================================")
    print(f" 📊 MARKET DATA TRUE IV & VOLATILITY RANKING: {sym}")
    print(f"============================================================\n")

    res = get_true_ivp_and_ivr(sym, force_refresh=force_refresh)

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
