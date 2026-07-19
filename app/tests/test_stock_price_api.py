import pandas as pd

import data_api.stock_price_api as stock_price_api


class FakeTicker:
    def __init__(self, symbol):
        self.symbol = symbol

    def history(self, period="1mo"):
        return pd.DataFrame({"Close": [100, 101, 102]})

    @property
    def info(self):
        return {
            "longName": "Fake Corp",
            "trailingPE": 12.3,
            "priceToBook": 1.1,
            "dividendYield": 0.02,
            "marketCap": 1_000_000,
        }

    @property
    def news(self):
        return [
            {"title": "Headline 1", "publisher": "Pub"},
            {"title": "Headline 2", "publisher": "Pub2"},
        ]


class EmptyInfoTicker(FakeTicker):
    @property
    def info(self):
        return {}


def test_fetch_price_history_returns_dataframe(monkeypatch):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    df = stock_price_api.fetch_price_history("7203.T")
    assert list(df["Close"]) == [100, 101, 102]


def test_fetch_fundamentals_maps_info_fields(monkeypatch):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    result = stock_price_api.fetch_fundamentals("7203.T")
    assert result["ticker"] == "7203.T"
    assert result["name"] == "Fake Corp"
    assert result["trailing_pe"] == 12.3
    assert result["price_to_book"] == 1.1
    assert result["dividend_yield"] == 0.02
    assert result["market_cap"] == 1_000_000


def test_fetch_fundamentals_missing_fields_return_none(monkeypatch):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", EmptyInfoTicker)
    result = stock_price_api.fetch_fundamentals("7203.T")
    assert result["trailing_pe"] is None
    assert result["price_to_book"] is None


def test_fetch_news_returns_title_and_publisher(monkeypatch):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    news = stock_price_api.fetch_news("7203.T", limit=1)
    assert news == [{"title": "Headline 1", "publisher": "Pub"}]


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
    assert df1["dividend_yield_pct"].tolist() == [2.0, 2.0]

    df2 = stock_price_api.fetch_universe_fundamentals(
        tickers, tmp_path, fetch_fundamentals=fake_fetch_fundamentals
    )
    assert call_count["n"] == 2
    assert df1["ticker"].tolist() == df2["ticker"].tolist()
