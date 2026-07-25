import pandas as pd

from prompt_patterns.screening import (
    apply_filters,
    build_screening_prompt,
    generate_screening_comments,
)


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


def test_generate_screening_comments_strips_code_fence():
    df = pd.DataFrame([{"ticker": "AAA", "per": 12.0, "dividend_yield_pct": 3.5}])
    fake_call_llm = lambda prompt: '```json\n{"AAA": "割安感があります。"}\n```'
    result = generate_screening_comments(df, call_llm=fake_call_llm)
    assert result == {"AAA": "割安感があります。"}


def test_apply_filters_matches_sector_equality():
    df = pd.DataFrame(
        [
            {"ticker": "AAA", "sector": "自動車・輸送機"},
            {"ticker": "BBB", "sector": "銀行"},
        ]
    )
    filters = [{"field": "sector", "operator": "==", "value": "自動車・輸送機"}]
    result = apply_filters(df, filters)
    assert result["ticker"].tolist() == ["AAA"]


def test_build_screening_prompt_includes_sector_list_when_given():
    prompt = build_screening_prompt(
        "自動車株でPERが低い銘柄", sectors=["自動車・輸送機", "銀行"]
    )
    assert "sector" in prompt
    assert "自動車・輸送機" in prompt
    assert "銀行" in prompt
    assert "業種名のいずれか一つ" in prompt


def test_build_screening_prompt_omits_sector_list_when_not_given():
    prompt = build_screening_prompt("PERが15倍以下")
    assert "sector" in prompt  # fieldとしての説明自体は常に含まれる
    assert "業種名のいずれか一つ" not in prompt  # 業種一覧の案内文は含まれない
