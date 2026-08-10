# company_profiles を銘柄ユニバースの単一情報源にする Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `screening/universe.py`（`UNIVERSE`/`UNIVERSE_NAMES`）と `screening/sectors.py`（`SECTOR_MAP`）を廃止し、`company_profiles` テーブル（+新設の`sector_jp`列）をスクリーニング/ランキング/戦略ビルダー/セクターローテーションが参照する銘柄一覧・日本語名・東証17業種区分の単一の情報源にする。

**Architecture:** `company_profiles` に `sector_jp`（東証17業種区分、`sector`/`industry`とは別軸）列を追加し、現行の228銘柄分のUNIVERSE_NAMES/SECTOR_MAPを静的CSV（`app/db/seed_company_profiles.csv`）に変換して、`init_db()` が新規DB・既存DBの両方に対して不足分のみ補完する形で投入する。以降、`data_api/stock_price_api.py::load_all_company_profiles()` を「アプリが分析対象とする銘柄一覧」の単一の取得口とし、4つのタブファイルと`ticker_names.py`をこれ経由に置き換える。

**Tech Stack:** Python, SQLAlchemy 2.x ORM, SQLite, Streamlit, pytest, 標準ライブラリ`csv`

## Global Constraints

- 既存の軽量マイグレーション方針を踏襲する（Alembic等は使わない）。
- 既存のテストスタイル（`tmp_path` + `create_db_engine` + `init_db` + `sessionmaker`）に合わせる。
- シードファイルは `app/data/`（`.gitignore`で除外済み）ではなく `app/db/` に置く。
- `company_profiles`に既に値が入っている列（実際にyfinanceから取得済み・管理者が編集済み）はシード投入で上書きしない。
- 本番DB（`app/data/app.db`）は今回のタスクでは直接操作しない。次回`init_db()`実行時（アプリ起動時）に自動反映される。

---

## File Structure

- Modify: `db/models.py` — `CompanyProfile.sector_jp`列を追加
- Modify: `db/engine.py` — `_add_column_if_missing`をテーブル名パラメータ化、`sector_jp`列マイグレーション、シード投入ロジックを追加
- Create: `db/seed_company_profiles.csv` — 228銘柄分のticker/name/sector_jp静的データ
- Modify: `data_api/stock_price_api.py` — `load_all_company_profiles`追加、`load_company_profile`/`save_company_profile_fields`に`sector_jp`追加
- Modify: `app_tabs/admin_tab.py` — 企業プロファイルフォームに`sector_jp`入力欄を追加
- Modify: `app_tabs/screening_tab.py`・`app_tabs/ranking_tab.py`・`app_tabs/strategy_builder_tab.py`・`app_tabs/shared.py` — `UNIVERSE`/`UNIVERSE_NAMES`/`SECTOR_MAP`を`load_all_company_profiles()`ベースに置き換え
- Modify: `portfolio_management/ticker_names.py` — `build_candidate_names`のデフォルト引数を`company_profiles`ベースに変更
- Delete: `screening/universe.py`・`screening/sectors.py`・`tests/test_universe.py`・`tests/test_sectors.py`
- Modify: `tests/test_db_engine.py`・`tests/test_stock_price_api.py`・`tests/test_ticker_names.py`
- Create: `tests/test_seed_company_profiles.py`

---

### Task 1: `company_profiles.sector_jp`列の追加とマイグレーション

**Files:**
- Modify: `db/models.py`
- Modify: `db/engine.py`
- Test: `tests/test_db_engine.py`

**Interfaces:**
- Produces: `CompanyProfile.sector_jp: str | None`。`init_db(engine)`実行後、既存DB・新規DBのいずれでも`company_profiles`テーブルに`sector_jp`列（NULL許容TEXT）が存在する。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_db_engine.py` の末尾に追加:

```python
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
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd app && python -m pytest tests/test_db_engine.py::test_init_db_adds_sector_jp_column_to_existing_company_profiles_table -v`
Expected: FAIL（`sector_jp`列が無い。なお`init_db()`の`Base.metadata.create_all`は既存テーブルをスキップするため、事前にFKなしの素朴なcompany_profilesテーブルを作っておくことでこのテストは既存DBを模している）

- [ ] **Step 3: `db/models.py`を修正する**

```python
class CompanyProfile(Base):
    __tablename__ = "company_profiles"

    ticker: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(nullable=True)
    name_updated_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)
    sector: Mapped[str | None] = mapped_column(nullable=True)
    industry: Mapped[str | None] = mapped_column(nullable=True)
    sector_jp: Mapped[str | None] = mapped_column(nullable=True)
    business_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_updated_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)
