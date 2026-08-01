from strategy_builder.sector_insight import (
    build_watchlist_from_rotation,
    find_dominant_lagging_sector,
    find_top_gaining_tickers,
)


def test_find_top_gaining_tickers_sorts_descending_and_limits():
    returns = {"AAA.T": 1.0, "BBB.T": 5.0, "CCC.T": 3.0}
    result = find_top_gaining_tickers(returns, top_n=2)
    assert result == [
        {"ticker": "BBB.T", "return_pct": 5.0},
        {"ticker": "CCC.T", "return_pct": 3.0},
    ]


def test_find_dominant_lagging_sector_picks_highest_coherence_across_bands():
    pairs = [
        {"leading_sector": "銀行", "lagging_sector": "保険", "band": "短期",
         "mean_coherence": 0.4, "lag_days_abs": 2.0},
        {"leading_sector": "銀行", "lagging_sector": "保険", "band": "中期",
         "mean_coherence": 0.7, "lag_days_abs": 5.2},
        {"leading_sector": "保険", "lagging_sector": "銀行", "band": "長期",
         "mean_coherence": 0.9, "lag_days_abs": 10.0},
    ]
    result = find_dominant_lagging_sector(pairs, "銀行", coherence_threshold=0.5)
    assert result["band"] == "中期"
    assert result["lagging_sector"] == "保険"


def test_find_dominant_lagging_sector_returns_none_below_threshold():
    pairs = [
        {"leading_sector": "銀行", "lagging_sector": "保険", "band": "短期",
         "mean_coherence": 0.3, "lag_days_abs": 2.0},
    ]
    assert find_dominant_lagging_sector(pairs, "銀行", coherence_threshold=0.5) is None


def test_find_dominant_lagging_sector_returns_none_when_no_pairs_for_sector():
    pairs = [
        {"leading_sector": "保険", "lagging_sector": "銀行", "band": "短期",
         "mean_coherence": 0.9, "lag_days_abs": 2.0},
    ]
    assert find_dominant_lagging_sector(pairs, "銀行", coherence_threshold=0.5) is None


def test_build_watchlist_from_rotation_returns_candidates_and_idea_text():
    ticker_latest_return_pct = {"7203.T": 3.5, "8306.T": 1.0}
    network_pairs = [
        {"leading_sector": "輸送用機器", "lagging_sector": "電気機器", "band": "中期",
         "mean_coherence": 0.6, "lag_days_abs": 6.1},
    ]
    sector_map = {
        "7203.T": "輸送用機器",
        "8306.T": "銀行",
        "6758.T": "電気機器",
        "6501.T": "電気機器",
    }
    universe_names = {"6758.T": "ソニーグループ", "6501.T": "日立製作所"}

    result = build_watchlist_from_rotation(
        ticker_latest_return_pct, network_pairs, sector_map, universe_names
    )

    assert result["idea_text"] is not None
    assert "輸送用機器" in result["idea_text"]
    assert "電気機器" in result["idea_text"]
    assert {c["ticker"] for c in result["candidates"]} == {"6758.T", "6501.T"}
    assert result["candidates"][0]["leading_sector"] == "輸送用機器"


def test_build_watchlist_from_rotation_returns_none_idea_when_no_pair_found():
    result = build_watchlist_from_rotation(
        {"7203.T": 3.5}, [], {"7203.T": "輸送用機器"}, {}
    )
    assert result == {"idea_text": None, "candidates": []}


def test_build_watchlist_from_rotation_skips_gainer_without_sector_and_tries_next():
    ticker_latest_return_pct = {"UNKNOWN.T": 9.9, "7203.T": 3.5}
    network_pairs = [
        {"leading_sector": "輸送用機器", "lagging_sector": "電気機器", "band": "中期",
         "mean_coherence": 0.6, "lag_days_abs": 6.1},
    ]
    sector_map = {"7203.T": "輸送用機器", "6758.T": "電気機器"}
    result = build_watchlist_from_rotation(
        ticker_latest_return_pct, network_pairs, sector_map, {}
    )
    assert result["idea_text"] is not None
    assert {c["ticker"] for c in result["candidates"]} == {"6758.T"}
