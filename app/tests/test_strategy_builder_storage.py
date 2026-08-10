import json

import pytest
from sqlalchemy.orm import sessionmaker

from db.engine import create_db_engine, init_db
from db.models import User
from strategy_builder.storage import (
    delete_strategy_by_id,
    load_all_strategies,
    load_strategies,
    save_strategy,
    update_strategy_json_by_id,
)


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


def test_load_all_strategies_includes_username_and_parsed_json(session_factory):
    with session_factory() as session:
        user = User(username="taro", hashed_password="h")
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = user.id

    save_strategy(
        user_id, {"strategy_name": "A", "conditions": []}, session_factory=session_factory
    )

    strategies = load_all_strategies(session_factory=session_factory)
    assert len(strategies) == 1
    assert strategies[0]["username"] == "taro"
    assert strategies[0]["strategy_name"] == "A"
    assert strategies[0]["strategy_json"] == {"strategy_name": "A", "conditions": []}


def test_load_all_strategies_spans_multiple_users(session_factory):
    with session_factory() as session:
        user1 = User(username="taro", hashed_password="h")
        user2 = User(username="hanako", hashed_password="h")
        session.add(user1)
        session.add(user2)
        session.commit()
        session.refresh(user1)
        session.refresh(user2)
        user1_id, user2_id = user1.id, user2.id

    save_strategy(
        user1_id, {"strategy_name": "A", "conditions": []}, session_factory=session_factory
    )
    save_strategy(
        user2_id, {"strategy_name": "B", "conditions": []}, session_factory=session_factory
    )

    strategies = load_all_strategies(session_factory=session_factory)
    usernames = sorted(s["username"] for s in strategies)
    assert usernames == ["hanako", "taro"]


def test_delete_strategy_by_id_removes_only_target_row(session_factory):
    with session_factory() as session:
        user = User(username="taro", hashed_password="h")
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = user.id

    save_strategy(
        user_id, {"strategy_name": "A", "conditions": []}, session_factory=session_factory
    )
    save_strategy(
        user_id, {"strategy_name": "B", "conditions": []}, session_factory=session_factory
    )
    strategies = load_all_strategies(session_factory=session_factory)
    target_id = next(s["id"] for s in strategies if s["strategy_name"] == "A")

    delete_strategy_by_id(target_id, session_factory=session_factory)

    remaining = load_all_strategies(session_factory=session_factory)
    assert [s["strategy_name"] for s in remaining] == ["B"]


def test_update_strategy_json_by_id_updates_content_and_syncs_name(session_factory):
    with session_factory() as session:
        user = User(username="taro", hashed_password="h")
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = user.id

    save_strategy(
        user_id, {"strategy_name": "A", "conditions": []}, session_factory=session_factory
    )
    target_id = load_all_strategies(session_factory=session_factory)[0]["id"]

    update_strategy_json_by_id(
        target_id,
        json.dumps({"strategy_name": "A改", "conditions": [{"field": "per"}]}),
        session_factory=session_factory,
    )

    updated = load_all_strategies(session_factory=session_factory)[0]
    assert updated["strategy_name"] == "A改"
    assert updated["strategy_json"]["conditions"] == [{"field": "per"}]


def test_update_strategy_json_by_id_raises_on_invalid_json(session_factory):
    with session_factory() as session:
        user = User(username="taro", hashed_password="h")
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = user.id

    save_strategy(
        user_id, {"strategy_name": "A", "conditions": []}, session_factory=session_factory
    )
    target_id = load_all_strategies(session_factory=session_factory)[0]["id"]

    with pytest.raises(json.JSONDecodeError):
        update_strategy_json_by_id(target_id, "not valid json", session_factory=session_factory)
