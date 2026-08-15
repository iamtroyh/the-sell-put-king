# -*- coding: utf-8 -*-
"""
Market Data & Fundamentals Engine
=================================
Multi-threaded Yahoo Finance integration, price history caching, Piotroski
F-Score calculation, SEC Form 4 insider sentiment analysis, and VIX macro
circuit breaker monitoring.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from option_quant.config import (
    BASE_DIR,
    DATA_DIR,
    SECTOR_MAP,
    atomic_write_json,
    is_etf_symbol,
    is_high_vol_growth,
    is_long_bull,
    normalize_symbol,
    to_display_symbol,
    to_yf_symbol,
)

logger = logging.getLogger("option_quant.market_data")

INSIDER_CACHE_PATH = os.path.join(DATA_DIR, "insider_sentiment_cache.json")
MARKET_HISTORY_CACHE_PATH = os.path.join(DATA_DIR, "market_history_cache.json")
FUNDAMENTAL_CACHE_PATH = os.path.join(DATA_DIR, "fundamental_cache.json")

_INSIDER_MEM_CACHE: Optional[Dict[str, Any]] = None
_INSIDER_LOCK = threading.Lock()


def fetch_chart_df(symbol: str, range_str: str = '1y') -> pd.DataFrame:
    """
    Directly query Yahoo Finance v8 chart API as a reliable fallback when
    yfinance encounters scraping or network rate limits.

    Args:
        symbol: Yahoo-compatible symbol.
        range_str: Historical range (e.g. '1y', '3mo', '5d').

    Returns:
        DataFrame indexed by DatetimeIndex with Open, High, Low, Close, Volume.
    """
    try:
        url = f'https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={range_str}'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
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
    except Exception as e:
        logger.debug(f"Failed to fetch chart API for {symbol}: {e}")
        return pd.DataFrame()


def calculate_piotroski_f_score(info: Optional[Dict[str, Any]]) -> Tuple[Optional[int], List[str]]:
    """
    Calculate Piotroski 9-point fundamental financial health score (0-9).
    F-Score <= 3 triggers one-vote veto penalty (-50 pts).
    F-Score >= 7 earns quality bonus (+10 pts).

    Args:
        info: Yahoo Finance company info dict.

    Returns:
        (score, list_of_passed_criteria)
    """
    if not info:
        return None, []

    score = 0
    checks = []
    roa = info.get("returnOnAssets")
    if roa is not None and roa > 0:
        score += 1
        checks.append("ROA>0")
    fcf = info.get("freeCashflow")
    if fcf is not None and fcf > 0:
        score += 1
        checks.append("FCF>0")
    roe = info.get("returnOnEquity")
    if roe is not None and roe > 0.08:
        score += 1
        checks.append("ROE良好")
    net_inc = info.get("netIncomeToCommon")
    if fcf is not None and net_inc is not None and fcf > net_inc:
        score += 1
        checks.append("现金流质量高于净利润")
    de = info.get("debtToEquity")
    if de is not None and de <= 150:
        score += 1
        checks.append("负债率可控")
    cr = info.get("currentRatio")
    if cr is not None and cr >= 1.0:
        score += 1
        checks.append("流动比率健康")
    gm = info.get("grossMargins")
    if gm is not None and gm >= 0.25:
        score += 1
        checks.append("毛利率充沛")
    rg = info.get("revenueGrowth")
    if rg is not None and rg > 0:
        score += 1
        checks.append("营收正增长")
    om = info.get("operatingMargins")
    if om is not None and om > 0.05:
        score += 1
        checks.append("营业利润率良好")

    return score, checks


def check_eva_and_moat(symbol: str, info: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """
    Evaluate Economic Value Added (EVA) and economic moat conviction.

    Args:
        symbol: Stock symbol.
        info: Yahoo Finance info dict.

    Returns:
        (is_high_conviction, moat_description)
    """
    if is_etf_symbol(symbol):
        return True, "宽基/行业 ETF 分散持有"

    if not info:
        return False, "暂无基本面数据"

    roe = info.get("returnOnEquity")
    de = info.get("debtToEquity")
    is_eva_pos = (roe is not None and roe >= 0.12 and (de is None or de <= 150))
    wide_moats = [
        "MSFT", "AAPL", "COST", "MCD", "ISRG", "NVDA", "GOOGL", "META",
        "V", "MA", "ORCL", "CME", "ICE", "ACN", "BSX", "SNPS", "IBM",
        "DHR", "MDT", "ABT"
    ]
    is_moat = (symbol in wide_moats) or is_long_bull(symbol)
    return (is_eva_pos or is_moat), ("Wide Moat 垄断壁垒" if is_moat else "ROIC>WACC 资本增加值>0")


def check_is_low_position(display_name: str, hist: pd.DataFrame, fund_info: Optional[Dict[str, Any]] = None) -> bool:
    """
    Determine whether a ticker is currently sitting in an oversold / extreme-value price zone.

    Args:
        display_name: Standard symbol.
        hist: Price history DataFrame.
        fund_info: Optional fundamental cache info dict.

    Returns:
        True if ticker qualifies as low-position.
    """
    if hist is None or hist.empty:
        return False

    current_price = float(hist['Close'].iloc[-1])
    high_52w = float(hist['Close'].max())
    low_52w = float(hist['Close'].min())
    sma_200 = float(hist['Close'].rolling(200).mean().iloc[-1]) if len(hist) >= 200 else current_price
    sma_50 = float(hist['Close'].rolling(50).mean().iloc[-1]) if len(hist) >= 50 else current_price
    chg_30d = float((current_price - hist['Close'].iloc[-22]) / hist['Close'].iloc[-22]) if len(hist) >= 22 else 0.0

    # Deep value & high quality elasticity exemption (Forward P/E <= 15.0 & FCF/OCF > 0)
    is_deep_value = False
    if fund_info and not is_long_bull(display_name):
        fwd_pe = fund_info.get('forwardPE') or fund_info.get('trailingPE')
        ocf = fund_info.get('operatingCashflow') or fund_info.get('freeCashflow')
        if fwd_pe and fwd_pe <= 15.0 and ocf and ocf > 0:
            is_deep_value = True
    elif fund_info and is_long_bull(display_name):
        fwd_pe = fund_info.get('forwardPE') or fund_info.get('trailingPE')
        ocf = fund_info.get('operatingCashflow') or fund_info.get('freeCashflow')
        if fwd_pe and fwd_pe <= 18.0 and ocf and ocf > 0:
            is_deep_value = True

    if is_long_bull(display_name):
        dev = (current_price - sma_200) / sma_200 if sma_200 > 0 else 0.0
        is_low = (
            (dev <= 0.03) or
            (sma_50 > sma_200 and current_price <= sma_50 * 1.01 and dev <= 0.08) or
            (chg_30d <= -0.08 and dev <= 0.05) or
            (is_deep_value and dev <= 0.06)
        )
    elif is_high_vol_growth(display_name):
        rp = (current_price - low_52w) / (high_52w - low_52w) if (high_52w - low_52w) > 0 else 0.5
        is_low = (rp <= 0.25) or (chg_30d <= -0.15 and rp <= 0.40) or (is_deep_value and rp <= 0.35)
    else:
        rp = (current_price - low_52w) / (high_52w - low_52w) if (high_52w - low_52w) > 0 else 0.5
        is_low = (rp <= 0.25) or (chg_30d <= -0.12 and rp <= 0.40) or (is_deep_value and rp <= 0.35)

    return bool(is_low)


# ==================== INSIDER SENTIMENT (SEC FORM 4) ====================

def _load_insider_cache() -> Dict[str, Any]:
    global _INSIDER_MEM_CACHE
    with _INSIDER_LOCK:
        if _INSIDER_MEM_CACHE is None:
            if os.path.exists(INSIDER_CACHE_PATH):
                try:
                    with open(INSIDER_CACHE_PATH, "r", encoding="utf-8") as f:
                        _INSIDER_MEM_CACHE = json.load(f)
                except Exception:
                    _INSIDER_MEM_CACHE = {}
            else:
                _INSIDER_MEM_CACHE = {}
        return _INSIDER_MEM_CACHE


def _classify_transaction(transaction_str: str, text_str: str = "") -> str:
    combined = (str(transaction_str) + " " + str(text_str)).lower()
    if not combined.strip():
        return "other"
    if any(k in combined for k in ("purchase", "buy", "bought", "open market purchase")):
        return "buy"
    if any(k in combined for k in ("sale", "sell", "sold", "open market sale")):
        return "sell"
    if any(k in combined for k in ("exercise", "conversion", "option", "grant", "award", "gift")):
        return "exercise_or_grant"
    return "other"


def get_insider_sentiment(symbol: str, days_back: int = 90, force_refresh: bool = False) -> Dict[str, Any]:
    """
    Fetches and analyzes SEC Form 4 insider transactions for a symbol.
    Returns structured sentiment (heavy_selling, net_buying, neutral), net values, and badge HTML.
    """
    sym = normalize_symbol(symbol)
    if is_etf_symbol(sym):
        return {
            "symbol": sym,
            "is_etf": True,
            "sentiment": "neutral",
            "net_value": 0.0,
            "buy_value": 0.0,
            "sell_value": 0.0,
            "buy_count": 0,
            "sell_count": 0,
            "badge_html": "<span style='padding: 2px 6px; border-radius: 4px; background: rgba(255,255,255,0.05); color: #a1a1aa; font-size: 10.5px; border: 1px solid rgba(255,255,255,0.1);'>ETF基金 (不适用内幕交易)</span>",
            "summary_text": "ETF 基金不适用单一个股高管 Form 4 交易排雷。",
            "transactions": []
        }

    cache = _load_insider_cache()
    if not force_refresh and sym in cache:
        cached_item = cache[sym]
        if datetime.datetime.now().timestamp() - cached_item.get("timestamp", 0) < 86400 * 2:
            return cached_item.get("data", {})

    yf_sym = to_yf_symbol(sym)
    try:
        t = yf.Ticker(yf_sym)
        df = t.insider_transactions
    except Exception:
        df = None

    if df is None or df.empty:
        res = {
            "symbol": sym,
            "is_etf": False,
            "sentiment": "neutral",
            "net_value": 0.0,
            "buy_value": 0.0,
            "sell_value": 0.0,
            "buy_count": 0,
            "sell_count": 0,
            "badge_html": "<span style='padding: 2px 6px; border-radius: 4px; background: rgba(255,255,255,0.05); color: #a1a1aa; font-size: 10.5px;'>⚪ 无近期内幕申报</span>",
            "summary_text": "过去 90 天暂无高管重大内幕交易申报。",
            "transactions": []
        }
        with _INSIDER_LOCK:
            cache[sym] = {"timestamp": datetime.datetime.now().timestamp(), "data": res}
            atomic_write_json(INSIDER_CACHE_PATH, cache)
        return res

    cutoff_date = datetime.date.today() - datetime.timedelta(days=days_back)
    buy_val = 0.0
    sell_val = 0.0
    buy_cnt = 0
    sell_cnt = 0
    tx_list = []

    for _, row in df.iterrows():
        try:
            start_date_val = row.get("Start Date") or row.get("Date")
            if not start_date_val:
                continue
            if isinstance(start_date_val, (pd.Timestamp, datetime.datetime)):
                tx_date = start_date_val.date()
            else:
                tx_date = datetime.datetime.strptime(str(start_date_val)[:10], "%Y-%m-%d").date()

            if tx_date < cutoff_date:
                continue

            tx_type = _classify_transaction(str(row.get("Transaction", "")), str(row.get("Text", "")))
            shares = float(row.get("Shares", 0.0) or 0.0)
            value = float(row.get("Value", 0.0) or 0.0)
            insider_name = str(row.get("Insider", "Unknown"))
            position = str(row.get("Position", ""))

            if tx_type == "buy":
                buy_cnt += 1
                buy_val += value
            elif tx_type == "sell":
                sell_cnt += 1
                sell_val += value

            tx_list.append({
                "date": tx_date.strftime("%Y-%m-%d"),
                "insider": insider_name,
                "position": position,
                "type": tx_type,
                "shares": shares,
                "value": value
            })
        except Exception:
            continue

    net_val = buy_val - sell_val
    if (sell_val >= 10_000_000 and buy_cnt == 0) or (sell_cnt >= 5 and buy_cnt == 0 and sell_val >= 5_000_000):
        sentiment = "heavy_selling"
        badge = f"<span style='color: #f87171; font-weight: bold; background: rgba(239,68,68,0.12); padding: 2px 6px; border-radius: 4px; border: 1px solid rgba(239,68,68,0.3);'>[🚨 高管大额减持 -${sell_val/1e6:.1f}M]</span>"
        summary = f"过去 90 天高管累计净减持 ${sell_val/1e6:.1f}M，无主动增持买入，需警惕内部人套现风险。"
    elif buy_val >= 500_000 or (buy_cnt >= 2 and net_val > 0):
        sentiment = "net_buying"
        badge = f"<span style='color: #34d399; font-weight: bold; background: rgba(52,211,153,0.12); padding: 2px 6px; border-radius: 4px; border: 1px solid rgba(52,211,153,0.3);'>[👔 高管增持 +${buy_val/1e3:.0f}K]</span>"
        summary = f"过去 90 天高管真金白银增持自购 ${buy_val/1e3:.0f}K，释放管理层对未来基本面坚定看好信号。"
    else:
        sentiment = "neutral"
        badge = "<span style='padding: 2px 6px; border-radius: 4px; background: rgba(255,255,255,0.05); color: #a1a1aa; font-size: 10.5px;'>⚪ 内幕交易平稳</span>"
        summary = "过去 90 天高管交易平稳，无异常大额集中买卖。"

    res = {
        "symbol": sym,
        "is_etf": False,
        "sentiment": sentiment,
        "net_value": net_val,
        "buy_value": buy_val,
        "sell_value": sell_val,
        "buy_count": buy_cnt,
        "sell_count": sell_cnt,
        "badge_html": badge,
        "summary_text": summary,
        "transactions": tx_list[:10]
    }

    with _INSIDER_LOCK:
        cache[sym] = {"timestamp": datetime.datetime.now().timestamp(), "data": res}
        atomic_write_json(INSIDER_CACHE_PATH, cache)

    return res


def batch_get_insider_sentiment(symbols: List[str], days_back: int = 90, max_workers: int = 15) -> Dict[str, Dict[str, Any]]:
    """Parallel batch fetch insider sentiment for a list of symbols."""
    results: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(get_insider_sentiment, s, days_back): s for s in symbols}
        for future in as_completed(futures):
            sym = futures[future]
            try:
                results[sym] = future.result()
            except Exception as e:
                logger.debug(f"Failed to fetch insider sentiment for {sym}: {e}")
                results[sym] = {
                    "symbol": sym, "sentiment": "neutral", "net_value": 0.0,
                    "buy_value": 0.0, "sell_value": 0.0, "transactions": []
                }
    return results


# ==================== MACRO CIRCUIT BREAKER & VIX ====================

def check_macro_circuit_breaker() -> Tuple[bool, bool, bool, List[str]]:
    """
    Evaluate Macro Circuit Breaker & VIX sentiment.

    Returns:
        (vix_extreme_crisis, deep_defense_mode, macro_circuit_breaker, cb_reasons)
    """
    vix_extreme_crisis = False
    deep_defense_mode = False
    macro_circuit_breaker = False
    cb_reasons: List[str] = []

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

    return vix_extreme_crisis, deep_defense_mode, macro_circuit_breaker, cb_reasons


def fetch_btc_price() -> Optional[float]:
    """Fetch live BTC-USD spot price."""
    try:
        btc_ticker = yf.Ticker("BTC-USD")
        btc_hist = btc_ticker.history(period="1d")
        if not btc_hist.empty:
            return float(btc_hist['Close'].iloc[-1])
    except Exception:
        pass
    return None
