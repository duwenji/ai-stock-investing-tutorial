# 市場データDB化（フェーズ2） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `data_api/stock_price_api.py`の各`fetch_*`関数を、DBを鮮度チェック付きの永続キャッシュとして使う**read-through**方式に変更し、株価・fundamentals・企業概要・日本語銘柄名・ニュースを全ユーザー・全プロセス再起動をまたいで共有・蓄積できるようにする（`docs/superpowers/specs/2026-08-10-database-multiuser-auth-design.md`のフェーズ2）。

**Architecture:** フェーズ1で導入済みの`db/`パッケージに`PriceHistory`/`FundamentalsSnapshot`/`CompanyProfile`/`TickerNews`の4テーブルを追加する。各`fetch_*`関数は「DBの鮮度を見て、新鮮ならDBから返す／古ければyfinance等から取得してDBへ書き込んでから返す」という同一パターンに統一する。`fetch_universe_fundamentals`/`fetch_universe_price_histories`（228銘柄一括）は専用ファイルキャッシュを廃止し、銘柄ごとの`fetch_fundamentals`/`fetch_price_history`（DB read-through）を並行呼び出しするだけの薄い集約関数にする。

**Tech Stack:** 既存のSQLAlchemy 2.0 + SQLite（フェーズ1と同じ`data/app.db`）。yfinance呼び出し自体は変更しない。

## Global Constraints

- Python >=3.14、パッケージ管理は`uv`（`ai-stock-investing-tutorial/app/pyproject.toml`）
- テストは`uv run pytest -v`（`app/`ディレクトリで実行）
- DBを使うテストは`tmp_path`上のファイルDB（`sqlite:///{tmp_path}/test.db`）を使う（`:memory:`は複数セッション間で共有できないため使わない）
- DB操作を行う関数は`session_factory`引数（デフォルトは本番用`db.engine.SessionLocal`）を受け取り、テストでは注入する（フェーズ1と同じDIパターン）
- 既存の`fetch_price_history`/`fetch_fundamentals`/`fetch_universe_fundamentals`/`fetch_universe_price_histories`が持つ「呼び出し元で処理系（`fetch_fundamentals=...`等）を差し替え可能」というDIパターンは維持する
- 個別銘柄の取得失敗が全体を止めない防御的実装（`isinstance(result, Exception)`でスキップ）は維持する
- リポジトリはmasterへの直接コミット運用（フィーチャーブランチ・worktreeは使わない）
- 各タスックの最後に該当テストファイルを実行して確認し、コミットする

---

### Task 1: DBモデル拡張（PriceHistory/FundamentalsSnapshot/CompanyProfile/TickerNews）

**Files:**
- Modify: `ai-stock-investing-tutorial/app/db/models.py`
- Modify: `ai-stock-investing-tutorial/app/db/engine.py`
- Modify: `ai-stock-investing-tutorial/app/tests/test_db_engine.py`

**Interfaces:**
- Produces:
  - `db.models.PriceHistory(id, ticker, date, open, high, low, close, volume)` — `UNIQUE(ticker, date)`
  - `db.models.FundamentalsSnapshot(id, ticker, snapshot_date, name, trailing_pe, price_to_book, dividend_yield, market_cap, return_on_equity, revenue_growth)` — `UNIQUE(ticker, snapshot_date)`。列名はfetch_fundamentals()が返す生の辞書のキーに合わせる（ROE/売上高伸び率のパーセント変換はfetch_universe_fundamentals側で行う既存方針を維持するため）
  - `db.models.CompanyProfile(ticker [PK], name, name_updated_at, sector, industry, business_summary, profile_updated_at)`
  - `db.models.TickerNews(id, ticker, title, publisher, link, fetched_at)` — `UNIQUE(ticker, link)`
  - `db.engine.create_db_engine`は`connect_args={"timeout": 30}`付きでエンジンを作る（後続タスクで複数銘柄を並行フェッチする際、SQLiteの書き込みロック競合で即座にエラーにせず一定時間リトライ待機させるため）

- [ ] **Step 1: 失敗するテストを書く**

`ai-stock-investing-tutorial/app/tests/test_db_engine.py`（既存内容を置き換え）:

```python
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
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_db_engine.py -v`
Expected: FAIL（`ImportError: cannot import name 'PriceHistory' from 'db.models'`）

- [ ] **Step 3: `db/models.py`にテーブルを追加する**

`ai-stock-investing-tutorial/app/db/models.py`の末尾に追加:

```python
class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_price_history_ticker_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(nullable=False, index=True)
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
    ticker: Mapped[str] = mapped_column(nullable=False, index=True)
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
    ticker: Mapped[str] = mapped_column(nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(nullable=True)
    publisher: Mapped[str | None] = mapped_column(nullable=True)
    link: Mapped[str | None] = mapped_column(nullable=True)
    fetched_at: Mapped[datetime.datetime] = mapped_column(default=_utcnow)
```

- [ ] **Step 4: `db/engine.py`にSQLite書き込みタイムアウトを設定する**

`ai-stock-investing-tutorial/app/db/engine.py`、変更前:

```python
def create_db_engine(db_url: str | None = None) -> Engine:
    """指定したdb_urlのエンジンを作成する。省略時は本番用のdata/app.dbを使う
    （その場合はDATA_DIRを作成してから接続する）。"""
    if db_url is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{DB_PATH}"
    return create_engine(db_url)
```

変更後:

```python
def create_db_engine(db_url: str | None = None) -> Engine:
    """指定したdb_urlのエンジンを作成する。省略時は本番用のdata/app.dbを使う
    （その場合はDATA_DIRを作成してから接続する）。フェーズ2以降、複数銘柄の
    並行フェッチ（map_concurrently）が同時にDB書き込みを行うため、SQLiteの
    書き込みロック競合時に即座にエラーにせず一定時間リトライ待機させる。"""
    if db_url is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{DB_PATH}"
    return create_engine(db_url, connect_args={"timeout": 30})
```

- [ ] **Step 5: テストを実行して通ることを確認する**

Run: `uv run pytest tests/test_db_engine.py -v`
Expected: PASS（6件）

- [ ] **Step 6: 全体テストスイートを実行して回帰が無いことを確認する**

Run: `uv run pytest -v`
Expected: PASS（全件）

- [ ] **Step 7: Commit**

```bash
git add db/models.py db/engine.py tests/test_db_engine.py
git commit -m "feat: 市場データ用テーブル（PriceHistory/FundamentalsSnapshot/CompanyProfile/TickerNews）を追加"
```

---

### Task 2: `fetch_price_history`のread-through化

**Files:**
- Modify: `ai-stock-investing-tutorial/app/data_api/stock_price_api.py`
- Modify: `ai-stock-investing-tutorial/app/tests/test_stock_price_api.py`

**Interfaces:**
- Consumes: `db.engine.SessionLocal`、`db.models.PriceHistory`（Task 1）
- Produces:
  - `data_api.stock_price_api.fetch_price_history(ticker_symbol: str, period: str = "1mo", session_factory=SessionLocal) -> pd.DataFrame`（戻り値の形は既存と同じ: `Open`/`High`/`Low`/`Close`/`Volume`列を持つDataFrame、インデックスは日付）
  - `data_api.stock_price_api._MAX_FETCH_PERIOD = "5y"`（鮮度切れ時に常にこの期間で取得する定数。アプリ内で使われる最大期間に合わせてあり、以後どの期間で要求されてもDBだけで足りるようにする）
  - `data_api.stock_price_api._upsert_price_history(session, ticker_symbol, history)`（内部ヘルパー、Task 6のテストからも直接使う）

- [ ] **Step 1: 失敗するテストを書く**

`ai-stock-investing-tutorial/app/tests/test_stock_price_api.py`の冒頭のimportに追加:

```python
import datetime
import logging

import pandas as pd
import pytest
from sqlalchemy.orm import sessionmaker

import data_api.stock_price_api as stock_price_api
from db.engine import create_db_engine, init_db
```

`FakeTicker.history`（既存の13-14行目）を置き換え:

変更前:

```python
    def history(self, period="1mo"):
        return pd.DataFrame({"Close": [100, 101, 102]})
```

変更後:

```python
    def history(self, period="1mo"):
        dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=3, freq="D")
        return pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0],
                "High": [105.0, 106.0, 107.0],
                "Low": [99.0, 100.0, 101.0],
                "Close": [100.0, 101.0, 102.0],
                "Volume": [1000.0, 1100.0, 1200.0],
            },
            index=dates,
        )
```

