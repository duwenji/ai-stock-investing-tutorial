"""SQLAlchemyエンジン・セッション生成、DBスキーマ初期化。"""

from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from db.models import Base

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "app.db"


def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_db_engine(db_url: str | None = None) -> Engine:
    """指定したdb_urlのエンジンを作成する。省略時は本番用のdata/app.dbを使う
    （その場合はDATA_DIRを作成してから接続する）。フェーズ2以降、複数銘柄の
    並行フェッチ（map_concurrently）が同時にDB書き込みを行うため、SQLiteの
    書き込みロック競合時に即座にエラーにせず一定時間リトライ待機させる。
    SQLiteはデフォルトで外部キー制約を強制しないため、接続ごとにPRAGMAで
    有効化する（price_history等のticker列に張ったFKを実効化するため）。"""
    if db_url is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{DB_PATH}"
    engine = create_engine(db_url, connect_args={"timeout": 30})
    event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def init_db(engine: Engine) -> None:
    """未作成のテーブルのみ作成する（既存テーブルには影響しない）。加えて、既存の
    usersテーブルにfirst_name/last_name/is_admin列が無ければALTER TABLEで追加する
    （Alembic等の本格的なマイグレーションツールは使わない方針のため、この程度の
    単純な追加列はここで直接吸収する）。さらに、DB内にis_admin=Trueのユーザーが
    1人もいなければ、最初に作成されたユーザー（MIN(id)）へ自動的に管理者権限を
    付与する（既存DBへの追加・新規DBでの初回起動の両方をこの1つの判定でカバーする）。
    最後に、price_history/fundamentals_snapshots/ticker_newsのticker列に対する
    company_profiles.tickerへの外部キー制約を実効化する（既存DBでは孤児tickerの
    バックフィル＋テーブル再作成を伴う）。"""
    Base.metadata.create_all(engine)
    _ensure_user_name_columns(engine)
    _ensure_admin_column(engine)
    _grant_admin_to_first_user_if_none_exists(engine)
    _ensure_market_data_foreign_keys(engine)


def _add_column_if_missing(connection, existing_columns: set, column: str, ddl_type: str) -> None:
    """列が無ければALTER TABLEで追加する。Streamlitのホットリロード等でinit_db()が
    ほぼ同時に複数回実行され、片方が追加した直後にもう片方も追加を試みる競合が
    起こり得るため、"duplicate column"エラーは（列が既にある証拠として）無視する。"""
    if column in existing_columns:
        return
    try:
        connection.execute(text(f"ALTER TABLE users ADD COLUMN {column} {ddl_type}"))
    except OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise
        connection.rollback()


def _ensure_user_name_columns(engine: Engine) -> None:
    with engine.connect() as connection:
        existing_columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(users)")).fetchall()
        }
        for column in ("first_name", "last_name"):
            _add_column_if_missing(connection, existing_columns, column, "TEXT")
        connection.commit()


def _ensure_admin_column(engine: Engine) -> None:
    with engine.connect() as connection:
        existing_columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(users)")).fetchall()
        }
        _add_column_if_missing(connection, existing_columns, "is_admin", "BOOLEAN DEFAULT 0")
        connection.commit()


def _grant_admin_to_first_user_if_none_exists(engine: Engine) -> None:
    with engine.connect() as connection:
        admin_count = connection.execute(
            text("SELECT COUNT(*) FROM users WHERE is_admin = 1")
        ).scalar()
        if admin_count == 0:
            connection.execute(
                text("UPDATE users SET is_admin = 1 WHERE id = (SELECT MIN(id) FROM users)")
            )
            connection.commit()


def _backfill_missing_company_profiles(connection) -> None:
    """price_history/fundamentals_snapshots/ticker_newsに存在するがcompany_profilesに
    行が無いtickerに対して、tickerのみのスタブ行を追加する（FK制約を実効化する前に
    参照整合性を満たしておくため）。"""
    for table_name in ("price_history", "fundamentals_snapshots", "ticker_news"):
        connection.execute(
            text(
                f"INSERT INTO company_profiles (ticker) "
                f"SELECT DISTINCT ticker FROM {table_name} "
                f"WHERE ticker NOT IN (SELECT ticker FROM company_profiles)"
            )
        )


def _rebuild_table_with_foreign_key_if_missing(
    engine: Engine, table_name: str, columns: list[str]
) -> None:
    """table_nameのticker列にFK制約が未宣言なら、テーブルを作り直して制約を追加する
    （SQLiteはALTER TABLEでのFK制約後付けに対応していないため）。既にFK制約が
    宣言済み（新規作成されたテーブル等）なら何もしない。"""
    old_table = f"{table_name}_pre_fk_migration"
    with engine.connect() as connection:
        fk_rows = connection.execute(text(f"PRAGMA foreign_key_list({table_name})")).fetchall()
        if fk_rows:
            return
        try:
            connection.execute(text(f"ALTER TABLE {table_name} RENAME TO {old_table}"))
            connection.commit()
        except OperationalError:
            # Streamlitのホットリロード等でinit_db()がほぼ同時に複数回実行され、
            # 別プロセスが既にリネーム・再作成を完了させていた場合はスキップする
            connection.rollback()
            return

    Base.metadata.tables[table_name].create(bind=engine)

    column_list = ", ".join(columns)
    with engine.connect() as connection:
        connection.execute(
            text(
                f"INSERT INTO {table_name} ({column_list}) "
                f"SELECT {column_list} FROM {old_table}"
            )
        )
        connection.execute(text(f"DROP TABLE {old_table}"))
        connection.commit()


def _ensure_market_data_foreign_keys(engine: Engine) -> None:
    """price_history/fundamentals_snapshots/ticker_newsのticker列に、company_profiles.ticker
    への外部キー制約を実効化する。(1) 各テーブルに存在するがcompany_profilesに無い
    tickerをスタブ行として先に補完し、(2) FK制約が未宣言のテーブルのみ作り直す。
    新規作成されたばかりのDBでは(1)(2)とも対象が無いため実質何もしない。"""
    with engine.connect() as connection:
        _backfill_missing_company_profiles(connection)
        connection.commit()

    _rebuild_table_with_foreign_key_if_missing(
        engine,
        "price_history",
        ["id", "ticker", "date", "open", "high", "low", "close", "volume"],
    )
    _rebuild_table_with_foreign_key_if_missing(
        engine,
        "fundamentals_snapshots",
        [
            "id",
            "ticker",
            "snapshot_date",
            "name",
            "trailing_pe",
            "price_to_book",
            "dividend_yield",
            "market_cap",
            "return_on_equity",
            "revenue_growth",
        ],
    )
    _rebuild_table_with_foreign_key_if_missing(
        engine, "ticker_news", ["id", "ticker", "title", "publisher", "link", "fetched_at"]
    )


engine = create_db_engine()
SessionLocal = sessionmaker(bind=engine)
