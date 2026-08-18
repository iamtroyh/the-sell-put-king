import datetime
import html
import math
import os
import sys
import json
import re
import time
import numpy as np
import pandas as pd
import requests
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from option_quant.config import (
    BASE_DIR,
    INVESTSKILL_DIR,
    INVESTSKILL_OUTPUT_DIR,
    PRESELECTED_TICKERS,
    RISK_FREE_RATE,
    get_dynamic_risk_free_rate,
    SECTOR_MAP,
    TICKER_EXCHANGE_MAP,
    TICKER_FUNDAMENTALS,
    TICKER_INTROS,
    TICKER_RISKS,
    atomic_write_json,
    format_tradingview_ticker,
    get_tradingview_url,
    is_etf_symbol,
    is_high_vol_growth,
    is_long_bull,
    normalize_symbol,
    to_display_symbol,
    to_rh_symbol,
    to_yf_symbol,
)
from option_quant.investskill import scan_investskill_reports
from option_quant.market_data import (
    calculate_piotroski_f_score,
    check_eva_and_moat,
    get_insider_sentiment,
    batch_get_insider_sentiment,
)
from option_quant.marketdata_client import (
    batch_get_derivative_metrics,
    calculate_roll_candidate,
    get_derivative_metrics,
    get_filtered_csp_candidates,
    get_true_ivp_and_ivr,
    MarketDataClient,
)
from option_quant.portfolio import calculate_portfolio_delta_exposure
from option_quant.scoring import (
    calculate_call_delta,
    calculate_covered_call_score,
    calculate_multi_horizon_hv,
    calculate_option_ev_and_pop,
    calculate_put_delta,
    calculate_sell_put_score,
    get_recommendation_reason,
    norm_cdf,
)

INVESTSKILL_DIR = os.environ.get("INVESTSKILL_DIR", os.path.expanduser("~/InvestSkill"))
INVESTSKILL_OUTPUT_DIR = os.environ.get("INVESTSKILL_OUTPUT_DIR", os.path.join(INVESTSKILL_DIR, "output"))

def fetch_chart_df(symbol, range_str='1y'):
    try:
        url = f'https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={range_str}'
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return pd.DataFrame()
        data = r.json()
        res = data['chart']['result'][0]
        timestamps = res['timestamp']
        quote = res['indicators']['quote'][0]
        dates = [datetime.datetime.fromtimestamp(ts) for ts in timestamps]
        df = pd.DataFrame({
            'Open': quote.get('open', []),
            'High': quote.get('high', []),
            'Low': quote.get('low', []),
            'Close': quote.get('close', []),
            'Volume': quote.get('volume', [])
        }, index=pd.DatetimeIndex(dates))
        df = df.dropna(subset=['Close'])
        return df
    except Exception:
        return pd.DataFrame()


DTE_MIN = 15
DTE_MAX = 60

GLOBAL_FUNDAMENTAL_CACHE = {}

def get_fundamental_info(ticker_symbol):
    cache_entry = GLOBAL_FUNDAMENTAL_CACHE.get(ticker_symbol)
    if cache_entry:
        return cache_entry.get("info", {})
    return {}




