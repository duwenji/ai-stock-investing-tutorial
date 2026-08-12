import pandas as pd

from strategy_builder.conditions import apply_strategy_conditions


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


def test_apply_strategy_conditions_supports_sector_equals():
    df = pd.DataFrame(
        [
            {"ticker": "AAA", "sector": "電気機器"},
            {"ticker": "BBB", "sector": "銀行"},
        ]
    )
    strategy = {"conditions": [{"indicator": "SECTOR", "operator": "EQUALS", "value": "電気機器"}]}
    result = apply_strategy_conditions(df, strategy)
    assert result["ticker"].tolist() == ["AAA"]
