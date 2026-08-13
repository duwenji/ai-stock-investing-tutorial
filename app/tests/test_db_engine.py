from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from db.engine import create_db_engine, init_db
from db.models import (
    CompanyProfile,
    FundamentalsSnapshot,
    Holding,
    PriceHistory,
    SectorDisplaySetting,
    Strategy,
    TickerNews,
    User,
)


def test_init_db_creates_all_tables(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    table_names = set(inspect(engine).get_table_names())
    assert {
        "users",
        "holdings",
        "strategies",
        "sector_display_settings",
        "price_history",
        "fundamentals_snapshots",
        "company_profiles",
        "ticker_news",
        "ai_sessions",
        "ai_generations",
    } <= table_names


def test_init_db_allows_basic_crud(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        user = User(username="taro", hashed_password="hashed")
        session.add(user)
        session.commit()
        session.refresh(user)

        session.add(Holding(user_id=user.id, ticker="TEST1.T", shares=100.0, cost=2500.0))
        session.add(Strategy(user_id=user.id, strategy_name="A", strategy_json="{}"))
        session.add(
            SectorDisplaySetting(
                user_id=user.id, visible_json="{}", order_json="{}", height_json="{}"
            )
        )
        session.add(
            PriceHistory(
                ticker="TEST1.T", date="2026-01-01", open=1, high=1, low=1, close=1, volume=1
            )
        )
        session.add(
            FundamentalsSnapshot(ticker="TEST1.T", snapshot_date="2026-01-01", trailing_pe=12.0)
        )
        session.add(CompanyProfile(ticker="TEST1.T", name="トヨタ自動車"))
        session.add(TickerNews(ticker="TEST1.T", title="t", publisher="p", link="https://x/1"))
        session.commit()

    with session_factory() as session:
        assert session.query(Holding).count() == 1
        assert session.query(Strategy).count() == 1
        assert session.query(SectorDisplaySetting).count() == 1
        assert session.query(PriceHistory).count() == 1
        assert session.query(FundamentalsSnapshot).count() == 1
        # company_profilesはinit_db()がseed_company_profiles.csvから228件を
        # 自動投入するため、全体件数ではなくこのテストが作った行を個別に確認する
        assert session.query(CompanyProfile).filter_by(ticker="TEST1.T").count() == 1
        assert session.query(TickerNews).count() == 1


def test_strategy_unique_constraint_on_user_and_name(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        user = User(username="taro", hashed_password="hashed")
        session.add(user)
        session.commit()
        session.refresh(user)

        session.add(Strategy(user_id=user.id, strategy_name="A", strategy_json="{}"))
        session.commit()

        session.add(Strategy(user_id=user.id, strategy_name="A", strategy_json="{}"))
        try:
            session.commit()
            assert False, "IntegrityErrorが発生するはず"
        except IntegrityError:
            session.rollback()


def test_price_history_unique_constraint_on_ticker_and_date(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(CompanyProfile(ticker="A"))
        session.add(
            PriceHistory(ticker="A", date="2026-01-01", open=1, high=1, low=1, close=1, volume=1)
        )
        session.commit()

        session.add(
            PriceHistory(ticker="A", date="2026-01-01", open=2, high=2, low=2, close=2, volume=2)
        )
        try:
            session.commit()
            assert False, "IntegrityErrorが発生するはず"
        except IntegrityError:
            session.rollback()


def test_fundamentals_snapshot_unique_constraint_on_ticker_and_date(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(CompanyProfile(ticker="A"))
        session.add(FundamentalsSnapshot(ticker="A", snapshot_date="2026-01-01"))
        session.commit()

        session.add(FundamentalsSnapshot(ticker="A", snapshot_date="2026-01-01"))
        try:
            session.commit()
            assert False, "IntegrityErrorが発生するはず"
        except IntegrityError:
            session.rollback()


def test_price_history_ticker_foreign_key_enforced(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(
            PriceHistory(
                ticker="NOPROFILE.T",
                date="2026-01-01",
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1,
            )
        )
        try:
            session.commit()
            assert False, "IntegrityErrorが発生するはず"
        except IntegrityError:
            session.rollback()


def test_fundamentals_snapshot_ticker_foreign_key_enforced(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(FundamentalsSnapshot(ticker="NOPROFILE.T", snapshot_date="2026-01-01"))
        try:
            session.commit()
            assert False, "IntegrityErrorが発生するはず"
        except IntegrityError:
            session.rollback()


def test_ticker_news_ticker_foreign_key_enforced(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(TickerNews(ticker="NOPROFILE.T", title="t", publisher="p", link="https://x/1"))
        try:
            session.commit()
            assert False, "IntegrityErrorが発生するはず"
        except IntegrityError:
            session.rollback()


def test_init_db_adds_missing_user_name_columns_to_existing_table(tmp_path):
    from sqlalchemy import text

    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    # フェーズ3以前（first_name/last_name追加前）のusersテーブルを模して作成する
    with engine.connect() as connection:
        connection.execute(
            text(
                "CREATE TABLE users ("
                "id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, "
                "email TEXT UNIQUE, hashed_password TEXT NOT NULL, created_at DATETIME)"
            )
        )
        connection.commit()

    init_db(engine)

    with engine.connect() as connection:
        columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(users)")).fetchall()
        }
    assert "first_name" in columns
    assert "last_name" in columns


def test_init_db_is_idempotent_on_second_call(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    init_db(engine)
    table_names = set(inspect(engine).get_table_names())
    assert "users" in table_names


def test_user_stores_first_name_and_last_name(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(
            User(
                username="taro",
                hashed_password="hashed",
                first_name="太郎",
                last_name="山田",
            )
        )
        session.commit()

    with session_factory() as session:
        stored = session.query(User).filter_by(username="taro").one()
        assert stored.first_name == "太郎"
        assert stored.last_name == "山田"


def test_init_db_adds_is_admin_column_to_existing_table(tmp_path):
    from sqlalchemy import text

    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    # is_admin列追加前のusersテーブルを模して作成する
    with engine.connect() as connection:
        connection.execute(
            text(
                "CREATE TABLE users ("
                "id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, "
                "email TEXT UNIQUE, hashed_password TEXT NOT NULL, created_at DATETIME)"
            )
        )
        connection.commit()

    init_db(engine)

    with engine.connect() as connection:
        columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(users)")).fetchall()
        }
    assert "is_admin" in columns


def test_init_db_grants_admin_to_first_user_when_no_admin_exists(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(User(username="alice", hashed_password="h"))
        session.add(User(username="bob", hashed_password="h"))
        session.commit()

    # init_db()の再呼び出し（実際にはapp.py起動のたびに呼ばれる）で
    # 最初に作成されたユーザーに管理者権限が自動付与される
    init_db(engine)

    with session_factory() as session:
        alice = session.query(User).filter_by(username="alice").one()
        bob = session.query(User).filter_by(username="bob").one()
        assert alice.is_admin is True
        assert bob.is_admin is False


def test_init_db_does_not_override_existing_admin_assignment(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(User(username="alice", hashed_password="h", is_admin=False))
        session.add(User(username="bob", hashed_password="h", is_admin=True))
        session.commit()

    init_db(engine)

    with session_factory() as session:
        alice = session.query(User).filter_by(username="alice").one()
        assert alice.is_admin is False  # 既にbobがadminなので上書きされない


def test_create_db_engine_enables_sqlite_foreign_keys(tmp_path):
    from sqlalchemy import text

    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with engine.connect() as connection:
        value = connection.execute(text("PRAGMA foreign_keys")).scalar()
    assert value == 1


def test_init_db_column_addition_tolerates_concurrent_duplicate_add(tmp_path):
    """Streamlitのホットリロード等でinit_db()がほぼ同時に複数回実行され、
    片方がALTER TABLEで列を追加した直後にもう片方も同じ列を追加しようとする
    競合状態を再現する。2回目の追加が"duplicate column"エラーになっても
    init_db()全体は例外を送出せず正常終了することを検証する。"""
    from sqlalchemy import text

    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)

    # is_admin列を追加済みの状態から、既存の列一覧に"is_admin"を含めずに
    # _add_column_if_missingを直接呼び、DB側では既に存在する列への
    # ALTER TABLEが実際に発生するようにする
    from db.engine import _add_column_if_missing

    with engine.connect() as connection:
        _add_column_if_missing(
            connection, "users", existing_columns=set(), column="is_admin", ddl_type="BOOLEAN DEFAULT 0"
        )
        connection.commit()

    with engine.connect() as connection:
        columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(users)")).fetchall()
        }
    assert "is_admin" in columns


def test_init_db_migrates_legacy_price_history_table_to_add_foreign_key(tmp_path):
    from sqlalchemy import text

    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with engine.connect() as connection:
        connection.execute(
            text(
                "CREATE TABLE price_history ("
                "id INTEGER PRIMARY KEY, ticker TEXT NOT NULL, date TEXT NOT NULL, "
                "open FLOAT NOT NULL, high FLOAT NOT NULL, low FLOAT NOT NULL, "
                "close FLOAT NOT NULL, volume FLOAT NOT NULL, "
                "UNIQUE (ticker, date))"
            )
        )
        # 実際の旧スキーマ（FK追加前）は ticker: Mapped[str] = mapped_column(..., index=True)
        # により明示的な単独インデックスも持っていた。これを再現しないと、
        # ALTER TABLE RENAME後もインデックス名だけは旧テーブル側に残る
        # というSQLiteの挙動由来のバグ（新テーブル作成時の同名インデックス
        # 衝突）を検出できない。
        connection.execute(
            text("CREATE INDEX ix_price_history_ticker ON price_history (ticker)")
        )
        connection.execute(
            text(
                "INSERT INTO price_history (ticker, date, open, high, low, close, volume) "
                "VALUES ('9999.T', '2026-01-01', 10, 11, 9, 10, 100)"
            )
        )
        connection.commit()

    init_db(engine)

    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        row = session.query(PriceHistory).filter_by(ticker="9999.T").one()
        assert row.date == "2026-01-01"
        assert row.open == 10.0

        profile = session.get(CompanyProfile, "9999.T")
        assert profile is not None

        session.add(
            PriceHistory(
                ticker="NOPROFILE.T",
                date="2026-01-02",
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1,
            )
        )
        try:
            session.commit()
            assert False, "IntegrityErrorが発生するはず"
        except IntegrityError:
            session.rollback()


def test_init_db_market_data_migration_is_idempotent(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    init_db(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        assert session.query(PriceHistory).count() == 0


def test_holdings_ticker_foreign_key_enforced(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        user = User(username="taro", hashed_password="hashed")
        session.add(user)
        session.commit()
        session.refresh(user)

        session.add(Holding(user_id=user.id, ticker="NOPROFILE.T", shares=1.0, cost=1.0))
        try:
            session.commit()
            assert False, "IntegrityErrorが発生するはず"
        except IntegrityError:
            session.rollback()


def test_init_db_migrates_legacy_holdings_table_that_already_has_a_users_foreign_key(tmp_path):
    """holdingsはuser_id -> users.idのFKを本制約導入前から持っており、
    「FKが1つも無いテーブルだけ作り直す」という単純な判定ではticker FKの
    追加漏れを見逃す。company_profiles宛のFKが無い場合に限って作り直す
    ことを検証する回帰テスト。"""
    from sqlalchemy import text

    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with engine.connect() as connection:
        connection.execute(
            text(
                "CREATE TABLE users ("
                "id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, "
                "email TEXT UNIQUE, hashed_password TEXT NOT NULL, created_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE holdings ("
                "id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, ticker TEXT NOT NULL, "
                "shares FLOAT NOT NULL, cost FLOAT NOT NULL, "
                "FOREIGN KEY(user_id) REFERENCES users (id))"
            )
        )
        connection.execute(
            text("INSERT INTO users (id, username, hashed_password) VALUES (1, 'taro', 'h')")
        )
        connection.execute(
            text(
                "INSERT INTO holdings (user_id, ticker, shares, cost) "
                "VALUES (1, '9999.T', 100, 2500)"
            )
        )
        connection.commit()

    init_db(engine)

    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        row = session.query(Holding).filter_by(ticker="9999.T").one()
        assert row.shares == 100.0

        profile = session.get(CompanyProfile, "9999.T")
        assert profile is not None

        # ticker FKが実効化されている
        session.add(Holding(user_id=1, ticker="NOPROFILE.T", shares=1.0, cost=1.0))
        try:
            session.commit()
            assert False, "IntegrityErrorが発生するはず"
        except IntegrityError:
            session.rollback()

        # 作り直し後もuser_id FKが失われていない
        session.add(Holding(user_id=999, ticker="9999.T", shares=1.0, cost=1.0))
        try:
            session.commit()
            assert False, "IntegrityErrorが発生するはず"
        except IntegrityError:
            session.rollback()


def test_init_db_adds_sector_jp_column_to_existing_company_profiles_table(tmp_path):
    from sqlalchemy import text

    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with engine.connect() as connection:
        connection.execute(
            text(
                "CREATE TABLE company_profiles ("
                "ticker TEXT PRIMARY KEY, name TEXT, name_updated_at DATETIME, "
                "sector TEXT, industry TEXT, business_summary TEXT, "
                "profile_updated_at DATETIME)"
            )
        )
        connection.commit()

    init_db(engine)

    with engine.connect() as connection:
        columns = {
            row[1]
            for row in connection.execute(
                text("PRAGMA table_info(company_profiles)")
            ).fetchall()
        }
    assert "sector_jp" in columns


def test_seed_default_company_profiles_inserts_missing_ticker(tmp_path):
    from db.engine import _seed_default_company_profiles

    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)

    seed_path = tmp_path / "seed.csv"
    seed_path.write_text(
        "ticker,name,sector_jp\nTEST1.T,テスト株式会社,情報通信・サービスその他\n",
        encoding="utf-8",
    )
    _seed_default_company_profiles(engine, seed_path=seed_path)

    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        profile = session.get(CompanyProfile, "TEST1.T")
        assert profile.name == "テスト株式会社"
        assert profile.sector_jp == "情報通信・サービスその他"


def test_seed_default_company_profiles_fills_only_null_fields(tmp_path):
    from db.engine import _seed_default_company_profiles

    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(CompanyProfile(ticker="TEST1.T", name="実際の名前"))
        session.commit()

    seed_path = tmp_path / "seed.csv"
    seed_path.write_text(
        "ticker,name,sector_jp\nTEST1.T,テスト株式会社,情報通信・サービスその他\n",
        encoding="utf-8",
    )
    _seed_default_company_profiles(engine, seed_path=seed_path)

    with session_factory() as session:
        profile = session.get(CompanyProfile, "TEST1.T")
        assert profile.name == "実際の名前"
        assert profile.sector_jp == "情報通信・サービスその他"


def test_seed_default_company_profiles_does_not_overwrite_existing_values(tmp_path):
    from db.engine import _seed_default_company_profiles

    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(CompanyProfile(ticker="TEST1.T", name="実際の名前", sector_jp="実際の業種"))
        session.commit()

    seed_path = tmp_path / "seed.csv"
    seed_path.write_text(
        "ticker,name,sector_jp\nTEST1.T,テスト株式会社,情報通信・サービスその他\n",
        encoding="utf-8",
    )
    _seed_default_company_profiles(engine, seed_path=seed_path)

    with session_factory() as session:
        profile = session.get(CompanyProfile, "TEST1.T")
        assert profile.name == "実際の名前"
        assert profile.sector_jp == "実際の業種"


def test_init_db_seeds_default_company_profiles_from_real_seed_file(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        profile = session.get(CompanyProfile, "7203.T")
        assert profile is not None
        assert profile.name
        assert profile.sector_jp


def test_init_db_migrates_multiple_legacy_tables_each_with_their_own_ticker_index(tmp_path):
    """本番DBで実際に起きた回帰の再現: price_history/fundamentals_snapshots/
    ticker_newsはいずれも旧スキーマの時点でticker列に単独インデックス
    （index=True由来）を持っていた。1回のinit_db()呼び出しで複数テーブルを
    連続して作り直す際、1つ目のテーブルの処理で放置されたインデックス名の
    衝突が2つ目以降のテーブルには影響しない（＝各テーブルの処理が独立して
    正しく完了する）ことを検証する。"""
    from sqlalchemy import text

    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with engine.connect() as connection:
        connection.execute(
            text(
                "CREATE TABLE price_history ("
                "id INTEGER PRIMARY KEY, ticker TEXT NOT NULL, date TEXT NOT NULL, "
                "open FLOAT NOT NULL, high FLOAT NOT NULL, low FLOAT NOT NULL, "
                "close FLOAT NOT NULL, volume FLOAT NOT NULL, "
                "UNIQUE (ticker, date))"
            )
        )
        connection.execute(
            text("CREATE INDEX ix_price_history_ticker ON price_history (ticker)")
        )
        connection.execute(
            text(
                "CREATE TABLE fundamentals_snapshots ("
                "id INTEGER PRIMARY KEY, ticker TEXT NOT NULL, snapshot_date TEXT NOT NULL, "
                "name TEXT, trailing_pe FLOAT, price_to_book FLOAT, dividend_yield FLOAT, "
                "market_cap FLOAT, return_on_equity FLOAT, revenue_growth FLOAT, "
                "UNIQUE (ticker, snapshot_date))"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX ix_fundamentals_snapshots_ticker "
                "ON fundamentals_snapshots (ticker)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO price_history (ticker, date, open, high, low, close, volume) "
                "VALUES ('9999.T', '2026-01-01', 10, 11, 9, 10, 100)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO fundamentals_snapshots (ticker, snapshot_date, trailing_pe) "
                "VALUES ('8888.T', '2026-01-01', 12.3)"
            )
        )
        connection.commit()

    init_db(engine)

    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        price_row = session.query(PriceHistory).filter_by(ticker="9999.T").one()
        assert price_row.date == "2026-01-01"

        fundamentals_row = (
            session.query(FundamentalsSnapshot).filter_by(ticker="8888.T").one()
        )
        assert fundamentals_row.trailing_pe == 12.3


def test_init_db_adds_summary_column_to_existing_ticker_news_table(tmp_path):
    from sqlalchemy import text

    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with engine.connect() as connection:
        connection.execute(
            text(
                "CREATE TABLE ticker_news ("
                "id INTEGER PRIMARY KEY, ticker TEXT NOT NULL, title TEXT, "
                "publisher TEXT, link TEXT, fetched_at DATETIME, "
                "FOREIGN KEY(ticker) REFERENCES company_profiles (ticker))"
            )
        )
        connection.commit()

    init_db(engine)

    with engine.connect() as connection:
        columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(ticker_news)")).fetchall()
        }
    assert "summary" in columns
