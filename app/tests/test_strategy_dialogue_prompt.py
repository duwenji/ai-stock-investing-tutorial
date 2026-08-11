from prompt_patterns.strategy_dialogue import (
    build_dialogue_prompt,
    build_refinement_prompt,
    parse_dialogue_response,
)


def test_build_dialogue_prompt_includes_persona_instructions():
    prompt = build_dialogue_prompt([{"role": "user", "content": "PERが低い銘柄"}])
    assert "クオンツ・アナリスト" in prompt
    assert "steps" in prompt


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


def test_build_dialogue_prompt_includes_sector_list_when_given():
    prompt = build_dialogue_prompt(
        [{"role": "user", "content": "電気機器の値上がり銘柄に注目したい"}],
        sectors=["電気機器", "銀行"],
    )
    assert "SECTOR" in prompt
    assert "電気機器" in prompt
    assert "銀行" in prompt


def test_build_dialogue_prompt_omits_sector_list_when_not_given():
    prompt = build_dialogue_prompt([{"role": "user", "content": "PERが低い銘柄"}])
    assert "SECTOR" in prompt  # indicatorとしての説明自体は常に含まれる
    assert "業種名のいずれか一つ" not in prompt  # 業種一覧の案内文は含まれない


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


def test_build_refinement_prompt_includes_strategy_and_feedback():
    pending = {
        "strategy_name": "割安株",
        "conditions": [{"indicator": "PER", "operator": "LESS_THAN", "value": 15}],
    }
    prompt = build_refinement_prompt(pending, "条件が厳しすぎます")
    assert "割安株" in prompt
    assert "条件が厳しすぎます" in prompt
    assert "json" in prompt


def test_build_refinement_prompt_lists_allowed_indicators_and_operators():
    pending = {"strategy_name": "割安株", "conditions": []}
    prompt = build_refinement_prompt(pending, "改善してください")
    assert "DIVIDEND_YIELD" in prompt
    assert "GREATER_EQUAL" in prompt


def test_build_dialogue_prompt_lists_all_pipeline_functions():
    prompt = build_dialogue_prompt([{"role": "user", "content": "PERが低い銘柄"}])
    assert "BACKTEST_RANK" in prompt
    assert "MULTI_STRATEGY_RANK" in prompt
    assert "FILTER_CURRENT_SIGNAL" in prompt
    assert "FILTER_BY_FUNDAMENTALS" in prompt
    assert "SORT_BY" in prompt
    assert "TOP_N" in prompt


def test_parse_dialogue_response_detects_finalized_strategy_json_with_steps():
    raw = (
        '```json\n{"strategy_name": "ゴールデンクロス", "steps": '
        '[{"function": "BACKTEST_RANK", "params": {"strategy": "移動平均クロスオーバー"}}]}\n```'
    )
    result = parse_dialogue_response(raw)
    assert result["kind"] == "strategy"
    assert result["strategy"]["strategy_name"] == "ゴールデンクロス"
