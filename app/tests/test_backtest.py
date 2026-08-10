import logging

import pandas as pd

from common.disclaimer import DISCLAIMER_NOTICE
from portfolio_management.backtest import (
    STRATEGIES,
    generate_backtest_explanation,
    run_bollinger_reversal_backtest,
    run_grid_search,
    run_ma_crossover_backtest,
    run_macd_crossover_backtest,
    run_rsi_reversal_backtest,
    run_universe_backtest_ranking,
    summarize_grid_stability,
)


def test_run_ma_crossover_backtest_shifts_signal_to_avoid_lookahead_bias():
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

    assert result["total_return_pct"] == -0.1
    assert result["max_drawdown_pct"] == -0.1
    assert result["benchmark_return_pct"] == 2.0
    assert result["trade_days"] == 1


def test_run_rsi_reversal_backtest_enters_on_oversold_recovery_and_exits_on_overbought():
    dates = pd.date_range("2026-01-01", periods=9, freq="D")
    prices = pd.Series([100, 90, 80, 70, 90, 110, 130, 130, 130], index=dates)

    result = run_rsi_reversal_backtest(prices, period=3, oversold=30, overbought=70)

    assert result == {
        "total_return_pct": 22.22,
        "benchmark_return_pct": 30.0,
        "win_rate_pct": 100.0,
        "max_drawdown_pct": 0.0,
        "trade_days": 1,
    }


def test_run_rsi_reversal_backtest_applies_transaction_cost_on_position_change():
    dates = pd.date_range("2026-01-01", periods=9, freq="D")
    prices = pd.Series([100, 90, 80, 70, 90, 110, 130, 130, 130], index=dates)

    result = run_rsi_reversal_backtest(
        prices, period=3, oversold=30, overbought=70, transaction_cost_pct=0.1
    )

    assert result == {
        "total_return_pct": 22.0,
        "benchmark_return_pct": 30.0,
        "win_rate_pct": 100.0,
        "max_drawdown_pct": -0.1,
        "trade_days": 1,
    }


def test_run_macd_crossover_backtest_shifts_signal_to_avoid_lookahead_bias():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.Series([100, 100, 102, 102], index=dates)

    result = run_macd_crossover_backtest(prices, fast=1, slow=2, signal=2)

    assert result == {
        "total_return_pct": 0.0,
        "benchmark_return_pct": 2.0,
        "win_rate_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "trade_days": 1,
    }


def test_run_macd_crossover_backtest_applies_transaction_cost_on_position_change():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.Series([100, 100, 102, 102], index=dates)

    result = run_macd_crossover_backtest(
        prices, fast=1, slow=2, signal=2, transaction_cost_pct=0.1
    )

    assert result["total_return_pct"] == -0.1
    assert result["max_drawdown_pct"] == -0.1
    assert result["benchmark_return_pct"] == 2.0
    assert result["trade_days"] == 1


def test_run_bollinger_reversal_backtest_enters_below_lower_band_and_exits_at_middle_band():
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    prices = pd.Series([100, 100, 70, 100, 100], index=dates)

    result = run_bollinger_reversal_backtest(prices, window=3, num_std=1.0)

    assert result == {
        "total_return_pct": 42.86,
        "benchmark_return_pct": 0.0,
        "win_rate_pct": 100.0,
        "max_drawdown_pct": 0.0,
        "trade_days": 1,
    }


def test_run_bollinger_reversal_backtest_applies_transaction_cost_on_position_change():
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    prices = pd.Series([100, 100, 70, 100, 100], index=dates)

    result = run_bollinger_reversal_backtest(
        prices, window=3, num_std=1.0, transaction_cost_pct=0.1
    )

    assert result == {
        "total_return_pct": 42.61,
        "benchmark_return_pct": 0.0,
        "win_rate_pct": 100.0,
        "max_drawdown_pct": -0.1,
        "trade_days": 1,
    }


def test_strategies_registry_contains_all_four_strategies():
    assert set(STRATEGIES.keys()) == {
        "移動平均クロスオーバー",
        "RSI逆張り",
        "MACDクロスオーバー",
        "ボリンジャーバンド逆張り",
    }


