# 移動平均線クロスオーバー・RSI・ATR・ADX・OBVに基づき、テクニカルシグナルを判定するエージェント。
import numpy as np
import pandas as pd


def _moving_average_signal(close: pd.Series, short_window: int, long_window: int) -> dict:
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


def _wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    # Wilderのスムージング（RSI/ATR/ADXで共通して使われる指数平滑）。
    # adjust=Falseの指数移動平均（alpha=1/period）で近似する。
    return series.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def _series_to_list(series: pd.Series) -> list[float | None]:
    # チャート描画用にJSON化できる形（NaN→None）へ変換する。
    return [None if pd.isna(v) else round(float(v), 2) for v in series]


def _rsi_signal(value: float) -> str:
    if value >= 70:
        return "買われすぎ"
    if value <= 30:
        return "売られすぎ"
    return "中立"


def _rsi(close: pd.Series, period: int) -> dict:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = _wilder_smooth(gain, period)
    avg_loss = _wilder_smooth(loss, period)

    # avg_loss==0（下落が一度も無い）の場合はゼロ除算を避け、上昇継続ならRSI=100とする。
    rsi_series = (100 - 100 / (1 + avg_gain / avg_loss.replace(0, np.nan))).where(
        avg_loss != 0, np.where(avg_gain > 0, 100.0, 50.0)
    )
    rsi_series = rsi_series.where(avg_gain.notna() & avg_loss.notna())

    rsi_value = rsi_series.iloc[-1]
    if pd.isna(rsi_value):
        return {
            "rsi": None,
            "rsi_signal": "データ不足",
            "rsi_series": _series_to_list(rsi_series),
        }

    return {
        "rsi": round(rsi_value, 2),
        "rsi_signal": _rsi_signal(rsi_value),
        "rsi_series": _series_to_list(rsi_series),
    }


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["Close"].shift(1)
    return pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _atr_signal(atr_pct: float) -> str:
    if atr_pct >= 3:
        return "高ボラティリティ"
    if atr_pct < 1:
        return "低ボラティリティ"
    return "中程度"


def _atr(df: pd.DataFrame, period: int) -> dict:
    tr = _true_range(df)
    atr_series = _wilder_smooth(tr, period)
    atr_pct_series = (atr_series / df["Close"]) * 100
    atr_value = atr_series.iloc[-1]

    if pd.isna(atr_value):
        return {
            "atr": None,
            "atr_pct": None,
            "atr_signal": "データ不足",
            "atr_pct_series": _series_to_list(atr_pct_series),
        }

    last_close = df["Close"].iloc[-1]
    atr_pct = (atr_value / last_close) * 100 if last_close else None

    return {
        "atr": round(atr_value, 2),
        "atr_pct": round(atr_pct, 2) if atr_pct is not None else None,
        "atr_signal": _atr_signal(atr_pct) if atr_pct is not None else "データ不足",
        "atr_pct_series": _series_to_list(atr_pct_series),
    }


def _adx(df: pd.DataFrame, period: int) -> dict:
    up_move = df["High"].diff()
    down_move = -df["Low"].diff()

    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    tr = _true_range(df)
    smoothed_tr = _wilder_smooth(tr, period)
    smoothed_plus_dm = _wilder_smooth(plus_dm, period)
    smoothed_minus_dm = _wilder_smooth(minus_dm, period)

    plus_di = 100 * smoothed_plus_dm / smoothed_tr
    minus_di = 100 * smoothed_minus_dm / smoothed_tr
    di_sum = plus_di + minus_di
    dx = 100 * (plus_di - minus_di).abs() / di_sum.replace(0, np.nan)

    adx_series = _wilder_smooth(dx, period)
    adx_value = adx_series.iloc[-1]
    if pd.isna(adx_value):
        return {
            "adx": None,
            "adx_signal": "データ不足",
            "adx_series": _series_to_list(adx_series),
        }

    if adx_value >= 25:
        signal = "強いトレンド"
    elif adx_value < 20:
        signal = "レンジ相場"
    else:
        signal = "中立"

    return {
        "adx": round(adx_value, 2),
        "adx_signal": signal,
        "adx_series": _series_to_list(adx_series),
    }


def _obv(df: pd.DataFrame, period: int) -> dict:
    close = df["Close"]
    volume = df["Volume"]
    direction = np.sign(close.diff().fillna(0))
    obv_series = (direction * volume).cumsum()

    if len(obv_series) <= period:
        return {"obv": None, "obv_signal": "データ不足"}

    obv_value = obv_series.iloc[-1]
    baseline = obv_series.iloc[-1 - period]

    if obv_value > baseline:
        signal = "増加傾向"
    elif obv_value < baseline:
        signal = "減少傾向"
    else:
        signal = "横ばい"

    return {"obv": round(obv_value, 2), "obv_signal": signal}


def analyze_technical(
    price_history: pd.DataFrame,
    short_window: int = 25,
    long_window: int = 75,
    rsi_period: int = 14,
    atr_period: int = 14,
    adx_period: int = 14,
    obv_period: int = 20,
) -> dict:
    close = price_history["Close"]

    result = _moving_average_signal(close, short_window, long_window)
    result.update(_rsi(close, rsi_period))
    result.update(_atr(price_history, atr_period))
    result.update(_adx(price_history, adx_period))
    result.update(_obv(price_history, obv_period))
    return result