`test_fetch_price_history_returns_dataframe`と`test_fetch_price_history_logs_request_and_response`を置き換え、新規テストを追加（既存の該当箇所を全てこの内容に差し替え）:

```python
def test_fetch_price_history_returns_dataframe(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    df = stock_price_api.fetch_price_history("7203.T", session_factory=session_factory)
    assert list(df["Close"]) == [100.0, 101.0, 102.0]


def test_fetch_price_history_reuses_db_on_second_call(monkeypatch, tmp_path):
    call_count = {"n": 0}

    class CountingTicker(FakeTicker):
        def history(self, period="1mo"):
            call_count["n"] += 1
            return super().history(period=period)

    monkeypatch.setattr(stock_price_api.yf, "Ticker", CountingTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_price_history("7203.T", session_factory=session_factory)
    assert call_count["n"] == 1

    stock_price_api.fetch_price_history("7203.T", session_factory=session_factory)
    assert call_count["n"] == 1


def test_fetch_price_history_refetches_when_stale(monkeypatch, tmp_path):
    call_count = {"n": 0}

    class CountingTicker(FakeTicker):
        def history(self, period="1mo"):
            call_count["n"] += 1
            return super().history(period=period)

    monkeypatch.setattr(stock_price_api.yf, "Ticker", CountingTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    old_date = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
    with session_factory() as session:
        session.add(
            stock_price_api.PriceHistory(
                ticker="7203.T", date=old_date, open=1, high=1, low=1, close=1, volume=1
            )
        )
        session.commit()

    stock_price_api.fetch_price_history("7203.T", session_factory=session_factory)
    assert call_count["n"] == 1


def test_upsert_price_history_skips_existing_dates(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    history = pd.DataFrame(
        {
            "Open": [1.0, 2.0, 3.0],
            "High": [1.0, 2.0, 3.0],
            "Low": [1.0, 2.0, 3.0],
            "Close": [1.0, 2.0, 3.0],
            "Volume": [1.0, 2.0, 3.0],
        },
        index=dates,
    )

    with session_factory() as session:
        stock_price_api._upsert_price_history(session, "7203.T", history)
        session.commit()
        assert session.query(stock_price_api.PriceHistory).count() == 3

    with session_factory() as session:
        stock_price_api._upsert_price_history(session, "7203.T", history)
        session.commit()
        assert session.query(stock_price_api.PriceHistory).count() == 3


def test_fetch_price_history_logs_request_and_response(monkeypatch, caplog, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_price_history("7203.T", session_factory=session_factory)

    assert (
        f"株価履歴リクエスト: ticker=7203.T period={stock_price_api._MAX_FETCH_PERIOD}"
        in caplog.text
    )
    assert "株価履歴レスポンス: ticker=7203.T" in caplog.text
    assert "101" in caplog.text
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_stock_price_api.py -v`
Expected: FAIL（`fetch_price_history()`が`session_factory`引数を受け付けない、`_upsert_price_history`が存在しない等）

- [ ] **Step 3: `data_api/stock_price_api.py`の`fetch_price_history`をread-through化する**

`ai-stock-investing-tutorial/app/data_api/stock_price_api.py`冒頭のimportに追加:

```python
import datetime
```

（既存の`import hashlib` / `import json` / `import logging` / `import re` / `from pathlib import Path`のブロックに追加。`hashlib`/`json`/`Path`はTask 6で不要になるためこの時点ではまだ残す）

さらに以下を追加:

```python
from db.engine import SessionLocal
from db.models import PriceHistory
```

`fetch_price_history`関数（26-36行目）を置き換え:

変更前:

```python
def fetch_price_history(ticker_symbol: str, period: str = "1mo"):
    """指定銘柄の株価時系列（OHLCV）をyfinance経由で取得する。"""
    logger.info("株価履歴リクエスト: ticker=%s period=%s", ticker_symbol, period)
    ticker = yf.Ticker(ticker_symbol)
    history = ticker.history(period=period)
    logger.info(
        "株価履歴レスポンス: ticker=%s data=%s",
        ticker_symbol,
        history.to_json(orient="records", date_format="iso"),
    )
    return history
```

変更後:

```python
# アプリ内で使われる最大期間（1mo/6mo/1y/2y/3y/5y）。鮮度切れ時は常にこの期間で
# yfinanceから取得してDBへ蓄積することで、以後どの期間で要求されてもDBだけで
# 足りるようにする（呼び出しごとに異なる期間を要求されても再フェッチが不要になる）。
_MAX_FETCH_PERIOD = "5y"
_PERIOD_TO_DAYS = {
    "1mo": 31,
    "6mo": 186,
    "1y": 366,
    "2y": 731,
    "3y": 1096,
    "5y": 1827,
}


def _period_to_start_date(period: str) -> datetime.date:
    days = _PERIOD_TO_DAYS.get(period, 366)
    return datetime.date.today() - datetime.timedelta(days=days)


def _fetch_price_history_from_yfinance(ticker_symbol: str, period: str) -> pd.DataFrame:
    """yfinanceから直接株価時系列を取得する（DBを経由しない生の取得処理）。"""
    logger.info("株価履歴リクエスト: ticker=%s period=%s", ticker_symbol, period)
    ticker = yf.Ticker(ticker_symbol)
    history = ticker.history(period=period)
    logger.info(
        "株価履歴レスポンス: ticker=%s data=%s",
        ticker_symbol,
        history.to_json(orient="records", date_format="iso"),
    )
    return history


def _upsert_price_history(session, ticker_symbol: str, history: pd.DataFrame) -> None:
    """historyの各日付をPriceHistoryへ追記する。既にDBにある日付は上書きしない
    （時系列を蓄積する方針のため）。"""
    if history.empty:
        return
    existing_dates = {
        row.date
        for row in session.query(PriceHistory.date).filter_by(ticker=ticker_symbol).all()
    }
    for index, row in history.iterrows():
        date_str = index.date().isoformat() if hasattr(index, "date") else str(index)
        if date_str in existing_dates:
            continue
        session.add(
            PriceHistory(
                ticker=ticker_symbol,
                date=date_str,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row["Volume"]),
            )
        )
        existing_dates.add(date_str)


def _load_price_history_from_db(session, ticker_symbol: str, period: str) -> pd.DataFrame:
    start_date = _period_to_start_date(period).isoformat()
    rows = (
        session.query(PriceHistory)
        .filter(PriceHistory.ticker == ticker_symbol, PriceHistory.date >= start_date)
        .order_by(PriceHistory.date)
        .all()
    )
    if not rows:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    return pd.DataFrame(
        {
            "Open": [r.open for r in rows],
            "High": [r.high for r in rows],
            "Low": [r.low for r in rows],
            "Close": [r.close for r in rows],
            "Volume": [r.volume for r in rows],
        },
        index=pd.to_datetime([r.date for r in rows]),
    )


def fetch_price_history(
    ticker_symbol: str, period: str = "1mo", session_factory=SessionLocal
) -> pd.DataFrame:
    """指定銘柄の株価時系列（OHLCV）を取得する。DB上の当該銘柄の最新日付が
    「本日から1日以内」ならDBから期間分を組み立てて返す。それより古い/データ無し
    ならyfinanceから_MAX_FETCH_PERIOD分を取得してPriceHistoryへ追記した上で、
    DBから期間分を組み立てて返す。"""
    with session_factory() as session:
        latest_date_str = (
            session.query(PriceHistory.date)
            .filter_by(ticker=ticker_symbol)
            .order_by(PriceHistory.date.desc())
            .limit(1)
            .scalar()
        )
        is_fresh = latest_date_str is not None and (
            datetime.date.today() - datetime.date.fromisoformat(latest_date_str)
        ).days <= 1

        if not is_fresh:
            history = _fetch_price_history_from_yfinance(ticker_symbol, _MAX_FETCH_PERIOD)
            _upsert_price_history(session, ticker_symbol, history)
            session.commit()

        return _load_price_history_from_db(session, ticker_symbol, period)
```

- [ ] **Step 4: テストを実行して通ることを確認する**

Run: `uv run pytest tests/test_stock_price_api.py -v`
Expected: 価格履歴関連のテストはPASS。fundamentals/news/company_profile/japanese_name関連のテストは、まだ関数側を変更していない`fetch_universe_fundamentals`/`fetch_universe_price_histories`のテスト（`tmp_path`を渡す旧シグネチャ）が失敗する可能性がある — これはTask 6で対応するため、このタスクでは価格履歴関連のテスト（`test_fetch_price_history_*`, `test_upsert_price_history_*`）がPASSすることのみを確認する

