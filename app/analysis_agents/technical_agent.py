import pandas as pd


def analyze_technical(
    price_history: pd.DataFrame, short_window: int = 25, long_window: int = 75
) -> dict:
    close = price_history["Close"]
    if len(close) < long_window:
        return {"ma_short": None, "ma_long": None, "signal": "データ不足"}

    ma_short = close.rolling(window=short_window).mean().iloc[-1]
    ma_long = close.rolling(window=long_window).mean().iloc[-1]

    if ma_short > ma_long:
        signal = "強気"
    elif ma_short < ma_long:
        signal = "弱気"
    else:
        signal = "中立"

    return {"ma_short": round(ma_short, 2), "ma_long": round(ma_long, 2), "signal": signal}
