from common.disclaimer import DISCLAIMER_NOTICE
from prompt_patterns.backtest_explanation import (
    build_backtest_prompt,
    build_ranking_comment_prompt,
    generate_ranking_comments,
)


def test_build_backtest_prompt_includes_ticker_and_facts():
    comparison = {"標準(25/75)": {"total_return_pct": 18.4, "trade_days": 312}}

    prompt = build_backtest_prompt("7203.T", comparison)

    assert "7203.T" in prompt
    assert "18.4" in prompt
    assert "312" in prompt
    assert DISCLAIMER_NOTICE in prompt


def test_build_backtest_prompt_instructs_overfitting_and_no_directive_language():
    comparison = {"標準(25/75)": {"total_return_pct": 18.4}}

    prompt = build_backtest_prompt("7203.T", comparison)

    assert "過学習" in prompt
    assert "取引コスト" in prompt
    assert "売買" in prompt
    assert "パラメータ" in prompt


def test_build_backtest_prompt_uses_default_strategy_name_when_omitted():
    comparison = {"標準(25/75)": {"total_return_pct": 18.4}}

    prompt = build_backtest_prompt("7203.T", comparison)

    assert "移動平均クロスオーバー戦略" in prompt


def test_build_backtest_prompt_uses_given_strategy_name():
    comparison = {"標準(14, 30/70)": {"total_return_pct": 5.0}}

    prompt = build_backtest_prompt("7203.T", comparison, strategy_name="RSI逆張り")

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