Run: `uv run pytest tests/test_stock_price_api.py -v -k "price_history"`
Expected: PASS（全件）

- [ ] **Step 5: Commit**

```bash
git add data_api/stock_price_api.py tests/test_stock_price_api.py
git commit -m "refactor: fetch_price_historyをDB read-through方式に変更"
```

---

### Task 3: `fetch_fundamentals`のread-through化

**Files:**
- Modify: `ai-stock-investing-tutorial/app/data_api/stock_price_api.py`
- Modify: `ai-stock-investing-tutorial/app/tests/test_stock_price_api.py`

**Interfaces:**
- Consumes: `db.models.FundamentalsSnapshot`（Task 1）
- Produces: `data_api.stock_price_api.fetch_fundamentals(ticker_symbol: str, session_factory=SessionLocal) -> dict`（戻り値の形は既存と同じ）

- [ ] **Step 1: 失敗するテストを書く**

`test_fetch_fundamentals_maps_info_fields`・`test_fetch_fundamentals_missing_fields_return_none`・`test_fetch_fundamentals_logs_request_and_response`を置き換え、新規テストを追加:

```python
def test_fetch_fundamentals_maps_info_fields(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    result = stock_price_api.fetch_fundamentals("7203.T", session_factory=session_factory)
    assert result["ticker"] == "7203.T"
    assert result["name"] == "Fake Corp"
    assert result["trailing_pe"] == 12.3
    assert result["price_to_book"] == 1.1
    assert result["dividend_yield"] == 0.02
    assert result["market_cap"] == 1_000_000
    assert result["return_on_equity"] == 0.155
    assert result["revenue_growth"] == 0.082


def test_fetch_fundamentals_missing_fields_return_none(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", EmptyInfoTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    result = stock_price_api.fetch_fundamentals("7203.T", session_factory=session_factory)
    assert result["trailing_pe"] is None
    assert result["price_to_book"] is None
    assert result["return_on_equity"] is None
    assert result["revenue_growth"] is None


def test_fetch_fundamentals_reuses_snapshot_on_second_call_same_day(monkeypatch, tmp_path):
    call_count = {"n": 0}

    class CountingTicker(FakeTicker):
        @property
        def info(self):
            call_count["n"] += 1
            return super().info

    monkeypatch.setattr(stock_price_api.yf, "Ticker", CountingTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_fundamentals("7203.T", session_factory=session_factory)
    assert call_count["n"] == 1
    stock_price_api.fetch_fundamentals("7203.T", session_factory=session_factory)
    assert call_count["n"] == 1


def test_fetch_fundamentals_logs_request_and_response(monkeypatch, caplog, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_fundamentals("7203.T", session_factory=session_factory)

    assert "fundamentalsリクエスト: ticker=7203.T" in caplog.text
    assert "fundamentalsレスポンス: ticker=7203.T" in caplog.text
    assert "Fake Corp" in caplog.text
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_stock_price_api.py -v -k "fundamentals and not universe"`
Expected: FAIL（`fetch_fundamentals()`が`session_factory`引数を受け付けない）

- [ ] **Step 3: `fetch_fundamentals`をread-through化する**

`data_api/stock_price_api.py`の`from db.models import PriceHistory`を次のように拡張:

```python
from db.models import FundamentalsSnapshot, PriceHistory
```

`fetch_fundamentals`関数（39-55行目）を置き換え:

変更前:

```python
def fetch_fundamentals(ticker_symbol: str) -> dict:
    """指定銘柄のファンダメンタルズ指標（PER・PBR・配当利回り・ROE・売上高伸び率等）を取得する。"""
    logger.info("fundamentalsリクエスト: ticker=%s", ticker_symbol)
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info
    result = {
        "ticker": ticker_symbol,
        "name": info.get("longName"),
        "trailing_pe": info.get("trailingPE"),
        "price_to_book": info.get("priceToBook"),
        "dividend_yield": info.get("dividendYield"),
        "market_cap": info.get("marketCap"),
        "return_on_equity": info.get("returnOnEquity"),
        "revenue_growth": info.get("revenueGrowth"),
    }
    logger.info("fundamentalsレスポンス: ticker=%s data=%s", ticker_symbol, result)
    return result
```

変更後:

```python
def _fetch_fundamentals_from_yfinance(ticker_symbol: str) -> dict:
    """yfinanceから直接ファンダメンタルズ指標を取得する（DBを経由しない生の取得処理）。"""
    logger.info("fundamentalsリクエスト: ticker=%s", ticker_symbol)
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info
    result = {
        "ticker": ticker_symbol,
        "name": info.get("longName"),
        "trailing_pe": info.get("trailingPE"),
        "price_to_book": info.get("priceToBook"),
        "dividend_yield": info.get("dividendYield"),
        "market_cap": info.get("marketCap"),
        "return_on_equity": info.get("returnOnEquity"),
        "revenue_growth": info.get("revenueGrowth"),
    }
    logger.info("fundamentalsレスポンス: ticker=%s data=%s", ticker_symbol, result)
    return result


def _fundamentals_snapshot_to_dict(row: FundamentalsSnapshot) -> dict:
    return {
        "ticker": row.ticker,
        "name": row.name,
        "trailing_pe": row.trailing_pe,
        "price_to_book": row.price_to_book,
        "dividend_yield": row.dividend_yield,
        "market_cap": row.market_cap,
        "return_on_equity": row.return_on_equity,
        "revenue_growth": row.revenue_growth,
    }


def fetch_fundamentals(ticker_symbol: str, session_factory=SessionLocal) -> dict:
    """指定銘柄のファンダメンタルズ指標を取得する。当日分のスナップショットが
    DBにあればそれを返し、無ければyfinanceから取得してDBへ新規スナップショット
    として追加する（同日内は追加取得しない）。"""
    today = datetime.date.today().isoformat()
    with session_factory() as session:
        row = (
            session.query(FundamentalsSnapshot)
            .filter_by(ticker=ticker_symbol, snapshot_date=today)
            .first()
        )
        if row is not None:
            return _fundamentals_snapshot_to_dict(row)

        result = _fetch_fundamentals_from_yfinance(ticker_symbol)
        session.add(
            FundamentalsSnapshot(
                ticker=ticker_symbol,
                snapshot_date=today,
                name=result["name"],
                trailing_pe=result["trailing_pe"],
                price_to_book=result["price_to_book"],
                dividend_yield=result["dividend_yield"],
                market_cap=result["market_cap"],
                return_on_equity=result["return_on_equity"],
                revenue_growth=result["revenue_growth"],
            )
        )
        session.commit()
        return result
```

- [ ] **Step 4: テストを実行して通ることを確認する**

Run: `uv run pytest tests/test_stock_price_api.py -v -k "fundamentals and not universe"`
Expected: PASS（全件）

- [ ] **Step 5: Commit**

```bash
git add data_api/stock_price_api.py tests/test_stock_price_api.py
git commit -m "refactor: fetch_fundamentalsをDB read-through方式に変更"
```

---

### Task 4: `fetch_company_profile`・`fetch_japanese_name`のread-through化（CompanyProfile統合）

**Files:**
- Modify: `ai-stock-investing-tutorial/app/data_api/stock_price_api.py`
- Modify: `ai-stock-investing-tutorial/app/tests/test_stock_price_api.py`

**Interfaces:**
- Consumes: `db.models.CompanyProfile`（Task 1）
- Produces:
  - `data_api.stock_price_api.fetch_company_profile(ticker_symbol: str, session_factory=SessionLocal) -> dict`
  - `data_api.stock_price_api.fetch_japanese_name(ticker_symbol: str, session_factory=SessionLocal) -> str | None`
  - `data_api.stock_price_api._PROFILE_FRESHNESS_DAYS = 30`

- [ ] **Step 1: 失敗するテストを書く**

`test_fetch_japanese_name_parses_yahoo_jp_title`・`test_fetch_japanese_name_returns_none_when_title_missing_marker`・`test_fetch_japanese_name_returns_none_on_request_failure`・`test_fetch_japanese_name_logs_request_and_response`・`test_fetch_japanese_name_logs_warning_on_request_failure`・`test_fetch_company_profile_maps_info_fields`・`test_fetch_company_profile_missing_fields_return_none`・`test_fetch_company_profile_logs_request_and_response`を置き換え、新規テストを追加:

