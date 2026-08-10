# 管理者機能フェーズA（認可基盤・戦略管理） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `User.is_admin`列を追加し、管理者アカウントにのみ表示される「管理者」タブを`app.py`に統合する。同フェーズで、最も要望の強い「全ユーザーの保存済み戦略の一覧・編集・削除」を実装する（`docs/superpowers/specs/2026-08-10-admin-crud-design.md`のフェーズA）。

**Architecture:** `db/engine.py`の`init_db()`に既存の`_ensure_user_name_columns`と同じ軽量マイグレーション方式で`is_admin`列追加を組み込み、DB内にadminが1人もいなければ最古のユーザーへ自動付与する。`app.py`はログイン成功後に`is_admin`を`st.session_state`へ設定し、`st.tabs`のラベルリストを動的に組み立てて8つ目の「管理者」タブを条件表示する。管理者向けのDB操作関数は既存の`user_id`引数を取るCRUDパターンを踏襲し、ユーザーを横断する分だけ`User`テーブルとJOINする。

**Tech Stack:** 既存のSQLAlchemy 2.0 + SQLite（フェーズ1〜3と同じ`data/app.db`）。新規依存追加は無し。

## Global Constraints

- Python >=3.14、パッケージ管理は`uv`（`ai-stock-investing-tutorial/app/pyproject.toml`）
- テストは`uv run pytest -v`（`app/`ディレクトリで実行）
- DBを使うテストは`tmp_path`上のファイルDB（`sqlite:///{tmp_path}/test.db`）を使う
- DB操作を行う関数は`session_factory`引数（デフォルトは本番用`db.engine.SessionLocal`）を受け取り、テストでは注入する（フェーズ1〜3と同じDIパターン）
- `app_tabs`配下のUI結線部分はユニットテスト対象外（既存の慣習どおり）
- リポジトリはmasterへの直接コミット運用（フィーチャーブランチ・worktreeは使わない）
- 実運用中の`data/app.db`は既に存在する（`users`テーブルに`is_admin`列が無い状態）。`init_db()`の軽量マイグレーションで起動時に自動的に追従させる

---

### Task 1: `User.is_admin`列の追加・既存DBへの自動列追加・最古ユーザーへの自動付与

**Files:**
- Modify: `ai-stock-investing-tutorial/app/db/models.py`
- Modify: `ai-stock-investing-tutorial/app/db/engine.py`
- Modify: `ai-stock-investing-tutorial/app/tests/test_db_engine.py`

**Interfaces:**
- Produces:
  - `db.models.User.is_admin: Mapped[bool]`（デフォルト`False`）
  - `db.engine.init_db(engine)`は`is_admin`列を（既存DBなら`ALTER TABLE`で、新規DBなら`create_all()`で）用意した上で、DB内に`is_admin=True`のユーザーが1人もいなければ`MIN(id)`のユーザーへ自動付与する

- [ ] **Step 1: 失敗するテストを書く**

`ai-stock-investing-tutorial/app/tests/test_db_engine.py`の末尾に追加:

```python
def test_init_db_adds_is_admin_column_to_existing_table(tmp_path):
    from sqlalchemy import text

    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    # is_admin列追加前のusersテーブルを模して作成する
    with engine.connect() as connection:
        connection.execute(
            text(
                "CREATE TABLE users ("
                "id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, "
                "email TEXT UNIQUE, hashed_password TEXT NOT NULL, created_at DATETIME)"
            )
        )
        connection.commit()

    init_db(engine)

    with engine.connect() as connection:
        columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(users)")).fetchall()
        }
    assert "is_admin" in columns


def test_init_db_grants_admin_to_first_user_when_no_admin_exists(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(User(username="alice", hashed_password="h"))
        session.add(User(username="bob", hashed_password="h"))
        session.commit()

    # init_db()の再呼び出し（実際にはapp.py起動のたびに呼ばれる）で
    # 最初に作成されたユーザーに管理者権限が自動付与される
    init_db(engine)

    with session_factory() as session:
        alice = session.query(User).filter_by(username="alice").one()
        bob = session.query(User).filter_by(username="bob").one()
        assert alice.is_admin is True
        assert bob.is_admin is False


def test_init_db_does_not_override_existing_admin_assignment(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(User(username="alice", hashed_password="h", is_admin=False))
        session.add(User(username="bob", hashed_password="h", is_admin=True))
        session.commit()

    init_db(engine)

    with session_factory() as session:
        alice = session.query(User).filter_by(username="alice").one()
        assert alice.is_admin is False  # 既にbobがadminなので上書きされない
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_db_engine.py -v -k "is_admin or admin_assignment or grants_admin"`
Expected: FAIL（`User.__init__`が`is_admin`を受け付けない、または`is_admin`列が追加されない）

