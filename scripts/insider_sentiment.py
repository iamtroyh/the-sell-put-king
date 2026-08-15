#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEC Form 4 Insider Sentiment Analysis CLI
=========================================
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from option_quant.market_data import (
    get_insider_sentiment,
    batch_get_insider_sentiment,
)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        sym = sys.argv[1].upper()
        res = get_insider_sentiment(sym)
        print(f"[{sym}] Sentiment: {res.get('sentiment')}")
        print(f"Net Value: ${res.get('net_value', 0.0):,.2f}")
        print(f"Summary: {res.get('summary_text')}")
    else:
        print("Usage: python3 scripts/insider_sentiment.py <TICKER>")
