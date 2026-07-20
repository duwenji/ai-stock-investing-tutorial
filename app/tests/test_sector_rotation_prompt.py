from prompt_patterns.sector_rotation import (
    build_sector_rotation_prompt,
    generate_sector_rotation_comments,
)


def test_build_sector_rotation_prompt_includes_pair_data_and_no_directive_language():
    top_pairs = [
        {
            "leading_sector": "電機・精密",
            "lagging_sector": "機械",
            "lag_days": 5,
            "correlation": 0.82,
        }
    ]

    prompt = build_sector_rotation_prompt(top_pairs)

    assert "電機・精密" in prompt
    assert "機械" in prompt
    assert "過去" in prompt
    assert "将来" in prompt
    assert "売買" in prompt


def test_generate_sector_rotation_comments_returns_empty_dict_for_empty_pairs():
    assert generate_sector_rotation_comments([]) == {}


def test_generate_sector_rotation_comments_parses_llm_json_response():
    top_pairs = [
        {
            "leading_sector": "電機・精密",
            "lagging_sector": "機械",
            "lag_days": 5,
            "correlation": 0.82,
        }
    ]
    fake_call_llm = lambda prompt: '{"電機・精密->機械": "先行して動く傾向があります。"}'

    result = generate_sector_rotation_comments(top_pairs, call_llm=fake_call_llm)

    assert result == {"電機・精密->機械": "先行して動く傾向があります。"}


def test_generate_sector_rotation_comments_falls_back_on_invalid_json():
    top_pairs = [
        {
            "leading_sector": "電機・精密",
            "lagging_sector": "機械",
            "lag_days": 5,
            "correlation": 0.82,
        }
    ]
    fake_call_llm = lambda prompt: "not json"

    result = generate_sector_rotation_comments(top_pairs, call_llm=fake_call_llm)

    assert result == {"電機・精密->機械": "コメント生成失敗"}
