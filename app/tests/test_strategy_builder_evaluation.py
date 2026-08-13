import json

import pytest
from sqlalchemy.orm import sessionmaker

from db.engine import create_db_engine, init_db
from db.models import AiGeneration, AiSession
from strategy_builder.evaluation import (
    build_evaluate_prompt,
    evaluate_strategy,
    run_evaluation_loop,
)


@pytest.fixture
def session_factory(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'ai_log.db'}")
    init_db(engine)
    return sessionmaker(bind=engine)


def test_build_evaluate_prompt_includes_strategy_and_criteria():
    strategy = {
        "strategy_name": "割安株",
        "steps": [
            {
                "function": "FILTER_BY_FUNDAMENTALS",
                "params": {"conditions": [{"indicator": "PER", "operator": "LESS_THAN", "value": 15}]},
            }
        ],
    }
    prompt = build_evaluate_prompt(strategy)
    assert "割安株" in prompt
    assert "PER" in prompt
    assert "pass" in prompt
    assert "各ステップのfunction・params" in prompt
    assert "断定的な投資助言" in prompt


def test_evaluate_strategy_parses_pass_response(session_factory):
    strategy = {"strategy_name": "割安株", "steps": []}
    result = evaluate_strategy(
        strategy,
        call_llm=lambda prompt: '{"pass": true, "feedback": ""}',
        session_factory=session_factory,
    )
    assert result == {"pass": True, "feedback": ""}


def test_evaluate_strategy_falls_back_to_fail_on_invalid_json(session_factory):
    strategy = {"strategy_name": "割安株", "steps": []}
    result = evaluate_strategy(
        strategy, call_llm=lambda prompt: "not json", session_factory=session_factory
    )
    assert result == {"pass": False, "feedback": "評価結果のパースに失敗しました。"}


def test_evaluate_strategy_falls_back_to_fail_when_pass_key_missing(session_factory):
    strategy = {"strategy_name": "割安株", "steps": []}
    result = evaluate_strategy(
        strategy,
        call_llm=lambda prompt: '{"feedback": "何か"}',
        session_factory=session_factory,
    )
    assert result == {"pass": False, "feedback": "評価結果のパースに失敗しました。"}


def test_evaluate_strategy_logs_facts_prompt_and_ai_output(session_factory):
    strategy = {"strategy_name": "割安株", "steps": []}
    evaluate_strategy(
        strategy,
        call_llm=lambda prompt: '{"pass": true, "feedback": ""}',
        session_id="session-1",
        turn_index=3,
        user_id=9,
        session_factory=session_factory,
    )

    with session_factory() as session:
        sessions = session.query(AiSession).all()
        assert len(sessions) == 1
        assert sessions[0].id == "session-1"
        assert sessions[0].feature == "strategy_evaluate"
        assert sessions[0].user_id == 9

        generations = session.query(AiGeneration).all()
        assert len(generations) == 1
        assert generations[0].feature == "strategy_evaluate"
        assert generations[0].turn_index == 3
        assert generations[0].session_id == "session-1"
        assert generations[0].ai_output == '{"pass": true, "feedback": ""}'
        assert json.loads(generations[0].facts) == {"strategy": strategy}


def test_run_evaluation_loop_returns_immediately_when_first_evaluation_passes(session_factory):
    strategy = {
        "strategy_name": "割安株",
        "steps": [{"function": "BACKTEST_RANK", "params": {"strategy": "移動平均クロスオーバー"}}],
    }
    call_count = {"n": 0}

    def fake_call_llm(prompt):
        call_count["n"] += 1
        return '{"pass": true, "feedback": ""}'

    result = run_evaluation_loop(strategy, call_llm=fake_call_llm, session_factory=session_factory)

    assert call_count["n"] == 1
    assert result == {
        "strategy": strategy,
        "iterations": 0,
        "last_feedback": None,
        "next_turn_index": 1,
    }


def test_run_evaluation_loop_refines_and_returns_on_second_pass(session_factory):
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

    result = run_evaluation_loop(strategy, call_llm=fake_call_llm, session_factory=session_factory)

    assert result["strategy"] == refined_strategy
    assert result["iterations"] == 1
    assert result["last_feedback"] == "対象銘柄数を絞ってください"
    assert result["next_turn_index"] == 3


def test_run_evaluation_loop_stops_at_max_iterations_when_never_passes(session_factory):
    strategy = {"strategy_name": "割安株", "steps": []}
    refined_once = {
        "strategy_name": "割安株2",
        "steps": [
            {
                "function": "FILTER_BY_FUNDAMENTALS",
                "params": {"conditions": [{"indicator": "PER", "operator": "LESS_THAN", "value": 10}]},
            }
        ],
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

    result = run_evaluation_loop(
        strategy, call_llm=fake_call_llm, max_iterations=2, session_factory=session_factory
    )

    assert result["strategy"] == refined_once
    assert result["iterations"] == 2
    assert result["last_feedback"] == "まだ不十分です"


def test_run_evaluation_loop_rejects_refinement_missing_steps_key(session_factory):
    strategy = {
        "strategy_name": "ゴールデンクロス",
        "steps": [{"function": "BACKTEST_RANK", "params": {"strategy": "移動平均クロスオーバー"}}],
    }
    # 改善案の応答にstepsキーが無い不正なケース（旧conditions形式が紛れ込む等）。
    invalid_refinement = {"strategy_name": "誤ったスキーマ", "conditions": []}
    responses = iter(
        [
            '{"pass": false, "feedback": "改善してください"}',
            json.dumps(invalid_refinement, ensure_ascii=False),
            '{"pass": false, "feedback": "まだ不十分です"}',
        ]
    )

    def fake_call_llm(prompt):
        return next(responses)

    result = run_evaluation_loop(
        strategy, call_llm=fake_call_llm, max_iterations=2, session_factory=session_factory
    )

    assert result["strategy"] == strategy


def test_run_evaluation_loop_skips_refinement_when_response_is_invalid_json(session_factory):
    strategy = {
        "strategy_name": "割安株",
        "steps": [{"function": "BACKTEST_RANK", "params": {"strategy": "移動平均クロスオーバー"}}],
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

    result = run_evaluation_loop(
        strategy, call_llm=fake_call_llm, max_iterations=3, session_factory=session_factory
    )

    assert result["strategy"] == strategy
    assert result["iterations"] == 1


def test_run_evaluation_loop_logs_evaluate_and_refine_turns_sharing_one_session(session_factory):
    strategy = {"strategy_name": "割安株", "steps": []}
    refined_strategy = {"strategy_name": "割安株2", "steps": []}
    responses = iter(
        [
            '{"pass": false, "feedback": "改善してください"}',
            json.dumps(refined_strategy, ensure_ascii=False),
            '{"pass": true, "feedback": ""}',
        ]
    )

    def fake_call_llm(prompt):
        return next(responses)

    result = run_evaluation_loop(
        strategy,
        call_llm=fake_call_llm,
        session_id="dialogue-session-1",
        turn_index_start=5,
        user_id=3,
        session_factory=session_factory,
    )

    assert result["next_turn_index"] == 8

    with session_factory() as session:
        sessions = session.query(AiSession).all()
        assert len(sessions) == 1
        assert sessions[0].id == "dialogue-session-1"

        generations = session.query(AiGeneration).order_by(AiGeneration.turn_index).all()
        assert [g.feature for g in generations] == [
            "strategy_evaluate",
            "strategy_refine",
            "strategy_evaluate",
        ]
        assert [g.turn_index for g in generations] == [5, 6, 7]
        assert all(g.session_id == "dialogue-session-1" for g in generations)
