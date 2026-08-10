# 管理者機能フェーズB（ユーザーアカウント管理） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 管理者タブに「ユーザーアカウント管理」セクションを追加し、全ユーザーの一覧表示・admin権限の付与剥奪・アカウント削除（関連データも削除）を行えるようにする（`docs/superpowers/specs/2026-08-10-admin-crud-design.md`のフェーズB）。

**Architecture:** 新規モジュール`admin.py`（`auth.py`とは役割分離: `auth.py`は認証フロー連携、`admin.py`は管理者タブからのDB操作）にユーザー管理用のCRUD関数を追加し、`app_tabs/admin_tab.py`にフェーズAの戦略管理セクションと同じ「一覧表示→行選択→操作ボタン」パターンでUIを追加する。SQLiteは外部キーCASCADEを有効化していないため、ユーザー削除時は`Holding`/`Strategy`/`SectorDisplaySetting`をアプリ側で明示的に削除する。ログイン中の自分自身に対する管理者権限剥奪・削除はボタンを無効化して防止する。

**Tech Stack:** 既存のSQLAlchemy 2.0 + SQLite（フェーズ1〜A/認証と同じ`data/app.db`）。新規依存追加は無し。

## Global Constraints

- Python >=3.14、パッケージ管理は`uv`（`ai-stock-investing-tutorial/app/pyproject.toml`）
- テストは`uv run pytest -v`（`app/`ディレクトリで実行）
- DBを使うテストは`tmp_path`上のファイルDB（`sqlite:///{tmp_path}/test.db`）を使う
- DB操作を行う関数は`session_factory`引数（デフォルトは本番用`db.engine.SessionLocal`）を受け取り、テストでは注入する（これまでのフェーズと同じDIパターン）
- `app_tabs`配下のUI結線部分はユニットテスト対象外（既存の慣習どおり）
- リポジトリはmasterへの直接コミット運用（フィーチャーブランチ・worktreeは使わない）

---

### Task 1: `admin.py`（ユーザー管理用DB関数）

**Files:**
- Create: `ai-stock-investing-tutorial/app/admin.py`
- Create: `ai-stock-investing-tutorial/app/tests/test_admin.py`

**Interfaces:**
- Consumes: `db.engine.SessionLocal`、`db.models.User`/`Holding`/`Strategy`/`SectorDisplaySetting`
- Produces:
  - `admin.list_users(session_factory=SessionLocal) -> list[dict]` — 各要素は`{"id", "username", "email", "created_at", "is_admin"}`
  - `admin.set_admin_status(user_id: int, is_admin: bool, session_factory=SessionLocal) -> None`
  - `admin.delete_user(user_id: int, session_factory=SessionLocal) -> None` — `User`本体に加え、紐づく`Holding`/`Strategy`/`SectorDisplaySetting`も削除する

- [ ] **Step 1: 失敗するテストを書く**

`ai-stock-investing-tutorial/app/tests/test_admin.py`:

```python
import pytest
from sqlalchemy.orm import sessionmaker

from admin import delete_user, list_users, set_admin_status
from db.engine import create_db_engine, init_db
from db.models import Holding, SectorDisplaySetting, Strategy, User


@pytest.fixture
def session_factory(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    return sessionmaker(bind=engine)


def test_list_users_returns_all_users_with_expected_fields(session_factory):
    with session_factory() as session:
        session.add(
            User(
                username="taro",
                email="taro@example.com",
                hashed_password="h",
                is_admin=True,
            )
        )
        session.add(User(username="hanako", hashed_password="h", is_admin=False))
        session.commit()

    users = list_users(session_factory=session_factory)
    assert len(users) == 2
    taro = next(u for u in users if u["username"] == "taro")
    assert taro["email"] == "taro@example.com"
    assert taro["is_admin"] is True
    hanako = next(u for u in users if u["username"] == "hanako")
    assert hanako["email"] is None
    assert hanako["is_admin"] is False


def test_set_admin_status_grants_and_revokes(session_factory):
    with session_factory() as session:
        user = User(username="taro", hashed_password="h", is_admin=False)
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = user.id

    set_admin_status(user_id, True, session_factory=session_factory)
    with session_factory() as session:
        assert session.query(User).filter_by(id=user_id).one().is_admin is True

    set_admin_status(user_id, False, session_factory=session_factory)
    with session_factory() as session:
        assert session.query(User).filter_by(id=user_id).one().is_admin is False


def test_delete_user_removes_user_and_related_data(session_factory):
    with session_factory() as session:
        user = User(username="taro", hashed_password="h")
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = user.id

        session.add(Holding(user_id=user_id, ticker="7203.T", shares=1.0, cost=1.0))
        session.add(Strategy(user_id=user_id, strategy_name="A", strategy_json="{}"))
        session.add(
            SectorDisplaySetting(
                user_id=user_id, visible_json="{}", order_json="{}", height_json="{}"
            )
        )
        session.commit()

    delete_user(user_id, session_factory=session_factory)

    with session_factory() as session:
        assert session.query(User).filter_by(id=user_id).count() == 0
        assert session.query(Holding).filter_by(user_id=user_id).count() == 0
        assert session.query(Strategy).filter_by(user_id=user_id).count() == 0
        assert session.query(SectorDisplaySetting).filter_by(user_id=user_id).count() == 0


def test_delete_user_does_not_affect_other_users(session_factory):
    with session_factory() as session:
        user1 = User(username="taro", hashed_password="h")
        user2 = User(username="hanako", hashed_password="h")
        session.add(user1)
        session.add(user2)
        session.commit()
        session.refresh(user1)
        session.refresh(user2)
        user1_id, user2_id = user1.id, user2.id

        session.add(Holding(user_id=user2_id, ticker="7203.T", shares=1.0, cost=1.0))
        session.commit()

    delete_user(user1_id, session_factory=session_factory)

    with session_factory() as session:
        assert session.query(User).filter_by(id=user2_id).count() == 1
        assert session.query(Holding).filter_by(user_id=user2_id).count() == 1
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_admin.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'admin'`）

