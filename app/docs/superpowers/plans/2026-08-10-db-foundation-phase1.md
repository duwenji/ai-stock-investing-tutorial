# DB基盤（フェーズ1: ユーザー個別データのDB化） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `holdings.json`/`strategies.json`/`sector_display_settings.json`のJSONファイル永続化を、SQLite+SQLAlchemyによるDB永続化に置き換える（`docs/superpowers/specs/2026-08-10-database-multiuser-auth-design.md`のフェーズ1）。

**Architecture:** 新規`db/`パッケージ（`models.py`のORMモデル4種＋`engine.py`のエンジン/セッション生成・`init_db()`）を土台に、既存の`portfolio_management/storage.py`・`strategy_builder/storage.py`・`sector_analysis/display_settings.py`の関数シグネチャを`path: Path`から`user_id: int`に変更する。認証（フェーズ3）はまだ導入せず、`app_tabs/shared.py`に置く暫定定数`DEFAULT_USER_ID = 1`に固定して動作させる。既存JSONファイルは`scripts/migrate_to_db.py`で一回限りDBへ移行する。

**Tech Stack:** SQLAlchemy 2.0系（宣言的マッピング、`Mapped`/`mapped_column`）、SQLite（`data/app.db`）、bcrypt（移行時の管理者パスワードハッシュ化）、pytest（`tmp_path`上のファイルSQLiteでテスト）。

## Global Constraints

- Python >=3.14、パッケージ管理は`uv`（`ai-stock-investing-tutorial/app/pyproject.toml`）
- テストは`uv run pytest -v`（`app/`ディレクトリで実行、`pythonpath = ["."]`設定済み）
- DBを使うテストは`sqlite:///:memory:`を使わない。`:memory:`はコネクションごとに別DBになるため、SQLAlchemyの複数セッションで共有できない。代わりに`tmp_path`上のファイルDB（`sqlite:///{tmp_path}/test.db`）を使う
- 既存コードのDI（依存注入）パターンに従う: DB操作を行う関数は`session_factory`引数（デフォルトは本番用`SessionLocal`）を受け取り、テストではtmp_path DBに束縛した`session_factory`を注入する（既存の`fetch_price_history=default_fetch_price_history`のような引数上書き可能デフォルト値パターンに準拠）
- SQLiteの外部キー制約（`PRAGMA foreign_keys`）は本フェーズでは有効化しない（カスケード削除等の要件が無いため、YAGNI）
- 既存関数のシグネチャ・戻り値の形（`list[dict]`等）は可能な限り維持し、呼び出し側の変更を最小化する
- リポジトリはmasterへの直接コミット運用（フィーチャーブランチ・worktreeは使わない）
- `app/.gitignore`は既に`data/`ディレクトリ全体を除外しているため、新設する`data/app.db`は追加設定なしでリポジトリ管理外になる

---

### Task 1: 依存追加（SQLAlchemy・bcrypt）

**Files:**
- Modify: `ai-stock-investing-tutorial/app/pyproject.toml`

**Interfaces:**
- Produces: `sqlalchemy`・`bcrypt`パッケージが以降のタスクでimport可能になる

- [ ] **Step 1: SQLAlchemyとbcryptを追加する**

`ai-stock-investing-tutorial/app`ディレクトリで実行:

```bash
uv add sqlalchemy bcrypt
```

- [ ] **Step 2: 追加を確認する**

Run: `uv run python -c "import sqlalchemy, bcrypt; print(sqlalchemy.__version__)"`
Expected: バージョン文字列が出力される（エラーなし）

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: DB基盤のためsqlalchemy・bcryptを追加"
```

---

### Task 2: `db/`パッケージ（models・engine・init_db）

**Files:**
- Create: `ai-stock-investing-tutorial/app/db/__init__.py`
- Create: `ai-stock-investing-tutorial/app/db/models.py`
- Create: `ai-stock-investing-tutorial/app/db/engine.py`
- Test: `ai-stock-investing-tutorial/app/tests/test_db_engine.py`

**Interfaces:**
- Produces:
  - `db.models.Base`（`DeclarativeBase`）
  - `db.models.User(id, username, email, hashed_password, created_at)`
  - `db.models.Holding(id, user_id, ticker, shares, cost)`
  - `db.models.Strategy(id, user_id, strategy_name, strategy_json, created_at)` — `UniqueConstraint(user_id, strategy_name)`
  - `db.models.SectorDisplaySetting(user_id [PK], visible_json, order_json, height_json)`
  - `db.engine.create_db_engine(db_url: str | None = None) -> Engine`
  - `db.engine.init_db(engine: Engine) -> None`
  - `db.engine.engine`（本番用エンジン、`data/app.db`）
  - `db.engine.SessionLocal`（本番用`sessionmaker`）
  - `db.engine.DATA_DIR`（`Path`、以降のタスクで`data/`配下のJSONパス組み立てに使う）

- [ ] **Step 1: 失敗するテストを書く**

`ai-stock-investing-tutorial/app/tests/test_db_engine.py`:

```python
from sqlalchemy import inspect
from sqlalchemy.orm import sessionmaker

from db.engine import create_db_engine, init_db
from db.models import Holding, SectorDisplaySetting, Strategy, User