def test_strategies_registry_entries_have_func_param_grid_and_min_days():
    for definition in STRATEGIES.values():
        assert callable(definition["func"])
        assert isinstance(definition["param_grid"], dict)
        assert len(definition["param_grid"]) == 2
        assert isinstance(definition["min_days"], int)


def test_strategies_registry_fixed_params_only_for_three_parameter_strategies():
    assert "fixed_params" not in STRATEGIES["移動平均クロスオーバー"]
    assert STRATEGIES["RSI逆張り"]["fixed_params"] == {"overbought": 70}
    assert STRATEGIES["MACDクロスオーバー"]["fixed_params"] == {"signal": 9}
    assert "fixed_params" not in STRATEGIES["ボリンジャーバンド逆張り"]


def test_strategies_registry_param_grid_sizes_are_within_grid_search_budget():
    for definition in STRATEGIES.values():
        combo_count = 1
        for values in definition["param_grid"].values():
            combo_count *= len(list(values))
        assert 15 <= combo_count <= 40


def test_generate_backtest_explanation_includes_disclaimer_and_commentary():
    grid_results = [
        {
            "params": {"short_window": 1, "long_window": 2},
            "total_return_pct": 0.0,
            "benchmark_return_pct": 2.0,
            "win_rate_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "trade_days": 1,
            "risk_adjusted_return": 0.0,
        }
    ]
    fake_call_llm = lambda prompt: "テスト用のバックテスト解説です。"

    result = generate_backtest_explanation("AAA.T", grid_results, call_llm=fake_call_llm)

    assert result.count(DISCLAIMER_NOTICE) == 2
    assert "テスト用のバックテスト解説です。" in result


def test_generate_backtest_explanation_passes_ticker_and_comparison_to_prompt():
    grid_results = [
        {
            "params": {"short_window": 1, "long_window": 2},
            "total_return_pct": 0.0,
            "benchmark_return_pct": 2.0,
            "win_rate_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "trade_days": 1,
            "risk_adjusted_return": 0.0,
        }
    ]
    captured_prompts = []

    def fake_call_llm(prompt):
        captured_prompts.append(prompt)
        return "解説"

    generate_backtest_explanation("AAA.T", grid_results, call_llm=fake_call_llm)

    assert "AAA.T" in captured_prompts[0]
    assert "short_window=1" in captured_prompts[0]


def test_generate_backtest_explanation_passes_strategy_name_to_prompt():
    grid_results = [
        {
            "params": {"period": 3, "oversold": 30},
            "total_return_pct": 22.22,
            "benchmark_return_pct": 30.0,
            "win_rate_pct": 100.0,
            "max_drawdown_pct": 0.0,
            "trade_days": 1,
            "risk_adjusted_return": 22.22,
        }
    ]
    captured_prompts = []

    def fake_call_llm(prompt):
        captured_prompts.append(prompt)
        return "解説"

    generate_backtest_explanation(
        "AAA.T", grid_results, strategy_name="RSI逆張り", call_llm=fake_call_llm
    )

    assert "RSI逆張り戦略" in captured_prompts[0]


def test_generate_backtest_explanation_passes_stability_info_to_prompt():
    grid_results = [
        {
            "params": {"short_window": 1, "long_window": 2},
            "total_return_pct": 0.0,
            "benchmark_return_pct": 2.0,
            "win_rate_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "trade_days": 1,
            "risk_adjusted_return": 0.0,
        },
        {
            "params": {"short_window": 1, "long_window": 3},
            "total_return_pct": 5.0,
            "benchmark_return_pct": 2.0,
            "win_rate_pct": 100.0,
            "max_drawdown_pct": 0.0,
            "trade_days": 1,
            "risk_adjusted_return": 5.0,
        },
    ]
    captured_prompts = []

    def fake_call_llm(prompt):
        captured_prompts.append(prompt)
        return "解説"

    generate_backtest_explanation("AAA.T", grid_results, call_llm=fake_call_llm)

    assert "is_stable" in captured_prompts[0]
    assert "grid_size" in captured_prompts[0]


