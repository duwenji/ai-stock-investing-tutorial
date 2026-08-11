import pandas as pd

import strategy_builder.pipeline_functions as pipeline_functions


def test_run_backtest_rank_adds_source_strategy_and_sorts_by_risk_adjusted_return(
    monkeypatch, tmp_path
):
    dates = pd.date_range("2026-01-01", periods=90, freq="D")

    def fake_fetch(tickers, period):
        return {
            "AAA.T": pd.Series(range(100, 190), index=dates, dtype=float),
            "BBB.T": pd.Series([100.0] * 90, index=dates, dtype=float),
        }

    monkeypatch.setattr(pipeline_functions, "fetch_universe_price_histories", fake_fetch)

    candidates_df = pd.DataFrame({"ticker": ["AAA.T", "BBB.T"]})
    result_df = pipeline_functions._run_backtest_rank(
        candidates_df, {"strategy": "移動平均クロスオーバー", "period": "1y"}, tmp_path
    )

    assert set(result_df["_source_strategy"]) == {"移動平均クロスオーバー"}
    assert result_df["risk_adjusted_return"].is_monotonic_decreasing


def test_run_backtest_rank_applies_top_n(monkeypatch, tmp_path):
    dates = pd.date_range("2026-01-01", periods=20, freq="D")

    def fake_fetch(tickers, period):
        return {t: pd.Series(range(100, 120), index=dates, dtype=float) for t in tickers}

    monkeypatch.setattr(pipeline_functions, "fetch_universe_price_histories", fake_fetch)
    monkeypatch.setattr(
        pipeline_functions,
        "STRATEGIES",
        {
            "テスト戦略": {
                "func": lambda prices, transaction_cost_pct=0.0, **p: {
                    "total_return_pct": 1.0, "benchmark_return_pct": 0.0,
                    "win_rate_pct": 100.0, "max_drawdown_pct": -1.0, "trade_days": 1,
                },
                "param_grid": {"x": [1]},
                "min_days": 1,
            }
        },
    )

    candidates_df = pd.DataFrame({"ticker": ["AAA.T", "BBB.T", "CCC.T"]})
    result_df = pipeline_functions._run_backtest_rank(
        candidates_df, {"strategy": "テスト戦略", "top_n": 2}, tmp_path
    )

    assert len(result_df) == 2


def test_run_backtest_rank_raises_for_unknown_strategy(tmp_path):
    candidates_df = pd.DataFrame({"ticker": ["AAA.T"]})
    try:
        pipeline_functions._run_backtest_rank(candidates_df, {"strategy": "存在しない戦略"}, tmp_path)
        assert False, "ValueErrorが送出されるべき"
    except ValueError:
        pass


def test_run_backtest_rank_reuses_cache_on_second_call(monkeypatch, tmp_path):
    dates = pd.date_range("2026-01-01", periods=20, freq="D")
    call_count = {"n": 0}

    def fake_fetch(tickers, period):
        call_count["n"] += 1
        return {t: pd.Series(range(100, 120), index=dates, dtype=float) for t in tickers}

    monkeypatch.setattr(pipeline_functions, "fetch_universe_price_histories", fake_fetch)
    monkeypatch.setattr(
        pipeline_functions,
        "STRATEGIES",
        {
            "テスト戦略": {
                "func": lambda prices, transaction_cost_pct=0.0, **p: {
                    "total_return_pct": 1.0, "benchmark_return_pct": 0.0,
                    "win_rate_pct": 100.0, "max_drawdown_pct": -1.0, "trade_days": 1,
                },
                "param_grid": {"x": [1]},
                "min_days": 1,
            }
        },
    )

    candidates_df = pd.DataFrame({"ticker": ["AAA.T"]})
    params = {"strategy": "テスト戦略"}
    pipeline_functions._run_backtest_rank(candidates_df, params, tmp_path)
    pipeline_functions._run_backtest_rank(candidates_df, params, tmp_path)

    assert call_count["n"] == 1


