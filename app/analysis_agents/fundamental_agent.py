from data_api.stock_price_api import fetch_fundamentals as default_fetch_fundamentals


def analyze_fundamentals(
    ticker_symbol: str, fetch_fundamentals=default_fetch_fundamentals
) -> dict:
    data = fetch_fundamentals(ticker_symbol)
    return {
        "ticker": ticker_symbol,
        "per": data.get("trailing_pe"),
        "pbr": data.get("price_to_book"),
        "dividend_yield": data.get("dividend_yield"),
    }
