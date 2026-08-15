# -*- coding: utf-8 -*-
"""
Option Quant Command Line Interface (CLI)
=========================================
Unified CLI entry point for quantitative options analysis, strategy research,
portfolio management, and Robinhood synchronization.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import List, Optional

from option_quant.config import mask_account_id
from option_quant.market_data import get_insider_sentiment
from option_quant.pipeline import (
    build_options_cache,
    filter_instruments,
    generate_report,
    get_scan_targets,
    prepare_quote_batches,
    run_pipeline,
    sync_account_data,
    sync_watchlist,
)
from option_quant.portfolio import calculate_portfolio_delta_exposure
from option_quant.scoring import calculate_apy


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_run(args: argparse.Namespace) -> int:
    run_pipeline(skip_mcp=args.skip_mcp, skip_sync=args.skip_sync)
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    print("🔄 Syncing Robinhood account, equity, and options positions...")
    res = sync_account_data()
    acc = res.get("account_info", {})
    cash = acc.get("cash_available", 0.0)
    collat = acc.get("total_collateral", 0.0)
    print(f"✅ Sync complete: Cash Available: ${cash:,.2f} | Collateral: ${collat:,.2f}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    print("🔍 Scanning targets across broad market and current positions...")
    targets = get_scan_targets()
    print(f"✅ Found {len(targets.get('sell_put', {}))} Sell Put and {len(targets.get('covered_call', {}))} CC targets.")
    return 0


def cmd_filter(args: argparse.Namespace) -> int:
    print("✂️ Filtering raw option instruments...")
    filtered = filter_instruments()
    prepare_quote_batches()
    print(f"✅ Filtered {len(filtered)} valid instruments.")
    return 0


def cmd_cache(args: argparse.Namespace) -> int:
    print("📦 Compiling local options cache database...")
    cache = build_options_cache()
    print(f"✅ Built options cache with {len(cache)} tickers.")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    print("📊 Executing scoring models and generating report.html...")
    generate_report()
    return 0


def cmd_watchlist(args: argparse.Namespace) -> int:
    print("📋 Syncing Robinhood 'Sell Put Candidate' Watchlist...")
    ok = sync_watchlist()
    if ok:
        print("✅ Watchlist synced successfully.")
        return 0
    print("❌ Watchlist sync failed.")
    return 1


def cmd_apy(args: argparse.Namespace) -> int:
    if args.params and len(args.params) == 3:
        try:
            dte = float(args.params[0])
            strike = float(args.params[1])
            premium = float(args.params[2])
            res = calculate_apy(dte, strike, premium)
            print("\n----------------------------------------")
            print("📊 期权 APY 计算结果：")
            print(f"  • 合约参数: {int(dte) if dte.is_integer() else dte}天到期 | 行权价 ${strike:.2f} | 权利金 ${premium:.2f}")
            print(f"  • 单期收益率:   {res['period_return']:.2f}%")
            print(f"  • 年化收益率:   \033[1;32m{res['simple_apy']:.2f}%\033[0m  (全额保证金标准)")
            print(f"  • 复利年化:     {res['compound_apy']:.2f}%")
            print(f"  • 净资金占用:   {res['net_simple_apy']:.2f}%")
            print("----------------------------------------\n")
            return 0
        except ValueError as e:
            print(f"❌ 参数错误: {e}")
            return 1
    else:
        # Interactive loop
        print("==============================================")
        print("       📈 期权 APY / 年化收益率计算器         ")
        print("==============================================")
        print("请输入：<到期天数 DTE> <行权价 Strike> <期权价格 Premium>")
        print("参数用空格隔开，例如: 15 100 2.5")
        print("输入 'q' 或 'exit' 退出程序。\n")
        while True:
            try:
                user_input = input("👉 请输入 (DTE 行权价 期权价): ").strip()
                if not user_input or user_input.lower() in ['q', 'quit', 'exit', '退出']:
                    break
                normalized = user_input.replace('。', '.').replace('，', ' ')
                parts = normalized.split()
                if len(parts) != 3:
                    print("⚠️ 输入格式错误！请输入 3 个数值并用空格分隔（如: 35 40 1.15）\n")
                    continue
                dte, strike, premium = float(parts[0]), float(parts[1]), float(parts[2])
                res = calculate_apy(dte, strike, premium)
                print(f"  ➔ 单期: {res['period_return']:.2f}% | 年化 APY: \033[1;32m{res['simple_apy']:.2f}%\033[0m\n")
            except Exception as e:
                print(f"❌ 错误: {e}\n")
        return 0


def cmd_delta(args: argparse.Namespace) -> int:
    print("📈 Calculating Portfolio Delta Notional Exposure...")
    res = calculate_portfolio_delta_exposure()
    notional = res.get("total_delta_notional", 0.0)
    lev = res.get("leverage_ratio", 0.0)
    status = res.get("status_label", "")
    print(f"✅ Total Delta Notional: ${notional:,.2f} | Leverage: {lev:.2f}x ({status})")
    return 0


def cmd_insider(args: argparse.Namespace) -> int:
    ticker = args.ticker.upper()
    print(f"👔 Fetching SEC Form 4 insider sentiment for {ticker}...")
    res = get_insider_sentiment(ticker)
    print(f"Sentiment: {res.get('sentiment')} | Net: ${res.get('net_value', 0.0):,.2f}")
    print(f"Summary: {res.get('summary_text')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="the-sell-put-king",
        description="The Sell Put King Strategy & Portfolio Management Engine",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")

    subparsers = parser.add_subparsers(dest="command", help="Subcommands")

    # run
    p_run = subparsers.add_parser("run", help="Run full quantitative research and report pipeline (default)")
    p_run.add_argument("--skip-mcp", action="store_true", help="Skip Robinhood MCP synchronization")
    p_run.add_argument("--skip-sync", action="store_true", help="Skip Watchlist sync")
    p_run.set_defaults(func=cmd_run)

    # sync
    p_sync = subparsers.add_parser("sync", help="Synchronize Robinhood balances and positions")
    p_sync.set_defaults(func=cmd_sync)

    # scan
    p_scan = subparsers.add_parser("scan", help="Scan candidate tickers for Sell Put and Covered Call")
    p_scan.set_defaults(func=cmd_scan)

    # filter
    p_filter = subparsers.add_parser("filter", help="Filter raw instruments by strike & Delta")
    p_filter.set_defaults(func=cmd_filter)

    # cache
    p_cache = subparsers.add_parser("cache", help="Compile local options database cache")
    p_cache.set_defaults(func=cmd_cache)

    # report
    p_report = subparsers.add_parser("report", help="Score candidates and render report.html")
    p_report.set_defaults(func=cmd_report)

    # watchlist
    p_wl = subparsers.add_parser("watchlist", help="Sync candidates to Robinhood Watchlist")
    p_wl.set_defaults(func=cmd_watchlist)

    # apy
    p_apy = subparsers.add_parser("apy", help="Option APY / Annualized yield calculator")
    p_apy.add_argument("params", nargs="*", help="Optional: <DTE> <Strike> <Premium>")
    p_apy.set_defaults(func=cmd_apy)

    # delta
    p_delta = subparsers.add_parser("delta", help="Calculate portfolio delta exposure and leverage")
    p_delta.set_defaults(func=cmd_delta)

    # insider
    p_insider = subparsers.add_parser("insider", help="Check SEC Form 4 insider sentiment for a ticker")
    p_insider.add_argument("ticker", help="Stock ticker symbol (e.g. AAPL, NVDA)")
    p_insider.set_defaults(func=cmd_insider)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]

    # Default to 'run' command if no subcommand provided
    if not argv or (len(argv) == 1 and argv[0] in ["-v", "--verbose"]):
        argv = ["run"] + argv

    args = parser.parse_args(argv)
    setup_logging(verbose=getattr(args, "verbose", False))

    if hasattr(args, "func"):
        return args.func(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
