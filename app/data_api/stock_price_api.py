import yfinance as yf


def fetch_price_history(ticker_symbol: str, period: str = "1mo"):
    ticker = yf.Ticker(ticker_symbol)
    return ticker.history(period=period)


def fetch_fundamentals(ticker_symbol: str) -> dict:
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info
    return {
        "ticker": ticker_symbol,
        "name": info.get("longName"),
        "trailing_pe": info.get("trailingPE"),
        "price_to_book": info.get("priceToBook"),
        "dividend_yield": info.get("dividendYield"),
        "market_cap": info.get("marketCap"),
    }


def fetch_news(ticker_symbol: str, limit: int = 5) -> list[dict]:
    ticker = yf.Ticker(ticker_symbol)
    news_items = ticker.news or []
    return [
        {"title": item.get("title"), "publisher": item.get("publisher")}
        for item in news_items[:limit]
    ]
