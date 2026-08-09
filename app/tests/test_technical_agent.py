import pandas as pd
import pytest

from analysis_agents.technical_agent import analyze_technical


def _close_only_ohlcv(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": [1000] * len(closes),
        }
    )


def test_analyze_technical_signals_bullish_on_uptrend():
    prices = _close_only_ohlcv([100, 101, 102, 103, 104, 105, 106, 107, 108, 109])
    result = analyze_technical(prices, short_window=2, long_window=5)
    assert result["signal"] == "強気"


def test_analyze_technical_returns_insufficient_data_when_too_short():
    prices = _close_only_ohlcv([100, 101])
    result = analyze_technical(prices, short_window=2, long_window=5)
    assert result["signal"] == "データ不足"
    assert result["ma_short"] is None
    assert result["ma_long"] is None


def _flat_ohlcv(days: int, day_range: float = 2.0, close: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [close] * days,
            "High": [close + day_range / 2] * days,
            "Low": [close - day_range / 2] * days,
            "Close": [close] * days,
            "Volume": [1000] * days,
        }
    )


def _uptrend_ohlcv(days: int, day_range: float = 1.0, start: float = 100.0) -> pd.DataFrame:
    high = [start + i + day_range for i in range(days)]
    low = [start + i for i in range(days)]
    close = [start + i + day_range for i in range(days)]
    return pd.DataFrame(
        {
            "Open": close,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": [1000] * days,
        }
    )


def _downtrend_ohlcv(days: int, day_range: float = 1.0, start: float = 200.0) -> pd.DataFrame:
    high = [start - i for i in range(days)]
    low = [start - i - day_range for i in range(days)]
    close = [start - i - day_range for i in range(days)]
    return pd.DataFrame(
        {
            "Open": close,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": [1000] * days,
        }
    )


class TestRSI:
    def test_reaches_100_on_pure_uptrend(self):
        prices = _uptrend_ohlcv(days=16)
        result = analyze_technical(prices, rsi_period=14)
        assert result["rsi"] == pytest.approx(100.0)
        assert result["rsi_signal"] == "買われすぎ"

    def test_reaches_0_on_pure_downtrend(self):
        prices = _downtrend_ohlcv(days=16)
        result = analyze_technical(prices, rsi_period=14)
        assert result["rsi"] == pytest.approx(0.0)
        assert result["rsi_signal"] == "売られすぎ"

    def test_insufficient_data(self):
        prices = _flat_ohlcv(days=3)
        result = analyze_technical(prices, rsi_period=14)
        assert result["rsi"] is None
        assert result["rsi_signal"] == "データ不足"

    def test_series_matches_scalar_and_length(self):
        prices = _uptrend_ohlcv(days=16)
        result = analyze_technical(prices, rsi_period=14)
        assert len(result["rsi_series"]) == len(prices)
        assert result["rsi_series"][-1] == result["rsi"]
        assert result["rsi_series"][0] is None


class TestATR:
    def test_calculates_constant_true_range(self):
        prices = _flat_ohlcv(days=16, day_range=2.0, close=100.0)
        result = analyze_technical(prices, atr_period=14)
        assert result["atr"] == pytest.approx(2.0)
        assert result["atr_pct"] == pytest.approx(2.0)
        assert result["atr_signal"] == "中程度"

    def test_signals_high_volatility(self):
        prices = _flat_ohlcv(days=16, day_range=5.0, close=100.0)
        result = analyze_technical(prices, atr_period=14)
        assert result["atr_signal"] == "高ボラティリティ"

    def test_signals_low_volatility(self):
        prices = _flat_ohlcv(days=16, day_range=0.2, close=100.0)
        result = analyze_technical(prices, atr_period=14)
        assert result["atr_signal"] == "低ボラティリティ"

    def test_insufficient_data(self):
        prices = _flat_ohlcv(days=3)
        result = analyze_technical(prices, atr_period=14)
        assert result["atr"] is None
        assert result["atr_signal"] == "データ不足"

    def test_series_matches_scalar_and_length(self):
        prices = _flat_ohlcv(days=16, day_range=2.0, close=100.0)
        result = analyze_technical(prices, atr_period=14)
        assert len(result["atr_pct_series"]) == len(prices)
        assert result["atr_pct_series"][-1] == result["atr_pct"]
        assert result["atr_pct_series"][0] is None


class TestADX:
    def test_reaches_100_on_pure_directional_trend(self):
        prices = _uptrend_ohlcv(days=25, day_range=1.0)
        result = analyze_technical(prices, adx_period=5)
        assert result["adx"] == pytest.approx(100.0)
        assert result["adx_signal"] == "強いトレンド"

    def test_signals_range_bound_market_on_zigzag(self):
        days = 30
        high = []
        low = []
        close = []
        price = 100.0
        for i in range(days):
            step = 1.0 if i % 2 == 0 else -1.0
            price += step
            high.append(price + 0.5)
            low.append(price - 0.5)
            close.append(price)
        prices = pd.DataFrame(
            {"Open": close, "High": high, "Low": low, "Close": close, "Volume": [1000] * days}
        )
        result = analyze_technical(prices, adx_period=5)
        assert result["adx"] < 20
        assert result["adx_signal"] == "レンジ相場"

    def test_series_matches_scalar_and_length(self):
        prices = _uptrend_ohlcv(days=25, day_range=1.0)
        result = analyze_technical(prices, adx_period=5)
        assert len(result["adx_series"]) == len(prices)
        assert result["adx_series"][-1] == result["adx"]
        assert result["adx_series"][0] is None

    def test_insufficient_data(self):
        prices = _flat_ohlcv(days=3)
        result = analyze_technical(prices, adx_period=14)
        assert result["adx"] is None
        assert result["adx_signal"] == "データ不足"


class TestOBV:
    def test_calculates_cumulative_volume_and_rising_signal(self):
        prices = pd.DataFrame(
            {
                "Open": [100, 102, 101, 101, 103],
                "High": [100, 102, 101, 101, 103],
                "Low": [100, 102, 101, 101, 103],
                "Close": [100, 102, 101, 101, 103],
                "Volume": [1000, 1500, 800, 500, 1200],
            }
        )
        result = analyze_technical(prices, obv_period=2)
        assert result["obv"] == pytest.approx(1900.0)
        assert result["obv_signal"] == "増加傾向"

    def test_signals_falling_on_declining_volume_trend(self):
        prices = pd.DataFrame(
            {
                "Open": [103, 101, 101, 102, 100],
                "High": [103, 101, 101, 102, 100],
                "Low": [103, 101, 101, 102, 100],
                "Close": [103, 101, 101, 102, 100],
                "Volume": [1000, 1500, 800, 500, 1200],
            }
        )
        result = analyze_technical(prices, obv_period=2)
        assert result["obv_signal"] == "減少傾向"

    def test_insufficient_data(self):
        prices = _flat_ohlcv(days=2)
        result = analyze_technical(prices, obv_period=5)
        assert result["obv"] is None
        assert result["obv_signal"] == "データ不足"
