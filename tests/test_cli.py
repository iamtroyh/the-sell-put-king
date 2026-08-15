# -*- coding: utf-8 -*-
"""Unit tests for option_quant.cli module."""

from option_quant.cli import build_parser, main


def test_cli_parser():
    parser = build_parser()
    args = parser.parse_args(["apy", "15", "100", "2.5"])
    assert args.command == "apy"
    assert args.params == ["15", "100", "2.5"]

    args_delta = parser.parse_args(["delta"])
    assert args_delta.command == "delta"

    args_insider = parser.parse_args(["insider", "AAPL"])
    assert args_insider.command == "insider"
    assert args_insider.ticker == "AAPL"


def test_cli_apy_execution():
    exit_code = main(["apy", "30", "100", "2.0"])
    assert exit_code == 0
