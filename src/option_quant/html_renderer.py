# -*- coding: utf-8 -*-
"""
HTML Report Rendering Engine
============================
High-performance, modular generator for the interactive quantitative option
strategy research dashboard, responsive cards, multi-tab panes, and sticky master rows.
"""

from __future__ import annotations

import datetime
import html
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from option_quant.config import (
    BASE_DIR,
    TICKER_EXCHANGE_MAP,
    get_tradingview_url,
    is_etf_symbol,
    normalize_symbol,
    to_display_symbol,
    to_rh_symbol,
)
from option_quant.market_data import calculate_piotroski_f_score, check_eva_and_moat
from option_quant.scoring import get_recommendation_reason

logger = logging.getLogger("option_quant.html_renderer")


def build_tradingview_card(ordered_watchlist: List[str], ticker_exchange_map: Optional[Dict[str, str]] = None) -> Tuple[str, str]:
    """
    Build the TradingView one-click copy card with accurate exchange prefixes.

    Returns:
        (card_html, comma_separated_symbols)
    """
    tv_map = ticker_exchange_map or TICKER_EXCHANGE_MAP
    tv_items: List[str] = []
    tv_plain_items: List[str] = []

    for t in ordered_watchlist:
        clean_t = to_rh_symbol(t)
        tv_plain_items.append(clean_t)
        exch = tv_map.get(t.upper().strip()) or tv_map.get(clean_t)
        if not exch:
            if clean_t in [
                'SPY', 'IWM', 'DIA', 'GLD', 'SLV', 'USO', 'GDX', 'GDXJ', 'ASHR', 'SPYM', 'VTV',
                'XLK', 'XLF', 'XLV', 'XLE', 'XLI', 'XLY', 'XLP', 'XLRE', 'XLU', 'XLB',
                'XBI', 'KWEB', 'URA', 'CTA', 'VNQ'
            ]:
                exch = 'AMEX'
            elif clean_t in [
                'CMCSA', 'QQQ', 'QQQM', 'IBIT', 'TLT', 'SOXX', 'SMH', 'TSLA', 'HOOD',
                'SOFI', 'NFLX', 'MSFT', 'META', 'AMZN', 'INTU', 'SNPS', 'ISRG', 'PDD',
                'TCOM', 'UPST', 'VEEV', 'LULU', 'AAPL', 'NVDA', 'AVGO', 'AMD', 'QCOM',
                'ASML', 'AMAT', 'LRCX', 'KLAC', 'MRVL', 'TXN', 'ADI', 'CDNS', 'COST',
                'SBUX', 'PEP', 'ADBE', 'ABNB', 'CME', 'MU', 'ANET', 'CEG', 'PYPL',
                'ULTA', 'SKHY', 'CRWD', 'PANW', 'FTNT', 'DDOG', 'ZS', 'COIN',
                'MARA', 'DKNG', 'FSLR', 'IDXX', 'HON', 'LIN', 'DUOL', 'GOOGL', 'BTDR',
                'MSTR', 'CLSK', 'APP', 'MELI', 'PODD', 'SPCX'
            ]:
                exch = 'NASDAQ'
            else:
                exch = 'NYSE'
        tv_items.append(f"{exch}:{clean_t}")

    tv_copy_str = ", ".join(tv_items)
    tv_plain_copy_str = ", ".join(tv_plain_items)

    card_html = f"""
    <div style="background: linear-gradient(135deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.8) 100%); border: 1px solid rgba(96, 165, 250, 0.3); border-radius: 10px; padding: 14px 18px; margin-bottom: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 8px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 16px;">📊</span>
          <span style="font-weight: 700; color: #ffffff; font-size: 13.5px;">TradingView Watchlist 一键导入文本</span>
          <span style="background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.4); font-size: 11px; padding: 1px 6px; border-radius: 4px; font-weight: 600;">精确降序同步 ({len(tv_items)} 只)</span>
        </div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap;">
          <button onclick="navigator.clipboard.writeText('{tv_plain_copy_str}').then(() => {{ this.innerText = '✅ 纯代码已复制！'; setTimeout(() => this.innerText = '📋 一键复制纯代码 (推荐)', 2500); }})" style="background: rgba(52, 211, 153, 0.2); border: 1px solid rgba(52, 211, 153, 0.5); color: #34d399; padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 700; cursor: pointer; transition: all 0.2s;">
            📋 一键复制纯代码 (推荐·零前缀错误)
          </button>
          <button onclick="navigator.clipboard.writeText('{tv_copy_str}').then(() => {{ this.innerText = '✅ 带前缀已复制！'; setTimeout(() => this.innerText = '📋 复制带交易所前缀', 2500); }})" style="background: rgba(96, 165, 250, 0.15); border: 1px solid rgba(96, 165, 250, 0.4); color: #60a5fa; padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.2s;">
            📋 复制带交易所前缀
          </button>
        </div>
      </div>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 8px;">
        <div>
          <div style="font-size: 11px; font-weight: 600; color: #34d399; margin-bottom: 4px;">🟢 纯代码模式 (TradingView 官方自动匹配交易所，100% 成功率):</div>
          <div style="background: #09090b; border: 1px solid #27272a; border-radius: 6px; padding: 8px 10px; font-family: SFMono-Regular, Consolas, 'Liberation Mono', Menlo, monospace; font-size: 11.5px; color: #34d399; word-break: break-all; max-height: 65px; overflow-y: auto; line-height: 1.4; user-select: all;">
            {tv_plain_copy_str}
          </div>
        </div>
        <div>
          <div style="font-size: 11px; font-weight: 600; color: #60a5fa; margin-bottom: 4px;">🔵 带交易所前缀 (官方主板映射):</div>
          <div style="background: #09090b; border: 1px solid #27272a; border-radius: 6px; padding: 8px 10px; font-family: SFMono-Regular, Consolas, 'Liberation Mono', Menlo, monospace; font-size: 11.5px; color: #60a5fa; word-break: break-all; max-height: 65px; overflow-y: auto; line-height: 1.4; user-select: all;">
            {tv_copy_str}
          </div>
        </div>
      </div>
      <div style="font-size: 11px; color: #a1a1aa; margin-top: 10px; line-height: 1.4;">
        💡 <strong>使用指引</strong>：在 TradingView 面板按 <code>Cmd+A</code> ➔ <code>Delete</code> 清空旧列表，或点击右上角 <strong><code>...</code> ➔ Import Watchlist</strong> 选文件；也可直接点击 <code>+</code> 添加代码并在输入框直接粘贴上面任一框的代码！
      </div>
    </div>
    """
    return card_html, tv_copy_str


