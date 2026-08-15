import json
import os
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
meta_path = os.path.join(BASE_DIR, "config", "ticker_metadata.json")
scan_cfg_path = os.path.join(BASE_DIR, "config", "scan_config.json")

with open(meta_path, "r", encoding="utf-8") as f:
    meta = json.load(f)

exchange_map = meta.get("ticker_exchange_map", {})

with open(scan_cfg_path, "r", encoding="utf-8") as f:
    scan_cfg = json.load(f)

all_tickers = sorted(list(set(scan_cfg.get("preselected_tickers", []) + scan_cfg.get("broad_tickers", []))))

def normalize_ticker(t):
    if t in ["BRK.B", "BRKB", "BRK-B"]:
        return "BRK.B", "BRK-B"
    return t, t

def check_ticker_exchange(t):
    disp_sym, yf_sym = normalize_ticker(t)
    try:
        ticker_obj = yf.Ticker(yf_sym)
        info = ticker_obj.info
        exch_raw = info.get("exchange", "")
        if exch_raw in ['NMS', 'NGM', 'NCM', 'NAS', 'NASDAQ']:
            exch = 'NASDAQ'
        elif exch_raw in ['NYQ', 'NYSE', 'NYE']:
            exch = 'NYSE'
        elif exch_raw in ['PCX', 'ASE', 'AMEX', 'ARCA', 'NYSEARCA']:
            exch = 'AMEX'
        else:
            exch = exch_raw
            
        if not exch:
            # Fallback based on known characteristics
            if disp_sym in ['SPY', 'IWM', 'DIA', 'GLD', 'SLV', 'USO', 'GDX', 'ASHR', 'SPYM', 'VTV', 'XLK', 'XLF', 'XLV', 'XLE', 'XLI', 'XLY', 'XLP', 'XLRE', 'XLU', 'XLB', 'XBI', 'KWEB', 'URA']:
                exch = 'AMEX'
            elif disp_sym in ['CMCSA', 'QQQ', 'QQQM', 'IBIT', 'TLT', 'SOXX', 'SMH', 'TSLA', 'HOOD', 'SOFI', 'NFLX', 'MSFT', 'META', 'AMZN', 'INTU', 'SNPS', 'ISRG', 'PDD', 'TCOM', 'UPST', 'VEEV', 'LULU', 'AAPL', 'NVDA', 'AVGO', 'AMD', 'QCOM', 'ASML', 'AMAT', 'LRCX', 'KLAC', 'MRVL', 'TXN', 'ADI', 'CDNS', 'COST', 'SBUX', 'PEP', 'ADBE', 'ABNB', 'CME', 'MU', 'ANET', 'CEG', 'PYPL', 'ULTA', 'SKHY', 'CRWD', 'PANW', 'FTNT', 'DDOG', 'ZS', 'COIN']:
                exch = 'NASDAQ'
            else:
                exch = 'NYSE'
        return disp_sym, exch, exch_raw
    except Exception as e:
        return disp_sym, None, str(e)

print(f"Checking {len(all_tickers)} tickers for exact exchange mappings...")
updated = 0

with ThreadPoolExecutor(max_workers=15) as executor:
    futures = {executor.submit(check_ticker_exchange, t): t for t in all_tickers}
    for future in as_completed(futures):
        disp_sym, exch, raw_or_err = future.result()
        if exch:
            old_exch = exchange_map.get(disp_sym)
            if old_exch != exch:
                print(f"Updating {disp_sym}: {old_exch} -> {exch} (raw: {raw_or_err})")
                exchange_map[disp_sym] = exch
                updated += 1
            else:
                pass
        else:
            print(f"Warning: Could not determine exchange for {disp_sym}: {raw_or_err}")

# Hardcode CMCSA and key fixes explicitly to prevent any regression
exchange_map["CMCSA"] = "NASDAQ"
exchange_map["BRK.B"] = "NYSE"
exchange_map["BRK-B"] = "NYSE"

meta["ticker_exchange_map"] = exchange_map
with open(meta_path, "w", encoding="utf-8") as f:
    json.dump(meta, f, indent=2, ensure_ascii=False)

print(f"\nCompleted! Updated {updated} ticker exchange mappings in {meta_path}.")
