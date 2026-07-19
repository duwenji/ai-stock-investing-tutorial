import pandas as pd

from portfolio_management.risk import assess_risk


def test_assess_risk_identical_series_have_correlation_one():
    dates = pd.date_range("2026-01-01", periods=10, freq="D")
    series_a = pd.Series(
        [100, 101, 102, 101, 103, 104, 103, 105, 106, 107], index=dates
    )
    series_b = series_a.copy()

    result = assess_risk({"AAA": series_a, "BBB": series_b})

    assert result["correlation"]["AAA"]["BBB"] == 1.0


def test_assess_risk_returns_volatility_for_each_ticker():
    dates = pd.date_range("2026-01-01", periods=10, freq="D")
    series_a = pd.Series(
        [100, 101, 102, 101, 103, 104, 103, 105, 106, 107], index=dates
    )

    result = assess_risk({"AAA": series_a})

    assert "AAA" in result["volatility_pct"]
    assert result["volatility_pct"]["AAA"] > 0
