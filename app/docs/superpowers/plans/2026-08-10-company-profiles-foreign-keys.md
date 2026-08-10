# company_profiles 外部キー制約 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `price_history`/`fundamentals_snapshots`/`ticker_news` の `ticker` 列に、`company_profiles.ticker` への実際のSQLite外部キー制約を追加し、既存DB・既存の書き込みコードの双方でも整合性を保ったまま機能させる。

**Architecture:** (1) SQLiteはデフォルトでFK制約を強制しないため`db/engine.py`の接続時に`PRAGMA foreign_keys=ON`を有効化する。(2) `db/models.py`の3テーブルの`ticker`列に`ForeignKey("company_profiles.ticker")`を追加する。(3) 既存DB（本制約導入前に作られたテーブル）はSQLiteがALTER TABLEでのFK制約後付けに対応していないため、`init_db()`起動時に「孤児tickerのcompany_profilesへのバックフィル→FK未宣言テーブルのみ作り直し」という軽量マイグレーションを自動実行する。(4) 書き込み側（`data_api/stock_price_api.py`の各fetch/save関数）は、書き込み前に対象tickerの`company_profiles`行が無ければ空のスタブ行を自動作成し、既存の呼び出し順序（例: `stock_detail/detail.py`が`fetch_price_history`を`fetch_company_profile`より先に呼ぶ）を壊さないようにする。

**Tech Stack:** Python, SQLAlchemy 2.x ORM, SQLite, pytest

## Global Constraints

- 既存の軽量マイグレーション方針を踏襲する（Alembic等は使わない、`db/engine.py`内に素朴な関数を追加する）。
- 既存のテストスタイル（`tmp_path` + `create_db_engine` + `init_db` + `sessionmaker`、`monkeypatch`でyfinance差し替え）に合わせる。
- 本番DB（`app/data/app.db`）は今回のタスクでは直接操作しない。次回アプリ起動時に`init_db()`が自動的にマイグレーションする（実施前にバックアップを推奨する旨をユーザーに案内するのみ）。
- コメントは「なぜ」が非自明な箇所にのみ日本語で1行程度、既存コードのコメントスタイルに合わせる。

---

## File Structure

- Modify: `db/engine.py` — SQLite FKのPRAGMA有効化、既存DB向けマイグレーション関数群、`init_db()`からの呼び出し追加
- Modify: `db/models.py` — 3テーブルの`ticker`列に`ForeignKey`追加
- Modify: `data_api/stock_price_api.py` — `_ensure_company_profile_stub`ヘルパー追加、書き込み関数への組み込み
- Modify: `tests/test_db_engine.py` — FK有効化・マイグレーションのテスト追加、既存の直接INSERTテストの修正
- Modify: `tests/test_stock_price_api.py` — スタブ自動作成のテスト追加、既存の直接INSERTテストの修正
- Modify: `docs/app-design.md` — ER図の関連線を実線化、説明文をFK実装の実態に合わせて更新

---

### Task 1: SQLiteのFK制約を接続時に有効化する

**Files:**
- Modify: `db/engine.py`
- Test: `tests/test_db_engine.py`

