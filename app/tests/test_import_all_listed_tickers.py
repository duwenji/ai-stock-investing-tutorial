import pandas as pd
import pytest
from sqlalchemy.orm import sessionmaker

from db.engine import create_db_engine, init_db
from db.models import CompanyProfile
from scripts.import_all_listed_tickers import (
    download_listing_xls_bytes,
    main,
    normalize_listing_rows,
    resolve_latest_listing_url,
    run_import,
)


@pytest.fixture
def session_factory(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine)
    # init_db()はseed_company_profiles.csvから228件を自動投入するため、
    # このテストファイルが対象ticker集合を厳密に制御できるよう一旦全件削除する。
    with factory() as session:
        session.query(CompanyProfile).delete()
        session.commit()
    return factory


def _listing_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_normalize_listing_rows_appends_tokyo_exchange_suffix():
    df = _listing_df([{"コード": "7203", "銘柄名": "トヨタ自動車", "17業種区分": "自動車・輸送機"}])
    result = normalize_listing_rows(df)
    assert result == [
        {"ticker": "7203.T", "name": "トヨタ自動車", "sector_jp": "自動車・輸送機"}
    ]


def test_normalize_listing_rows_converts_unclassified_marker_to_none():
    # ETF・REIT・PRO Market・種類株式等は17業種区分が"-"（未分類）になる
    df = _listing_df([{"コード": "1305", "銘柄名": "テストETF", "17業種区分": "-"}])
    result = normalize_listing_rows(df)
    assert result[0]["sector_jp"] is None


def test_run_import_inserts_new_tickers(session_factory):
    df = _listing_df(
        [
            {"コード": "1301", "銘柄名": "極洋", "17業種区分": "食品"},
            {"コード": "1305", "銘柄名": "テストETF", "17業種区分": "-"},
        ]
    )

    summary = run_import(session_factory=session_factory, df=df)

    assert summary["total"] == 2
    with session_factory() as session:
        profile = session.get(CompanyProfile, "1301.T")
        assert profile.name == "極洋"
        assert profile.sector_jp == "食品"
        etf_profile = session.get(CompanyProfile, "1305.T")
        assert etf_profile.sector_jp is None


def test_run_import_does_not_overwrite_existing_values(session_factory):
    with session_factory() as session:
        session.add(
            CompanyProfile(ticker="1301.T", name="実際の名前", sector_jp="実際の業種")
        )
        session.commit()

    df = _listing_df([{"コード": "1301", "銘柄名": "極洋", "17業種区分": "食品"}])
    run_import(session_factory=session_factory, df=df)

    with session_factory() as session:
        profile = session.get(CompanyProfile, "1301.T")
        assert profile.name == "実際の名前"
        assert profile.sector_jp == "実際の業種"


def test_run_import_fills_only_null_fields(session_factory):
    with session_factory() as session:
        session.add(CompanyProfile(ticker="1301.T", name="実際の名前"))
        session.commit()

    df = _listing_df([{"コード": "1301", "銘柄名": "極洋", "17業種区分": "食品"}])
    run_import(session_factory=session_factory, df=df)

    with session_factory() as session:
        profile = session.get(CompanyProfile, "1301.T")
        assert profile.name == "実際の名前"
        assert profile.sector_jp == "食品"


def test_resolve_latest_listing_url_extracts_link_from_landing_page(monkeypatch):
    class FakeResponse:
        text = '<a href="/markets/statistics-equities/misc/abc123-att/data_j.xls">一覧</a>'

        def raise_for_status(self):
            pass

    monkeypatch.setattr(
        "scripts.import_all_listed_tickers.requests.get",
        lambda url, headers=None, timeout=None: FakeResponse(),
    )

    url = resolve_latest_listing_url()

    assert url == "https://www.jpx.co.jp/markets/statistics-equities/misc/abc123-att/data_j.xls"


def test_resolve_latest_listing_url_raises_when_link_not_found(monkeypatch):
    class FakeResponse:
        text = "<html>該当リンクなし</html>"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(
        "scripts.import_all_listed_tickers.requests.get",
        lambda url, headers=None, timeout=None: FakeResponse(),
    )

    with pytest.raises(ValueError):
        resolve_latest_listing_url()


def test_download_listing_xls_bytes_overwrites_archive_path(monkeypatch, tmp_path):
    class FakeResponse:
        content = b"fake-xls-bytes"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(
        "scripts.import_all_listed_tickers.resolve_latest_listing_url",
        lambda: "https://www.jpx.co.jp/dummy/data_j.xls",
    )
    monkeypatch.setattr(
        "scripts.import_all_listed_tickers.requests.get",
        lambda url, headers=None, timeout=None: FakeResponse(),
    )

    archive_path = tmp_path / "docs" / "data_j.xls"
    result = download_listing_xls_bytes(archive_path=archive_path)

    assert result == b"fake-xls-bytes"
    assert archive_path.read_bytes() == b"fake-xls-bytes"


def test_main_downloads_and_imports_then_exits_zero(monkeypatch, session_factory):
    df = _listing_df([{"コード": "1301", "銘柄名": "極洋", "17業種区分": "食品"}])

    monkeypatch.setattr("scripts.import_all_listed_tickers.SessionLocal", session_factory)
    monkeypatch.setattr("scripts.import_all_listed_tickers.init_db", lambda engine: None)
    monkeypatch.setattr("scripts.import_all_listed_tickers.setup_logging", lambda **kwargs: None)
    monkeypatch.setattr(
        "scripts.import_all_listed_tickers.download_listing_xls_bytes", lambda: b""
    )
    monkeypatch.setattr("pandas.read_excel", lambda *args, **kwargs: df)

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0

    with session_factory() as session:
        assert session.get(CompanyProfile, "1301.T") is not None