```python
def test_fetch_company_profile_maps_info_fields(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    result = stock_price_api.fetch_company_profile("7203.T", session_factory=session_factory)
    assert result["ticker"] == "7203.T"
    assert result["sector"] == "Consumer Cyclical"
    assert result["industry"] == "Auto Manufacturers"
    assert result["business_summary"] == "Test business summary text."


def test_fetch_company_profile_missing_fields_return_none(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", EmptyInfoTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    result = stock_price_api.fetch_company_profile("7203.T", session_factory=session_factory)
    assert result["sector"] is None
    assert result["industry"] is None
    assert result["business_summary"] is None


def test_fetch_company_profile_reuses_db_within_freshness_window(monkeypatch, tmp_path):
    call_count = {"n": 0}

    class CountingTicker(FakeTicker):
        @property
        def info(self):
            call_count["n"] += 1
            return super().info

    monkeypatch.setattr(stock_price_api.yf, "Ticker", CountingTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_company_profile("7203.T", session_factory=session_factory)
    assert call_count["n"] == 1
    stock_price_api.fetch_company_profile("7203.T", session_factory=session_factory)
    assert call_count["n"] == 1


def test_fetch_company_profile_refetches_when_stale(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    old_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=31)
    with session_factory() as session:
        session.add(
            stock_price_api.CompanyProfile(
                ticker="7203.T", sector="Old", industry="Old", profile_updated_at=old_time
            )
        )
        session.commit()

    result = stock_price_api.fetch_company_profile("7203.T", session_factory=session_factory)
    assert result["sector"] == "Consumer Cyclical"


def test_fetch_company_profile_logs_request_and_response(monkeypatch, caplog, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_company_profile("7203.T", session_factory=session_factory)

    assert "company profileリクエスト: ticker=7203.T" in caplog.text
    assert "company profileレスポンス: ticker=7203.T" in caplog.text
    assert "Auto Manufacturers" in caplog.text


def test_fetch_japanese_name_parses_yahoo_jp_title(monkeypatch, tmp_path):
    def fake_get(url, headers=None, timeout=None):
        assert url == "https://finance.yahoo.co.jp/quote/6753.T"
        return FakeResponse(
            "<title>シャープ(株)【6753】：株価・株式情報（夜間PTS含む） - Yahoo!ファイナンス</title>"
        )

    monkeypatch.setattr(stock_price_api.requests, "get", fake_get)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    assert stock_price_api.fetch_japanese_name(
        "6753.T", session_factory=session_factory
    ) == "シャープ(株)"


def test_fetch_japanese_name_returns_none_when_title_missing_marker(monkeypatch, tmp_path):
    monkeypatch.setattr(
        stock_price_api.requests,
        "get",
        lambda url, headers=None, timeout=None: FakeResponse(
            "<title>ページが見つかりません - Yahoo!ファイナンス</title>"
        ),
    )
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    # マーカー「【」を含まないタイトルはティッカーページではないとみなし None を返す
    assert stock_price_api.fetch_japanese_name("0000.T", session_factory=session_factory) is None


def test_fetch_japanese_name_returns_none_on_request_failure(monkeypatch, tmp_path):
    def raise_error(url, headers=None, timeout=None):
        raise stock_price_api.requests.RequestException("network error")

    monkeypatch.setattr(stock_price_api.requests, "get", raise_error)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    assert stock_price_api.fetch_japanese_name("6753.T", session_factory=session_factory) is None


def test_fetch_japanese_name_reuses_db_within_freshness_window(monkeypatch, tmp_path):
    call_count = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        call_count["n"] += 1
        return FakeResponse(
            "<title>シャープ(株)【6753】：株価・株式情報（夜間PTS含む） - Yahoo!ファイナンス</title>"
        )

    monkeypatch.setattr(stock_price_api.requests, "get", fake_get)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_japanese_name("6753.T", session_factory=session_factory)
    assert call_count["n"] == 1
    stock_price_api.fetch_japanese_name("6753.T", session_factory=session_factory)
    assert call_count["n"] == 1


def test_fetch_japanese_name_logs_request_and_response(monkeypatch, caplog, tmp_path):
    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(
            "<title>シャープ(株)【6753】：株価・株式情報（夜間PTS含む） - Yahoo!ファイナンス</title>"
        )

    monkeypatch.setattr(stock_price_api.requests, "get", fake_get)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_japanese_name("6753.T", session_factory=session_factory)

    assert "日本語銘柄名リクエスト: url=https://finance.yahoo.co.jp/quote/6753.T" in caplog.text
    assert "日本語銘柄名レスポンス: url=https://finance.yahoo.co.jp/quote/6753.T" in caplog.text
    assert "シャープ" in caplog.text


def test_fetch_japanese_name_logs_warning_on_request_failure(monkeypatch, caplog, tmp_path):
    def raise_error(url, headers=None, timeout=None):
        raise stock_price_api.requests.RequestException("network error")

    monkeypatch.setattr(stock_price_api.requests, "get", raise_error)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_japanese_name("6753.T", session_factory=session_factory)

    assert "日本語銘柄名取得失敗: url=https://finance.yahoo.co.jp/quote/6753.T" in caplog.text


def test_company_profile_and_japanese_name_update_independently(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)

    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(
            "<title>シャープ(株)【6753】：株価・株式情報（夜間PTS含む） - Yahoo!ファイナンス</title>"
        )

    monkeypatch.setattr(stock_price_api.requests, "get", fake_get)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_japanese_name("6753.T", session_factory=session_factory)
    stock_price_api.fetch_company_profile("6753.T", session_factory=session_factory)

    with session_factory() as session:
        row = session.get(stock_price_api.CompanyProfile, "6753.T")
        assert row.name == "シャープ(株)"
        assert row.sector == "Consumer Cyclical"
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_stock_price_api.py -v -k "company_profile or japanese_name"`
Expected: FAIL（シグネチャ不一致・`CompanyProfile`未import）

- [ ] **Step 3: `fetch_company_profile`・`fetch_japanese_name`をread-through化する**

`data_api/stock_price_api.py`の`from db.models import FundamentalsSnapshot, PriceHistory`を次のように拡張:

```python
from db.models import CompanyProfile, FundamentalsSnapshot, PriceHistory
```

`fetch_company_profile`関数（58-70行目）を置き換え:

変更前:

```python
def fetch_company_profile(ticker_symbol: str) -> dict:
    """指定銘柄の業種・事業内容をyfinance経由で取得する。"""
    logger.info("company profileリクエスト: ticker=%s", ticker_symbol)
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info
    result = {
        "ticker": ticker_symbol,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "business_summary": info.get("longBusinessSummary"),
    }
    logger.info("company profileレスポンス: ticker=%s data=%s", ticker_symbol, result)
    return result
```

変更後:

```python
_PROFILE_FRESHNESS_DAYS = 30


def _is_stale(updated_at: datetime.datetime | None, max_age_days: int) -> bool:
    if updated_at is None:
        return True
    now = datetime.datetime.now(datetime.timezone.utc)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=datetime.timezone.utc)
    return (now - updated_at).days >= max_age_days


def _fetch_company_profile_from_yfinance(ticker_symbol: str) -> dict:
    """yfinanceから直接業種・事業内容を取得する（DBを経由しない生の取得処理）。"""
    logger.info("company profileリクエスト: ticker=%s", ticker_symbol)
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info
    result = {
        "ticker": ticker_symbol,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "business_summary": info.get("longBusinessSummary"),
    }
    logger.info("company profileレスポンス: ticker=%s data=%s", ticker_symbol, result)
    return result


def fetch_company_profile(ticker_symbol: str, session_factory=SessionLocal) -> dict:
    """指定銘柄の業種・事業内容を取得する。CompanyProfile.profile_updated_atが
    _PROFILE_FRESHNESS_DAYS以内ならDBの値を再利用し、無ければ/古ければyfinanceから
    取得してsector/industry/business_summary/profile_updated_atのみ更新する
    （nameカラムはfetch_japanese_nameが管理するため触れない）。"""
    with session_factory() as session:
        row = session.get(CompanyProfile, ticker_symbol)
        if row is not None and not _is_stale(row.profile_updated_at, _PROFILE_FRESHNESS_DAYS):
            return {
                "ticker": ticker_symbol,
                "sector": row.sector,
                "industry": row.industry,
                "business_summary": row.business_summary,
            }

        result = _fetch_company_profile_from_yfinance(ticker_symbol)
        if row is None:
            row = CompanyProfile(ticker=ticker_symbol)
            session.add(row)
        row.sector = result["sector"]
        row.industry = result["industry"]
        row.business_summary = result["business_summary"]
        row.profile_updated_at = datetime.datetime.now(datetime.timezone.utc)
        session.commit()
        return result
```