- [ ] **Step 3: `db/models.py`に列を追加する**

`ai-stock-investing-tutorial/app/db/models.py`の`User`クラス、変更前:

```python
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(unique=True, nullable=True)
    hashed_password: Mapped[str] = mapped_column(nullable=False)
    first_name: Mapped[str | None] = mapped_column(nullable=True)
    last_name: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(default=_utcnow)
```

変更後:

```python
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
```

- [ ] **Step 4: `db/engine.py`に列追加・自動付与処理を実装する**

`ai-stock-investing-tutorial/app/db/engine.py`の`init_db`関数、変更前:

```python
def init_db(engine: Engine) -> None:
    """未作成のテーブルのみ作成する（既存テーブルには影響しない）。加えて、既存の
    usersテーブルにfirst_name/last_name列が無ければALTER TABLEで追加する
    （フェーズ3で追加した列。Alembic等の本格的なマイグレーションツールは使わない
    方針のため、この程度の単純な追加列はここで直接吸収する。新規作成時は
    create_all()が最初から両方の列を含むテーブルを作るため対象外）。"""
    Base.metadata.create_all(engine)
    _ensure_user_name_columns(engine)
```

変更後:

```python
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
```

- [ ] **Step 5: テストを実行して通ることを確認する**

Run: `uv run pytest tests/test_db_engine.py -v`
Expected: PASS（全件）

- [ ] **Step 6: 全体テストスイートを実行して回帰が無いことを確認する**

Run: `uv run pytest -v`
Expected: PASS（全件）

- [ ] **Step 7: Commit**

```bash
git add db/models.py db/engine.py tests/test_db_engine.py
git commit -m "feat: Userにis_admin列を追加し、最初のユーザーへ自動的に管理者権限を付与する"
```

---

### Task 2: `auth.get_is_admin`

**Files:**
- Modify: `ai-stock-investing-tutorial/app/auth.py`
- Modify: `ai-stock-investing-tutorial/app/tests/test_auth.py`

**Interfaces:**
- Produces: `auth.get_is_admin(username: str, session_factory=SessionLocal) -> bool`

- [ ] **Step 1: 失敗するテストを書く**

`ai-stock-investing-tutorial/app/tests/test_auth.py`の末尾に追加（`User`は既にimport済み。`build_credentials`等のimportに`get_is_admin`を追加する）:

```python
def test_get_is_admin_returns_true_for_admin_user(session_factory):
    with session_factory() as session:
        session.add(User(username="admin", hashed_password="h", is_admin=True))
        session.commit()

    assert get_is_admin("admin", session_factory=session_factory) is True


def test_get_is_admin_returns_false_for_non_admin_user(session_factory):
    with session_factory() as session:
        session.add(User(username="taro", hashed_password="h", is_admin=False))
        session.commit()

    assert get_is_admin("taro", session_factory=session_factory) is False


def test_get_is_admin_returns_false_for_unknown_username(session_factory):
    assert get_is_admin("nobody", session_factory=session_factory) is False
```

`test_auth.py`冒頭のimportを変更前:

```python
from auth import build_credentials, get_user_id, persist_new_user, persist_password_update
```

変更後:

```python
from auth import build_credentials, get_is_admin, get_user_id, persist_new_user, persist_password_update
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_auth.py -v -k "is_admin"`
Expected: FAIL（`ImportError: cannot import name 'get_is_admin'`）

- [ ] **Step 3: `auth.py`に関数を追加する**

`ai-stock-investing-tutorial/app/auth.py`の`get_user_id`関数の直後に追加:

```python
def get_is_admin(username: str, session_factory=SessionLocal) -> bool:
    """ユーザー名から管理者権限の有無を引き当てる。ユーザーが存在しなければ
    Falseを返す。"""
    with session_factory() as session:
        user = session.query(User).filter_by(username=username).first()
        return bool(user.is_admin) if user else False
```