**Interfaces:**
- Produces: `create_db_engine()`が返す`Engine`は、以後すべての接続で`PRAGMA foreign_keys=ON`が有効な状態になる。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_db_engine.py` の末尾に追加:

```python
def test_create_db_engine_enables_sqlite_foreign_keys(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with engine.connect() as connection:
        value = connection.execute(text("PRAGMA foreign_keys")).scalar()
    assert value == 1
```

ファイル冒頭のimportに `from sqlalchemy import text` を追加（既存の`test_init_db_adds_missing_user_name_columns_to_existing_table`内でローカルimportされているものをトップレベルに揃えてよいが、最小変更のため今回はテスト関数内で `from sqlalchemy import text` する）:

```python
def test_create_db_engine_enables_sqlite_foreign_keys(tmp_path):
    from sqlalchemy import text

    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with engine.connect() as connection:
        value = connection.execute(text("PRAGMA foreign_keys")).scalar()
    assert value == 1
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd app && python -m pytest tests/test_db_engine.py::test_create_db_engine_enables_sqlite_foreign_keys -v`
Expected: FAIL（`value == 0`、PRAGMAが未設定のためデフォルトのOFF）

- [ ] **Step 3: `db/engine.py` を修正する**

`db/engine.py` の import行を修正:

```python
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from db.models import Base
```

`create_db_engine`の直前に関数を追加し、`create_db_engine`本体を修正:

```python
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
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `cd app && python -m pytest tests/test_db_engine.py::test_create_db_engine_enables_sqlite_foreign_keys -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add app/db/engine.py app/tests/test_db_engine.py
git commit -m "feat: enable SQLite foreign key enforcement on every connection"
```

---

### Task 2: モデルにFK制約を追加する

**Files:**
- Modify: `db/models.py`
- Test: `tests/test_db_engine.py`

**Interfaces:**
- Consumes: Task 1で有効化された`PRAGMA foreign_keys=ON`
- Produces: `PriceHistory.ticker`/`FundamentalsSnapshot.ticker`/`TickerNews.ticker`はいずれも`company_profiles.ticker`へのFK制約を持つ（新規作成テーブルのみ。既存テーブルへの反映はTask 3）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_db_engine.py` の末尾に追加:

```python
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
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd app && python -m pytest tests/test_db_engine.py -k foreign_key_enforced -v`
Expected: FAIL（3件とも、FK制約が無いためIntegrityErrorが発生せず`assert False`に到達する）

- [ ] **Step 3: `db/models.py` を修正する**

`PriceHistory`クラスの`ticker`列:

```python
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
```

`FundamentalsSnapshot`クラスの`ticker`列:

```python
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
```

`TickerNews`クラスの`ticker`列:

```python
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
```

（`CompanyProfile`クラス自体・`Holding.ticker`は変更しない。`holdings`はユーザー自由入力の保有銘柄であり、銘柄マスタへのFKは意図的に張らない。）

- [ ] **Step 4: テストが通ることを確認する**

Run: `cd app && python -m pytest tests/test_db_engine.py -k foreign_key_enforced -v`
Expected: PASS（3件）

- [ ] **Step 5: コミット**

```bash
git add app/db/models.py app/tests/test_db_engine.py
git commit -m "feat: add foreign key from market-data tables to company_profiles.ticker"
```

---

### Task 3: 既存DB向けの軽量マイグレーション（バックフィル＋テーブル再作成）

**Files:**
- Modify: `db/engine.py`
- Test: `tests/test_db_engine.py`

**Interfaces:**
- Consumes: Task 1の`_enable_sqlite_foreign_keys`、Task 2でFK付きになった`Base.metadata.tables["price_history"|"fundamentals_snapshots"|"ticker_news"]`
- Produces: `init_db(engine)`は、FK制約導入前に作られた既存テーブルに対しても、呼び出し後は「孤児tickerがcompany_profilesにスタブ補完済み」かつ「3テーブルすべてにFK制約が実効化済み」の状態にする。新規DBに対しては何もしない（`create_all`が最初からFK付きで作るため）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_db_engine.py` の末尾に追加:

```python
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
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd app && python -m pytest tests/test_db_engine.py -k "migrates_legacy or migration_is_idempotent" -v`
Expected: FAIL（`test_init_db_migrates_legacy_price_history_table_to_add_foreign_key`は`profile is not None`または末尾のIntegrityError期待で失敗する。`_idempotent`の方はTask3実装前でも通る可能性があるが、Task3実装後も壊れないことの回帰テストとして残す）

- [ ] **Step 3: `db/engine.py` にマイグレーション関数を追加する**

`init_db`関数の直後（`_add_column_if_missing`の前）に追加:

```python
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
```

`init_db`関数を修正:

```python
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
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `cd app && python -m pytest tests/test_db_engine.py -v`
Expected: PASS（全件。Task1・2で追加した分も含めて回帰が無いことを確認する）

- [ ] **Step 5: コミット**

```bash
git add app/db/engine.py app/tests/test_db_engine.py
git commit -m "feat: migrate legacy market-data tables to enforce company_profiles foreign key"
```

---

### Task 4: 既存テストの修正（FK制約により壊れるもの）

Task 2・3の時点で、以下の既存テストは「`company_profiles`行を作らずに`price_history`/`fundamentals_snapshots`へ直接INSERTする」ため、`init_db`済みDBに対して実行するとFK違反で失敗する。各テストに対象tickerの`CompanyProfile`行を追加する。

**Files:**
- Modify: `tests/test_db_engine.py`
- Modify: `tests/test_stock_price_api.py`

- [ ] **Step 1: `tests/test_db_engine.py` の `test_price_history_unique_constraint_on_ticker_and_date` を修正**

修正前:

```python
def test_price_history_unique_constraint_on_ticker_and_date(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(
            PriceHistory(ticker="A", date="2026-01-01", open=1, high=1, low=1, close=1, volume=1)
        )
        session.commit()
```

修正後（`CompanyProfile(ticker="A")`を先に追加）:

```python
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
```

- [ ] **Step 2: `tests/test_db_engine.py` の `test_fundamentals_snapshot_unique_constraint_on_ticker_and_date` を修正**

修正前:

```python
def test_fundamentals_snapshot_unique_constraint_on_ticker_and_date(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(FundamentalsSnapshot(ticker="A", snapshot_date="2026-01-01"))
        session.commit()
```

修正後:

```python
def test_fundamentals_snapshot_unique_constraint_on_ticker_and_date(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(CompanyProfile(ticker="A"))
        session.add(FundamentalsSnapshot(ticker="A", snapshot_date="2026-01-01"))
        session.commit()
```

- [ ] **Step 3: `tests/test_stock_price_api.py` の `test_fetch_price_history_refetches_when_stale` を修正**

修正前:

```python
    old_date = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
    with session_factory() as session:
        session.add(
            stock_price_api.PriceHistory(
                ticker="7203.T", date=old_date, open=1, high=1, low=1, close=1, volume=1
            )
        )
        session.commit()
```

修正後:

```python
    old_date = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
    with session_factory() as session:
        session.add(stock_price_api.CompanyProfile(ticker="7203.T"))
        session.add(
            stock_price_api.PriceHistory(
                ticker="7203.T", date=old_date, open=1, high=1, low=1, close=1, volume=1
            )
        )
        session.commit()
```

- [ ] **Step 4: `tests/test_stock_price_api.py` の `test_load_price_history_for_ticker_returns_rows_sorted_by_date` を修正**

修正前:

```python
    with session_factory() as session:
        session.add(
            stock_price_api.PriceHistory(
                ticker="7203.T", date="2026-01-02", open=2, high=2, low=2, close=2, volume=2
            )
        )
        session.add(
            stock_price_api.PriceHistory(
                ticker="7203.T", date="2026-01-01", open=1, high=1, low=1, close=1, volume=1
            )
        )
        session.commit()
```

修正後:

```python
    with session_factory() as session:
        session.add(stock_price_api.CompanyProfile(ticker="7203.T"))
        session.add(
            stock_price_api.PriceHistory(
                ticker="7203.T", date="2026-01-02", open=2, high=2, low=2, close=2, volume=2
            )
        )
        session.add(
            stock_price_api.PriceHistory(
                ticker="7203.T", date="2026-01-01", open=1, high=1, low=1, close=1, volume=1
            )
        )
        session.commit()
```

- [ ] **Step 5: `tests/test_stock_price_api.py` の `test_load_fundamentals_snapshots_for_ticker_returns_all_fields` を修正**

修正前:

```python
    with session_factory() as session:
        session.add(
            stock_price_api.FundamentalsSnapshot(
                ticker="7203.T", snapshot_date="2026-01-01", trailing_pe=12.3, market_cap=1000
            )
        )
        session.commit()
```

修正後:

```python
    with session_factory() as session:
        session.add(stock_price_api.CompanyProfile(ticker="7203.T"))
        session.add(
            stock_price_api.FundamentalsSnapshot(
                ticker="7203.T", snapshot_date="2026-01-01", trailing_pe=12.3, market_cap=1000
            )
        )
        session.commit()
```

- [ ] **Step 6: 修正した5件のテストが通ることを確認する**

Run: `cd app && python -m pytest tests/test_db_engine.py tests/test_stock_price_api.py -v`
Expected: 現時点ではまだ `data_api/stock_price_api.py` 側の書き込み関数を直接呼ぶテスト（`save_price_history_for_ticker`等）が新規にFK違反で落ちる可能性がある。この5件について個別確認する場合は `-k "unique_constraint or refetches_when_stale or returns_rows_sorted_by_date or returns_all_fields"` で絞り込み、PASSすることを確認する（他の失敗はTask5で解消する）。

- [ ] **Step 7: コミット**

```bash
git add app/tests/test_db_engine.py app/tests/test_stock_price_api.py
git commit -m "test: add company_profiles rows to tests that insert child rows directly"
```

---

### Task 5: 書き込み関数でcompany_profilesスタブ行を自動作成する

**Files:**
- Modify: `data_api/stock_price_api.py`
- Test: `tests/test_stock_price_api.py`

**Interfaces:**
- Produces: `_ensure_company_profile_stub(session, ticker_symbol: str) -> None` — 指定tickerの`CompanyProfile`行が無ければ、ticker列のみのスタブ行を`session`へ追加する（呼び出し側でcommitする）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_stock_price_api.py` の末尾に追加:

```python
def test_fetch_price_history_creates_company_profile_stub_for_new_ticker(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_price_history("7203.T", session_factory=session_factory)

    with session_factory() as session:
        assert session.get(stock_price_api.CompanyProfile, "7203.T") is not None


def test_fetch_fundamentals_creates_company_profile_stub_for_new_ticker(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_fundamentals("7203.T", session_factory=session_factory)

    with session_factory() as session:
        assert session.get(stock_price_api.CompanyProfile, "7203.T") is not None


def test_fetch_news_creates_company_profile_stub_for_new_ticker(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_news("7203.T", limit=1, session_factory=session_factory)

    with session_factory() as session:
        assert session.get(stock_price_api.CompanyProfile, "7203.T") is not None


def test_fetch_price_history_before_fetch_company_profile_does_not_violate_foreign_key(
    monkeypatch, tmp_path
):
    """stock_detail.generate_stock_detailはfetch_price_historyをfetch_company_profileより
    先に呼ぶため、その呼び出し順序でもFK違反にならないことを確認する。"""
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.fetch_price_history("7203.T", session_factory=session_factory)
    profile = stock_price_api.fetch_company_profile("7203.T", session_factory=session_factory)
    assert profile["sector"] == "Consumer Cyclical"


def test_save_price_history_for_ticker_creates_company_profile_stub_for_new_ticker(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.save_price_history_for_ticker(
        "9999.T",
        [
            {
                "date": "2026-01-01",
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 1.0,
            }
        ],
        session_factory=session_factory,
    )

    with session_factory() as session:
        assert session.get(stock_price_api.CompanyProfile, "9999.T") is not None


def test_save_fundamentals_snapshots_for_ticker_creates_company_profile_stub_for_new_ticker(
    tmp_path,
):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.save_fundamentals_snapshots_for_ticker(
        "9999.T",
        [{"snapshot_date": "2026-01-01", "trailing_pe": 10.0}],
        session_factory=session_factory,
    )

    with session_factory() as session:
        assert session.get(stock_price_api.CompanyProfile, "9999.T") is not None
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd app && python -m pytest tests/test_stock_price_api.py -k "creates_company_profile_stub or before_fetch_company_profile" -v`
Expected: FAIL（`IntegrityError`がテスト内部で送出され、pytestがエラーとして報告する）

- [ ] **Step 3: `data_api/stock_price_api.py` を修正する**

`_period_to_start_date`関数の直後、`_fetch_price_history_from_yfinance`の前にヘルパーを追加:

```python
def _ensure_company_profile_stub(session, ticker_symbol: str) -> None:
    """price_history等への書き込み前に、company_profilesへ参照先スタブ行が無ければ
    作成する（tickerにFK制約を張っているため、先に親行が無いと書き込みが失敗する）。
    stock_detail/detail.pyのようにfetch_price_historyをfetch_company_profileより
    先に呼ぶ既存の呼び出し順序でも壊れないようにするための仕組み。"""
    if session.get(CompanyProfile, ticker_symbol) is None:
        session.add(CompanyProfile(ticker=ticker_symbol))
```

`_upsert_price_history`関数を修正（`if history.empty: return`の直後に追加）:

```python
def _upsert_price_history(session, ticker_symbol: str, history: pd.DataFrame) -> None:
    """historyの各日付をPriceHistoryへ追記する。既にDBにある日付は上書きしない
    （時系列を蓄積する方針のため）。"""
    if history.empty:
        return
    _ensure_company_profile_stub(session, ticker_symbol)
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
```

`fetch_fundamentals`関数を修正（`result = _fetch_fundamentals_from_yfinance(...)`の直後に追加）:

```python
        result = _fetch_fundamentals_from_yfinance(ticker_symbol)
        _ensure_company_profile_stub(session, ticker_symbol)
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

`_insert_new_ticker_news`関数を修正（先頭に早期リターンとスタブ作成を追加）:

```python
def _insert_new_ticker_news(session, ticker_symbol: str, items: list[dict]) -> None:
    """未知の記事のみTickerNewsへ追記する。linkがある記事は(ticker, link)で、
    linkが無い記事は(ticker, title, publisher)で重複判定する。"""
    if not items:
        return
    _ensure_company_profile_stub(session, ticker_symbol)
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
```

`save_price_history_for_ticker`関数を修正:

```python
def save_price_history_for_ticker(
    ticker: str, rows: list[dict], session_factory=SessionLocal
) -> None:
    """指定銘柄のPriceHistoryを全置換する（管理者向け）。既存行を全削除し、
    渡されたrowsを再挿入する（portfolio_management/storage.pyのsave_holdingsと
    同じ全置換パターン）。"""
    with session_factory() as session:
        session.query(PriceHistory).filter_by(ticker=ticker).delete()
        if rows:
            _ensure_company_profile_stub(session, ticker)
        for row in rows:
            session.add(
                PriceHistory(
                    ticker=ticker,
                    date=row["date"],
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                )
            )
        session.commit()
```

`save_fundamentals_snapshots_for_ticker`関数を修正:

```python
def save_fundamentals_snapshots_for_ticker(
    ticker: str, rows: list[dict], session_factory=SessionLocal
) -> None:
    """指定銘柄のFundamentalsSnapshotを全置換する（管理者向け）。既存行を全削除し、
    渡されたrowsを再挿入する。"""
    with session_factory() as session:
        session.query(FundamentalsSnapshot).filter_by(ticker=ticker).delete()
        if rows:
            _ensure_company_profile_stub(session, ticker)
        for row in rows:
            session.add(
                FundamentalsSnapshot(
                    ticker=ticker,
                    snapshot_date=row["snapshot_date"],
                    name=row.get("name"),
                    trailing_pe=row.get("trailing_pe"),
                    price_to_book=row.get("price_to_book"),
                    dividend_yield=row.get("dividend_yield"),
                    market_cap=row.get("market_cap"),
                    return_on_equity=row.get("return_on_equity"),
                    revenue_growth=row.get("revenue_growth"),
                )
            )
        session.commit()
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `cd app && python -m pytest tests/test_stock_price_api.py -v`
Expected: PASS（全件）

- [ ] **Step 5: コミット**

```bash
git add app/data_api/stock_price_api.py app/tests/test_stock_price_api.py
git commit -m "feat: auto-create company_profiles stub rows before writing dependent market data"
```

---

### Task 6: ドキュメント更新（app-design.md）

**Files:**
- Modify: `docs/app-design.md`

- [ ] **Step 1: ER図の関連線を点線から実線に変更する**

現在の該当箇所:

```
    company_profiles ||..o{ price_history : "ticker"
    company_profiles ||..o{ fundamentals_snapshots : "ticker"
    company_profiles ||..o{ ticker_news : "ticker"
```

修正後:

```
    company_profiles ||--o{ price_history : "ticker"
    company_profiles ||--o{ fundamentals_snapshots : "ticker"
    company_profiles ||--o{ ticker_news : "ticker"
```

- [ ] **Step 2: ER図直後の説明文を実装の実態に合わせて更新する**

現在の該当パラグラフ:

```
`price_history`・`fundamentals_snapshots`・`company_profiles`・`ticker_news` の4テーブルは `ticker`（銘柄コード文字列）をキーに参照される。上記ER図の点線（非識別関連）は `company_profiles.ticker` を基準とした論理的な対応関係を示すものであり、実際のDBスキーマ上は銘柄マスタテーブルが存在せず、`holdings.ticker` を含めどのテーブル間にも外部キー制約はない（すべて文字列一致でのみ対応付く）。
```

修正後:

```
`price_history`・`fundamentals_snapshots`・`company_profiles`・`ticker_news` の4テーブルは `ticker`（銘柄コード文字列）をキーに参照される。`company_profiles` を銘柄マスタとして、`price_history`/`fundamentals_snapshots`/`ticker_news` の `ticker` 列には `company_profiles.ticker` への外部キー制約を設定しており（`db/engine.py` で `PRAGMA foreign_keys=ON` を有効化して実効化）、上記ER図の実線はこれを表す。書き込み側（`data_api/stock_price_api.py::_ensure_company_profile_stub`）は、対象tickerの `company_profiles` 行が無ければ書き込み前に空のスタブ行（ticker列のみ）を自動作成するため、`stock_detail/detail.py` のように `fetch_price_history` を `fetch_company_profile` より先に呼ぶ既存の呼び出し順序でも破綻しない。本制約導入前に作られた既存DBに対しては、`db/engine.py::init_db()` が起動時に (1) 孤児ticker（子テーブルにはあるが `company_profiles` に無いticker）をスタブ補完し、(2) FK制約が未宣言のテーブルのみ作り直す、という軽量マイグレーションを自動実行する（SQLiteはALTER TABLEでのFK制約後付けに対応していないため）。なお `holdings.ticker` はユーザーの保有銘柄自由入力であり、`company_profiles` へのFKは意図的に張っていない（保有銘柄と銘柄マスタは独立管理）。
```

- [ ] **Step 3: 変更をコミット**

```bash
git add app/docs/app-design.md
git commit -m "docs: describe the company_profiles foreign key and its migration"
```

---

### Task 7: 全体テストとユーザーへの案内

**Files:** なし（検証のみ）

- [ ] **Step 1: 全テストを実行する**

Run: `cd app && python -m pytest -v`
Expected: PASS（全件。既存の他モジュールのテストに影響が無いことを確認する）

- [ ] **Step 2: 本番DBへの適用はユーザーに委ねる**

`app/data/app.db` は今回のタスクでは直接操作しない。次回アプリ起動（`streamlit run app.py` 等、内部で `init_db()` が呼ばれる経路）で自動的にマイグレーションされる。ユーザーには「初回起動前に `app/data/app.db` のバックアップを取ることを推奨する」旨を伝える（既に `app/data/app.db.backup-before-admin-phasec` という先例がある）。