def test_init_db_creates_all_tables(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    table_names = set(inspect(engine).get_table_names())
    assert {"users", "holdings", "strategies", "sector_display_settings"} <= table_names


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
        session.commit()

    with session_factory() as session:
        assert session.query(Holding).count() == 1
        assert session.query(Strategy).count() == 1
        assert session.query(SectorDisplaySetting).count() == 1


def test_strategy_unique_constraint_on_user_and_name(tmp_path):
    from sqlalchemy.exc import IntegrityError

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
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_db_engine.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'db'`）

- [ ] **Step 3: `db/__init__.py`を作成する**

`ai-stock-investing-tutorial/app/db/__init__.py`: 空ファイル

- [ ] **Step 4: `db/models.py`を実装する**

`ai-stock-investing-tutorial/app/db/models.py`:

```python
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
```

- [ ] **Step 5: `db/engine.py`を実装する**

`ai-stock-investing-tutorial/app/db/engine.py`:

```python
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
```

- [ ] **Step 6: テストを実行して通ることを確認する**

Run: `uv run pytest tests/test_db_engine.py -v`
Expected: PASS（3件）

- [ ] **Step 7: Commit**

```bash
git add db/__init__.py db/models.py db/engine.py tests/test_db_engine.py
git commit -m "feat: DB基盤（User/Holding/Strategy/SectorDisplaySettingモデル・engine）を追加"
```

---

### Task 3: `portfolio_management/storage.py`のDB化

**Files:**
- Modify: `ai-stock-investing-tutorial/app/portfolio_management/storage.py`（全面書き換え）
- Modify: `ai-stock-investing-tutorial/app/tests/test_storage.py`（全面書き換え）

**Interfaces:**
- Consumes: `db.engine.SessionLocal`、`db.models.Holding`（Task 2）
- Produces:
  - `portfolio_management.storage.load_holdings(user_id: int, session_factory=SessionLocal) -> list[dict]`
  - `portfolio_management.storage.save_holdings(user_id: int, holdings: list[dict], session_factory=SessionLocal) -> None`
  - （`dict`の形は従来と同じ: `{"ticker": str, "shares": float, "cost": float}`）

- [ ] **Step 1: 失敗するテストを書く**

`ai-stock-investing-tutorial/app/tests/test_storage.py`（既存内容を置き換え）:

```python
import pytest
from sqlalchemy.orm import sessionmaker

from db.engine import create_db_engine, init_db
from portfolio_management.storage import load_holdings, save_holdings


@pytest.fixture
def session_factory(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    return sessionmaker(bind=engine)


def test_load_holdings_returns_empty_list_when_none_saved(session_factory):
    assert load_holdings(1, session_factory=session_factory) == []


def test_save_then_load_holdings_roundtrip(session_factory):
    holdings = [{"ticker": "7203.T", "shares": 100.0, "cost": 2500.0}]
    save_holdings(1, holdings, session_factory=session_factory)
    assert load_holdings(1, session_factory=session_factory) == holdings


def test_save_holdings_replaces_previous_holdings(session_factory):
    save_holdings(1, [{"ticker": "A", "shares": 1.0, "cost": 1.0}], session_factory=session_factory)
    save_holdings(1, [{"ticker": "B", "shares": 2.0, "cost": 2.0}], session_factory=session_factory)
    assert load_holdings(1, session_factory=session_factory) == [
        {"ticker": "B", "shares": 2.0, "cost": 2.0}
    ]


def test_holdings_are_scoped_per_user(session_factory):
    save_holdings(1, [{"ticker": "A", "shares": 1.0, "cost": 1.0}], session_factory=session_factory)
    save_holdings(2, [{"ticker": "B", "shares": 2.0, "cost": 2.0}], session_factory=session_factory)
    assert load_holdings(1, session_factory=session_factory) == [
        {"ticker": "A", "shares": 1.0, "cost": 1.0}
    ]
    assert load_holdings(2, session_factory=session_factory) == [
        {"ticker": "B", "shares": 2.0, "cost": 2.0}
    ]
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_storage.py -v`
Expected: FAIL（`load_holdings()`が`path`引数を要求し、シグネチャ不一致でTypeError）

- [ ] **Step 3: `portfolio_management/storage.py`を書き換える**

`ai-stock-investing-tutorial/app/portfolio_management/storage.py`（全面置き換え）:

```python
"""保有銘柄一覧（holdings）をDBで永続化・読み込みするモジュール。"""

from db.engine import SessionLocal
from db.models import Holding


def load_holdings(user_id: int, session_factory=SessionLocal) -> list[dict]:
    """指定ユーザーの保有銘柄一覧をDBから読み込む。1件も無ければ空リストを返す。"""
    with session_factory() as session:
        rows = (
            session.query(Holding)
            .filter_by(user_id=user_id)
            .order_by(Holding.id)
            .all()
        )
        return [
            {"ticker": row.ticker, "shares": row.shares, "cost": row.cost} for row in rows
        ]


def save_holdings(user_id: int, holdings: list[dict], session_factory=SessionLocal) -> None:
    """指定ユーザーの保有銘柄一覧をDBに保存する。既存の保有銘柄は全て削除してから
    渡されたholdingsで置き換える（呼び出し元は常に全件を渡す想定）。"""
    with session_factory() as session:
        session.query(Holding).filter_by(user_id=user_id).delete()
        for holding in holdings:
            session.add(
                Holding(
                    user_id=user_id,
                    ticker=holding["ticker"],
                    shares=holding["shares"],
                    cost=holding["cost"],
                )
            )
        session.commit()
```

- [ ] **Step 4: テストを実行して通ることを確認する**

Run: `uv run pytest tests/test_storage.py -v`
Expected: PASS（4件）

- [ ] **Step 5: Commit**

```bash
git add portfolio_management/storage.py tests/test_storage.py
git commit -m "refactor: 保有銘柄の永続化をJSONファイルからDBに変更"
```

---

### Task 4: `strategy_builder/storage.py`のDB化

**Files:**
- Modify: `ai-stock-investing-tutorial/app/strategy_builder/storage.py`（全面書き換え）
- Modify: `ai-stock-investing-tutorial/app/tests/test_strategy_builder_storage.py`（全面書き換え）

**Interfaces:**
- Consumes: `db.engine.SessionLocal`、`db.models.Strategy`（Task 2）
- Produces:
  - `strategy_builder.storage.load_strategies(user_id: int, session_factory=SessionLocal) -> list[dict]`
  - `strategy_builder.storage.save_strategy(user_id: int, strategy: dict, session_factory=SessionLocal) -> None`

- [ ] **Step 1: 失敗するテストを書く**

`ai-stock-investing-tutorial/app/tests/test_strategy_builder_storage.py`（既存内容を置き換え）:

```python
import pytest
from sqlalchemy.orm import sessionmaker

from db.engine import create_db_engine, init_db
from strategy_builder.storage import load_strategies, save_strategy


@pytest.fixture
def session_factory(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    return sessionmaker(bind=engine)


def test_load_strategies_returns_empty_list_when_none_saved(session_factory):
    assert load_strategies(1, session_factory=session_factory) == []


def test_save_strategy_appends_new_strategy(session_factory):
    save_strategy(
        1, {"strategy_name": "割安成長株", "conditions": []}, session_factory=session_factory
    )
    assert load_strategies(1, session_factory=session_factory) == [
        {"strategy_name": "割安成長株", "conditions": []}
    ]


def test_save_strategy_overwrites_existing_strategy_with_same_name(session_factory):
    save_strategy(
        1, {"strategy_name": "割安成長株", "conditions": [1]}, session_factory=session_factory
    )
    save_strategy(
        1, {"strategy_name": "割安成長株", "conditions": [2]}, session_factory=session_factory
    )
    strategies = load_strategies(1, session_factory=session_factory)
    assert len(strategies) == 1
    assert strategies[0]["conditions"] == [2]


def test_strategies_are_scoped_per_user(session_factory):
    save_strategy(1, {"strategy_name": "A", "conditions": []}, session_factory=session_factory)
    save_strategy(2, {"strategy_name": "B", "conditions": []}, session_factory=session_factory)
    assert [s["strategy_name"] for s in load_strategies(1, session_factory=session_factory)] == ["A"]
    assert [s["strategy_name"] for s in load_strategies(2, session_factory=session_factory)] == ["B"]
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_strategy_builder_storage.py -v`
Expected: FAIL（シグネチャ不一致）

- [ ] **Step 3: `strategy_builder/storage.py`を書き換える**

`ai-stock-investing-tutorial/app/strategy_builder/storage.py`（全面置き換え）:

```python
"""確定済み投資戦略（AI戦略ビルダー機能）をDBで永続化・読み込みするモジュール。"""

import json

from db.engine import SessionLocal
from db.models import Strategy


def load_strategies(user_id: int, session_factory=SessionLocal) -> list[dict]:
    """指定ユーザーの保存済み戦略一覧をDBから読み込む。1件も無ければ空リストを返す。"""
    with session_factory() as session:
        rows = (
            session.query(Strategy)
            .filter_by(user_id=user_id)
            .order_by(Strategy.id)
            .all()
        )
        return [json.loads(row.strategy_json) for row in rows]


def save_strategy(user_id: int, strategy: dict, session_factory=SessionLocal) -> None:
    """戦略を1件、保存済み一覧に追記する。同名（strategy_name）の戦略が既にあれば
    上書きする。"""
    name = strategy.get("strategy_name")
    with session_factory() as session:
        session.query(Strategy).filter_by(user_id=user_id, strategy_name=name).delete()
        session.add(
            Strategy(
                user_id=user_id,
                strategy_name=name,
                strategy_json=json.dumps(strategy, ensure_ascii=False),
            )
        )
        session.commit()
```

- [ ] **Step 4: テストを実行して通ることを確認する**

Run: `uv run pytest tests/test_strategy_builder_storage.py -v`
Expected: PASS（4件）

- [ ] **Step 5: Commit**

```bash
git add strategy_builder/storage.py tests/test_strategy_builder_storage.py
git commit -m "refactor: 保存済み戦略の永続化をJSONファイルからDBに変更"
```

---

### Task 5: `sector_analysis/display_settings.py`のDB化

**Files:**
- Modify: `ai-stock-investing-tutorial/app/sector_analysis/display_settings.py`（全面書き換え）
- Modify: `ai-stock-investing-tutorial/app/tests/test_sector_display_settings.py`（全面書き換え）

**Interfaces:**
- Consumes: `db.engine.SessionLocal`、`db.models.SectorDisplaySetting`（Task 2）
- Produces:
  - `sector_analysis.display_settings.DEFAULT_SECTOR_DISPLAY_SETTINGS`（変更なし）
  - `sector_analysis.display_settings._normalize(data: dict | None) -> dict[str, dict]`（新規、Task 7の移行スクリプトからも使う）
  - `sector_analysis.display_settings.load_sector_display_settings(user_id: int, session_factory=SessionLocal) -> dict[str, dict]`
  - `sector_analysis.display_settings.save_sector_display_settings(user_id: int, settings: dict[str, dict], session_factory=SessionLocal) -> None`

- [ ] **Step 1: 失敗するテストを書く**

`ai-stock-investing-tutorial/app/tests/test_sector_display_settings.py`（既存内容を置き換え）:

```python
import json

import pytest
from sqlalchemy.orm import sessionmaker

from db.engine import create_db_engine, init_db
from sector_analysis.display_settings import (
    DEFAULT_SECTOR_DISPLAY_SETTINGS,
    _normalize,
    load_sector_display_settings,
    save_sector_display_settings,
)


def test_normalize_none_returns_defaults():
    assert _normalize(None) == DEFAULT_SECTOR_DISPLAY_SETTINGS


def test_normalize_non_dict_returns_defaults():
    assert _normalize([1, 2, 3]) == DEFAULT_SECTOR_DISPLAY_SETTINGS


def test_normalize_legacy_flat_format_becomes_visible():
    data = {
        "heatmap": False,
        "pairs_table": False,
        "ai_comments": False,
        "network_diagram": True,
        "wavelet_analysis": False,
    }
    result = _normalize(data)
    assert result["visible"] == data
    assert result["order"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]
    assert result["height"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["height"]


def test_normalize_missing_keys_filled_with_defaults():
    data = {"visible": {"heatmap": False}, "order": {}, "height": {}}
    result = _normalize(data)
    assert result["visible"]["heatmap"] is False
    assert result["visible"]["pairs_table"] is True
    assert result["order"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]
    assert result["height"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["height"]


def test_normalize_unknown_keys_are_dropped():
    data = {
        "visible": {"heatmap": False, "some_future_key": True},
        "order": {},
        "height": {},
    }
    result = _normalize(data)
    assert "some_future_key" not in result["visible"]
    assert result["visible"]["heatmap"] is False


def test_normalize_non_bool_visible_value_falls_back_to_default():
    data = {"visible": {"heatmap": "yes"}, "order": {}, "height": {}}
    result = _normalize(data)
    assert result["visible"]["heatmap"] is True


def test_normalize_non_int_order_value_falls_back_to_default():
    data = {"visible": {}, "order": {"heatmap": "first"}, "height": {}}
    result = _normalize(data)
    assert result["order"]["heatmap"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]["heatmap"]


def test_normalize_bool_order_value_falls_back_to_default():
    # boolはPythonではintのサブクラスなので、明示的に弾かれることを確認する
    data = {"visible": {}, "order": {"heatmap": True}, "height": {}}
    result = _normalize(data)
    assert result["order"]["heatmap"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]["heatmap"]


def test_normalize_non_numeric_height_value_falls_back_to_default():
    data = {"visible": {}, "order": {}, "height": {"heatmap": "big"}}
    result = _normalize(data)
    assert result["height"]["heatmap"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["height"]["heatmap"]


def test_normalize_unknown_height_key_is_dropped():
    data = {"visible": {}, "order": {}, "height": {"pairs_table": 999}}
    result = _normalize(data)
    assert "pairs_table" not in result["height"]


@pytest.fixture
def session_factory(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    return sessionmaker(bind=engine)


def test_load_returns_defaults_when_no_row(session_factory):
    assert load_sector_display_settings(1, session_factory=session_factory) == (
        DEFAULT_SECTOR_DISPLAY_SETTINGS
    )


def test_save_then_load_roundtrip(session_factory):
    settings = {
        "visible": {
            "heatmap": False,
            "pairs_table": True,
            "ai_comments": False,
            "network_diagram": True,
            "wavelet_analysis": False,
        },
        "order": {
            "heatmap": 3,
            "pairs_table": 1,
            "ai_comments": 2,
            "network_diagram": 5,
            "wavelet_analysis": 4,
        },
        "height": {"heatmap": 600, "network_diagram": 350, "wavelet_analysis": 450},
    }
    save_sector_display_settings(1, settings, session_factory=session_factory)
    assert load_sector_display_settings(1, session_factory=session_factory) == settings


def test_save_overwrites_existing_settings(session_factory):
    settings_a = {
        "visible": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["visible"]),
        "order": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]),
        "height": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["height"]),
    }
    settings_b = json.loads(json.dumps(settings_a))
    settings_b["visible"]["heatmap"] = False

    save_sector_display_settings(1, settings_a, session_factory=session_factory)
    save_sector_display_settings(1, settings_b, session_factory=session_factory)
    assert load_sector_display_settings(1, session_factory=session_factory)["visible"]["heatmap"] is (
        False
    )


def test_settings_are_scoped_per_user(session_factory):
    settings_1 = {
        "visible": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["visible"]),
        "order": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]),
        "height": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["height"]),
    }
    save_sector_display_settings(1, settings_1, session_factory=session_factory)
    assert load_sector_display_settings(2, session_factory=session_factory) == (
        DEFAULT_SECTOR_DISPLAY_SETTINGS
    )
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_sector_display_settings.py -v`
Expected: FAIL（`_normalize`が存在しない／`load_sector_display_settings`のシグネチャ不一致）

- [ ] **Step 3: `sector_analysis/display_settings.py`を書き換える**

`ai-stock-investing-tutorial/app/sector_analysis/display_settings.py`（全面置き換え）:

```python
"""セクターローテーションタブの表示セクション設定（表示ON/OFF・表示順序・
チャート高さ）をDBで永続化・読み込みするモジュール。"""

