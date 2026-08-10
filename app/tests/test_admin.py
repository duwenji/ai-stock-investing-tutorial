import pytest
from sqlalchemy.orm import sessionmaker

from admin import delete_user, list_users, set_admin_status
from db.engine import create_db_engine, init_db
from db.models import CompanyProfile, Holding, SectorDisplaySetting, Strategy, User


@pytest.fixture
def session_factory(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    return sessionmaker(bind=engine)


def test_list_users_returns_all_users_with_expected_fields(session_factory):
    with session_factory() as session:
        session.add(
            User(
                username="taro",
                email="taro@example.com",
                hashed_password="h",
                is_admin=True,
            )
        )
        session.add(User(username="hanako", hashed_password="h", is_admin=False))
        session.commit()

    users = list_users(session_factory=session_factory)
    assert len(users) == 2
    taro = next(u for u in users if u["username"] == "taro")
    assert taro["email"] == "taro@example.com"
    assert taro["is_admin"] is True
    hanako = next(u for u in users if u["username"] == "hanako")
    assert hanako["email"] is None
    assert hanako["is_admin"] is False


def test_set_admin_status_grants_and_revokes(session_factory):
    with session_factory() as session:
        user = User(username="taro", hashed_password="h", is_admin=False)
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = user.id

    set_admin_status(user_id, True, session_factory=session_factory)
    with session_factory() as session:
        assert session.query(User).filter_by(id=user_id).one().is_admin is True

    set_admin_status(user_id, False, session_factory=session_factory)
    with session_factory() as session:
        assert session.query(User).filter_by(id=user_id).one().is_admin is False


def test_delete_user_removes_user_and_related_data(session_factory):
    with session_factory() as session:
        user = User(username="taro", hashed_password="h")
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = user.id

        session.add(CompanyProfile(ticker="7203.T"))
        session.add(Holding(user_id=user_id, ticker="7203.T", shares=1.0, cost=1.0))
        session.add(Strategy(user_id=user_id, strategy_name="A", strategy_json="{}"))
        session.add(
            SectorDisplaySetting(
                user_id=user_id, visible_json="{}", order_json="{}", height_json="{}"
            )
        )
        session.commit()

    delete_user(user_id, session_factory=session_factory)

    with session_factory() as session:
        assert session.query(User).filter_by(id=user_id).count() == 0
        assert session.query(Holding).filter_by(user_id=user_id).count() == 0
        assert session.query(Strategy).filter_by(user_id=user_id).count() == 0
        assert session.query(SectorDisplaySetting).filter_by(user_id=user_id).count() == 0


def test_delete_user_does_not_affect_other_users(session_factory):
    with session_factory() as session:
        user1 = User(username="taro", hashed_password="h")
        user2 = User(username="hanako", hashed_password="h")
        session.add(user1)
        session.add(user2)
        session.commit()
        session.refresh(user1)
        session.refresh(user2)
        user1_id, user2_id = user1.id, user2.id

        session.add(CompanyProfile(ticker="7203.T"))
        session.add(Holding(user_id=user2_id, ticker="7203.T", shares=1.0, cost=1.0))
        session.commit()

    delete_user(user1_id, session_factory=session_factory)

    with session_factory() as session:
        assert session.query(User).filter_by(id=user2_id).count() == 1
        assert session.query(Holding).filter_by(user_id=user2_id).count() == 1
