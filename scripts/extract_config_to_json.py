import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, 'config')
os.makedirs(CONFIG_DIR, exist_ok=True)

sys.path.insert(0, os.path.join(BASE_DIR, 'scripts'))
import ticker_config
import generate_report

scan_config_data = {
    "preselected_tickers": ticker_config.PRESELECTED_TICKERS,
    "broad_tickers": ticker_config.BROAD_TICKERS,
    "long_bull_tickers": sorted(list(ticker_config.LONG_BULL_TICKERS)),
    "etf_tickers": sorted(list(ticker_config.ETF_TICKERS))
}

scan_config_file = os.path.join(CONFIG_DIR, 'scan_config.json')
with open(scan_config_file, 'w', encoding='utf-8') as f:
    json.dump(scan_config_data, f, indent=2, ensure_ascii=False)
print(f"Successfully wrote {scan_config_file}")

ticker_metadata_data = {
    "ticker_intros": generate_report.TICKER_INTROS,
    "ticker_risks": generate_report.TICKER_RISKS,
    "sector_map": generate_report.SECTOR_MAP,
    "ticker_fundamentals": generate_report.TICKER_FUNDAMENTALS,
    "ticker_exchange_map": ticker_config.TICKER_EXCHANGE_MAP
}

ticker_metadata_file = os.path.join(CONFIG_DIR, 'ticker_metadata.json')
with open(ticker_metadata_file, 'w', encoding='utf-8') as f:
    json.dump(ticker_metadata_data, f, indent=2, ensure_ascii=False)
print(f"Successfully wrote {ticker_metadata_file}")
