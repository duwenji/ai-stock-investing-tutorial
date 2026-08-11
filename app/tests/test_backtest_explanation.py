from prompt_patterns.backtest_explanation import (
    build_backtest_prompt,
    build_improvement_prompt,
    build_ranking_comment_prompt,
    generate_ranking_comments,
)


def test_build_backtest_prompt_includes_ticker_and_facts():
    comparison = {"最良（short_window=27, long_window=75）": {"total_return_pct": 18.4, "trade_days": 312}}
    stability = {"cv": 0.3, "is_stable": True, "grid_size": 30}

    prompt = build_backtest_prompt("7203.T", comparison, stability)

    assert "7203.T" in prompt
    assert "18.4" in prompt
    assert "312" in prompt


def test_build_backtest_prompt_includes_stability_info():
    comparison = {"最良（short_window=27, long_window=75）": {"total_return_pct": 18.4}}
    stability = {"cv": 0.62, "is_stable": False, "grid_size": 30}

    prompt = build_backtest_prompt("7203.T", comparison, stability)

    assert "0.62" in prompt
    assert "is_stable" in prompt


def test_build_backtest_prompt_instructs_overfitting_and_no_directive_language():
    comparison = {"最良（short_window=27, long_window=75）": {"total_return_pct": 18.4}}
    stability = {"cv": 0.3, "is_stable": True, "grid_size": 30}

    prompt = build_backtest_prompt("7203.T", comparison, stability)

    assert "過学習" in prompt
    assert "取引コスト" in prompt
    assert "売買" in prompt
    assert "パラメータ" in prompt


def test_build_backtest_prompt_uses_default_strategy_name_when_omitted():
    comparison = {"最良（short_window=27, long_window=75）": {"total_return_pct": 18.4}}
    stability = {"cv": 0.3, "is_stable": True, "grid_size": 30}

    prompt = build_backtest_prompt("7203.T", comparison, stability)

    assert "移動平均クロスオーバー戦略" in prompt


def test_build_backtest_prompt_uses_given_strategy_name():
    comparison = {"最良（period=14, oversold=30）": {"total_return_pct": 5.0}}
    stability = {"cv": 0.3, "is_stable": True, "grid_size": 36}

    prompt = build_backtest_prompt("7203.T", comparison, stability, strategy_name="RSI逆張り")

    assert "RSI逆張り戦略" in prompt
    assert "移動平均クロスオーバー戦略" not in prompt


def test_build_ranking_comment_prompt_includes_ticker_data_and_json_output_instruction():
    ranking_rows = [{"ticker": "AAA.T", "total_return_pct": 20.0, "risk_adjusted_return": 6.0}]

    prompt = build_ranking_comment_prompt(ranking_rows)

    assert "AAA.T" in prompt
    assert "20.0" in prompt
    assert "6.0" in prompt


def test_generate_ranking_comments_returns_empty_dict_for_empty_ranking():
    assert generate_ranking_comments([]) == {}


def test_generate_ranking_comments_parses_llm_json_response():
    ranking_rows = [
        {"ticker": "AAA.T", "total_return_pct": 20.0, "risk_adjusted_return": 6.0},
        {"ticker": "BBB.T", "total_return_pct": 10.0, "risk_adjusted_return": 2.0},
    ]
    fake_call_llm = lambda prompt: '{"AAA.T": "好調でした。", "BBB.T": "堅調でした。"}'

    result = generate_ranking_comments(ranking_rows, call_llm=fake_call_llm)

    assert result == {"AAA.T": "好調でした。", "BBB.T": "堅調でした。"}


def test_generate_ranking_comments_falls_back_on_invalid_json():
    ranking_rows = [{"ticker": "AAA.T", "total_return_pct": 20.0, "risk_adjusted_return": 6.0}]
    fake_call_llm = lambda prompt: "not json"

    result = generate_ranking_comments(ranking_rows, call_llm=fake_call_llm)

    assert result == {"AAA.T": "コメント生成失敗"}


def test_build_improvement_prompt_includes_ticker_facts_and_prior_explanation():
    comparison = {"最良（short_window=27, long_window=75）": {"total_return_pct": 18.4, "trade_days": 312}}
    stability = {"cv": 0.3, "is_stable": True, "grid_size": 30}

    prompt = build_improvement_prompt(
        "7203.T", comparison, "これまでの解説文です。", stability, "移動平均クロスオーバー"
    )

    assert "7203.T" in prompt
    assert "18.4" in prompt
    assert "これまでの解説文です。" in prompt


def test_build_improvement_prompt_instructs_overfitting_and_no_directive_language():
    comparison = {"最良（short_window=27, long_window=75）": {"total_return_pct": 18.4}}
    stability = {"cv": 0.3, "is_stable": True, "grid_size": 30}

    prompt = build_improvement_prompt("7203.T", comparison, "解説文", stability, "移動平均クロスオーバー")

    assert "過学習" in prompt
    assert "取引コスト" in prompt
    assert "売買" in prompt


def test_build_improvement_prompt_uses_default_strategy_name_when_omitted():
    comparison = {"最良（short_window=27, long_window=75）": {"total_return_pct": 18.4}}
    stability = {"cv": 0.3, "is_stable": True, "grid_size": 30}

    prompt = build_improvement_prompt("7203.T", comparison, "解説文", stability)

    assert "移動平均クロスオーバー戦略" in prompt
