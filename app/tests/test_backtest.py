import pandas as pd

from portfolio_management.backtest import (
    BACKTEST_PRESETS,
    run_backtest_comparison,
    run_ma_crossover_backtest,
)


def test_run_ma_crossover_backtest_shifts_signal_to_avoid_lookahead_bias():
    # short_window=1, long_window=2 のとき、
    # day2にクロスオーバーが発生するが、シグナルは1日ずらされるため
    # 実際にポジションを持つのはday3のみ（このday3のリターンは0）。
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.Series([100, 100, 102, 102], index=dates)

    result = run_ma_crossover_backtest(prices, short_window=1, long_window=2)

    assert result == {
        "total_return_pct": 0.0,
        "benchmark_return_pct": 2.0,
        "win_rate_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "trade_days": 1,
    }


def test_run_ma_crossover_backtest_applies_transaction_cost_on_position_change():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.Series([100, 100, 102, 102], index=dates)

    result = run_ma_crossover_backtest(
        prices, short_window=1, long_window=2, transaction_cost_pct=0.1
    )

    # 唯一のポジション変化日（day3のエントリー）に0.1%のコストが乗る。
    assert result["total_return_pct"] == -0.1
    assert result["max_drawdown_pct"] == -0.1
    assert result["benchmark_return_pct"] == 2.0
    assert result["trade_days"] == 1


def test_backtest_presets_are_short_and_standard():
    assert BACKTEST_PRESETS == [
        ("短期(5/25)", 5, 25),
        ("標準(25/75)", 25, 75),
    ]


def test_run_backtest_comparison_returns_result_per_preset_label():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.Series([100, 100, 102, 102], index=dates)

    result = run_backtest_comparison(prices, presets=[("A", 1, 2), ("B", 1, 2)])

    expected_single = {
        "total_return_pct": 0.0,
        "benchmark_return_pct": 2.0,
        "win_rate_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "trade_days": 1,
    }
    assert result == {"A": expected_single, "B": expected_single}