`fetch_japanese_name`関数（96-121行目）を置き換え:

変更前:

```python
def fetch_japanese_name(ticker_symbol: str) -> str | None:
    """Yahoo!ファイナンス（日本版）のページタイトルから日本語の銘柄名を取得する。

    yfinance（Yahoo Financeのグローバルデータ）は日本株の名前を英語でしか
    返さないため、日本語名専用にこの関数を使う。
    """
    url = f"https://finance.yahoo.co.jp/quote/{ticker_symbol}"
    logger.info("日本語銘柄名リクエスト: url=%s", url)
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        response.raise_for_status()
    except requests.RequestException:
        logger.warning("日本語銘柄名取得失敗: url=%s", url)
        return None
    logger.info("日本語銘柄名レスポンス: url=%s body=%s", url, response.text)

    match = _YAHOO_JP_TITLE_RE.search(response.text)
    if not match:
        return None

    title = match.group(1)
    if "【" not in title:
        return None

    name = title.split("【", 1)[0].strip()
    return name or None
```

変更後:

```python
def _fetch_japanese_name_from_source(ticker_symbol: str) -> str | None:
    """Yahoo!ファイナンス（日本版）のページタイトルから直接日本語銘柄名を取得する
    （DBを経由しない生の取得処理）。yfinance（Yahoo Financeのグローバルデータ）は
    日本株の名前を英語でしか返さないため、日本語名専用にこの関数を使う。
    """
    url = f"https://finance.yahoo.co.jp/quote/{ticker_symbol}"
    logger.info("日本語銘柄名リクエスト: url=%s", url)
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        response.raise_for_status()
    except requests.RequestException:
        logger.warning("日本語銘柄名取得失敗: url=%s", url)
        return None
    logger.info("日本語銘柄名レスポンス: url=%s body=%s", url, response.text)

    match = _YAHOO_JP_TITLE_RE.search(response.text)
    if not match:
        return None

    title = match.group(1)
    if "【" not in title:
        return None

    name = title.split("【", 1)[0].strip()
    return name or None


def fetch_japanese_name(ticker_symbol: str, session_factory=SessionLocal) -> str | None:
    """指定銘柄の日本語名を取得する。CompanyProfile.name_updated_atが
    _PROFILE_FRESHNESS_DAYS以内ならDBの値を再利用する。取得に失敗した場合は
    DBを更新せずNoneを返す（次回呼び出し時に再試行される）。"""
    with session_factory() as session:
        row = session.get(CompanyProfile, ticker_symbol)
        if (
            row is not None
            and row.name is not None
            and not _is_stale(row.name_updated_at, _PROFILE_FRESHNESS_DAYS)
        ):
            return row.name

        name = _fetch_japanese_name_from_source(ticker_symbol)
        if name is None:
            return None

        if row is None:
            row = CompanyProfile(ticker=ticker_symbol)
            session.add(row)
        row.name = name
        row.name_updated_at = datetime.datetime.now(datetime.timezone.utc)
        session.commit()
        return name
```

- [ ] **Step 4: テストを実行して通ることを確認する**

Run: `uv run pytest tests/test_stock_price_api.py -v -k "company_profile or japanese_name"`
Expected: PASS（全件）

- [ ] **Step 5: Commit**

```bash
git add data_api/stock_price_api.py tests/test_stock_price_api.py
git commit -m "refactor: fetch_company_profile・fetch_japanese_nameをCompanyProfileテーブルのDB read-through方式に変更"
```

---

### Task 5: `fetch_news`のread-through化

**Files:**
- Modify: `ai-stock-investing-tutorial/app/data_api/stock_price_api.py`
- Modify: `ai-stock-investing-tutorial/app/tests/test_stock_price_api.py`

**Interfaces:**
- Consumes: `db.models.TickerNews`（Task 1）
- Produces: `data_api.stock_price_api.fetch_news(ticker_symbol: str, limit: int = 5, session_factory=SessionLocal) -> list[dict]`（戻り値の形は既存と同じ: `[{"title", "publisher", "link"}, ...]`）

- [ ] **Step 1: 失敗するテストを書く**

`test_fetch_news_returns_title_publisher_and_link`・`test_fetch_news_handles_missing_nested_fields`・`test_fetch_news_logs_request_and_response`を置き換え、新規テストを追加:

```python
def test_fetch_news_returns_title_publisher_and_link(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    news = stock_price_api.fetch_news("7203.T", limit=1, session_factory=session_factory)
    assert news == [
        {"title": "Headline 1", "publisher": "Pub", "link": "https://example.com/1"}
    ]


def test_fetch_news_handles_missing_nested_fields(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", MissingNewsFieldsTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    news = stock_price_api.fetch_news("7203.T", limit=1, session_factory=session_factory)
    assert news == [{"title": "Headline only", "publisher": None, "link": None}]


def test_fetch_news_accumulates_across_calls_without_duplicates(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_news("7203.T", limit=5, session_factory=session_factory)
    stock_price_api.fetch_news("7203.T", limit=5, session_factory=session_factory)

    with session_factory() as session:
        assert (
            session.query(stock_price_api.TickerNews).filter_by(ticker="7203.T").count() == 2
        )


def test_fetch_news_deduplicates_articles_without_link(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", MissingNewsFieldsTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_news("7203.T", limit=5, session_factory=session_factory)
    stock_price_api.fetch_news("7203.T", limit=5, session_factory=session_factory)

    with session_factory() as session:
        assert (
            session.query(stock_price_api.TickerNews).filter_by(ticker="7203.T").count() == 1
        )


def test_fetch_news_logs_request_and_response(monkeypatch, caplog, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_news("7203.T", limit=1, session_factory=session_factory)

    assert "newsリクエスト: ticker=7203.T limit=1" in caplog.text
    assert "newsレスポンス: ticker=7203.T" in caplog.text
    assert "Headline 1" in caplog.text
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_stock_price_api.py -v -k "fetch_news"`
Expected: FAIL（`fetch_news()`が`session_factory`引数を受け付けない、`TickerNews`未import）

- [ ] **Step 3: `fetch_news`をread-through化する**

`data_api/stock_price_api.py`の`from db.models import CompanyProfile, FundamentalsSnapshot, PriceHistory`を次のように拡張:

```python
from db.models import CompanyProfile, FundamentalsSnapshot, PriceHistory, TickerNews
```

`fetch_news`関数（73-93行目）を置き換え:

変更前:

```python
def fetch_news(ticker_symbol: str, limit: int = 5) -> list[dict]:
    """指定銘柄に関連する最新ニュースを取得し、表示に必要な項目だけに整形する。"""
    logger.info("newsリクエスト: ticker=%s limit=%s", ticker_symbol, limit)
    ticker = yf.Ticker(ticker_symbol)
    news_items = ticker.news or []
    result = []
    for item in news_items[:limit]:
        # yfinanceのニュースレスポンスはネストしたcontent/provider構造のため、
        # 欠損があっても落ちないよう各階層でNone安全に取り出す
        content = item.get("content") or {}
        provider = content.get("provider") or {}
        link_info = content.get("clickThroughUrl") or content.get("canonicalUrl") or {}
        result.append(
            {
                "title": content.get("title"),
                "publisher": provider.get("displayName"),
                "link": link_info.get("url"),
            }
        )
    logger.info("newsレスポンス: ticker=%s data=%s", ticker_symbol, result)
    return result
```

変更後:

