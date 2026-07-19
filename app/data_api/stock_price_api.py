import hashlib
import json
from pathlib import Path

import pandas as pd
import yfinance as yf

from common.cache import read_cache, write_cache


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
    result = []
    for item in news_items[:limit]:
        content = item.get("content") or {}
        provider = content.get("provider") or {}
        link_info = content.get("clickThroughUrl") or content.get("canonicalUrl") or {}
        result.append(
            {
                "title": content.get("title"),
                "publisher": provider.get("displayName"),
                "link": link_info.get("url"),
            }
        )
    return result


def fetch_universe_fundamentals(
    tickers: list[str],
    cache_dir: Path,
    fetch_fundamentals=fetch_fundamentals,
) -> pd.DataFrame:
    cache_key = "universe-" + hashlib.sha256(
        "-".join(sorted(tickers)).encode("utf-8")
    ).hexdigest()[:12]
    cached = read_cache(cache_dir, cache_key)
    if cached is not None:
        return pd.DataFrame(json.loads(cached))

    rows = []
    for ticker_symbol in tickers:
        data = fetch_fundamentals(ticker_symbol)
        rows.append(
            {
                "ticker": data.get("ticker", ticker_symbol),
                "name": data.get("name"),
                "per": data.get("trailing_pe"),
                "pbr": data.get("price_to_book"),
                # yfinance's dividendYield is already a percentage number
                # (e.g. 3.45 means 3.45%), not a fraction to scale up.
                "dividend_yield_pct": data.get("dividend_yield"),
                "market_cap": data.get("market_cap"),
            }
        )
    df = pd.DataFrame(rows)
    write_cache(cache_dir, cache_key, df.to_json(orient="records", force_ascii=False))
    return df