- [ ] **Step 4: テストを実行して通ることを確認する**

Run: `uv run pytest tests/test_auth.py -v`
Expected: PASS（全件）

- [ ] **Step 5: Commit**

```bash
git add auth.py tests/test_auth.py
git commit -m "feat: authにget_is_adminを追加"
```

---

### Task 3: `strategy_builder/storage.py`への管理者向け関数の追加

**Files:**
- Modify: `ai-stock-investing-tutorial/app/strategy_builder/storage.py`
- Modify: `ai-stock-investing-tutorial/app/tests/test_strategy_builder_storage.py`

**Interfaces:**
- Consumes: `db.models.User`
- Produces:
  - `strategy_builder.storage.load_all_strategies(session_factory=SessionLocal) -> list[dict]` — 各要素は`{"id", "user_id", "username", "strategy_name", "strategy_json"（パース済みdict）, "created_at"}`
  - `strategy_builder.storage.delete_strategy_by_id(strategy_id: int, session_factory=SessionLocal) -> None`
  - `strategy_builder.storage.update_strategy_json_by_id(strategy_id: int, strategy_json_str: str, session_factory=SessionLocal) -> None` — 不正なJSONの場合は`json.JSONDecodeError`をそのまま送出する

- [ ] **Step 1: 失敗するテストを書く**

`ai-stock-investing-tutorial/app/tests/test_strategy_builder_storage.py`冒頭のimportを変更前:

```python
import pytest
from sqlalchemy.orm import sessionmaker

from db.engine import create_db_engine, init_db
from strategy_builder.storage import load_strategies, save_strategy
```

変更後:

```python
import json

import pytest
from sqlalchemy.orm import sessionmaker

from db.engine import create_db_engine, init_db
from db.models import User
from strategy_builder.storage import (
    delete_strategy_by_id,
    load_all_strategies,
    load_strategies,
    save_strategy,
    update_strategy_json_by_id,
)
```

ファイル末尾に追加:

```python
def test_load_all_strategies_includes_username_and_parsed_json(session_factory):
    with session_factory() as session:
        user = User(username="taro", hashed_password="h")
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = user.id

    save_strategy(
        user_id, {"strategy_name": "A", "conditions": []}, session_factory=session_factory
    )

    strategies = load_all_strategies(session_factory=session_factory)
    assert len(strategies) == 1
    assert strategies[0]["username"] == "taro"
    assert strategies[0]["strategy_name"] == "A"
    assert strategies[0]["strategy_json"] == {"strategy_name": "A", "conditions": []}


def test_load_all_strategies_spans_multiple_users(session_factory):
    with session_factory() as session:
        user1 = User(username="taro", hashed_password="h")
        user2 = User(username="hanako", hashed_password="h")
        session.add(user1)
        session.add(user2)
        session.commit()
        session.refresh(user1)
        session.refresh(user2)
        user1_id, user2_id = user1.id, user2.id

    save_strategy(
        user1_id, {"strategy_name": "A", "conditions": []}, session_factory=session_factory
    )
    save_strategy(
        user2_id, {"strategy_name": "B", "conditions": []}, session_factory=session_factory
    )

    strategies = load_all_strategies(session_factory=session_factory)
    usernames = sorted(s["username"] for s in strategies)
    assert usernames == ["hanako", "taro"]


def test_delete_strategy_by_id_removes_only_target_row(session_factory):
    with session_factory() as session:
        user = User(username="taro", hashed_password="h")
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = user.id

    save_strategy(
        user_id, {"strategy_name": "A", "conditions": []}, session_factory=session_factory
    )
    save_strategy(
        user_id, {"strategy_name": "B", "conditions": []}, session_factory=session_factory
    )
    strategies = load_all_strategies(session_factory=session_factory)
    target_id = next(s["id"] for s in strategies if s["strategy_name"] == "A")

    delete_strategy_by_id(target_id, session_factory=session_factory)

    remaining = load_all_strategies(session_factory=session_factory)
    assert [s["strategy_name"] for s in remaining] == ["B"]


def test_update_strategy_json_by_id_updates_content_and_syncs_name(session_factory):
    with session_factory() as session:
        user = User(username="taro", hashed_password="h")
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = user.id

    save_strategy(
        user_id, {"strategy_name": "A", "conditions": []}, session_factory=session_factory
    )
    target_id = load_all_strategies(session_factory=session_factory)[0]["id"]

    update_strategy_json_by_id(
        target_id,
        json.dumps({"strategy_name": "A改", "conditions": [{"field": "per"}]}),
        session_factory=session_factory,
    )

    updated = load_all_strategies(session_factory=session_factory)[0]
    assert updated["strategy_name"] == "A改"
    assert updated["strategy_json"]["conditions"] == [{"field": "per"}]


def test_update_strategy_json_by_id_raises_on_invalid_json(session_factory):
    with session_factory() as session:
        user = User(username="taro", hashed_password="h")
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = user.id

    save_strategy(
        user_id, {"strategy_name": "A", "conditions": []}, session_factory=session_factory
    )
    target_id = load_all_strategies(session_factory=session_factory)[0]["id"]

    with pytest.raises(json.JSONDecodeError):
        update_strategy_json_by_id(target_id, "not valid json", session_factory=session_factory)
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_strategy_builder_storage.py -v -k "load_all_strategies or delete_strategy_by_id or update_strategy_json_by_id"`
Expected: FAIL（`ImportError: cannot import name 'load_all_strategies'`）

