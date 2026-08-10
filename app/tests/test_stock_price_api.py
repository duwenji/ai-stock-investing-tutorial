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
        session.add(
            stock_price_api.PriceHistory(
                ticker="7203.T", date=old_date, open=1, high=1, low=1, close=1, volume=1
            )
        )
        session.commit()

    stock_price_api.fetch_price_history("7203.T", session_factory=session_factory)
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


def test_fetch_news_returns_title_publisher_and_link(monkeypatch):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    news = stock_price_api.fetch_news("7203.T", limit=1)
    assert news == [
        {"title": "Headline 1", "publisher": "Pub", "link": "https://example.com/1"}
    ]


def test_fetch_news_handles_missing_nested_fields(monkeypatch):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", MissingNewsFieldsTicker)
    news = stock_price_api.fetch_news("7203.T", limit=1)
    assert news == [{"title": "Headline only", "publisher": None, "link": None}]


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise stock_price_api.requests.HTTPError(f"status {self.status_code}")


def test_fetch_japanese_name_parses_yahoo_jp_title(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        assert url == "https://finance.yahoo.co.jp/quote/6753.T"
        return FakeResponse(
            "<title>シャープ(株)【6753】：株価・株式情報（夜間PTS含む） - Yahoo!ファイナンス</title>"
        )

    monkeypatch.setattr(stock_price_api.requests, "get", fake_get)
    assert stock_price_api.fetch_japanese_name("6753.T") == "シャープ(株)"


def test_fetch_japanese_name_returns_none_when_title_missing_marker(monkeypatch):
    monkeypatch.setattr(
        stock_price_api.requests,
        "get",
        lambda url, headers=None, timeout=None: FakeResponse(
            "<title>ページが見つかりません - Yahoo!ファイナンス</title>"
        ),
    )
    # マーカー「【」を含まないタイトルはティッカーページではないとみなし None を返す
    assert stock_price_api.fetch_japanese_name("0000.T") is None


def test_fetch_japanese_name_returns_none_on_request_failure(monkeypatch):
    def raise_error(url, headers=None, timeout=None):
        raise stock_price_api.requests.RequestException("network error")

    monkeypatch.setattr(stock_price_api.requests, "get", raise_error)
    assert stock_price_api.fetch_japanese_name("6753.T") is None


def test_fetch_universe_fundamentals_uses_cache_on_second_call(tmp_path):
    call_count = {"n": 0}

    def fake_fetch_fundamentals(ticker_symbol):
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
    df1 = stock_price_api.fetch_universe_fundamentals(
        tickers, tmp_path, fetch_fundamentals=fake_fetch_fundamentals
    )
    assert call_count["n"] == 2
    assert df1["dividend_yield_pct"].tolist() == [0.02, 0.02]

    df2 = stock_price_api.fetch_universe_fundamentals(
        tickers, tmp_path, fetch_fundamentals=fake_fetch_fundamentals
    )
    assert call_count["n"] == 2
    assert df1["ticker"].tolist() == df2["ticker"].tolist()


def test_fetch_universe_fundamentals_converts_roe_and_revenue_growth_to_pct(tmp_path):
    def fake_fetch_fundamentals(ticker_symbol):
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
        ["AAA.T"], tmp_path, fetch_fundamentals=fake_fetch_fundamentals
    )
    assert df["roe_pct"].tolist() == pytest.approx([15.5])
    assert df["revenue_growth_pct"].tolist() == pytest.approx([8.2])


def test_fetch_universe_fundamentals_handles_missing_roe_and_revenue_growth(tmp_path):
    def fake_fetch_fundamentals(ticker_symbol):
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
        ["AAA.T"], tmp_path, fetch_fundamentals=fake_fetch_fundamentals
    )
    assert df["roe_pct"].iloc[0] is None or pd.isna(df["roe_pct"].iloc[0])
    assert df["revenue_growth_pct"].iloc[0] is None or pd.isna(df["revenue_growth_pct"].iloc[0])


def test_fetch_universe_fundamentals_skips_ticker_that_raises_and_keeps_others(tmp_path):
    def fake_fetch_fundamentals(ticker_symbol):
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
        tickers, tmp_path, fetch_fundamentals=fake_fetch_fundamentals
    )
    assert sorted(df["ticker"].tolist()) == ["AAA.T", "CCC.T"]