import json

from db.engine import SessionLocal
from db.models import SectorDisplaySetting

_SECTION_KEYS = (
    "heatmap",
    "pairs_table",
    "ai_comments",
    "network_diagram",
    "wavelet_analysis",
)
_HEIGHT_KEYS = ("heatmap", "network_diagram", "wavelet_analysis")

DEFAULT_SECTOR_DISPLAY_SETTINGS: dict[str, dict] = {
    "visible": {key: True for key in _SECTION_KEYS},
    "order": {key: index + 1 for index, key in enumerate(_SECTION_KEYS)},
    "height": {"heatmap": 500, "network_diagram": 400, "wavelet_analysis": 400},
}


def _is_new_format(data: dict) -> bool:
    """新形式（トップレベルに"visible"辞書キーを持つ）かどうかを判定する。
    旧フラットbool形式（{"heatmap": true, ...}）にはこのキーが無い。"""
    return isinstance(data.get("visible"), dict)


def _normalize(data: dict | None) -> dict[str, dict]:
    """設定dictを検証し、欠落キー・型不正な値・未知のキーをデフォルト値で
    補う/無視した正規形を返す。dataがdictでない場合はデフォルト設定を返す。
    移行スクリプト（scripts/migrate_to_db.py、旧JSONファイルの読み込み）と
    load_sector_display_settingsの両方から使う共通ロジック。"""
    settings = {
        "visible": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["visible"]),
        "order": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]),
        "height": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["height"]),
    }
    if not isinstance(data, dict):
        return settings

    if not _is_new_format(data):
        for key in _SECTION_KEYS:
            if key in data and isinstance(data[key], bool):
                settings["visible"][key] = data[key]
        return settings

    visible_data = data.get("visible")
    if isinstance(visible_data, dict):
        for key in _SECTION_KEYS:
            value = visible_data.get(key)
            if isinstance(value, bool):
                settings["visible"][key] = value

    order_data = data.get("order")
    if isinstance(order_data, dict):
        for key in _SECTION_KEYS:
            value = order_data.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                settings["order"][key] = value

    height_data = data.get("height")
    if isinstance(height_data, dict):
        for key in _HEIGHT_KEYS:
            value = height_data.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                settings["height"][key] = value

    return settings


