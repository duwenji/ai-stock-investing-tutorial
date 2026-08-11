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
