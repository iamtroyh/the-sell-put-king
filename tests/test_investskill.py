# -*- coding: utf-8 -*-
"""Unit tests for option_quant.investskill module."""

import os
import tempfile
from option_quant.investskill import scan_investskill_reports


def test_scan_investskill_reports():
    with tempfile.TemporaryDirectory() as tmp_dir:
        report_file = os.path.join(tmp_dir, "AAPL_report_2026-08-10.html")
        mock_html = """
        <!DOCTYPE html>
        <html>
        <body>
            <span class="hero-meta-label">多因子综合评分</span>
            <span class="hero-meta-value">8.5</span>
            <span class="hero-meta-label">投资结论</span>
            <span class="hero-meta-value">🚀 Strong Buy</span>
            <strong>核心投资逻辑：</strong>苹果生态护城河宽广，服务性收入持续高增。</p>
        </body>
        </html>
        """
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(mock_html)

        reports = scan_investskill_reports(output_dir=tmp_dir, max_age_days=10, current_date_str="2026-08-15")
        assert "AAPL" in reports
        assert reports["AAPL"]["score"] == 8.5
        assert "Strong Buy" in reports["AAPL"]["verdict"]
        assert reports["AAPL"]["is_stale"] is False
