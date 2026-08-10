"""アプリのユーザー個別データを保持するSQLAlchemy ORMモデル定義。"""

import datetime

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(unique=True, nullable=True)
    hashed_password: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(default=_utcnow)


class Holding(Base):
    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(nullable=False)
    shares: Mapped[float] = mapped_column(nullable=False)
    cost: Mapped[float] = mapped_column(nullable=False)


class Strategy(Base):
    __tablename__ = "strategies"
    __table_args__ = (
        UniqueConstraint("user_id", "strategy_name", name="uq_strategy_user_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    strategy_name: Mapped[str] = mapped_column(nullable=False)
    strategy_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(default=_utcnow)


class SectorDisplaySetting(Base):
    __tablename__ = "sector_display_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    visible_json: Mapped[str] = mapped_column(Text, nullable=False)
    order_json: Mapped[str] = mapped_column(Text, nullable=False)
    height_json: Mapped[str] = mapped_column(Text, nullable=False)
