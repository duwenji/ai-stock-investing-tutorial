import numpy as np
import pandas as pd

from sector_analysis.wavelet import (
    classify_period_band,
    compute_cross_wavelet_lead_lag,
    compute_dominant_lag_series,
    deserialize_sector_returns,
    serialize_sector_returns,
)


def test_classify_period_band_boundaries():
    assert classify_period_band(4.0) == "短期"
    assert classify_period_band(9.9) == "短期"
    assert classify_period_band(10.0) == "中期"
    assert classify_period_band(39.9) == "中期"
    assert classify_period_band(40.0) == "長期"
    assert classify_period_band(120.0) == "長期"
    assert classify_period_band(3.9) is None
    assert classify_period_band(120.1) is None


def test_compute_cross_wavelet_lead_lag_detects_known_lag():
    n = 240
    t = np.arange(n)
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    period = 20.0
    shift = 5
    base = pd.Series(np.sin(2 * np.pi * t / period), index=dates)
    # laggedはbaseよりshift日遅れて追随する（＝baseが先行）
    lagged = pd.Series(np.sin(2 * np.pi * (t - shift) / period), index=dates)

    df = compute_cross_wavelet_lead_lag(base, lagged, "X", "Y")

    assert not df.empty
    near_period = df[(df["period_days"] >= 15) & (df["period_days"] <= 25)]
    assert not near_period.empty
    median_lag = near_period["lag_days"].median()
    assert abs(median_lag - shift) < 3
    assert (near_period["leading_sector"] == "X").mean() > 0.6


def test_compute_cross_wavelet_lead_lag_coherence_bounds():
    n = 240
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    rng = np.random.default_rng(0)
    x = pd.Series(rng.normal(size=n), index=dates)
    y = pd.Series(rng.normal(size=n), index=dates)

    df = compute_cross_wavelet_lead_lag(x, y, "X", "Y")

    assert not df.empty
    assert (df["coherence"] >= 0).all()
    assert (df["coherence"] <= 1).all()


def test_compute_cross_wavelet_lead_lag_returns_empty_for_insufficient_data():
    dates = pd.date_range("2025-01-01", periods=10, freq="D")
    x = pd.Series(np.arange(10, dtype=float), index=dates)
    y = pd.Series(np.arange(10, dtype=float), index=dates)

    df = compute_cross_wavelet_lead_lag(x, y, "X", "Y")

    assert list(df.columns) == [
        "date", "period_days", "band", "coherence", "lag_days", "leading_sector",
    ]
    assert df.empty


def test_compute_dominant_lag_series_weights_by_coherence():
    dates = pd.date_range("2025-01-01", periods=2, freq="D")
    band_df = pd.DataFrame(
        {
            "date": [dates[0], dates[0], dates[1], dates[1]],
            "lag_days": [10.0, 0.0, 5.0, 5.0],
            "coherence": [1.0, 0.0, 0.5, 0.5],
        }
    )

    result = compute_dominant_lag_series(band_df)

    assert list(result["dominant_lag_days"]) == [10.0, 5.0]


def test_serialize_deserialize_sector_returns_round_trip():
    dates = pd.date_range("2025-01-01", periods=3, freq="D")
    original = {"業種X": pd.Series([0.01, np.nan, -0.02], index=dates)}

    data = serialize_sector_returns(original)
    restored = deserialize_sector_returns(data)

    pd.testing.assert_series_equal(
        restored["業種X"], original["業種X"], check_names=False, check_freq=False
    )