def test_fetch_universe_fundamentals_logs_duration(tmp_path, caplog):
    def fake_fetch_fundamentals(ticker_symbol):
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
            ["AAA.T"], tmp_path, fetch_fundamentals=fake_fetch_fundamentals
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


def test_fetch_news_logs_request_and_response(monkeypatch, caplog):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_news("7203.T", limit=1)

    assert "newsリクエスト: ticker=7203.T limit=1" in caplog.text
    assert "newsレスポンス: ticker=7203.T" in caplog.text
    assert "Headline 1" in caplog.text


def test_fetch_japanese_name_logs_request_and_response(monkeypatch, caplog):
    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(
            "<title>シャープ(株)【6753】：株価・株式情報（夜間PTS含む） - Yahoo!ファイナンス</title>"
        )

    monkeypatch.setattr(stock_price_api.requests, "get", fake_get)
    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_japanese_name("6753.T")

    assert "日本語銘柄名リクエスト: url=https://finance.yahoo.co.jp/quote/6753.T" in caplog.text
    assert "日本語銘柄名レスポンス: url=https://finance.yahoo.co.jp/quote/6753.T" in caplog.text
    assert "シャープ" in caplog.text


def test_fetch_universe_price_histories_uses_cache_on_second_call(tmp_path):
    call_count = {"n": 0}
    dates = pd.date_range("2026-01-01", periods=3, freq="D")

    def fake_fetch_price_history(ticker_symbol, period="1mo"):
        call_count["n"] += 1
        return pd.DataFrame({"Close": [10.0, 11.0, 12.0]}, index=dates)

    tickers = ["AAA.T", "BBB.T"]
    result1 = stock_price_api.fetch_universe_price_histories(
        tickers, "1y", tmp_path, fetch_price_history=fake_fetch_price_history
    )
    assert call_count["n"] == 2
    assert result1["AAA.T"].tolist() == [10.0, 11.0, 12.0]

    result2 = stock_price_api.fetch_universe_price_histories(
        tickers, "1y", tmp_path, fetch_price_history=fake_fetch_price_history
    )
    assert call_count["n"] == 2
    assert result2["AAA.T"].tolist() == [10.0, 11.0, 12.0]


def test_fetch_universe_price_histories_skips_failed_ticker(tmp_path):
    dates = pd.date_range("2026-01-01", periods=2, freq="D")

    def fake_fetch_price_history(ticker_symbol, period="1mo"):
        if ticker_symbol == "BAD.T":
            raise ValueError("boom")
        return pd.DataFrame({"Close": [1.0, 2.0]}, index=dates)

    result = stock_price_api.fetch_universe_price_histories(
        ["AAA.T", "BAD.T"], "1y", tmp_path, fetch_price_history=fake_fetch_price_history
    )
    assert list(result.keys()) == ["AAA.T"]


def test_fetch_universe_price_histories_skips_empty_history(tmp_path):
    def fake_fetch_price_history(ticker_symbol, period="1mo"):
        return pd.DataFrame({"Close": []})

    result = stock_price_api.fetch_universe_price_histories(
        ["AAA.T"], "1y", tmp_path, fetch_price_history=fake_fetch_price_history
    )
    assert result == {}


def test_fetch_japanese_name_logs_warning_on_request_failure(monkeypatch, caplog):
    def raise_error(url, headers=None, timeout=None):
        raise stock_price_api.requests.RequestException("network error")

    monkeypatch.setattr(stock_price_api.requests, "get", raise_error)
    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_japanese_name("6753.T")

    assert "日本語銘柄名取得失敗: url=https://finance.yahoo.co.jp/quote/6753.T" in caplog.text


def test_fetch_company_profile_maps_info_fields(monkeypatch):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    result = stock_price_api.fetch_company_profile("7203.T")
    assert result["ticker"] == "7203.T"
    assert result["sector"] == "Consumer Cyclical"
    assert result["industry"] == "Auto Manufacturers"
    assert result["business_summary"] == "Test business summary text."


def test_fetch_company_profile_missing_fields_return_none(monkeypatch):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", EmptyInfoTicker)
    result = stock_price_api.fetch_company_profile("7203.T")
    assert result["sector"] is None
    assert result["industry"] is None
    assert result["business_summary"] is None


def test_fetch_company_profile_logs_request_and_response(monkeypatch, caplog):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_company_profile("7203.T")

    assert "company profileリクエスト: ticker=7203.T" in caplog.text
    assert "company profileレスポンス: ticker=7203.T" in caplog.text
    assert "Auto Manufacturers" in caplog.text
