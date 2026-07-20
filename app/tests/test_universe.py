from screening.universe import UNIVERSE, UNIVERSE_NAMES

# 拡張前（既存60銘柄）のティッカー。和集合により必ず残ることを回帰的に検証する。
_PRE_EXPANSION_TICKERS = [
    "7203.T", "7267.T", "7201.T", "6758.T", "6861.T", "6501.T", "6503.T",
    "6752.T", "6902.T", "6971.T", "8035.T", "6273.T", "9432.T", "9433.T",
    "9434.T", "9984.T", "8306.T", "8316.T", "8411.T", "8766.T", "8058.T",
    "8031.T", "8001.T", "2914.T", "4502.T", "4519.T", "4568.T", "3382.T",
    "9843.T", "8267.T", "4901.T", "7751.T", "7011.T", "6301.T", "5108.T",
    "4063.T", "6367.T", "9020.T", "9022.T", "9101.T", "8801.T", "8802.T",
    "6098.T", "4661.T", "6857.T", "6920.T", "6146.T", "6723.T", "3436.T",
    "4062.T", "6981.T", "6762.T", "6963.T", "6702.T", "285A.T", "7735.T",
    "6701.T", "4004.T", "6890.T", "7729.T",
]


def test_universe_size_covers_nikkei225_and_existing():
    # 日経225(225件)と拡張前の既存60銘柄の和集合。重複57件を除くと228件になる。
    assert len(UNIVERSE) == 228


def test_universe_tickers_are_unique():
    assert len(UNIVERSE) == len(set(UNIVERSE))


def test_universe_tickers_use_tokyo_exchange_suffix():
    assert all(ticker.endswith(".T") for ticker in UNIVERSE)


def test_universe_names_cover_all_tickers():
    assert set(UNIVERSE_NAMES.keys()) == set(UNIVERSE)


def test_universe_names_have_non_empty_values():
    assert all(isinstance(name, str) and name for name in UNIVERSE_NAMES.values())


def test_universe_retains_all_pre_expansion_tickers():
    assert set(_PRE_EXPANSION_TICKERS) <= set(UNIVERSE)