- [ ] **Step 3: `admin.py`を実装する**

`ai-stock-investing-tutorial/app/admin.py`:

```python
"""管理者操作用のDB連携モジュール。ユーザーアカウント自体の管理
（一覧・admin権限付与剥奪・削除）を担う。auth.pyは認証フロー連携を担当し、
本モジュールは管理者タブからの操作に特化する。
"""

from db.engine import SessionLocal
from db.models import Holding, SectorDisplaySetting, Strategy, User


def list_users(session_factory=SessionLocal) -> list[dict]:
    """全ユーザーの一覧をDBから読み込む。"""
    with session_factory() as session:
        users = session.query(User).order_by(User.id).all()
        return [
            {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "created_at": user.created_at,
                "is_admin": user.is_admin,
            }
            for user in users
        ]


def set_admin_status(user_id: int, is_admin: bool, session_factory=SessionLocal) -> None:
    """指定ユーザーの管理者権限を設定する。"""
    with session_factory() as session:
        user = session.query(User).filter_by(id=user_id).first()
        user.is_admin = is_admin
        session.commit()


def delete_user(user_id: int, session_factory=SessionLocal) -> None:
    """指定ユーザーのアカウントを削除する。SQLiteの外部キーCASCADEを
    有効化していないため、紐づくHolding/Strategy/SectorDisplaySettingも
    アプリ側で明示的に削除する。"""
    with session_factory() as session:
        session.query(Holding).filter_by(user_id=user_id).delete()
        session.query(Strategy).filter_by(user_id=user_id).delete()
        session.query(SectorDisplaySetting).filter_by(user_id=user_id).delete()
        session.query(User).filter_by(id=user_id).delete()
        session.commit()
```

- [ ] **Step 4: テストを実行して通ることを確認する**

Run: `uv run pytest tests/test_admin.py -v`
Expected: PASS（4件）

- [ ] **Step 5: Commit**

```bash
git add admin.py tests/test_admin.py
git commit -m "feat: ユーザーアカウント管理用のDB関数（list_users/set_admin_status/delete_user）を追加"
```

---

### Task 2: 管理者タブへのユーザー管理セクション追加

**Files:**
- Modify: `ai-stock-investing-tutorial/app/app_tabs/admin_tab.py`

**Interfaces:**
- Consumes: `admin.list_users`/`set_admin_status`/`delete_user`（Task 1）、`app_tabs.shared.get_current_user_id`

このタスクはUIウィジェットの結線でありユニットテスト対象外（既存の`app_tabs`の慣習どおり）。Step 4で手動起動して確認する。

- [ ] **Step 1: importを追加する**

`ai-stock-investing-tutorial/app/app_tabs/admin_tab.py`、変更前:

```python
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
```

変更後:

```python
import json
import logging

import pandas as pd
import streamlit as st

from admin import delete_user, list_users, set_admin_status
from strategy_builder.storage import (
    delete_strategy_by_id,
    load_all_strategies,
    update_strategy_json_by_id,
)

from app_tabs.shared import get_current_user_id

logger = logging.getLogger(__name__)
```

