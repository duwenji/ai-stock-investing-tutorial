"""SQLAlchemyエンジン・セッション生成、DBスキーマ初期化。"""

from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from db.models import Base

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "app.db"


def create_db_engine(db_url: str | None = None) -> Engine:
    """指定したdb_urlのエンジンを作成する。省略時は本番用のdata/app.dbを使う
    （その場合はDATA_DIRを作成してから接続する）。フェーズ2以降、複数銘柄の
    並行フェッチ（map_concurrently）が同時にDB書き込みを行うため、SQLiteの
    書き込みロック競合時に即座にエラーにせず一定時間リトライ待機させる。"""
    if db_url is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{DB_PATH}"
    return create_engine(db_url, connect_args={"timeout": 30})


def init_db(engine: Engine) -> None:
    """未作成のテーブルのみ作成する（既存テーブルには影響しない）。加えて、既存の
    usersテーブルにfirst_name/last_name/is_admin列が無ければALTER TABLEで追加する
    （Alembic等の本格的なマイグレーションツールは使わない方針のため、この程度の
    単純な追加列はここで直接吸収する）。さらに、DB内にis_admin=Trueのユーザーが
    1人もいなければ、最初に作成されたユーザー（MIN(id)）へ自動的に管理者権限を
    付与する（既存DBへの追加・新規DBでの初回起動の両方をこの1つの判定でカバーする）。"""
    Base.metadata.create_all(engine)
    _ensure_user_name_columns(engine)
    _ensure_admin_column(engine)
    _grant_admin_to_first_user_if_none_exists(engine)


def _ensure_user_name_columns(engine: Engine) -> None:
    with engine.connect() as connection:
        existing_columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(users)")).fetchall()
        }
        for column in ("first_name", "last_name"):
            if column not in existing_columns:
                connection.execute(text(f"ALTER TABLE users ADD COLUMN {column} TEXT"))
        connection.commit()


def _ensure_admin_column(engine: Engine) -> None:
    with engine.connect() as connection:
        existing_columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(users)")).fetchall()
        }
        if "is_admin" not in existing_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0"))
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


engine = create_db_engine()
SessionLocal = sessionmaker(bind=engine)
