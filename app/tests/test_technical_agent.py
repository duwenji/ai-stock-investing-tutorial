import pandas as pd

from analysis_agents.technical_agent import analyze_technical


def test_analyze_technical_signals_bullish_on_uptrend():
    prices = pd.DataFrame({"Close": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109]})
    result = analyze_technical(prices, short_window=2, long_window=5)
    assert result["signal"] == "強気"


def test_analyze_technical_returns_insufficient_data_when_too_short():
    prices = pd.DataFrame({"Close": [100, 101]})
    result = analyze_technical(prices, short_window=2, long_window=5)
    assert result["signal"] == "データ不足"
    assert result["ma_short"] is None
    assert result["ma_long"] is None