def test_merge_strategy_results_selects_best_strategy_and_computes_aggregates():
    rows_by_strategy = {
        "戦略A": [
            {"ticker": "AAA.T", "total_return_pct": 10.0, "benchmark_return_pct": 4.0,
             "win_rate_pct": 100.0, "max_drawdown_pct": -5.0, "risk_adjusted_return": 2.0,
             "best_params": {"x": 1}},
        ],
        "戦略B": [
            {"ticker": "AAA.T", "total_return_pct": -3.0, "benchmark_return_pct": 4.0,
             "win_rate_pct": 0.0, "max_drawdown_pct": -6.0, "risk_adjusted_return": -0.5,
             "best_params": {"y": 2}},
        ],
    }

    merged = pipeline_functions._merge_strategy_results(rows_by_strategy)

    assert merged == [
        {
            "ticker": "AAA.T",
            "total_return_pct": 10.0,
            "benchmark_return_pct": 4.0,
            "win_rate_pct": 100.0,
            "max_drawdown_pct": -5.0,
            "risk_adjusted_return": 2.0,
            "best_params": {"x": 1},
            "_source_strategy": "戦略A",
            "avg_risk_adjusted_return": 0.75,
            "profitable_strategy_count": 1,
        }
    ]


def test_merge_strategy_results_handles_ticker_missing_from_some_strategies():
    rows_by_strategy = {
        "戦略A": [{"ticker": "AAA.T", "total_return_pct": 5.0, "benchmark_return_pct": 0.0,
                   "win_rate_pct": 100.0, "max_drawdown_pct": -1.0, "risk_adjusted_return": 5.0,
                   "best_params": {}}],
        "戦略B": [],
    }

    merged = pipeline_functions._merge_strategy_results(rows_by_strategy)

    assert len(merged) == 1
    assert merged[0]["avg_risk_adjusted_return"] == 5.0
    assert merged[0]["profitable_strategy_count"] == 1


def test_run_multi_strategy_rank_picks_best_strategy_per_ticker(monkeypatch, tmp_path):
    dates = pd.date_range("2026-01-01", periods=5, freq="D")

    def fake_fetch(tickers, period):
        return {t: pd.Series([100.0, 101.0, 102.0, 103.0, 104.0], index=dates) for t in tickers}

    monkeypatch.setattr(pipeline_functions, "fetch_universe_price_histories", fake_fetch)

    def strategy_a(prices, transaction_cost_pct=0.0, **params):
        return {"total_return_pct": 10.0, "benchmark_return_pct": 4.0, "win_rate_pct": 100.0,
                "max_drawdown_pct": -5.0, "trade_days": 1}

    def strategy_b(prices, transaction_cost_pct=0.0, **params):
        return {"total_return_pct": 20.0, "benchmark_return_pct": 4.0, "win_rate_pct": 100.0,
                "max_drawdown_pct": -5.0, "trade_days": 1}

    monkeypatch.setattr(
        pipeline_functions,
        "STRATEGIES",
        {
            "戦略A": {"func": strategy_a, "param_grid": {"x": [1]}, "min_days": 1},
            "戦略B": {"func": strategy_b, "param_grid": {"x": [1]}, "min_days": 1},
        },
    )

    candidates_df = pd.DataFrame({"ticker": ["AAA.T"]})
    result_df = pipeline_functions._run_multi_strategy_rank(
        candidates_df, {"period": "1y", "top_n": 10}, tmp_path
    )

    row = result_df.iloc[0]
    assert row["_source_strategy"] == "戦略B"
    assert row["risk_adjusted_return"] == 4.0
    assert row["avg_risk_adjusted_return"] == 3.0
    assert row["profitable_strategy_count"] == 2


def test_detect_recent_cross_true_when_cross_within_window():
    dates = pd.date_range("2026-01-01", periods=6, freq="D")
    fast = pd.Series([1, 1, 1, 5, 5, 5], index=dates, dtype=float)
    slow = pd.Series([2, 2, 2, 2, 2, 2], index=dates, dtype=float)

    assert pipeline_functions._detect_recent_cross(fast, slow, "up", within_days=5) is True


def test_detect_recent_cross_false_when_cross_outside_window():
    dates = pd.date_range("2026-01-01", periods=8, freq="D")
    fast = pd.Series([1, 1, 5, 5, 5, 5, 5, 5], index=dates, dtype=float)
    slow = pd.Series([2, 2, 2, 2, 2, 2, 2, 2], index=dates, dtype=float)
    # クロス（下→上）は3日目（index=2）で発生。直近2日以内には無い。

    assert pipeline_functions._detect_recent_cross(fast, slow, "up", within_days=2) is False


