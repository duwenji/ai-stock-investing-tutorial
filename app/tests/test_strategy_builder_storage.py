import pytest
from sqlalchemy.orm import sessionmaker

from db.engine import create_db_engine, init_db
from strategy_builder.storage import load_strategies, save_strategy


@pytest.fixture
def session_factory(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    return sessionmaker(bind=engine)


def test_load_strategies_returns_empty_list_when_none_saved(session_factory):
    assert load_strategies(1, session_factory=session_factory) == []


def test_save_strategy_appends_new_strategy(session_factory):
    save_strategy(
        1, {"strategy_name": "割安成長株", "conditions": []}, session_factory=session_factory
    )
    assert load_strategies(1, session_factory=session_factory) == [
        {"strategy_name": "割安成長株", "conditions": []}
    ]


def test_save_strategy_overwrites_existing_strategy_with_same_name(session_factory):
    save_strategy(
        1, {"strategy_name": "割安成長株", "conditions": [1]}, session_factory=session_factory
    )
    save_strategy(
        1, {"strategy_name": "割安成長株", "conditions": [2]}, session_factory=session_factory
    )
    strategies = load_strategies(1, session_factory=session_factory)
    assert len(strategies) == 1
    assert strategies[0]["conditions"] == [2]


def test_strategies_are_scoped_per_user(session_factory):
    save_strategy(1, {"strategy_name": "A", "conditions": []}, session_factory=session_factory)
    save_strategy(2, {"strategy_name": "B", "conditions": []}, session_factory=session_factory)
    assert [s["strategy_name"] for s in load_strategies(1, session_factory=session_factory)] == ["A"]
    assert [s["strategy_name"] for s in load_strategies(2, session_factory=session_factory)] == ["B"]
