#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The Sell Put King Master Pipeline Runner
========================================
Executes InvestSkill index synchronization, multi-factor option scoring,
HTML report rendering, and optional Robinhood watchlist updates.
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from option_quant.pipeline import run_pipeline

if __name__ == "__main__":
    run_pipeline()
