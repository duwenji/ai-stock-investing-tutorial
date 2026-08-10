import pytest
from sqlalchemy.orm import sessionmaker

from db.engine import create_db_engine, init_db
from db.models import CompanyProfile, User
from portfolio_management.storage import load_holdings, save_holdings


@pytest.fixture
def session_factory(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(User(username="user1", hashed_password="h"))
        session.add(User(username="user2", hashed_password="h"))
        session.commit()
    return factory


def test_load_holdings_returns_empty_list_when_none_saved(session_factory):
    assert load_holdings(1, session_factory=session_factory) == []


def test_save_then_load_holdings_roundtrip(session_factory):
    holdings = [{"ticker": "7203.T", "shares": 100.0, "cost": 2500.0}]
    save_holdings(1, holdings, session_factory=session_factory)
    assert load_holdings(1, session_factory=session_factory) == holdings


def test_save_holdings_replaces_previous_holdings(session_factory):
    save_holdings(1, [{"ticker": "A", "shares": 1.0, "cost": 1.0}], session_factory=session_factory)
    save_holdings(1, [{"ticker": "B", "shares": 2.0, "cost": 2.0}], session_factory=session_factory)
    assert load_holdings(1, session_factory=session_factory) == [
        {"ticker": "B", "shares": 2.0, "cost": 2.0}
    ]


def test_holdings_are_scoped_per_user(session_factory):
    save_holdings(1, [{"ticker": "A", "shares": 1.0, "cost": 1.0}], session_factory=session_factory)
    save_holdings(2, [{"ticker": "B", "shares": 2.0, "cost": 2.0}], session_factory=session_factory)
    assert load_holdings(1, session_factory=session_factory) == [
        {"ticker": "A", "shares": 1.0, "cost": 1.0}
    ]
    assert load_holdings(2, session_factory=session_factory) == [
        {"ticker": "B", "shares": 2.0, "cost": 2.0}
    ]


def test_save_holdings_creates_company_profile_stub_for_new_ticker(session_factory):
    save_holdings(1, [{"ticker": "9999.T", "shares": 1.0, "cost": 1.0}], session_factory=session_factory)

    with session_factory() as session:
        assert session.get(CompanyProfile, "9999.T") is not None
