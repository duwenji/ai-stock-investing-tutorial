import pytest
from sqlalchemy.orm import sessionmaker

from auth import build_credentials, get_user_id, persist_new_user, persist_password_update
from db.engine import create_db_engine, init_db
from db.models import User


@pytest.fixture
def session_factory(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    return sessionmaker(bind=engine)


def test_build_credentials_uses_first_and_last_name_when_present(session_factory):
    with session_factory() as session:
        session.add(
            User(
                username="taro",
                email="taro@example.com",
                hashed_password="hashed",
                first_name="太郎",
                last_name="山田",
            )
        )
        session.commit()

    credentials = build_credentials(session_factory=session_factory)
    entry = credentials["usernames"]["taro"]
    assert entry["email"] == "taro@example.com"
    assert entry["password"] == "hashed"
    assert entry["first_name"] == "太郎"
    assert entry["last_name"] == "山田"
    assert "name" not in entry


def test_build_credentials_falls_back_to_username_when_no_name(session_factory):
    with session_factory() as session:
        session.add(User(username="admin", email=None, hashed_password="hashed"))
        session.commit()

    credentials = build_credentials(session_factory=session_factory)
    entry = credentials["usernames"]["admin"]
    assert entry["name"] == "admin"
    assert "first_name" not in entry
    assert "last_name" not in entry


def test_build_credentials_returns_empty_usernames_when_no_users(session_factory):
    assert build_credentials(session_factory=session_factory) == {"usernames": {}}


def test_get_user_id_returns_id_for_existing_username(session_factory):
    with session_factory() as session:
        user = User(username="taro", hashed_password="hashed")
        session.add(user)
        session.commit()
        session.refresh(user)
        expected_id = user.id

    assert get_user_id("taro", session_factory=session_factory) == expected_id


def test_get_user_id_returns_none_for_unknown_username(session_factory):
    assert get_user_id("nobody", session_factory=session_factory) is None


def test_persist_new_user_inserts_row(session_factory):
    user = persist_new_user(
        "taro", "taro@example.com", "hashed-pw", "太郎", "山田", session_factory=session_factory
    )
    assert user.id is not None

    with session_factory() as session:
        stored = session.query(User).filter_by(username="taro").one()
        assert stored.email == "taro@example.com"
        assert stored.hashed_password == "hashed-pw"
        assert stored.first_name == "太郎"
        assert stored.last_name == "山田"


def test_persist_password_update_updates_hash(session_factory):
    persist_new_user("taro", None, "old-hash", session_factory=session_factory)
    persist_password_update("taro", "new-hash", session_factory=session_factory)

    with session_factory() as session:
        stored = session.query(User).filter_by(username="taro").one()
        assert stored.hashed_password == "new-hash"