- [ ] **Step 3: `strategy_builder/storage.py`に関数を追加する**

`ai-stock-investing-tutorial/app/strategy_builder/storage.py`冒頭のimportを変更前:

```python
import json

from db.engine import SessionLocal
from db.models import Strategy
```

変更後:

```python
import json

from db.engine import SessionLocal
from db.models import Strategy, User
```

ファイル末尾に追加:

```python
def load_all_strategies(session_factory=SessionLocal) -> list[dict]:
    """全ユーザーの保存済み戦略一覧を、紐づくユーザー名付きでDBから読み込む
    （管理者向け）。strategy_jsonはパース済みdictとして含める。"""
    with session_factory() as session:
        rows = (
            session.query(Strategy, User.username)
            .join(User, Strategy.user_id == User.id)
            .order_by(Strategy.id)
            .all()
        )
        return [
            {
                "id": strategy.id,
                "user_id": strategy.user_id,
                "username": username,
                "strategy_name": strategy.strategy_name,
                "strategy_json": json.loads(strategy.strategy_json),
                "created_at": strategy.created_at,
            }
            for strategy, username in rows
        ]


def delete_strategy_by_id(strategy_id: int, session_factory=SessionLocal) -> None:
    """指定したIDの戦略を削除する（管理者向け、ユーザーを問わない）。"""
    with session_factory() as session:
        session.query(Strategy).filter_by(id=strategy_id).delete()
        session.commit()


def update_strategy_json_by_id(
    strategy_id: int, strategy_json_str: str, session_factory=SessionLocal
) -> None:
    """指定したIDの戦略のstrategy_jsonを更新する（管理者向け）。
    strategy_json_strが不正なJSONの場合はjson.JSONDecodeErrorをそのまま送出する。
    パース結果にstrategy_nameキーがあればstrategy_name列も同期する。"""
    parsed = json.loads(strategy_json_str)
    with session_factory() as session:
        strategy = session.query(Strategy).filter_by(id=strategy_id).first()
        strategy.strategy_json = strategy_json_str
        if "strategy_name" in parsed:
            strategy.strategy_name = parsed["strategy_name"]
        session.commit()
```

- [ ] **Step 4: テストを実行して通ることを確認する**

Run: `uv run pytest tests/test_strategy_builder_storage.py -v`
Expected: PASS（全件）

- [ ] **Step 5: Commit**

```bash
git add strategy_builder/storage.py tests/test_strategy_builder_storage.py
git commit -m "feat: 全ユーザーの戦略を横断管理する関数（load_all_strategies/delete_strategy_by_id/update_strategy_json_by_id）を追加"
```

---

### Task 4: 管理者タブの新設・`app.py`への統合

**Files:**
- Create: `ai-stock-investing-tutorial/app/app_tabs/admin_tab.py`
- Modify: `ai-stock-investing-tutorial/app/app.py`

**Interfaces:**
- Consumes: `auth.get_is_admin`（Task 2）、`strategy_builder.storage.load_all_strategies`/`delete_strategy_by_id`/`update_strategy_json_by_id`（Task 3）
- Produces: `app_tabs.admin_tab.render_admin_tab() -> None`

