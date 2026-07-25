import numpy as np
import pandas as pd

from sector_analysis.wavelet import (
    classify_period_band,
    compute_all_pairs_dominant_lag,
    compute_cross_wavelet_lead_lag,
    compute_dominant_lag_series,
    deserialize_sector_returns,
    serialize_sector_returns,
    summarize_band_snapshot,
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


def test_compute_dominant_lag_series_includes_avg_coherence():
    dates = pd.date_range("2025-01-01", periods=2, freq="D")
    band_df = pd.DataFrame(
        {
            "date": [dates[0], dates[0], dates[1], dates[1]],
            "lag_days": [10.0, 0.0, 5.0, 5.0],
            "coherence": [1.0, 0.0, 0.5, 0.3],
        }
    )

    result = compute_dominant_lag_series(band_df)

    assert list(result["avg_coherence"]) == [0.5, 0.4]


def test_summarize_band_snapshot_returns_latest_snapshot():
    dates = pd.date_range("2025-01-01", periods=2, freq="D")
    band_df = pd.DataFrame(
        {
            "date": [dates[0], dates[0], dates[1], dates[1]],
            "lag_days": [10.0, 0.0, 5.0, 5.0],
            "coherence": [1.0, 0.0, 0.5, 0.3],
        }
    )

    snapshot = summarize_band_snapshot(band_df)

    assert snapshot == {
        "date": dates[1],
        "dominant_lag_days": 5.0,
        "avg_coherence": 0.4,
    }


def test_summarize_band_snapshot_returns_none_for_empty_df():
    band_df = pd.DataFrame(columns=["date", "lag_days", "coherence"])

    assert summarize_band_snapshot(band_df) is None


def test_serialize_deserialize_sector_returns_round_trip():
    dates = pd.date_range("2025-01-01", periods=3, freq="D")
    original = {"業種X": pd.Series([0.01, np.nan, -0.02], index=dates)}

    data = serialize_sector_returns(original)
    restored = deserialize_sector_returns(data)

    pd.testing.assert_series_equal(
        restored["業種X"], original["業種X"], check_names=False, check_freq=False
    )


def test_compute_all_pairs_dominant_lag_detects_known_lag_direction_and_magnitude():
    n = 240
    t = np.arange(n)
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    period = 20.0
    shift = 5
    a = pd.Series(np.sin(2 * np.pi * t / period), index=dates)
    # bはaよりshift日遅れて追随する（＝aが先行）
    b = pd.Series(np.sin(2 * np.pi * (t - shift) / period), index=dates)

    result = compute_all_pairs_dominant_lag({"A": a, "B": b}, window_days=20)

    mid_band = result[(result["sector_x"] == "A") & (result["sector_y"] == "B") & (result["band"] == "中期")]
    assert not mid_band.empty
    row = mid_band.iloc[0]
    assert row["leading_sector"] == "A"
    assert row["lagging_sector"] == "B"
    assert abs(row["dominant_lag_days"] - shift) < 3
    assert abs(row["lag_days_abs"] - shift) < 3
    assert 0.0 <= row["mean_coherence"] <= 1.0


def test_compute_all_pairs_dominant_lag_skips_pairs_with_insufficient_data():
    n = 240
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    rng = np.random.default_rng(0)
    a = pd.Series(rng.normal(size=n), index=dates)
    b = pd.Series(rng.normal(size=n), index=dates)
    # cは10日分しかデータがなく、a・bとの共通非欠損データが不足する
    short_dates = pd.date_range("2025-01-01", periods=10, freq="D")
    c = pd.Series(np.arange(10, dtype=float), index=short_dates)

    result = compute_all_pairs_dominant_lag({"A": a, "B": b, "C": c}, window_days=20)

    assert not result.empty
    assert not ((result["sector_x"] == "C") | (result["sector_y"] == "C")).any()
    assert ((result["sector_x"] == "A") & (result["sector_y"] == "B")).any()


def test_compute_all_pairs_dominant_lag_skips_pair_that_raises(monkeypatch):
    import sector_analysis.wavelet as wavelet_module

    n = 240
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    rng = np.random.default_rng(2)
    sector_returns = {
        name: pd.Series(rng.normal(size=n), index=dates) for name in ["A", "B", "C"]
    }

    original = wavelet_module.compute_cross_wavelet_lead_lag

    def flaky(series_x, series_y, sector_x_name, sector_y_name, **kwargs):
        if {sector_x_name, sector_y_name} == {"A", "B"}:
            raise RuntimeError("boom")
        return original(series_x, series_y, sector_x_name, sector_y_name, **kwargs)

    monkeypatch.setattr(wavelet_module, "compute_cross_wavelet_lead_lag", flaky)

    result = wavelet_module.compute_all_pairs_dominant_lag(sector_returns, window_days=20)

    assert not ((result["sector_x"] == "A") & (result["sector_y"] == "B")).any()
    assert (
        ((result["sector_x"] == "A") & (result["sector_y"] == "C")).any()
        or ((result["sector_x"] == "B") & (result["sector_y"] == "C")).any()
    )


def test_compute_all_pairs_dominant_lag_mean_coherence_within_bounds():
    n = 240
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    rng = np.random.default_rng(1)
    sector_returns = {
        name: pd.Series(rng.normal(size=n), index=dates) for name in ["A", "B", "C"]
    }

    result = compute_all_pairs_dominant_lag(sector_returns, window_days=20)

    assert not result.empty
    assert (result["mean_coherence"] >= 0).all()
    assert (result["mean_coherence"] <= 1).all()


def test_compute_all_pairs_dominant_lag_returns_empty_for_single_sector():
    dates = pd.date_range("2025-01-01", periods=240, freq="D")
    result = compute_all_pairs_dominant_lag({"A": pd.Series(np.zeros(240), index=dates)})

    assert list(result.columns) == [
        "sector_x",
        "sector_y",
        "band",
        "dominant_lag_days",
        "mean_coherence",
        "leading_sector",
        "lagging_sector",
        "lag_days_abs",
    ]
    assert result.empty