def main():
    today = datetime.date.today()
    print(f"Starting research process. Today's date: {today}")
    
    # Load Robinhood options cache from data/ directory per clean architecture rules
    options_cache = {}
    cache_file = os.path.join(BASE_DIR, "data", "robinhood_options_cache.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as f:
                options_cache = json.load(f)
            print(f"Loaded Robinhood options cache for {len(options_cache)} tickers.")
        except Exception as e:
            print(f"Warning: Failed to load options cache: {e}")
            
    # Fetch BTC-USD price
    btc_price = None
    try:
        btc_ticker = yf.Ticker("BTC-USD")
        btc_hist = btc_ticker.history(period="1d")
        if not btc_hist.empty:
            btc_price = btc_hist['Close'].iloc[-1]
            print(f"Fetched BTC-USD price: {btc_price}")
    except Exception as e:
        print(f"Warning: Failed to fetch BTC-USD price: {e}")
        
    # 1. Load current positions from JSON
    current_positions = []
    positions_file = os.path.join(BASE_DIR, "data", "current_positions.json")
    if os.path.exists(positions_file):
        try:
            with open(positions_file, 'r') as f:
                data = json.load(f)
                current_positions = data.get("positions", [])
            print(f"Loaded current positions: {current_positions}")
        except Exception as e:
            print(f"Warning: Failed to load current positions: {e}")
            
    # Map to ticker symbols for simple checks
    current_position_tickers = []
    if isinstance(current_positions, list) and len(current_positions) > 0 and isinstance(current_positions[0], dict):
        current_position_tickers = [pos['symbol'] for pos in current_positions]
    else:
        current_position_tickers = current_positions

    # Load current equity positions from JSON
    current_equity_positions = []
    equity_positions_file = os.path.join(BASE_DIR, "data", "current_equity_positions.json")
    equity_info_map = {}
    if os.path.exists(equity_positions_file):
        try:
            with open(equity_positions_file, 'r') as f:
                eq_data = json.load(f)
                current_equity_positions = [to_display_symbol(pos['symbol']) for pos in eq_data.get("equity_positions", [])]
                for pos in eq_data.get("equity_positions", []):
                    equity_info_map[to_display_symbol(pos['symbol'])] = {
                        "average_buy_price": float(pos['average_buy_price']),
                        "quantity": float(pos['quantity'])
                    }
            print(f"Loaded current equity positions: {current_equity_positions}")
        except Exception as e:
            print(f"Warning: Failed to load current equity positions: {e}")
            
    # Load trade PnL history to detect 30-day Wash Sale risks
    wash_sale_history_map = {}
    trade_pnl_file = os.path.join(BASE_DIR, "data", "trade_pnl_history.json")
    if os.path.exists(trade_pnl_file):
        try:
            with open(trade_pnl_file, 'r', encoding='utf-8') as f:
                pnl_history_data = json.load(f)
                for tr in pnl_history_data.get("trades", []):
                    sym = to_display_symbol(tr.get("symbol", ""))
                    rg = float(tr.get("realized_gain", 0.0))
                    ts_str = tr.get("timestamp", "")
                    if rg < 0 and ts_str:
                        tr_dt = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00")).date()
                        days_diff = (today - tr_dt).days
                        if 0 <= days_diff <= 30:
                            unlock_dt = tr_dt + datetime.timedelta(days=31)
                            if sym not in wash_sale_history_map:
                                wash_sale_history_map[sym] = []
                            wash_sale_history_map[sym].append({
                                "loss": rg,
                                "trade_date": tr_dt.strftime("%Y-%m-%d"),
                                "unlock_date": unlock_dt.strftime("%Y-%m-%d"),
                                "days_ago": days_diff
                            })
            print(f"Loaded Wash Sale risk history for tickers: {list(wash_sale_history_map.keys())}")
        except Exception as e:
            print(f"Warning: Failed to parse trade_pnl_history.json: {e}")
            
    # ==================== SHORT PUT SCAN & SCORING ====================
    # Read scan_targets.json directly to keep active_tickers 100% synchronized with get_scan_targets.py
    active_tickers = {} # display_name -> yf_symbol
    scan_targets_file = os.path.join(BASE_DIR, "data", "scan_targets.json")
    scan_targets_data = {}
    if os.path.exists(scan_targets_file):
        try:
            with open(scan_targets_file, 'r', encoding='utf-8') as f:
                scan_targets_data = json.load(f)
            st_dict = scan_targets_data.get("sell_put", {})
            for t_sym in st_dict:
                active_tickers[to_display_symbol(t_sym)] = to_yf_symbol(t_sym)
            print(f"Loaded {len(active_tickers)} target tickers from scan_targets.json: {list(active_tickers.keys())}")
        except Exception as e:
            print(f"Error loading scan_targets.json: {e}")

    if not active_tickers:
        for pos in current_position_tickers:
            active_tickers[to_display_symbol(pos)] = to_yf_symbol(pos)
        for pre in PRESELECTED_TICKERS:
            active_tickers[to_display_symbol(pre)] = to_yf_symbol(pre)
            
    global GLOBAL_FUNDAMENTAL_CACHE
    fundamental_cache_path = os.path.join(BASE_DIR, 'data', 'fundamental_cache.json')
    if os.path.exists(fundamental_cache_path):
        try:
            with open(fundamental_cache_path, 'r') as f:
                GLOBAL_FUNDAMENTAL_CACHE = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load fundamental_cache.json: {e}")
            
    now_ts = time.time()
    start_time = time.time()
    tickers_to_fetch = list(active_tickers.keys())
    
    # ==================== Parallel Market Data & Fundamentals Fetching ====================
    ticker_history_map = {}
    market_history_cache_path = os.path.join(BASE_DIR, 'data', 'market_history_cache.json')
    market_history_cache = {}
    if os.path.exists(market_history_cache_path):
        try:
            with open(market_history_cache_path, 'r', encoding='utf-8') as f:
                market_history_cache = json.load(f)
        except Exception:
            pass

    print(f"Pre-fetching live market history and fundamental data concurrently for {len(tickers_to_fetch)} tickers...")
    def fetch_ticker_all(symbol):
        yf_sym = to_yf_symbol(symbol)
        hist = None
        info = {}
        try:
            t_obj = yf.Ticker(yf_sym)
            hist = t_obj.history(period="1y").dropna(subset=['Close'])
            info = t_obj.info or {}
        except Exception:
            hist = None
            info = {}
            
        if hist is None or hist.empty:
            hist = fetch_chart_df(yf_sym, "1y")
            
        if not info:
            info = GLOBAL_FUNDAMENTAL_CACHE.get(symbol, {}).get("info", {})
            
        return symbol, hist, info

    cache_updated = False
    m_cache_updated = False
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(fetch_ticker_all, t): t for t in tickers_to_fetch}
        for future in as_completed(futures):
            sym, hist, info = future.result()
            if hist is not None and not hist.empty:
                ticker_history_map[sym] = hist
                try:
                    c_price = float(hist['Close'].iloc[-1])
                    h_52 = float(hist['Close'].max())
                    l_52 = float(hist['Close'].min())
                    s_200 = float(hist['Close'].rolling(200).mean().iloc[-1]) if len(hist) >= 200 else c_price
                    rets = np.log(hist['Close'] / hist['Close'].shift(1))
                    hv30_val = float(rets.rolling(30).std().iloc[-1] * np.sqrt(252) * 100) if len(rets) >= 30 else 30.0
                    r30_val = float((c_price - hist['Close'].iloc[-22]) / hist['Close'].iloc[-22]) if len(hist) >= 22 else 0.0
                    market_history_cache[sym] = {
                        "current_price": c_price,
                        "high_52w": h_52,
                        "low_52w": l_52,
                        "sma_200": s_200,
                        "hv_30": hv30_val if not np.isnan(hv30_val) else 30.0,
                        "return_30d": r30_val if not np.isnan(r30_val) else 0.0,
                        "timestamp": now_ts
                    }
                    m_cache_updated = True
                except Exception:
                    pass
            if info:
                GLOBAL_FUNDAMENTAL_CACHE[sym] = {
                    "timestamp": now_ts,
                    "info": info
                }
                cache_updated = True

    if cache_updated:
        atomic_write_json(fundamental_cache_path, GLOBAL_FUNDAMENTAL_CACHE)
    if m_cache_updated:
        atomic_write_json(market_history_cache_path, market_history_cache)
        
    print(f"✅ Pre-fetched data for {len(ticker_history_map)} tickers in {time.time() - start_time:.2f}s.")

    # ==================== Parallel SEC Form 4 Insider Sentiment Pre-fetching ====================
    insider_start_t = time.time()
    print(f"Pre-fetching SEC Form 4 insider sentiment data for {len(tickers_to_fetch)} tickers...")
    insider_sentiment_map = batch_get_insider_sentiment(tickers_to_fetch)
    print(f"✅ Pre-fetched insider sentiment for {len(insider_sentiment_map)} tickers in {time.time() - insider_start_t:.2f}s.")

    all_options = []
    ticker_market_data = {}
    low_position_tickers = set(current_position_tickers)
    
    # ==================== MACRO CIRCUIT BREAKER & VIX CHECK ====================
    vix_extreme_crisis = False  # VIX >= 40.0: extreme black swan, halt new CSP openings
    deep_defense_mode = False   # VIX >= 30.0 or 30d broad market drop <= -12%: deep OTM mode (Delta 0.08~0.15, Cushion >= 12%)
    macro_circuit_breaker = False # VIX >= 25.0 or 30d broad market drop <= -8%: yellow alert defense mode (Delta tightened to 0.10~0.25)
    cb_reasons = []
    
    for m_sym, m_name in [('SPY', '标普500'), ('QQQ', '纳斯达克100'), ('SPYM', '标普500 ETF'), ('QQQM', '纳斯达克100 ETF')]:
        try:
            m_hist = fetch_chart_df(m_sym, "3mo")
            if m_hist.empty:
                m_t = yf.Ticker(m_sym)
                m_hist = m_t.history(period="3mo").dropna(subset=['Close'])
            if len(m_hist) >= 21:
                m_curr = float(m_hist['Close'].iloc[-1])
                m_prev = float(m_hist['Close'].iloc[-21])
                m_ret = (m_curr - m_prev) / m_prev
                if m_ret <= -0.12:
                    deep_defense_mode = True
                    macro_circuit_breaker = True
                    cb_reasons.append(f"{m_name}({m_sym}) 近30天重度大跌 {abs(m_ret)*100:.1f}% (开启红灯深虚值防守)")
                elif m_ret <= -0.08:
                    macro_circuit_breaker = True
                    cb_reasons.append(f"{m_name}({m_sym}) 近30天回撤达 {abs(m_ret)*100:.1f}% (开启黄灯防守)")
        except Exception:
            pass
            
    try:
        vix_hist = fetch_chart_df('^VIX', "5d")
        if vix_hist.empty:
            vix_t = yf.Ticker('^VIX')
            vix_hist = vix_t.history(period="5d").dropna(subset=['Close'])
        if not vix_hist.empty:
            vix_val = float(vix_hist['Close'].iloc[-1])
            if vix_val >= 40.0:
                vix_extreme_crisis = True
                deep_defense_mode = True
                macro_circuit_breaker = True
                cb_reasons.append(f"VIX恐慌指数高达 {vix_val:.2f} (触发极端黑天鹅熔断，暂停新建单)")
            elif vix_val >= 30.0:
                deep_defense_mode = True
                macro_circuit_breaker = True
                cb_reasons.append(f"VIX恐慌指数高达 {vix_val:.2f} (触发红灯极高IV深虚值防守模式)")
            elif vix_val >= 25.0:
                macro_circuit_breaker = True
                cb_reasons.append(f"VIX恐慌指数升至 {vix_val:.2f} (触发黄灯防守模式)")
    except Exception:
        pass
            
    if vix_extreme_crisis:
        print(f"🚨🚨 VIX EXTREME CRISIS (>=40)! Reasons: {', '.join(cb_reasons)}")
    elif deep_defense_mode:
        print(f"🔴 RED LIGHT DEEP DEFENSE MODE (VIX>=30/Drop>=12%)! Reasons: {', '.join(cb_reasons)}")
    elif macro_circuit_breaker:
        print(f"🟡 YELLOW ALERT MODE (VIX>=25/Drop>=8%)! Reasons: {', '.join(cb_reasons)}")
    else:
        print("✅ Macro Circuit Breaker & VIX check passed (normal market sentiment).")

    print(f"Pre-fetching derivative metrics (Max Pain, Skew, PCR) concurrently for {len(active_tickers)} tickers...")
    t0_dm = time.time()
    derivative_map = batch_get_derivative_metrics(list(active_tickers.keys()), max_workers=20)
    print(f"✅ Pre-fetched derivative metrics for {len(derivative_map)} tickers in {time.time()-t0_dm:.2f}s.")
    
    for display_ticker, yf_ticker in active_tickers.items():
        hist = ticker_history_map.get(display_ticker)
        if hist is None or hist.empty:
            hist = fetch_chart_df(yf_ticker, "1y")
                
        cached_m = market_history_cache.get(display_ticker, {})
        st_info = scan_targets_data.get("sell_put", {}).get(display_ticker, {})
        
        if hist is not None and not hist.empty:
            current_price = float(hist['Close'].iloc[-1])
            high_52w = float(hist['Close'].max())
            low_52w = float(hist['Close'].min())
            sma_200 = float(hist['Close'].rolling(200).mean().iloc[-1]) if len(hist) >= 200 else current_price
            
            returns = np.log(hist['Close'] / hist['Close'].shift(1))
            hv_30 = returns.rolling(30).std() * np.sqrt(252) * 100
            hv_30_clean = hv_30.dropna()
            
            # Multi-Horizon Weighted Realized Volatility Blend (30D 50% + 60D 30% + 90D 20% anchored by 252D ceiling)
            hv_metrics = calculate_multi_horizon_hv(returns)
            curr_hv_30_val = hv_metrics["hv_30"]
            curr_hv_60_val = hv_metrics["hv_60"]
            curr_hv_90_val = hv_metrics["hv_90"]
            hv_252_val = hv_metrics["hv_252"]
            hv_blend_val = hv_metrics["hv_blend"]
            effective_hv_val = hv_metrics["effective_hv"]
            
            price_22d_ago = hist['Close'].iloc[-22] if len(hist) >= 22 else hist['Close'].iloc[0]
            return_30d = float((current_price - price_22d_ago) / price_22d_ago) if price_22d_ago > 0 else 0.0

            # Williams VixFix Synthetic Implied Volatility calculation
            highest_close_22 = hist['Close'].rolling(22).max()
            low_series = hist['Low'] if 'Low' in hist.columns else hist['Close']
            vixfix_series = ((highest_close_22 - low_series) / highest_close_22) * 100.0
            vixfix_clean = vixfix_series.dropna()
            current_vixfix = vixfix_clean.iloc[-1] if not vixfix_clean.empty else 0.0
            vixfix_252d_ivp = (vixfix_clean.values < current_vixfix).mean() * 100.0 if len(vixfix_clean) > 0 else 0.0
            vixfix_30d_clean = vixfix_clean.iloc[-30:] if len(vixfix_clean) >= 30 else vixfix_clean
            vixfix_30d_ivp = (vixfix_30d_clean.values < current_vixfix).mean() * 100.0 if len(vixfix_clean) > 0 else 0.0
        elif cached_m:
            current_price = cached_m.get("current_price", st_info.get("current_price", 100.0))
            high_52w = cached_m.get("high_52w", current_price * 1.25)
            low_52w = cached_m.get("low_52w", current_price * 0.80)
            sma_200 = cached_m.get("sma_200", current_price)
            curr_hv_30_val = cached_m.get("hv_30", 30.0)
            curr_hv_60_val = cached_m.get("hv_60", curr_hv_30_val)
            curr_hv_90_val = cached_m.get("hv_90", curr_hv_60_val)
            hv_252_val = cached_m.get("hv_252", curr_hv_30_val)
            hv_blend_val = cached_m.get("hv_blend", 0.50 * curr_hv_30_val + 0.30 * curr_hv_60_val + 0.20 * curr_hv_90_val)
            effective_hv_val = cached_m.get("effective_hv", min(hv_blend_val, hv_252_val))
            hv_30_clean = pd.Series([curr_hv_30_val])
            return_30d = cached_m.get("return_30d", 0.0)
            current_vixfix = cached_m.get("current_vixfix", 20.0)
            vixfix_252d_ivp = cached_m.get("vixfix_252d_ivp", 50.0)
            vixfix_30d_ivp = cached_m.get("vixfix_30d_ivp", 50.0)
        elif st_info:
            current_price = float(st_info.get("current_price", 100.0))
            high_52w = current_price * 1.25
            low_52w = current_price * 0.80
            sma_200 = current_price
            curr_hv_30_val = 30.0
            curr_hv_60_val = 30.0
            curr_hv_90_val = 30.0
            hv_252_val = 30.0
            hv_blend_val = 30.0
            effective_hv_val = 30.0
            hv_30_clean = pd.Series([30.0])
            return_30d = 0.0
            current_vixfix = 20.0
            vixfix_252d_ivp = 50.0
            vixfix_30d_ivp = 50.0
        else:
            continue
            
        if "is_low_position" in st_info:
            is_low_position = st_info["is_low_position"]
        elif hist is not None and not hist.empty:
            if is_long_bull(display_ticker):
                dev = (current_price - sma_200) / sma_200 if sma_200 > 0 else 0.0
                is_low_position = (dev <= 0.00) or (return_30d <= -0.15 and dev <= 0.03)
            else:
                rp = (current_price - low_52w) / (high_52w - low_52w) if (high_52w - low_52w) > 0 else 0.5
                is_low_position = (rp <= 0.20) or (return_30d <= -0.15 and rp <= 0.40)
        else:
            is_low_position = cached_m.get("is_low_position", False)
            
        if is_low_position:
            low_position_tickers.add(display_ticker)
        is_etf = is_etf_symbol(display_ticker)
        
        # Stepped drop and black swan evaluation
        is_black_swan = False
        knife_level = 0
        if is_etf:
            if return_30d <= -0.25:
                is_black_swan = True
                knife_level = 3
            elif return_30d <= -0.15:
                knife_level = 2
            elif return_30d <= -0.08:
                knife_level = 1
        else:
            if return_30d <= -0.35:
                is_black_swan = True
                knife_level = 3
            elif return_30d <= -0.25:
                knife_level = 2
            elif return_30d <= -0.15:
                knife_level = 1
                
        is_falling_knife = knife_level > 0
        
        is_fcf_negative = False
        fcf_margin = None
        if not is_etf:
            f_info = GLOBAL_FUNDAMENTAL_CACHE.get(display_ticker, {}).get("info", {})
            sec_name = SECTOR_MAP.get(display_ticker) or f_info.get('sector', "")
            is_fin_or_reit = sec_name in ['Financial Services', 'Financials', 'Real Estate', 'Utilities']
            fcf = f_info.get('freeCashflow')
            rev = f_info.get('totalRevenue')
            ocf = f_info.get('operatingCashflow')
            ebitda_margin = f_info.get('ebitdaMargins')
            
            if fcf is not None and rev is not None and rev > 0:
                fcf_margin = (fcf / rev) * 100.0

            if is_fin_or_reit:
                is_fcf_negative = False
                fcf_margin = None
            elif fcf is not None and fcf < 0:
                # If operating cashflow is positive and EBITDA margin is healthy, it is M&A amortization/Capex, not operational burn
                if ocf is not None and ocf > 0 and ebitda_margin is not None and ebitda_margin > 0.08:
                    is_fcf_negative = False
                    fcf_margin = None
                else:
                    is_fcf_negative = True

        # True IVP & IVR via Market Data API
        true_iv_info = get_true_ivp_and_ivr(display_ticker)
        derivative_metrics = derivative_map.get(display_ticker) or get_derivative_metrics(display_ticker)

        ticker_market_data[display_ticker] = {
            'current_price': current_price,
            'high_52w': high_52w,
            'low_52w': low_52w,
            'sma_200': sma_200,
            'hv_distribution': hv_30_clean.values,
            'current_hv_30': curr_hv_30_val,
            'current_hv_60': curr_hv_60_val,
            'current_hv_90': curr_hv_90_val,
            'current_hv_252': hv_252_val,
            'current_hv_blend': hv_blend_val,
            'effective_hv': effective_hv_val,
            'current_vixfix': current_vixfix,
            'vixfix_252d_ivp': vixfix_252d_ivp,
            'vixfix_30d_ivp': vixfix_30d_ivp,
            'true_iv_info': true_iv_info,
            'derivative_metrics': derivative_metrics,
            'return_30d': return_30d,
            'knife_level': knife_level,
            'is_falling_knife': is_falling_knife,
            'is_black_swan': is_black_swan,
            'is_fcf_negative': is_fcf_negative,
            'fcf_margin': fcf_margin
        }
        
        # Black swan veto: skip new CSP openings for unheld crashing tickers
        if is_black_swan and display_ticker not in current_position_tickers:
            print(f"  [⛔ Black Swan Drop Circuit Breaker] {display_ticker} dropped {abs(return_30d)*100:.1f}% in 30d, vetoing new CSP openings.")
            continue
            
        use_cache = display_ticker in options_cache
        if use_cache:
            exp_dates = list(options_cache[display_ticker].keys())
        elif scan_targets_data and display_ticker in scan_targets_data.get("sell_put", {}):
            exp_dates = scan_targets_data["sell_put"][display_ticker].get("expirations", [])
        else:
            exp_dates = []
            try:
                t_obj = yf.Ticker(yf_ticker)
                exp_dates = list(t_obj.options)
            except Exception:
                exp_dates = []
            
        if not exp_dates:
            continue
            
        # Check upcoming earnings release timestamp
        earnings_ts = None
        dte_earnings = None
        if not is_etf:
            fund_data = GLOBAL_FUNDAMENTAL_CACHE.get(display_ticker, {}).get("info", {})
            if not fund_data:
                try:
                    fund_data = ticker.info
                except Exception:
                    fund_data = {}
            earnings_ts = fund_data.get('earningsTimestampStart') or fund_data.get('earningsTimestamp')
            if earnings_ts:
                try:
                    earnings_date = datetime.datetime.fromtimestamp(earnings_ts, tz=datetime.timezone.utc).date()
                    dte_earnings = (earnings_date - today).days
                except Exception:
                    pass

        # Filter expirations: strictly prioritize Standard Monthly Expirations (3rd Friday of the month, day 15-21)
        valid_exp_dates = []
        for exp_str in exp_dates:
            try:
                exp_date = datetime.datetime.strptime(exp_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            dte = (exp_date - today).days
            if DTE_MIN <= dte <= DTE_MAX:
                valid_exp_dates.append((exp_str, exp_date, dte))

        # Filter for standard monthly expirations (3rd Friday, or 3rd Thursday if holiday early closure)
        def _is_monthly_exp(d: datetime.date) -> bool:
            return (d.weekday() == 4 and (15 <= d.day <= 21)) or (d.weekday() == 3 and (14 <= d.day <= 20))

        monthly_exp_dates = [
            (exp_str, exp_date, dte)
            for exp_str, exp_date, dte in valid_exp_dates
            if _is_monthly_exp(exp_date)
        ]

        # If earnings are scheduled within 30 days, smart buffer defense:
        # Prioritize expirations that have at least 14 days post-earnings buffer (DTE >= dte_earnings + 14)
        if dte_earnings is not None and 0 <= dte_earnings <= 30:
            min_buf_dte = max(DTE_MIN, dte_earnings + 14)
            buffered_exps = [x for x in valid_exp_dates if x[2] >= min_buf_dte]
            if buffered_exps:
                target_exp_dates = [x for x in buffered_exps if x in monthly_exp_dates] + [x for x in buffered_exps if x not in monthly_exp_dates]
            else:
                target_exp_dates = monthly_exp_dates if monthly_exp_dates else valid_exp_dates
        else:
            target_exp_dates = monthly_exp_dates if monthly_exp_dates else valid_exp_dates

        ticker_options = []
        for exp_str, exp_date, dte in target_exp_dates:
            # Earnings-DTE Smart Buffer defense rules
            is_earnings_crosser = False
            if dte_earnings is not None and 0 <= dte_earnings <= 30:
                if dte > dte_earnings:
                    is_earnings_crosser = True

            if use_cache:
                cache_puts = options_cache[display_ticker][exp_str].get("puts", [])
                if not cache_puts:
                    continue
                puts = pd.DataFrame(cache_puts)
            else:
                try:
                    opt_chain = ticker.option_chain(exp_str)
                    puts = opt_chain.puts
                except Exception:
                    continue
                    
            for _, put in puts.iterrows():
                strike = put['strike']
                bid = put['bid']
                ask = put['ask']
                oi = put['openInterest']
                iv = put['impliedVolatility']
                
                if pd.isna(bid) or pd.isna(ask) or bid < 0 or ask < 0:
                    continue
                mark = (bid + ask) / 2.0
                if mark <= 0.01:
                    continue
                    
                spread_ratio = (ask - bid) / mark if mark > 0 else 0.0
                abs_spread = ask - bid
                is_low_dollar_tight = (abs_spread <= 0.15 and mark <= 0.60)

                # Refined 4-Tier Smooth Liquidity Model (Conservative Pricing + Non-Punitive Spread Handling)
                # Tier 1 (🟢 极佳流动性): Spread <= 20% & OI >= 50 -> 100% Mark price, 0 penalty
                # Tier 2 (🟡 标准流动性): (Spread <= 35% or is_low_dollar_tight) & OI >= 20 -> Conservative min(Mark, Bid*1.15), 0 penalty
                # Tier 3 (🟠 中度点差): (Spread <= 50% or abs_spread <= 0.25) & OI >= 10 -> Conservative min(Mark, Bid*1.10), 0 penalty (price already discounted, limit order recommended)
                # Tier 4 (🔴 宽幅点差): Spread > 50% or OI < 10 (with Bid > 0) -> Conservative min(Mark, Bid*1.05), modest -4.0 pt penalty
                # Tier 5 (⛔ 零买盘): Bid <= 0 -> 0 price, -15.0 pt penalty
                if (spread_ratio <= 0.20 and oi >= 50) or (abs_spread <= 0.10 and mark <= 0.60):
                    liq_tier = 1
                    liq_penalty = 0.0
                    passed_gatekeeper = True
                    liq_warning = ""
                    exec_price = mark
                elif (spread_ratio <= 0.35 or is_low_dollar_tight) and (oi >= 20):
                    liq_tier = 2
                    liq_penalty = 0.0
                    passed_gatekeeper = True
                    liq_warning = ""
                    exec_price = min(mark, bid * 1.15) if spread_ratio > 0.15 and bid > 0 else mark
                elif (spread_ratio <= 0.50 or (abs_spread <= 0.25 and mark <= 0.80)) and (oi >= 10):
                    liq_tier = 3
                    liq_penalty = 0.0
                    passed_gatekeeper = True
                    liq_warning = "中度点差 (建议限价单)"
                    exec_price = min(mark, bid * 1.10) if bid > 0 else mark
                elif bid > 0:
                    liq_tier = 4
                    liq_penalty = 4.0
                    passed_gatekeeper = False
                    liq_warning = "宽点差 (建议限价单)"
                    exec_price = min(mark, bid * 1.05) if bid > 0 else mark
                else:
                    liq_tier = 5
                    liq_penalty = 15.0
                    passed_gatekeeper = False
                    liq_warning = "零买盘匮乏"
                    exec_price = 0.0
                
                t_years = dte / 365.0
                raw_delta = put.get('delta')
                if raw_delta is not None and not pd.isna(raw_delta) and float(raw_delta) != 0.0:
                    delta = float(raw_delta)
                else:
                    delta = calculate_put_delta(current_price, strike, t_years, RISK_FREE_RATE, iv)
                
                # Apply Delta and cushion filters based on VIX mode, earnings defense, and high-vol profiles
                cushion = (current_price - strike) / current_price * 100.0 if current_price > 0 else 0.0
                if vix_extreme_crisis:
                    continue
                elif deep_defense_mode:
                    if not (-0.15 <= delta <= -0.08) or cushion < 12.0:
                        continue
                elif macro_circuit_breaker:
                    if not (-0.25 <= delta <= -0.10):
                        continue
                elif is_earnings_crosser:
                    # Earnings-cross defense: tighten Delta upper bound to -0.20 and require safety cushion >= 10.0%
                    if not (-0.20 <= delta <= -0.10) or cushion < 10.0:
                        continue
                elif is_low_position:
                    # Valuation Trough (RP <= 0.20 or Dev <= 0.00): expand Delta allowance to [-0.40, -0.08] with cushion >= 3.0%
                    delta_lower_limit = -0.40 if not is_high_vol_growth(display_ticker) else -0.35
                    if not (delta_lower_limit <= delta <= -0.08) or cushion < 3.0:
                        continue
                elif is_high_vol_growth(display_ticker):
                    # High volatility growth stock defense (non-trough): Delta upper bound -0.25 and cushion >= 10.0%
                    if not (-0.25 <= delta <= -0.08) or cushion < 10.0:
                        continue
                else:
                    if not (-0.30 <= delta <= -0.08) or cushion < 3.0:
                        continue
                    
                abs_delta = abs(delta)
                risk_profile = None
                if deep_defense_mode:
                    if 0.08 <= abs_delta < 0.10:
                        risk_profile = "保守"
                    elif 0.10 <= abs_delta < 0.13:
                        risk_profile = "平衡"
                    elif 0.13 <= abs_delta <= 0.15:
                        risk_profile = "激进"
                elif macro_circuit_breaker or is_earnings_crosser:
                    if 0.10 <= abs_delta < 0.14:
                        risk_profile = "保守"
                    elif 0.14 <= abs_delta < 0.17:
                        risk_profile = "平衡"
                    elif 0.17 <= abs_delta <= 0.20:
                        risk_profile = "激进"
                elif is_low_position:
                    if 0.10 <= abs_delta < 0.20:
                        risk_profile = "保守"
                    elif 0.20 <= abs_delta < 0.30:
                        risk_profile = "平衡"
                    elif 0.30 <= abs_delta <= 0.40:
                        risk_profile = "激进"
                else:
                    if 0.10 <= abs_delta < 0.17:
                        risk_profile = "保守"
                    elif 0.17 <= abs_delta < 0.24:
                        risk_profile = "平衡"
                    elif 0.24 <= abs_delta <= 0.30:
                        risk_profile = "激进"
                        
                if not risk_profile:
                    continue

                if is_falling_knife:
                    if risk_profile == "保守":
                        risk_profile = "平衡"
                    elif risk_profile == "平衡":
                        risk_profile = "激进"
                
                annualized_yield = (exec_price / strike) * (365.0 / max(1, dte)) * 100.0
                curr_hv_30 = ticker_market_data[display_ticker].get('current_hv_30', 30.0)
                eff_hv = ticker_market_data[display_ticker].get('effective_hv', curr_hv_30)

                # Quantitative EV & POP Calculation under lognormal distribution (Dual-Damping Volatility Estimator)
                ev_res = calculate_option_ev_and_pop(
                    spot=current_price,
                    strike=strike,
                    dte=dte,
                    premium=exec_price,
                    iv=iv,
                    hv=(eff_hv / 100.0) if eff_hv > 0 else iv,
                )
                pop = ev_res["pop"]
                ev_dollar = ev_res["ev_dollar"]
                ev_apy = ev_res["ev_apy"]
                trade_sharpe = ev_res["trade_sharpe"]
                breakeven = ev_res["breakeven"]
                half_kelly_pct = ev_res["half_kelly_pct"]

                fund_info = get_fundamental_info(display_ticker)
                f_score, _ = calculate_piotroski_f_score(fund_info)
                insider_info = insider_sentiment_map.get(display_ticker, {})
                insider_sent = insider_info.get("sentiment", "neutral")

                sec = SECTOR_MAP.get(display_ticker) or (fund_info.get("sector") if fund_info else None) or ("ETF" if is_etf_symbol(display_ticker) else "Other")
                is_financial_or_utility = (sec in ["Financial Services", "Financials & Crypto", "ETF", "Financials", "Utilities", "Real Estate"]) or (display_ticker in ["XLU", "XLF", "VNQ", "XLRE"])
                de_ratio = fund_info.get("debtToEquity") if fund_info else None
                is_heavy_debt = (float(de_ratio) if (de_ratio is not None and not is_financial_or_utility and not is_etf_symbol(display_ticker)) else False)

                deriv = ticker_market_data[display_ticker].get('derivative_metrics', {})
                put_skew = deriv.get('put_skew')
                max_pain = deriv.get('max_pain')
                pcr_oi = deriv.get('pcr_oi')
                expected_move_pct = deriv.get('expected_move_pct')

                true_iv = ticker_market_data[display_ticker].get('true_iv_info', {})
                iv_percent = iv * 100.0
                if true_iv.get('has_true_iv'):
                    ivp = true_iv['ivp']
                    ivr = true_iv['ivr']
                    has_true_iv = True
                else:
                    ivp = (hv_30_clean.values < iv_percent).mean() * 100.0 if len(hv_30_clean) > 0 else 0.0
                    ivr = None
                    has_true_iv = False

                total_score, s_price, s_safety, s_option_alpha, s_yield, trend_penalty = calculate_sell_put_score(
                    ticker=display_ticker,
                    current_price=current_price,
                    strike=strike,
                    delta=delta,
                    mark=mark,
                    annualized_yield=annualized_yield,
                    ivp=ivp,
                    dte=dte,
                    sma_200=sma_200,
                    low_52w=low_52w,
                    high_52w=high_52w,
                    curr_hv=eff_hv,
                    knife_level=knife_level,
                    is_fcf_negative=is_fcf_negative,
                    f_score=f_score,
                    insider_sentiment=insider_sent,
                    is_heavy_debt=is_heavy_debt,
                    ivr=ivr,
                    put_skew=put_skew,
                    max_pain=max_pain,
                    pcr_oi=pcr_oi,
                    expected_move_pct=expected_move_pct,
                    is_earnings_crosser=is_earnings_crosser,
                    ev_apy=ev_apy,
                    ev_dollar=ev_dollar,
                    pop=pop,
                    fcf_margin=ticker_market_data[display_ticker].get('fcf_margin'),
                    return_30d=ticker_market_data[display_ticker].get('return_30d'),
                    is_wash_sale_risk=(display_ticker in wash_sale_history_map),
                )
                    
                opt_info = {
                    'ticker': display_ticker,
                    'current_price': current_price,
                    'expiration': exp_str,
                    'dte': dte,
                    'strike': strike,
                    'delta': delta,
                    'bid': bid,
                    'ask': ask,
                    'mark': mark,
                    'spread_ratio': spread_ratio,
                    'open_interest': int(oi) if not pd.isna(oi) else 0,
                    'iv': iv_percent,
                    'ivp': ivp,
                    'ivr': ivr,
                    'has_true_iv': has_true_iv,
                    'put_skew': put_skew,
                    'max_pain': max_pain,
                    'pcr_oi': pcr_oi,
                    'expected_move_pct': expected_move_pct,
                    'pop': pop,
                    'ev_dollar': ev_dollar,
                    'ev_apy': ev_apy,
                    'trade_sharpe': trade_sharpe,
                    'breakeven': breakeven,
                    'half_kelly_pct': half_kelly_pct,
                    's_yield': s_yield,
                    's_safety': s_safety,
                    's_option_alpha': s_option_alpha,
                    's_iv': s_option_alpha,
                    's_price': s_price,
                    'total_score': total_score,
                    'trend_penalty': trend_penalty,
                    'passed_gatekeeper': passed_gatekeeper,
                    'liq_tier': liq_tier,
                    'liq_penalty': liq_penalty,
                    'liq_warning': liq_warning,
                    'annualized_yield': annualized_yield,
                    'warning': False,
                    'risk_profile': risk_profile,
                    'is_earnings_crosser': is_earnings_crosser,
                    'is_heavy_debt': is_heavy_debt,
                    'f_score': f_score,
                    'is_high_qual': is_etf_symbol(display_ticker) or (f_score is not None and f_score >= 7) or (insider_sent == 'net_buying'),
                }
                ticker_options.append(opt_info)
                
        by_profile = {"保守": [], "平衡": [], "激进": []}
        for opt in ticker_options:
            prof = opt['risk_profile']
            if prof in by_profile:
                by_profile[prof].append(opt)
                
        selected_ticker_options = []
        for prof in ["保守", "平衡", "激进"]:
            opts_in_prof = by_profile[prof]
            if not opts_in_prof:
                continue
            passed = [o for o in opts_in_prof if o['passed_gatekeeper']]
            failed = [o for o in opts_in_prof if not o['passed_gatekeeper']]
            if passed:
                passed.sort(key=lambda x: x['total_score'], reverse=True)
                selected_ticker_options.append(passed[0])
            elif failed:
                # Rank failed options by lowest penalty tier, then tightest spread, then highest score
                failed.sort(key=lambda x: (x.get('liq_penalty', 15.0), x['spread_ratio'], -x['total_score']))
                fallback_opt = failed[0]
                pen = fallback_opt.get('liq_penalty', 5.0)
                fallback_opt['warning'] = (pen > 0)
                fallback_opt['total_score'] = max(0.0, fallback_opt['total_score'] - pen)
                selected_ticker_options.append(fallback_opt)
        all_options.extend(selected_ticker_options)
        
    all_options.sort(key=lambda x: x['total_score'], reverse=True)
    
    unique_tickers = []
    for opt in all_options:
        t = opt['ticker']
        if t in low_position_tickers and t not in unique_tickers:
            unique_tickers.append(t)
            
    ticker_balanced_score = {}
    for t in unique_tickers:
        t_opts = [opt for opt in all_options if opt['ticker'] == t]
        bal_opts = [opt for opt in t_opts if opt.get('risk_profile') == '平衡']
        if bal_opts:
            best_opt = max(bal_opts, key=lambda x: x['total_score'])
            ticker_balanced_score[t] = best_opt['total_score']
        elif t_opts:
            best_opt = max(t_opts, key=lambda x: x['total_score'])
            ticker_balanced_score[t] = best_opt['total_score']
        else:
            ticker_balanced_score[t] = -999.0

    def get_relative_price_position(ticker_symbol):
        mdata = ticker_market_data.get(ticker_symbol, {})
        current_price = mdata.get('current_price', 0.0)
        high_52w = mdata.get('high_52w', 0.0)
        low_52w = mdata.get('low_52w', 0.0)
        sma_200 = mdata.get('sma_200', 0.0)
        
        f_info = GLOBAL_FUNDAMENTAL_CACHE.get(ticker_symbol, {}).get("info", {})
        fwd_pe = f_info.get("forwardPE") or f_info.get("trailingPE")
        ocf = f_info.get("operatingCashflow") or f_info.get("freeCashflow")
        deep_val_boost = 0.0
        if fwd_pe and fwd_pe <= 15.0 and ocf and ocf > 0 and not is_etf_symbol(ticker_symbol):
            deep_val_boost = -0.30  # Deep value bonus: relative position discount for ranking priority

        if is_long_bull(ticker_symbol):
            dev = (current_price - sma_200) / sma_200 if sma_200 > 0 else 0.0
            dev = max(-0.15, dev) # Scheme 1: bound maximum negative deviation to -15%
            return (dev / 0.05) + deep_val_boost
        else:
            rp = (current_price - low_52w) / (high_52w - low_52w) if (high_52w - low_52w) > 0 else 0.5
            return ((rp - 0.20) / 0.20) + deep_val_boost
            
    # Sort unique_tickers primarily by balanced option multi-factor total score (descending), secondarily by relative price position (ascending)
    raw_sorted = sorted(unique_tickers, key=lambda t: (-ticker_balanced_score.get(t, -999.0), get_relative_price_position(t)))

    
    # Apply sector concentration limit ONLY to the top 10 items
    ordered_watchlist = []
    sector_counts = {}
    
    # Pass 1: try to fill the top 10 while keeping each sector's count in the top 10 <= 3
    for t in raw_sorted:
        if len(ordered_watchlist) >= 10:
            break
        sec = SECTOR_MAP.get(t) or GLOBAL_FUNDAMENTAL_CACHE.get(t, {}).get("info", {}).get("sector") or ('ETF' if is_etf_symbol(t) else 'Other')
        if sector_counts.get(sec, 0) < 3:
            ordered_watchlist.append(t)
            sector_counts[sec] = sector_counts.get(sec, 0) + 1
            
    # Pass 2: append all other tickers in their raw sorted order
    for t in raw_sorted:
        if t not in ordered_watchlist:
            ordered_watchlist.append(t)
            
    # Pass 3: Guarantee all current position tickers are included in ordered_watchlist (append at end if not ranked)
    for p_ticker in current_position_tickers:
        if p_ticker not in ordered_watchlist:
            ordered_watchlist.append(p_ticker)
            
    try:
        with open(os.path.join(BASE_DIR, "data", "watchlist_tickers.json"), "w") as f:
            json.dump({"tickers": ordered_watchlist}, f, indent=2)
        print(f"Generated ordered watchlist tickers (sector diversified): {ordered_watchlist}")
    except Exception as e:
        print(f"Error writing watchlist_tickers.json: {e}")

    # ==================== COVERED CALL SCAN ====================
    eligible_cc_positions = [p for p in current_equity_positions if equity_info_map.get(p, {}).get("quantity", 0) >= 100.0]
    all_cc_options = []
    
    for pos_ticker in eligible_cc_positions:
        print(f"Processing Covered Call options for {pos_ticker}...")
        pos_info = equity_info_map[pos_ticker]
        avg_cost = pos_info["average_buy_price"]
        qty = pos_info["quantity"]
        yf_ticker = to_yf_symbol(pos_ticker)
        
        hist = ticker_history_map.get(pos_ticker)
        if hist is None or hist.empty:
            try:
                ticker = yf.Ticker(yf_ticker)
                hist = ticker.history(period="1y").dropna(subset=['Close'])
            except Exception:
                hist = None
                
        cached_m = market_history_cache.get(pos_ticker, {})
        if hist is not None and not hist.empty:
            current_price = float(hist['Close'].iloc[-1])
            high_52w = float(hist['Close'].max())
            low_52w = float(hist['Close'].min())
            sma_200 = float(hist['Close'].rolling(200).mean().iloc[-1]) if len(hist) >= 200 else current_price
            returns = np.log(hist['Close'] / hist['Close'].shift(1))
            hv_30 = float((returns.rolling(30).std() * np.sqrt(252) * 100).dropna().iloc[-1]) if not (returns.rolling(30).std() * np.sqrt(252) * 100).dropna().empty else 30.0
            hv_30_clean = pd.Series([hv_30])
        elif cached_m:
            current_price = cached_m.get("current_price", avg_cost)
            high_52w = cached_m.get("high_52w", current_price * 1.25)
            low_52w = cached_m.get("low_52w", current_price * 0.80)
            sma_200 = cached_m.get("sma_200", current_price)
            hv_30 = cached_m.get("hv_30", 30.0)
            hv_30_clean = pd.Series([hv_30])
        else:
            current_price = avg_cost
            high_52w = current_price * 1.25
            low_52w = current_price * 0.80
            sma_200 = current_price
            hv_30 = 30.0
            hv_30_clean = pd.Series([hv_30])
            
        use_cache = pos_ticker in options_cache
        if use_cache:
            exp_dates = list(options_cache[pos_ticker].keys())
        elif scan_targets_data and pos_ticker in scan_targets_data.get("covered_call", {}):
            exp_dates = scan_targets_data["covered_call"][pos_ticker].get("expirations", [])
        else:
            exp_dates = []
            try:
                exp_dates = list(ticker.options)
            except Exception:
                exp_dates = []
            
        ticker_cc_options = []
        for exp_str in exp_dates:
            try:
                exp_date = datetime.datetime.strptime(exp_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            dte = (exp_date - today).days
            if not (15 <= dte <= 45):
                continue
                
            if use_cache:
                cache_calls = options_cache[pos_ticker][exp_str].get("calls", [])
                if not cache_calls:
                    continue
                calls = pd.DataFrame(cache_calls)
            else:
                try:
                    opt_chain = ticker.option_chain(exp_str)
                    calls = opt_chain.calls
                except Exception:
                    continue
                    
            for _, call in calls.iterrows():
                strike = call['strike']
                bid = call['bid']
                ask = call['ask']
                oi = call['openInterest']
                iv = call['impliedVolatility']
                
                if pd.isna(bid) or pd.isna(ask) or bid < 0 or ask < 0:
                    continue
                mark = (bid + ask) / 2.0
                if mark <= 0.01:
                    continue
                    
                spread_ratio = (ask - bid) / mark if mark > 0 else 0.0
                passed_gatekeeper = (spread_ratio <= 0.35) and (oi >= 20)
                
                t_years = dte / 365.0
                raw_delta = call.get('delta')
                if raw_delta is not None and not pd.isna(raw_delta) and float(raw_delta) != 0.0:
                    delta = float(raw_delta)
                else:
                    delta = calculate_call_delta(current_price, strike, t_years, RISK_FREE_RATE, iv)
                
                if strike < avg_cost:
                    continue
                # Conservative Executable Price for Covered Calls
                if spread_ratio > 0.15 and bid > 0:
                    exec_price = min(mark, bid * 1.15)
                elif bid > 0:
                    exec_price = mark
                else:
                    exec_price = mark * 0.50
                    
                annualized_yield = (exec_price / strike) * (365.0 / max(1, dte)) * 100.0
                iv_percent = iv * 100.0
                true_iv = ticker_market_data.get(pos_ticker, {}).get('true_iv_info', {})
                if true_iv.get('has_true_iv'):
                    ivp = true_iv['ivp']
                    ivr = true_iv['ivr']
                    s_iv = true_iv['composite_s_iv']
                    has_true_iv = True
                else:
                    ivp = (hv_30_clean.values < iv_percent).mean() * 100.0 if len(hv_30_clean) > 0 else 0.0
                    ivr = None
                    s_iv = ivp
                    has_true_iv = False
                
                total_score, s_yield, s_safety, s_iv, s_price = calculate_covered_call_score(
                    ticker=pos_ticker,
                    current_price=current_price,
                    avg_cost=avg_cost,
                    strike=strike,
                    delta=delta,
                    mark=mark,
                    annualized_yield=annualized_yield,
                    ivp=ivp,
                    dte=dte,
                    sma_200=sma_200,
                    low_52w=low_52w,
                    high_52w=high_52w,
                )
                
                opt_info = {
                    'ticker': pos_ticker,
                    'current_price': current_price,
                    'avg_cost': avg_cost,
                    'expiration': exp_str,
                    'dte': dte,
                    'strike': strike,
                    'delta': delta,
                    'bid': bid,
                    'ask': ask,
                    'mark': mark,
                    'spread_ratio': spread_ratio,
                    'open_interest': int(oi) if not pd.isna(oi) else 0,
                    'iv': iv_percent,
                    'ivp': ivp,
                    'ivr': ivr,
                    'has_true_iv': has_true_iv,
                    's_yield': s_yield,
                    's_safety': s_safety,
                    's_iv': s_iv,
                    's_price': s_price,
                    'total_score': total_score,
                    'passed_gatekeeper': passed_gatekeeper,
                    'annualized_yield': annualized_yield,
                    'warning': False
                }
                ticker_cc_options.append(opt_info)
                
        passed_options = [o for o in ticker_cc_options if o['passed_gatekeeper']]
        failed_options = [o for o in ticker_cc_options if not o['passed_gatekeeper']]
        selected_ticker_options = []
        if len(passed_options) >= 3:
            passed_options.sort(key=lambda x: x['total_score'], reverse=True)
            selected_ticker_options = passed_options[:5]
        else:
            selected_ticker_options = list(passed_options)
            failed_options.sort(key=lambda x: x['spread_ratio'])
            gap = 3 - len(selected_ticker_options)
            fill_options = failed_options[:gap]
            for opt in fill_options:
                opt['warning'] = True
                opt['total_score'] = max(0.0, opt['total_score'] - 30.0)
                selected_ticker_options.append(opt)
        all_cc_options.extend(selected_ticker_options)

    # ==================== FALLING KNIVES ANALYSIS ====================

    
    circuit_breaker_html = ""
    if macro_circuit_breaker:
        circuit_breaker_html = f"""
        <div class="card" style="margin-top: 16px; margin-bottom: 16px; border-color: rgba(245, 158, 11, 0.4); background: rgba(245, 158, 11, 0.05); backdrop-filter: blur(16px);">
            <div class="card-title" style="color: #fbbf24; border-bottom-color: rgba(245, 158, 11, 0.2); display: flex; align-items: center; gap: 8px;">
                <span>🚨 宏观熔断防守模式已激活 (Macro Circuit Breaker Triggered)</span>
                <span style="font-size: 11px; font-weight: normal; padding: 2px 8px; border-radius: 9999px; background: rgba(245, 158, 11, 0.15); border: 1px solid rgba(245, 158, 11, 0.3); color: #fbbf24;">全场 Delta 强制收紧至 0.25</span>
            </div>
            <p style="font-size: 13.5px; color: var(--text-primary); margin: 0 0 12px 0; line-height: 1.6;">
                <strong>触发原因：</strong> {', '.join(cb_reasons)}。
            </p>
            <p style="font-size: 13px; color: var(--text-secondary); margin: 0; line-height: 1.6;">
                <strong>防守纪律执行中：</strong> 当前大盘进入系统性调整或技术性回撤区间，系统已自动取消所有低位放宽 Delta 特例，将全场卖出 Put 的 Delta 严格锁定在 <code>[-0.25, -0.10]</code> 之间，以保留极致的下跌缓冲垫；同时禁止在非核心题材股上建仓。
            </p>
        </div>
        """
    else:
        circuit_breaker_html = """
        <div class="card" style="margin-top: 16px; margin-bottom: 16px; border-color: rgba(52, 211, 153, 0.2); background: rgba(52, 211, 153, 0.02); backdrop-filter: blur(16px);">
            <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
                <div style="display: flex; align-items: center; gap: 10px; color: #34d399; font-size: 13.5px; font-weight: 500;">
                    <span>✅</span>
                    <span>大盘宏观熔断阀监控正常（SPY / QQQ 近30天未出现 &ge;8% 系统性急跌），未触发熔断。</span>
                </div>
                <span style="font-size: 11px; padding: 2px 8px; border-radius: 4px; background: rgba(52, 211, 153, 0.1); color: #34d399; border: 1px solid rgba(52, 211, 153, 0.2);">正常策略模式</span>
            </div>
        </div>
        """
    
    macro_sentiment_html = circuit_breaker_html

    # ==================== TICKER DEEP-DIVE MAP FOR GROUPED CARDS ====================
    active_tickers_list = list(active_tickers.keys())
    sorted_tickers = []
    for t in ordered_watchlist:
        if t in active_tickers_list and t not in sorted_tickers:
            sorted_tickers.append(t)
    for t in active_tickers_list:
        if t not in sorted_tickers:
            sorted_tickers.append(t)

    ticker_deep_dive_map = {}
    ticker_info_map = {}
    
    print("Fetching fundamental data and building deep dive cards for all grouped tickers...")
    for ticker_name in sorted_tickers:
        try:
            info = get_fundamental_info(ticker_name)
            
            company_name = info.get("longName", info.get("shortName", ticker_name))
            fcf = info.get("freeCashflow")
            roe = info.get("returnOnEquity")
            de = info.get("debtToEquity")
            forward_pe = info.get("forwardPE")
            peg = info.get("pegRatio")
            target_price = info.get("targetMeanPrice")
            curr_price = info.get("currentPrice") or info.get("regularMarketPrice") or ticker_market_data.get(ticker_name, {}).get('current_price', 0.0)
            
            m_data = ticker_market_data.get(ticker_name, {})
            low_52w = m_data.get('low_52w', 0.0)
            high_52w = m_data.get('high_52w', 100.0)
            sma_200 = m_data.get('sma_200', 0.0)
            rp = (curr_price - low_52w) / (high_52w - low_52w) if (high_52w - low_52w) > 0 else 0.5
            dev = (curr_price - sma_200) / sma_200 if sma_200 > 0 else 0.0
            
            if is_etf_symbol(ticker_name):
                fcf_status = "⚪ N/A"
                fcf_val_str = "N/A"
                roe_status = "⚪ N/A"
                roe_val_str = "N/A"
                de_status = "⚪ N/A"
                de_val_str = "N/A"
                peg_status = "⚪ N/A"
                peg_val_str = "N/A"
                target_discount = 0
                val_status = "⚪ N/A"
                val_val_str = "N/A"
                f_score_val = None
                f_score_status_str = "⚪ N/A"
            else:
                ocf = info.get("operatingCashflow")
                ebitda_m = info.get("ebitdaMargins")
                if fcf is not None and fcf > 0:
                    fcf_status = "🟢 优异"
                    fcf_val_str = f"${fcf/1e9:.2f}B"
                elif ocf is not None and ocf > 0 and ebitda_m is not None and ebitda_m > 0.08:
                    fcf_status = "🟡 稳健(OCF+)"
                    fcf_val_str = f"${fcf/1e9:.2f}B" if fcf is not None else f"${ocf/1e9:.2f}B"
                elif fcf is None:
                    fcf_status = "⚪ N/A"
                    fcf_val_str = "N/A"
                else:
                    fcf_status = "🔴 警告"
                    fcf_val_str = f"${fcf/1e9:.2f}B"
                
                roe_status = "🟢 优异" if (roe is not None and roe >= 0.12) else ("🟡 偏低" if (roe is not None and roe >= 0.05) else ("⚪ N/A" if roe is None else "🔴 警告"))
                roe_val_str = f"{roe*100:.1f}%" if roe is not None else "N/A"
                
                de_status = "🟢 安全" if (de is not None and de <= 150) else ("🟡 偏高" if (de is not None and de <= 250) else ("⚪ N/A" if de is None else "🔴 高风险"))
                de_val_str = f"{de:.1f}%" if de is not None else "N/A"
                
                peg_status = "🟢 便宜" if (peg is not None and peg <= 1.2) else ("🟡 合理" if (peg is not None and peg <= 1.8) else ("⚪ N/A" if peg is None else "🔴 偏高"))
                peg_val_str = f"{peg:.2f}" if peg is not None else "N/A"
                
                target_discount = ((target_price - curr_price) / target_price * 100) if target_price and curr_price else 0
                if target_price is None or target_price <= 0:
                    val_status = "⚪ N/A"
                    val_val_str = "N/A"
                else:
                    val_status = "🟢 洼地" if target_discount >= 15 else ("🟡 合理" if target_discount >= 0 else "🔴 溢价")
                    val_val_str = f"折价 {target_discount:.1f}%" if target_discount > 0 else (f"溢价 {abs(target_discount):.1f}%" if target_discount else "N/A")
            
                f_score_val, _ = calculate_piotroski_f_score(info)
                if f_score_val is not None:
                    f_score_status_str = "🟢 极高质" if f_score_val >= 7 else ("🟡 中等" if f_score_val >= 4 else "🔴 一票否决")
                else:
                    f_score_status_str = "⚪ N/A"
            
            ticker_opts = [o for o in all_options if o['ticker'] == ticker_name]
            best_strike = ticker_opts[0]['strike'] if ticker_opts else curr_price * 0.9
            strike_discount = (curr_price - best_strike) / curr_price * 100 if curr_price > 0 else 0
            strike_pe = (forward_pe * (best_strike / curr_price)) if forward_pe and curr_price else 0
            
            statuses = [fcf_status, roe_status, de_status, peg_status, val_status]
            available_count = sum([1 for s in statuses if "⚪" not in s])
            pass_count = sum([1 for s in statuses if "🟢" in s])
            
            earnings_ts = info.get('earningsTimestampStart') or info.get('earningsTimestamp')
            earnings_date_str = None
            dte_earnings = None
            if earnings_ts:
                try:
                    earnings_date = datetime.datetime.fromtimestamp(earnings_ts, tz=datetime.timezone.utc).date()
                    earnings_date_str = earnings_date.strftime('%Y-%m-%d')
                    dte_earnings = (earnings_date - today).days
                except Exception:
                    pass
            
            ticker_info_map[ticker_name] = {
                "company_name": company_name,
                "target_price": target_price,
                "target_discount": target_discount,
                "forward_pe": forward_pe,
                "pass_count": pass_count,
                "available_count": available_count,
                "earnings_date_str": earnings_date_str,
                "dte_earnings": dte_earnings
            }
            
            if is_etf_symbol(ticker_name):
                verdict = "【ETF 基金 • 适合指数配置】"
                verdict_color = "#34d399"
            elif available_count == 0:
                verdict = "【暂无财报数据 • 建议独立评估】"
                verdict_color = "#a1a1aa"
            else:
                pass_ratio = pass_count / available_count
                if pass_ratio >= 0.8:
                    verdict = "【优质价值洼地 • 强力推荐】"
                    verdict_color = "#34d399"
                elif pass_ratio >= 0.4:
                    verdict = "【中性资产 • 建议稳健建仓】"
                    verdict_color = "#fbbf24"
                else:
                    verdict = "【风险资产 • 建议防范风险】"
                    verdict_color = "#f87171"
                
            if is_etf_symbol(ticker_name):
                analysis_desc = "该标的为宽基/行业 ETF，具备天然的底层资产分散度，接股相当于买入一揽子成分股。"
            elif available_count == 0:
                analysis_desc = "由于该标的缺乏公开的财务指标（如自由现金流、ROE 等），无法评估其量化财务健康度，请手动核对财报。"
            elif available_count < 5:
                analysis_desc = f"该标的由于部分财务数据缺失，已评估的财务指标中有 {pass_count}/{available_count} 项符合安全价值标准。"
                if fcf and fcf <= 0:
                    analysis_desc += " 警告：公司自由现金流为负，属于失血状态，接股风险极大。"
                if de and de > 200:
                    analysis_desc += " 警告：公司债务杠杆偏高，利息开支可能压制净利润。"
                if roe and roe < 0.08:
                    analysis_desc += " 提示：资本回报率偏低，公司盈利效率有待提升。"
                if target_discount > 20:
                    analysis_desc += f" 当前股价较分析师目标价 ${target_price:.2f} 折价达 {target_discount:.1f}%，具备极高估值安全边际。"
            else:
                analysis_desc = f"该标的各项财务指标中有 {pass_count}/5 项符合安全价值标准。"
                if fcf and fcf <= 0:
                    analysis_desc += " 警告：公司自由现金流为负，属于失血状态，接股风险极大。"
                if de and de > 200:
                    analysis_desc += " 警告：公司债务杠杆偏高，利息开支可能压制净利润。"
                if roe and roe < 0.08:
                    analysis_desc += " 提示：资本回报率偏低，公司盈利效率有待提升。"
                if target_discount > 20:
                    analysis_desc += f" 当前股价较分析师目标价 ${target_price:.2f} 折价达 {target_discount:.1f}%，具备极高估值安全边际。"
            
            if ticker_name in TICKER_RISKS:
                risk_desc = TICKER_RISKS[ticker_name]
            elif ticker_name.replace('.', '-') in TICKER_RISKS:
                risk_desc = TICKER_RISKS[ticker_name.replace('.', '-')]
            else:
                sector = SECTOR_MAP.get(ticker_name, SECTOR_MAP.get(ticker_name.replace('.', '-'), 'General'))
                sector_defaults = {
                    'Semiconductors': '1. 行业具有极强的强周期属性，对全球半导体资本开支及库存周期高度敏感；2. 尖端制程与 AI 芯片面临严厉的地缘政治与出口管制风险；3. 研发及流片成本巨大，若下游需求不及预期易出现折旧与估值双杀。',
                    'SaaS & Cyber': '1. 估值倍数（PS/PE）通常较高，在宏观逆风或营收增速微降时极易发生杀估值回撤；2. 企业 IT 预算收紧会显著拉长订单签约周期；3. 赛道技术迭代极快，面临微软及行业龙头强烈的 bundle 捆绑竞争。',
                    'Healthcare & MedTech': '1. 新药研发管线与 FDA 临床试验审批具有极大的二进制不确定性（成功/失败）；2. 核心重磅药物面临专利悬崖及生物类似药的剧烈侵蚀；3. 受医保集采与定价谈判（IRA 法案）政策压制。',
                    'Financials & Crypto': '1. 宏观利率调控对银行净息差（NIM）及资管规模（AUM）影响显著；2. 持续面临关于资本充足率、手续费及反垄断的严厉监管审查；3. 宏观经济衰退可能引发信贷违约率上升或交易量萎缩。',
                    'Consumer & Staples': '1. 通胀下消费者可支配收入受限或企业削减资本开支，直接压制同店销售与出货量；2. 原材料及人工劳动力成本上涨压缩毛利率；3. 全球供应链及汇率波动风险。',
                    'Industrials & Aerospace': '1. 业绩对全球宏观经济景气度、制造业 PMI 及设备更新周期极其敏感；2. 人工工资通胀与原材料价格波动侵蚀制造毛利率；3. 供应链干扰或关键地缘贸易摩擦风险。',
                    'Energy & Commodities': '1. 业绩高度绑定原油、天然气或工业金属的国际大宗商品周期价格；2. 面临全球碳减排政策与清洁能源转型的长期结构性需求压制；3. 地缘冲突及产油国减产决定的不确定性。',
                    'ETF': '1. 追踪特定指数或板块，完全承担该行业或市场的系统性 Beta 波动风险；2. 宏观利率、通胀数据及美联储货币政策转向将对基金净值产生直接冲击；3. 资金流动性与情绪面溢价波动。',
                    'Tech': '1. 高度依赖技术创新与软硬件升级周期，颠覆性技术可能快速重塑行业竞争格局；2. 面临全球严厉的反垄断、数据安全及隐私监管审查；3. 估值溢价受美联储利率预期影响较大。',
                    'China ADR': '1. 业绩表现与中国国内宏观经济复苏及消费信心紧密相关；2. 行业竞争极其激烈，低价补贴战蚕食企业利润；3. 持续面临地缘政治以及跨境监管不确定性。'
                }
                risk_desc = sector_defaults.get(sector, "1. 需关注宏观经济与美联储利率政策走势对该标的估值的系统性压制；2. 需防范行业竞争加剧、原材料或人力成本上升带来的毛利率侵蚀；3. 建议在建仓前详细核查其最新财报与现金流状况。")
                
            dev_color = "#34d399" if dev <= 0.00 else "#f87171"
            rp_color = "#34d399" if rp <= 0.20 else "#f87171"
            
            if ticker_name in current_position_tickers:
                badge_text = "当前持仓标的"
                badge_bg = "rgba(96, 165, 250, 0.15)"
                badge_color = "#60a5fa"
            elif ticker_name in PRESELECTED_TICKERS:
                badge_text = "核心自选池"
                badge_bg = "rgba(168, 85, 247, 0.15)"
                badge_color = "#c084fc"
            else:
                badge_text = "动态推荐标的"
                badge_bg = "rgba(52, 211, 153, 0.15)"
                badge_color = "#34d399"
                
            intro_text = TICKER_INTROS.get(ticker_name, TICKER_INTROS.get(ticker_name.replace('.', '-'), ''))
            if not intro_text:
                sector = SECTOR_MAP.get(ticker_name, SECTOR_MAP.get(ticker_name.replace('.', '-'), 'General'))
                sector_intros = {
                    'Semiconductors': '全球半导体与芯片产业链核心优质龙头。',
                    'SaaS & Cyber': '企业云服务 SaaS 与网络安全领域龙头标的。',
                    'Healthcare & MedTech': '全球生物医药、创新药与医疗技术核心标的。',
                    'Financials & Crypto': '顶级银行、资管、互金与金融服务巨头。',
                    'Consumer & Staples': '全球消费品、零售与高防守型必需消费品龙头。',
                    'Industrials & Aerospace': '工程机械、航空航天与国防军工核心龙头。',
                    'Energy & Commodities': '原油、天然气、工业金属与大宗商品核心标的。',
                    'ETF': '追踪大盘或特定行业指数的宽基/行业主题 ETF。',
                    'Tech': '全球消费电子、移动生态与前沿科技创新巨头。',
                    'China ADR': '中国海外上市互联网与消费精选优质龙头。'
                }
                intro_text = f"{company_name}，{sector_intros.get(sector, '全市场精选优质标的。')}"
                
            safe_intro_text = html.escape(intro_text)
            tv_url = get_tradingview_url(ticker_name)
            tv_btn = f'<a href="{tv_url}" target="_blank" onclick="event.stopPropagation();" style="font-size: 11.5px; font-weight: 600; color: #60a5fa; text-decoration: none; padding: 2px 8px; border-radius: 4px; background: rgba(96, 165, 250, 0.1); border: 1px solid rgba(96, 165, 250, 0.3); display: inline-flex; align-items: center; gap: 4px;" title="在 TradingView 查看 K线图表">📈 TradingView</a>'
            
            # If the ticker is a falling knife, fetch or construct its qualitative analysis
            knife_analysis_block = ""
            is_knife = ticker_market_data.get(ticker_name, {}).get('is_falling_knife', False)
            if is_knife:
                ret_30 = ticker_market_data[ticker_name].get('return_30d', 0.0)
                fund = TICKER_FUNDAMENTALS.get(ticker_name, {
                    'name': company_name,
                    'verdict': '【需独立评估】',
                    'verdict_color': '#a1a1aa',
                    'analysis': '该标的近期跌幅较大触发飞刀预警。暂无系统预设的基本面深度解析，请在建仓前务必独立确认其最新财报、行业竞争格局及监管政策，防范基本面恶化风险。'
                })
                safe_analysis = html.escape(fund['analysis'])
                knife_analysis_block = f"""
                            <!-- 飞刀警示与专家研判 -->
                            <div style="margin-bottom: 14px; padding: 12px 16px; background: rgba(239, 68, 68, 0.06); border: 1px solid rgba(239, 68, 68, 0.2); border-left: 4px solid #ef4444; border-radius: 8px; font-size: 13px; line-height: 1.5; color: #f87171; font-family: -apple-system, sans-serif;">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-weight: bold; flex-wrap: wrap; gap: 8px;">
                                    <span style="display: flex; align-items: center; gap: 4px;">🚨 急跌飞刀预警（近30天急跌 {abs(ret_30)*100:.1f}%）</span>
                                    <span style="color: {fund['verdict_color']};">{fund['verdict']}</span>
                                </div>
                                <p style="margin: 0; color: #e4e4e7; font-size: 12.5px; line-height: 1.6;">
                                    <strong>基本面研判：</strong> {safe_analysis}
                                </p>
                            </div>
                """

            # Conditionally generate fundamentals table or ETF notice
            if is_etf_symbol(ticker_name):
                fundamentals_table_html = """
                            <div style="padding: 16px; border: 1px solid #27272a; border-radius: 8px; background: rgba(255, 255, 255, 0.01); text-align: center; color: #a1a1aa; font-size: 13.5px; margin-bottom: 16px; font-family: -apple-system, sans-serif;">
                                💡 <strong>本标的为 ETF 基金</strong>，其健康度与底层指数成分挂钩，不适用个股财务健康度（FCF/ROE/Debt/PEG）指标评价。
                            </div>
                """
            else:
                fundamentals_table_html = f"""
                            <div style="overflow-x: auto; margin-bottom: 16px;">
                                <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 12.5px; color: var(--text-primary);">
                                    <tr style="border-bottom: 1px solid rgba(255,255,255,0.08); height: 32px;">
                                        <th style="color: var(--text-secondary); font-weight: 500; padding: 6px 12px;">财务指标</th>
                                        <th style="color: var(--text-secondary); font-weight: 500; padding: 6px 12px;">当前数值</th>
                                        <th style="color: var(--text-secondary); font-weight: 500; padding: 6px 12px;">安全门槛</th>
                                        <th style="color: var(--text-secondary); font-weight: 500; padding: 6px 12px;">健康状态</th>
                                    </tr>
                                    <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); height: 32px;">
                                        <td style="padding: 6px 12px;">自由现金流 (Free Cash Flow)</td>
                                        <td style="padding: 6px 12px; font-weight: 500;">{fcf_val_str}</td>
                                        <td style="padding: 6px 12px; color: var(--text-secondary);">&gt; $0 (正流入)</td>
                                        <td style="padding: 6px 12px; font-weight: 600;">{fcf_status}</td>
                                    </tr>
                                    <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); height: 32px;">
                                        <td style="padding: 6px 12px;">净资产收益率 (ROE)</td>
                                        <td style="padding: 6px 12px; font-weight: 500;">{roe_val_str}</td>
                                        <td style="padding: 6px 12px; color: var(--text-secondary);">&ge; 12.0%</td>
                                        <td style="padding: 6px 12px; font-weight: 600;">{roe_status}</td>
                                    </tr>
                                    <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); height: 32px;">
                                        <td style="padding: 6px 12px;">资产负债率 (Debt to Equity)</td>
                                        <td style="padding: 6px 12px; font-weight: 500;">{de_val_str}</td>
                                        <td style="padding: 6px 12px; color: var(--text-secondary);">&le; 150.0%</td>
                                        <td style="padding: 6px 12px; font-weight: 600;">{de_status}</td>
                                    </tr>
                                    <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); height: 32px;">
                                        <td style="padding: 6px 12px;">估值增速比 (PEG Ratio)</td>
                                        <td style="padding: 6px 12px; font-weight: 500;">{peg_val_str}</td>
                                        <td style="padding: 6px 12px; color: var(--text-secondary);">&le; 1.50</td>
                                        <td style="padding: 6px 12px; font-weight: 600;">{peg_status}</td>
                                    </tr>
                                    <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); height: 32px;">
                                        <td style="padding: 6px 12px;">Piotroski F-Score (质量得分)</td>
                                        <td style="padding: 6px 12px; font-weight: 500;">{f"{f_score_val}/9 分" if f_score_val is not None else "N/A"}</td>
                                        <td style="padding: 6px 12px; color: var(--text-secondary);">&ge; 7分 (低水淘汰≤3分)</td>
                                        <td style="padding: 6px 12px; font-weight: 600;">{f_score_status_str}</td>
                                    </tr>
                                    <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); height: 32px;">
                                        <td style="padding: 6px 12px;">分析师估值折让 (Target Discount)</td>
                                        <td style="padding: 6px 12px; font-weight: 500;">{val_val_str}</td>
                                        <td style="padding: 6px 12px; color: var(--text-secondary);">&ge; 15.0% 折价</td>
                                        <td style="padding: 6px 12px; font-weight: 600;">{val_status}</td>
                                    </tr>
                                </table>
                            </div>
                """

            # Insider sentiment for deep dive
            insider_data_dd = insider_sentiment_map.get(ticker_name, {})
            insider_badge_dd = insider_data_dd.get("badge_html", "")
            insider_summary_dd = insider_data_dd.get("summary_text", "暂无显著高管减持或异常预警")

            deep_dive_block = f"""
                        <div id="deep-dive-{ticker_name.replace('.', '-')}" style="background: rgba(255, 255, 255, 0.015); border: 1px solid #27272a; border-radius: 10px; padding: 18px; margin-bottom: 20px;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; flex-wrap: wrap; gap: 8px;">
                                <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                                    <strong style="font-size: 15px; color: #ffffff;">🔍 基本面与估值深度剖析 • {company_name}</strong>
                                    <span style="font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 9999px; background: {badge_bg}; color: {badge_color}; border: 1px solid {badge_color};">{badge_text}</span>
                                    {tv_btn}
                                </div>
                                <span style="font-size: 13px; font-weight: 700; color: {verdict_color};">{verdict}</span>
                            </div>
                            
                            {knife_analysis_block}
                            
                            <div style="margin-bottom: 14px; padding: 10px 14px; background: rgba(59, 130, 246, 0.08); border-left: 3px solid #3b82f6; border-radius: 6px; font-size: 13px; color: #e4e4e7; line-height: 1.5;">
                                <strong style="color: #60a5fa;">💡 标的简介：</strong> {intro_text}
                            </div>
                            
                            <!-- 当前价格与技术位置 -->
                            <div style="display: flex; gap: 16px; margin-bottom: 16px; padding: 12px 16px; background: rgba(0, 0, 0, 0.4); border: 1px solid #27272a; border-radius: 8px; font-size: 13px; flex-wrap: wrap;">
                                <div style="flex: 1; min-width: 120px;">
                                    <span style="color: var(--text-secondary);">当前股价:</span>
                                    <strong style="color: #ffffff; font-size: 14px; margin-left: 4px;">${curr_price:.2f}</strong>
                                </div>
                                <div style="flex: 1; min-width: 180px;">
                                    <span style="color: var(--text-secondary);">52周区间:</span>
                                    <span style="color: #ffffff; font-weight: 500; margin-left: 4px;">${low_52w:.2f} - ${high_52w:.2f}</span>
                                    <span style="color: {rp_color}; font-size: 11px; font-weight: 600; margin-left: 4px;">(相对位置 RP: {rp*100:.1f}%)</span>
                                </div>
                                <div style="flex: 1; min-width: 180px;">
                                    <span style="color: var(--text-secondary);">200日均线:</span>
                                    <span style="color: #ffffff; font-weight: 500; margin-left: 4px;">${sma_200:.2f}</span>
                                    <span style="color: {dev_color}; font-size: 11px; font-weight: 600; margin-left: 4px;">(偏离度: {dev*100:+.1f}%)</span>
                                </div>
                            </div>
                            
                            {fundamentals_table_html}
                            
                            <!-- Bear Case 红队防雷逆向检验 -->
                            <div style="margin-bottom: 14px; padding: 12px 16px; background: rgba(168, 85, 247, 0.05); border: 1px solid rgba(168, 85, 247, 0.2); border-left: 4px solid #c084fc; border-radius: 8px; font-size: 12.5px; line-height: 1.5; color: var(--text-primary);">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-weight: bold;">
                                    <span style="color: #c084fc; display: flex; align-items: center; gap: 4px;">🥊 Bear Case 红队防雷逆向检验 (Devil's Advocate Audit)</span>
                                    <span style="font-size: 11px; font-weight: 600; padding: 2px 6px; border-radius: 4px; background: {'rgba(239, 68, 68, 0.15)' if (is_knife or (fcf and fcf <= 0)) else 'rgba(52, 211, 153, 0.15)'}; color: {'#f87171' if (is_knife or (fcf and fcf <= 0)) else '#34d399'};">
                                        {'[🔴 红队建议: 财报损伤/慎防接飞刀]' if (is_knife or (fcf and fcf <= 0)) else '[🟢 红队建议: 财务稳健/属情绪超跌]'}
                                    </span>
                                </div>
                                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 8px; margin-bottom: 6px;">
                                    <div><strong>1. 利润质量 (GAAP vs Non-GAAP):</strong> <span style="color: var(--text-secondary);">{'警惕重度 SBC 股权激励调增' if (peg and peg > 2.0) else 'GAAP 盈利真实度良好'}</span></div>
                                    <div><strong>2. FCF 现金消耗 (Burn Rate):</strong> <span style="color: var(--text-secondary);">{f'失血状态 ({fcf_val_str})' if (fcf and fcf <= 0) else f'现金流充沛 ({fcf_val_str})'}</span></div>
                                    <div><strong>3. 债务杠杆 (Debt to Equity):</strong> <span style="color: var(--text-secondary);">{f'负债率过高 ({de_val_str})' if (de and de > 200) else f'债务可控 ({de_val_str})'}</span></div>
                                    <div><strong>4. 高管增减持 (SEC Form 4):</strong> {insider_badge_dd} <span style="color: var(--text-secondary); font-size: 11.5px;">{insider_summary_dd}</span></div>
                                </div>
                            </div>

                            <p style="font-size: 13px; color: var(--text-secondary); margin: 0 0 12px 0; line-height: 1.6;">
                                <strong>最差情况接股分析：</strong> 如果期权被行权（以 <strong>${best_strike:.2f}</strong> 接股），对应的行权价 Forward P/E 将降至 <strong>{f"{strike_pe:.1f}x" if strike_pe else "N/A"}</strong>（当前 Forward P/E 为 {f"{forward_pe:.1f}x" if forward_pe else "N/A"}）。接股价格较当前股价折让 <strong>{strike_discount:.1f}%</strong>。{analysis_desc}
                            </p>

                            <!-- 策略逻辑失效条件与重估 Trigger -->
                            <div style="margin-bottom: 12px; padding: 10px 14px; background: rgba(239, 68, 68, 0.04); border: 1px solid rgba(239, 68, 68, 0.15); border-radius: 6px; font-size: 12px; color: #f87171; line-height: 1.5;">
                                <strong>🚨 策略逻辑失效条件 (Thesis Invalidation)：</strong> 假设在建仓期间，股价有效跌破 200 日线 <strong>-8.0%</strong> 以上，或大盘恐慌指数 VIX 冲破 <strong>30</strong> 触发红灯防守，则本合约的“低位接股”假设判定失效，需取消后续卖出或实施向下 Roll 防守！
                                <br><span style="color: var(--text-secondary); font-size: 11px;">🔄 <strong>重估 Trigger：</strong> 距财报天数 < 7 天 | 股价单日波动 > ±8% | 行业出现重大监管事件。</span>
                            </div>

                            <p style="font-size: 13px; color: #f87171; margin: 0; line-height: 1.6; padding: 10px 14px; background: rgba(248, 113, 113, 0.06); border-left: 3px solid #f87171; border-radius: 4px;">
                                <strong>🚨 核心风险提示：</strong> {risk_desc}
                            </p>
                        </div>
            """
            ticker_deep_dive_map[ticker_name] = deep_dive_block
        except Exception as e:
            print(f"Error fetching fundamentals for {ticker_name}: {e}")
            ticker_info_map[ticker_name] = {
                "company_name": ticker_name,
                "target_price": 0,
                "target_discount": 0,
                "forward_pe": 0,
                "pass_count": 0
            }
            tv_url = get_tradingview_url(ticker_name)
            tv_btn = f'<a href="{tv_url}" target="_blank" onclick="event.stopPropagation();" style="font-size: 11.5px; font-weight: 600; color: #60a5fa; text-decoration: none; padding: 2px 8px; border-radius: 4px; background: rgba(96, 165, 250, 0.1); border: 1px solid rgba(96, 165, 250, 0.3); display: inline-flex; align-items: center; gap: 4px;" title="在 TradingView 查看 K线图表">📈 TradingView</a>'
            ticker_deep_dive_map[ticker_name] = f"""
                        <div id="deep-dive-{ticker_name.replace('.', '-')}" style="background: rgba(255, 255, 255, 0.015); border: 1px solid #27272a; border-radius: 10px; padding: 18px; margin-bottom: 20px;">
                            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px;">
                                <strong style="font-size: 15px; color: #ffffff;">🔍 基本面深度剖析 • {ticker_name}</strong>
                                {tv_btn}
                            </div>
                            <p style="font-size: 13px; color: #f87171; margin: 8px 0 0 0;">[⚠️基本面数据获取失败] 无法调用 API 评估其价值属性，请手动确认其基本面状况后再做建仓决策。</p>
                        </div>
            """
    new_tickers_analysis_html = ""

    # ==================== HTML GENERATION ====================
    profile_tags = {
        "保守": "<span style='padding: 2px 6px; border-radius: 4px; background-color: #065f46; color: #34d399; font-size: 11px; font-weight: 600;'>保守</span>",
        "平衡": "<span style='padding: 2px 6px; border-radius: 4px; background-color: #1e3a8a; color: #93c5fd; font-size: 11px; font-weight: 600;'>平衡</span>",
        "激进": "<span style='padding: 2px 6px; border-radius: 4px; background-color: #78350f; color: #fcd34d; font-size: 11px; font-weight: 600;'>激进</span>"
    }

    # Generate Candidate Watchlist Table (Grouped by Ticker & Valuation Monitor)
    tv_formatted_tickers = [format_tradingview_ticker(t) for t in ordered_watchlist]
    tv_copy_str = ", ".join(tv_formatted_tickers)
    tv_plain_copy_str = ", ".join([to_rh_symbol(t) for t in ordered_watchlist])
    
    tv_card_html = f"""
    <div style="margin-bottom: 16px; padding: 16px; background: linear-gradient(135deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.8) 100%); border: 1px solid rgba(96, 165, 250, 0.3); border-radius: 10px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3);">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; flex-wrap: wrap; gap: 8px;">
        <span style="font-size: 14px; font-weight: 600; color: #60a5fa; display: flex; align-items: center; gap: 8px;">
          <span>📈</span> TradingView 一键复制自选股 (Watchlist Sync String)
        </span>
        <div style="display: flex; gap: 8px; flex-wrap: wrap;">
          <button onclick="navigator.clipboard.writeText('{tv_plain_copy_str}'); alert('✅ 纯代码文本已复制！直接在 TradingView 粘贴即可 100% 自动识别，零前缀错误！');" style="background: rgba(52, 211, 153, 0.2); border: 1px solid rgba(52, 211, 153, 0.5); color: #34d399; padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 700; cursor: pointer; transition: all 0.2s;">
            📋 一键复制纯代码 (推荐·零前缀错误)
          </button>
          <button onclick="navigator.clipboard.writeText('{tv_copy_str}'); alert('TradingView 带交易所前缀文本已复制！');" style="background: rgba(96, 165, 250, 0.15); border: 1px solid rgba(96, 165, 250, 0.4); color: #60a5fa; padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.2s;">
            📋 复制带交易所前缀
          </button>
        </div>
      </div>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 8px;">
        <div>
          <div style="font-size: 11px; font-weight: 600; color: #34d399; margin-bottom: 4px;">🟢 纯代码模式 (Pure Tickers - TradingView 官方自动匹配交易所，100% 成功率):</div>
          <div style="background: #09090b; border: 1px solid #27272a; border-radius: 6px; padding: 8px 10px; font-family: SFMono-Regular, Consolas, 'Liberation Mono', Menlo, monospace; font-size: 11.5px; color: #34d399; word-break: break-all; max-height: 65px; overflow-y: auto; line-height: 1.4; user-select: all;">
            {tv_plain_copy_str}
          </div>
        </div>
        <div>
          <div style="font-size: 11px; font-weight: 600; color: #60a5fa; margin-bottom: 4px;">🔵 带交易所前缀 (Exchange Prefixes - 官方主板映射):</div>
          <div style="background: #09090b; border: 1px solid #27272a; border-radius: 6px; padding: 8px 10px; font-family: SFMono-Regular, Consolas, 'Liberation Mono', Menlo, monospace; font-size: 11.5px; color: #60a5fa; word-break: break-all; max-height: 65px; overflow-y: auto; line-height: 1.4; user-select: all;">
            {tv_copy_str}
          </div>
        </div>
      </div>
      <div style="font-size: 11px; color: #a1a1aa; margin-top: 10px; line-height: 1.4;">
        💡 <strong>使用指引</strong>：在 TradingView 界面按 <code>Cmd+A</code> ➔ <code>Delete</code> 清空旧自选股，或点击右上角 <strong><code>...</code> ➔ Import Watchlist</strong> 选文件；也可直接点击 <code>+</code> 添加代码并在输入框直接粘贴上面任一框的代码！
      </div>
    </div>
    """

    table_grouped = tv_card_html + """
    <div style="overflow-x: auto; border: 1px solid #27272a; border-radius: 10px; background-color: #09090b; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.2);">
      <table style="border-collapse: collapse; width: 100%; text-align: left; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 13px; line-height: 1.5; color: #f4f4f5;">
        <thead style="background-color: #18181b; color: #ffffff; border-bottom: 2px solid #27272a;">
          <tr>
            <th style="padding: 12px 14px; font-weight: 600; text-align: center; width: 45px; white-space: nowrap;">排名</th>
            <th style="padding: 12px 14px; font-weight: 600; white-space: nowrap;">标的名称</th>
            <th style="padding: 12px 14px; font-weight: 600; white-space: nowrap;">当前股价</th>
            <th style="padding: 12px 14px; font-weight: 600; white-space: nowrap;">下次财报日</th>
            <th style="padding: 12px 14px; font-weight: 600; white-space: nowrap;">财务健康度</th>
            <th style="padding: 12px 14px; font-weight: 600; white-space: nowrap;">52周区间与位置 (RP)</th>
            <th style="padding: 12px 14px; font-weight: 600; white-space: nowrap;">200日均线偏离度</th>
            <th style="padding: 12px 14px; font-weight: 600; white-space: nowrap;">首选行权价 (平衡型)</th>
            <th style="padding: 12px 14px; font-weight: 600; text-align: center; white-space: nowrap;" title="252日真实历史隐含波动率百分位 (IVP)">IVP</th>
            <th style="padding: 12px 14px; font-weight: 600; text-align: center; white-space: nowrap;">InvestSkill 研报信号</th>
            <th style="padding: 12px 14px; font-weight: 600; text-align: center; white-space: nowrap;" title="三支柱多因子打分: 估值底 (40%) / 接股安全 (30%) / 期权Alpha (30%)">期权评分 (平衡型)<br><span style="font-size: 10px; font-weight: normal; color: #a1a1aa;">(估值 / 安全 / Alpha)</span></th>
          </tr>
        </thead>
        <tbody>"""
        
    # ==================== InvestSkill 100% Coverage & Freshness Guarantee (<= 7 Days) ====================
    report_stock_tickers = set()
    for t in ordered_watchlist:
        if not is_etf_symbol(t):
            report_stock_tickers.add(normalize_symbol(t))
    if isinstance(current_positions, list):
        for p in current_positions:
            if isinstance(p, dict) and p.get("symbol") and not is_etf_symbol(p["symbol"]):
                report_stock_tickers.add(normalize_symbol(p["symbol"]))
    if isinstance(current_equity_positions, list):
        for sym in current_equity_positions:
            if sym and not is_etf_symbol(sym):
                report_stock_tickers.add(normalize_symbol(sym))

    investskill_reports = scan_investskill_reports(INVESTSKILL_OUTPUT_DIR, max_age_days=7)
    
    missing_or_stale = []
    for t in sorted(list(report_stock_tickers)):
        clean_t = t.upper().strip()
        info = investskill_reports.get(clean_t) or investskill_reports.get(clean_t.replace('.', '-')) or investskill_reports.get(clean_t.replace('-', '.'))
        if not info or info.get("is_stale", True) or info.get("age_days", 999) > 7:
            missing_or_stale.append(clean_t)

    if missing_or_stale:
        print(f"ℹ️ [InvestSkill Status] 检测到 {len(missing_or_stale)} 只个股标的在 ~/InvestSkill/output 中缺失或研报已过期 (>7天): {missing_or_stale} (可通过 AI 对话调用 InvestSkill 框架生成)")
    else:
        print(f"✅ [InvestSkill Status] 100% 个股标的均具备 7 天以内的最新深度研报 ({len(report_stock_tickers)} 只个股已全量覆盖)")

    for idx, t in enumerate(ordered_watchlist):
        bg_c = "#09090b" if idx % 2 == 0 else "#18181b"
        mdata = ticker_market_data.get(t, {})
        tinfo = ticker_info_map.get(t, {})
        fund_info = get_fundamental_info(t)
        f_score_tuple = calculate_piotroski_f_score(fund_info)
        f_score_t = f_score_tuple[0] if f_score_tuple else None
        is_high_qual_t = is_etf_symbol(t) or (f_score_t is not None and f_score_t >= 7) or (insider_sentiment_map.get(t, {}).get('sentiment') == 'net_buying')
        
        curr_p = mdata.get('current_price', 0.0)
        low_52 = mdata.get('low_52w', 0.0)
        high_52 = mdata.get('high_52w', 0.0)
        sma_200 = mdata.get('sma_200', 0.0)
        
        rp = (curr_p - low_52) / (high_52 - low_52) * 100.0 if (high_52 - low_52) > 0 else 50.0
        dev = (curr_p - sma_200) / sma_200 * 100.0 if sma_200 > 0 else 0.0
        
        cname = tinfo.get('company_name', t)
        target_p = tinfo.get('target_price', 0.0)
        target_disc = tinfo.get('target_discount', 0.0)
        pass_cnt = tinfo.get('pass_count', 0)
        fpe = tinfo.get('forward_pe', 0.0)
        
        if t == 'IBIT' and btc_price:
            price_cell = f"<strong style='color: #ffffff; font-size: 14px;'>${curr_p:.2f}</strong><br><span style='font-size: 10.5px; color: #a1a1aa;'>(BTC ${btc_price:,.0f})</span>"
        else:
            price_cell = f"<strong style='color: #ffffff; font-size: 14px;'>${curr_p:.2f}</strong>"
            
        earnings_date_str = tinfo.get('earnings_date_str')
        dte_earnings = tinfo.get('dte_earnings')
        if is_etf_symbol(t):
            earnings_cell = "<span style='color: #a1a1aa;'>⚪ ETF 免检</span>"
        elif earnings_date_str:
            if dte_earnings is not None and 0 <= dte_earnings <= 14:
                earnings_cell = f"<span style='color: #fbbf24; font-weight: 600;'>📅 {earnings_date_str}</span><br><span style='font-size: 10.5px; color: #fbbf24;'>(距今 {dte_earnings}D ⚠️临近)</span>"
            elif dte_earnings is not None and dte_earnings < 0:
                earnings_cell = f"<span style='color: #a1a1aa;'>📅 {earnings_date_str}</span><br><span style='font-size: 10.5px; color: #a1a1aa;'>(已公布)</span>"
            elif dte_earnings is not None:
                earnings_cell = f"<span style='color: #f4f4f5;'>📅 {earnings_date_str}</span><br><span style='font-size: 10.5px; color: #a1a1aa;'>(距今 {dte_earnings}D)</span>"
            else:
                earnings_cell = f"<span style='color: #f4f4f5;'>📅 {earnings_date_str}</span>"
        else:
            earnings_cell = "<span style='color: #a1a1aa;'>⚪ N/A 暂无</span>"
            
        avail_cnt = tinfo.get('available_count', 5)
        fpe_str = f"Fwd P/E: {fpe:.1f}x" if fpe and fpe > 0 else "Fwd P/E: N/A"
        if is_etf_symbol(t):
            health_color = "#34d399"
            health_cell = f"<span style='color: {health_color}; font-weight: 600;'>🟢 ETF 免检</span><br><span style='font-size: 10.5px; color: #a1a1aa;'>基金资产</span>"
        elif avail_cnt == 0:
            health_color = "#a1a1aa"
            health_cell = f"<span style='color: {health_color}; font-weight: 600;'>⚪ N/A 缺失</span><br><span style='font-size: 10.5px; color: #a1a1aa;'>暂无财报</span>"
        else:
            pass_ratio = pass_cnt / avail_cnt if avail_cnt > 0 else 0
            if pass_ratio >= 0.8:
                health_color = "#34d399"
                health_lbl = "优异"
                icon = "🟢"
            elif pass_ratio >= 0.4:
                health_color = "#fbbf24"
                health_lbl = "合理"
                icon = "🟡"
            else:
                health_color = "#f87171"
                health_lbl = "较弱"
                icon = "🔴"
            health_cell = f"<span style='color: {health_color}; font-weight: 600;'>{icon} {pass_cnt}/{avail_cnt} {health_lbl}</span><br><span style='font-size: 10.5px; color: #a1a1aa;'>{fpe_str}</span>"
        
        rp_color = "#34d399" if rp <= 20.0 else ("#f87171" if rp >= 60.0 else "#e4e4e7")
        rp_lbl = "底端超跌" if rp <= 20.0 else ("中性阻力小" if rp <= 60.0 else "偏高区间")
        rp_cell = f"<span style='color: #ffffff;'>${low_52:.2f} - ${high_52:.2f}</span><br><span style='color: {rp_color}; font-size: 11px; font-weight: 600;'>RP: {rp:.1f}% ({rp_lbl})</span>"
        
        dev_color = "#34d399" if dev <= 0.0 else "#f87171"
        dev_lbl = "跌破均线支撑" if dev <= 0.0 else "均线上方"
        dev_cell = f"<span style='color: #ffffff;'>${sma_200:.2f}</span><br><span style='color: {dev_color}; font-size: 11px; font-weight: 600;'>偏离: {dev:+.1f}% ({dev_lbl})</span>"
        
        if target_p and target_p > 0:
            disc_color = "#34d399" if target_disc >= 15.0 else ("#fbbf24" if target_disc >= 0.0 else "#f87171")
            disc_cell = f"<span style='color: #ffffff;'>${target_p:.2f}</span><br><span style='color: {disc_color}; font-size: 11px; font-weight: 600;'>{'折价' if target_disc>=0 else '溢价'} {abs(target_disc):.1f}%</span>"
        else:
            disc_cell = "<span style='color: #a1a1aa;'>N/A</span>"
            
        t_opts = [o for o in all_options if o['ticker'] == t]
        bal_opts = [o for o in t_opts if o.get('risk_profile') == '平衡']
        if bal_opts:
            best_opt = max(bal_opts, key=lambda x: x['total_score'])
        else:
            best_opt = max(t_opts, key=lambda x: x['total_score']) if t_opts else None
        if best_opt:
            b_strike = best_opt['strike']
            b_score = best_opt['total_score']
            cushion = (b_strike - curr_p) / curr_p * 100.0 if curr_p > 0 else 0.0
            cush_color = "#34d399" if cushion <= -5.0 else "#fbbf24"
            
            if t == 'IBIT' and btc_price:
                b_strike_btc = b_strike * (btc_price / curr_p) if curr_p > 0 else 0
                strike_cell = f"<strong style='color: #ffffff; font-size: 14px;'>${b_strike:.2f}</strong> <span style='font-size: 10px; color: #a1a1aa;'>(BTC ${b_strike_btc:,.0f})</span><br><span style='color: {cush_color}; font-size: 11px; font-weight: 600;'>接股缓冲: {cushion:+.1f}%</span>"
            else:
                strike_cell = f"<strong style='color: #ffffff; font-size: 14px;'>${b_strike:.2f}</strong><br><span style='color: {cush_color}; font-size: 11px; font-weight: 600;'>接股缓冲: {cushion:+.1f}%</span>"
            score_s = "color: #4ade80; font-weight: bold;" if b_score >= 80 else "color: #e4e4e7; font-weight: bold;"
            s_p_val = best_opt.get('s_price', 0.0)
            s_s_val = best_opt.get('s_safety', 0.0)
            s_a_val = best_opt.get('s_option_alpha', 0.0)
            pen_val = best_opt.get('trend_penalty', 0.0)
            pen_str = f"<span style='color: #ef4444; font-size: 10px;'> -{pen_val:.0f}</span>" if pen_val > 0 else ""
            
            ev_d_val = best_opt.get('ev_dollar', 0.0)
            b_ivp = best_opt.get('ivp', 50.0)
            is_high_qual_best = best_opt.get('is_high_qual', is_high_qual_t)
            if ev_d_val > 10 and (b_ivp is None or b_ivp >= 35.0):
                neg_ev_tag = f"<div style='margin-top: 3px;'><span style='background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: 600;' title='期权处于超额波动率溢价区 (EV +${ev_d_val:.0f}, IVP {b_ivp:.0f}%)，享有丰厚权利金'>💰 溢价收租</span></div>"
            elif ev_d_val >= -150 or (ev_d_val > 10 and b_ivp < 35.0):
                neg_ev_tag = f"<div style='margin-top: 3px;'><span style='background: rgba(14, 165, 233, 0.15); color: #38bdf8; border: 1px solid rgba(14, 165, 233, 0.4); padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: 600;' title='期权处于公允波动率稳态区 (EV ${ev_d_val:+.0f})，平稳收获时间价值'>🟢 稳健收租</span></div>"
            else:
                # Deep negative EV (< -150)
                if is_high_qual_best:
                    neg_ev_tag = f"<div style='margin-top: 3px;'><span style='background: rgba(139, 92, 246, 0.15); color: #c084fc; border: 1px solid rgba(139, 92, 246, 0.4); padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: 600;' title='期权费处于低波压缩区 (EV ${ev_d_val:+.0f})，标的基本面极佳，行权价处于估值击球区，适合折扣接股'>💎 折扣建仓</span></div>"
                else:
                    neg_ev_tag = f"<div style='margin-top: 3px;'><span style='background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: 600;' title='期权费被过度压缩 (EV ${ev_d_val:+.0f})，收取的权利金不足以覆盖潜在尾部风险'>⚠️ 收益偏薄</span></div>"

            score_cell = (
                f"<div style='text-align: center;'>"
                f"<strong style='{score_s} font-size: 15px;'>{b_score:.1f}</strong>"
                f"<div style='font-size: 10.5px; display: flex; gap: 2px; align-items: center; justify-content: center; margin-top: 2px; font-family: monospace;' "
                f"title='三支柱得分: 估值底 (50%) {s_p_val:.0f} / 接股安全 (30%) {s_s_val:.0f} / 期权Alpha (20%) {s_a_val:.0f}'>"
                f"<span style='color: #60a5fa;' title='Pillar 1: 估值底 (50%)'>估{s_p_val:.0f}</span>"
                f"<span style='color: #52525b;'>/</span>"
                f"<span style='color: #34d399;' title='Pillar 2: 接股安全 (30%)'>安{s_s_val:.0f}</span>"
                f"<span style='color: #52525b;'>/</span>"
                f"<span style='color: #c084fc;' title='Pillar 3: 期权Alpha (20%)'>α{s_a_val:.0f}</span>"
                f"{pen_str}"
                f"</div>"
                f"{neg_ev_tag}"
                f"</div>"
            )
            
            # IVP Single Number Cell for Master Row
            ivp_val = best_opt.get('ivp', 50.0)
            iv_val = best_opt.get('iv', 0.0)
            ivr_val = best_opt.get('ivr')
            has_t_iv = best_opt.get('has_true_iv', False)
            
            if ivp_val >= 75:
                ivp_color = "#c084fc"  # High IVP (purple)
            elif ivp_val <= 25:
                ivp_color = "#f87171"  # Low IVP (red)
            else:
                ivp_color = "#38bdf8"  # Normal IVP (cyan)
                
            ivr_title_str = f", IVR: {ivr_val:.0f}%" if ivr_val is not None else ""
            t_tag = "真 252d IVP" if has_t_iv else "IVP"
            
            iv_cell_master = (
                f"<div style='text-align: center;'>"
                f"<strong style='color: {ivp_color}; font-size: 14px;' "
                f"title='{t_tag}: {ivp_val:.0f}% (当前期权 IV: {iv_val:.1f}%{ivr_title_str})'>{ivp_val:.0f}%</strong>"
                f"</div>"
            )
        else:
            strike_cell = "<span style='color: #a1a1aa;'>暂无推荐</span>"
            score_cell = "<span style='color: #a1a1aa;'>N/A</span>"
            iv_cell_master = "<div style='text-align: center;'><span style='color: #a1a1aa;'>--</span></div>"
            
        badges = []
        if t in current_position_tickers:
            badges.append("<span style='padding: 2px 6px; border-radius: 4px; background-color: rgba(96, 165, 250, 0.15); color: #60a5fa; font-size: 10.5px; font-weight: 600; margin-left: 6px; border: 1px solid rgba(96, 165, 250, 0.3);'>持仓</span>")
        elif t in PRESELECTED_TICKERS:
            badges.append("<span style='padding: 2px 6px; border-radius: 4px; background-color: rgba(168, 85, 247, 0.15); color: #c084fc; font-size: 10.5px; font-weight: 600; margin-left: 6px; border: 1px solid rgba(168, 85, 247, 0.3);'>核心</span>")
        else:
            badges.append("<span style='padding: 2px 6px; border-radius: 4px; background-color: rgba(52, 211, 153, 0.15); color: #34d399; font-size: 10.5px; font-weight: 600; margin-left: 6px; border: 1px solid rgba(52, 211, 153, 0.3);'>推荐</span>")
            
        is_knife = mdata.get('is_falling_knife', False)
        if is_knife:
            badges.append("<span style='padding: 2px 6px; border-radius: 4px; background-color: rgba(248, 113, 113, 0.15); color: #f87171; font-size: 10.5px; font-weight: 600; margin-left: 6px; border: 1px solid rgba(248, 113, 113, 0.3);'>🚨 飞刀预警</span>")
            
        # Check InvestSkill report
        clean_t_upper = t.upper().strip()
        investskill_info = investskill_reports.get(clean_t_upper) or investskill_reports.get(clean_t_upper.replace('.', '-')) or investskill_reports.get(clean_t_upper.replace('-', '.'))
        if investskill_info:
            rep_date_val = investskill_info['date']
            is_stale_val = investskill_info.get('is_stale', False)
            age_val = investskill_info.get('age_days', 0)
            if is_stale_val:
                badges.append(f"<span style='padding: 2px 6px; border-radius: 4px; background-color: rgba(239, 68, 68, 0.15); color: #f87171; font-size: 10.5px; font-weight: 600; margin-left: 6px; border: 1px solid rgba(239, 68, 68, 0.3);' title='InvestSkill 研报已逾期 ({age_val}天前)'>📑 研报 {rep_date_val} (⚠️已过期 {age_val}天)</span>")
            else:
                badges.append(f"<span style='padding: 2px 6px; border-radius: 4px; background-color: rgba(16, 185, 129, 0.15); color: #34d399; font-size: 10.5px; font-weight: 600; margin-left: 6px; border: 1px solid rgba(16, 185, 129, 0.3);' title='已生成 InvestSkill 机构研报 ({rep_date_val})'>📑 研报 {rep_date_val}</span>")

        # Check Insider Sentiment
        insider_data_master = insider_sentiment_map.get(t, {})
        if insider_data_master and not is_etf_symbol(t):
            insider_badge_html = insider_data_master.get("badge_html", "")
            if insider_badge_html and insider_data_master.get("sentiment") in ["net_buying", "heavy_selling"]:
                badges.append(f"<span style='margin-left: 6px;'>{insider_badge_html}</span>")

        badge_str = "".join(badges)
        
        row_slug = t.replace('.', '-')
        row_id = f"details-{row_slug}"
        master_id = f"master-{row_slug}"
        
        intro_t = TICKER_INTROS.get(t, TICKER_INTROS.get(t.replace('.', '-'), ''))
        if not intro_t:
            sec_t = SECTOR_MAP.get(t, SECTOR_MAP.get(t.replace('.', '-'), 'General'))
            sec_intros = {
                'Semiconductors': '全球半导体与芯片产业链核心优质龙头。',
                'SaaS & Cyber': '企业云服务 SaaS 与网络安全领军标的。',
                'Healthcare & MedTech': '全球生物医药、创新药与医疗技术核心标的。',
                'Financials & Crypto': '顶级银行、资管、互金与金融服务巨头。',
                'Consumer & Staples': '全球消费品、零售与高防守型必需消费品龙头。',
                'Industrials & Aerospace': '工程机械、航空航天与国防军工核心龙头。',
                'Energy & Commodities': '原油、天然气、工业金属与大宗商品核心标的。',
                'ETF': '追踪大盘或特定行业指数的宽基/行业主题 ETF。',
                'Tech': '全球消费电子、移动生态与前沿科技创新巨头。',
                'China ADR': '中国海外上市互联网与消费精选优质龙头。'
            }
            intro_t = f"{cname}，{sec_intros.get(sec_t, '全市场精选优质标的。')}"
            
        if t in current_position_tickers:
            reason_str = "账户当前期权持仓标的，强制纳入动态扫描与跟踪。"
        elif t in PRESELECTED_TICKERS:
            reason_str = "预设核心蓝筹自选池，长期重点关注与车轮布局。"
        elif mdata.get('is_falling_knife', False):
            reason_str = "近期股价急跌触发监控，短期跌幅较大，潜在修复空间较厚。"
        elif is_long_bull(t):
            reason_str = f"稳步长牛蓝筹，较 200日线偏离 {dev:+.1f}%，回踩低位良机。"
        else:
            reason_str = f"均值回归标的，52周相对位置 RP 仅 {rp:.0f}%，处于历史底部区间。"
            
        tv_url = get_tradingview_url(t)
        t_link = f"<a href='{tv_url}' target='_blank' onclick='event.stopPropagation();' style='color: #ffffff; text-decoration: none; border-bottom: 1px dashed #60a5fa;' title='打开 {t} TradingView 图表'><strong style='color: #ffffff; font-size: 14.5px;'>{t}</strong> <span style='font-size: 11.5px; color: #60a5fa;'>📈</span></a>"
        safe_intro_t = html.escape(intro_t)
        name_cell = f"{t_link}{badge_str} <span style='color: #a1a1aa; font-size: 11.5px; margin-left: 4px;'>({cname})</span><br><span style='font-size: 11.5px; color: #60a5fa; font-weight: 500;'>💡 {safe_intro_t}</span><br><span style='font-size: 11px; color: #34d399;'>🎯 准入理由：{reason_str}</span>"
        
        # Construct InvestSkill Signal Cell for Master Row
        if investskill_info:
            inv_score = investskill_info.get('score')
            inv_verdict = investskill_info.get('verdict', '')
            inv_action = investskill_info.get('action', '')
            inv_is_stale = investskill_info.get('is_stale', False)
            inv_age = investskill_info.get('age_days', 0)
            rep_date_str = investskill_info.get('date', '')
            
            if inv_is_stale:
                sig_tag = f"<span style='background: rgba(239, 68, 68, 0.15); color: #f87171; font-weight: 700; font-size: 11px; padding: 2px 7px; border-radius: 5px; border: 1px solid rgba(239, 68, 68, 0.35); display: inline-flex; align-items: center; gap: 3px;'>⚠️ 已过期 ({inv_age}天)</span>"
                score_sub = f"<span style='color: #f87171; font-size: 10px; font-family: monospace; margin-top: 2px; display: inline-block;' title='研报日期 {rep_date_str}，已过期超过 7 天'>{inv_score:.1f}/10 • 待更新</span>" if inv_score is not None else "<span style='color: #f87171; font-size: 10px;'>待更新</span>"
                investskill_cell = f"<div style='text-align: center;'>{sig_tag}<br>{score_sub}</div>"
            else:
                # Format clean verdict tag for fresh reports
                u_verdict = inv_verdict.upper()
                u_action = inv_action.upper()
                if (inv_score is not None and inv_score >= 8.0) or 'STRONG' in u_verdict or '强烈' in inv_verdict or 'STRONG' in u_action or '强烈' in inv_action:
                    sig_tag = "<span style='background: rgba(16, 185, 129, 0.2); color: #34d399; font-weight: 700; font-size: 11px; padding: 2px 7px; border-radius: 5px; border: 1px solid rgba(16, 185, 129, 0.4); display: inline-flex; align-items: center; gap: 3px;'>🚀 Strong Buy</span>"
                elif (inv_score is not None and inv_score >= 7.0) or 'BULLISH' in u_verdict or 'BUY' in u_verdict or '看多' in inv_verdict or '买入' in inv_verdict or 'BUY' in u_action or '买入' in inv_action:
                    sig_tag = "<span style='background: rgba(59, 130, 246, 0.15); color: #60a5fa; font-weight: 700; font-size: 11px; padding: 2px 7px; border-radius: 5px; border: 1px solid rgba(96, 165, 250, 0.35); display: inline-flex; align-items: center; gap: 3px;'>🟢 Bullish</span>"
                elif (inv_score is not None and inv_score >= 5.5) or 'HOLD' in u_verdict or 'NEUTRAL' in u_verdict or '中立' in inv_verdict or '观望' in inv_verdict:
                    sig_tag = "<span style='background: rgba(245, 158, 11, 0.15); color: #fbbf24; font-weight: 600; font-size: 11px; padding: 2px 7px; border-radius: 5px; border: 1px solid rgba(245, 158, 11, 0.35); display: inline-flex; align-items: center; gap: 3px;'>🟡 Neutral</span>"
                elif (inv_score is not None and inv_score < 5.5) or any(w in u_verdict for w in ['BEARISH', 'SELL', '看空', '劣质', '规避', '清仓']) or any(w in u_action for w in ['SELL', '规避', '清仓']):
                    sig_tag = "<span style='background: rgba(239, 68, 68, 0.15); color: #f87171; font-weight: 700; font-size: 11px; padding: 2px 7px; border-radius: 5px; border: 1px solid rgba(239, 68, 68, 0.35); display: inline-flex; align-items: center; gap: 3px;'>🔴 Bearish</span>"
                else:
                    sig_tag = ""  # Leave empty if unknown or undefined without assuming default fallback
                    
                score_text = f"{inv_score:.1f}/10" if inv_score is not None else ""
                if sig_tag and score_text:
                    investskill_cell = f"<div style='text-align: center;'>{sig_tag}<br><span style='color: #a1a1aa; font-size: 10.5px; font-family: monospace; margin-top: 2px; display: inline-block;'>{score_text}</span></div>"
                elif sig_tag:
                    investskill_cell = f"<div style='text-align: center;'>{sig_tag}</div>"
                elif score_text:
                    investskill_cell = f"<div style='text-align: center;'><span style='color: #a1a1aa; font-size: 10.5px; font-family: monospace;'>{score_text}</span></div>"
                else:
                    investskill_cell = "<div style='text-align: center;'><span style='color: #71717a; font-size: 11px;'>--</span></div>"
        elif is_etf_symbol(t):
            investskill_cell = "<div style='text-align: center;'><span style='background: rgba(168, 85, 247, 0.12); color: #c084fc; font-size: 10.5px; padding: 2px 6px; border-radius: 4px; border: 1px solid rgba(168, 85, 247, 0.3);'>宽基/ETF</span><br><span style='color: #a1a1aa; font-size: 10px;'>指数底仓</span></div>"
        else:
            investskill_cell = "<div style='text-align: center;'><span style='background: rgba(255, 255, 255, 0.05); color: #71717a; font-size: 10.5px; padding: 2px 6px; border-radius: 4px; border: 1px dashed #3f3f46;'>待生成</span></div>"

        search_terms = f"{t.upper()} {to_yf_symbol(t)} {to_display_symbol(t)} {cname} {intro_t} {'持仓' if t in current_position_tickers else ''}"
        safe_search_terms = html.escape(search_terms, quote=True)

        table_grouped += f"""
          <tr id="{master_id}" data-ticker="{t.upper()}" data-search="{safe_search_terms}" onclick="toggleDetails('{row_id}', '{master_id}')" style="background-color: {bg_c}; border-bottom: 1px solid #27272a; cursor: pointer; transition: background-color 0.15s;">
            <td style="padding: 10px 14px; text-align: center; color: #a1a1aa; font-weight: 500;">
              <span style="font-family: monospace; font-size: 12.5px;">{idx+1}</span>
              <br><span class="collapse-toggle-btn" style="font-size: 10.5px; color: #60a5fa; cursor: pointer; font-weight: 600;">▼ 展开</span>
            </td>
            <td style="padding: 10px 14px;">{name_cell}</td>
            <td style="padding: 10px 14px;">{price_cell}</td>
            <td style="padding: 10px 14px;">{earnings_cell}</td>
            <td style="padding: 10px 14px;">{health_cell}</td>
            <td style="padding: 10px 14px;">{rp_cell}</td>
            <td style="padding: 10px 14px;">{dev_cell}</td>
            <td style="padding: 10px 14px;">{strike_cell}</td>
            <td style="padding: 10px 14px; text-align: center;">{iv_cell_master}</td>
            <td style="padding: 10px 14px; text-align: center;">{investskill_cell}</td>
            <td style="padding: 10px 14px; text-align: center;">{score_cell}</td>
          </tr>"""
          
        deep_dive_content = ticker_deep_dive_map.get(t, "")
        
        profile_order = {"保守": 0, "平衡": 1, "激进": 2}
        t_opts.sort(key=lambda x: profile_order.get(x['risk_profile'], 99))
        
        if not t_opts:
            opts_table_html = """
            <div style="padding: 16px; border: 1px dashed #ef4444; border-radius: 8px; text-align: center; color: #ef4444; background-color: rgba(239, 68, 68, 0.05); margin-top: 4px; font-size: 13px; font-weight: 500; font-family: -apple-system, sans-serif;">
              ⚠️ 暂无合规推荐合约。当前标的在扫描到期日与 Delta 区间内无符合流动性或安全垫的期权合约。
            </div>
            """
        else:
            opts_table_html = """
            <div style="max-height: 400px; overflow-y: auto; border: 1px solid #27272a; border-radius: 8px; background-color: #000000; margin-top: 4px;">
              <table style="border-collapse: collapse; width: 100%; text-align: left; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 12.5px; line-height: 1.5; color: #f4f4f5;">
                <thead style="position: sticky; top: 0; background-color: #18181b; color: #ffffff; z-index: 10; box-shadow: 0 2px 4px rgba(0,0,0,0.2);">
                  <tr>
                    <th style="padding: 8px 12px; font-weight: 600; text-align: center; width: 40px;">排名</th>
                    <th style="padding: 8px 12px; font-weight: 600; width: 60px;">风险类型</th>
                    <th style="padding: 8px 12px; font-weight: 600;">到期日</th>
                    <th style="padding: 8px 12px; font-weight: 600;">行权价</th>
                    <th style="padding: 8px 12px; font-weight: 600;">目标 Delta</th>
                    <th style="padding: 8px 12px; font-weight: 600;">权利金</th>
                    <th style="padding: 8px 12px; font-weight: 600;">年化收益率</th>
                    <th style="padding: 8px 12px; font-weight: 600;">隐含波动率</th>
                    <th style="padding: 8px 12px; font-weight: 600;">综合得分</th>
                    <th style="padding: 8px 12px; font-weight: 600; min-width: 250px;">推荐理由与风险提示</th>
                  </tr>
                </thead>
                <tbody>"""
            
            for o_idx, opt in enumerate(t_opts):
                o_bg = "#09090b" if o_idx % 2 == 0 else "#18181b"
                score_s2 = "color: #4ade80; font-weight: bold;" if opt['total_score'] >= 80 else "color: #e4e4e7;"
                ivp_text_style2 = "color: #c084fc; font-weight: 600;" if opt.get('has_true_iv') else "color: #a1a1aa;"
                if opt.get('has_true_iv') and opt.get('ivr') is not None:
                    iv_cell2 = f"<span style='color: #f4f4f5;'>{opt['iv']:.1f}%</span><br><span style='{ivp_text_style2} font-size: 10px;' title='True 252d IVP: {opt['ivp']:.0f}%, True 252d IVR: {opt['ivr']:.0f}%'>真IVP:{opt['ivp']:.0f}% <span style=\"color:#38bdf8;\">IVR:{opt['ivr']:.0f}%</span></span>"
                else:
                    iv_cell2 = f"<span style='color: #f4f4f5;'>{opt['iv']:.1f}%</span><br><span style='{ivp_text_style2} font-size: 10px;'>IVP: {opt['ivp']:.0f}%</span>"
                s_p_c = opt.get('s_price', 0.0)
                s_s_c = opt.get('s_safety', 0.0)
                s_a_c = opt.get('s_option_alpha', 0.0)
                penalty_str2 = f" <span style='color: #ef4444;'>-{opt['trend_penalty']:.0f}</span>" if opt.get('trend_penalty', 0.0) > 0 else ""
                ev_c_val = opt.get('ev_dollar', 0.0)
                o_ivp = opt.get('ivp', 50.0)
                is_high_qual_opt = opt.get('is_high_qual', is_high_qual_t)
                if ev_c_val > 10 and (o_ivp is None or o_ivp >= 35.0):
                    neg_ev_tag2 = f"<br><span style='background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); padding: 0.5px 4px; border-radius: 3px; font-size: 9.5px; font-weight: 600;' title='期权处于超额波动率溢价区 (EV +${ev_c_val:.0f}, IVP {o_ivp:.0f}%)，享有丰厚权利金'>💰 溢价收租</span>"
                elif ev_c_val >= -150 or (ev_c_val > 10 and o_ivp < 35.0):
                    neg_ev_tag2 = f"<br><span style='background: rgba(14, 165, 233, 0.15); color: #38bdf8; border: 1px solid rgba(14, 165, 233, 0.4); padding: 0.5px 4px; border-radius: 3px; font-size: 9.5px; font-weight: 600;' title='期权处于公允波动率稳态区 (EV ${ev_c_val:+.0f})，平稳收获时间价值'>🟢 稳健收租</span>"
                else:
                    if is_high_qual_opt:
                        neg_ev_tag2 = f"<br><span style='background: rgba(139, 92, 246, 0.15); color: #c084fc; border: 1px solid rgba(139, 92, 246, 0.4); padding: 0.5px 4px; border-radius: 3px; font-size: 9.5px; font-weight: 600;' title='期权费处于低波压缩区 (EV ${ev_c_val:+.0f})，标的基本面极佳，行权价处于估值击球区，适合折扣接股'>💎 折扣建仓</span>"
                    else:
                        neg_ev_tag2 = f"<br><span style='background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); padding: 0.5px 4px; border-radius: 3px; font-size: 9.5px; font-weight: 600;' title='期权费被过度压缩 (EV ${ev_c_val:+.0f})，收取的权利金不足以覆盖潜在尾部风险'>⚠️ 收益偏薄</span>"

                score_cell2 = (
                    f"<strong style='{score_s2} font-size: 13.5px;'>{opt['total_score']:.1f}</strong><br>"
                    f"<span style='font-size: 10px; color: #a1a1aa; font-family: monospace;' "
                    f"title='三支柱明细: 估值底 {s_p_c:.0f} / 接股安全 {s_s_c:.0f} / 期权Alpha {s_a_c:.0f}'>"
                    f"<span style='color: #60a5fa;' title='Pillar 1: 估值底 (50%)'>估{s_p_c:.0f}</span>/"
                    f"<span style='color: #34d399;' title='Pillar 2: 接股安全 (30%)'>安{s_s_c:.0f}</span>/"
                    f"<span style='color: #c084fc;' title='Pillar 3: 期权Alpha (20%)'>α{s_a_c:.0f}</span>"
                    f"{penalty_str2}"
                    f"</span>"
                    f"{neg_ev_tag2}"
                )
                
                reason2 = get_recommendation_reason(opt, mdata, wash_sale_history_map, insider_sentiment_map, fund_info)
                pct_drop2 = (opt['strike'] - opt['current_price']) / opt['current_price'] * 100.0 if opt['current_price']>0 else 0.0
                prof_tag2 = profile_tags.get(opt['risk_profile'], opt['risk_profile'])
                
                if opt['ticker'] == 'IBIT' and btc_price:
                    strike_btc2 = opt['strike'] * (btc_price / opt['current_price']) if opt['current_price']>0 else 0
                    strike_cell2 = f"<span style='color: #ffffff; font-weight: 600;'>${opt['strike']:.2f}<br><span style='font-size: 10px; color: #a1a1aa;'>(BTC ${strike_btc2:,.0f})</span></span><br><span style='color: #a1a1aa; font-size: 10px;'>({pct_drop2:+.1f}%)</span>"
                else:
                    strike_cell2 = f"<span style='color: #ffffff; font-weight: 600;'>${opt['strike']:.2f}</span><br><span style='color: #a1a1aa; font-size: 10px;'>({pct_drop2:+.1f}%)</span>"
                    
                if opt.get('ev_dollar') is not None and opt.get('pop') is not None:
                    ev_col = "#34d399" if opt['ev_dollar'] > 0 else "#f87171"
                    yield_cell2 = f"<span style='color: #f4f4f5; font-weight: 600;'>{opt['annualized_yield']:.1f}%</span><br><span style='color: {ev_col}; font-size: 10.5px; font-weight: 600;'>POP {opt['pop']:.0f}% | EV {opt['ev_dollar']:+.0f}$</span>"
                else:
                    yield_cell2 = f"<span style='color: #f4f4f5;'>{opt['annualized_yield']:.1f}%</span>"
                    
                opts_table_html += f"""
                  <tr style="background-color: {o_bg}; border-bottom: 1px solid #27272a;">
                    <td style="padding: 8px 12px; text-align: center; color: #a1a1aa;">{o_idx+1}</td>
                    <td style="padding: 8px 12px;">{prof_tag2}</td>
                    <td style="padding: 8px 12px;"><span style='color: #f4f4f5;'>{opt['expiration']}<br><span style='font-size: 10px; color: #a1a1aa;'>({opt['dte']}D)</span></span></td>
                    <td style="padding: 8px 12px;">{strike_cell2}</td>
                    <td style="padding: 8px 12px;"><span style='color: #f4f4f5;'>{opt['delta']:.2f}</span></td>
                    <td style="padding: 8px 12px;"><span style='color: #f4f4f5;'>${opt['mark']:.2f}</span></td>
                    <td style="padding: 8px 12px;">{yield_cell2}</td>
                    <td style="padding: 8px 12px;">{iv_cell2}</td>
                    <td style="padding: 8px 12px;">{score_cell2}</td>
                    <td style="padding: 8px 12px; color: #a1a1aa; font-size: 12px;">{reason2}</td>
                  </tr>"""
            opts_table_html += "\n            </tbody>\n          </table>\n        </div>"

        # Build InvestSkill Pane HTML
        if investskill_info:
            rep_rel_path = investskill_info['rel_path']
            rep_date = investskill_info['date']
            rep_age = investskill_info.get('age_days', 0)
            is_stale = investskill_info.get('is_stale', False)
            rep_score_str = f"• 综合评分: {investskill_info['score']:.1f}/10" if investskill_info['score'] is not None else ""
            
            if is_stale:
                investskill_tab_btn_badge = f"<span style='background: rgba(239, 68, 68, 0.2); color: #f87171; font-size: 11px; padding: 1px 6px; border-radius: 4px; margin-left: 4px;'>{rep_date} (⚠️已过期 {rep_age}天)</span>"
                stale_banner = f"<div style='background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.3); color: #f87171; padding: 6px 12px; border-radius: 6px; font-size: 12px; margin-bottom: 10px;'>⚠️ <strong>研报已逾期 ({rep_age}天前)</strong>：该研报已超过 7 天保鲜期，建议使用 <code>research {t}</code> 快捷指令重新生成最新研报。</div>"
            else:
                investskill_tab_btn_badge = f"<span style='background: rgba(52, 211, 153, 0.2); color: #34d399; font-size: 11px; padding: 1px 6px; border-radius: 4px; margin-left: 4px;'>{rep_date}</span>"
                stale_banner = ""
                
            investskill_pane_html = f"""
            <div style="background: #09090b; border: 1px solid #27272a; border-radius: 10px; padding: 16px; margin-top: 4px;">
              {stale_banner}
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 10px;">
                <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                  <span style="font-size: 14px; font-weight: 700; color: #ffffff;">📑 {t} InvestSkill 机构级深度投资研报</span>
                  <span style="background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); font-size: 11px; padding: 2px 8px; border-radius: 4px; font-weight: 600;">日期: {rep_date} {rep_score_str}</span>
                  <span style="font-size: 12px; color: #a1a1aa;">(已集成 Chart.js 交互图表、DCF 内在价值、Piotroski 财务评分与 Bear Case 做空红队检验)</span>
                </div>
                <a href="{rep_rel_path}" target="_blank" style="background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%); color: #ffffff; text-decoration: none; padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 600; display: inline-flex; align-items: center; gap: 6px; box-shadow: 0 2px 8px rgba(37, 99, 235, 0.3);">
                  <span>↗️ 在新窗口全屏打开独立研报</span>
                </a>
              </div>
              <div style="width: 100%; height: 780px; border: 1px solid #27272a; border-radius: 8px; overflow: hidden; background: #ffffff; box-shadow: 0 4px 16px rgba(0,0,0,0.5);">
                <iframe src="{rep_rel_path}" style="width: 100%; height: 100%; border: none;" loading="lazy"></iframe>
              </div>
            </div>
            """
        elif is_etf_symbol(t):
            investskill_tab_btn_badge = "<span style='background: rgba(168, 85, 247, 0.15); color: #c084fc; font-size: 11px; padding: 1px 6px; border-radius: 4px; margin-left: 4px;'>宽基/ETF 免检</span>"
            investskill_pane_html = f"""
            <div style="padding: 32px 20px; border: 1px solid rgba(168, 85, 247, 0.3); border-radius: 10px; text-align: center; background: rgba(168, 85, 247, 0.04); margin-top: 4px;">
              <div style="font-size: 28px; margin-bottom: 8px;">🏛️</div>
              <div style="color: #ffffff; font-size: 15px; font-weight: 700; margin-bottom: 6px;">{t} 属于宽基/行业 ETF 指数底仓（免个股财务研报）</div>
              <p style="color: #a1a1aa; font-size: 13px; max-width: 620px; margin: 0 auto 16px; line-height: 1.6;">
                ETF 标的自带一篮子资产分散风险与内生再平衡机制，无单一公司财务造假破产或做空风险。期权建仓以大盘宏观估值、点位支撑及波动率收益率为核心依据。
              </p>
              <div style="display: flex; justify-content: center; gap: 12px; flex-wrap: wrap;">
                <a href="file://{os.path.join(INVESTSKILL_OUTPUT_DIR, 'index.html')}" target="_blank" style="background: rgba(255,255,255,0.06); border: 1px solid #3f3f46; color: #e4e4e7; text-decoration: none; padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 500;">
                  📂 查看 InvestSkill 研报索引库 ↗
                </a>
              </div>
            </div>
            """
        else:
            investskill_tab_btn_badge = "<span style='background: rgba(255, 255, 255, 0.08); color: #a1a1aa; font-size: 11px; padding: 1px 6px; border-radius: 4px; margin-left: 4px;'>待生成</span>"
            investskill_pane_html = f"""
            <div style="padding: 32px 20px; border: 1px dashed #3b82f6; border-radius: 10px; text-align: center; background: rgba(59, 130, 246, 0.03); margin-top: 4px;">
              <div style="font-size: 28px; margin-bottom: 8px;">📑</div>
              <div style="color: #ffffff; font-size: 15px; font-weight: 700; margin-bottom: 6px;">尚未生成 {t} 的 InvestSkill 深度机构研报</div>
              <p style="color: #a1a1aa; font-size: 13px; max-width: 620px; margin: 0 auto 16px; line-height: 1.6;">
                InvestSkill 提供了 25 个专业投资分析框架（包含 <code>stock-eval</code> 财务质量评分、<code>dcf-valuation</code> 内在价值折现、<code>bear-case</code> 做空红队压力测试与 <code>options-analysis</code> 期权微观结构）。
              </p>
              <div style="display: flex; justify-content: center; gap: 12px; flex-wrap: wrap;">
                <a href="file://{os.path.join(INVESTSKILL_OUTPUT_DIR, 'index.html')}" target="_blank" style="background: rgba(255,255,255,0.06); border: 1px solid #3f3f46; color: #e4e4e7; text-decoration: none; padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 500;">
                  📂 查看 InvestSkill 研报索引库 ↗
                </a>
              </div>
            </div>
            """
        
        table_grouped += f"""
          <tr id="{row_id}" style="display: none; background-color: #000000; border-bottom: 2px solid #3b82f6;">
            <td colspan="11" style="padding: 20px 24px; background: linear-gradient(180deg, #0b0b0f 0%, #000000 100%);">
              <div style="max-width: 1300px; margin: 0 auto;">
                
                <!-- Details Header Bar with Collapse Button -->
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px solid #27272a; flex-wrap: wrap; gap: 10px;">
                  <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                    <span style="font-size: 16px; font-weight: 700; color: #ffffff;">🎯 {t} 深度研判与期权决策工作台</span>
                    {badge_str}
                  </div>
                  <button onclick="toggleDetails('{row_id}', '{master_id}')" style="background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.35); color: #f87171; padding: 5px 14px; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.2s;" title="收起此标的展开详情">
                    ▲ 收起此标的 (Collapse)
                  </button>
                </div>

                <!-- Tab Navigation -->
                <div class="detail-tabs-container">
                  <div class="detail-tabs-header">
                    <button class="detail-tab-btn active" data-tab="options" onclick="switchDetailTab('{row_id}', 'options')">
                      <span>📊</span> 候选期权合约 (Option Contracts)
                    </button>
                    <button class="detail-tab-btn" data-tab="investskill" onclick="switchDetailTab('{row_id}', 'investskill')">
                      <span>📑</span> InvestSkill 深度研报 {investskill_tab_btn_badge}
                    </button>
                    <button class="detail-tab-btn" data-tab="valuation" onclick="switchDetailTab('{row_id}', 'valuation')">
                      <span>🔍</span> 极速基本面与接股估值
                    </button>
                  </div>

                  <!-- Pane 1: Options -->
                  <div class="detail-tab-pane active" data-pane="options">
                    {opts_table_html}
                  </div>

                  <!-- Pane 2: InvestSkill -->
                  <div class="detail-tab-pane" data-pane="investskill">
                    {investskill_pane_html}
                  </div>

                  <!-- Pane 3: Fast Valuation -->
                  <div class="detail-tab-pane" data-pane="valuation">
                    {deep_dive_content}
                  </div>
                </div>

              </div>
            </td>
          </tr>"""
          
    table_grouped += "\n        </tbody>\n      </table>\n    </div>\n"

    # 3. Generate Covered Call Table
    cc_html = ""
    if not all_cc_options:
        cc_html = '<div style="padding: 24px; background-color: #18181b; border: 1px solid #27272a; border-radius: 8px; text-align: center; color: #a1a1aa; font-family: -apple-system, sans-serif; font-size: 13px;">目前账户中无持股数量 &ge; 100 股的股票现货，无需建立 Covered Call 仓位。</div>'
    else:
        grouped_tickers = set([o['ticker'] for o in all_cc_options])
        for ticker_name in grouped_tickers:
            ticker_opts = [o for o in all_cc_options if o['ticker'] == ticker_name]
            ticker_opts.sort(key=lambda x: x['total_score'], reverse=True)
            
            pos_info = equity_info_map[ticker_name]
            avg_cost = pos_info['average_buy_price']
            qty = pos_info['quantity']
            curr_price = ticker_opts[0]['current_price']
            
            header_desc = f"持股数: <b>{qty:.0f}股</b> (持仓均价: ${avg_cost:.2f}, 当前股价: ${curr_price:.2f}, 盈亏: {((curr_price-avg_cost)/avg_cost*100):+.1f}%)"
            
            tv_url = get_tradingview_url(ticker_name)
            tv_link = f"<a href='{tv_url}' target='_blank' style='color: #ffffff; text-decoration: none;' title='查看 TradingView 图表'>{ticker_name} <span style='font-size: 12px; color: #60a5fa;'>📈</span></a>"
            cc_html += f"""<h4 style="color: #ffffff; margin-top: 24px; margin-bottom: 12px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 14px; font-weight: 600; border-left: 4px solid #f59e0b; padding-left: 10px;">📉 {tv_link} &nbsp;|&nbsp; <span style="font-size: 12px; font-weight: normal; color: #a1a1aa;">{header_desc}</span></h4>
<div style="max-height: 450px; overflow-y: auto; border: 1px solid #27272a; border-radius: 8px; margin-bottom: 24px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.2); background-color: #09090b;">
  <table style="border-collapse: collapse; width: 100%; text-align: left; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 13px; line-height: 1.5; color: #f4f4f5;">
    <thead style="position: sticky; top: 0; background-color: #18181b; color: #ffffff; z-index: 10; box-shadow: 0 2px 4px rgba(0,0,0,0.2);">
      <tr>
        <th style="padding: 10px 16px; font-weight: 600; text-transform: uppercase; font-size: 11px; letter-spacing: 0.05em; border-bottom: 2px solid #27272a; white-space: nowrap; width: 45px; text-align: center;">排名</th>
        <th style="padding: 10px 16px; font-weight: 600; text-transform: uppercase; font-size: 11px; letter-spacing: 0.05em; border-bottom: 2px solid #27272a; white-space: nowrap;">到期日</th>
        <th style="padding: 10px 16px; font-weight: 600; text-transform: uppercase; font-size: 11px; letter-spacing: 0.05em; border-bottom: 2px solid #27272a; white-space: nowrap;">行权价</th>
        <th style="padding: 10px 16px; font-weight: 600; text-transform: uppercase; font-size: 11px; letter-spacing: 0.05em; border-bottom: 2px solid #27272a; white-space: nowrap;">目标 Delta</th>
        <th style="padding: 10px 16px; font-weight: 600; text-transform: uppercase; font-size: 11px; letter-spacing: 0.05em; border-bottom: 2px solid #27272a; white-space: nowrap;">权利金</th>
        <th style="padding: 10px 16px; font-weight: 600; text-transform: uppercase; font-size: 11px; letter-spacing: 0.05em; border-bottom: 2px solid #27272a; white-space: nowrap;">年化收益率</th>
        <th style="padding: 10px 16px; font-weight: 600; text-transform: uppercase; font-size: 11px; letter-spacing: 0.05em; border-bottom: 2px solid #27272a; white-space: nowrap;">隐含波动率</th>
        <th style="padding: 10px 16px; font-weight: 600; text-transform: uppercase; font-size: 11px; letter-spacing: 0.05em; border-bottom: 2px solid #27272a; white-space: nowrap;">综合得分</th>
        <th style="padding: 10px 16px; font-weight: 600; text-transform: uppercase; font-size: 11px; border-bottom: 2px solid #27272a; min-width: 280px;">推荐理由与风险提示</th>
      </tr>
    </thead>
    <tbody>"""
            for idx, opt in enumerate(ticker_opts):
                bg_c = "#09090b" if idx % 2 == 0 else "#18181b"
                score_s = "color: #4ade80; font-weight: bold;" if opt['total_score'] >= 80 else "color: #e4e4e7;"
                ivp_text_style = "color: #c084fc; font-weight: 600;" if opt.get('has_true_iv') else "color: #a1a1aa;"
                if opt.get('has_true_iv') and opt.get('ivr') is not None:
                    iv_cell = f"<span style='color: #f4f4f5;'>{opt['iv']:.1f}%</span><br><span style='{ivp_text_style} font-size: 10px;' title='True 252d IVP: {opt['ivp']:.0f}%, True 252d IVR: {opt['ivr']:.0f}%'>真IVP:{opt['ivp']:.0f}% <span style=\"color:#38bdf8;\">IVR:{opt['ivr']:.0f}%</span></span>"
                else:
                    iv_cell = f"<span style='color: #f4f4f5;'>{opt['iv']:.1f}%</span><br><span style='{ivp_text_style} font-size: 10px;'>IVP: {opt['ivp']:.0f}%</span>"
                score_cell = f"<span style='{score_s}'>{opt['total_score']:.1f}</span><br><span style='color: #a1a1aa; font-size: 10px;'>({opt['s_price']:.0f}/{opt['s_safety']:.0f}/{opt['s_yield']:.0f}/{opt['s_iv']:.0f})</span>"
                
                warning_lbl = ""
                if opt['warning']:
                    warning_lbl = " <span style='color: #ef4444; font-weight: bold;'>[🚨极低流动性警告]</span>"
                    
                profit_pct = (opt['strike'] - avg_cost) / avg_cost * 100.0
                pct_diff = (opt['strike'] - curr_price) / curr_price * 100.0
                reason = f"行权价比持仓成本高 {profit_pct:+.1f}%（若被行权可获额外股价涨幅收益）。当前股价距行权价差 {pct_diff:.1f}%。{warning_lbl}"
                
                cc_html += f"""
      <tr style="background-color: {bg_c}; border-bottom: 1px solid #27272a; transition: background-color 0.15s;">
        <td style="padding: 8px 16px; vertical-align: middle; text-align: center; border-bottom: 1px solid #27272a;"><span style='color: #a1a1aa;'>{idx+1}</span></td>
        <td style="padding: 8px 16px; vertical-align: middle; border-bottom: 1px solid #27272a;"><span style='color: #f4f4f5;'>{opt['expiration']}<br><span style='font-size: 10px; color: #a1a1aa;'>({opt['dte']}D)</span></span></td>
        <td style="padding: 8px 16px; vertical-align: middle; border-bottom: 1px solid #27272a;"><span style='color: #ffffff; font-weight: 600;'>${opt['strike']:.2f}</span><br><span style='color: #a1a1aa; font-size: 10px;'>({pct_diff:+.1f}%)</span></td>
        <td style="padding: 8px 16px; vertical-align: middle; border-bottom: 1px solid #27272a;"><span style='color: #f4f4f5;'>{opt['delta']:.2f}</span></td>
        <td style="padding: 8px 16px; vertical-align: middle; border-bottom: 1px solid #27272a;"><span style='color: #f4f4f5;'>${opt['mark']:.2f}</span></td>
        <td style="padding: 8px 16px; vertical-align: middle; border-bottom: 1px solid #27272a;"><span style='color: #f4f4f5;'>{opt['annualized_yield']:.1f}%</span></td>
        <td style="padding: 8px 16px; vertical-align: middle; border-bottom: 1px solid #27272a;">{iv_cell}</td>
        <td style="padding: 8px 16px; vertical-align: middle; border-bottom: 1px solid #27272a;">{score_cell}</td>
        <td style="padding: 8px 16px; vertical-align: middle; border-bottom: 1px solid #27272a; white-space: normal; text-align: left; max-width: 380px; font-size: 12.5px; color: #a1a1aa; line-height: 1.4;">{reason}</td>
      </tr>"""
            cc_html += "\n    </tbody>\n  </table>\n</div>\n"

    # ==================== GENERATE TASK 1 TABLE & ACTION PLAN ====================
    table_task1 = ""
    action_plan_recs = []
    
    # Calculate portfolio delta exposure with live spot prices
    spot_prices_map = {sym: ticker_market_data.get(sym, {}).get('current_price', 100.0) for sym in active_tickers}
    portfolio_delta_summary = calculate_portfolio_delta_exposure(spot_prices_map)
    
    # Sort current_positions by DTE ascending
    if isinstance(current_positions, list) and len(current_positions) > 0 and isinstance(current_positions[0], dict):
        current_positions.sort(key=lambda x: x['dte'])
        
    for idx, pos in enumerate(current_positions):
        if not isinstance(pos, dict):
            continue
        ticker = pos['symbol']
        strike = pos['strike']
        expiration = pos['expiration']
        dte = pos['dte']
        delta = pos['delta']
        open_p = pos['open_price']
        curr_p = pos['current_price']
        qty = pos['quantity']
        
        mdata = ticker_market_data.get(ticker, {})
        curr_stock_price = mdata.get('current_price', strike)
        tinfo = ticker_info_map.get(ticker, {})
        
        safety_cushion = (curr_stock_price - strike) / curr_stock_price * 100.0 if curr_stock_price > 0 else 0.0
        
        pnl = (open_p - curr_p) * 100.0 * qty
        pnl_pct = (open_p - curr_p) / open_p * 100.0 if open_p > 0 else 0.0
        
        open_yield = (open_p / strike) * (365.0 / dte) * 100.0 if dte > 0 else 0.0
        remaining_yield = (curr_p / strike) * (365.0 / dte) * 100.0 if dte > 0 else 0.0
        
        # Net assignment basis and valuation
        net_basis = strike - open_p
        discount_to_curr = (net_basis - curr_stock_price) / curr_stock_price * 100.0 if curr_stock_price > 0 else 0.0
        forward_pe = tinfo.get('forward_pe', 0.0)
        strike_pe = forward_pe * (net_basis / curr_stock_price) if (forward_pe and curr_stock_price > 0) else 0.0
        pe_tag = f"Forward P/E {strike_pe:.1f}x" if strike_pe > 0 else ""
        
        # InvestSkill assignment suitability assessment
        clean_t = ticker.upper().strip()
        rep_info = investskill_reports.get(clean_t) or investskill_reports.get(clean_t.replace('.', '-')) or investskill_reports.get(clean_t.replace('-', '.'))
        
        if is_etf_symbol(ticker) or ticker in ['ASHR', 'IBIT', 'SPYM', 'QQQM', 'IWM', 'VTV', 'TLT', 'XLV', 'XLP', 'XLE']:
            assignment_safe = True
            badge_text = "🟢 宽基ETF·安心接股"
            tradeoff_status = "【可安心接股·绝不割肉】"
            tradeoff_color = "#34d399"
            tradeoff_desc = f"宽基/行业指数基金无个股暴雷或财务做空风险。实际净接股成本 ${net_basis:.2f} ({discount_to_curr:+.1f}% 较现价折让)，底层资产扎实，非常适合长线底仓接股或开启车轮 CC 收租。"
        elif rep_info:
            rep_score = rep_info.get('score')
            rep_verdict = rep_info.get('verdict', '')
            rep_summary = rep_info.get('summary', '')
            if (rep_score is not None and rep_score >= 7.0) or any(w in rep_verdict.upper() for w in ['STRONG BUY', 'BUY', 'BULLISH', '看多']):
                assignment_safe = True
                badge_text = f"🟢 优质·安心接股 ({rep_score:.1f}分)" if rep_score else "🟢 优质·安心接股"
                tradeoff_status = "【可安心接股·绝不割肉】"
                tradeoff_color = "#34d399"
                tradeoff_desc = f"InvestSkill 机构评级为【{rep_verdict or '看多'}】({rep_score or 8.5:.1f}/10分)。{rep_summary[:100]}... 实际净接股成本仅 ${net_basis:.2f} (较现价折让 {abs(discount_to_curr):.1f}%{'，' + pe_tag if pe_tag else ''})，安全边际充足，具备极高长线持股价值。相比于割肉平仓，低价接股长期持有的期望收益显著更优，坚决无需恐慌割肉！"
            elif (rep_score is not None and rep_score < 5.5) or any(w in rep_verdict.upper() for w in ['BEARISH', 'SELL', '看空', '劣质']):
                assignment_safe = False
                badge_text = f"🔴 质地恶化·严禁接股 ({rep_score:.1f}分)" if rep_score else "🔴 质地恶化·严禁接股"
                tradeoff_status = "【基本面破灭·割肉平仓更优】"
                tradeoff_color = "#ef4444"
                tradeoff_desc = f"🚨 InvestSkill 做空红队警示重大基本面恶化【{rep_verdict}】({rep_score or 4.0:.1f}/10分)。若被迫接股将承担本金持续缩水风险！相比于接股后承受阴跌，挂单买入平仓 (BTC) 割肉止损或大幅向下展期为更优解！"
            else:
                assignment_safe = True
                badge_text = f"🟡 周期波动·可接股 ({rep_score:.1f}分)" if rep_score else "🟡 周期波动·可接股"
                tradeoff_status = "【周期波动·可审慎接股】"
                tradeoff_color = "#fbbf24"
                tradeoff_desc = f"基本面处于行业周期或扩产调整期，实际净接股成本 ${net_basis:.2f}。若选择接股需控制总仓位，并在接股后立即以成本均价卖出 30-45 天虚值 Covered Call。"
        else:
            assignment_safe = True
            badge_text = "🟢 蓝筹资产·可接股"
            tradeoff_status = "【蓝筹资产·可接股】"
            tradeoff_color = "#34d399"
            tradeoff_desc = f"底层核心精选池标的，实际净接股成本 ${net_basis:.2f}。若被行权可从容接股并开启车轮策略第二步卖出 Covered Call 收租。"

        is_knife = mdata.get('is_falling_knife', False)
        is_fcf_neg = mdata.get('is_fcf_negative', False)
        is_deep_itm = (safety_cushion < -5.0) or (delta < -0.60)
        curr_hv = mdata.get('current_hv_30', 30.0)
        
        # Dynamic volatility tiering (linked to HV30): match closing and greedy hold APY thresholds
        if curr_hv < 20.0:
            min_inefficient_yield = 6.0    # Low volatility / ETF: remaining APY < 6% is deemed inefficient
            greedy_hold_yield = 10.0       # Low volatility / ETF: remaining APY >= 10% qualifies for greedy hold
            vol_tier_label = "低波防守 (HV30<20%)"
        elif curr_hv <= 35.0:
            min_inefficient_yield = 10.0   # Medium volatility: standard threshold < 10%
            greedy_hold_yield = 15.0       # Medium volatility: standard threshold >= 15%
            vol_tier_label = "中波稳健 (HV30 20-35%)"
        else:
            min_inefficient_yield = 15.0   # High volatility: requires higher risk compensation, APY < 15% closes to reallocate
            greedy_hold_yield = 22.0       # High volatility: remaining APY >= 22% qualifies for greedy hold
            vol_tier_label = "高波成长 (HV30>35%)"
        
        tv_url = get_tradingview_url(ticker)
        tv_link_inline = f"<a href='{tv_url}' target='_blank' style='color: var(--text-primary); text-decoration: none; border-bottom: 1px dashed #60a5fa;' title='查看 {ticker} TradingView 图表'>{ticker} <span style='font-size: 10.5px; color: #60a5fa;'>📈</span></a>"

        # 1. Inefficient yield BTC / Absolute profit take
        if remaining_yield < min_inefficient_yield or pnl_pct >= 80.0:
            decision = "止盈平仓 (BTC)"
            decision_class = "highlight-blue"
            decision_cell = f"<strong style='color: #60a5fa;'>止盈平仓 (BTC)</strong><br><span style='font-size: 10.5px; color: #a1a1aa;'>资金低效/止盈兑现</span>"
            reason_str = "浮盈达 80% 以上" if pnl_pct >= 80.0 else f"剩余年化已跌破{vol_tier_label}底线 ({remaining_yield:.1f}% < {min_inefficient_yield:.1f}%)"
            action_plan_recs.append(
                f"<li><strong>{tv_link_inline} {expiration} ${strike:.2f} Put 💰【资金低效·止盈平仓】</strong>：当前{reason_str}（浮盈 <strong class='highlight-green'>{pnl_pct:+.1f}%</strong>，[{vol_tier_label}]），继续占用保证金的报酬率极低。建议挂单买入平仓 (BTC) 以释放资金换仓。建议限价：<strong>${curr_p:.2f}</strong>。</li>"
            )
        # 2. Greedy hold
        elif pnl_pct >= 50.0 and remaining_yield >= greedy_hold_yield and safety_cushion >= 6.0:
            decision = "贪婪持有 (Hold)"
            decision_class = "highlight-green"
            decision_cell = f"<strong style='color: #34d399;'>贪婪持有 (Hold)</strong><br><span style='font-size: 10.5px; color: #34d399; font-weight: 600;'>{badge_text}</span>"
            action_plan_recs.append(
                f"<li><strong>{tv_link_inline} {expiration} ${strike:.2f} Put 🚀【高息尾部·贪婪持有】</strong>：浮盈达 <strong class='highlight-green'>{pnl_pct:+.1f}%</strong>，剩余年化回报率仍高达 <strong class='highlight-green'>{remaining_yield:.1f}%</strong>（超过该档门槛 {greedy_hold_yield:.1f}%，[{vol_tier_label}]）且安全垫深达 <strong>{safety_cushion:+.1f}%</strong>。系统判定为高息尾部收租特例，强烈建议继续持有吃满时间红利！<br><span style='color: #a1a1aa; font-size: 11.5px;'>💡 接股裁决：<strong style='color: {tradeoff_color};'>{tradeoff_status}</strong> {tradeoff_desc}</span></li>"
            )
        # 3. Dynamic take profit BTC
        elif pnl_pct >= 50.0 and (remaining_yield < greedy_hold_yield or safety_cushion < 6.0) and not is_deep_itm:
            decision = "动态止盈 (BTC)"
            decision_class = "highlight-blue"
            decision_cell = f"<strong style='color: #60a5fa;'>动态止盈 (BTC)</strong><br><span style='font-size: 10.5px; color: #a1a1aa;'>尾部报酬率偏低</span>"
            action_plan_recs.append(
                f"<li><strong>{tv_link_inline} {expiration} ${strike:.2f} Put 💰【动态止盈平仓】</strong>：当前浮盈达 <strong class='highlight-green'>{pnl_pct:+.1f}%</strong>，但剩余年化回报率（{remaining_yield:.1f}%）已低于风险补偿门槛（{greedy_hold_yield:.1f}%）。建议挂单买入平仓 (BTC) 锁定利润，建议平仓限价：<strong>${curr_p:.2f}</strong>。</li>"
            )
        # 4. Critical roll or assignment (DTE <= 15 and safety_cushion < 3.0%)
        elif dte <= 15 and safety_cushion < 3.0:
            if assignment_safe:
                decision = "择机展期或接股"
                decision_class = "highlight-orange"
                decision_cell = f"<strong style='color: #fbbf24;'>择机展期或接股</strong><br><span style='font-size: 10.5px; color: #34d399; font-weight: 600;'>{badge_text}</span>"
                roll_res = calculate_roll_candidate(ticker, strike, curr_p, dte)
                if roll_res.get("has_roll"):
                    roll_tip = f"{roll_res['summary_html']}<br><span style='color: #a1a1aa; font-size: 11px;'>（亦可直接准备全额现金低价接股并开启车轮 Covered Call）</span>"
                else:
                    roll_tip = "若希望进一步拉大安全垫并获取额外 Net Credit 净权利金，建议向下向后展期 (Roll Down & Out) 30~45 天；若选择现金接股，成本极低，接股后可立即卖出 Covered Call" if curr_hv >= 25.0 else "由于标的 IV 偏低，展期 Net Credit 空间有限，建议直接准备全额现金低价接股并开启车轮 CC"
                
                action_plan_recs.append(
                    f"<li><strong>{tv_link_inline} {expiration} ${strike:.2f} Put 🔄【临界到期·从容展期或接股】</strong>：距离到期仅剩 {dte} 天，现价距行权价仅剩 <strong class='highlight-red'>{safety_cushion:+.1f}%</strong> 安全垫。<br><strong style='color: {tradeoff_color};'>{tradeoff_status}</strong>：{tradeoff_desc}<br><span style='color: #f4f4f5; font-size: 12px;'>👉 <strong>操作指引</strong>：{roll_tip}。<strong>标的基本面扎实，坚决无需市价割肉平仓！</strong></span></li>"
                )
            else:
                decision = "割肉平仓 (BTC 避险)"
                decision_class = "highlight-red"
                decision_cell = f"<strong style='color: #ef4444;'>割肉平仓 (BTC 避险)</strong><br><span style='font-size: 10.5px; color: #ef4444; font-weight: 600;'>{badge_text}</span>"
                action_plan_recs.append(
                    f"<li><strong>{tv_link_inline} {expiration} ${strike:.2f} Put 🚨【基本面破灭·割肉平仓避险】</strong>：距离到期仅剩 {dte} 天，安全垫已破防 ({safety_cushion:+.1f}%)。<br><strong style='color: {tradeoff_color};'>{tradeoff_status}</strong>：{tradeoff_desc}<br><span style='color: #ef4444; font-size: 12px;'>👉 <strong>操作指引</strong>：相比于接股承担持续阴跌损失，当前买入平仓 (BTC) 割肉止损是更优的风控方案！</span></li>"
                )
        # 5. Deep ITM management
        elif is_deep_itm and dte > 15:
            if assignment_safe:
                decision = "准备现金接股 (备战CC)"
                decision_class = "highlight-green"
                decision_cell = f"<strong style='color: #34d399;'>准备现金接股 (备战CC)</strong><br><span style='font-size: 10.5px; color: #34d399; font-weight: 600;'>{badge_text}</span>"
                roll_res = calculate_roll_candidate(ticker, strike, curr_p, dte)
                roll_extra = f"<br><span style='color: #38bdf8; font-size: 11.5px;'>{roll_res['summary_html']}</span>" if roll_res.get("has_roll") else ""
                action_plan_recs.append(
                    f"<li><strong>{tv_link_inline} {expiration} ${strike:.2f} Put 🛡️【深实值·安心备战现金接股与CC】</strong>：标的现价暂低于行权价 <strong class='highlight-red'>{abs(safety_cushion):.1f}%</strong> (Delta {delta:.2f})，距离到期仍有 {dte} 天。<br><strong style='color: {tradeoff_color};'>{tradeoff_status}</strong>：{tradeoff_desc}{roll_extra}<br><span style='color: #34d399; font-size: 12px;'>👉 <strong>操作指引</strong>：标的估值具备强大支撑，低位接股完全契合长线底仓理念。建议提前核查账户可用现金以备行权，或等待股价技术反弹契机向下/向后展期增厚权利金。无需恐慌割肉！</span></li>"
                )
            else:
                decision = "割肉平仓 (BTC 避险)"
                decision_class = "highlight-red"
                decision_cell = f"<strong style='color: #ef4444;'>割肉平仓 (BTC 避险)</strong><br><span style='font-size: 10.5px; color: #ef4444; font-weight: 600;'>{badge_text}</span>"
                action_plan_recs.append(
                    f"<li><strong>{tv_link_inline} {expiration} ${strike:.2f} Put 🚨【深实值且基本面崩坏·建议平仓止损】</strong>：标的现价低于行权价 {abs(safety_cushion):.1f}%。<br><strong style='color: {tradeoff_color};'>{tradeoff_status}</strong>：{tradeoff_desc}<br><span style='color: #ef4444; font-size: 12px;'>👉 <strong>操作指引</strong>：建议寻找盘中反弹反抽机会挂单买入平仓 (BTC) 止损，避免被迫接手基本面恶化资产！</span></li>"
                )
        # 6. Standard hold
        else:
            decision = "继续持有 (Hold)"
            decision_class = "highlight-green"
            decision_cell = f"<strong style='color: #34d399;'>继续持有 (Hold)</strong><br><span style='font-size: 10.5px; color: #34d399; font-weight: 600;'>{badge_text}</span>"
            if is_knife or is_fcf_neg:
                action_plan_recs.append(
                    f"<li><strong>{tv_link_inline} {expiration} ${strike:.2f} Put 🔍【技术急跌/Capex波动·基本面良性持有】</strong>：该标的虽有短期波动（近30天变动 {abs(mdata.get('return_30d', 0.0))*100:.1f}%），当前安全垫为 <strong class='highlight-green'>{safety_cushion:+.1f}%</strong>。<br><strong style='color: {tradeoff_color};'>{tradeoff_status}</strong>：{tradeoff_desc}<br><span style='color: #34d399; font-size: 12px;'>👉 <strong>操作指引</strong>：继续持有赚取 Theta 衰减。若被行权，此价格接股质地优良，安心收租！</span></li>"
                )
            
        pnl_class = "highlight-green" if pnl >= 0 else "highlight-red"
        
        if ticker == 'IBIT' and btc_price and curr_stock_price > 0:
            strike_btc = strike * (btc_price / curr_stock_price)
            price_cell = f"${curr_stock_price:.2f} (BTC ${btc_price:,.0f}) / ${strike:.2f} (BTC ${strike_btc:,.0f})<br><span class='highlight-green' style='font-size: 11px; font-weight: 600;'>{safety_cushion:+.2f}%</span>"
        else:
            price_cell = f"${curr_stock_price:.2f} / ${strike:.2f}<br><span class='highlight-green' style='font-size: 11px; font-weight: 600;'>{safety_cushion:+.2f}%</span>"
            
        yield_style = "color: #a1a1aa;" if remaining_yield < 5.0 else ("color: #4ade80; font-weight: 600;" if remaining_yield >= 15.0 else "color: #f4f4f5;")
        
        ticker_link = f"<a href='{tv_url}' target='_blank' style='color: #ffffff; text-decoration: none; border-bottom: 1px dashed #60a5fa;' title='查看 {ticker} TradingView 图表'><strong style='color: #fff;'>{ticker}</strong> <span style='font-size: 11px; color: #60a5fa;'>📈</span></a>"
        
        # Danger pulse only if fundamental breakdown occurs (unsafe assignment)
        row_class_attr = 'class="danger-pulse"' if (not assignment_safe) else ''
        row_style = '' if (not assignment_safe) else f'style="background-color: {"#09090b" if idx % 2 == 0 else "#18181b"};"'
        
        # Position Delta, Gamma & Pin Risk
        pos_delta_shares = -delta * qty * 100.0
        pos_delta_notional = pos_delta_shares * curr_stock_price
        gamma = float(pos.get('gamma', 0.0))
        is_pin_risk = (dte <= 14 and safety_cushion < 3.0 and gamma >= 0.06)
        gamma_badge = " <span style='color: #ef4444; font-size: 10px; font-weight: bold; background: rgba(239, 68, 68, 0.15); padding: 1px 4px; border-radius: 3px; border: 1px solid rgba(239,68,68,0.3);'>[⚡Pin Risk]</span>" if is_pin_risk else ""
        gamma_str = f" • &Gamma; {gamma:.3f}" if gamma > 0 else ""
        delta_cell = f"<strong style='color: #ffffff;'>{delta:.3f}</strong>{gamma_badge}<br><span style='font-size: 10.5px; color: #60a5fa;'>等效 {pos_delta_shares:+.1f}股 • ${pos_delta_notional:,.0f}{gamma_str}</span>"
        
        table_task1 += f"""
        <tr {row_class_attr} {row_style}>
            <td style="padding: 12px 16px; vertical-align: middle; border-bottom: 1px solid #27272a;">{ticker_link}</td>
            <td style="padding: 12px 16px; vertical-align: middle; border-bottom: 1px solid #27272a;">{int(qty)}张 • {expiration} ${strike:.2f} Put</td>
            <td style="padding: 12px 16px; vertical-align: middle; border-bottom: 1px solid #27272a;">{price_cell}</td>
            <td style="padding: 12px 16px; vertical-align: middle; border-bottom: 1px solid #27272a;">{dte} 天</td>
            <td style="padding: 12px 16px; vertical-align: middle; border-bottom: 1px solid #27272a;">{delta_cell}</td>
            <td style="padding: 12px 16px; vertical-align: middle; border-bottom: 1px solid #27272a;" class="{pnl_class}">
                {pnl:+.2f} ({pnl_pct:+.1f}%)<br>
                <span style="font-size: 10.5px; color: var(--text-secondary);">(开仓: ${open_p:.2f} / 现值: ${curr_p:.2f})</span>
            </td>
            <td style="padding: 12px 16px; vertical-align: middle; border-bottom: 1px solid #27272a;">
                <span style="font-size: 11px; color: var(--text-secondary);">开仓: {open_yield:.1f}%</span><br>
                <span style="{yield_style}">剩余: {remaining_yield:.1f}%</span>
            </td>
            <td style="padding: 12px 16px; vertical-align: middle; border-bottom: 1px solid #27272a;">{decision_cell}</td>
        </tr>"""
        
    if not action_plan_recs:
        action_plan_html = """
        <div class="card">
            <h3 class="card-title">🟢 行动方案与风险管理 (Action Plan)</h3>
            <h4 style="font-size: 13px; margin: 0 0 8px 0; color: var(--text-primary);">2.1 核心仓位管理说明：</h4>
            <ul>
                <li><strong>全部继续持有 (Hold)</strong>：当前所有持仓均处于安全区间（安全垫充足且未达止盈门槛），可静待时间价值（Theta）衰减。</li>
            </ul>
        </div>"""
    else:
        recs_list_html = "\n".join(action_plan_recs)
        action_plan_html = f"""
        <div class="card">
            <h3 class="card-title">🟢 行动方案与风险管理 (Action Plan)</h3>
            <h4 style="font-size: 13px; margin: 0 0 8px 0; color: var(--text-primary);">2.1 核心仓位管理说明：</h4>
            <ul>
                {recs_list_html}
                <li><strong>其余持仓继续持有 (Hold)</strong>：其余未列出的 Short Put 仓位安全垫充足，建议继续持有赚取 Theta 衰减。</li>
            </ul>
        </div>"""

    # ==================== HTML MERGING ====================
    print("Merging generated tables into report.html...")
    
    # Check data freshness
    stale_files = []
    files_to_check = [
        ("账户资产信息", os.path.join(BASE_DIR, 'data', 'account_info.json')),
        ("期权持仓信息", os.path.join(BASE_DIR, 'data', 'current_positions.json')),
        ("股票持仓信息", os.path.join(BASE_DIR, 'data', 'current_equity_positions.json'))
    ]
    for label, filepath in files_to_check:
        if os.path.exists(filepath):
            age_min = (time.time() - os.path.getmtime(filepath)) / 60.0
            if age_min > 30.0:
                stale_files.append((label, age_min))
                
    stale_banner_html = ""
    if stale_files:
        stale_details = "、".join([f"{l}（已过期 {a:.0f}分钟）" for l, a in stale_files])
        print(f"⚠️ [STALE DATA WARNING] {stale_details}")
        stale_banner_html = f"""
        <div style="background-color: rgba(239, 68, 68, 0.1); border: 1px solid #ef4444; color: #f87171; padding: 12px 16px; border-radius: 8px; margin-bottom: 20px; font-size: 13px; display: flex; align-items: center; gap: 8px; font-family: -apple-system, sans-serif;">
            <span>⚠️</span>
            <span><strong>数据过期警告</strong>：当前报告中的 {stale_details}。数据非最新，可能存在偏差。请通过 Robinhood MCP 重新运行资产同步！</span>
        </div>
        """
        
    with open(os.path.join(BASE_DIR, 'report_template.html'), 'r') as f:
        template = f.read()
        
    # Note: cash_available must strictly represent unleveraged_buying_power (unleveraged cash for Sell Put)
    account_info = {
        "total_collateral": 0.0,
        "cash_available": 0.0,
        "active_options": "0 <span style=\"font-size: 13px; font-weight: normal; color: var(--text-secondary);\">Short Puts</span>",
        "active_options_sub": "0 笔潜在 Covered Call",
        "scanned_tickers": len(active_tickers),
        "watchlist_candidates": len(ordered_watchlist)
    }
    account_info_path = os.path.join(BASE_DIR, 'data', 'account_info.json')
    if os.path.exists(account_info_path):
        try:
            with open(account_info_path, 'r') as f:
                account_info.update(json.load(f))
        except Exception as e:
            print(f"Warning: Failed to load account_info.json: {e}")
            
    # Calculate collateral budget for Top 5 and Top 10 distinct tickers
    distinct_tickers_options = []
    seen_tickers = set()
    for opt in all_options:
        ticker = opt['ticker']
        if ticker not in seen_tickers:
            seen_tickers.add(ticker)
            distinct_tickers_options.append(opt)
            
    top_5_options = distinct_tickers_options[:5]
    top_10_options = distinct_tickers_options[:10]
    
    collateral_needed_5 = sum(opt['strike'] * 100.0 for opt in top_5_options)
    collateral_needed_10 = sum(opt['strike'] * 100.0 for opt in top_10_options)
    
    cash_available = account_info.get('cash_available', 0.0)
    
    gap_5 = max(0.0, collateral_needed_5 - cash_available)
    gap_10 = max(0.0, collateral_needed_10 - cash_available)
    
    def format_money(val):
        return f"${val:,.2f}" if val < 10000 else f"${int(val):,}"

    gap_5_str = f'<span style="color: var(--green); font-weight: 600;">充足 (缺口 $0)</span>' if gap_5 <= 0 else f'<span style="color: var(--red); font-weight: 600;">缺口 {format_money(gap_5)}</span>'
    gap_10_str = f'<span style="color: var(--green); font-weight: 600;">充足 (缺口 $0)</span>' if gap_10 <= 0 else f'<span style="color: var(--red); font-weight: 600;">缺口 {format_money(gap_10)}</span>'
    
    collateral_budget_html = f"""
    <div class="card" style="margin-top: 24px; border: 1px solid rgba(96, 165, 250, 0.15); background: linear-gradient(180deg, rgba(24, 24, 27, 0.8) 0%, rgba(9, 9, 11, 0.9) 100%); margin-bottom: 32px;">
        <h3 class="card-title" style="border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 12px; margin-bottom: 16px; color: #ffffff; display: flex; align-items: center; gap: 8px;">
            <span>💰</span> 资金占用与保证金安全度统计 (Collateral & Buying Power Budget)
        </h3>
        <p style="font-size: 13.5px; color: var(--text-secondary); margin-bottom: 18px; line-height: 1.5;">
            基于 <strong>Cash Secured Put (CSP)</strong> 的全额本金行权假设，若您按照综合性价比排名建仓（各标的仅建立 <strong>1 张</strong> 最优合约），所需的担保资金预算及与当前账户可用无杠杆购买力的对比情况如下：
        </p>
        
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px;">
            <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.04); border-radius: 12px; padding: 16px; display: flex; flex-direction: column; gap: 10px;">
                <span style="font-size: 11px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em;">当前账户可用现金</span>
                <span style="font-size: 22px; font-weight: 700; color: var(--blue); font-family: 'Outfit', sans-serif;">{format_money(cash_available)}</span>
                <span style="font-size: 12px; color: rgba(255, 255, 255, 0.4);">取自无杠杆购买力 (Unleveraged Buying Power)</span>
            </div>
            
            <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.04); border-radius: 12px; padding: 16px; display: flex; flex-direction: column; gap: 8px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-size: 11px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em;">Top 5 标的建仓预算</span>
                    <span style="font-size: 10.5px; padding: 2px 6px; background: rgba(52, 211, 153, 0.1); border: 1px solid rgba(52, 211, 153, 0.2); border-radius: 4px; color: var(--green);">各 1 张</span>
                </div>
                <span style="font-size: 20px; font-weight: 700; color: #ffffff; font-family: 'Outfit', sans-serif;">{format_money(collateral_needed_5)}</span>
                <div style="display: flex; justify-content: space-between; font-size: 12.5px; margin-top: 4px;">
                    <span style="color: var(--text-secondary);">购买力状态:</span>
                    <span>{gap_5_str}</span>
                </div>
                <div style="font-size: 10.5px; color: rgba(255,255,255,0.3); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="{', '.join(opt['ticker'] for opt in top_5_options)}">
                    标的: {', '.join(opt['ticker'] for opt in top_5_options)}
                </div>
            </div>
            
            <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.04); border-radius: 12px; padding: 16px; display: flex; flex-direction: column; gap: 8px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-size: 11px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em;">Top 10 标的建仓预算</span>
                    <span style="font-size: 10.5px; padding: 2px 6px; background: rgba(168, 85, 247, 0.1); border: 1px solid rgba(168, 85, 247, 0.2); border-radius: 4px; color: #c084fc;">各 1 张</span>
                </div>
                <span style="font-size: 20px; font-weight: 700; color: #ffffff; font-family: 'Outfit', sans-serif;">{format_money(collateral_needed_10)}</span>
                <div style="display: flex; justify-content: space-between; font-size: 12.5px; margin-top: 4px;">
                    <span style="color: var(--text-secondary);">购买力状态:</span>
                    <span>{gap_10_str}</span>
                </div>
                <div style="font-size: 10.5px; color: rgba(255,255,255,0.3); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="{', '.join(opt['ticker'] for opt in top_10_options)}">
                    标的: {', '.join(opt['ticker'] for opt in top_10_options)}
                </div>
            </div>
        </div>
        
        <div style="margin-top: 16px; padding: 10px 14px; background: rgba(251, 191, 36, 0.05); border: 1px solid rgba(251, 191, 36, 0.15); border-radius: 6px; font-size: 12px; color: var(--orange); display: flex; align-items: center; gap: 6px;">
            <span>⚠️</span>
            <span><strong>风控建议</strong>：若存在可用现金缺口，请勿同时满仓挂单！建议优先从 Top 5 性价比最高的合约中精选 1-2 个标的建立底仓，保持账户至少保留 20% 以上的富余购买力应对突发波动。</span>
        </div>
    </div>
    """

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    btc_price_str = f"{btc_price:,.0f}" if btc_price else ""
    
    # Build Wash Sale Risk Warning Card HTML
    recent_loss_items = []
    for s_name, s_losses in wash_sale_history_map.items():
        for l_item in s_losses:
            tv_url = get_tradingview_url(s_name)
            t_link = f"<a href='{tv_url}' target='_blank' style='color: #f87171; font-weight: bold; text-decoration: none; border-bottom: 1px dashed #f87171;'>{s_name}</a>"
            recent_loss_items.append(
                f"<li style='margin-bottom: 6px;'><strong>{t_link}</strong>：平仓割肉/交易亏损 <strong>-${abs(l_item['loss']):.2f}</strong>（交易日: {l_item['trade_date']}，{l_item['days_ago']}天前）。<br><span style='color: #fbbf24; font-size: 11.5px;'>🔐 Wash Sale 禁入期中，解封解禁日期：<strong>{l_item['unlock_date']}</strong></span></li>"
            )
    
    floating_loss_items = []
    if isinstance(current_positions, list):
        for pos in current_positions:
            if not isinstance(pos, dict): continue
            sym = pos['symbol']
            op = pos['open_price']
            cp = pos['current_price']
            q = pos['quantity']
            strike = pos['strike']
            exp = pos['expiration']
            pnl_val = (op - cp) * 100.0 * q
            pnl_p = (op - cp) / op * 100.0 if op > 0 else 0.0
            if pnl_val < 0:
                tv_url = get_tradingview_url(sym)
                t_link = f"<a href='{tv_url}' target='_blank' style='color: #fbbf24; font-weight: bold; text-decoration: none; border-bottom: 1px dashed #fbbf24;'>{sym}</a>"
                floating_loss_items.append(
                    f"<li style='margin-bottom: 6px;'><strong>{t_link}</strong> ({exp} ${strike:.2f} Put)：浮亏 <strong>-${abs(pnl_val):.2f} ({pnl_p:.1f}%)</strong>。<br><span style='color: #a1a1aa; font-size: 11.5px;'>若当前平仓割肉 (BTC) 并在 30 天内重开，已实现亏损将无法当期抵税。</span></li>"
                )
                
    recent_loss_html = "<ul>" + "".join(recent_loss_items) + "</ul>" if recent_loss_items else "<p style='color: var(--text-secondary); font-size: 12.5px; margin: 0;'>无近30天平仓亏损记录。</p>"
    floating_loss_html = "<ul>" + "".join(floating_loss_items) + "</ul>" if floating_loss_items else "<p style='color: var(--text-secondary); font-size: 12.5px; margin: 0;'>无浮亏持仓。</p>"

    wash_sale_warning_html = f"""
    <div class="card" style="margin-top: 16px; margin-bottom: 24px; border-color: rgba(239, 68, 68, 0.4); background: rgba(239, 68, 68, 0.04); backdrop-filter: blur(16px);">
        <div class="card-title" style="color: #f87171; border-bottom-color: rgba(239, 68, 68, 0.2); display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
            <span style="display: flex; align-items: center; gap: 8px;">
                <span>🚨 Wash Sale（洗售逃税防范规则）风险监控警示</span>
            </span>
            <span style="font-size: 11px; font-weight: normal; padding: 2px 8px; border-radius: 9999px; background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.3); color: #f87171;">税务风控机制</span>
        </div>
        <p style="font-size: 13px; color: var(--text-primary); margin: 0 0 12px 0; line-height: 1.6;">
            <strong>避税风控纪律：</strong> 根据美国 IRS 税务规则，在平仓割肉/卖出亏损标的前后 <strong>30 天（共 61 天）</strong> 内，若重新开仓买入相同或极度相似（Substantially Identical）的股票或看跌/看涨期权（如 sell put），该笔已发生的亏损将<strong>被强制禁止当期申报扣税 (Disallowed)</strong>，其亏损额将被累加并调增至新仓位的成本基准（Cost Basis）。
        </p>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; margin-top: 12px;">
            <div style="background: rgba(0,0,0,0.3); border: 1px solid rgba(239, 68, 68, 0.2); border-radius: 8px; padding: 14px 16px;">
                <div style="font-size: 13px; font-weight: 600; color: #f87171; margin-bottom: 8px; display: flex; align-items: center; gap: 6px;">
                    <span>🛑</span> 近 30 天已割肉平仓标的（新建 CSP 限制）
                </div>
                {recent_loss_html}
            </div>
            <div style="background: rgba(0,0,0,0.3); border: 1px solid rgba(251, 191, 36, 0.2); border-radius: 8px; padding: 14px 16px;">
                <div style="font-size: 13px; font-weight: 600; color: #fbbf24; margin-bottom: 8px; display: flex; align-items: center; gap: 6px;">
                    <span>⚠️</span> 当前处于浮亏状态的期权持仓（若平仓 BTC 并在30天内重开将触发 Wash Sale）
                </div>
                {floating_loss_html}
            </div>
        </div>
    </div>
    """

    output = template.replace('<!-- TABLE_GROUPED_PLACEHOLDER -->', table_grouped)
    output = output.replace('<!-- COLLATERAL_BUDGET_PLACEHOLDER -->', collateral_budget_html)
    output = output.replace('<!-- TABLE_CC_PLACEHOLDER -->', cc_html)
    output = output.replace('<!-- TABLE_TASK1_PLACEHOLDER -->', table_task1)
    output = output.replace('<!-- ACTION_PLAN_PLACEHOLDER -->', action_plan_html)
    output = output.replace('<!-- WASH_SALE_WARNING_PLACEHOLDER -->', wash_sale_warning_html)
    output = output.replace('<!-- STALE_DATA_WARNING_BANNER -->', stale_banner_html)
    output = output.replace('<!-- MACRO_SENTIMENT_MONITOR_PLACEHOLDER -->', macro_sentiment_html)
    output = output.replace('<!-- NEW_TICKERS_DEEP_DIVE_PLACEHOLDER -->', new_tickers_analysis_html)
    output = output.replace('<!-- REPORT_TIME_PLACEHOLDER -->', now_str)
    output = output.replace('<!-- BTC_PRICE_PLACEHOLDER -->', btc_price_str)
    

            
    # (Legacy regex yield calculation removed as remaining_yield is already cleanly rendered in Table 1)
        
    tot_collateral = account_info.get('total_collateral', 0.0)
    cash_avail = account_info.get('cash_available', 0.0)
    act_opts = account_info.get('active_options', '0')
    act_opts_sub = account_info.get('active_options_sub', '')
    scanned_ticks = account_info.get('scanned_tickers', 0)
    wl_candidates = account_info.get('watchlist_candidates', 0)

    output = output.replace('<!-- TOTAL_COLLATERAL_PLACEHOLDER -->', f"${int(tot_collateral):,}")
    output = output.replace('<!-- CASH_AVAILABLE_PLACEHOLDER -->', f"${int(cash_avail):,}")
    output = output.replace('<!-- ACTIVE_OPTIONS_PLACEHOLDER -->', str(act_opts))
    output = output.replace('<!-- ACTIVE_OPTIONS_SUB_PLACEHOLDER -->', str(act_opts_sub))
    output = output.replace('<!-- SCANNED_TICKERS_PLACEHOLDER -->', f"{scanned_ticks} <span style=\"font-size: 13px; font-weight: normal; color: var(--text-secondary);\">Tickers</span>")
    output = output.replace('<!-- WATCHLIST_CANDIDATES_PLACEHOLDER -->', f"{wl_candidates} <span style=\"font-size: 13px; font-weight: normal; color: var(--text-secondary);\">Candidates</span>")
    output = output.replace('<!-- PORTFOLIO_THETA_PLACEHOLDER -->', f"+${account_info.get('portfolio_theta', 0.0):.2f}")
    
    delta_notional_val = portfolio_delta_summary.get("total_delta_notional", 0.0)
    delta_lev_ratio = portfolio_delta_summary.get("leverage_ratio", 0.0)
    delta_status_label = portfolio_delta_summary.get("status_label", "🟢 稳健防守")
    delta_status_color = portfolio_delta_summary.get("status_color", "#34d399")

    output = output.replace('<!-- PORTFOLIO_DELTA_NOTIONAL_PLACEHOLDER -->', f"${int(delta_notional_val):,}")
    output = output.replace('<!-- PORTFOLIO_LEVERAGE_PLACEHOLDER -->', f"{delta_lev_ratio:.2f}x 杠杆率 • <span style='color: {delta_status_color}; font-weight: 600;'>{delta_status_label}</span>")
    
    with open(os.path.join(BASE_DIR, 'report.html'), 'w', encoding='utf-8') as f:
        f.write(output)
    total_sec = time.time() - start_time
    print(f"report.html successfully generated and updated in {total_sec:.2f}s!")
    
    # Generate compact metadata summary JSON for Agent / UI health check
    summary_audit = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date": today.strftime("%Y-%m-%d"),
        "runtime_seconds": round(total_sec, 2),
        "target_tickers_count": len(active_tickers),
        "qualifying_tickers_count": len(ordered_watchlist),
        "ordered_watchlist_top10": ordered_watchlist[:10],
        "open_positions_count": len(current_positions),
        "open_positions": [p.get("symbol") for p in current_positions],
        "macro_mode": "VIX_EXTREME" if vix_extreme_crisis else ("RED_DEFENSE" if deep_defense_mode else ("YELLOW_DEFENSE" if macro_circuit_breaker else "NORMAL")),
        "report_html_size_kb": round(os.path.getsize(os.path.join(BASE_DIR, 'report.html')) / 1024, 1)
    }
    atomic_write_json(os.path.join(BASE_DIR, "data", "report_summary.json"), summary_audit)

if __name__ == "__main__":
    main()
