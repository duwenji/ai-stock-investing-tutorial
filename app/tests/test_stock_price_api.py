import datetime
import logging

import pandas as pd
import pytest
from sqlalchemy.orm import sessionmaker

import data_api.stock_price_api as stock_price_api
from db.engine import create_db_engine, init_db


class FakeTicker:
    def __init__(self, symbol):
        self.symbol = symbol

    def history(self, period="1mo"):
        dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=3, freq="D")
        return pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0],
                "High": [105.0, 106.0, 107.0],
                "Low": [99.0, 100.0, 101.0],
                "Close": [100.0, 101.0, 102.0],
                "Volume": [1000.0, 1100.0, 1200.0],
            },
            index=dates,
        )

    @property
    def info(self):
        return {
            "longName": "Fake Corp",
            "trailingPE": 12.3,
            "priceToBook": 1.1,
            "dividendYield": 0.02,
            "marketCap": 1_000_000,
            "returnOnEquity": 0.155,
            "revenueGrowth": 0.082,
            "sector": "Consumer Cyclical",
            "industry": "Auto Manufacturers",
            "longBusinessSummary": "Test business summary text.",
        }

    @property
    def news(self):
        return [
            {
                "content": {
                    "title": "Headline 1",
                    "provider": {"displayName": "Pub"},
                    "clickThroughUrl": {"url": "https://example.com/1"},
                }
            },
            {
                "content": {
                    "title": "Headline 2",
                    "provider": {"displayName": "Pub2"},
                    "clickThroughUrl": {"url": "https://example.com/2"},
                }
            },
        ]


class MissingNewsFieldsTicker(FakeTicker):
    @property
    def news(self):
        return [{"content": {"title": "Headline only"}}]


class EmptyInfoTicker(FakeTicker):
    @property
    def info(self):
        return {}


