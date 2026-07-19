import pandas as pd

from prompt_patterns.screening import apply_filters, generate_screening_comments


def test_apply_filters_filters_rows_matching_all_conditions():
    df = pd.DataFrame(
        [
            {"ticker": "AAA", "per": 12.0, "pbr": 1.0, "dividend_yield_pct": 3.5},
            {"ticker": "BBB", "per": 20.0, "pbr": 2.0, "dividend_yield_pct": 1.0},
        ]
    )
    filters = [
        {"field": "per", "operator": "<=", "value": 15},
        {"field": "dividend_yield_pct", "operator": ">=", "value": 3},
    ]
    result = apply_filters(df, filters)
    assert result["ticker"].tolist() == ["AAA"]


def test_apply_filters_ignores_unknown_field():
    df = pd.DataFrame([{"ticker": "AAA", "per": 12.0}])
    filters = [{"field": "unknown_field", "operator": "<=", "value": 5}]
    result = apply_filters(df, filters)
    assert result["ticker"].tolist() == ["AAA"]


def test_apply_filters_excludes_missing_values():
    df = pd.DataFrame([{"ticker": "AAA", "per": None}])
    filters = [{"field": "per", "operator": "<=", "value": 15}]
    result = apply_filters(df, filters)
    assert result.empty


def test_generate_screening_comments_parses_json_response():
    df = pd.DataFrame([{"ticker": "AAA", "per": 12.0, "dividend_yield_pct": 3.5}])
    fake_call_llm = lambda prompt: '{"AAA": "割安感があります。"}'
    result = generate_screening_comments(df, call_llm=fake_call_llm)
    assert result == {"AAA": "割安感があります。"}


def test_generate_screening_comments_returns_empty_for_empty_df():
    df = pd.DataFrame(columns=["ticker", "per", "dividend_yield_pct"])
    result = generate_screening_comments(df, call_llm=lambda prompt: "{}")
    assert result == {}


def test_generate_screening_comments_fallback_on_invalid_json():
    df = pd.DataFrame([{"ticker": "AAA", "per": 12.0, "dividend_yield_pct": 3.5}])
    result = generate_screening_comments(df, call_llm=lambda prompt: "not json")
    assert result == {"AAA": "コメント生成失敗"}