def build_macro_sentiment_card(
    vix_extreme_crisis: bool,
    deep_defense_mode: bool,
    macro_circuit_breaker: bool,
    cb_reasons: List[str],
) -> str:
    """Build the Macro Risk & VIX monitoring alert banner."""
    if vix_extreme_crisis:
        color = "#ef4444"
        badge_text = "🚨 极端黑天鹅熔断 (VIX>=40) • 全场暂停新建仓"
        bg_style = "background-color: rgba(239, 68, 68, 0.15); border: 1px solid #ef4444;"
    elif deep_defense_mode:
        color = "#f87171"
        badge_text = "🔴 红灯极深虚值防守 (VIX>=30/跌幅>=12%) • Delta锁定0.08~0.15 & 安全垫>=12%"
        bg_style = "background-color: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.4);"
    elif macro_circuit_breaker:
        color = "#fbbf24"
        badge_text = "🟡 黄灯防守模式 (VIX>=25/跌幅>=8%) • Delta筛选收紧至0.10~0.25"
        bg_style = "background-color: rgba(251, 191, 36, 0.1); border: 1px solid rgba(251, 191, 36, 0.4);"
    else:
        color = "#34d399"
        badge_text = "🟢 宏观常态模式 • VIX与大盘处于健康波动区间"
        bg_style = "background-color: rgba(52, 211, 153, 0.08); border: 1px solid rgba(52, 211, 153, 0.3);"

    reasons_text = "；".join(cb_reasons) if cb_reasons else "大盘走势平稳，各核心指数与恐慌指数均处于标准阈值以内。"

    return f"""
    <div style="{bg_style} border-radius: 8px; padding: 12px 16px; margin-bottom: 20px; font-size: 13px; font-family: -apple-system, sans-serif;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; flex-wrap: wrap; gap: 6px;">
        <strong style="color: {color}; font-size: 13.5px;">{badge_text}</strong>
        <span style="font-size: 11px; color: var(--text-secondary);">实时恐慌指数与大盘风控熔断阀</span>
      </div>
      <div style="color: var(--text-primary); line-height: 1.5; font-size: 12.5px;">
        {reasons_text}
      </div>
    </div>
    """