def test_generate_backtest_explanation_calls_llm_twice_and_includes_improvement_section():
    grid_results = [
        {
            "params": {"short_window": 1, "long_window": 2},
            "total_return_pct": 0.0,
            "benchmark_return_pct": 2.0,
            "win_rate_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "trade_days": 1,
            "risk_adjusted_return": 0.0,
        }
    ]
    responses = iter(["結果の解説です。", "追加提案です。"])
    call_count = {"n": 0}

    def fake_call_llm(prompt):
        call_count["n"] += 1
        return next(responses)

    result = generate_backtest_explanation("AAA.T", grid_results, call_llm=fake_call_llm)

    assert call_count["n"] == 2
    assert "結果の解説です。" in result
    assert "追加提案です。" in result
    assert "## 追加で検討したい観点" in result


def test_generate_backtest_explanation_second_prompt_includes_first_explanation():
    grid_results = [
        {
            "params": {"short_window": 1, "long_window": 2},
            "total_return_pct": 0.0,
            "benchmark_return_pct": 2.0,
            "win_rate_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "trade_days": 1,
            "risk_adjusted_return": 0.0,
        }
    ]
    captured_prompts = []
    responses = iter(["最初の解説文です。", "改善提案文です。"])

    def fake_call_llm(prompt):
        captured_prompts.append(prompt)
        return next(responses)

    generate_backtest_explanation("AAA.T", grid_results, call_llm=fake_call_llm)

    assert "最初の解説文です。" in captured_prompts[1]
    assert "AAA.T" in captured_prompts[1]


def test_generate_backtest_explanation_gate_skips_second_call_when_explanation_empty():
    grid_results = [
        {
            "params": {"short_window": 1, "long_window": 2},
            "total_return_pct": 0.0,
            "benchmark_return_pct": 2.0,
            "win_rate_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "trade_days": 1,
            "risk_adjusted_return": 0.0,
        }
    ]
    call_count = {"n": 0}

    def fake_call_llm(prompt):
        call_count["n"] += 1
        return "   "

    result = generate_backtest_explanation("AAA.T", grid_results, call_llm=fake_call_llm)

    assert call_count["n"] == 1
    assert result == "解説の生成に失敗しました。"


def test_generate_backtest_explanation_omits_improvement_section_when_step2_empty():
    grid_results = [
        {
            "params": {"short_window": 1, "long_window": 2},
            "total_return_pct": 0.0,
            "benchmark_return_pct": 2.0,
            "win_rate_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "trade_days": 1,
            "risk_adjusted_return": 0.0,
        }
    ]
    responses = iter(["結果の解説です。", "  "])

    def fake_call_llm(prompt):
        return next(responses)

    result = generate_backtest_explanation("AAA.T", grid_results, call_llm=fake_call_llm)

    assert "結果の解説です。" in result
    assert "## 追加で検討したい観点" not in result


def test_run_universe_backtest_ranking_sorts_by_risk_adjusted_return_and_skips_short_history():
    dates3 = pd.date_range("2026-01-01", periods=3, freq="D")
    dates1 = pd.date_range("2026-01-01", periods=1, freq="D")
    prices_by_ticker = {
        "AAA.T": pd.Series([20.0, 20.0, 20.0], index=dates3),
        "BBB.T": pd.Series([60.0, 60.0, 60.0], index=dates3),
        "CCC.T": pd.Series([999.0], index=dates1),
    }

    def fake_backtest_func(prices, transaction_cost_pct=0.0, **params):
        marker = float(prices.iloc[0])
        return {
            "total_return_pct": marker,
            "benchmark_return_pct": 0.0,
            "win_rate_pct": 100.0,
            "max_drawdown_pct": -10.0,
            "trade_days": 1,
        }

    result = run_universe_backtest_ranking(
        prices_by_ticker, fake_backtest_func, param_grid={"x": [1]}, min_days=2
    )

    assert [row["ticker"] for row in result] == ["BBB.T", "AAA.T"]
    assert result[0]["risk_adjusted_return"] == 6.0
    assert result[1]["risk_adjusted_return"] == 2.0
    assert result[0]["best_params"] == {"x": 1}


