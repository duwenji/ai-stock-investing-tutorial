import json

from strategy_builder.evaluation import (
    build_evaluate_prompt,
    evaluate_strategy,
    run_evaluation_loop,
)


def test_build_evaluate_prompt_includes_strategy_and_criteria():
    strategy = {
        "strategy_name": "割安株",
        "conditions": [{"indicator": "PER", "operator": "LESS_THAN", "value": 15}],
    }
    prompt = build_evaluate_prompt(strategy)
    assert "割安株" in prompt
    assert "PER" in prompt
    assert "pass" in prompt
    assert "断定的な投資助言" in prompt


def test_evaluate_strategy_parses_pass_response():
    strategy = {"strategy_name": "割安株", "conditions": []}
    result = evaluate_strategy(strategy, call_llm=lambda prompt: '{"pass": true, "feedback": ""}')
    assert result == {"pass": True, "feedback": ""}


def test_evaluate_strategy_falls_back_to_fail_on_invalid_json():
    strategy = {"strategy_name": "割安株", "conditions": []}
    result = evaluate_strategy(strategy, call_llm=lambda prompt: "not json")
    assert result == {"pass": False, "feedback": "評価結果のパースに失敗しました。"}


def test_evaluate_strategy_falls_back_to_fail_when_pass_key_missing():
    strategy = {"strategy_name": "割安株", "conditions": []}
    result = evaluate_strategy(strategy, call_llm=lambda prompt: '{"feedback": "何か"}')
    assert result == {"pass": False, "feedback": "評価結果のパースに失敗しました。"}


def test_run_evaluation_loop_returns_immediately_when_first_evaluation_passes():
    strategy = {
        "strategy_name": "割安株",
        "conditions": [{"indicator": "PER", "operator": "LESS_THAN", "value": 15}],
    }
    call_count = {"n": 0}

    def fake_call_llm(prompt):
        call_count["n"] += 1
        return '{"pass": true, "feedback": ""}'

    result = run_evaluation_loop(strategy, call_llm=fake_call_llm)

    assert call_count["n"] == 1
    assert result == {"strategy": strategy, "iterations": 0, "last_feedback": None}


def test_run_evaluation_loop_refines_and_returns_on_second_pass():
    strategy = {
        "strategy_name": "割安株",
        "conditions": [{"indicator": "PER", "operator": "LESS_THAN", "value": 15}],
    }
    refined_strategy = {
        "strategy_name": "割安株（改善）",
        "conditions": [{"indicator": "PER", "operator": "LESS_THAN", "value": 20}],
    }
    responses = iter(
        [
            '{"pass": false, "feedback": "条件が厳しすぎます"}',
            json.dumps(refined_strategy, ensure_ascii=False),
            '{"pass": true, "feedback": ""}',
        ]
    )

    def fake_call_llm(prompt):
        return next(responses)

    result = run_evaluation_loop(strategy, call_llm=fake_call_llm)

    assert result["strategy"] == refined_strategy
    assert result["iterations"] == 1
    assert result["last_feedback"] == "条件が厳しすぎます"


def test_run_evaluation_loop_stops_at_max_iterations_when_never_passes():
    strategy = {"strategy_name": "割安株", "conditions": []}
    refined_once = {
        "strategy_name": "割安株2",
        "conditions": [{"indicator": "PER", "operator": "LESS_THAN", "value": 10}],
    }
    responses = iter(
        [
            '{"pass": false, "feedback": "改善してください"}',
            json.dumps(refined_once, ensure_ascii=False),
            '{"pass": false, "feedback": "まだ不十分です"}',
        ]
    )

    def fake_call_llm(prompt):
        return next(responses)

    result = run_evaluation_loop(strategy, call_llm=fake_call_llm, max_iterations=2)

    assert result["strategy"] == refined_once
    assert result["iterations"] == 2
    assert result["last_feedback"] == "まだ不十分です"


def test_run_evaluation_loop_refines_steps_based_strategy_and_returns_on_second_pass():
    strategy = {
        "strategy_name": "ゴールデンクロス",
        "steps": [{"function": "BACKTEST_RANK", "params": {"strategy": "移動平均クロスオーバー"}}],
    }
    refined_strategy = {
        "strategy_name": "ゴールデンクロス（改善）",
        "steps": [
            {"function": "BACKTEST_RANK", "params": {"strategy": "移動平均クロスオーバー", "top_n": 50}}
        ],
    }
    responses = iter(
        [
            '{"pass": false, "feedback": "対象銘柄数を絞ってください"}',
            json.dumps(refined_strategy, ensure_ascii=False),
            '{"pass": true, "feedback": ""}',
        ]
    )

    def fake_call_llm(prompt):
        return next(responses)

    result = run_evaluation_loop(strategy, call_llm=fake_call_llm)

    assert result["strategy"] == refined_strategy
    assert result["iterations"] == 1


def test_run_evaluation_loop_rejects_refinement_with_wrong_schema_for_steps_strategy():
    strategy = {
        "strategy_name": "ゴールデンクロス",
        "steps": [{"function": "BACKTEST_RANK", "params": {"strategy": "移動平均クロスオーバー"}}],
    }
    # 改善案の応答がconditions形式（旧スキーマ）で返ってきた不正なケース
    wrong_schema_refinement = {
        "strategy_name": "誤ったスキーマ",
        "conditions": [{"indicator": "PER", "operator": "LESS_THAN", "value": 15}],
    }
    responses = iter(
        [
            '{"pass": false, "feedback": "改善してください"}',
            json.dumps(wrong_schema_refinement, ensure_ascii=False),
            '{"pass": false, "feedback": "まだ不十分です"}',
        ]
    )

    def fake_call_llm(prompt):
        return next(responses)

    result = run_evaluation_loop(strategy, call_llm=fake_call_llm, max_iterations=2)

    assert result["strategy"] == strategy


def test_run_evaluation_loop_skips_refinement_when_response_is_invalid_json():
    strategy = {
        "strategy_name": "割安株",
        "conditions": [{"indicator": "PER", "operator": "LESS_THAN", "value": 15}],
    }
    responses = iter(
        [
            '{"pass": false, "feedback": "改善してください"}',
            "not valid json",
            '{"pass": true, "feedback": ""}',
        ]
    )

    def fake_call_llm(prompt):
        return next(responses)

    result = run_evaluation_loop(strategy, call_llm=fake_call_llm, max_iterations=3)

    assert result["strategy"] == strategy
    assert result["iterations"] == 1