def test_detect_recent_cross_false_when_insufficient_data():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    fast = pd.Series([1, 2, 3], index=dates, dtype=float)
    slow = pd.Series([2, 2, 2], index=dates, dtype=float)

    assert pipeline_functions._detect_recent_cross(fast, slow, "up", within_days=5) is False


def test_detect_recent_cross_detects_downward_direction():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    fast = pd.Series([5, 5, 1, 1], index=dates, dtype=float)
    slow = pd.Series([2, 2, 2, 2], index=dates, dtype=float)

    assert pipeline_functions._detect_recent_cross(fast, slow, "down", within_days=3) is True


def test_detect_recent_threshold_cross_true_when_crossed_up_recently():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    series = pd.Series([20.0, 25.0, 35.0, 35.0], index=dates)

    assert pipeline_functions._detect_recent_threshold_cross(
        series, threshold=30.0, direction="up", within_days=2
    ) is True


def test_detect_recent_threshold_cross_false_when_never_crossed():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    series = pd.Series([20.0, 21.0, 22.0, 23.0], index=dates)

    assert pipeline_functions._detect_recent_threshold_cross(
        series, threshold=30.0, direction="up", within_days=3
    ) is False


def test_resolve_strategy_params_uses_best_params_when_keys_match():
    params = pipeline_functions._resolve_strategy_params(
        "移動平均クロスオーバー", {"short_window": 10, "long_window": 40}
    )
    assert params == {"short_window": 10, "long_window": 40}


def test_resolve_strategy_params_falls_back_to_defaults_when_keys_mismatch():
    params = pipeline_functions._resolve_strategy_params("移動平均クロスオーバー", {"period": 14})
    assert params == {"short_window": 25, "long_window": 75}


def test_resolve_strategy_params_falls_back_to_defaults_when_none():
    params = pipeline_functions._resolve_strategy_params("RSI逆張り", None)
    assert params == {"period": 14, "oversold": 30, "overbought": 70}


def test_detect_signal_for_row_dispatches_ma_crossover():
    dates = pd.date_range("2026-01-01", periods=10, freq="D")
    close = pd.Series([10, 10, 10, 10, 10, 20, 20, 20, 20, 20], index=dates, dtype=float)

    result = pipeline_functions._detect_signal_for_row(
        close, "移動平均クロスオーバー", {"short_window": 1, "long_window": 3}, "ENTRY"
    )
    assert result is True


def test_detect_signal_for_row_dispatches_rsi_entry_uses_oversold(monkeypatch):
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    close = pd.Series(range(4), index=dates, dtype=float)
    captured = {}

    def fake_compute_rsi(prices, period):
        captured["period"] = period
        return pd.Series([20.0, 20.0, 35.0, 35.0], index=dates)

    monkeypatch.setattr(pipeline_functions, "compute_rsi_series", fake_compute_rsi)

    entry_result = pipeline_functions._detect_signal_for_row(
        close, "RSI逆張り", {"period": 7, "oversold": 30, "overbought": 70}, "ENTRY"
    )
    exit_result = pipeline_functions._detect_signal_for_row(
        close, "RSI逆張り", {"period": 7, "oversold": 30, "overbought": 70}, "EXIT"
    )

    assert captured["period"] == 7
    assert entry_result is True
    assert exit_result is False


def test_detect_signal_for_row_dispatches_macd_crossover(monkeypatch):
    dates = pd.date_range("2026-01-01", periods=6, freq="D")
    close = pd.Series(range(6), index=dates, dtype=float)

    def fake_compute_macd(prices, fast, slow, signal):
        macd_line = pd.Series([-1.0, -1.0, -1.0, 1.0, 1.0, 1.0], index=dates)
        signal_line = pd.Series([0.0] * 6, index=dates)
        return macd_line, signal_line

    monkeypatch.setattr(pipeline_functions, "compute_macd_series", fake_compute_macd)

    result = pipeline_functions._detect_signal_for_row(
        close, "MACDクロスオーバー", {"fast": 12, "slow": 26, "signal": 9}, "ENTRY"
    )
    assert result is True


