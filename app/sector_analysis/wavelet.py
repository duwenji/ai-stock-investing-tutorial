"""クロスウェーブレット変換により、2業種間の値動きが「何営業日ずれて連動しているか」を
周期帯（短期/中期/長期）ごとに検出するモジュール。

通常の相関係数は時間的に一定の関係しか捉えられないが、ウェーブレット変換なら
「短期的には業種Aが先行するが、長期的には業種Bが先行する」といった周期ごとに
異なるリード・ラグ関係を検出できる。結果はnetwork.py（Mermaid図）や
correlation.pyと並んでセクターローテーション分析タブで使われる。
"""

import itertools
import logging

import numpy as np
import pandas as pd
import pywt

from common.logging_config import log_duration

logger = logging.getLogger(__name__)

# 複素モルレーウェーブレット。位相情報（=リード・ラグの符号）を持つため、
# 大きさのみの実数ウェーブレットではなくこちらを使う。"1.5-1.0"は
# 帯域幅パラメータと中心周波数パラメータ（pywtの命名規則）。
WAVELET = "cmor1.5-1.0"

# 周期（営業日）を短期/中期/長期に分類する境界値。値が大きいほど
# ゆっくりした（長期的な）値動きの周期を表す。
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
    # pywt.cwtは「周期」ではなく「スケール」というウェーブレット固有の単位で
    # 動くため、対数間隔（geomspace）で刻んだ周期の並びをスケールに変換する。
    # 対数間隔にするのは、短期の周期を細かく、長期の周期を粗くサンプルする方が
    # 少ないスケール数で短期〜長期を効率よくカバーできるため。
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

    # コヒーレンス（0〜1）はクロススペクトルの正規化された強さで、その時点・
    # その周期で2業種がどれだけ同期して動いているかを表す指標。1に近いほど
    # 連動が強く、ラグの値も信頼できるとみなす。
    with np.errstate(divide="ignore", invalid="ignore"):
        coherence = np.abs(sxy) ** 2 / (sxx * syy)
    coherence = np.clip(np.nan_to_num(coherence, nan=0.0), 0.0, 1.0)

    # クロスウェーブレットの位相差から、周期に対する時間差（何営業日分の
    # ずれか）を算出する。位相はradianなので2πで正規化してから周期days倍する。
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

    avg_coherenceは、その日付における対象バンド内の周期（スケール）方向の
    コヒーレンス単純平均（重み付けなし）。dominant_lag_daysの重み付けとは
    独立した「その日のバンド全体の確からしさ」の目安として扱う。
    """
    weighted = band_df.assign(_weighted_lag=band_df["lag_days"] * band_df["coherence"])
    agg = weighted.groupby("date").agg(
        _weighted_sum=("_weighted_lag", "sum"),
        _weight_total=("coherence", "sum"),
        avg_coherence=("coherence", "mean"),
    )
    agg = agg[agg["_weight_total"] > 0]
    agg["dominant_lag_days"] = agg["_weighted_sum"] / agg["_weight_total"]
    return agg.reset_index()[["date", "dominant_lag_days", "avg_coherence"]]


def summarize_band_snapshot(band_df: pd.DataFrame) -> dict | None:
    """特定周期帯のDataFrameから、直近日付における支配的ラグとバンド平均
    コヒーレンスのスナップショットを返す。有効なデータがなければNoneを返す。
    """
    dominant = compute_dominant_lag_series(band_df)
    if dominant.empty:
        return None
    last = dominant.iloc[-1]
    return {
        "date": last["date"],
        "dominant_lag_days": float(last["dominant_lag_days"]),
        "avg_coherence": float(last["avg_coherence"]),
    }


def compute_all_pairs_dominant_lag(
    sector_returns: dict[str, pd.Series],
    window_days: int = 20,
) -> pd.DataFrame:
    """全業種ペアについてウェーブレット分析を一括実行し、周期帯ごとに
    直近window_days営業日のコヒーレンス加重平均ラグに集約する。

    個別ペアの計算で例外が発生した場合、またはデータ不足で
    compute_cross_wavelet_lead_lagが空のDataFrameを返した場合は、
    そのペアを結果から除外し処理を継続する。
    """
    with log_duration(logger, f"ウェーブレット全ペア計算（{len(sector_returns)}業種）"):
        columns = [
            "sector_x",
            "sector_y",
            "band",
            "dominant_lag_days",
            "mean_coherence",
            "leading_sector",
            "lagging_sector",
            "lag_days_abs",
        ]
        rows = []
        sectors = sorted(sector_returns.keys())
        for sector_x, sector_y in itertools.combinations(sectors, 2):
            try:
                pair_df = compute_cross_wavelet_lead_lag(
                    sector_returns[sector_x], sector_returns[sector_y], sector_x, sector_y
                )
            except Exception:
                continue
            if pair_df.empty:
                continue

            for band in PERIOD_BANDS:
                band_df = pair_df[pair_df["band"] == band]
                if band_df.empty:
                    continue
                per_date = compute_dominant_lag_series(band_df)
                if per_date.empty:
                    continue

                windowed = per_date.tail(window_days)
                weight_total = windowed["avg_coherence"].sum()
                if weight_total <= 0:
                    continue

                dominant_lag_days = (
                    windowed["dominant_lag_days"] * windowed["avg_coherence"]
                ).sum() / weight_total
                mean_coherence = windowed["avg_coherence"].mean()
                leading_sector = sector_x if dominant_lag_days >= 0 else sector_y
                lagging_sector = sector_y if dominant_lag_days >= 0 else sector_x

                rows.append(
                    {
                        "sector_x": sector_x,
                        "sector_y": sector_y,
                        "band": band,
                        "dominant_lag_days": dominant_lag_days,
                        "mean_coherence": mean_coherence,
                        "leading_sector": leading_sector,
                        "lagging_sector": lagging_sector,
                        "lag_days_abs": abs(dominant_lag_days),
                    }
                )

        return pd.DataFrame(rows, columns=columns)