def load_sector_display_settings(user_id: int, session_factory=SessionLocal) -> dict[str, dict]:
    """指定ユーザーの表示設定をDBから読み込む。保存済みの設定が無ければ
    デフォルト設定を返す。"""
    with session_factory() as session:
        row = session.get(SectorDisplaySetting, user_id)
        if row is None:
            return _normalize(None)
        data = {
            "visible": json.loads(row.visible_json),
            "order": json.loads(row.order_json),
            "height": json.loads(row.height_json),
        }
        return _normalize(data)


def save_sector_display_settings(
    user_id: int, settings: dict[str, dict], session_factory=SessionLocal
) -> None:
    """指定ユーザーの表示設定をDBに保存する。既存の設定があれば上書きする。"""
    with session_factory() as session:
        row = session.get(SectorDisplaySetting, user_id)
        if row is None:
            row = SectorDisplaySetting(user_id=user_id)
            session.add(row)
        row.visible_json = json.dumps(settings["visible"], ensure_ascii=False)
        row.order_json = json.dumps(settings["order"], ensure_ascii=False)
        row.height_json = json.dumps(settings["height"], ensure_ascii=False)
        session.commit()
```

- [ ] **Step 4: テストを実行して通ることを確認する**

Run: `uv run pytest tests/test_sector_display_settings.py -v`
Expected: PASS（13件）

- [ ] **Step 5: Commit**

```bash
git add sector_analysis/display_settings.py tests/test_sector_display_settings.py
git commit -m "refactor: セクター表示設定の永続化をJSONファイルからDBに変更"
```

---

### Task 6: `app_tabs`配線（DEFAULT_USER_ID・呼び出し箇所更新・app.pyへのinit_db()追加）

**Files:**
- Modify: `ai-stock-investing-tutorial/app/app_tabs/shared.py:31-36`
- Modify: `ai-stock-investing-tutorial/app/app_tabs/portfolio_tab.py:20-28,39,120,127`
- Modify: `ai-stock-investing-tutorial/app/app_tabs/qa_tab.py:23-28,43`
- Modify: `ai-stock-investing-tutorial/app/app_tabs/ranking_tab.py:21-27,59,127`
- Modify: `ai-stock-investing-tutorial/app/app_tabs/strategy_builder_tab.py:31-37,41,142,198`
- Modify: `ai-stock-investing-tutorial/app/app_tabs/sector/tab.py:22,36,106`
- Modify: `ai-stock-investing-tutorial/app/app.py:31-33`（st.set_page_config直後）

**Interfaces:**
- Consumes: Task 3〜5で変更した`load_holdings`/`save_holdings`/`load_strategies`/`save_strategy`/`load_sector_display_settings`/`save_sector_display_settings`（すべて`user_id`第一引数）、`db.engine.engine`/`init_db`（Task 2）
- Produces: `app_tabs.shared.DEFAULT_USER_ID: int`（フェーズ3で認証済みユーザーIDに置き換えるまでの暫定値。`scripts/migrate_to_db.py`が作成する最初のユーザーのIDと一致させる）

このタスクは既存関数の呼び出し引数を機械的に置き換えるだけで、`app_tabs`配下にユニットテストは存在しない（既存の慣習どおり）。各編集後に全体テストスイートで回帰が無いことを確認する。

- [ ] **Step 1: `app_tabs/shared.py`の定数を置き換える**

`ai-stock-investing-tutorial/app/app_tabs/shared.py:31-36`、変更前:

```python
# 保有銘柄データやAPI取得結果のキャッシュを保存するディレクトリ構成
APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
HOLDINGS_PATH = DATA_DIR / "holdings.json"
SECTOR_DISPLAY_SETTINGS_PATH = DATA_DIR / "sector_display_settings.json"
CACHE_DIR = DATA_DIR / "cache"
```

変更後:

```python
# API取得結果のキャッシュを保存するディレクトリ構成
APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"

