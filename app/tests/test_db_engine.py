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

        session.add(Holding(user_id=user.id, ticker="7203.T", shares=100.0, cost=2500.0))
        session.add(Strategy(user_id=user.id, strategy_name="A", strategy_json="{}"))
        session.add(
            SectorDisplaySetting(
                user_id=user.id, visible_json="{}", order_json="{}", height_json="{}"
            )
        )
        session.add(
            PriceHistory(
                ticker="7203.T", date="2026-01-01", open=1, high=1, low=1, close=1, volume=1
            )
        )
        session.add(
            FundamentalsSnapshot(ticker="7203.T", snapshot_date="2026-01-01", trailing_pe=12.0)
        )
        session.add(CompanyProfile(ticker="7203.T", name="トヨタ自動車"))
        session.add(TickerNews(ticker="7203.T", title="t", publisher="p", link="https://x/1"))
        session.commit()

    with session_factory() as session:
        assert session.query(Holding).count() == 1
        assert session.query(Strategy).count() == 1
        assert session.query(SectorDisplaySetting).count() == 1
        assert session.query(PriceHistory).count() == 1
        assert session.query(FundamentalsSnapshot).count() == 1
        assert session.query(CompanyProfile).count() == 1
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
        session.add(FundamentalsSnapshot(ticker="A", snapshot_date="2026-01-01"))
        session.commit()

        session.add(FundamentalsSnapshot(ticker="A", snapshot_date="2026-01-01"))
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
