import json

import pytest
from sqlalchemy.orm import sessionmaker

from common.ai_generation_log import log_ai_generation
from db.engine import create_db_engine, init_db
from db.models import AiGeneration, AiSession


@pytest.fixture
def session_factory(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'ai_log.db'}")
    init_db(engine)
    return sessionmaker(bind=engine)


def test_log_ai_generation_creates_session_and_generation_on_first_call(session_factory):
    log_ai_generation(
        "session-1",
        "stock_detail_comment",
        facts={"per": 12.0},
        prompt="銘柄について教えて",
        ai_output="AIの回答です",
        turn_index=0,
        ticker="AAA.T",
        user_id=5,
        session_feature="stock_detail",
        session_factory=session_factory,
    )

    with session_factory() as session:
        sessions = session.query(AiSession).all()
        assert len(sessions) == 1
        assert sessions[0].id == "session-1"
        assert sessions[0].feature == "stock_detail"
        assert sessions[0].ticker == "AAA.T"
        assert sessions[0].user_id == 5

        generations = session.query(AiGeneration).all()
        assert len(generations) == 1
        generation = generations[0]
        assert generation.session_id == "session-1"
        assert generation.turn_index == 0
        assert generation.feature == "stock_detail_comment"
        assert json.loads(generation.facts) == {"per": 12.0}
        assert generation.prompt == "銘柄について教えて"
        assert generation.ai_output == "AIの回答です"


def test_log_ai_generation_reuses_existing_session_on_second_call(session_factory):
    log_ai_generation(
        "session-1",
        "stock_detail_comment",
        facts={"per": 12.0},
        prompt="p1",
        ai_output="a1",
        turn_index=0,
        session_factory=session_factory,
    )
    log_ai_generation(
        "session-1",
        "stock_detail_profile",
        facts={"sector": "Tech"},
        prompt="p2",
        ai_output="a2",
        turn_index=1,
        session_factory=session_factory,
    )

    with session_factory() as session:
        assert session.query(AiSession).count() == 1
        generations = session.query(AiGeneration).order_by(AiGeneration.turn_index).all()
        assert len(generations) == 2
        assert generations[0].turn_index == 0
        assert generations[1].turn_index == 1
        assert generations[0].session_id == generations[1].session_id == "session-1"


def test_log_ai_generation_defaults_session_feature_to_feature_when_omitted(session_factory):
    log_ai_generation(
        "session-1",
        "strategy_evaluate",
        facts={"strategy": {}},
        prompt="p",
        ai_output="a",
        session_factory=session_factory,
    )

    with session_factory() as session:
        session_row = session.get(AiSession, "session-1")
        assert session_row.feature == "strategy_evaluate"