# フェーズ3（認証導入）で認証済みユーザーのIDに置き換えるまでの暫定値。
# scripts/migrate_to_db.pyが作成する最初のユーザーのIDと一致する。
DEFAULT_USER_ID = 1
```

- [ ] **Step 2: `app_tabs/portfolio_tab.py`を更新する**

`ai-stock-investing-tutorial/app/app_tabs/portfolio_tab.py:20-28`、変更前:

```python
from app_tabs.shared import (
    CACHE_DIR,
    HOLDINGS_PATH,
    cached_analyze_fundamentals,
    cached_fetch_japanese_name,
    cached_fetch_news,
    cached_fetch_price_history,
    handle_table_selection,
)
```

変更後:

```python
from app_tabs.shared import (
    CACHE_DIR,
    DEFAULT_USER_ID,
    cached_analyze_fundamentals,
    cached_fetch_japanese_name,
    cached_fetch_news,
    cached_fetch_price_history,
    handle_table_selection,
)
```

`portfolio_tab.py:39`、変更前: `st.session_state["holdings_rows"] = load_holdings(HOLDINGS_PATH)`
変更後: `st.session_state["holdings_rows"] = load_holdings(DEFAULT_USER_ID)`

`portfolio_tab.py:120`、変更前: `save_holdings(HOLDINGS_PATH, holdings)`
変更後: `save_holdings(DEFAULT_USER_ID, holdings)`

`portfolio_tab.py:127`、変更前: `save_holdings(HOLDINGS_PATH, holdings)`
変更後: `save_holdings(DEFAULT_USER_ID, holdings)`

- [ ] **Step 3: `app_tabs/qa_tab.py`を更新する**

`ai-stock-investing-tutorial/app/app_tabs/qa_tab.py:23-28`、変更前:

```python
from app_tabs.shared import (
    HOLDINGS_PATH,
    cached_analyze_fundamentals,
    cached_fetch_news,
    cached_fetch_price_history,
)
```

変更後:

```python
from app_tabs.shared import (
    DEFAULT_USER_ID,
    cached_analyze_fundamentals,
    cached_fetch_news,
    cached_fetch_price_history,
)
```

`qa_tab.py:43`、変更前: `holdings = load_holdings(HOLDINGS_PATH)`
変更後: `holdings = load_holdings(DEFAULT_USER_ID)`

- [ ] **Step 4: `app_tabs/ranking_tab.py`を更新する**

`ai-stock-investing-tutorial/app/app_tabs/ranking_tab.py:21-27`、変更前:

```python
from app_tabs.shared import (
    CACHE_DIR,
    HOLDINGS_PATH,
    cached_fetch_japanese_name,
    cached_fetch_price_history,
    handle_table_selection,
)
```

変更後:

```python
from app_tabs.shared import (
    CACHE_DIR,
    DEFAULT_USER_ID,
    cached_fetch_japanese_name,
    cached_fetch_price_history,
    handle_table_selection,
)
```

`ranking_tab.py:59`、変更前: `holdings = load_holdings(HOLDINGS_PATH)`
変更後: `holdings = load_holdings(DEFAULT_USER_ID)`

`ranking_tab.py:127`、変更前:

```python
        candidate_names = build_candidate_names(
            load_holdings(HOLDINGS_PATH), resolve_name=cached_fetch_japanese_name
        )
