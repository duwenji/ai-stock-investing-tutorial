import numpy as np
import pandas as pd

from sector_analysis.correlation import compute_lead_lag_pairs, compute_sector_returns


def test_compute_sector_returns_averages_tickers_in_same_sector():
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    prices_by_ticker = {
        "A.T": pd.Series([100.0, 102.0, 104.0, 103.0, 105.0], index=dates),
        "B.T": pd.Series([200.0, 204.0, 208.0, 206.0, 210.0], index=dates),
    }
    sector_map = {"A.T": "業種X", "B.T": "業種X"}

    result = compute_sector_returns(prices_by_ticker, sector_map)

    assert list(result.keys()) == ["業種X"]
    expected = prices_by_ticker["A.T"].pct_change()
    pd.testing.assert_series_equal(result["業種X"], expected, check_names=False)


def test_compute_sector_returns_skips_missing_ticker_and_keeps_sector():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    prices_by_ticker = {"A.T": pd.Series([100.0, 101.0, 102.0], index=dates)}
    sector_map = {"A.T": "業種X", "B.T": "業種X"}

    result = compute_sector_returns(prices_by_ticker, sector_map)

    assert list(result.keys()) == ["業種X"]


def test_compute_sector_returns_excludes_sector_with_no_available_tickers():
    sector_map = {"A.T": "業種X"}

    result = compute_sector_returns({}, sector_map)

    assert result == {}


def test_compute_lead_lag_pairs_detects_known_lag():
    rng = np.random.default_rng(42)
    n = 60
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    base = pd.Series(rng.normal(size=n), index=dates)

    lag_n = 5
    # shifted[t] = base[t - lag_n] -> shiftedは base に lag_n 日遅れて追随する
    shifted = base.shift(lag_n)
    sector_returns = {"X業種": base, "Y業種": shifted}

    pairs = compute_lead_lag_pairs(sector_returns, max_lag_days=10)

    assert len(pairs) == 1
    pair = pairs[0]
    assert pair["leading_sector"] == "X業種"
    assert pair["lagging_sector"] == "Y業種"
    assert pair["lag_days"] == lag_n
    assert abs(pair["correlation"] - 1.0) < 1e-9


def test_compute_lead_lag_pairs_excludes_pairs_with_insufficient_overlap():
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    sector_returns = {
        "X業種": pd.Series([0.01, 0.02, -0.01, 0.03, 0.0], index=dates),
        "Y業種": pd.Series([0.02, 0.01, -0.02, 0.01, 0.0], index=dates),
    }

    pairs = compute_lead_lag_pairs(sector_returns, max_lag_days=20)

    assert pairs == []


def test_compute_lead_lag_pairs_sorts_by_absolute_correlation_descending():
    rng = np.random.default_rng(7)
    n = 60
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    a = pd.Series(rng.normal(size=n), index=dates)
    b = a.shift(3)  # aと強く相関
    c = pd.Series(rng.normal(size=n), index=dates)  # aと無関係

    sector_returns = {"A業種": a, "B業種": b, "C業種": c}

    pairs = compute_lead_lag_pairs(sector_returns, max_lag_days=10)

    assert len(pairs) == 3
    strongest = pairs[0]
    assert {strongest["leading_sector"], strongest["lagging_sector"]} == {"A業種", "B業種"}
    for earlier, later in zip(pairs, pairs[1:]):
        assert abs(earlier["correlation"]) >= abs(later["correlation"])
