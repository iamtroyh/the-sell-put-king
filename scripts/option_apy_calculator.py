#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Option APY / Annualized Yield Calculator CLI
============================================
Usage:
    python3 scripts/option_apy_calculator.py <DTE> <Strike> <Premium>
    python3 scripts/option_apy_calculator.py  # Interactive mode
"""

import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from option_quant.cli import cmd_apy
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("params", nargs="*")
    args = parser.parse_args()
    sys.exit(cmd_apy(args))