def test_run_universe_backtest_ranking_falls_back_to_total_return_when_drawdown_is_zero():
    dates = pd.date_range("2026-01-01", periods=2, freq="D")
    prices_by_ticker = {"AAA.T": pd.Series([10.0, 10.0], index=dates)}

    def fake_backtest_func(prices, transaction_cost_pct=0.0, **params):
        return {
            "total_return_pct": 15.0,
            "benchmark_return_pct": 0.0,
            "win_rate_pct": 100.0,
            "max_drawdown_pct": 0.0,
            "trade_days": 1,
        }

    result = run_universe_backtest_ranking(
        prices_by_ticker, fake_backtest_func, param_grid={"x": [1]}, min_days=1
    )

    assert result[0]["risk_adjusted_return"] == 15.0


def test_run_universe_backtest_ranking_picks_best_params_per_ticker_and_reports_stability():
    dates = pd.date_range("2026-01-01", periods=2, freq="D")
    prices_by_ticker = {"AAA.T": pd.Series([10.0, 10.0], index=dates)}

    def fake_backtest_func(prices, transaction_cost_pct=0.0, **params):
        return {
            "total_return_pct": float(params["x"]) * 10,
            "benchmark_return_pct": 0.0,
            "win_rate_pct": 100.0,
            "max_drawdown_pct": -5.0,
            "trade_days": 1,
        }

    result = run_universe_backtest_ranking(
        prices_by_ticker, fake_backtest_func, param_grid={"x": [1, 2, 3]}, min_days=1
    )

    assert result[0]["best_params"] == {"x": 3}
    assert result[0]["risk_adjusted_return"] == 6.0
    assert "stability_cv" in result[0]
    assert "is_stable" in result[0]


def test_run_universe_backtest_ranking_applies_fixed_params():
    dates = pd.date_range("2026-01-01", periods=2, freq="D")
    prices_by_ticker = {"AAA.T": pd.Series([10.0, 10.0], index=dates)}
    captured_kwargs = []

    def fake_backtest_func(prices, transaction_cost_pct=0.0, **params):
        captured_kwargs.append(params)
        return {
            "total_return_pct": 0.0,
            "benchmark_return_pct": 0.0,
            "win_rate_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "trade_days": 0,
        }

    run_universe_backtest_ranking(
        prices_by_ticker,
        fake_backtest_func,
        param_grid={"x": [1]},
        fixed_params={"y": 9},
        min_days=1,
    )

    assert captured_kwargs == [{"x": 1, "y": 9}]


def test_run_universe_backtest_ranking_skips_ticker_when_grid_search_raises(caplog):
    dates = pd.date_range("2026-01-01", periods=2, freq="D")
    prices_by_ticker = {
        "AAA.T": pd.Series([10.0, 10.0], index=dates),
        "BBB.T": pd.Series([20.0, 20.0], index=dates),
    }

    def fake_backtest_func(prices, transaction_cost_pct=0.0, **params):
        if float(prices.iloc[0]) == 10.0:
            raise ValueError("計算失敗")
        return {
            "total_return_pct": 5.0,
            "benchmark_return_pct": 0.0,
            "win_rate_pct": 100.0,
            "max_drawdown_pct": -1.0,
            "trade_days": 1,
        }

    with caplog.at_level(logging.ERROR, logger="portfolio_management.backtest"):
        result = run_universe_backtest_ranking(
            prices_by_ticker, fake_backtest_func, param_grid={"x": [1]}, min_days=1
        )

    assert [row["ticker"] for row in result] == ["BBB.T"]


def test_run_universe_backtest_ranking_logs_duration(caplog):
    dates = pd.date_range("2026-01-01", periods=80, freq="D")
    prices_by_ticker = {"AAA.T": pd.Series(range(100, 180), index=dates, dtype=float)}

    with caplog.at_level(logging.INFO, logger="portfolio_management.backtest"):
        run_universe_backtest_ranking(
            prices_by_ticker,
            run_ma_crossover_backtest,
            param_grid={"short_window": [5], "long_window": [25]},
        )

    assert "ユニバース一括バックテスト" in caplog.text
    assert "を開始" in caplog.text
    assert "が完了しました" in caplog.text


