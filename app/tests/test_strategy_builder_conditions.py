import pandas as pd

from strategy_builder.conditions import (
    apply_strategy_conditions,
    build_match_reason,
    sort_by_strategy,
)


def test_apply_strategy_conditions_filters_rows_matching_all_conditions():
    df = pd.DataFrame(
        [
            {"ticker": "AAA", "per": 12.0, "roe_pct": 15.0},
            {"ticker": "BBB", "per": 20.0, "roe_pct": 5.0},
        ]
    )
    strategy = {
        "conditions": [
            {"indicator": "PER", "operator": "LESS_THAN", "value": 15},
            {"indicator": "ROE", "operator": "GREATER_THAN", "value": 10},
        ]
    }
    result = apply_strategy_conditions(df, strategy)
    assert result["ticker"].tolist() == ["AAA"]


def test_apply_strategy_conditions_ignores_unknown_indicator():
    df = pd.DataFrame([{"ticker": "AAA", "per": 12.0}])
    strategy = {"conditions": [{"indicator": "UNKNOWN", "operator": "LESS_THAN", "value": 5}]}
    result = apply_strategy_conditions(df, strategy)
    assert result["ticker"].tolist() == ["AAA"]


def test_apply_strategy_conditions_ignores_unknown_operator():
    df = pd.DataFrame([{"ticker": "AAA", "per": 12.0}])
    strategy = {"conditions": [{"indicator": "PER", "operator": "UNKNOWN_OP", "value": 5}]}
    result = apply_strategy_conditions(df, strategy)
    assert result["ticker"].tolist() == ["AAA"]


def test_apply_strategy_conditions_excludes_missing_values():
    df = pd.DataFrame([{"ticker": "AAA", "per": None}])
    strategy = {"conditions": [{"indicator": "PER", "operator": "LESS_THAN", "value": 15}]}
    result = apply_strategy_conditions(df, strategy)
    assert result.empty


def test_apply_strategy_conditions_supports_equals_operator():
    df = pd.DataFrame([{"ticker": "AAA", "market_cap": 100}, {"ticker": "BBB", "market_cap": 200}])
    strategy = {"conditions": [{"indicator": "MARKET_CAP", "operator": "EQUALS", "value": 100}]}
    result = apply_strategy_conditions(df, strategy)
    assert result["ticker"].tolist() == ["AAA"]


def test_sort_by_strategy_sorts_descending_by_indicator():
    df = pd.DataFrame([{"ticker": "AAA", "roe_pct": 5.0}, {"ticker": "BBB", "roe_pct": 15.0}])
    strategy = {"sort_by": "ROE", "order": "DESC"}
    result = sort_by_strategy(df, strategy)
    assert result["ticker"].tolist() == ["BBB", "AAA"]


def test_sort_by_strategy_sorts_ascending_when_order_is_asc():
    df = pd.DataFrame([{"ticker": "AAA", "roe_pct": 5.0}, {"ticker": "BBB", "roe_pct": 15.0}])
    strategy = {"sort_by": "ROE", "order": "ASC"}
    result = sort_by_strategy(df, strategy)
    assert result["ticker"].tolist() == ["AAA", "BBB"]


def test_sort_by_strategy_returns_unchanged_when_sort_by_unknown():
    df = pd.DataFrame([{"ticker": "AAA", "roe_pct": 5.0}])
    strategy = {"sort_by": "UNKNOWN", "order": "DESC"}
    result = sort_by_strategy(df, strategy)
    assert result["ticker"].tolist() == ["AAA"]


def test_build_match_reason_includes_actual_value_and_threshold():
    row = pd.Series({"per": 12.3, "roe_pct": 15.2})
    conditions = [
        {"indicator": "PER", "operator": "LESS_THAN", "value": 15},
        {"indicator": "ROE", "operator": "GREATER_THAN", "value": 10},
    ]
    reason = build_match_reason(row, conditions)
    assert "PER 12.3（条件: 15未満）" in reason
    assert "ROE 15.2（条件: 10より大）" in reason


def test_build_match_reason_skips_missing_values():
    row = pd.Series({"per": None, "roe_pct": 15.2})
    conditions = [
        {"indicator": "PER", "operator": "LESS_THAN", "value": 15},
        {"indicator": "ROE", "operator": "GREATER_THAN", "value": 10},
    ]
    reason = build_match_reason(row, conditions)
    assert "PER" not in reason
    assert "ROE 15.2（条件: 10より大）" in reason


def test_build_match_reason_returns_placeholder_when_no_conditions_match():
    row = pd.Series({"per": 12.3})
    reason = build_match_reason(
        row, [{"indicator": "UNKNOWN", "operator": "LESS_THAN", "value": 1}]
    )
    assert reason == "条件詳細なし"