```python
def _fetch_news_from_yfinance(ticker_symbol: str, limit: int) -> list[dict]:
    """yfinanceから直接ニュースを取得し、表示に必要な項目だけに整形する
    （DBを経由しない生の取得処理）。"""
    logger.info("newsリクエスト: ticker=%s limit=%s", ticker_symbol, limit)
    ticker = yf.Ticker(ticker_symbol)
    news_items = ticker.news or []
    result = []
    for item in news_items[:limit]:
        # yfinanceのニュースレスポンスはネストしたcontent/provider構造のため、
        # 欠損があっても落ちないよう各階層でNone安全に取り出す
        content = item.get("content") or {}
        provider = content.get("provider") or {}
        link_info = content.get("clickThroughUrl") or content.get("canonicalUrl") or {}
        result.append(
            {
                "title": content.get("title"),
                "publisher": provider.get("displayName"),
                "link": link_info.get("url"),
            }
        )
    logger.info("newsレスポンス: ticker=%s data=%s", ticker_symbol, result)
    return result


def _insert_new_ticker_news(session, ticker_symbol: str, items: list[dict]) -> None:
    """未知の記事のみTickerNewsへ追記する。linkがある記事は(ticker, link)で、
    linkが無い記事は(ticker, title, publisher)で重複判定する。"""
    existing_links = {
        row.link
        for row in session.query(TickerNews.link)
        .filter_by(ticker=ticker_symbol)
        .filter(TickerNews.link.isnot(None))
        .all()
    }
    existing_no_link = {
        (row.title, row.publisher)
        for row in session.query(TickerNews.title, TickerNews.publisher)
        .filter_by(ticker=ticker_symbol, link=None)
        .all()
    }
    for item in items:
        link = item.get("link")
        if link is not None:
            if link in existing_links:
                continue
            existing_links.add(link)
        else:
            key = (item.get("title"), item.get("publisher"))
            if key in existing_no_link:
                continue
            existing_no_link.add(key)
        session.add(
            TickerNews(
                ticker=ticker_symbol,
                title=item.get("title"),
                publisher=item.get("publisher"),
                link=link,
            )
        )


def fetch_news(ticker_symbol: str, limit: int = 5, session_factory=SessionLocal) -> list[dict]:
    """指定銘柄に関連する最新ニュースを取得する。毎回yfinanceから最新記事を取得して
    未知の記事のみDBへ追記した上で、DBに蓄積された記事から最新limit件を返す
    （複数ユーザーの取得タイミングの違いにより結果的に記事が積み上がる）。"""
    with session_factory() as session:
        fresh_items = _fetch_news_from_yfinance(ticker_symbol, limit)
        _insert_new_ticker_news(session, ticker_symbol, fresh_items)
        session.commit()

        rows = (
            session.query(TickerNews)
            .filter_by(ticker=ticker_symbol)
            .order_by(TickerNews.fetched_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {"title": row.title, "publisher": row.publisher, "link": row.link} for row in rows
        ]
```

- [ ] **Step 4: テストを実行して通ることを確認する**

Run: `uv run pytest tests/test_stock_price_api.py -v -k "fetch_news"`
Expected: PASS（全件）

- [ ] **Step 5: Commit**

```bash
git add data_api/stock_price_api.py tests/test_stock_price_api.py
git commit -m "refactor: fetch_newsをTickerNewsテーブルのDB read-through方式に変更"
```

---

### Task 6: `fetch_universe_fundamentals`・`fetch_universe_price_histories`のDB化・呼び出し側更新・キャッシュTTL見直し

**Files:**
- Modify: `ai-stock-investing-tutorial/app/data_api/stock_price_api.py`
- Modify: `ai-stock-investing-tutorial/app/tests/test_stock_price_api.py`
- Modify: `ai-stock-investing-tutorial/app/app_tabs/screening_tab.py`
- Modify: `ai-stock-investing-tutorial/app/app_tabs/strategy_builder_tab.py`
- Modify: `ai-stock-investing-tutorial/app/app_tabs/shared.py`

**Interfaces:**
- Consumes: `fetch_fundamentals`（Task 3）、`fetch_price_history`（Task 2）
- Produces:
  - `data_api.stock_price_api.fetch_universe_fundamentals(tickers: list[str], session_factory=SessionLocal, fetch_fundamentals=fetch_fundamentals) -> pd.DataFrame`（`cache_dir`引数を廃止）
  - `data_api.stock_price_api.fetch_universe_price_histories(tickers: list[str], period: str, session_factory=SessionLocal, fetch_price_history=fetch_price_history) -> dict[str, pd.Series]`（`cache_dir`引数を廃止）

- [ ] **Step 1: 失敗するテストを書く**

`test_fetch_universe_fundamentals_uses_cache_on_second_call`から`test_fetch_universe_price_histories_skips_empty_history`まで（既存の146〜343行目付近、ユニバース関連テスト一式）を、以下の内容に置き換える:

```python
def test_fetch_universe_fundamentals_calls_fetch_fundamentals_per_ticker():
    call_count = {"n": 0}

    def fake_fetch_fundamentals(ticker_symbol, session_factory=None):
        call_count["n"] += 1
        return {
            "ticker": ticker_symbol,
            "name": ticker_symbol,
            "trailing_pe": 10.0,
            "price_to_book": 1.0,
            "dividend_yield": 0.02,
            "market_cap": 1,
        }

    tickers = ["AAA.T", "BBB.T"]
    df = stock_price_api.fetch_universe_fundamentals(
        tickers, fetch_fundamentals=fake_fetch_fundamentals
    )
    assert call_count["n"] == 2
    assert df["dividend_yield_pct"].tolist() == [0.02, 0.02]


def test_fetch_universe_fundamentals_converts_roe_and_revenue_growth_to_pct():
    def fake_fetch_fundamentals(ticker_symbol, session_factory=None):
        return {
            "ticker": ticker_symbol,
            "name": ticker_symbol,
            "trailing_pe": 10.0,
            "price_to_book": 1.0,
            "dividend_yield": 0.02,
            "market_cap": 1,
            "return_on_equity": 0.155,
            "revenue_growth": 0.082,
        }

    df = stock_price_api.fetch_universe_fundamentals(
        ["AAA.T"], fetch_fundamentals=fake_fetch_fundamentals
    )
    assert df["roe_pct"].tolist() == pytest.approx([15.5])
    assert df["revenue_growth_pct"].tolist() == pytest.approx([8.2])


def test_fetch_universe_fundamentals_handles_missing_roe_and_revenue_growth():
    def fake_fetch_fundamentals(ticker_symbol, session_factory=None):
        return {
            "ticker": ticker_symbol,
            "name": ticker_symbol,
            "trailing_pe": 10.0,
            "price_to_book": 1.0,
            "dividend_yield": 0.02,
            "market_cap": 1,
            "return_on_equity": None,
            "revenue_growth": None,
        }

    df = stock_price_api.fetch_universe_fundamentals(
        ["AAA.T"], fetch_fundamentals=fake_fetch_fundamentals
    )
    assert df["roe_pct"].iloc[0] is None or pd.isna(df["roe_pct"].iloc[0])
    assert df["revenue_growth_pct"].iloc[0] is None or pd.isna(df["revenue_growth_pct"].iloc[0])


def test_fetch_universe_fundamentals_skips_ticker_that_raises_and_keeps_others():
    def fake_fetch_fundamentals(ticker_symbol, session_factory=None):
        if ticker_symbol == "BAD.T":
            raise ValueError("boom")
        return {
            "ticker": ticker_symbol,
            "name": ticker_symbol,
            "trailing_pe": 10.0,
            "price_to_book": 1.0,
            "dividend_yield": 0.02,
            "market_cap": 1,
        }

    tickers = ["AAA.T", "BAD.T", "CCC.T"]
    df = stock_price_api.fetch_universe_fundamentals(
        tickers, fetch_fundamentals=fake_fetch_fundamentals
    )
    assert sorted(df["ticker"].tolist()) == ["AAA.T", "CCC.T"]


def test_fetch_universe_fundamentals_logs_duration(caplog):
    def fake_fetch_fundamentals(ticker_symbol, session_factory=None):
        return {
            "ticker": ticker_symbol,
            "name": ticker_symbol,
            "trailing_pe": 10.0,
            "price_to_book": 1.0,
            "dividend_yield": 0.02,
            "market_cap": 1,
        }

    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_universe_fundamentals(
            ["AAA.T"], fetch_fundamentals=fake_fetch_fundamentals
        )

    assert "ユニバースfundamentals一括取得" in caplog.text
    assert "を開始" in caplog.text
    assert "が完了しました" in caplog.text


def test_fetch_universe_price_histories_calls_fetch_price_history_per_ticker():
    call_count = {"n": 0}
    dates = pd.date_range("2026-01-01", periods=3, freq="D")

    def fake_fetch_price_history(ticker_symbol, period="1mo", session_factory=None):
        call_count["n"] += 1
        return pd.DataFrame({"Close": [10.0, 11.0, 12.0]}, index=dates)

    tickers = ["AAA.T", "BBB.T"]
    result = stock_price_api.fetch_universe_price_histories(
        tickers, "1y", fetch_price_history=fake_fetch_price_history
    )
    assert call_count["n"] == 2
    assert result["AAA.T"].tolist() == [10.0, 11.0, 12.0]


def test_fetch_universe_price_histories_skips_failed_ticker():
    dates = pd.date_range("2026-01-01", periods=2, freq="D")

    def fake_fetch_price_history(ticker_symbol, period="1mo", session_factory=None):
        if ticker_symbol == "BAD.T":
            raise ValueError("boom")
        return pd.DataFrame({"Close": [1.0, 2.0]}, index=dates)

    result = stock_price_api.fetch_universe_price_histories(
        ["AAA.T", "BAD.T"], "1y", fetch_price_history=fake_fetch_price_history
    )
    assert list(result.keys()) == ["AAA.T"]


def test_fetch_universe_price_histories_skips_empty_history():
    def fake_fetch_price_history(ticker_symbol, period="1mo", session_factory=None):
        return pd.DataFrame({"Close": []})

    result = stock_price_api.fetch_universe_price_histories(
        ["AAA.T"], "1y", fetch_price_history=fake_fetch_price_history
    )
    assert result == {}
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_stock_price_api.py -v -k "universe"`
Expected: FAIL（`fetch_universe_fundamentals()`/`fetch_universe_price_histories()`が`tmp_path`を第2位置引数として受け取れずTypeError）

