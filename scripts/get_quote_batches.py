#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prepare 40-ID Quote Batches for API Slicing
===========================================
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from option_quant.pipeline import prepare_quote_batches

if __name__ == "__main__":
    prepare_quote_batches()