def test_run_grid_search_returns_result_for_each_combination_in_cartesian_product():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.Series([100, 100, 102, 102], index=dates)

    grid_results = run_grid_search(
        prices,
        run_ma_crossover_backtest,
        param_grid={"short_window": [1], "long_window": [2, 3]},
    )

    assert len(grid_results) == 2
    assert {row["params"]["long_window"] for row in grid_results} == {2, 3}
    assert all(row["params"]["short_window"] == 1 for row in grid_results)


def test_run_grid_search_computes_risk_adjusted_return_per_combination():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.Series([100, 100, 102, 102], index=dates)

    grid_results = run_grid_search(
        prices,
        run_ma_crossover_backtest,
        param_grid={"short_window": [1], "long_window": [2]},
    )

    assert grid_results == [
        {
            "params": {"short_window": 1, "long_window": 2},
            "total_return_pct": 0.0,
            "benchmark_return_pct": 2.0,
            "win_rate_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "trade_days": 1,
            "risk_adjusted_return": 0.0,
        }
    ]


def test_run_grid_search_applies_fixed_params_to_every_combination():
    dates = pd.date_range("2026-01-01", periods=9, freq="D")
    prices = pd.Series([100, 90, 80, 70, 90, 110, 130, 130, 130], index=dates)
    captured_kwargs = []

    def fake_backtest_func(prices, transaction_cost_pct=0.0, **params):
        captured_kwargs.append(params)
        return {
            "total_return_pct": 0.0,
            "benchmark_return_pct": 0.0,
            "win_rate_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "trade_days": 0,
        }

    run_grid_search(
        prices,
        fake_backtest_func,
        param_grid={"period": [3, 5]},
        fixed_params={"oversold": 30, "overbought": 70},
    )

    assert captured_kwargs == [
        {"period": 3, "oversold": 30, "overbought": 70},
        {"period": 5, "oversold": 30, "overbought": 70},
    ]


def test_run_grid_search_logs_duration(caplog):
    dates = pd.date_range("2026-01-01", periods=80, freq="D")
    prices = pd.Series(range(100, 180), index=dates, dtype=float)

    with caplog.at_level(logging.INFO, logger="portfolio_management.backtest"):
        run_grid_search(
            prices,
            run_ma_crossover_backtest,
            param_grid={"short_window": [5], "long_window": [25]},
        )

    assert "グリッドサーチ計算" in caplog.text
    assert "を開始" in caplog.text
    assert "が完了しました" in caplog.text


def test_summarize_grid_stability_picks_best_and_worst_by_risk_adjusted_return():
    grid_results = [
        {"params": {"short_window": 5}, "risk_adjusted_return": 3.0},
        {"params": {"short_window": 6}, "risk_adjusted_return": 9.0},
        {"params": {"short_window": 7}, "risk_adjusted_return": 1.0},
    ]

    summary = summarize_grid_stability(grid_results)

    assert summary["best"]["params"] == {"short_window": 6}
    assert summary["worst"]["params"] == {"short_window": 7}
    assert summary["grid_size"] == 3


def test_summarize_grid_stability_is_stable_when_coefficient_of_variation_is_low():
    grid_results = [
        {"params": {"a": 1}, "risk_adjusted_return": 10.0},
        {"params": {"a": 2}, "risk_adjusted_return": 10.0},
        {"params": {"a": 3}, "risk_adjusted_return": 10.0},
    ]

    summary = summarize_grid_stability(grid_results)

    assert summary["cv"] == 0.0
    assert summary["is_stable"] is True


def test_summarize_grid_stability_is_unstable_at_cv_boundary():
    grid_results = [
        {"params": {"a": 1}, "risk_adjusted_return": 5.0},
        {"params": {"a": 2}, "risk_adjusted_return": 15.0},
    ]

    summary = summarize_grid_stability(grid_results)

    assert summary["cv"] == 0.5
    assert summary["is_stable"] is False


def test_summarize_grid_stability_marks_unjudgeable_when_mean_near_zero():
    grid_results = [
        {"params": {"a": 1}, "risk_adjusted_return": 1.0},
        {"params": {"a": 2}, "risk_adjusted_return": -1.0},
    ]

    summary = summarize_grid_stability(grid_results)

    assert summary["cv"] is None
    assert summary["is_stable"] is False