def build_collateral_budget_card(
    all_options: List[Dict[str, Any]],
    cash_available: float,
) -> str:
    """Build the Collateral & Cash Purchasing Power Gap Card."""
    distinct_options: List[Dict[str, Any]] = []
    seen = set()
    for opt in all_options:
        ticker = opt['ticker']
        if ticker not in seen:
            seen.add(ticker)
            distinct_options.append(opt)

    top_5 = distinct_options[:5]
    top_10 = distinct_options[:10]

    top_5_collateral = sum(opt['strike'] * 100 for opt in top_5)
    top_10_collateral = sum(opt['strike'] * 100 for opt in top_10)

    top_5_shortage = max(0.0, top_5_collateral - cash_available)
    top_10_shortage = max(0.0, top_10_collateral - cash_available)

    top_5_status = "<span style='color: #34d399; font-weight: 600;'>🟢 资金完全充足 (无缺口)</span>" if top_5_shortage == 0 else f"<span style='color: #f87171; font-weight: 600;'>⚠️ 缺口 ${top_5_shortage:,.0f}</span>"
    top_10_status = "<span style='color: #34d399; font-weight: 600;'>🟢 资金完全充足 (无缺口)</span>" if top_10_shortage == 0 else f"<span style='color: #f87171; font-weight: 600;'>⚠️ 缺口 ${top_10_shortage:,.0f}</span>"

    top_5_items = "".join([f"<li style='margin-bottom: 4px;'><strong>{opt['ticker']}</strong>: ${opt['strike']:.2f} Strike ➔ 担保金 <strong>${opt['strike']*100:,.0f}</strong> ({opt['annualized_yield']:.1f}% APY)</li>" for opt in top_5])
    top_10_items = "".join([f"<li style='margin-bottom: 4px;'><strong>{opt['ticker']}</strong>: ${opt['strike']:.2f} Strike ➔ 担保金 <strong>${opt['strike']*100:,.0f}</strong> ({opt['annualized_yield']:.1f}% APY)</li>" for opt in top_10])

    return f"""
    <div class="card" style="margin-top: 24px; border-color: rgba(59, 130, 246, 0.3); background: rgba(59, 130, 246, 0.03);">
        <div class="card-title" style="color: #60a5fa; border-bottom-color: rgba(59, 130, 246, 0.2); display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
            <span style="display: flex; align-items: center; gap: 8px;">
                <span>💰 标的建仓资金占用与保证金缺口测算 (Cash Secured Put)</span>
            </span>
            <span style="font-size: 11px; font-weight: normal; padding: 2px 8px; border-radius: 9999px; background: rgba(59, 130, 246, 0.15); border: 1px solid rgba(59, 130, 246, 0.3); color: #60a5fa;">全额现金行权假设</span>
        </div>
        <p style="font-size: 13px; color: var(--text-primary); margin: 0 0 12px 0; line-height: 1.6;">
            当前账户<strong>可用现金 (Unleveraged Cash) 为 <span style="color: #34d399; font-weight: 700;">${cash_available:,.2f}</span></strong>。按当前多因子评分优选前 5 名与前 10 名各建仓 1 张 CSP 的资金测算如下：
        </p>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; margin-top: 12px;">
            <div style="background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 14px 16px;">
                <div style="font-size: 13px; font-weight: 600; color: #f4f4f5; margin-bottom: 8px; display: flex; justify-content: space-between;">
                    <span>🥇 建仓 Top 5 标的 (各 1 张)</span>
                    <span>{top_5_status}</span>
                </div>
                <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 10px;">
                    所需总担保金：<strong style="color: #ffffff; font-size: 14px;">${top_5_collateral:,.0f}</strong>
                </div>
                <ul style="font-size: 12px; color: var(--text-secondary); padding-left: 18px; margin: 0;">
                    {top_5_items}
                </ul>
            </div>
            <div style="background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 14px 16px;">
                <div style="font-size: 13px; font-weight: 600; color: #f4f4f5; margin-bottom: 8px; display: flex; justify-content: space-between;">
                    <span>🔟 建仓 Top 10 标的 (各 1 张)</span>
                    <span>{top_10_status}</span>
                </div>
                <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 10px;">
                    所需总担保金：<strong style="color: #ffffff; font-size: 14px;">${top_10_collateral:,.0f}</strong>
                </div>
                <ul style="font-size: 12px; color: var(--text-secondary); padding-left: 18px; margin: 0;">
                    {top_10_items}
                </ul>
            </div>
        </div>
    </div>
    """
