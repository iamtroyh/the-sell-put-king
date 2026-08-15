#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch Live Account Data from Robinhood MCP
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
    with RobinhoodMCPClient() as client:
        # 1. Portfolio
        portfolio_res = client.get_portfolio()
        if portfolio_res:
            atomic_write_json(os.path.join(BASE_DIR, "data", "mcp_portfolio.json"), portfolio_res)
            print("Saved mcp_portfolio.json")

        # 2. Equity Positions
        equity_res = client.get_equity_positions()
        if equity_res:
            atomic_write_json(os.path.join(BASE_DIR, "data", "mcp_equity_positions.json"), equity_res)
            print("Saved mcp_equity_positions.json")

        # 3. Option Positions
        options_res = client.get_option_positions(nonzero=True)
        if options_res:
            atomic_write_json(os.path.join(BASE_DIR, "data", "mcp_option_positions.json"), options_res)
            print("Saved mcp_option_positions.json")

        # 4. Active Option Instruments & Quotes
        option_ids = []
        positions = options_res.get("data", {}).get("positions", []) if options_res else []
        for pos in positions:
            opt_id = pos.get("option_id")
            if opt_id and float(pos.get("quantity", 0)) > 0:
                option_ids.append(opt_id)

        if option_ids:
            inst_res = client.get_option_instruments(ids=option_ids)
            if inst_res:
                atomic_write_json(os.path.join(BASE_DIR, "data", "mcp_active_instruments.json"), {"data": {"instruments": inst_res}})
                print(f"Saved mcp_active_instruments.json ({len(option_ids)} instruments)")

            quotes_res = client.get_option_quotes(option_ids)
            if quotes_res:
                atomic_write_json(os.path.join(BASE_DIR, "data", "mcp_active_quotes.json"), {"data": {"results": [{"quote": q} for q in quotes_res]}})
                print(f"Saved mcp_active_quotes.json ({len(option_ids)} quotes)")

    print("Live account data sync completed successfully.")

if __name__ == "__main__":
    main()
