#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch Live Option Quotes from Robinhood MCP
===========================================
"""

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from option_quant.config import atomic_write_json
from option_quant.mcp_client import RobinhoodMCPClient

def main():
    batches_file = os.path.join(BASE_DIR, "data", "quote_batches.json")
    raw_quotes_file = os.path.join(BASE_DIR, "data", "raw_quotes.json")

    if not os.path.exists(batches_file):
        print(f"Error: {batches_file} not found.")
        return

    with open(batches_file, 'r', encoding='utf-8') as f:
        batches = json.load(f)

    existing_quote_map = {}
    if os.path.exists(raw_quotes_file):
        try:
            with open(raw_quotes_file, 'r', encoding='utf-8') as f:
                existing = json.load(f)
            for q in existing:
                inst_id = q.get("instrument_id")
                if inst_id:
                    existing_quote_map[inst_id] = q
        except Exception:
            pass

    with RobinhoodMCPClient() as client:
        for i, batch in enumerate(batches):
            quotes = client.get_option_quotes(batch)
            for q in quotes:
                inst_id = q.get("instrument_id")
                if inst_id:
                    existing_quote_map[inst_id] = q
            print(f"Batch {i+1}/{len(batches)} fetched successfully. Total accumulated: {len(existing_quote_map)}")

    merged = list(existing_quote_map.values())
    atomic_write_json(raw_quotes_file, merged)
    print(f"Successfully saved {len(merged)} total quotes to {raw_quotes_file}")

if __name__ == "__main__":
    main()
