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
    first_name: Mapped[str | None] = mapped_column(nullable=True)
    last_name: Mapped[str | None] = mapped_column(nullable=True)
    is_admin: Mapped[bool] = mapped_column(default=False, nullable=False)
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


class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_price_history_ticker_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(
        ForeignKey("company_profiles.ticker"), nullable=False, index=True
    )
    date: Mapped[str] = mapped_column(nullable=False)
    open: Mapped[float] = mapped_column(nullable=False)
    high: Mapped[float] = mapped_column(nullable=False)
    low: Mapped[float] = mapped_column(nullable=False)
    close: Mapped[float] = mapped_column(nullable=False)
    volume: Mapped[float] = mapped_column(nullable=False)


class FundamentalsSnapshot(Base):
    __tablename__ = "fundamentals_snapshots"
    __table_args__ = (
        UniqueConstraint("ticker", "snapshot_date", name="uq_fundamentals_ticker_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(
        ForeignKey("company_profiles.ticker"), nullable=False, index=True
    )
    snapshot_date: Mapped[str] = mapped_column(nullable=False)
    name: Mapped[str | None] = mapped_column(nullable=True)
    trailing_pe: Mapped[float | None] = mapped_column(nullable=True)
    price_to_book: Mapped[float | None] = mapped_column(nullable=True)
    dividend_yield: Mapped[float | None] = mapped_column(nullable=True)
    market_cap: Mapped[float | None] = mapped_column(nullable=True)
    return_on_equity: Mapped[float | None] = mapped_column(nullable=True)
    revenue_growth: Mapped[float | None] = mapped_column(nullable=True)


class CompanyProfile(Base):
    __tablename__ = "company_profiles"

    ticker: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(nullable=True)
    name_updated_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)
    sector: Mapped[str | None] = mapped_column(nullable=True)
    industry: Mapped[str | None] = mapped_column(nullable=True)
    business_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_updated_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)


class TickerNews(Base):
    __tablename__ = "ticker_news"
    __table_args__ = (
        UniqueConstraint("ticker", "link", name="uq_ticker_news_ticker_link"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(
        ForeignKey("company_profiles.ticker"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(nullable=True)
    publisher: Mapped[str | None] = mapped_column(nullable=True)
    link: Mapped[str | None] = mapped_column(nullable=True)
    fetched_at: Mapped[datetime.datetime] = mapped_column(default=_utcnow)