- [ ] **Step 3: `fetch_universe_fundamentals`・`fetch_universe_price_histories`をDB化する**

`data_api/stock_price_api.py`冒頭のimportから、この2関数以外で使われなくなった`import hashlib`・`import json`・`from pathlib import Path`・`from common.cache import read_cache, write_cache`を削除する。

`fetch_universe_fundamentals`関数（129-174行目）を置き換え:

変更前:

```python
def fetch_universe_fundamentals(
    tickers: list[str],
    cache_dir: Path,
    fetch_fundamentals=fetch_fundamentals,
) -> pd.DataFrame:
    """複数銘柄のファンダメンタルズをまとめて取得し、DataFrameとして返す。

    セクター分析などスクリーニング用途で銘柄集合全体を扱うため、
    キャッシュと並行取得によって繰り返し呼び出しのコストを抑える。
    """
    # 銘柄集合ごとに一意なキャッシュキーを作る（順序に依らないようソートしてハッシュ化）
    cache_key = "universe-" + hashlib.sha256(
        "-".join(sorted(tickers)).encode("utf-8")
    ).hexdigest()[:12]
    cached = read_cache(cache_dir, cache_key)
    if cached is not None:
        return pd.DataFrame(json.loads(cached))

    with log_duration(logger, f"ユニバースfundamentals一括取得（{len(tickers)}銘柄）"):
        # 銘柄数が多いと逐次取得は遅いため、複数銘柄を並行してAPI取得する
        results = map_concurrently(tickers, fetch_fundamentals)
        rows = []
        for ticker_symbol in tickers:
            data = results[ticker_symbol]
            # 個別銘柄の取得失敗（例外）は全体を止めず、その銘柄だけスキップする
            if isinstance(data, Exception):
                continue
            rows.append(
                {
                    "ticker": data.get("ticker", ticker_symbol),
                    "name": data.get("name"),
                    "per": data.get("trailing_pe"),
                    "pbr": data.get("price_to_book"),
                    # yfinance's dividendYield is already a percentage number
                    # (e.g. 3.45 means 3.45%), not a fraction to scale up.
                    "dividend_yield_pct": data.get("dividend_yield"),
                    "market_cap": data.get("market_cap"),
                    # returnOnEquity/revenueGrowthは小数（例: 0.155 = 15.5%）で
                    # 返るため、dividend_yieldと異なり100倍してパーセント表示用にする。
                    "roe_pct": _to_pct(data.get("return_on_equity")),
                    "revenue_growth_pct": _to_pct(data.get("revenue_growth")),
                }
            )
        df = pd.DataFrame(rows)
        write_cache(cache_dir, cache_key, df.to_json(orient="records", force_ascii=False))
    return df
```

変更後:

```python
def fetch_universe_fundamentals(
    tickers: list[str],
    session_factory=SessionLocal,
    fetch_fundamentals=fetch_fundamentals,
) -> pd.DataFrame:
    """複数銘柄のファンダメンタルズをまとめて取得し、DataFrameとして返す。

    銘柄ごとの鮮度チェック・DB読み書きはfetch_fundamentals（DB read-through）に
    委譲し、ここでは並行実行（複数銘柄を並行してAPI取得）と結果の整形のみを行う。
    """
    with log_duration(logger, f"ユニバースfundamentals一括取得（{len(tickers)}銘柄）"):
        results = map_concurrently(
            tickers, lambda ticker: fetch_fundamentals(ticker, session_factory=session_factory)
        )
        rows = []
        for ticker_symbol in tickers:
            data = results[ticker_symbol]
            # 個別銘柄の取得失敗（例外）は全体を止めず、その銘柄だけスキップする
            if isinstance(data, Exception):
                continue
            rows.append(
                {
                    "ticker": data.get("ticker", ticker_symbol),
                    "name": data.get("name"),
                    "per": data.get("trailing_pe"),
                    "pbr": data.get("price_to_book"),
                    # yfinance's dividendYield is already a percentage number
                    # (e.g. 3.45 means 3.45%), not a fraction to scale up.
                    "dividend_yield_pct": data.get("dividend_yield"),
                    "market_cap": data.get("market_cap"),
                    # returnOnEquity/revenueGrowthは小数（例: 0.155 = 15.5%）で
                    # 返るため、dividend_yieldと異なり100倍してパーセント表示用にする。
                    "roe_pct": _to_pct(data.get("return_on_equity")),
                    "revenue_growth_pct": _to_pct(data.get("revenue_growth")),
                }
            )
        return pd.DataFrame(rows)
```

`fetch_universe_price_histories`関数（177-227行目）を置き換え:

変更前:

```python
def fetch_universe_price_histories(
    tickers: list[str],
    period: str,
    cache_dir: Path,
    fetch_price_history=fetch_price_history,
) -> dict[str, pd.Series]:
    """複数銘柄の終値時系列をまとめて取得し、{ticker: pd.Series} として返す。

    strategy_builderの簡易バックテスト・銘柄選定実行画面で、絞り込み後の
    銘柄群の株価をまとめて取得する用途に使う。取得失敗・空データの銘柄は
    結果から除外する。
    """
    cache_key = "universe-prices-" + hashlib.sha256(
        f"{period}-{'-'.join(sorted(tickers))}".encode("utf-8")
    ).hexdigest()[:12]
    cached = read_cache(cache_dir, cache_key)
    if cached is not None:
        payload = json.loads(cached)
        return {
            ticker: pd.Series(
                data["values"], index=pd.to_datetime(data["dates"]), name="Close"
            )
            for ticker, data in payload.items()
        }

    with log_duration(logger, f"ユニバース株価一括取得（{len(tickers)}銘柄, period={period}）"):
        results = map_concurrently(
            tickers, lambda ticker: fetch_price_history(ticker, period=period)
        )
        prices_by_ticker: dict[str, pd.Series] = {}
        for ticker in tickers:
            history = results[ticker]
            if isinstance(history, Exception) or history is None or history.empty:
                continue
            prices_by_ticker[ticker] = history["Close"]

        write_cache(
            cache_dir,
            cache_key,
            json.dumps(
                {
                    ticker: {
                        "dates": [d.isoformat() for d in series.index],
                        "values": [float(v) for v in series],
                    }
                    for ticker, series in prices_by_ticker.items()
                }
            ),
        )
    return prices_by_ticker
```

変更後:

```python
def fetch_universe_price_histories(
    tickers: list[str],
    period: str,
    session_factory=SessionLocal,
    fetch_price_history=fetch_price_history,
) -> dict[str, pd.Series]:
    """複数銘柄の終値時系列をまとめて取得し、{ticker: pd.Series} として返す。

    strategy_builderの簡易バックテスト・銘柄選定実行画面で、絞り込み後の
    銘柄群の株価をまとめて取得する用途に使う。銘柄ごとの鮮度チェック・DB読み書きは
    fetch_price_history（DB read-through）に委譲し、ここでは並行実行と結果の整形
    のみを行う。取得失敗・空データの銘柄は結果から除外する。
    """
    with log_duration(logger, f"ユニバース株価一括取得（{len(tickers)}銘柄, period={period}）"):
        results = map_concurrently(
            tickers,
            lambda ticker: fetch_price_history(
                ticker, period=period, session_factory=session_factory
            ),
        )
        prices_by_ticker: dict[str, pd.Series] = {}
        for ticker in tickers:
            history = results[ticker]
            if isinstance(history, Exception) or history is None or history.empty:
                continue
            prices_by_ticker[ticker] = history["Close"]
        return prices_by_ticker
```

