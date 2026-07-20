# 短期・長期の移動平均線クロスオーバーに基づき、テクニカルシグナルを判定するエージェント。
import pandas as pd


def analyze_technical(
    price_history: pd.DataFrame, short_window: int = 25, long_window: int = 75
) -> dict:
    close = price_history["Close"]
    # 長期移動平均を計算するのに十分なデータ数が無い場合は、誤ったシグナルを
    # 出さないよう「データ不足」として明示的に判定を保留する。
    if len(close) < long_window:
        return {"ma_short": None, "ma_long": None, "signal": "データ不足"}

    ma_short = close.rolling(window=short_window).mean().iloc[-1]
    ma_long = close.rolling(window=long_window).mean().iloc[-1]

    # ゴールデンクロス（短期>長期）を強気、デッドクロス（短期<長期）を弱気と判定する。
    if ma_short > ma_long:
        signal = "強気"
    elif ma_short < ma_long:
        signal = "弱気"
    else:
        signal = "中立"

    return {"ma_short": round(ma_short, 2), "ma_long": round(ma_long, 2), "signal": signal}