def test_fetch_price_history_returns_dataframe(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    df = stock_price_api.fetch_price_history("7203.T", session_factory=session_factory)
    assert list(df["Close"]) == [100.0, 101.0, 102.0]


def test_fetch_price_history_reuses_db_on_second_call(monkeypatch, tmp_path):
    call_count = {"n": 0}

    class CountingTicker(FakeTicker):
        def history(self, period="1mo"):
            call_count["n"] += 1
            return super().history(period=period)

    monkeypatch.setattr(stock_price_api.yf, "Ticker", CountingTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_price_history("7203.T", session_factory=session_factory)
    assert call_count["n"] == 1

    stock_price_api.fetch_price_history("7203.T", session_factory=session_factory)
    assert call_count["n"] == 1


def test_fetch_price_history_refetches_when_stale(monkeypatch, tmp_path):
    call_count = {"n": 0}

    class CountingTicker(FakeTicker):
        def history(self, period="1mo"):
            call_count["n"] += 1
            return super().history(period=period)

    monkeypatch.setattr(stock_price_api.yf, "Ticker", CountingTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    old_date = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
    with session_factory() as session:
        session.add(stock_price_api.CompanyProfile(ticker="TEST1.T"))
        session.add(
            stock_price_api.PriceHistory(
                ticker="TEST1.T", date=old_date, open=1, high=1, low=1, close=1, volume=1
            )
        )
        session.commit()

    stock_price_api.fetch_price_history("TEST1.T", session_factory=session_factory)
    assert call_count["n"] == 1


def test_upsert_price_history_skips_existing_dates(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    history = pd.DataFrame(
        {
            "Open": [1.0, 2.0, 3.0],
            "High": [1.0, 2.0, 3.0],
            "Low": [1.0, 2.0, 3.0],
            "Close": [1.0, 2.0, 3.0],
            "Volume": [1.0, 2.0, 3.0],
        },
        index=dates,
    )

    with session_factory() as session:
        stock_price_api._upsert_price_history(session, "7203.T", history)
        session.commit()
        assert session.query(stock_price_api.PriceHistory).count() == 3

    with session_factory() as session:
        stock_price_api._upsert_price_history(session, "7203.T", history)
        session.commit()
        assert session.query(stock_price_api.PriceHistory).count() == 3


def test_fetch_fundamentals_maps_info_fields(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    result = stock_price_api.fetch_fundamentals("7203.T", session_factory=session_factory)
    assert result["ticker"] == "7203.T"
    assert result["name"] == "Fake Corp"
    assert result["trailing_pe"] == 12.3
    assert result["price_to_book"] == 1.1
    assert result["dividend_yield"] == 0.02
    assert result["market_cap"] == 1_000_000
    assert result["return_on_equity"] == 0.155
    assert result["revenue_growth"] == 0.082


def test_fetch_fundamentals_missing_fields_return_none(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", EmptyInfoTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    result = stock_price_api.fetch_fundamentals("7203.T", session_factory=session_factory)
    assert result["trailing_pe"] is None
    assert result["price_to_book"] is None
    assert result["return_on_equity"] is None
    assert result["revenue_growth"] is None


def test_fetch_fundamentals_reuses_snapshot_on_second_call_same_day(monkeypatch, tmp_path):
    call_count = {"n": 0}

    class CountingTicker(FakeTicker):
        @property
        def info(self):
            call_count["n"] += 1
            return super().info

    monkeypatch.setattr(stock_price_api.yf, "Ticker", CountingTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_fundamentals("7203.T", session_factory=session_factory)
    assert call_count["n"] == 1
    stock_price_api.fetch_fundamentals("7203.T", session_factory=session_factory)
    assert call_count["n"] == 1


def test_fetch_news_returns_title_publisher_and_link(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    news = stock_price_api.fetch_news("7203.T", limit=1, session_factory=session_factory)
    assert news == [
        {"title": "Headline 1", "publisher": "Pub", "link": "https://example.com/1"}
    ]


def test_fetch_news_handles_missing_nested_fields(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", MissingNewsFieldsTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    news = stock_price_api.fetch_news("7203.T", limit=1, session_factory=session_factory)
    assert news == [{"title": "Headline only", "publisher": None, "link": None}]


def test_fetch_news_accumulates_across_calls_without_duplicates(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_news("7203.T", limit=5, session_factory=session_factory)
    stock_price_api.fetch_news("7203.T", limit=5, session_factory=session_factory)

    with session_factory() as session:
        assert (
            session.query(stock_price_api.TickerNews).filter_by(ticker="7203.T").count() == 2
        )


def test_fetch_news_deduplicates_articles_without_link(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", MissingNewsFieldsTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_news("7203.T", limit=5, session_factory=session_factory)
    stock_price_api.fetch_news("7203.T", limit=5, session_factory=session_factory)

    with session_factory() as session:
        assert (
            session.query(stock_price_api.TickerNews).filter_by(ticker="7203.T").count() == 1
        )


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise stock_price_api.requests.HTTPError(f"status {self.status_code}")


def test_fetch_japanese_name_parses_yahoo_jp_title(monkeypatch, tmp_path):
    def fake_get(url, headers=None, timeout=None):
        assert url == "https://finance.yahoo.co.jp/quote/6753.T"
        return FakeResponse(
            "<title>シャープ(株)【6753】：株価・株式情報（夜間PTS含む） - Yahoo!ファイナンス</title>"
        )

    monkeypatch.setattr(stock_price_api.requests, "get", fake_get)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    assert stock_price_api.fetch_japanese_name(
        "6753.T", session_factory=session_factory
    ) == "シャープ(株)"


def test_fetch_japanese_name_returns_none_when_title_missing_marker(monkeypatch, tmp_path):
    monkeypatch.setattr(
        stock_price_api.requests,
        "get",
        lambda url, headers=None, timeout=None: FakeResponse(
            "<title>ページが見つかりません - Yahoo!ファイナンス</title>"
        ),
    )
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    # マーカー「【」を含まないタイトルはティッカーページではないとみなし None を返す
    assert stock_price_api.fetch_japanese_name("0000.T", session_factory=session_factory) is None


def test_fetch_japanese_name_returns_none_on_request_failure(monkeypatch, tmp_path):
    def raise_error(url, headers=None, timeout=None):
        raise stock_price_api.requests.RequestException("network error")

    monkeypatch.setattr(stock_price_api.requests, "get", raise_error)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    assert stock_price_api.fetch_japanese_name("6753.T", session_factory=session_factory) is None


def test_fetch_japanese_name_reuses_db_within_freshness_window(monkeypatch, tmp_path):
    call_count = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        call_count["n"] += 1
        return FakeResponse(
            "<title>シャープ(株)【6753】：株価・株式情報（夜間PTS含む） - Yahoo!ファイナンス</title>"
        )

    monkeypatch.setattr(stock_price_api.requests, "get", fake_get)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_japanese_name("6753.T", session_factory=session_factory)
    assert call_count["n"] == 1
    stock_price_api.fetch_japanese_name("6753.T", session_factory=session_factory)
    assert call_count["n"] == 1


def test_company_profile_and_japanese_name_update_independently(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)

    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(
            "<title>シャープ(株)【6753】：株価・株式情報（夜間PTS含む） - Yahoo!ファイナンス</title>"
        )

    monkeypatch.setattr(stock_price_api.requests, "get", fake_get)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_japanese_name("6753.T", session_factory=session_factory)
    stock_price_api.fetch_company_profile("6753.T", session_factory=session_factory)

    with session_factory() as session:
        row = session.get(stock_price_api.CompanyProfile, "6753.T")
        assert row.name == "シャープ(株)"
        assert row.sector == "Consumer Cyclical"


def test_fetch_universe_fundamentals_calls_fetch_fundamentals_per_ticker():
    call_count = {"n": 0}

    def fake_fetch_fundamentals(ticker_symbol, session_factory=None):
        call_count["n"] += 1
        return {
            "ticker": ticker_symbol,
            "name": ticker_symbol,
            "trailing_pe": 10.0,
            "price_to_book": 1.0,
            "dividend_yield": 0.02,
            "market_cap": 1,
        }

    tickers = ["AAA.T", "BBB.T"]
    df = stock_price_api.fetch_universe_fundamentals(
        tickers, fetch_fundamentals=fake_fetch_fundamentals
    )
    assert call_count["n"] == 2
    assert df["dividend_yield_pct"].tolist() == [0.02, 0.02]


def test_fetch_universe_fundamentals_converts_roe_and_revenue_growth_to_pct():
    def fake_fetch_fundamentals(ticker_symbol, session_factory=None):
        return {
            "ticker": ticker_symbol,
            "name": ticker_symbol,
            "trailing_pe": 10.0,
            "price_to_book": 1.0,
            "dividend_yield": 0.02,
            "market_cap": 1,
            "return_on_equity": 0.155,
            "revenue_growth": 0.082,
        }

    df = stock_price_api.fetch_universe_fundamentals(
        ["AAA.T"], fetch_fundamentals=fake_fetch_fundamentals
    )
    assert df["roe_pct"].tolist() == pytest.approx([15.5])
    assert df["revenue_growth_pct"].tolist() == pytest.approx([8.2])


def test_fetch_universe_fundamentals_handles_missing_roe_and_revenue_growth():
    def fake_fetch_fundamentals(ticker_symbol, session_factory=None):
        return {
            "ticker": ticker_symbol,
            "name": ticker_symbol,
            "trailing_pe": 10.0,
            "price_to_book": 1.0,
            "dividend_yield": 0.02,
            "market_cap": 1,
            "return_on_equity": None,
            "revenue_growth": None,
        }

    df = stock_price_api.fetch_universe_fundamentals(
        ["AAA.T"], fetch_fundamentals=fake_fetch_fundamentals
    )
    assert df["roe_pct"].iloc[0] is None or pd.isna(df["roe_pct"].iloc[0])
    assert df["revenue_growth_pct"].iloc[0] is None or pd.isna(df["revenue_growth_pct"].iloc[0])


def test_fetch_universe_fundamentals_skips_ticker_that_raises_and_keeps_others():
    def fake_fetch_fundamentals(ticker_symbol, session_factory=None):
        if ticker_symbol == "BAD.T":
            raise ValueError("boom")
        return {
            "ticker": ticker_symbol,
            "name": ticker_symbol,
            "trailing_pe": 10.0,
            "price_to_book": 1.0,
            "dividend_yield": 0.02,
            "market_cap": 1,
        }

    tickers = ["AAA.T", "BAD.T", "CCC.T"]
    df = stock_price_api.fetch_universe_fundamentals(
        tickers, fetch_fundamentals=fake_fetch_fundamentals
    )
    assert sorted(df["ticker"].tolist()) == ["AAA.T", "CCC.T"]


def test_fetch_universe_fundamentals_logs_duration(caplog):
    def fake_fetch_fundamentals(ticker_symbol, session_factory=None):
        return {
            "ticker": ticker_symbol,
            "name": ticker_symbol,
            "trailing_pe": 10.0,
            "price_to_book": 1.0,
            "dividend_yield": 0.02,
            "market_cap": 1,
        }

    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_universe_fundamentals(
            ["AAA.T"], fetch_fundamentals=fake_fetch_fundamentals
        )

    assert "ユニバースfundamentals一括取得" in caplog.text
    assert "を開始" in caplog.text
    assert "が完了しました" in caplog.text


def test_fetch_price_history_logs_request_and_response(monkeypatch, caplog, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_price_history("7203.T", session_factory=session_factory)

    assert (
        f"株価履歴リクエスト: ticker=7203.T period={stock_price_api._MAX_FETCH_PERIOD}"
        in caplog.text
    )
    assert "株価履歴レスポンス: ticker=7203.T" in caplog.text
    assert "101" in caplog.text


def test_fetch_fundamentals_logs_request_and_response(monkeypatch, caplog, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_fundamentals("7203.T", session_factory=session_factory)

    assert "fundamentalsリクエスト: ticker=7203.T" in caplog.text
    assert "fundamentalsレスポンス: ticker=7203.T" in caplog.text
    assert "Fake Corp" in caplog.text


def test_fetch_news_logs_request_and_response(monkeypatch, caplog, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_news("7203.T", limit=1, session_factory=session_factory)

    assert "newsリクエスト: ticker=7203.T limit=1" in caplog.text
    assert "newsレスポンス: ticker=7203.T" in caplog.text
    assert "Headline 1" in caplog.text


def test_fetch_japanese_name_logs_request_and_response(monkeypatch, caplog, tmp_path):
    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(
            "<title>シャープ(株)【6753】：株価・株式情報（夜間PTS含む） - Yahoo!ファイナンス</title>"
        )

    monkeypatch.setattr(stock_price_api.requests, "get", fake_get)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_japanese_name("6753.T", session_factory=session_factory)

    assert "日本語銘柄名リクエスト: url=https://finance.yahoo.co.jp/quote/6753.T" in caplog.text
    assert "日本語銘柄名レスポンス: url=https://finance.yahoo.co.jp/quote/6753.T" in caplog.text
    assert "シャープ" in caplog.text


def test_fetch_universe_price_histories_calls_fetch_price_history_per_ticker():
    call_count = {"n": 0}
    dates = pd.date_range("2026-01-01", periods=3, freq="D")

    def fake_fetch_price_history(ticker_symbol, period="1mo", session_factory=None):
        call_count["n"] += 1
        return pd.DataFrame({"Close": [10.0, 11.0, 12.0]}, index=dates)

    tickers = ["AAA.T", "BBB.T"]
    result = stock_price_api.fetch_universe_price_histories(
        tickers, "1y", fetch_price_history=fake_fetch_price_history
    )
    assert call_count["n"] == 2
    assert result["AAA.T"].tolist() == [10.0, 11.0, 12.0]


def test_fetch_universe_price_histories_skips_failed_ticker():
    dates = pd.date_range("2026-01-01", periods=2, freq="D")

    def fake_fetch_price_history(ticker_symbol, period="1mo", session_factory=None):
        if ticker_symbol == "BAD.T":
            raise ValueError("boom")
        return pd.DataFrame({"Close": [1.0, 2.0]}, index=dates)

    result = stock_price_api.fetch_universe_price_histories(
        ["AAA.T", "BAD.T"], "1y", fetch_price_history=fake_fetch_price_history
    )
    assert list(result.keys()) == ["AAA.T"]


def test_fetch_universe_price_histories_skips_empty_history():
    def fake_fetch_price_history(ticker_symbol, period="1mo", session_factory=None):
        return pd.DataFrame({"Close": []})

    result = stock_price_api.fetch_universe_price_histories(
        ["AAA.T"], "1y", fetch_price_history=fake_fetch_price_history
    )
    assert result == {}


def test_fetch_japanese_name_logs_warning_on_request_failure(monkeypatch, caplog, tmp_path):
    def raise_error(url, headers=None, timeout=None):
        raise stock_price_api.requests.RequestException("network error")

    monkeypatch.setattr(stock_price_api.requests, "get", raise_error)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_japanese_name("6753.T", session_factory=session_factory)

    assert "日本語銘柄名取得失敗: url=https://finance.yahoo.co.jp/quote/6753.T" in caplog.text


def test_fetch_company_profile_maps_info_fields(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    result = stock_price_api.fetch_company_profile("7203.T", session_factory=session_factory)
    assert result["ticker"] == "7203.T"
    assert result["sector"] == "Consumer Cyclical"
    assert result["industry"] == "Auto Manufacturers"
    assert result["business_summary"] == "Test business summary text."


def test_fetch_company_profile_missing_fields_return_none(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", EmptyInfoTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    result = stock_price_api.fetch_company_profile("7203.T", session_factory=session_factory)
    assert result["sector"] is None
    assert result["industry"] is None
    assert result["business_summary"] is None


def test_fetch_company_profile_reuses_db_within_freshness_window(monkeypatch, tmp_path):
    call_count = {"n": 0}

    class CountingTicker(FakeTicker):
        @property
        def info(self):
            call_count["n"] += 1
            return super().info

    monkeypatch.setattr(stock_price_api.yf, "Ticker", CountingTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_company_profile("7203.T", session_factory=session_factory)
    assert call_count["n"] == 1
    stock_price_api.fetch_company_profile("7203.T", session_factory=session_factory)
    assert call_count["n"] == 1


def test_fetch_company_profile_refetches_when_stale(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    old_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=31)
    with session_factory() as session:
        session.add(
            stock_price_api.CompanyProfile(
                ticker="TEST1.T", sector="Old", industry="Old", profile_updated_at=old_time
            )
        )
        session.commit()

    result = stock_price_api.fetch_company_profile("TEST1.T", session_factory=session_factory)
    assert result["sector"] == "Consumer Cyclical"


def test_fetch_company_profile_logs_request_and_response(monkeypatch, caplog, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_company_profile("7203.T", session_factory=session_factory)

    assert "company profileリクエスト: ticker=7203.T" in caplog.text
    assert "company profileレスポンス: ticker=7203.T" in caplog.text
    assert "Auto Manufacturers" in caplog.text


def test_load_price_history_for_ticker_returns_rows_sorted_by_date(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(stock_price_api.CompanyProfile(ticker="TEST1.T"))
        session.add(
            stock_price_api.PriceHistory(
                ticker="TEST1.T", date="2026-01-02", open=2, high=2, low=2, close=2, volume=2
            )
        )
        session.add(
            stock_price_api.PriceHistory(
                ticker="TEST1.T", date="2026-01-01", open=1, high=1, low=1, close=1, volume=1
            )
        )
        session.commit()

    rows = stock_price_api.load_price_history_for_ticker(
        "TEST1.T", session_factory=session_factory
    )
    assert [r["date"] for r in rows] == ["2026-01-01", "2026-01-02"]
    assert rows[0]["open"] == 1.0


def test_save_price_history_for_ticker_replaces_existing_rows(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.save_price_history_for_ticker(
        "7203.T",
        [
            {
                "date": "2026-01-01",
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 1.0,
            }
        ],
        session_factory=session_factory,
    )
    stock_price_api.save_price_history_for_ticker(
        "7203.T",
        [
            {
                "date": "2026-01-02",
                "open": 2.0,
                "high": 2.0,
                "low": 2.0,
                "close": 2.0,
                "volume": 2.0,
            }
        ],
        session_factory=session_factory,
    )

    rows = stock_price_api.load_price_history_for_ticker(
        "7203.T", session_factory=session_factory
    )
    assert [r["date"] for r in rows] == ["2026-01-02"]


def test_save_price_history_for_ticker_does_not_affect_other_tickers(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.save_price_history_for_ticker(
        "AAA.T",
        [
            {
                "date": "2026-01-01",
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 1.0,
            }
        ],
        session_factory=session_factory,
    )
    stock_price_api.save_price_history_for_ticker(
        "BBB.T",
        [
            {
                "date": "2026-01-01",
                "open": 2.0,
                "high": 2.0,
                "low": 2.0,
                "close": 2.0,
                "volume": 2.0,
            }
        ],
        session_factory=session_factory,
    )
    stock_price_api.save_price_history_for_ticker("AAA.T", [], session_factory=session_factory)

    assert (
        stock_price_api.load_price_history_for_ticker("AAA.T", session_factory=session_factory)
        == []
    )
    bbb_rows = stock_price_api.load_price_history_for_ticker(
        "BBB.T", session_factory=session_factory
    )
    assert len(bbb_rows) == 1


def test_load_fundamentals_snapshots_for_ticker_returns_all_fields(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(stock_price_api.CompanyProfile(ticker="TEST1.T"))
        session.add(
            stock_price_api.FundamentalsSnapshot(
                ticker="TEST1.T", snapshot_date="2026-01-01", trailing_pe=12.3, market_cap=1000
            )
        )
        session.commit()

    rows = stock_price_api.load_fundamentals_snapshots_for_ticker(
        "TEST1.T", session_factory=session_factory
    )
    assert len(rows) == 1
    assert rows[0]["snapshot_date"] == "2026-01-01"
    assert rows[0]["trailing_pe"] == 12.3
    assert rows[0]["market_cap"] == 1000


def test_save_fundamentals_snapshots_for_ticker_replaces_existing_rows(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.save_fundamentals_snapshots_for_ticker(
        "7203.T",
        [{"snapshot_date": "2026-01-01", "trailing_pe": 10.0}],
        session_factory=session_factory,
    )
    stock_price_api.save_fundamentals_snapshots_for_ticker(
        "7203.T",
        [{"snapshot_date": "2026-01-02", "trailing_pe": 20.0}],
        session_factory=session_factory,
    )

    rows = stock_price_api.load_fundamentals_snapshots_for_ticker(
        "7203.T", session_factory=session_factory
    )
    assert [r["snapshot_date"] for r in rows] == ["2026-01-02"]
    assert rows[0]["trailing_pe"] == 20.0


def test_load_company_profile_returns_none_when_missing(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    assert (
        stock_price_api.load_company_profile("TEST1.T", session_factory=session_factory) is None
    )


def test_save_company_profile_fields_creates_new_row(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.save_company_profile_fields(
        "7203.T",
        "トヨタ自動車",
        "Consumer Cyclical",
        "Auto Manufacturers",
        "概要",
        session_factory=session_factory,
    )

    profile = stock_price_api.load_company_profile("7203.T", session_factory=session_factory)
    assert profile["name"] == "トヨタ自動車"
    assert profile["sector"] == "Consumer Cyclical"
    assert profile["industry"] == "Auto Manufacturers"
    assert profile["business_summary"] == "概要"


def test_save_company_profile_fields_updates_existing_row(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(stock_price_api.CompanyProfile(ticker="TEST1.T", sector="Old"))
        session.commit()

    stock_price_api.save_company_profile_fields(
        "TEST1.T",
        "トヨタ自動車",
        "Consumer Cyclical",
        "Auto Manufacturers",
        "概要",
        session_factory=session_factory,
    )

    profile = stock_price_api.load_company_profile("TEST1.T", session_factory=session_factory)
    assert profile["sector"] == "Consumer Cyclical"


def test_fetch_price_history_creates_company_profile_stub_for_new_ticker(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_price_history("7203.T", session_factory=session_factory)

    with session_factory() as session:
        assert session.get(stock_price_api.CompanyProfile, "7203.T") is not None


def test_fetch_fundamentals_creates_company_profile_stub_for_new_ticker(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_fundamentals("7203.T", session_factory=session_factory)

    with session_factory() as session:
        assert session.get(stock_price_api.CompanyProfile, "7203.T") is not None


def test_fetch_news_creates_company_profile_stub_for_new_ticker(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_news("7203.T", limit=1, session_factory=session_factory)

    with session_factory() as session:
        assert session.get(stock_price_api.CompanyProfile, "7203.T") is not None


def test_fetch_price_history_before_fetch_company_profile_does_not_violate_foreign_key(
    monkeypatch, tmp_path
):
    """stock_detail.generate_stock_detailはfetch_price_historyをfetch_company_profileより
    先に呼ぶため、その呼び出し順序でもFK違反にならないことを確認する。"""
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_price_history("7203.T", session_factory=session_factory)
    profile = stock_price_api.fetch_company_profile("7203.T", session_factory=session_factory)
    assert profile["sector"] == "Consumer Cyclical"


def test_save_price_history_for_ticker_creates_company_profile_stub_for_new_ticker(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.save_price_history_for_ticker(
        "9999.T",
        [
            {
                "date": "2026-01-01",
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 1.0,
            }
        ],
        session_factory=session_factory,
    )

    with session_factory() as session:
        assert session.get(stock_price_api.CompanyProfile, "9999.T") is not None


def test_save_fundamentals_snapshots_for_ticker_creates_company_profile_stub_for_new_ticker(
    tmp_path,
):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.save_fundamentals_snapshots_for_ticker(
        "9999.T",
        [{"snapshot_date": "2026-01-01", "trailing_pe": 10.0}],
        session_factory=session_factory,
    )

    with session_factory() as session:
        assert session.get(stock_price_api.CompanyProfile, "9999.T") is not None
