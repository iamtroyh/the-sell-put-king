#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch Trade PnL History from Robinhood MCP
==========================================
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from option_quant.config import atomic_write_json
from option_quant.mcp_client import RobinhoodMCPClient

def main():
    pnl_history_file = os.path.join(BASE_DIR, "data", "trade_pnl_history.json")
    with RobinhoodMCPClient() as client:
        trades = client.get_pnl_trade_history(span="month")
        atomic_write_json(pnl_history_file, {"trades": trades})
        print(f"Successfully fetched and saved {len(trades)} PnL trades to {pnl_history_file}")

if __name__ == "__main__":
    main()
