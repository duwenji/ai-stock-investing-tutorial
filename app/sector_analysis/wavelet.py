import numpy as np
import pandas as pd
import pywt

WAVELET = "cmor1.5-1.0"

PERIOD_BANDS: dict[str, tuple[float, float]] = {
    "短期": (4.0, 10.0),
    "中期": (10.0, 40.0),
    "長期": (40.0, 120.0),
}


def classify_period_band(period_days: float) -> str | None:
    """周期（営業日）をPERIOD_BANDSに基づき短期/中期/長期に分類する。

    範囲外（4未満、または120超）の場合はNoneを返す。
    """
    bands = list(PERIOD_BANDS.items())
    for index, (band, (lo, hi)) in enumerate(bands):
        is_last = index == len(bands) - 1
        in_range = lo <= period_days <= hi if is_last else lo <= period_days < hi
        if in_range:
            return band
    return None


def serialize_sector_returns(
    sector_returns: dict[str, pd.Series],
) -> dict[str, dict[str, list]]:
    """業種別リターン系列の辞書を、JSON保存可能な辞書に変換する。NaNはNoneに変換する。"""
    return {
        sector: {
            "dates": [d.isoformat() for d in series.index],
            "values": [None if pd.isna(v) else float(v) for v in series],
        }
        for sector, series in sector_returns.items()
    }


def deserialize_sector_returns(
    data: dict[str, dict[str, list]],
) -> dict[str, pd.Series]:
    """serialize_sector_returnsの逆変換。Noneはnp.nanに戻す。"""
    result: dict[str, pd.Series] = {}
    for sector, payload in data.items():
        values = [np.nan if v is None else v for v in payload["values"]]
        index = pd.to_datetime(payload["dates"])
        result[sector] = pd.Series(values, index=index)
    return result


def _build_scales(
    min_period_days: float, max_period_days: float, voices_per_octave: int
) -> tuple[np.ndarray, np.ndarray]:
    num_octaves = np.log2(max_period_days / min_period_days)
    n_scales = max(2, int(round(num_octaves * voices_per_octave)) + 1)
    periods = np.geomspace(min_period_days, max_period_days, n_scales)
    center_freq = pywt.central_frequency(WAVELET)
    scales = center_freq * periods  # sampling_period = 1日
    return scales, periods


def _smooth_along_time(coeffs: np.ndarray, periods: np.ndarray) -> np.ndarray:
    # スケール（周期）ごとに、その周期の長さに比例した窓幅のboxcarフィルタで
    # 時間軸方向に平滑化する。コヒーレンス計算に必須（平滑化なしでは常に1になる）。
    smoothed = np.empty_like(coeffs)
    for i, period in enumerate(periods):
        window = max(1, int(round(period)))
        kernel = np.ones(window) / window
        pad_left = window // 2
        pad_right = window - pad_left - 1
        padded = np.pad(coeffs[i], (pad_left, pad_right), mode="edge")
        smoothed[i] = np.convolve(padded, kernel, mode="valid")
    return smoothed


def compute_cross_wavelet_lead_lag(
    series_x: pd.Series,
    series_y: pd.Series,
    sector_x_name: str,
    sector_y_name: str,
    min_period_days: float = 4.0,
    max_period_days: float = 120.0,
    voices_per_octave: int = 4,
) -> pd.DataFrame:
    """2業種の日次リターン系列から、時間×周期ごとのクロスウェーブレット・
    コヒーレンスと符号付きラグ（どちらの業種が何営業日先行するか）を計算する。

    lag_days > 0はsector_x_nameが先行、lag_days < 0はsector_y_nameが先行することを示す。
    共通の非欠損データ数がmax_period_days * 2未満の場合は空のDataFrameを返す。
    """
    columns = ["date", "period_days", "band", "coherence", "lag_days", "leading_sector"]
    combined = pd.concat([series_x.rename("x"), series_y.rename("y")], axis=1).dropna()
    if len(combined) < max_period_days * 2:
        return pd.DataFrame(columns=columns)

    scales, periods = _build_scales(min_period_days, max_period_days, voices_per_octave)
    coeffs_x, _ = pywt.cwt(combined["x"].to_numpy(), scales, WAVELET, sampling_period=1.0)
    coeffs_y, _ = pywt.cwt(combined["y"].to_numpy(), scales, WAVELET, sampling_period=1.0)

    sxx = _smooth_along_time(coeffs_x * np.conj(coeffs_x), periods).real
    syy = _smooth_along_time(coeffs_y * np.conj(coeffs_y), periods).real
    sxy = _smooth_along_time(coeffs_x * np.conj(coeffs_y), periods)

    with np.errstate(divide="ignore", invalid="ignore"):
        coherence = np.abs(sxy) ** 2 / (sxx * syy)
    coherence = np.clip(np.nan_to_num(coherence, nan=0.0), 0.0, 1.0)

    phase = np.angle(sxy)
    lag_days = phase / (2 * np.pi) * periods[:, None]

    n_scales, n_time = lag_days.shape
    dates = combined.index
    band_per_scale = [classify_period_band(p) for p in periods]
    lag_flat = lag_days.flatten()

    df = pd.DataFrame(
        {
            "date": np.tile(dates.values, n_scales),
            "period_days": np.repeat(periods, n_time),
            "band": np.repeat(band_per_scale, n_time),
            "coherence": coherence.flatten(),
            "lag_days": lag_flat,
            "leading_sector": np.where(lag_flat >= 0, sector_x_name, sector_y_name),
        }
    )
    return df[df["band"].notna()].reset_index(drop=True)


def compute_dominant_lag_series(band_df: pd.DataFrame) -> pd.DataFrame:
    """特定周期帯のDataFrame（date, lag_days, coherenceを含む）から、
    日付ごとのコヒーレンス加重平均ラグを計算する。コヒーレンス合計が0の日付は除外する。
    """
    weighted = band_df.assign(_weighted_lag=band_df["lag_days"] * band_df["coherence"])
    agg = weighted.groupby("date").agg(
        _weighted_sum=("_weighted_lag", "sum"), _weight_total=("coherence", "sum")
    )
    agg = agg[agg["_weight_total"] > 0]
    agg["dominant_lag_days"] = agg["_weighted_sum"] / agg["_weight_total"]
    return agg.reset_index()[["date", "dominant_lag_days"]]