このタスクはUIウィジェットの結線でありユニットテスト対象外（既存の`app_tabs`の慣習どおり）。Step 4で手動起動して確認する。

- [ ] **Step 1: `app_tabs/admin_tab.py`を作成する**

`ai-stock-investing-tutorial/app/app_tabs/admin_tab.py`:

```python
"""管理者タブ: is_admin権限を持つユーザーのみに表示される管理機能。
フェーズAでは全ユーザーの保存済み戦略の一覧・編集・削除のみを提供する
（ユーザー管理・市場データ管理は後続フェーズで追加）。
"""

import json
import logging

import pandas as pd
import streamlit as st

from strategy_builder.storage import (
    delete_strategy_by_id,
    load_all_strategies,
    update_strategy_json_by_id,
)

logger = logging.getLogger(__name__)


def render_admin_tab() -> None:
    logger.info("管理者タブを表示")
    st.header("管理者")
    _render_strategy_management()


def _render_strategy_management() -> None:
    st.subheader("全ユーザー戦略管理")
    strategies = load_all_strategies()
    if not strategies:
        st.caption("保存済み戦略はまだありません。")
        return

    display_df = pd.DataFrame(
        [
            {
                "ユーザー": s["username"],
                "戦略名": s["strategy_name"],
                "作成日時": s["created_at"],
            }
            for s in strategies
        ]
    )
    st.caption("行をクリックすると内容を編集できます。")
    event = st.dataframe(
        display_df,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="admin_strategy_table",
    )
    selected_idx = event.selection.rows[0] if event.selection.rows else None
    if selected_idx is None:
        return

    selected = strategies[selected_idx]
    st.caption(f"選択中: {selected['username']} / {selected['strategy_name']}")
    json_text = st.text_area(
        "strategy_json",
        value=json.dumps(selected["strategy_json"], ensure_ascii=False, indent=2),
        height=300,
        key=f"admin_strategy_json_{selected['id']}",
    )
    save_col, delete_col = st.columns(2)
    with save_col:
        if st.button("保存", key=f"admin_strategy_save_{selected['id']}"):
            try:
                update_strategy_json_by_id(selected["id"], json_text)
                st.success("更新しました。")
                st.rerun()
            except json.JSONDecodeError as exc:
                st.error(f"JSONの形式が不正です: {exc}")
    with delete_col:
        if st.button("削除", key=f"admin_strategy_delete_{selected['id']}"):
            delete_strategy_by_id(selected["id"])
            st.success("削除しました。")
            st.rerun()
```

- [ ] **Step 2: `app.py`にimportを追加する**

`ai-stock-investing-tutorial/app/app.py`、変更前:

```python
from auth import build_credentials, get_user_id, persist_new_user, persist_password_update
from common.disclaimer import DISCLAIMER_NOTICE
from common.logging_config import setup_logging
from data_api.llm_client import check_claude_cli_available
from db.engine import engine, init_db

from app_tabs.backtest_tab import render_backtest_tab
```

変更後:

```python
from auth import build_credentials, get_is_admin, get_user_id, persist_new_user, persist_password_update
from common.disclaimer import DISCLAIMER_NOTICE
from common.logging_config import setup_logging
from data_api.llm_client import check_claude_cli_available
from db.engine import engine, init_db

from app_tabs.admin_tab import render_admin_tab
from app_tabs.backtest_tab import render_backtest_tab
```

- [ ] **Step 3: ログイン成功後に`is_admin`を`session_state`へ設定する**

`ai-stock-investing-tutorial/app/app.py`、変更前:

```python
st.session_state["user_id"] = get_user_id(st.session_state["username"])

authenticator.logout(location="sidebar")
```

変更後:

```python
st.session_state["user_id"] = get_user_id(st.session_state["username"])
st.session_state["is_admin"] = get_is_admin(st.session_state["username"])

authenticator.logout(location="sidebar")
```

- [ ] **Step 4: 管理者にのみ8つ目のタブを表示するよう変更する**

`ai-stock-investing-tutorial/app/app.py`、変更前:

