"""SQLAlchemyエンジン・セッション生成、DBスキーマ初期化。"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from db.models import Base

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "app.db"


def create_db_engine(db_url: str | None = None) -> Engine:
    """指定したdb_urlのエンジンを作成する。省略時は本番用のdata/app.dbを使う
    （その場合はDATA_DIRを作成してから接続する）。"""
    if db_url is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{DB_PATH}"
    return create_engine(db_url)


def init_db(engine: Engine) -> None:
    """未作成のテーブルのみ作成する（既存テーブルには影響しない）。"""
    Base.metadata.create_all(engine)


engine = create_db_engine()
SessionLocal = sessionmaker(bind=engine)
