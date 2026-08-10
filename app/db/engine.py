"""SQLAlchemyエンジン・セッション生成、DBスキーマ初期化。"""

import csv
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from db.models import Base

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "app.db"
SEED_COMPANY_PROFILES_PATH = Path(__file__).resolve().parent / "seed_company_profiles.csv"


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
    price_history/fundamentals_snapshots/ticker_news/holdingsのticker列に対する
    company_profiles.tickerへの外部キー制約を実効化し、company_profilesに
    sector_jp列（東証17業種区分。UNIVERSE/SECTOR_MAP廃止に伴う追加）が無ければ
    追加する（既存DBでは孤児tickerのバックフィル＋テーブル再作成を伴う）。"""
    Base.metadata.create_all(engine)
    _ensure_user_name_columns(engine)
    _ensure_admin_column(engine)
    _grant_admin_to_first_user_if_none_exists(engine)
    _ensure_market_data_foreign_keys(engine)
    _ensure_company_profile_sector_jp_column(engine)
    _seed_default_company_profiles(engine)


def _add_column_if_missing(
    connection, table_name: str, existing_columns: set, column: str, ddl_type: str
) -> None:
    """列が無ければALTER TABLEで追加する。Streamlitのホットリロード等でinit_db()が
    ほぼ同時に複数回実行され、片方が追加した直後にもう片方も追加を試みる競合が
    起こり得るため、"duplicate column"エラーは（列が既にある証拠として）無視する。"""
    if column in existing_columns:
        return
    try:
        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column} {ddl_type}"))
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
            _add_column_if_missing(connection, "users", existing_columns, column, "TEXT")
        connection.commit()


def _ensure_admin_column(engine: Engine) -> None:
    with engine.connect() as connection:
        existing_columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(users)")).fetchall()
        }
        _add_column_if_missing(connection, "users", existing_columns, "is_admin", "BOOLEAN DEFAULT 0")
        connection.commit()


def _ensure_company_profile_sector_jp_column(engine: Engine) -> None:
    with engine.connect() as connection:
        existing_columns = {
            row[1]
            for row in connection.execute(
                text("PRAGMA table_info(company_profiles)")
            ).fetchall()
        }
        _add_column_if_missing(
            connection, "company_profiles", existing_columns, "sector_jp", "TEXT"
        )
        connection.commit()


def _seed_default_company_profiles(
    engine: Engine, seed_path: Path = SEED_COMPANY_PROFILES_PATH
) -> None:
    """seed_company_profiles.csv（旧UNIVERSE_NAMES/SECTOR_MAP相当の静的データ）を
    company_profilesへ投入する。該当tickerの行が無ければ新規作成し、あっても
    name/sector_jpがNULLの場合はそのフィールドのみ埋める。既に値が入っている列
    （実際にyfinanceから取得済みの値や管理者が編集した値）は上書きしない。"""
    if not seed_path.exists():
        return
    with seed_path.open(encoding="utf-8", newline="") as f:
        seed_rows = list(csv.DictReader(f))

    with engine.connect() as connection:
        for seed_row in seed_rows:
            ticker = seed_row["ticker"]
            existing = connection.execute(
                text("SELECT name, sector_jp FROM company_profiles WHERE ticker = :ticker"),
                {"ticker": ticker},
            ).first()
            if existing is None:
                connection.execute(
                    text(
                        "INSERT INTO company_profiles (ticker, name, sector_jp) "
                        "VALUES (:ticker, :name, :sector_jp)"
                    ),
                    {
                        "ticker": ticker,
                        "name": seed_row["name"],
                        "sector_jp": seed_row["sector_jp"],
                    },
                )
                continue
            existing_name, existing_sector_jp = existing
            if existing_name is None:
                connection.execute(
                    text("UPDATE company_profiles SET name = :name WHERE ticker = :ticker"),
                    {"ticker": ticker, "name": seed_row["name"]},
                )
            if existing_sector_jp is None:
                connection.execute(
                    text(
                        "UPDATE company_profiles SET sector_jp = :sector_jp "
                        "WHERE ticker = :ticker"
                    ),
                    {"ticker": ticker, "sector_jp": seed_row["sector_jp"]},
                )
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
    """price_history/fundamentals_snapshots/ticker_news/holdingsに存在するがcompany_profiles
    に行が無いtickerに対して、tickerのみのスタブ行を追加する（FK制約を実効化する前に
    参照整合性を満たしておくため）。"""
    for table_name in ("price_history", "fundamentals_snapshots", "ticker_news", "holdings"):
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
    """table_nameのticker列にcompany_profiles宛のFK制約が未宣言なら、テーブルを
    作り直して制約を追加する（SQLiteはALTER TABLEでのFK制約後付けに対応していない
    ため）。holdingsのようにuser_id -> users.id等、他のFKを既に持つテーブルもある
    ため、「FKが1つも無いか」ではなく「company_profiles宛のFKがあるか」で判定する
    （後者を先に持つテーブルは無いはずなので、他のFKは作り直し後も維持される）。"""
    old_table = f"{table_name}_pre_fk_migration"
    with engine.connect() as connection:
        fk_rows = connection.execute(text(f"PRAGMA foreign_key_list({table_name})")).fetchall()
        if any(row[2] == "company_profiles" for row in fk_rows):
            return
        try:
            connection.execute(text(f"ALTER TABLE {table_name} RENAME TO {old_table}"))
        except OperationalError:
            # Streamlitのホットリロード等でinit_db()がほぼ同時に複数回実行され、
            # 別プロセスが既にリネーム・再作成を完了させていた場合はスキップする
            connection.rollback()
            return

        # SQLiteのALTER TABLE RENAMEは明示的に名前を付けたインデックス（例:
        # index=Trueが生成するix_<table>_ticker）を追従してリネームしない
        # （インデックス自体は旧テーブル名のまま残り、参照先だけがリネーム後の
        # テーブルに切り替わる）。放置すると新テーブル作成時に同名インデックスの
        # 作成で衝突するため、旧テーブルに付いたインデックスは作り直し前に
        # 明示的に削除する（旧テーブル自体もこの後DROPするため実害はない）。
        index_rows = connection.execute(text(f"PRAGMA index_list({old_table})")).fetchall()
        for index_row in index_rows:
            index_name = index_row[1]
            if index_name.startswith("sqlite_autoindex_"):
                # UNIQUE制約由来の自動生成インデックスはDROP INDEX不可であり、
                # 旧テーブルごとDROPされるため個別の削除は不要
                continue
            connection.execute(text(f"DROP INDEX {index_name}"))
        connection.commit()

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
    """price_history/fundamentals_snapshots/ticker_news/holdingsのticker列に、
    company_profiles.tickerへの外部キー制約を実効化する。(1) 各テーブルに存在するが
    company_profilesに無いtickerをスタブ行として先に補完し、(2) company_profiles宛の
    FK制約が未宣言のテーブルのみ作り直す。新規作成されたばかりのDBでは(1)(2)とも
    対象が無いため実質何もしない。"""
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
    _rebuild_table_with_foreign_key_if_missing(
        engine, "holdings", ["id", "user_id", "ticker", "shares", "cost"]
    )


engine = create_db_engine()
SessionLocal = sessionmaker(bind=engine)