```

変更後:

```python
        candidate_names = build_candidate_names(
            load_holdings(DEFAULT_USER_ID), resolve_name=cached_fetch_japanese_name
        )
```

- [ ] **Step 5: `app_tabs/strategy_builder_tab.py`を更新する**

`ai-stock-investing-tutorial/app/app_tabs/strategy_builder_tab.py:31-37`、変更前:

```python
from app_tabs.shared import (
    CACHE_DIR,
    DATA_DIR,
    handle_table_selection,
    render_mermaid,
    run_or_load_sector_rotation,
)
```

変更後:

```python
from app_tabs.shared import (
    CACHE_DIR,
    DEFAULT_USER_ID,
    handle_table_selection,
    render_mermaid,
    run_or_load_sector_rotation,
)
```

`strategy_builder_tab.py:41`（`STRATEGIES_PATH = DATA_DIR / "strategies.json"`の行）を削除する。

`strategy_builder_tab.py:142`、変更前: `saved_strategies = load_strategies(STRATEGIES_PATH)`
変更後: `saved_strategies = load_strategies(DEFAULT_USER_ID)`

`strategy_builder_tab.py:198`、変更前: `save_strategy(STRATEGIES_PATH, pending)`
変更後: `save_strategy(DEFAULT_USER_ID, pending)`

- [ ] **Step 6: `app_tabs/sector/tab.py`を更新する**

`ai-stock-investing-tutorial/app/app_tabs/sector/tab.py:22`、変更前:

```python
from app_tabs.shared import SECTOR_DISPLAY_SETTINGS_PATH, run_or_load_sector_rotation
```

変更後:

```python
from app_tabs.shared import DEFAULT_USER_ID, run_or_load_sector_rotation
```

`sector/tab.py:36`、変更前: `display_settings = load_sector_display_settings(SECTOR_DISPLAY_SETTINGS_PATH)`
変更後: `display_settings = load_sector_display_settings(DEFAULT_USER_ID)`

`sector/tab.py:106`、変更前: `save_sector_display_settings(SECTOR_DISPLAY_SETTINGS_PATH, new_display_settings)`
変更後: `save_sector_display_settings(DEFAULT_USER_ID, new_display_settings)`

- [ ] **Step 7: `app.py`にDB初期化を追加する**

`ai-stock-investing-tutorial/app/app.py`、`from data_api.llm_client import check_claude_cli_available`の行の直後に追加:

```python
from db.engine import engine, init_db
```

`st.set_page_config(page_title="株投資リサーチアプリ", layout="wide")`の行の直後に追加:

```python
init_db(engine)
```

- [ ] **Step 8: 全体テストスイートを実行して回帰が無いことを確認する**

Run: `uv run pytest -v`
Expected: PASS（全件。`app_tabs`配下は元々ユニットテスト対象外のため、このタスクで新規に壊れるテストは無いはず）

- [ ] **Step 9: Commit**

```bash
git add app_tabs/shared.py app_tabs/portfolio_tab.py app_tabs/qa_tab.py app_tabs/ranking_tab.py app_tabs/strategy_builder_tab.py app_tabs/sector/tab.py app.py
git commit -m "refactor: app_tabsの永続化呼び出しをDEFAULT_USER_ID経由のDBアクセスに配線"
```

---

### Task 7: 既存JSONデータの移行スクリプト

**Files:**
- Create: `ai-stock-investing-tutorial/app/scripts/__init__.py`
- Create: `ai-stock-investing-tutorial/app/scripts/migrate_to_db.py`
- Test: `ai-stock-investing-tutorial/app/tests/test_migrate_to_db.py`

**Interfaces:**
- Consumes: `db.engine.SessionLocal`/`engine`/`init_db`/`DATA_DIR`（Task 2）、`db.models.User`/`Holding`/`Strategy`/`SectorDisplaySetting`（Task 2）、`sector_analysis.display_settings._normalize`（Task 5）
- Produces:
  - `scripts.migrate_to_db.create_admin_user(session, username, password, email) -> User`
  - `scripts.migrate_to_db.migrate_holdings(session, user_id, path=HOLDINGS_PATH) -> int`
  - `scripts.migrate_to_db.migrate_strategies(session, user_id, path=STRATEGIES_PATH) -> int`
  - `scripts.migrate_to_db.migrate_sector_display_settings(session, user_id, path=SECTOR_DISPLAY_SETTINGS_PATH) -> bool`
  - `scripts.migrate_to_db.main() -> None`（対話的CLIエントリーポイント、テスト対象外）

- [ ] **Step 1: `scripts/__init__.py`を作成する**

`ai-stock-investing-tutorial/app/scripts/__init__.py`: 空ファイル

- [ ] **Step 2: 失敗するテストを書く**

`ai-stock-investing-tutorial/app/tests/test_migrate_to_db.py`:

```python
import json

