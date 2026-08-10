import pandas as pd
import pytest
from sqlalchemy.orm import sessionmaker

from db.engine import create_db_engine, init_db
from db.models import CompanyProfile
from scripts.update_market_data import main, run_update


@pytest.fixture
def session_factory(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine)
    # init_db()はseed_company_profiles.csvから228件のcompany_profilesを自動投入
    # するため、このテストファイルが対象ticker集合を厳密に制御できるよう
    # 一旦全件削除しておく（この時点ではprice_history等の子行はまだ無いため
    # FK違反は起きない）。
    with factory() as session:
        session.query(CompanyProfile).delete()
        session.commit()
    return factory


def _seed_tickers(session_factory, tickers):
    with session_factory() as session:
        for ticker in tickers:
            session.add(CompanyProfile(ticker=ticker))
        session.commit()


def test_run_update_calls_fetch_functions_for_every_company_profile_ticker(
    monkeypatch, session_factory
):
    _seed_tickers(session_factory, ["AAAA.T", "BBBB.T"])

    called_price = []
    called_fundamentals = []
    called_news = []

    def fake_fetch_price_history(ticker, session_factory=None):
        called_price.append(ticker)
        return pd.DataFrame()

    def fake_fetch_fundamentals(ticker, session_factory=None):
        called_fundamentals.append(ticker)
        return {}

    def fake_fetch_news(ticker, session_factory=None):
        called_news.append(ticker)
        return []

    monkeypatch.setattr(
        "scripts.update_market_data.fetch_price_history", fake_fetch_price_history
    )
    monkeypatch.setattr(
        "scripts.update_market_data.fetch_fundamentals", fake_fetch_fundamentals
    )
    monkeypatch.setattr("scripts.update_market_data.fetch_news", fake_fetch_news)

    summary = run_update(session_factory=session_factory)

    assert sorted(called_price) == ["AAAA.T", "BBBB.T"]
    assert sorted(called_fundamentals) == ["AAAA.T", "BBBB.T"]
    assert sorted(called_news) == ["AAAA.T", "BBBB.T"]
    assert summary["price_history"]["success"] == 2
    assert summary["fundamentals"]["success"] == 2
    assert summary["news"]["success"] == 2
    assert summary["price_history"]["failed"] == []


def test_run_update_records_failures_without_stopping_other_tickers(
    monkeypatch, session_factory
):
    _seed_tickers(session_factory, ["AAAA.T", "BBBB.T"])

    def flaky_fetch_price_history(ticker, session_factory=None):
        if ticker == "AAAA.T":
            raise RuntimeError("boom")
        return pd.DataFrame()

    monkeypatch.setattr(
        "scripts.update_market_data.fetch_price_history", flaky_fetch_price_history
    )
    monkeypatch.setattr(
        "scripts.update_market_data.fetch_fundamentals",
        lambda ticker, session_factory=None: {},
    )
    monkeypatch.setattr(
        "scripts.update_market_data.fetch_news", lambda ticker, session_factory=None: []
    )

    summary = run_update(session_factory=session_factory)

    assert summary["price_history"]["success"] == 1
    assert summary["price_history"]["failed"] == ["AAAA.T"]
    assert summary["fundamentals"]["success"] == 2
    assert summary["news"]["success"] == 2


def test_main_exits_zero_when_all_succeed(monkeypatch, session_factory):
    _seed_tickers(session_factory, ["AAAA.T"])
    monkeypatch.setattr(
        "scripts.update_market_data.SessionLocal", session_factory
    )
    monkeypatch.setattr(
        "scripts.update_market_data.fetch_price_history",
        lambda ticker, session_factory=None: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "scripts.update_market_data.fetch_fundamentals",
        lambda ticker, session_factory=None: {},
    )
    monkeypatch.setattr(
        "scripts.update_market_data.fetch_news", lambda ticker, session_factory=None: []
    )
    monkeypatch.setattr("scripts.update_market_data.init_db", lambda engine: None)

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_main_exits_one_when_any_ticker_fails(monkeypatch, session_factory):
    _seed_tickers(session_factory, ["AAAA.T"])
    monkeypatch.setattr(
        "scripts.update_market_data.SessionLocal", session_factory
    )

    def failing_fetch(ticker, session_factory=None):
        raise RuntimeError("boom")

    monkeypatch.setattr("scripts.update_market_data.fetch_price_history", failing_fetch)
    monkeypatch.setattr(
        "scripts.update_market_data.fetch_fundamentals",
        lambda ticker, session_factory=None: {},
    )
    monkeypatch.setattr(
        "scripts.update_market_data.fetch_news", lambda ticker, session_factory=None: []
    )
    monkeypatch.setattr("scripts.update_market_data.init_db", lambda engine: None)

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
