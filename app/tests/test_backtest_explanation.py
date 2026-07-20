from common.disclaimer import DISCLAIMER_NOTICE
from prompt_patterns.backtest_explanation import build_backtest_prompt


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