import pytest
from sqlalchemy.orm import sessionmaker

from db.engine import create_db_engine, init_db
from db.models import Holding, SectorDisplaySetting, Strategy, User
from scripts.migrate_to_db import (
    create_admin_user,
    migrate_holdings,
    migrate_sector_display_settings,
    migrate_strategies,
)


@pytest.fixture
def session_factory(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    return sessionmaker(bind=engine)


def test_create_admin_user_hashes_password(session_factory):
    with session_factory() as session:
        user = create_admin_user(session, "taro", "s3cret", "taro@example.com")
        assert user.id is not None
        assert user.username == "taro"
        assert user.email == "taro@example.com"
        assert user.hashed_password != "s3cret"

        stored = session.query(User).filter_by(username="taro").one()
        assert stored.hashed_password == user.hashed_password


def test_migrate_holdings_inserts_rows_and_renames_file(tmp_path, session_factory):
    path = tmp_path / "holdings.json"
    path.write_text(
        json.dumps([{"ticker": "7203.T", "shares": 100, "cost": 2500.0}]),
        encoding="utf-8",
    )
    with session_factory() as session:
        user = create_admin_user(session, "taro", "s3cret", None)
        count = migrate_holdings(session, user.id, path=path)

        assert count == 1
        assert session.query(Holding).filter_by(user_id=user.id).count() == 1
    assert not path.exists()
    assert (tmp_path / "holdings.json.migrated").exists()


def test_migrate_holdings_missing_file_does_nothing(tmp_path, session_factory):
    path = tmp_path / "holdings.json"
    with session_factory() as session:
        user = create_admin_user(session, "taro", "s3cret", None)
        count = migrate_holdings(session, user.id, path=path)
        assert count == 0
        assert session.query(Holding).count() == 0
    assert not path.exists()


def test_migrate_strategies_inserts_rows_and_renames_file(tmp_path, session_factory):
    path = tmp_path / "strategies.json"
    path.write_text(
        json.dumps([{"strategy_name": "割安成長株", "conditions": []}]),
        encoding="utf-8",
    )
    with session_factory() as session:
        user = create_admin_user(session, "taro", "s3cret", None)
        count = migrate_strategies(session, user.id, path=path)

        assert count == 1
        row = session.query(Strategy).filter_by(user_id=user.id).one()
        assert json.loads(row.strategy_json) == {
            "strategy_name": "割安成長株",
            "conditions": [],
        }
    assert (tmp_path / "strategies.json.migrated").exists()


def test_migrate_sector_display_settings_normalizes_legacy_format(tmp_path, session_factory):
    path = tmp_path / "sector_display_settings.json"
    path.write_text(json.dumps({"heatmap": False, "pairs_table": True}), encoding="utf-8")
    with session_factory() as session:
        user = create_admin_user(session, "taro", "s3cret", None)
        migrated = migrate_sector_display_settings(session, user.id, path=path)

        assert migrated is True
        row = session.query(SectorDisplaySetting).filter_by(user_id=user.id).one()
        assert json.loads(row.visible_json)["heatmap"] is False
    assert (tmp_path / "sector_display_settings.json.migrated").exists()


def test_migrate_sector_display_settings_missing_file_returns_false(tmp_path, session_factory):
    path = tmp_path / "sector_display_settings.json"
    with session_factory() as session:
        user = create_admin_user(session, "taro", "s3cret", None)
        migrated = migrate_sector_display_settings(session, user.id, path=path)
        assert migrated is False
        assert session.query(SectorDisplaySetting).count() == 0
```

- [ ] **Step 3: テストが失敗することを確認する**

Run: `uv run pytest tests/test_migrate_to_db.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'scripts.migrate_to_db'`）

- [ ] **Step 4: `scripts/migrate_to_db.py`を実装する**

`ai-stock-investing-tutorial/app/scripts/migrate_to_db.py`:

```python
"""既存のJSON永続化データ（holdings.json・strategies.json・
sector_display_settings.json）をDBへ一回限り移行するスクリプト。

実行方法（ai-stock-investing-tutorial/app ディレクトリで）:
    uv run python -m scripts.migrate_to_db
"""

import getpass
import json
from pathlib import Path

import bcrypt
from sqlalchemy.orm import Session

from db.engine import DATA_DIR, SessionLocal, engine, init_db
from db.models import Holding, SectorDisplaySetting, Strategy, User
from sector_analysis.display_settings import _normalize

HOLDINGS_PATH = DATA_DIR / "holdings.json"
STRATEGIES_PATH = DATA_DIR / "strategies.json"
SECTOR_DISPLAY_SETTINGS_PATH = DATA_DIR / "sector_display_settings.json"


def _load_json(path: Path):
    """JSONファイルを読み込む。存在しない、または壊れている場合はNoneを返す。"""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _mark_migrated(path: Path) -> None:
    path.rename(path.with_suffix(".json.migrated"))


def create_admin_user(session: Session, username: str, password: str, email: str | None) -> User:
    """管理者（最初の）ユーザーを作成する。パスワードはbcryptでハッシュ化して保存する。"""
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    user = User(username=username, email=email or None, hashed_password=hashed)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def migrate_holdings(session: Session, user_id: int, path: Path = HOLDINGS_PATH) -> int:
    """holdings.jsonの内容を指定ユーザーの保有銘柄としてDBへ移行し、移行元ファイルを
    リネームする。移行した件数を返す。ファイルが無い/壊れている場合は0件のまま
    何もしない。"""
    data = _load_json(path)
    holdings = data if isinstance(data, list) else []
    for holding in holdings:
        ticker = holding.get("ticker")
        if not ticker:
            continue
        session.add(
            Holding(
                user_id=user_id,
                ticker=ticker,
                shares=holding.get("shares", 0),
                cost=holding.get("cost", 0.0),
            )
        )
    session.commit()
    if holdings:
        _mark_migrated(path)
    return len(holdings)


def migrate_strategies(session: Session, user_id: int, path: Path = STRATEGIES_PATH) -> int:
    """strategies.jsonの内容を指定ユーザーの保存済み戦略としてDBへ移行し、移行元
    ファイルをリネームする。移行した件数を返す。"""
    data = _load_json(path)
    strategies = data if isinstance(data, list) else []
    for strategy in strategies:
        name = strategy.get("strategy_name")
        if not name:
            continue
        session.add(
            Strategy(
                user_id=user_id,
                strategy_name=name,
                strategy_json=json.dumps(strategy, ensure_ascii=False),
            )
        )
    session.commit()
    if strategies:
        _mark_migrated(path)
    return len(strategies)


def migrate_sector_display_settings(
    session: Session, user_id: int, path: Path = SECTOR_DISPLAY_SETTINGS_PATH
) -> bool:
    """sector_display_settings.jsonの内容を、既存の読み込みロジックと同じ検証
    （_normalize）を通した上で指定ユーザーの表示設定としてDBへ移行し、移行元
    ファイルをリネームする。ファイルが無ければFalseを返し何もしない。"""
    data = _load_json(path)
    if data is None:
        return False
    normalized = _normalize(data)
    session.add(
        SectorDisplaySetting(
            user_id=user_id,
            visible_json=json.dumps(normalized["visible"], ensure_ascii=False),
            order_json=json.dumps(normalized["order"], ensure_ascii=False),
            height_json=json.dumps(normalized["height"], ensure_ascii=False),
        )
    )
    session.commit()
    _mark_migrated(path)
    return True


def main() -> None:
    init_db(engine)
    with SessionLocal() as session:
        username = input("管理者ユーザー名: ").strip()
        password = getpass.getpass("パスワード: ")
        email = input("メールアドレス（任意、Enterでスキップ）: ").strip()

        user = create_admin_user(session, username, password, email)
        print(f"ユーザー '{user.username}' (id={user.id}) を作成しました。")

        n_holdings = migrate_holdings(session, user.id)
        print(f"保有銘柄 {n_holdings} 件を移行しました。")

        n_strategies = migrate_strategies(session, user.id)
        print(f"保存済み戦略 {n_strategies} 件を移行しました。")

        migrated_settings = migrate_sector_display_settings(session, user.id)
        print(
            "セクター表示設定を移行しました。"
            if migrated_settings
            else "セクター表示設定は見つかりませんでした。"
        )


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: テストを実行して通ることを確認する**

Run: `uv run pytest tests/test_migrate_to_db.py -v`
Expected: PASS（6件）

- [ ] **Step 6: Commit**

```bash
git add scripts/__init__.py scripts/migrate_to_db.py tests/test_migrate_to_db.py
git commit -m "feat: 既存JSONデータをDBへ移行するスクリプトを追加"
```

---

### Task 8: 全体テスト実行・移行スクリプト実行・手動動作確認

このタスクは新規コードを書かず、フェーズ1全体が実際のデータで動くことを確認する。

**Files:** なし（確認のみ）

- [ ] **Step 1: 全体テストスイートを実行する**

Run: `uv run pytest -v`（`ai-stock-investing-tutorial/app`ディレクトリで）
Expected: 全件PASS

- [ ] **Step 2: 実データ（`data/holdings.json`等）が存在する場合はバックアップする**

```bash
cp -r data data.backup-before-db-migration
```

- [ ] **Step 3: 移行スクリプトを実行する**

`ai-stock-investing-tutorial/app`ディレクトリで:

```bash
uv run python -m scripts.migrate_to_db
```

プロンプトに従い、管理者ユーザー名・パスワードを入力する（メールアドレスは任意でEnterでスキップ可）。「ユーザー '...' (id=1) を作成しました。」と表示されることを確認する（`id=1`であること＝`app_tabs/shared.py`の`DEFAULT_USER_ID = 1`と一致することが重要）。

- [ ] **Step 4: `data/app.db`が作成されたことを確認する**

Run: `ls data/app.db`
Expected: ファイルが存在する

- [ ] **Step 5: アプリを起動し、手動で動作確認する**

```bash
uv run python -m streamlit run app.py
```

ブラウザで以下を確認する:
- 「ポートフォリオ」タブ: 移行前に登録していた保有銘柄が表示される。銘柄を1件追加→保存→ページをリロードしても保持されている
- 「AI戦略ビルダー」タブ: 移行前に保存していた戦略が「保存済み戦略」の選択肢に表示される
- 「セクターローテーション」タブ: 「表示設定」の内容（表示ON/OFF・順序）が移行前の設定を反映している。設定を変更して保存し、ページをリロードしても保持されている
- ターミナルのログにエラーが出ていないこと

- [ ] **Step 6: 問題なければバックアップを削除する**

```bash
rm -rf data.backup-before-db-migration
```

（手動確認で問題が見つかった場合はバックアップから`data/*.json`を復元し、コミット履歴を`git log`で確認して原因を調査する。このステップはコミットを伴わない）
