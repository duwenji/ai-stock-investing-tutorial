# 銘柄のファンダメンタルズ指標（PER・PBR・配当利回り）を取得・整形するエージェント。
from data_api.stock_price_api import fetch_fundamentals as default_fetch_fundamentals


def analyze_fundamentals(
    ticker_symbol: str, fetch_fundamentals=default_fetch_fundamentals
) -> dict:
    # 外部APIの生データ（フィールド名がAPI固有）を、アプリ内で共通して使う
    # per/pbr/dividend_yield という分かりやすいキー名に変換する。
    data = fetch_fundamentals(ticker_symbol)
    return {
        "ticker": ticker_symbol,
        "per": data.get("trailing_pe"),
        "pbr": data.get("price_to_book"),
        "dividend_yield": data.get("dividend_yield"),
    }