```

- [ ] **Step 4: `db/engine.py`の`_add_column_if_missing`をテーブル名パラメータ化する**

現在`_add_column_if_missing`は`users`テーブルにハードコードされている。`company_profiles`にも使うため、テーブル名を引数化する。

修正前:

```python
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
```

修正後:

```python
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
```

呼び出し元2箇所（`_ensure_user_name_columns`・`_ensure_admin_column`）を修正:

```python
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
```

- [ ] **Step 5: `_ensure_company_profile_sector_jp_column`を追加し`init_db()`から呼ぶ**

`_ensure_admin_column`の直後に追加:

```python
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
```

`init_db()`を修正（`_ensure_market_data_foreign_keys(engine)`の後に呼ぶ。company_profilesテーブル自体は`_ensure_market_data_foreign_keys`実行前でも`Base.metadata.create_all`で既に存在するため順序上の依存はないが、FK関連の処理を先に完了させてから列追加を行う）:

```python
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
    追加した上で、seed_company_profiles.csv（旧UNIVERSE_NAMES/SECTOR_MAP相当の
    初期データ）を投入する。"""
    Base.metadata.create_all(engine)
    _ensure_user_name_columns(engine)
    _ensure_admin_column(engine)
    _grant_admin_to_first_user_if_none_exists(engine)
    _ensure_market_data_foreign_keys(engine)
    _ensure_company_profile_sector_jp_column(engine)
```

（シード投入呼び出しはTask 3で追加する）

- [ ] **Step 6: テストが通ることを確認する**

Run: `cd app && python -m pytest tests/test_db_engine.py -v`
Expected: PASS（全件。既存の列追加テスト2件も含めて回帰が無いことを確認する）

- [ ] **Step 7: コミット**

```bash
git add app/db/models.py app/db/engine.py app/tests/test_db_engine.py
git commit -m "feat: add company_profiles.sector_jp column with lightweight migration"
```

---

### Task 2: シードCSVの生成とデータ整合性テスト

**Files:**
- Create: `db/seed_company_profiles.csv`
- Create: `tests/test_seed_company_profiles.py`

**Interfaces:**
- Produces: `app/db/seed_company_profiles.csv`（ヘッダー行`ticker,name,sector_jp` + 228データ行）。この時点では `screening/universe.py`・`screening/sectors.py` はまだ削除しない（Task 8まで他タブファイルが参照し続けるため）。

- [ ] **Step 1: 一時生成スクリプトを作成し実行する**

`app/scripts/_generate_seed_company_profiles.py`（一時ファイル、CSV生成後に削除する）を作成:

```python
"""UNIVERSE_NAMES/SECTOR_MAPからseed_company_profiles.csvを生成する一時スクリプト。
CSV生成後、本ファイルは削除する（screening/universe.py・screening/sectors.py
削除に先立って一度だけ実行するためのもの）。"""

import csv
from pathlib import Path

from screening.sectors import SECTOR_MAP
from screening.universe import UNIVERSE_NAMES

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "db" / "seed_company_profiles.csv"


def main() -> None:
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ticker", "name", "sector_jp"])
        for ticker in sorted(UNIVERSE_NAMES):
            writer.writerow([ticker, UNIVERSE_NAMES[ticker], SECTOR_MAP[ticker]])
    print(f"{len(UNIVERSE_NAMES)}件を{OUTPUT_PATH}へ書き出しました。")


if __name__ == "__main__":
    main()
```

Run: `cd app && python -m scripts._generate_seed_company_profiles`
Expected: `228件を...db/seed_company_profiles.csvへ書き出しました。` と表示され、`app/db/seed_company_profiles.csv`が生成される。

- [ ] **Step 2: 生成されたCSVを確認し、一時スクリプトを削除する**

Run: `cd app && head -5 db/seed_company_profiles.csv && wc -l db/seed_company_profiles.csv`
Expected: ヘッダー行 + 228データ行で229行。1行目は`ticker,name,sector_jp`。

一時生成スクリプトを削除:

```bash
rm app/scripts/_generate_seed_company_profiles.py
```

- [ ] **Step 3: シードCSVのデータ整合性テストを書く**

`tests/test_seed_company_profiles.py`（新規）:

```python
import csv
from pathlib import Path

SEED_PATH = Path(__file__).resolve().parent.parent / "db" / "seed_company_profiles.csv"


def _read_seed_rows() -> list[dict]:
    with SEED_PATH.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_seed_file_has_228_rows():
    assert len(_read_seed_rows()) == 228


def test_seed_tickers_are_unique():
    rows = _read_seed_rows()
    tickers = [row["ticker"] for row in rows]
    assert len(tickers) == len(set(tickers))


def test_seed_tickers_use_tokyo_exchange_suffix():
    rows = _read_seed_rows()
    assert all(row["ticker"].endswith(".T") for row in rows)


def test_seed_names_are_non_empty():
    rows = _read_seed_rows()
    assert all(row["name"] for row in rows)


def test_seed_covers_all_seventeen_sectors():
    expected_sectors = {
        "食品", "エネルギー資源", "建設・資材", "素材・化学", "医薬品",
        "自動車・輸送機", "鉄鋼・非鉄", "機械", "電機・精密", "運輸・物流",
        "商社・卸売", "小売", "銀行", "金融（除く銀行）", "不動産",
        "情報通信・サービスその他", "電力・ガス",
    }
    rows = _read_seed_rows()
    assert {row["sector_jp"] for row in rows} == expected_sectors
```

- [ ] **Step 4: テストを実行して通ることを確認する**

Run: `cd app && python -m pytest tests/test_seed_company_profiles.py -v`
Expected: PASS（5件）。旧`tests/test_universe.py`/`tests/test_sectors.py`が検証していた不変条件（`UNIVERSE`の228件・重複無し・`.T`サフィックス・名前非空・17業種完全カバー）を、CSVに対する検証として引き継いでいる。

- [ ] **Step 5: コミット**

```bash
git add app/db/seed_company_profiles.csv app/tests/test_seed_company_profiles.py
git commit -m "feat: add seed_company_profiles.csv generated from UNIVERSE_NAMES/SECTOR_MAP"
```

---

### Task 3: シード投入ロジックを`init_db()`に組み込む

**Files:**
- Modify: `db/engine.py`
- Modify: `db/models.py`（importのみ）
- Test: `tests/test_db_engine.py`

**Interfaces:**
- Consumes: Task 1の`CompanyProfile.sector_jp`列、Task 2の`db/seed_company_profiles.csv`
- Produces: `_seed_default_company_profiles(engine: Engine, seed_path: Path = SEED_COMPANY_PROFILES_PATH) -> None`。`init_db(engine)`実行後、`seed_company_profiles.csv`の各tickerについて、`company_profiles`に行が無ければ新規作成、あっても`name`/`sector_jp`が`NULL`ならそのフィールドのみ埋める（既存の非NULL値は上書きしない）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_db_engine.py` の末尾に追加（テストは実DBの228銘柄と衝突しないよう`TEST1.T`という架空tickerを使う）:

```python
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
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd app && python -m pytest tests/test_db_engine.py -k seed_default_company_profiles -v`
Expected: FAIL（`_seed_default_company_profiles`が未定義、および実ファイル未読み込みのため`test_init_db_seeds_default_company_profiles_from_real_seed_file`も`profile is None`で失敗）

- [ ] **Step 3: `db/engine.py`に実装する**

先頭のimportに`csv`を追加:

```python
import csv
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from db.models import Base
```

`APP_DIR`定義の直後に定数を追加:

```python
SEED_COMPANY_PROFILES_PATH = Path(__file__).resolve().parent / "seed_company_profiles.csv"
```

`_ensure_company_profile_sector_jp_column`の直後に追加:

```python
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
```

`init_db()`の末尾に呼び出しを追加:

```python
def init_db(engine: Engine) -> None:
    """...（docstring既存のまま）"""
    Base.metadata.create_all(engine)
    _ensure_user_name_columns(engine)
    _ensure_admin_column(engine)
    _grant_admin_to_first_user_if_none_exists(engine)
    _ensure_market_data_foreign_keys(engine)
    _ensure_company_profile_sector_jp_column(engine)
    _seed_default_company_profiles(engine)
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `cd app && python -m pytest tests/test_db_engine.py -v`
Expected: PASS（全件）

- [ ] **Step 5: コミット**

```bash
git add app/db/engine.py app/tests/test_db_engine.py
git commit -m "feat: seed company_profiles from seed_company_profiles.csv on init_db"
```

---

### Task 4: `load_all_company_profiles`と`sector_jp`対応

**Files:**
- Modify: `data_api/stock_price_api.py`
- Modify: `app_tabs/admin_tab.py`
- Test: `tests/test_stock_price_api.py`

**Interfaces:**
- Produces: `load_all_company_profiles(session_factory=SessionLocal) -> list[dict]`（ticker順、各要素は`{"ticker", "name", "sector_jp", "sector", "industry", "business_summary"}`）。`load_company_profile`の戻り値辞書に`sector_jp`キーが追加される。`save_company_profile_fields(ticker, name, sector, industry, business_summary, sector_jp=None, session_factory=SessionLocal)`。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_stock_price_api.py` の末尾に追加:

```python
def test_load_all_company_profiles_returns_rows_ordered_by_ticker(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(stock_price_api.CompanyProfile(ticker="ZZZZ.T", name="Z社", sector_jp="小売"))
        session.add(stock_price_api.CompanyProfile(ticker="AAAA.T", name="A社", sector_jp="銀行"))
        session.commit()

    profiles = stock_price_api.load_all_company_profiles(session_factory=session_factory)
    tickers = [p["ticker"] for p in profiles]
    assert tickers.index("AAAA.T") < tickers.index("ZZZZ.T")
    aaaa = next(p for p in profiles if p["ticker"] == "AAAA.T")
    assert aaaa["name"] == "A社"
    assert aaaa["sector_jp"] == "銀行"


def test_save_company_profile_fields_stores_sector_jp(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.save_company_profile_fields(
        "9999.T",
        "テスト株式会社",
        "Technology",
        "Software",
        "概要",
        sector_jp="情報通信・サービスその他",
        session_factory=session_factory,
    )

    profile = stock_price_api.load_company_profile("9999.T", session_factory=session_factory)
    assert profile["sector_jp"] == "情報通信・サービスその他"
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd app && python -m pytest tests/test_stock_price_api.py -k "load_all_company_profiles or stores_sector_jp" -v`
Expected: FAIL（`load_all_company_profiles`未定義、`save_company_profile_fields`が`sector_jp`キーワード引数を受け付けない）

- [ ] **Step 3: `data_api/stock_price_api.py`を修正する**

`load_company_profile`を修正:

```python
def load_company_profile(ticker: str, session_factory=SessionLocal) -> dict | None:
    """指定銘柄の企業プロファイルをDBから読み込む（管理者向け）。無ければNoneを
    返す。"""
    with session_factory() as session:
        row = session.get(CompanyProfile, ticker)
        if row is None:
            return None
        return {
            "ticker": row.ticker,
            "name": row.name,
            "sector": row.sector,
            "industry": row.industry,
            "sector_jp": row.sector_jp,
            "business_summary": row.business_summary,
        }
```

`load_company_profile`の直後に`load_all_company_profiles`を追加:

```python
def load_all_company_profiles(session_factory=SessionLocal) -> list[dict]:
    """company_profilesの全行をticker順で返す（UNIVERSE/UNIVERSE_NAMES/SECTOR_MAP
    廃止に伴い、アプリが分析対象とする銘柄一覧の単一の情報源として使う）。"""
    with session_factory() as session:
        rows = session.query(CompanyProfile).order_by(CompanyProfile.ticker).all()
        return [
            {
                "ticker": row.ticker,
                "name": row.name,
                "sector_jp": row.sector_jp,
                "sector": row.sector,
                "industry": row.industry,
                "business_summary": row.business_summary,
            }
            for row in rows
        ]
```

`save_company_profile_fields`を修正:

```python
def save_company_profile_fields(
    ticker: str,
    name: str | None,
    sector: str | None,
    industry: str | None,
    business_summary: str | None,
    sector_jp: str | None = None,
    session_factory=SessionLocal,
) -> None:
    """指定銘柄の企業プロファイルを直接UPDATEする（管理者向け）。行が無ければ
    新規作成する。"""
    with session_factory() as session:
        row = session.get(CompanyProfile, ticker)
        if row is None:
            row = CompanyProfile(ticker=ticker)
            session.add(row)
        row.name = name
        row.sector = sector
        row.industry = industry
        row.business_summary = business_summary
        row.sector_jp = sector_jp
        session.commit()
```

- [ ] **Step 4: `app_tabs/admin_tab.py`の企業プロファイルフォームに`sector_jp`欄を追加する**

修正前:

```python
    st.markdown("**企業プロファイル（CompanyProfile）**")
    profile = load_company_profile(ticker) or {}
    with st.form(key=f"admin_company_profile_form_{ticker}"):
        name = st.text_input("日本語銘柄名", value=profile.get("name") or "")
        sector = st.text_input("業種", value=profile.get("sector") or "")
        industry = st.text_input("詳細業種", value=profile.get("industry") or "")
        business_summary = st.text_area(
            "事業内容", value=profile.get("business_summary") or "", height=150
        )
        if st.form_submit_button("企業プロファイルを保存"):
            save_company_profile_fields(
                ticker,
                name or None,
                sector or None,
                industry or None,
                business_summary or None,
            )
            st.success("企業プロファイルを保存しました。")
            st.rerun()
```

修正後:

```python
    st.markdown("**企業プロファイル（CompanyProfile）**")
    profile = load_company_profile(ticker) or {}
    with st.form(key=f"admin_company_profile_form_{ticker}"):
        name = st.text_input("日本語銘柄名", value=profile.get("name") or "")
        sector = st.text_input("業種", value=profile.get("sector") or "")
        industry = st.text_input("詳細業種", value=profile.get("industry") or "")
        sector_jp = st.text_input("東証17業種区分", value=profile.get("sector_jp") or "")
        business_summary = st.text_area(
            "事業内容", value=profile.get("business_summary") or "", height=150
        )
        if st.form_submit_button("企業プロファイルを保存"):
            save_company_profile_fields(
                ticker,
                name or None,
                sector or None,
                industry or None,
                business_summary or None,
                sector_jp or None,
            )
            st.success("企業プロファイルを保存しました。")
            st.rerun()
```

- [ ] **Step 5: テストが通ることを確認する**

Run: `cd app && python -m pytest tests/test_stock_price_api.py -v`
Expected: PASS（全件）

- [ ] **Step 6: コミット**

```bash
git add app/data_api/stock_price_api.py app/app_tabs/admin_tab.py app/tests/test_stock_price_api.py
git commit -m "feat: add load_all_company_profiles and sector_jp support to admin CRUD"
```

---

### Task 5: `screening_tab.py`を`load_all_company_profiles()`ベースに置き換える

**Files:**
- Modify: `app_tabs/screening_tab.py`

**Interfaces:**
- Consumes: Task 4の`load_all_company_profiles`

- [ ] **Step 1: importを修正する**

修正前:

```python
from data_api.stock_price_api import fetch_universe_fundamentals
from prompt_patterns.screening import (
    apply_filters,
    build_screening_prompt,
    generate_screening_comments,
)
from screening.sectors import SECTOR_MAP
from screening.universe import UNIVERSE, UNIVERSE_NAMES
```

修正後:

```python
from data_api.stock_price_api import fetch_universe_fundamentals, load_all_company_profiles
from prompt_patterns.screening import (
    apply_filters,
    build_screening_prompt,
    generate_screening_comments,
)
```

- [ ] **Step 2: `render_screening_tab`本体を修正する**

修正前:

```python
def render_screening_tab() -> None:
    logger.info("スクリーニングタブを表示")
    st.header("銘柄スクリーニング")

    condition_text = st.text_input(
        "スクリーニング条件を自然言語で入力してください",
        placeholder="PERが15倍以下で配当利回りが3%以上",
    )

    if condition_text:
        # 入力条件が前回から変わった場合のみLLMを呼び出し、自然言語条件を
        # 構造化フィルタ（JSON）に変換する。変わっていなければ結果をセッションから再利用する
        if st.session_state.get("screening_condition_text") != condition_text:
            prompt = build_screening_prompt(
                condition_text, sectors=sorted(set(SECTOR_MAP.values()))
            )
```

修正後:

```python
def render_screening_tab() -> None:
    logger.info("スクリーニングタブを表示")
    st.header("銘柄スクリーニング")

    company_profiles = load_all_company_profiles()
    tickers = [p["ticker"] for p in company_profiles]
    names_by_ticker = {p["ticker"]: p["name"] for p in company_profiles if p["name"]}
    sector_jp_by_ticker = {
        p["ticker"]: p["sector_jp"] for p in company_profiles if p["sector_jp"]
    }

    condition_text = st.text_input(
        "スクリーニング条件を自然言語で入力してください",
        placeholder="PERが15倍以下で配当利回りが3%以上",
    )

    if condition_text:
        # 入力条件が前回から変わった場合のみLLMを呼び出し、自然言語条件を
        # 構造化フィルタ（JSON）に変換する。変わっていなければ結果をセッションから再利用する
        if st.session_state.get("screening_condition_text") != condition_text:
            prompt = build_screening_prompt(
                condition_text, sectors=sorted(set(sector_jp_by_ticker.values()))
            )
```

続けて絞り込みボタンの処理を修正する。修正前:

```python
            # ユニバース銘柄のファンダメンタルズを取得し、条件でフィルタしてAIコメントを付与する
            if st.button("この条件で絞り込む"):
                with log_duration(logger, "スクリーニング絞り込み実行"):
                    universe_df = fetch_universe_fundamentals(UNIVERSE)
                    universe_df["name"] = universe_df["ticker"].map(UNIVERSE_NAMES).fillna(
                        universe_df["name"]
                    )
                    universe_df["sector"] = universe_df["ticker"].map(SECTOR_MAP)
```

修正後:

```python
            # 対象銘柄のファンダメンタルズを取得し、条件でフィルタしてAIコメントを付与する
            if st.button("この条件で絞り込む"):
                with log_duration(logger, "スクリーニング絞り込み実行"):
                    universe_df = fetch_universe_fundamentals(tickers)
                    universe_df["name"] = universe_df["ticker"].map(names_by_ticker).fillna(
                        universe_df["name"]
                    )
                    universe_df["sector"] = universe_df["ticker"].map(sector_jp_by_ticker)
```

- [ ] **Step 3: 手動確認の準備として構文エラーが無いことを確認する**

Run: `cd app && python -c "import app_tabs.screening_tab"`
Expected: エラー無く終了する（importエラーが無いことの確認。Streamlit UIの実地確認はTask 10でまとめて行う）

- [ ] **Step 4: コミット**

```bash
git add app/app_tabs/screening_tab.py
git commit -m "refactor: use load_all_company_profiles in screening tab"
```

---

### Task 6: `ranking_tab.py`を`load_all_company_profiles()`ベースに置き換える

**Files:**
- Modify: `app_tabs/ranking_tab.py`

- [ ] **Step 1: importを修正する**

修正前:

```python
from common.cache import read_cache, write_cache
from common.concurrency import map_concurrently
from common.disclaimer import DISCLAIMER_NOTICE
from common.logging_config import log_duration
from data_api.llm_client import call_llm
from portfolio_management.backtest import STRATEGIES, run_universe_backtest_ranking
from portfolio_management.storage import load_holdings
from portfolio_management.ticker_names import build_candidate_names
from prompt_patterns.backtest_explanation import generate_ranking_comments
from screening.universe import UNIVERSE
```

修正後:

```python
from common.cache import read_cache, write_cache
from common.concurrency import map_concurrently
from common.disclaimer import DISCLAIMER_NOTICE
from common.logging_config import log_duration
from data_api.llm_client import call_llm
from data_api.stock_price_api import load_all_company_profiles
from portfolio_management.backtest import STRATEGIES, run_universe_backtest_ranking
from portfolio_management.storage import load_holdings
from portfolio_management.ticker_names import build_candidate_names
from prompt_patterns.backtest_explanation import generate_ranking_comments
```

- [ ] **Step 2: 対象銘柄の組み立てを修正する**

修正前:

```python
        # 分析対象はユニバース銘柄と保有銘柄の和集合とする
        holdings = load_holdings(get_current_user_id())
        holdings_tickers = [h["ticker"] for h in holdings if h.get("ticker")]
        target_tickers = sorted(set(UNIVERSE) | set(holdings_tickers))
```

修正後:

```python
        # 分析対象はcompany_profilesの全銘柄と保有銘柄の和集合とする
        holdings = load_holdings(get_current_user_id())
        holdings_tickers = [h["ticker"] for h in holdings if h.get("ticker")]
        all_tickers = [p["ticker"] for p in load_all_company_profiles()]
        target_tickers = sorted(set(all_tickers) | set(holdings_tickers))
```

- [ ] **Step 3: importエラーが無いことを確認する**

Run: `cd app && python -c "import app_tabs.ranking_tab"`
Expected: エラー無く終了する

- [ ] **Step 4: コミット**

```bash
git add app/app_tabs/ranking_tab.py
git commit -m "refactor: use load_all_company_profiles in ranking tab"
```

---

### Task 7: `strategy_builder_tab.py`を`load_all_company_profiles()`ベースに置き換える

**Files:**
- Modify: `app_tabs/strategy_builder_tab.py`

**Interfaces:**
- Consumes: `strategy_builder.sector_insight.build_watchlist_from_rotation(ticker_latest_return_pct, network_pairs, sector_map: dict[str, str], universe_names: dict[str, str], ...)` — 既存シグネチャのまま、渡す辞書の中身のみ変更する。

- [ ] **Step 1: importを修正する**

修正前:

```python
from common.disclaimer import DISCLAIMER_NOTICE
from data_api.llm_client import call_llm
from data_api.stock_price_api import (
    fetch_universe_fundamentals,
    fetch_universe_price_histories,
)
from prompt_patterns.strategy_dialogue import build_dialogue_prompt, parse_dialogue_response
from screening.sectors import SECTOR_MAP
from screening.universe import UNIVERSE, UNIVERSE_NAMES
from sector_analysis.network import build_mermaid_lead_lag_graph
```

修正後:

```python
from common.disclaimer import DISCLAIMER_NOTICE
from data_api.llm_client import call_llm
from data_api.stock_price_api import (
    fetch_universe_fundamentals,
    fetch_universe_price_histories,
    load_all_company_profiles,
)
from prompt_patterns.strategy_dialogue import build_dialogue_prompt, parse_dialogue_response
from sector_analysis.network import build_mermaid_lead_lag_graph
```

- [ ] **Step 2: `_render_sector_rotation_suggestion`を修正する（`SECTOR_MAP`/`UNIVERSE_NAMES`をパラメータとして渡す箇所）**

修正前:

```python
        watchlist = build_watchlist_from_rotation(
            payload.get("ticker_latest_return_pct", {}),
            payload.get("network_pairs", []),
            SECTOR_MAP,
            UNIVERSE_NAMES,
            band=band,
        )
```

修正後:

```python
        company_profiles = load_all_company_profiles()
        sector_jp_by_ticker = {
            p["ticker"]: p["sector_jp"] for p in company_profiles if p["sector_jp"]
        }
        names_by_ticker = {p["ticker"]: p["name"] for p in company_profiles if p["name"]}
        watchlist = build_watchlist_from_rotation(
            payload.get("ticker_latest_return_pct", {}),
            payload.get("network_pairs", []),
            sector_jp_by_ticker,
            names_by_ticker,
            band=band,
        )
```

- [ ] **Step 3: `_render_dialogue_section`のLLMプロンプトを修正する**

修正前:

```python
    if history[-1]["role"] == "user" and pending is None:
        prompt = build_dialogue_prompt(history, sectors=sorted(set(SECTOR_MAP.values())))
```

修正後:

```python
    if history[-1]["role"] == "user" and pending is None:
        sector_jp_values = {
            p["sector_jp"] for p in load_all_company_profiles() if p["sector_jp"]
        }
        prompt = build_dialogue_prompt(history, sectors=sorted(sector_jp_values))
```

- [ ] **Step 4: `_render_backtest_section`を修正する**

修正前:

```python
    if st.button("バックテストを実行", key="strategy_run_backtest"):
        with st.spinner("バックテストを実行中..."):
            universe_df = fetch_universe_fundamentals(UNIVERSE)
            universe_df["name"] = universe_df["ticker"].map(UNIVERSE_NAMES).fillna(
                universe_df["name"]
            )
            universe_df["sector"] = universe_df["ticker"].map(SECTOR_MAP)
            matched_df = apply_strategy_conditions(universe_df, strategy)
```

修正後:

```python
    if st.button("バックテストを実行", key="strategy_run_backtest"):
        with st.spinner("バックテストを実行中..."):
            company_profiles = load_all_company_profiles()
            tickers = [p["ticker"] for p in company_profiles]
            names_by_ticker = {p["ticker"]: p["name"] for p in company_profiles if p["name"]}
            sector_jp_by_ticker = {
                p["ticker"]: p["sector_jp"] for p in company_profiles if p["sector_jp"]
            }
            universe_df = fetch_universe_fundamentals(tickers)
            universe_df["name"] = universe_df["ticker"].map(names_by_ticker).fillna(
                universe_df["name"]
            )
            universe_df["sector"] = universe_df["ticker"].map(sector_jp_by_ticker)
            matched_df = apply_strategy_conditions(universe_df, strategy)
```

- [ ] **Step 5: `_render_screening_sector_network`を修正する**

修正前:

```python
    selected_sectors = set(result_df["ticker"].map(SECTOR_MAP).dropna())
```

修正後:

```python
    sector_jp_by_ticker = {
        p["ticker"]: p["sector_jp"] for p in load_all_company_profiles() if p["sector_jp"]
    }
    selected_sectors = set(result_df["ticker"].map(sector_jp_by_ticker).dropna())
```

- [ ] **Step 6: `_render_screening_section`を修正する**

修正前:

```python
    if st.button("最新データで銘柄選定を実行", key="strategy_run_screening"):
        with st.spinner("銘柄を絞り込み中..."):
            universe_df = fetch_universe_fundamentals(UNIVERSE)
            universe_df["name"] = universe_df["ticker"].map(UNIVERSE_NAMES).fillna(
                universe_df["name"]
            )
            universe_df["sector"] = universe_df["ticker"].map(SECTOR_MAP)
            matched_df = apply_strategy_conditions(universe_df, strategy)
            matched_df = sort_by_strategy(matched_df, strategy)
```

修正後:

```python
    if st.button("最新データで銘柄選定を実行", key="strategy_run_screening"):
        with st.spinner("銘柄を絞り込み中..."):
            company_profiles = load_all_company_profiles()
            tickers = [p["ticker"] for p in company_profiles]
            names_by_ticker = {p["ticker"]: p["name"] for p in company_profiles if p["name"]}
            sector_jp_by_ticker = {
                p["ticker"]: p["sector_jp"] for p in company_profiles if p["sector_jp"]
            }
            universe_df = fetch_universe_fundamentals(tickers)
            universe_df["name"] = universe_df["ticker"].map(names_by_ticker).fillna(
                universe_df["name"]
            )
            universe_df["sector"] = universe_df["ticker"].map(sector_jp_by_ticker)
            matched_df = apply_strategy_conditions(universe_df, strategy)
            matched_df = sort_by_strategy(matched_df, strategy)
```

- [ ] **Step 7: importエラーが無いことを確認する**

Run: `cd app && python -c "import app_tabs.strategy_builder_tab"`
Expected: エラー無く終了する

- [ ] **Step 8: コミット**

```bash
git add app/app_tabs/strategy_builder_tab.py
git commit -m "refactor: use load_all_company_profiles in strategy builder tab"
```

---

### Task 8: `shared.py`のセクターローテーションを`sector_jp`保有銘柄ベースに置き換える

**Files:**
- Modify: `app_tabs/shared.py`

**設計判断:** セクターローテーション分析は業種バケット化が前提のため、`company_profiles`の全銘柄ではなく「`sector_jp`が設定されている銘柄」のみを対象にする。これにより分析対象集合が無関係な保有銘柄追加のたびに変動する（＝日次キャッシュキーが不必要に変わる）のを避ける。

- [ ] **Step 1: importを修正する**

修正前:

```python
from data_api.stock_price_api import fetch_japanese_name, fetch_news, fetch_price_history
from prompt_patterns.sector_rotation import generate_sector_rotation_comments
from screening.sectors import SECTOR_MAP
from screening.universe import UNIVERSE
from sector_analysis.correlation import compute_lead_lag_pairs, compute_sector_returns
```

修正後:

```python
from data_api.stock_price_api import (
    fetch_japanese_name,
    fetch_news,
    fetch_price_history,
    load_all_company_profiles,
)
from prompt_patterns.sector_rotation import generate_sector_rotation_comments
from sector_analysis.correlation import compute_lead_lag_pairs, compute_sector_returns
```

- [ ] **Step 2: `run_or_load_sector_rotation`を修正する**

修正前:

```python
def run_or_load_sector_rotation(period: str, force_regenerate: bool) -> dict | None:
    """セクターローテーション分析を実行または既存キャッシュから読み込み、
    ペイロード（pairs/sector_returns/network_pairs/comments/
    ticker_latest_return_pct等）を返す。分析可能な銘柄が1件もない場合はNoneを返す。

    セクタータブ・AI戦略ビルダータブの両方から呼ばれる共通処理。同一の
    period・UNIVERSEであればディスクキャッシュを共有し、二重計算を避ける。
    実行結果は st.session_state["sector_payload"] にも保存する。
    """
    cache_key = "sector-rotation-" + hashlib.sha256(
        f"{period}-{'-'.join(sorted(UNIVERSE))}".encode("utf-8")
    ).hexdigest()[:12]
```

修正後:

```python
def run_or_load_sector_rotation(period: str, force_regenerate: bool) -> dict | None:
    """セクターローテーション分析を実行または既存キャッシュから読み込み、
    ペイロード（pairs/sector_returns/network_pairs/comments/
    ticker_latest_return_pct等）を返す。分析可能な銘柄が1件もない場合はNoneを返す。

    対象銘柄は company_profiles のうち sector_jp（東証17業種区分）が設定されて
    いるものに限る（業種バケット化が前提の分析のため）。

    セクタータブ・AI戦略ビルダータブの両方から呼ばれる共通処理。同一の
    period・対象銘柄集合であればディスクキャッシュを共有し、二重計算を避ける。
    実行結果は st.session_state["sector_payload"] にも保存する。
    """
    company_profiles = load_all_company_profiles()
    sector_jp_by_ticker = {
        p["ticker"]: p["sector_jp"] for p in company_profiles if p["sector_jp"]
    }
    sector_universe = sorted(sector_jp_by_ticker)

    cache_key = "sector-rotation-" + hashlib.sha256(
        f"{period}-{'-'.join(sector_universe)}".encode("utf-8")
    ).hexdigest()[:12]
```

続けて、ティッカー反復処理を修正する。修正前:

```python
    if payload is None:
        with log_duration(logger, f"セクターローテーション分析実行（{period}）"):
            skipped_tickers = []
            prices_by_ticker = {}
            with st.spinner(f"株価データを取得中...（{len(UNIVERSE)}銘柄）"):
                price_results = map_concurrently(
                    UNIVERSE, lambda ticker: cached_fetch_price_history(ticker, period)
                )
            for ticker in UNIVERSE:
                history = price_results[ticker]
```

修正後:

```python
    if payload is None:
        with log_duration(logger, f"セクターローテーション分析実行（{period}）"):
            skipped_tickers = []
            prices_by_ticker = {}
            with st.spinner(f"株価データを取得中...（{len(sector_universe)}銘柄）"):
                price_results = map_concurrently(
                    sector_universe, lambda ticker: cached_fetch_price_history(ticker, period)
                )
            for ticker in sector_universe:
                history = price_results[ticker]
```

最後に、`SECTOR_MAP`参照2箇所を修正する。修正前:

```python
            sector_returns = compute_sector_returns(prices_by_ticker, SECTOR_MAP)
            excluded_sectors = sorted(set(SECTOR_MAP.values()) - set(sector_returns.keys()))
```

修正後:

```python
            sector_returns = compute_sector_returns(prices_by_ticker, sector_jp_by_ticker)
            excluded_sectors = sorted(
                set(sector_jp_by_ticker.values()) - set(sector_returns.keys())
            )
```

- [ ] **Step 3: importエラーが無いことを確認する**

Run: `cd app && python -c "import app_tabs.shared"`
Expected: エラー無く終了する

- [ ] **Step 4: コミット**

```bash
git add app/app_tabs/shared.py
git commit -m "refactor: scope sector rotation to company_profiles rows with sector_jp"
```

---

### Task 9: `ticker_names.py::build_candidate_names`のデフォルト引数を置き換える

**Files:**
- Modify: `portfolio_management/ticker_names.py`
- Test: `tests/test_ticker_names.py`

**Interfaces:**
- Produces: `build_candidate_names(holdings: list[dict], known_names: dict[str, str] | None = None, resolve_name=default_resolve_name) -> dict[str, str]`（引数名`universe_names`→`known_names`に変更。デフォルト`None`時は`load_all_company_profiles()`から遅延構築）

- [ ] **Step 1: 既存テストを新しい引数名に追従させる**

`tests/test_ticker_names.py`の`universe_names=`をすべて`known_names=`に置換する（4箇所）:

```python
from portfolio_management.ticker_names import build_candidate_names


def test_returns_universe_names_when_no_extra_holdings():
    result = build_candidate_names([], known_names={"7203.T": "トヨタ自動車"})
    assert result == {"7203.T": "トヨタ自動車"}


def test_resolves_names_for_holdings_outside_universe():
    holdings = [{"ticker": "AAA.T", "shares": 10, "cost": 100.0}]

    def fake_resolve_name(ticker):
        assert ticker == "AAA.T"
        return "フェイク株式会社"

    result = build_candidate_names(
        holdings,
        known_names={"7203.T": "トヨタ自動車"},
        resolve_name=fake_resolve_name,
    )
    assert result == {"7203.T": "トヨタ自動車", "AAA.T": "フェイク株式会社"}


def test_excludes_holdings_whose_name_cannot_be_resolved():
    holdings = [{"ticker": "BBB.T", "shares": 10, "cost": 100.0}]

    result = build_candidate_names(
        holdings,
        known_names={},
        resolve_name=lambda ticker: None,
    )
    assert result == {}


def test_universe_name_is_not_overwritten_by_holding_lookup():
    holdings = [{"ticker": "7203.T", "shares": 10, "cost": 100.0}]

    def fake_resolve_name(ticker):
        raise AssertionError("known_names内のティッカーはresolve_nameを呼ばない")

    result = build_candidate_names(
        holdings,
        known_names={"7203.T": "トヨタ自動車"},
        resolve_name=fake_resolve_name,
    )
    assert result == {"7203.T": "トヨタ自動車"}
```

同ファイルの末尾にデフォルト値（未指定時）のテストを追加:

```python
def test_default_known_names_loaded_from_company_profiles(monkeypatch):
    import portfolio_management.ticker_names as ticker_names_module

    monkeypatch.setattr(
        ticker_names_module,
        "load_all_company_profiles",
        lambda: [{"ticker": "7203.T", "name": "トヨタ自動車"}],
    )

    result = build_candidate_names([], resolve_name=lambda ticker: None)
    assert result == {"7203.T": "トヨタ自動車"}
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd app && python -m pytest tests/test_ticker_names.py -v`
Expected: 既存4件は`known_names`という未知のキーワード引数でTypeError、新規1件は`load_all_company_profiles`未importでAttributeError

- [ ] **Step 3: `portfolio_management/ticker_names.py`を修正する**

修正前:

```python
"""銘柄コードから日本語の銘柄名を解決し、画面表示等に使う
「銘柄コード→銘柄名」の対応表を組み立てるモジュール。"""

from data_api.stock_price_api import fetch_japanese_name as default_resolve_name
from screening.universe import UNIVERSE_NAMES


def build_candidate_names(
    holdings: list[dict],
    universe_names: dict[str, str] = UNIVERSE_NAMES,
    resolve_name=default_resolve_name,
) -> dict[str, str]:
    """既知の銘柄名一覧（UNIVERSE_NAMES）をベースに、そこに含まれない
    保有銘柄についてはAPI経由で名称を解決し追加する。ユニバースに
    存在する銘柄は再解決せず、無駄なAPI呼び出しを避ける。"""
    candidates = dict(universe_names)
    for holding in holdings:
        ticker = holding.get("ticker")
        if not ticker or ticker in candidates:
            continue
        name = resolve_name(ticker)
        if name:
            candidates[ticker] = name
    return candidates
```

修正後:

```python
"""銘柄コードから日本語の銘柄名を解決し、画面表示等に使う
「銘柄コード→銘柄名」の対応表を組み立てるモジュール。"""

from data_api.stock_price_api import fetch_japanese_name as default_resolve_name
from data_api.stock_price_api import load_all_company_profiles


def build_candidate_names(
    holdings: list[dict],
    known_names: dict[str, str] | None = None,
    resolve_name=default_resolve_name,
) -> dict[str, str]:
    """既知の銘柄名一覧（company_profiles、未指定時は都度DBから読み込む）を
    ベースに、そこに含まれない保有銘柄についてはAPI経由で名称を解決し追加する。
    既知の銘柄は再解決せず、無駄なAPI呼び出しを避ける。"""
    if known_names is None:
        known_names = {
            p["ticker"]: p["name"] for p in load_all_company_profiles() if p["name"]
        }
    candidates = dict(known_names)
    for holding in holdings:
        ticker = holding.get("ticker")
        if not ticker or ticker in candidates:
            continue
        name = resolve_name(ticker)
        if name:
            candidates[ticker] = name
    return candidates
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `cd app && python -m pytest tests/test_ticker_names.py -v`
Expected: PASS（5件）

- [ ] **Step 5: コミット**

```bash
git add app/portfolio_management/ticker_names.py app/tests/test_ticker_names.py
git commit -m "refactor: build_candidate_names defaults to company_profiles names"
```

---

### Task 10: `UNIVERSE`/`SECTOR_MAP`ファイル削除と全体確認

**Files:**
- Delete: `screening/universe.py`
- Delete: `screening/sectors.py`
- Delete: `tests/test_universe.py`
- Delete: `tests/test_sectors.py`

**Interfaces:**
- Consumes: Task 5〜9で`UNIVERSE`/`UNIVERSE_NAMES`/`SECTOR_MAP`への参照がすべて置き換わっていること

- [ ] **Step 1: 残存参照が無いことを確認する**

Run: `cd app && grep -rn "screening.universe\|screening.sectors\|UNIVERSE\b\|UNIVERSE_NAMES\|SECTOR_MAP" --include=*.py . | grep -v ".venv"`
Expected: 出力なし（`screening/universe.py`・`screening/sectors.py`自身とそのテストを除き、参照が残っていないこと）

- [ ] **Step 2: ファイルを削除する**

```bash
rm app/screening/universe.py app/screening/sectors.py app/tests/test_universe.py app/tests/test_sectors.py
```

- [ ] **Step 3: 全体テストを実行する**

Run: `cd app && python -m pytest -v`
Expected: PASS（全件。screening/universe.py・sectors.py削除によるimportエラーが無いことを含めて確認する）

- [ ] **Step 4: アプリを起動し、影響4タブを手動確認する**

Run: `cd app && streamlit run app.py`

以下を実際にブラウザ操作で確認する（これら4ファイルには自動テストが無いため）:

1. スクリーニングタブ: 自然言語条件を入力し「この条件で絞り込む」を実行。結果一覧に銘柄・業種が表示されること。
2. ランキングタブ: 「一括バックテストを実行」を実行し、結果が返ること。
3. 戦略ビルダータブ: 投資アイデア入力→対話→確定→バックテスト→銘柄選定の一連の流れがエラー無く動くこと。「本日の値上がり銘柄」提案（`_render_sector_rotation_suggestion`）も表示されること。
4. セクターローテーションタブ（既存のセクタータブ）: 分析を実行し、業種別の結果が表示されること。

Expected: いずれもエラー無く、以前と同等の内容が表示される。

- [ ] **Step 5: コミット**

```bash
git add app/screening/ app/tests/test_universe.py app/tests/test_sectors.py
git commit -m "chore: remove UNIVERSE/UNIVERSE_NAMES/SECTOR_MAP now superseded by company_profiles"
```

---

## Post-implementation note

本番DB（`app/data/app.db`）は今回の一連のタスクでは直接操作しない。次回`streamlit run app.py`（内部で`init_db()`を呼ぶ経路）実行時に、`sector_jp`列追加とシードデータ投入が自動的に反映される。実行前に`app/data/app.db`のバックアップを取ることを推奨する。
