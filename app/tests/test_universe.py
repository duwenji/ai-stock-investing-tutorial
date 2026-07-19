from screening.universe import UNIVERSE, UNIVERSE_NAMES


def test_universe_size_within_expected_range():
    assert 40 <= len(UNIVERSE) <= 60


def test_universe_tickers_are_unique():
    assert len(UNIVERSE) == len(set(UNIVERSE))


def test_universe_tickers_use_tokyo_exchange_suffix():
    assert all(ticker.endswith(".T") for ticker in UNIVERSE)


def test_universe_names_cover_all_tickers():
    assert set(UNIVERSE_NAMES.keys()) == set(UNIVERSE)


def test_universe_names_have_non_empty_values():
    assert all(isinstance(name, str) and name for name in UNIVERSE_NAMES.values())
