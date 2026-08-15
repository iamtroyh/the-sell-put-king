#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch Target Option Instruments from Robinhood MCP
==================================================
"""

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from option_quant.config import atomic_write_json, normalize_symbol
from option_quant.mcp_client import RobinhoodMCPClient

def prune_instrument(inst: dict) -> dict:
    return {
        "id": inst.get("id"),
        "chain_symbol": normalize_symbol(inst.get("chain_symbol")),
        "expiration_date": inst.get("expiration_date"),
        "strike_price": str(inst.get("strike_price")),
        "type": inst.get("type")
    }

def main():
    targets_file = os.path.join(BASE_DIR, "data", "scan_targets.json")
    raw_inst_file = os.path.join(BASE_DIR, "data", "raw_instruments.json")

    if not os.path.exists(targets_file):
        print(f"Error: {targets_file} not found.")
        return

    with open(targets_file, 'r', encoding='utf-8') as f:
        targets = json.load(f)

    sell_put_targets = targets.get("sell_put", {})
    covered_call_targets = targets.get("covered_call", {})

    instruments_map = {}
    with RobinhoodMCPClient() as client:
        # Sell Put
        for sym, t_info in sell_put_targets.items():
            exps = t_info.get("expirations", [])
            if exps:
                insts = client.get_option_instruments(chain_symbol=sym, expiration_dates=exps, opt_type="put")
                for it in insts:
                    p_it = prune_instrument(it)
                    if p_it["id"]:
                        instruments_map[p_it["id"]] = p_it

        # Covered Call
        for sym, t_info in covered_call_targets.items():
            exps = t_info.get("expirations", [])
            if exps:
                insts = client.get_option_instruments(chain_symbol=sym, expiration_dates=exps, opt_type="call")
                for it in insts:
                    p_it = prune_instrument(it)
                    if p_it["id"]:
                        instruments_map[p_it["id"]] = p_it

    all_insts = list(instruments_map.values())
    atomic_write_json(raw_inst_file, all_insts)
    print(f"Successfully saved {len(all_insts)} instruments to {raw_inst_file}")

if __name__ == "__main__":
    main()
