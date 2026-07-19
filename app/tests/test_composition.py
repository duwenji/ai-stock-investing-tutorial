from portfolio_management.composition import analyze_portfolio_composition


def test_analyze_portfolio_composition_computes_weight_and_pnl():
    holdings = [
        {"ticker": "AAA", "shares": 100, "cost": 1000.0},
        {"ticker": "BBB", "shares": 50, "cost": 2000.0},
    ]
    current_prices = {"AAA": 1100.0, "BBB": 1900.0}

    result = analyze_portfolio_composition(holdings, current_prices)

    aaa = next(r for r in result["holdings"] if r["ticker"] == "AAA")
    bbb = next(r for r in result["holdings"] if r["ticker"] == "BBB")
    assert aaa["value"] == 110000.0
    assert bbb["value"] == 95000.0
    assert result["total_value"] == 205000.0
    assert aaa["pnl"] == 10000.0
    assert bbb["pnl"] == -5000.0
    assert round(aaa["weight_pct"], 1) == round(110000 / 205000 * 100, 1)


def test_analyze_portfolio_composition_handles_missing_price():
    holdings = [{"ticker": "CCC", "shares": 10, "cost": 500.0}]
    result = analyze_portfolio_composition(holdings, {})
    ccc = result["holdings"][0]
    assert ccc["current_price"] is None
    assert ccc["value"] is None
    assert ccc["pnl"] is None
    assert ccc["weight_pct"] is None
