from screening.universe import UNIVERSE


def test_universe_size_within_expected_range():
    assert 40 <= len(UNIVERSE) <= 50


def test_universe_tickers_are_unique():
    assert len(UNIVERSE) == len(set(UNIVERSE))


def test_universe_tickers_use_tokyo_exchange_suffix():
    assert all(ticker.endswith(".T") for ticker in UNIVERSE)