```python
# 7つの主要機能をタブとして構成する
(
    tab_portfolio,
    tab_screening,
    tab_backtest,
    tab_ranking,
    tab_sector,
    tab_strategy_builder,
    tab_qa,
) = st.tabs(
    [
        "ポートフォリオ",
        "スクリーニング",
        "バックテスト",
        "一括バックテスト",
        "セクターローテーション",
        "AI戦略ビルダー",
        "AI質問箱",
    ]
)

with tab_portfolio:
    render_portfolio_tab()

with tab_screening:
    render_screening_tab()

with tab_backtest:
    render_backtest_tab()

with tab_ranking:
    render_ranking_tab()

with tab_sector:
    render_sector_tab()

with tab_strategy_builder:
    render_strategy_builder_tab()

with tab_qa:
    render_qa_tab()
```

変更後:

```python
# 7つの主要機能に加え、管理者には8つ目の「管理者」タブを表示する
tab_labels = [
    "ポートフォリオ",
    "スクリーニング",
    "バックテスト",
    "一括バックテスト",
    "セクターローテーション",
    "AI戦略ビルダー",
    "AI質問箱",
]
if st.session_state["is_admin"]:
    tab_labels.append("管理者")

tabs = st.tabs(tab_labels)
(
    tab_portfolio,
    tab_screening,
    tab_backtest,
    tab_ranking,
    tab_sector,
    tab_strategy_builder,
    tab_qa,
) = tabs[:7]

with tab_portfolio:
    render_portfolio_tab()

with tab_screening:
    render_screening_tab()

with tab_backtest:
    render_backtest_tab()

with tab_ranking:
    render_ranking_tab()

with tab_sector:
    render_sector_tab()

with tab_strategy_builder:
    render_strategy_builder_tab()

with tab_qa:
    render_qa_tab()

if st.session_state["is_admin"]:
    with tabs[7]:
        render_admin_tab()
```

- [ ] **Step 5: 構文確認**

Run: `uv run python -c "import ast; ast.parse(open('app.py', encoding='utf-8').read())"`
Expected: エラーなく終了する

- [ ] **Step 6: 全体テストスイートを実行して回帰が無いことを確認する**

Run: `uv run pytest -v`
Expected: PASS（全件）

- [ ] **Step 7: Commit**

```bash
git add app_tabs/admin_tab.py app.py
git commit -m "feat: 管理者専用タブ（全ユーザー戦略管理）を追加"
```

---

### Task 5: 全体テスト・実データでの動作確認・手動ブラウザ確認

このタスクは新規コードを書かず、フェーズA全体が実際のアプリで動くことを確認する。

**Files:** なし（確認のみ）

- [ ] **Step 1: 全体テストスイートを実行する**

Run: `uv run pytest -v`（`ai-stock-investing-tutorial/app`ディレクトリで）
Expected: 全件PASS

- [ ] **Step 2: 実データ（`data/app.db`）をバックアップする**

```bash
cp data/app.db data/app.db.backup-before-admin
```

- [ ] **Step 3: アプリを起動する**

```bash
uv run python -m streamlit run app.py
```

- [ ] **Step 4: 既存DBへの自動付与を確認する**

```bash
uv run python -c "
import sqlite3
conn = sqlite3.connect('data/app.db')
rows = conn.execute('SELECT id, username, is_admin FROM users ORDER BY id').fetchall()
for row in rows:
    print(row)
"
```

Expected: `id=1`（`admin`アカウント）の行が`is_admin=1`になっている。他のユーザーは`is_admin=0`

- [ ] **Step 5: ブラウザで動作確認する**

`http://localhost:8501`を開き、以下を確認する:

- `admin`アカウントでログインする → 8つ目に「管理者」タブが表示される
- 「管理者」タブを開き、全ユーザー分の保存済み戦略が一覧表示されることを確認する（ユーザー名・戦略名・作成日時）
- 一覧の行をクリックし、`strategy_json`の編集欄が表示されることを確認する。内容を少し変更（例: `conditions`に1件追加）して保存し、「更新しました」と表示され一覧に反映されることを確認する
- 別の戦略行を選び、「削除」ボタンで削除できることを確認する
- `admin`以外の一般ユーザーでログインし直し、「管理者」タブが表示されないことを確認する

- [ ] **Step 6: 問題なければバックアップを削除する**

```bash
rm -f data/app.db.backup-before-admin
```

（手動確認で問題が見つかった場合はバックアップから`data/app.db`を復元し、原因を調査する。このステップはコミットを伴わない）
