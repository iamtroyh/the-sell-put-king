#!/usr/bin/env node
/**
 * generate-output-index.js
 * Scans the output/ directory for all HTML reports and generates/updates output/index.html.
 * Strictly respects the ground-truth investment signal verdict text in each report.
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const OUTPUT_DIR = path.join(ROOT, 'output');

function generateIndex() {
  if (!fs.existsSync(OUTPUT_DIR)) {
    fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  }

  const files = fs.readdirSync(OUTPUT_DIR).filter(f => f.endsWith('.html') && f !== 'index.html');

  const reports = files.map(file => {
    const filePath = path.join(OUTPUT_DIR, file);
    const stat = fs.statSync(filePath);
    const content = fs.readFileSync(filePath, 'utf8');

    // Extract title
    const titleMatch = content.match(/<title>(.*?)<\/title>/i);
    const title = titleMatch ? titleMatch[1].trim() : file;

    // Price integrity sanity check (detect truncated $ amounts due to shell expansion)
    const brokenPriceMatches = content.match(/(?:Strike|保本价|权利金|行权价|现价|支撑|阻力|止损|tier-val[^>]*>)\s*(\.\d{2})/gi);
    if (brokenPriceMatches) {
      console.warn(`⚠️ [WARNING] Possible truncated price detected in ${file}:`, brokenPriceMatches);
    }

    // Extract ticker from filename or title
    let ticker = 'REPORT';
    const filenameTickerMatch = file.match(/^([A-Z0-9\.]+)_/i) || file.match(/report-([A-Z0-9\.]+)-/i) || file.match(/-([A-Z0-9\.]+)-/);
    if (filenameTickerMatch) {
      ticker = filenameTickerMatch[1].toUpperCase();
    } else {
      const titleTickerMatch = title.match(/^([A-Z0-9\.]+){1,6}\b/);
      if (titleTickerMatch) ticker = titleTickerMatch[1].toUpperCase();
    }

    // Score extraction
    let score = null;
    const scoreMatch = content.match(/class="[^"]*signal-score[^"]*"[^>]*>\s*([\d\.]+)\s*\/\s*10/i) ||
                       content.match(/signal-score[^>]*>\s*([\d\.]+)\s*\/\s*10/i) ||
                       content.match(/Score:\s*([\d\.]+)\s*\/\s*10/i) ||
                       content.match(/(\d\.\d+)\s*\/\s*10/);
    if (scoreMatch) {
      score = parseFloat(scoreMatch[1]);
    }

    // Exact Signal Verdict Extraction (Ground Truth from Report HTML)
    let signalType = 'NEUTRAL';
    let signalText = '中立 (NEUTRAL)';

    const verdictMatch = content.match(/class="[^"]*signal-verdict[^"]*"[^>]*>([\s\S]*?)<\/(?:div|span)>/i) ||
                         content.match(/class="[^"]*signal-badge[^"]*"[^>]*>([\s\S]*?)<\/(?:div|span)>/i) ||
                         content.match(/class="[^"]*badge-hero-signal[^"]*"[^>]*>([\s\S]*?)<\/(?:div|span)>/i) ||
                         content.match(/sig-label">投资信号[^<]*<\/div>\s*<div class="sig-val"[^>]*>([\s\S]*?)<\/div>/i) ||
                         content.match(/signal-lbl">投资信号[^<]*<\/div>\s*<div class="signal-val"[^>]*>([\s\S]*?)<\/div>/i) ||
                         content.match(/<span class="hero-meta-label">投资结论[^<]*<\/span>\s*<span class="hero-meta-value"[^>]*>([\s\S]*?)<\/span>/i) ||
                         content.match(/signal-verdict[^>]*>([\s\S]*?)<\/div>/i);
    const actionMatch = content.match(/sig-label">投资建议[^<]*<\/(?:span|div)>\s*<(?:span|div) class="sig-val"[^>]*>([\s\S]*?)<\/(?:span|div)>/i) ||
                        content.match(/signal-lbl">操作建议[^<]*<\/(?:span|div)>\s*<(?:span|div) class="signal-val"[^>]*>([\s\S]*?)<\/(?:span|div)>/i) ||
                        content.match(/sig-label">执行操作[^<]*<\/(?:span|div)>\s*<(?:span|div) class="sig-val"[^>]*>([\s\S]*?)<\/(?:span|div)>/i) ||
                        content.match(/sig-label">Action[^<]*<\/(?:span|div)>\s*<(?:span|div) class="sig-val"[^>]*>([\s\S]*?)<\/(?:span|div)>/i);
    const heroMetaMatch = content.match(/<span class="hero-meta-value"[^>]*>([\s\S]*?)<\/span>/gi) ||
                          content.match(/<span class="badge badge-hero-signal"[^>]*>([\s\S]*?)<\/span>/gi);

    const verdictStr = verdictMatch ? verdictMatch[1].replace(/<[^>]+>/g, '').trim() : '';
    const actionStr = actionMatch ? actionMatch[1].replace(/<[^>]+>/g, '').trim() : '';
    const heroStr = heroMetaMatch ? heroMetaMatch.map(m => m.replace(/<[^>]+>/g, '')).join(' ') : '';

    const combinedStr = `${verdictStr} ${actionStr} ${heroStr}`;

    if (/强烈看多|strong buy|强烈买入|strong bullish/i.test(verdictStr) ||
        /强烈看多|strong buy|强烈买入|strong bullish/i.test(actionStr) ||
        /强烈看多|strong buy|强烈买入|strong bullish/i.test(heroStr)) {
      signalType = 'STRONG_BUY';
      signalText = '强烈看多 (STRONG BUY)';
    } else if (/看多|bullish/i.test(verdictStr) || /买入|buy/i.test(verdictStr) ||
               /看多|bullish/i.test(actionStr) || /买入|buy/i.test(actionStr)) {
      signalType = 'BULLISH';
      signalText = '看多 (BULLISH)';
    } else if (/强烈看空|strong sell|强烈卖出|strong bearish/i.test(verdictStr) ||
               /强烈看空|strong sell|强烈卖出|strong bearish/i.test(actionStr) ||
               /强烈看空|strong sell|强烈卖出|strong bearish/i.test(heroStr)) {
      signalType = 'STRONG_SELL';
      signalText = '强烈看空 (STRONG SELL)';
    } else if (/看空|bearish|卖出|sell/i.test(verdictStr) || /减持|卖出|sell/i.test(actionStr)) {
      signalType = 'BEARISH';
      signalText = '看空 (BEARISH)';
    } else if (/中立|neutral|持有|hold/i.test(verdictStr) || /中立|neutral|持有|hold/i.test(actionStr)) {
      signalType = 'NEUTRAL';
      signalText = '中立 (NEUTRAL)';
    } else if (/strong buy|强烈看多|强烈买入/i.test(combinedStr)) {
      signalType = 'STRONG_BUY';
      signalText = '强烈看多 (STRONG BUY)';
    } else if (/bullish|看多/i.test(combinedStr)) {
      signalType = 'BULLISH';
      signalText = '看多 (BULLISH)';
    } else if (/strong sell|强烈看空|强烈卖出/i.test(combinedStr)) {
      signalType = 'STRONG_SELL';
      signalText = '强烈看空 (STRONG SELL)';
    } else if (/bearish|看空/i.test(combinedStr)) {
      signalType = 'BEARISH';
      signalText = '看空 (BEARISH)';
    }

    // Extract Date
    const dateMatch = file.match(/(\d{4}-\d{2}-\d{2})/);
    const dateStr = dateMatch ? dateMatch[1] : stat.mtime.toISOString().split('T')[0];

    const sizeKB = (stat.size / 1024).toFixed(1);

    return {
      filename: file,
      title,
      ticker,
      signalType,
      signalText,
      score: score !== null ? score.toFixed(1) : null,
      date: dateStr,
      mtimeMs: stat.mtimeMs,
      sizeKB
    };
  });

  // Sort by report date descending (YYYY-MM-DD), then mtimeMs descending, then Ticker
  reports.sort((a, b) => {
    if (a.date !== b.date) {
      return b.date.localeCompare(a.date);
    }
    if (b.mtimeMs !== a.mtimeMs) {
      return b.mtimeMs - a.mtimeMs;
    }
    return a.ticker.localeCompare(b.ticker);
  });

  const uniqueTickers = [...new Set(reports.map(r => r.ticker))].filter(t => t !== 'REPORT');
  const nowStr = new Date().toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' });

  const strongBuyCount = reports.filter(r => r.signalType === 'STRONG_BUY').length;
  const bullishCount = reports.filter(r => r.signalType === 'BULLISH').length;
  const neutralCount = reports.filter(r => r.signalType === 'NEUTRAL').length;
  const bearishCount = reports.filter(r => r.signalType === 'BEARISH' || r.signalType === 'STRONG_SELL').length;

  const reportsRows = reports.map(r => {
    let badgeClass = 'badge-neutral';
    let rowClass = '';
    let tickerClass = '';
    let btnClass = '';
    let iconPrefix = '';
    let displaySignal = r.signalText;

    if (r.signalType === 'STRONG_BUY') {
      badgeClass = 'badge-strong-buy';
      rowClass = 'row-strong-buy';
      tickerClass = 'ticker-strong-buy';
      btnClass = 'btn-strong-buy';
      iconPrefix = '🚀 ';
    } else if (r.signalType === 'BULLISH') {
      badgeClass = 'badge-bullish';
      iconPrefix = '🟢 ';
    } else if (r.signalType === 'NEUTRAL') {
      badgeClass = 'badge-neutral';
      iconPrefix = '🟡 ';
    } else if (r.signalType === 'BEARISH') {
      badgeClass = 'badge-bearish';
      iconPrefix = '🔴 ';
    } else if (r.signalType === 'STRONG_SELL') {
      badgeClass = 'badge-strong-sell';
      rowClass = 'row-strong-sell';
      iconPrefix = '⛔ ';
    }

    let fullDisplay = `${iconPrefix}${displaySignal}`;
    if (r.score) {
      fullDisplay += ` • ${r.score}/10`;
    }

    return `
        <tr class="report-row ${rowClass}" data-signal-type="${r.signalType}" data-search="${(r.ticker + ' ' + r.title + ' ' + r.filename + ' ' + r.date + ' ' + r.signalText + ' ' + r.signalType).toLowerCase()}">
          <td><span class="ticker-pill ${tickerClass}">${r.ticker}</span></td>
          <td>
            <a href="./${r.filename}" class="report-title-link">${escapeHtml(r.title)}</a>
            <div class="file-name">${r.filename} (${r.sizeKB} KB)</div>
          </td>
          <td><span class="badge ${badgeClass}">${fullDisplay}</span></td>
          <td>${r.date}</td>
          <td style="text-align: right;">
            <a href="./${r.filename}" class="open-btn ${btnClass}">View Report &rarr;</a>
          </td>
        </tr>`;
  }).join('\n');

  const htmlContent = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0, viewport-fit=cover">
  <meta name="format-detection" content="telephone=no">
  <title>InvestSkill — 报告目录与信号索引 (Reports Directory)</title>
  <style>
    :root {
      --bg-color: #0f172a;
      --card-bg: #1e293b;
      --card-border: #334155;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --primary-blue: #38bdf8;
      --accent-navy: #1e3a8a;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--bg-color);
      color: var(--text-main);
      min-height: 100vh;
      padding-bottom: 3rem;
    }
    .header {
      background: linear-gradient(135deg, #0f172a 0%, #064e3b 40%, #1e3a8a 100%);
      padding: 3rem 2rem;
      border-bottom: 1px solid var(--card-border);
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
    }
    .header-content {
      max-width: 1200px;
      margin: 0 auto;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 1.5rem;
    }
    .header h1 {
      font-size: 2.2rem;
      font-weight: 700;
      color: #ffffff;
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }
    .header p {
      color: #a7f3d0;
      margin-top: 0.5rem;
      font-size: 1.05rem;
    }
    .stats-bar {
      display: flex;
      gap: 1rem;
      flex-wrap: wrap;
    }
    .stat-card {
      background: rgba(15, 23, 42, 0.65);
      border: 1px solid rgba(255, 255, 255, 0.12);
      padding: 0.85rem 1.25rem;
      border-radius: 10px;
      backdrop-filter: blur(8px);
      transition: all 0.2s ease;
    }
    .stat-card-strong-buy {
      background: linear-gradient(135deg, rgba(6, 78, 59, 0.6) 0%, rgba(4, 120, 87, 0.35) 100%);
      border: 1px solid #10b981;
      cursor: pointer;
      box-shadow: 0 0 14px rgba(16, 185, 129, 0.25);
    }
    .stat-card-strong-buy:hover {
      transform: translateY(-2px);
      box-shadow: 0 0 20px rgba(52, 211, 153, 0.45);
      border-color: #34d399;
    }
    .stat-val {
      font-size: 1.5rem;
      font-weight: 700;
      color: #34d399;
    }
    .stat-lbl {
      font-size: 0.8rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .container {
      max-width: 1200px;
      margin: 2rem auto;
      padding: 0 1.5rem;
    }
    .search-box {
      margin-bottom: 1rem;
    }
    .search-input {
      width: 100%;
      padding: 0.85rem 1.25rem;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      color: var(--text-main);
      font-size: 1rem;
      outline: none;
      transition: border-color 0.2s;
    }
    .search-input:focus {
      border-color: var(--primary-blue);
    }

    /* ── QUICK FILTER TABS ── */
    .filter-tabs {
      display: flex;
      gap: 0.6rem;
      margin-bottom: 1.5rem;
      flex-wrap: wrap;
    }
    .filter-pill {
      padding: 0.45rem 0.95rem;
      border-radius: 20px;
      font-size: 0.85rem;
      font-weight: 600;
      background: rgba(30, 41, 59, 0.7);
      border: 1px solid var(--card-border);
      color: var(--text-muted);
      cursor: pointer;
      transition: all 0.2s;
    }
    .filter-pill:hover {
      background: rgba(51, 65, 85, 0.9);
      color: #fff;
    }
    .filter-pill.active {
      background: var(--accent-navy);
      border-color: var(--primary-blue);
      color: #fff;
    }
    .filter-pill-strong-buy {
      background: linear-gradient(135deg, rgba(6, 78, 59, 0.6) 0%, rgba(4, 120, 87, 0.4) 100%);
      border-color: #059669;
      color: #34d399;
    }
    .filter-pill-strong-buy:hover, .filter-pill-strong-buy.active {
      background: linear-gradient(135deg, #047857 0%, #10b981 100%);
      border-color: #34d399;
      color: #ffffff;
      box-shadow: 0 0 12px rgba(16, 185, 129, 0.5);
    }

    .table-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      overflow: hidden;
      box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      text-align: left;
    }
    th {
      background: rgba(15, 23, 42, 0.5);
      padding: 1rem 1.25rem;
      font-size: 0.85rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      border-bottom: 1px solid var(--card-border);
    }
    td {
      padding: 1.1rem 1.25rem;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
      vertical-align: middle;
      transition: background 0.15s ease;
    }
    tr:last-child td {
      border-bottom: none;
    }
    tr:hover td {
      background: rgba(255, 255, 255, 0.02);
    }

    /* ── STRONG BUY ROW HIGHLIGHT ── */
    .row-strong-buy {
      background: linear-gradient(90deg, rgba(16, 185, 129, 0.09) 0%, rgba(30, 41, 59, 0.4) 60%);
      border-left: 4px solid #10b981;
    }
    .row-strong-buy:hover td {
      background: linear-gradient(90deg, rgba(16, 185, 129, 0.16) 0%, rgba(30, 41, 59, 0.85) 100%) !important;
    }

    .ticker-pill {
      background: #0284c7;
      color: white;
      font-weight: 700;
      padding: 0.35rem 0.75rem;
      border-radius: 6px;
      font-size: 0.9rem;
      display: inline-block;
      letter-spacing: 0.5px;
    }
    .ticker-strong-buy {
      background: linear-gradient(135deg, #047857 0%, #10b981 100%) !important;
      box-shadow: 0 0 10px rgba(16, 185, 129, 0.45);
      border: 1px solid #34d399;
      font-weight: 800;
    }

    .report-title-link {
      color: var(--text-main);
      text-decoration: none;
      font-weight: 600;
      font-size: 1.05rem;
    }
    .report-title-link:hover {
      color: var(--primary-blue);
      text-decoration: underline;
    }
    .file-name {
      font-size: 0.82rem;
      color: var(--text-muted);
      margin-top: 0.25rem;
      font-family: monospace;
    }

    /* ── DYNAMIC GRADIENT SIGNAL BADGES ── */
    .badge {
      padding: 0.4rem 0.8rem;
      border-radius: 6px;
      font-size: 0.82rem;
      font-weight: 700;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      letter-spacing: 0.3px;
    }

    /* 强烈看多 (Strong Bullish / Strong Buy) -> 动态呼吸发光 + 翡翠绿渐变 */
    @keyframes strongBuyPulse {
      0%, 100% {
        box-shadow: 0 0 10px rgba(16, 185, 129, 0.4), 0 0 20px rgba(5, 150, 105, 0.2);
        border-color: #34d399;
      }
      50% {
        box-shadow: 0 0 18px rgba(52, 211, 153, 0.85), 0 0 32px rgba(16, 185, 129, 0.5);
        border-color: #a7f3d0;
      }
    }
    .badge-strong-buy {
      background: linear-gradient(135deg, #064e3b 0%, #047857 50%, #059669 100%);
      color: #ffffff !important;
      border: 1.5px solid #34d399;
      animation: strongBuyPulse 2.5s infinite ease-in-out;
      text-shadow: 0 0 8px rgba(52, 211, 153, 0.7);
      font-weight: 800;
      padding: 0.45rem 0.9rem;
      font-size: 0.86rem;
    }

    /* 看多 (Bullish / Buy) -> 中等青绿色 */
    .badge-bullish {
      background: rgba(16, 185, 129, 0.18);
      color: #6ee7b7;
      border: 1px solid #059669;
    }
    /* 中立 (Neutral / Hold) -> 琥珀金黄色 */
    .badge-neutral {
      background: rgba(245, 158, 11, 0.2);
      color: #fbbf24;
      border: 1px solid #d97706;
    }
    /* 看空 (Bearish / Sell) -> 橙红色 */
    .badge-bearish {
      background: rgba(239, 68, 68, 0.2);
      color: #fca5a5;
      border: 1px solid #dc2626;
    }
    /* 强烈看空 (Strong Bearish / Strong Sell) -> 深红发光渐变 */
    .badge-strong-sell {
      background: linear-gradient(135deg, rgba(185, 28, 28, 0.45) 0%, rgba(239, 68, 68, 0.3) 100%);
      color: #f87171;
      border: 1px solid #ef4444;
      box-shadow: 0 0 10px rgba(239, 68, 68, 0.35);
    }

    .open-btn {
      display: inline-block;
      padding: 0.5rem 1rem;
      background: var(--accent-navy);
      color: white;
      text-decoration: none;
      border-radius: 8px;
      font-size: 0.9rem;
      font-weight: 600;
      border: 1px solid var(--primary-blue);
      transition: all 0.2s;
    }
    .open-btn:hover {
      background: var(--primary-blue);
      color: #0f172a;
    }
    .btn-strong-buy {
      background: linear-gradient(135deg, #047857, #059669) !important;
      border: 1px solid #34d399 !important;
      color: #ecfdf5 !important;
      font-weight: 700;
      box-shadow: 0 0 10px rgba(16, 185, 129, 0.35);
    }
    .btn-strong-buy:hover {
      background: #10b981 !important;
      color: #022c22 !important;
      box-shadow: 0 0 18px rgba(52, 211, 153, 0.8);
      transform: translateY(-1px);
    }

    .table-scroll {
      width: 100%;
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }
    .footer {
      text-align: center;
      margin-top: 3rem;
      color: var(--text-muted);
      font-size: 0.85rem;
    }
    @media (max-width: 768px) {
      .header { padding: 2rem 1rem; }
      .header h1 { font-size: 1.5rem; }
      .header p { font-size: 0.9rem; }
      .header-content { flex-direction: column; align-items: flex-start; gap: 1rem; }
      .stats-bar { width: 100%; justify-content: flex-start; gap: 0.5rem; }
      .stat-card { flex: 1; min-width: 105px; padding: 0.6rem 0.8rem; }
      .container { padding: 0 1rem; margin: 1.25rem auto; }
      .search-input { padding: 0.75rem 1rem; font-size: 0.95rem; }
      .filter-tabs { gap: 0.4rem; margin-bottom: 1rem; }
      .filter-pill { font-size: 0.78rem; padding: 0.35rem 0.7rem; }
      th, td { padding: 0.75rem 0.6rem; }
      .ticker-pill { font-size: 0.8rem; padding: 0.25rem 0.5rem; }
      .report-title-link { font-size: 0.95rem; }
      .file-name { font-size: 0.75rem; }
      .badge { font-size: 0.75rem; padding: 0.3rem 0.5rem; }
      .open-btn { font-size: 0.8rem; padding: 0.35rem 0.65rem; }
    }
  </style>
</head>
<body>

  <div class="header">
    <div class="header-content">
      <div>
        <h1>📊 InvestSkill 报告与信号动态索引目录</h1>
        <p>动态索引美股研究报告、多因子综合得分与信号颜色渐变 (Dynamic Index of Stock Research Reports)</p>
      </div>
      <div class="stats-bar">
        <div class="stat-card">
          <div class="stat-val">${reports.length}</div>
          <div class="stat-lbl">Total Reports</div>
        </div>
        <div class="stat-card">
          <div class="stat-val">${uniqueTickers.length}</div>
          <div class="stat-lbl">Tickers</div>
        </div>
        <div class="stat-card stat-card-strong-buy" onclick="filterBySignal('STRONG_BUY')" title="点击速查强烈看多研报">
          <div class="stat-val">🚀 ${strongBuyCount}</div>
          <div class="stat-lbl" style="color: #6ee7b7; font-weight:700;">Strong Buy</div>
        </div>
      </div>
    </div>
  </div>

  <div class="container">
    <div class="search-box">
      <input type="text" id="searchInput" class="search-input" placeholder="🔍 搜索股票代码、标题、信号或日期 (Search by ticker, title, signal...)" onkeyup="applyFilter()">
    </div>

    <div class="filter-tabs">
      <button class="filter-pill active" data-filter="ALL" onclick="setSignalFilter('ALL', this)">🌟 全部 (${reports.length})</button>
      <button class="filter-pill filter-pill-strong-buy" data-filter="STRONG_BUY" onclick="setSignalFilter('STRONG_BUY', this)">🚀 强烈看多 (${strongBuyCount})</button>
      <button class="filter-pill" data-filter="BULLISH" onclick="setSignalFilter('BULLISH', this)">🟢 看多 (${bullishCount})</button>
      <button class="filter-pill" data-filter="NEUTRAL" onclick="setSignalFilter('NEUTRAL', this)">🟡 中立 (${neutralCount})</button>
      <button class="filter-pill" data-filter="BEARISH" onclick="setSignalFilter('BEARISH', this)">🔴 看空 (${bearishCount})</button>
    </div>

    <div class="table-card">
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Report Title / File</th>
              <th>Signal & Score (投资信号与得分)</th>
              <th>Generated Date</th>
              <th style="text-align: right;">Action</th>
            </tr>
          </thead>
          <tbody id="reportsTable">
            ${reportsRows.length > 0 ? reportsRows : '<tr><td colspan="5" style="text-align:center; color: var(--text-muted);">No reports found in output/ directory.</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>

    <div class="footer">
      Generated automatically by InvestSkill Engine • Last updated: ${nowStr}
    </div>
  </div>

  <script>
    let activeSignalFilter = 'ALL';

    function setSignalFilter(filterType, btn) {
      activeSignalFilter = filterType;
      document.querySelectorAll('.filter-pill').forEach(el => el.classList.remove('active'));
      if (btn) btn.classList.add('active');
      applyFilter();
    }

    function filterBySignal(sig) {
      const btn = document.querySelector(\`.filter-pill[data-filter="\${sig}"]\`);
      setSignalFilter(sig, btn);
    }

    function applyFilter() {
      const q = document.getElementById('searchInput').value.toLowerCase().trim();
      const rows = document.querySelectorAll('.report-row');

      rows.forEach(row => {
        const text = row.getAttribute('data-search') || '';
        const sigType = row.getAttribute('data-signal-type') || '';

        const matchesQuery = !q || text.includes(q);
        let matchesSignal = true;

        if (activeSignalFilter === 'STRONG_BUY') {
          matchesSignal = (sigType === 'STRONG_BUY');
        } else if (activeSignalFilter === 'BULLISH') {
          matchesSignal = (sigType === 'BULLISH');
        } else if (activeSignalFilter === 'NEUTRAL') {
          matchesSignal = (sigType === 'NEUTRAL');
        } else if (activeSignalFilter === 'BEARISH') {
          matchesSignal = (sigType === 'BEARISH' || sigType === 'STRONG_SELL');
        }

        if (matchesQuery && matchesSignal) {
          row.style.display = '';
        } else {
          row.style.display = 'none';
        }
      });
    }
  </script>
</body>
</html>`;

  const outputPath = path.join(OUTPUT_DIR, 'index.html');
  fs.writeFileSync(outputPath, htmlContent, 'utf8');
  console.log(`Successfully generated ${outputPath} with ${reports.length} report(s).`);
}

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

if (require.main === module) {
  generateIndex();
}

module.exports = { generateIndex };
