import csv
from pathlib import Path

SEED_PATH = Path(__file__).resolve().parent.parent / "db" / "seed_company_profiles.csv"


def _read_seed_rows() -> list[dict]:
    with SEED_PATH.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_seed_file_has_228_rows():
    assert len(_read_seed_rows()) == 228


def test_seed_tickers_are_unique():
    rows = _read_seed_rows()
    tickers = [row["ticker"] for row in rows]
    assert len(tickers) == len(set(tickers))


def test_seed_tickers_use_tokyo_exchange_suffix():
    rows = _read_seed_rows()
    assert all(row["ticker"].endswith(".T") for row in rows)


def test_seed_names_are_non_empty():
    rows = _read_seed_rows()
    assert all(row["name"] for row in rows)


def test_seed_covers_all_seventeen_sectors():
    expected_sectors = {
        "食品", "エネルギー資源", "建設・資材", "素材・化学", "医薬品",
        "自動車・輸送機", "鉄鋼・非鉄", "機械", "電機・精密", "運輸・物流",
        "商社・卸売", "小売", "銀行", "金融（除く銀行）", "不動産",
        "情報通信・サービスその他", "電力・ガス",
    }
    rows = _read_seed_rows()
    assert {row["sector_jp"] for row in rows} == expected_sectors
