# -*- coding: utf-8 -*-
"""Unit tests for option_quant.portfolio module."""

import datetime
from option_quant.portfolio import calculate_portfolio_delta_exposure, get_wash_sale_risks


def test_calculate_portfolio_delta_exposure():
    res = calculate_portfolio_delta_exposure(spot_prices={"AAPL": 200.0, "NVDA": 120.0})
    assert "total_delta_notional" in res
    assert "leverage_ratio" in res
    assert "status_label" in res
    assert isinstance(res["positions"], list)


def test_wash_sale_risks():
    today = datetime.date.today()
    wash_map, floating_loss = get_wash_sale_risks(today=today)
    assert isinstance(wash_map, dict)
    assert isinstance(floating_loss, list)