- [ ] **Step 2: `render_admin_tab`にユーザー管理セクションを追加する**

`ai-stock-investing-tutorial/app/app_tabs/admin_tab.py`、変更前:

```python
def render_admin_tab() -> None:
    logger.info("管理者タブを表示")
    st.header("管理者")
    _render_strategy_management()
```

変更後:

```python
def render_admin_tab() -> None:
    logger.info("管理者タブを表示")
    st.header("管理者")
    _render_strategy_management()
    st.divider()
    _render_user_management()
```

- [ ] **Step 3: `_render_user_management`関数を追加する**

`ai-stock-investing-tutorial/app/app_tabs/admin_tab.py`の末尾に追加:

```python
def _render_user_management() -> None:
    st.subheader("ユーザーアカウント管理")
    current_user_id = get_current_user_id()
    users = list_users()

    display_df = pd.DataFrame(
        [
            {
                "ユーザー名": u["username"],
                "メール": u["email"] or "―",
                "登録日": u["created_at"],
                "管理者": u["is_admin"],
            }
            for u in users
        ]
    )
    st.caption("行をクリックすると操作できます。")
    event = st.dataframe(
        display_df,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="admin_user_table",
    )
    selected_idx = event.selection.rows[0] if event.selection.rows else None
    if selected_idx is None:
        return

    selected = users[selected_idx]
    is_self = selected["id"] == current_user_id
    st.caption(f"選択中: {selected['username']}" + ("（自分自身）" if is_self else ""))

    admin_col, delete_col = st.columns(2)
    with admin_col:
        if selected["is_admin"]:
            if st.button(
                "管理者権限を剥奪",
                key=f"admin_user_revoke_{selected['id']}",
                disabled=is_self,
            ):
                set_admin_status(selected["id"], False)
                st.success("管理者権限を剥奪しました。")
                st.rerun()
        else:
            if st.button("管理者権限を付与", key=f"admin_user_grant_{selected['id']}"):
                set_admin_status(selected["id"], True)
                st.success("管理者権限を付与しました。")
                st.rerun()
    with delete_col:
        if st.button(
            "アカウント削除", key=f"admin_user_delete_{selected['id']}", disabled=is_self
        ):
            delete_user(selected["id"])
            st.success("アカウントを削除しました。")
            st.rerun()

    if is_self:
        st.caption("自分自身の管理者権限剥奪・アカウント削除はできません。")
```

- [ ] **Step 4: 構文確認**

Run: `uv run python -c "import ast; ast.parse(open('app_tabs/admin_tab.py', encoding='utf-8').read())"`
Expected: エラーなく終了する

- [ ] **Step 5: 全体テストスイートを実行して回帰が無いことを確認する**

Run: `uv run pytest -v`
Expected: PASS（全件）

- [ ] **Step 6: Commit**

```bash
git add app_tabs/admin_tab.py
git commit -m "feat: 管理者タブにユーザーアカウント管理セクションを追加"
```

---

### Task 3: 全体テスト・手動ブラウザ確認

このタスクは新規コードを書かず、フェーズB全体が実際のアプリで動くことを確認する。

**Files:** なし（確認のみ）

- [ ] **Step 1: 全体テストスイートを実行する**

Run: `uv run pytest -v`（`ai-stock-investing-tutorial/app`ディレクトリで）
Expected: 全件PASS

- [ ] **Step 2: 実データ（`data/app.db`）をバックアップする**

```bash
cp data/app.db data/app.db.backup-before-admin-phaseb
```

- [ ] **Step 3: アプリを起動する**

```bash
uv run python -m streamlit run app.py
```

- [ ] **Step 4: ブラウザで動作確認する**

`http://localhost:8501`を開き、`admin`アカウントでログインして以下を確認する:

- 「管理者」タブの「ユーザーアカウント管理」セクションに全ユーザーが一覧表示される（ユーザー名・メール・登録日・管理者フラグ）
- 自分自身（`admin`）の行を選択すると、「管理者権限を剥奪」「アカウント削除」ボタンが無効化されていることを確認する
- 自分以外のユーザーの行を選択し、「管理者権限を付与」→反映されることを確認する。再度選択し「管理者権限を剥奪」→反映されることを確認する
- テスト用に作成した不要なユーザーを1件選び、「アカウント削除」で削除できることを確認する。削除後、そのユーザーが一覧から消えることを確認する

- [ ] **Step 5: 問題なければバックアップを削除する**

```bash
rm -f data/app.db.backup-before-admin-phaseb
```

（手動確認で問題が見つかった場合はバックアップから`data/app.db`を復元し、原因を調査する。このステップはコミットを伴わない）