- [ ] **Step 4: 呼び出し側を更新する**

`ai-stock-investing-tutorial/app/app_tabs/screening_tab.py:20`、変更前:

```python
from app_tabs.shared import CACHE_DIR, handle_table_selection
```

変更後:

```python
from app_tabs.shared import handle_table_selection
```

`screening_tab.py:64`、変更前: `universe_df = fetch_universe_fundamentals(UNIVERSE, CACHE_DIR)`
変更後: `universe_df = fetch_universe_fundamentals(UNIVERSE)`

`ai-stock-investing-tutorial/app/app_tabs/strategy_builder_tab.py:31-37`、変更前:

```python
from app_tabs.shared import (
    CACHE_DIR,
    DEFAULT_USER_ID,
    handle_table_selection,
    render_mermaid,
    run_or_load_sector_rotation,
)
```

変更後:

```python
from app_tabs.shared import (
    DEFAULT_USER_ID,
    handle_table_selection,
    render_mermaid,
    run_or_load_sector_rotation,
)
```

`strategy_builder_tab.py:238`、変更前: `universe_df = fetch_universe_fundamentals(UNIVERSE, CACHE_DIR)`
変更後: `universe_df = fetch_universe_fundamentals(UNIVERSE)`

`strategy_builder_tab.py:250-252`、変更前:

```python
                prices_by_ticker = fetch_universe_price_histories(
                    matched_tickers, period, CACHE_DIR
                )
```

変更後:

```python
                prices_by_ticker = fetch_universe_price_histories(matched_tickers, period)
```

`strategy_builder_tab.py:340`、変更前: `universe_df = fetch_universe_fundamentals(UNIVERSE, CACHE_DIR)`
変更後: `universe_df = fetch_universe_fundamentals(UNIVERSE)`

`strategy_builder_tab.py:352-354`、変更前:

```python
            price_by_ticker = fetch_universe_price_histories(
                matched_df["ticker"].tolist(), "1y", CACHE_DIR
            )
```

変更後:

```python
            price_by_ticker = fetch_universe_price_histories(matched_df["ticker"].tolist(), "1y")
```

- [ ] **Step 5: `app_tabs/shared.py`のキャッシュラッパーTTLを見直す**

`ai-stock-investing-tutorial/app/app_tabs/shared.py`、変更前:

```python
@st.cache_data(ttl=60 * 60 * 24)
def cached_fetch_japanese_name(ticker: str) -> str | None:
    """銘柄名はほぼ変化しないため、1日単位でキャッシュして外部API呼び出しを抑える。"""
    return fetch_japanese_name(ticker)


@st.cache_data(ttl=60 * 30)
def cached_fetch_price_history(ticker: str, period: str):
    """株価履歴は頻繁な再取得が不要なため、30分キャッシュして表示速度と負荷を両立する。"""
    return fetch_price_history(ticker, period=period)


@st.cache_data(ttl=60 * 30)
def cached_analyze_fundamentals(ticker: str) -> dict:
    """ファンダメンタルズ分析結果を30分キャッシュし、同一銘柄への重複計算を避ける。"""
    return analyze_fundamentals(ticker)


@st.cache_data(ttl=60 * 30)
def cached_fetch_news(ticker: str) -> list[dict]:
    """ニュース取得結果を30分キャッシュし、同一銘柄への重複リクエストを避ける。"""
    return fetch_news(ticker)
```

変更後:

```python
@st.cache_data(ttl=60)
def cached_fetch_japanese_name(ticker: str) -> str | None:
    """銘柄名はDB（CompanyProfile）で全ユーザー共有・長期キャッシュされているため、
    ここでは同一セッション内の連続rerunでDB問い合わせを繰り返さない薄い前段
    キャッシュとして短時間だけ保持する。"""
    return fetch_japanese_name(ticker)


@st.cache_data(ttl=60)
def cached_fetch_price_history(ticker: str, period: str):
    """株価履歴はDB（PriceHistory）で全ユーザー共有・長期キャッシュされているため、
    ここでは同一セッション内の連続rerunでDB問い合わせを繰り返さない薄い前段
    キャッシュとして短時間だけ保持する。"""
    return fetch_price_history(ticker, period=period)


@st.cache_data(ttl=60)
def cached_analyze_fundamentals(ticker: str) -> dict:
    """ファンダメンタルズはDB（FundamentalsSnapshot）で全ユーザー共有・長期
    キャッシュされているため、ここでは同一セッション内の連続rerunでDB問い合わせを
    繰り返さない薄い前段キャッシュとして短時間だけ保持する。"""
    return analyze_fundamentals(ticker)


@st.cache_data(ttl=60)
def cached_fetch_news(ticker: str) -> list[dict]:
    """ニュースはDB（TickerNews）に蓄積されるため、ここでは同一セッション内の
    連続rerunでDB問い合わせを繰り返さない薄い前段キャッシュとして短時間だけ
    保持する。"""
    return fetch_news(ticker)
```

- [ ] **Step 6: テストを実行して通ることを確認する**

Run: `uv run pytest tests/test_stock_price_api.py -v`
Expected: PASS（全件）

- [ ] **Step 7: 全体テストスイートを実行して回帰が無いことを確認する**

Run: `uv run pytest -v`
Expected: PASS（全件。`screening_tab.py`/`strategy_builder_tab.py`はユニットテスト対象外のため新規に壊れるテストは無いはず）

- [ ] **Step 8: Commit**

```bash
git add data_api/stock_price_api.py tests/test_stock_price_api.py app_tabs/screening_tab.py app_tabs/strategy_builder_tab.py app_tabs/shared.py
git commit -m "refactor: fetch_universe_fundamentals/fetch_universe_price_historiesのファイルキャッシュを廃止しDB read-through方式に統一"
```

---

### Task 7: 全体テスト・手動動作確認

このタスクは新規コードを書かず、フェーズ2全体が実際のアプリで動くことを確認する。

**Files:** なし（確認のみ）

- [ ] **Step 1: 全体テストスイートを実行する**

Run: `uv run pytest -v`（`ai-stock-investing-tutorial/app`ディレクトリで）
Expected: 全件PASS

- [ ] **Step 2: アプリを起動し、手動で動作確認する**

```bash
uv run python -m streamlit run app.py
```

ブラウザで以下を確認する:
- **ポートフォリオ**タブ: 保有銘柄の「詳細」ボタンから銘柄詳細ダイアログを開き、株価チャート・ファンダメンタルズ・ニュースが表示される（初回はyfinance/スクレイピングへのリクエストが発生するが、エラーにならず表示される）
- 同じ銘柄をもう一度開く、またはページをリロードして再度開いた際に、レスポンスが速くなっている（DBキャッシュが効いている）ことを確認する
- **スクリーニング**タブ: 条件を入力して絞り込みを実行し、結果テーブルが表示される（`fetch_universe_fundamentals`のDB化後の動作確認）
- **AI戦略ビルダー**タブ: 「④ 最新データで銘柄選定を実行」を実行し、銘柄選定結果が表示される（`fetch_universe_price_histories`のDB化後の動作確認）
- ターミナルのログにエラーが出ていないこと（特に「database is locked」のようなSQLite関連エラーが出ていないこと）

- [ ] **Step 3: DBに市場データが蓄積されていることを確認する**

```bash
uv run python -c "
from sqlalchemy.orm import sessionmaker
from db.engine import engine
from db.models import PriceHistory, FundamentalsSnapshot, CompanyProfile, TickerNews

Session = sessionmaker(bind=engine)
with Session() as s:
    print('price_history rows:', s.query(PriceHistory).count())
    print('fundamentals_snapshots rows:', s.query(FundamentalsSnapshot).count())
    print('company_profiles rows:', s.query(CompanyProfile).count())
    print('ticker_news rows:', s.query(TickerNews).count())
"
```

Expected: 手動確認で触った銘柄の分だけ各テーブルに行が入っている（0件のテーブルがあれば、そのテーブルに対応する機能を上記Step 2で実際に触っていないだけの可能性が高いので、該当機能を一度実行してから再確認する）
