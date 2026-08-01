from prompt_patterns.strategy_dialogue import build_dialogue_prompt, parse_dialogue_response


def test_build_dialogue_prompt_includes_persona_instructions():
    prompt = build_dialogue_prompt([{"role": "user", "content": "PERが低い銘柄"}])
    assert "クオンツ・アナリスト" in prompt
    assert "conditions" in prompt


def test_build_dialogue_prompt_includes_full_history_in_order():
    history = [
        {"role": "user", "content": "PERが低い銘柄"},
        {"role": "assistant", "content": "PERの閾値はいくつにしますか？"},
        {"role": "user", "content": "15倍以下で"},
    ]
    prompt = build_dialogue_prompt(history)
    user_pos = prompt.index("ユーザー: PERが低い銘柄")
    assistant_pos = prompt.index("AI: PERの閾値はいくつにしますか？")
    second_user_pos = prompt.index("ユーザー: 15倍以下で")
    assert user_pos < assistant_pos < second_user_pos


def test_parse_dialogue_response_detects_finalized_strategy_json():
    raw = (
        '```json\n{"strategy_name": "割安株", "conditions": '
        '[{"indicator": "PER", "operator": "LESS_THAN", "value": 15}], '
        '"sort_by": "PER", "order": "ASC"}\n```'
    )
    result = parse_dialogue_response(raw)
    assert result["kind"] == "strategy"
    assert result["strategy"]["strategy_name"] == "割安株"


def test_parse_dialogue_response_detects_question_text():
    raw = "PERの閾値はいくつにしますか？"
    result = parse_dialogue_response(raw)
    assert result == {"kind": "question", "text": "PERの閾値はいくつにしますか？"}


def test_parse_dialogue_response_treats_malformed_json_as_question():
    raw = "```json\n{not valid json\n```"
    result = parse_dialogue_response(raw)
    assert result["kind"] == "question"


def test_parse_dialogue_response_requires_conditions_key_for_strategy():
    raw = '{"strategy_name": "割安株"}'
    result = parse_dialogue_response(raw)
    assert result["kind"] == "question"
