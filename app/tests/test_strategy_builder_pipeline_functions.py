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