def test_detect_signal_for_row_dispatches_bollinger_entry_uses_lower_band(monkeypatch):
    dates = pd.date_range("2026-01-01", periods=6, freq="D")
    close = pd.Series([100.0, 100.0, 100.0, 70.0, 70.0, 70.0], index=dates)

    def fake_compute_bands(prices, window, num_std):
        return pd.Series([100.0] * 6, index=dates), pd.Series([90.0] * 6, index=dates)

    monkeypatch.setattr(pipeline_functions, "compute_bollinger_bands", fake_compute_bands)

    entry_result = pipeline_functions._detect_signal_for_row(
        close, "ボリンジャーバンド逆張り", {"window": 20, "num_std": 2.0}, "ENTRY"
    )
    assert entry_result is True


def test_detect_signal_for_row_dispatches_bollinger_exit_uses_middle_band(monkeypatch):
    dates = pd.date_range("2026-01-01", periods=6, freq="D")
    close = pd.Series([70.0, 70.0, 70.0, 100.0, 100.0, 100.0], index=dates)

    def fake_compute_bands(prices, window, num_std):
        return pd.Series([90.0] * 6, index=dates), pd.Series([60.0] * 6, index=dates)

    monkeypatch.setattr(pipeline_functions, "compute_bollinger_bands", fake_compute_bands)

    exit_result = pipeline_functions._detect_signal_for_row(
        close, "ボリンジャーバンド逆張り", {"window": 20, "num_std": 2.0}, "EXIT"
    )
    assert exit_result is True


def test_detect_signal_for_row_returns_false_for_unknown_strategy():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    close = pd.Series([1.0, 2.0, 3.0], index=dates)

    assert pipeline_functions._detect_signal_for_row(close, "未知戦略", None, "ENTRY") is False


def test_run_filter_current_signal_keeps_only_rows_with_entry_signal(monkeypatch, tmp_path):
    dates = pd.date_range("2026-01-01", periods=6, freq="D")

    def fake_fetch(tickers, period):
        return {
            "AAA.T": pd.Series([10, 10, 10, 10, 10, 10], index=dates, dtype=float),
            "BBB.T": pd.Series([10, 10, 10, 20, 20, 20], index=dates, dtype=float),
        }

    monkeypatch.setattr(pipeline_functions, "fetch_universe_price_histories", fake_fetch)

    candidates_df = pd.DataFrame(
        [
            {"ticker": "AAA.T", "_source_strategy": "移動平均クロスオーバー",
             "best_params": {"short_window": 1, "long_window": 3}},
            {"ticker": "BBB.T", "_source_strategy": "移動平均クロスオーバー",
             "best_params": {"short_window": 1, "long_window": 3}},
        ]
    )

    result_df = pipeline_functions._run_filter_current_signal(
        candidates_df, {"signal": "ENTRY"}, tmp_path
    )

    assert result_df["ticker"].tolist() == ["BBB.T"]


def test_run_filter_current_signal_uses_explicit_strategy_override(monkeypatch, tmp_path):
    dates = pd.date_range("2026-01-01", periods=6, freq="D")

    def fake_fetch(tickers, period):
        return {"AAA.T": pd.Series([10, 10, 10, 20, 20, 20], index=dates, dtype=float)}

    monkeypatch.setattr(pipeline_functions, "fetch_universe_price_histories", fake_fetch)

    candidates_df = pd.DataFrame(
        [{"ticker": "AAA.T", "best_params": {"short_window": 1, "long_window": 3}}]
    )

    result_df = pipeline_functions._run_filter_current_signal(
        candidates_df, {"signal": "ENTRY", "strategy": "移動平均クロスオーバー"}, tmp_path
    )

    assert result_df["ticker"].tolist() == ["AAA.T"]


def test_run_filter_current_signal_skips_row_when_strategy_unresolvable(monkeypatch, tmp_path):
    dates = pd.date_range("2026-01-01", periods=6, freq="D")

    def fake_fetch(tickers, period):
        return {"AAA.T": pd.Series([10, 10, 10, 20, 20, 20], index=dates, dtype=float)}

    monkeypatch.setattr(pipeline_functions, "fetch_universe_price_histories", fake_fetch)

    candidates_df = pd.DataFrame([{"ticker": "AAA.T"}])
    result_df = pipeline_functions._run_filter_current_signal(
        candidates_df, {"signal": "ENTRY"}, tmp_path
    )

    assert result_df.empty
