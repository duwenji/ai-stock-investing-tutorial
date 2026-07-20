from screening.sectors import SECTOR_MAP
from screening.universe import UNIVERSE


def test_sector_map_keys_match_universe():
    assert set(SECTOR_MAP.keys()) == set(UNIVERSE)


def test_sector_map_values_are_non_empty_strings():
    assert all(isinstance(sector, str) and sector for sector in SECTOR_MAP.values())


def test_sector_map_covers_all_seventeen_sectors():
    expected_sectors = {
        "食品", "エネルギー資源", "建設・資材", "素材・化学", "医薬品",
        "自動車・輸送機", "鉄鋼・非鉄", "機械", "電機・精密", "運輸・物流",
        "商社・卸売", "小売", "銀行", "金融（除く銀行）", "不動産",
        "情報通信・サービスその他", "電力・ガス",
    }
    assert set(SECTOR_MAP.values()) == expected_sectors
