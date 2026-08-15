#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Portfolio Delta Notional Exposure Calculator
============================================
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from option_quant.portfolio import calculate_portfolio_delta_exposure

def main():
    res = calculate_portfolio_delta_exposure()
    print(f"Total Delta Notional: ${res['total_delta_notional']:,.2f}")
    print(f"Leverage Ratio: {res['leverage_ratio']:.2f}x ({res['status_label']})")
    print(f"Positions Count: {len(res['positions'])}")

if __name__ == "__main__":
    main()
