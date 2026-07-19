from analysis_agents.fundamental_agent import analyze_fundamentals


def test_analyze_fundamentals_maps_fields_from_fetch_result():
    fake_fetch = lambda ticker: {
        "ticker": ticker,
        "trailing_pe": 12.3,
        "price_to_book": 1.1,
        "dividend_yield": 0.02,
    }

    result = analyze_fundamentals("7203.T", fetch_fundamentals=fake_fetch)

    assert result == {"ticker": "7203.T", "per": 12.3, "pbr": 1.1, "dividend_yield": 0.02}
