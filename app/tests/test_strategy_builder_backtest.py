import pandas as pd

from strategy_builder.backtest import run_strategy_backtest


def test_run_strategy_backtest_computes_equal_weight_return_and_flat_drawdown():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    prices_by_ticker = {
        "AAA.T": pd.Series([100.0, 110.0, 121.0], index=dates),
        "BBB.T": pd.Series([50.0, 50.0, 55.0], index=dates),
    }
    result = run_strategy_backtest(prices_by_ticker)
    assert result["total_return_pct"] == 15.5
    assert result["max_drawdown_pct"] == 0.0
    assert result["win_rate_pct"] == 100.0
    assert result["ticker_returns"] == {"AAA.T": 21.0, "BBB.T": 10.0}
    assert result["equity_curve"].tolist() == [100.0, 105.0, 115.5]


def test_run_strategy_backtest_computes_max_drawdown_for_single_ticker_dip():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices_by_ticker = {"AAA.T": pd.Series([100.0, 130.0, 90.0, 120.0], index=dates)}
    result = run_strategy_backtest(prices_by_ticker)
    assert result["total_return_pct"] == 20.0
    assert result["max_drawdown_pct"] == -30.77
    assert result["win_rate_pct"] == 100.0


def test_run_strategy_backtest_handles_staggered_start_dates():
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    prices_by_ticker = {
        "AAA.T": pd.Series([100.0] * 5, index=dates),
        "BBB.T": pd.Series([50.0, 55.0, 60.0], index=dates[2:]),
    }
    result = run_strategy_backtest(prices_by_ticker)
    assert result["equity_curve"].tolist() == [100.0, 100.0, 100.0, 105.0, 110.0]
    assert result["ticker_returns"] == {"AAA.T": 0.0, "BBB.T": 20.0}
    assert result["win_rate_pct"] == 50.0


def test_run_strategy_backtest_returns_zeroed_result_for_empty_input():
    result = run_strategy_backtest({})
    assert result["total_return_pct"] == 0.0
    assert result["max_drawdown_pct"] == 0.0
    assert result["win_rate_pct"] == 0.0
    assert result["equity_curve"].empty
    assert result["ticker_returns"] == {}


def test_run_strategy_backtest_skips_ticker_with_insufficient_data():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    prices_by_ticker = {
        "AAA.T": pd.Series([100.0, 110.0, 121.0], index=dates),
        "SHORT.T": pd.Series([10.0], index=dates[:1]),
    }
    result = run_strategy_backtest(prices_by_ticker)
    assert "SHORT.T" not in result["ticker_returns"]
