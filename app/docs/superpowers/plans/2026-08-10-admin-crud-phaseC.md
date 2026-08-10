# 管理者機能フェーズC（市場データ管理） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 管理者タブに「市場データ管理」セクションを追加し、銘柄コード指定で株価履歴（`PriceHistory`）・fundamentalsスナップショット（`FundamentalsSnapshot`）・企業プロファイル（`CompanyProfile`）を検索・編集・削除できるようにする（`docs/superpowers/specs/2026-08-10-admin-crud-design.md`のフェーズC）。これで管理者機能（フェーズA/B/C）が全て揃う。

**Architecture:** `data_api/stock_price_api.py`に管理者向けの読み書き関数を追加する。`PriceHistory`/`FundamentalsSnapshot`は`portfolio_management/storage.py`の`save_holdings`と同じ「全削除→再挿入」の全置換パターンを踏襲し、`st.data_editor(num_rows="dynamic")`で行の編集・追加・削除を1つの保存操作にまとめる。`CompanyProfile`は銘柄ごとに1行のみのため、直接UPDATE（無ければ新規作成）するシンプルなフォーム編集にする。

**Tech Stack:** 既存のSQLAlchemy 2.0 + SQLite（これまでのフェーズと同じ`data/app.db`）。新規依存追加は無し。

## Global Constraints

- Python >=3.14、パッケージ管理は`uv`（`ai-stock-investing-tutorial/app/pyproject.toml`）
- テストは`uv run pytest -v`（`app/`ディレクトリで実行）
- DBを使うテストは`tmp_path`上のファイルDB（`sqlite:///{tmp_path}/test.db`）を使う。`tests/test_stock_price_api.py`の既存の慣習に合わせ、共有fixtureではなく各テスト関数内で`create_db_engine`/`init_db`/`sessionmaker`を直接呼ぶ
- DB操作を行う関数は`session_factory`引数（デフォルトは本番用`db.engine.SessionLocal`）を受け取り、テストでは注入する
- `app_tabs`配下のUI結線部分はユニットテスト対象外（既存の慣習どおり）
- **`st.dataframe`/`st.data_editor`の行選択・編集状態は削除操作後の`st.rerun()`でも古い状態を保持し得る**（フェーズA/Bで実際に発生し修正したバグ）。本フェーズは全置換保存パターンのため個別行選択には依存しないが、保存時に空行（必須キーが未入力の追加行）を除外する処理を必ず入れる
- リポジトリはmasterへの直接コミット運用（フィーチャーブランチ・worktreeは使わない）

---

### Task 1: `data_api/stock_price_api.py`への管理者向け読み書き関数の追加

**Files:**
- Modify: `ai-stock-investing-tutorial/app/data_api/stock_price_api.py`
- Modify: `ai-stock-investing-tutorial/app/tests/test_stock_price_api.py`

**Interfaces:**
- Produces:
  - `data_api.stock_price_api.load_price_history_for_ticker(ticker: str, session_factory=SessionLocal) -> list[dict]` — 各要素は`{"date", "open", "high", "low", "close", "volume"}`
  - `data_api.stock_price_api.save_price_history_for_ticker(ticker: str, rows: list[dict], session_factory=SessionLocal) -> None` — 該当銘柄の既存行を全削除して`rows`を再挿入する
  - `data_api.stock_price_api.load_fundamentals_snapshots_for_ticker(ticker: str, session_factory=SessionLocal) -> list[dict]` — 各要素は`{"snapshot_date", "name", "trailing_pe", "price_to_book", "dividend_yield", "market_cap", "return_on_equity", "revenue_growth"}`
  - `data_api.stock_price_api.save_fundamentals_snapshots_for_ticker(ticker: str, rows: list[dict], session_factory=SessionLocal) -> None` — 同様に全置換
  - `data_api.stock_price_api.load_company_profile(ticker: str, session_factory=SessionLocal) -> dict | None` — `{"ticker", "name", "sector", "industry", "business_summary"}`、無ければ`None`
  - `data_api.stock_price_api.save_company_profile_fields(ticker: str, name: str | None, sector: str | None, industry: str | None, business_summary: str | None, session_factory=SessionLocal) -> None` — 既存行を直接UPDATE（無ければ新規作成）

- [ ] **Step 1: 失敗するテストを書く**

`ai-stock-investing-tutorial/app/tests/test_stock_price_api.py`の末尾に追加:

```python
def test_load_price_history_for_ticker_returns_rows_sorted_by_date(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

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

    rows = stock_price_api.load_price_history_for_ticker(
        "7203.T", session_factory=session_factory
    )
    assert [r["date"] for r in rows] == ["2026-01-01", "2026-01-02"]
    assert rows[0]["open"] == 1.0


def test_save_price_history_for_ticker_replaces_existing_rows(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.save_price_history_for_ticker(
        "7203.T",
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
    stock_price_api.save_price_history_for_ticker(
        "7203.T",
        [
            {
                "date": "2026-01-02",
                "open": 2.0,
                "high": 2.0,
                "low": 2.0,
                "close": 2.0,
                "volume": 2.0,
            }
        ],
        session_factory=session_factory,
    )

    rows = stock_price_api.load_price_history_for_ticker(
        "7203.T", session_factory=session_factory
    )
    assert [r["date"] for r in rows] == ["2026-01-02"]


def test_save_price_history_for_ticker_does_not_affect_other_tickers(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.save_price_history_for_ticker(
        "AAA.T",
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
    stock_price_api.save_price_history_for_ticker(
        "BBB.T",
        [
            {
                "date": "2026-01-01",
                "open": 2.0,
                "high": 2.0,
                "low": 2.0,
                "close": 2.0,
                "volume": 2.0,
            }
        ],
        session_factory=session_factory,
    )
    stock_price_api.save_price_history_for_ticker("AAA.T", [], session_factory=session_factory)

    assert (
        stock_price_api.load_price_history_for_ticker("AAA.T", session_factory=session_factory)
        == []
    )
    bbb_rows = stock_price_api.load_price_history_for_ticker(
        "BBB.T", session_factory=session_factory
    )
    assert len(bbb_rows) == 1


def test_load_fundamentals_snapshots_for_ticker_returns_all_fields(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(
            stock_price_api.FundamentalsSnapshot(
                ticker="7203.T", snapshot_date="2026-01-01", trailing_pe=12.3, market_cap=1000
            )
        )
        session.commit()

    rows = stock_price_api.load_fundamentals_snapshots_for_ticker(
        "7203.T", session_factory=session_factory
    )
    assert len(rows) == 1
    assert rows[0]["snapshot_date"] == "2026-01-01"
    assert rows[0]["trailing_pe"] == 12.3
    assert rows[0]["market_cap"] == 1000


def test_save_fundamentals_snapshots_for_ticker_replaces_existing_rows(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.save_fundamentals_snapshots_for_ticker(
        "7203.T",
        [{"snapshot_date": "2026-01-01", "trailing_pe": 10.0}],
        session_factory=session_factory,
    )
    stock_price_api.save_fundamentals_snapshots_for_ticker(
        "7203.T",
        [{"snapshot_date": "2026-01-02", "trailing_pe": 20.0}],
        session_factory=session_factory,
    )

    rows = stock_price_api.load_fundamentals_snapshots_for_ticker(
        "7203.T", session_factory=session_factory
    )
    assert [r["snapshot_date"] for r in rows] == ["2026-01-02"]
    assert rows[0]["trailing_pe"] == 20.0


def test_load_company_profile_returns_none_when_missing(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    assert (
        stock_price_api.load_company_profile("7203.T", session_factory=session_factory) is None
    )


def test_save_company_profile_fields_creates_new_row(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    stock_price_api.save_company_profile_fields(
        "7203.T",
        "トヨタ自動車",
        "Consumer Cyclical",
        "Auto Manufacturers",
        "概要",
        session_factory=session_factory,
    )

    profile = stock_price_api.load_company_profile("7203.T", session_factory=session_factory)
    assert profile["name"] == "トヨタ自動車"
    assert profile["sector"] == "Consumer Cyclical"
    assert profile["industry"] == "Auto Manufacturers"
    assert profile["business_summary"] == "概要"


def test_save_company_profile_fields_updates_existing_row(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(stock_price_api.CompanyProfile(ticker="7203.T", sector="Old"))
        session.commit()

    stock_price_api.save_company_profile_fields(
        "7203.T",
        "トヨタ自動車",
        "Consumer Cyclical",
        "Auto Manufacturers",
        "概要",
        session_factory=session_factory,
    )

    profile = stock_price_api.load_company_profile("7203.T", session_factory=session_factory)
    assert profile["sector"] == "Consumer Cyclical"
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_stock_price_api.py -v -k "for_ticker or company_profile_fields"`
Expected: FAIL（`AttributeError: module 'data_api.stock_price_api' has no attribute 'load_price_history_for_ticker'`）

- [ ] **Step 3: `data_api/stock_price_api.py`に関数を追加する**

`ai-stock-investing-tutorial/app/data_api/stock_price_api.py`の末尾に追加:

```python
def load_price_history_for_ticker(ticker: str, session_factory=SessionLocal) -> list[dict]:
    """指定銘柄の株価履歴を全件DBから読み込む（管理者向け）。"""
    with session_factory() as session:
        rows = (
            session.query(PriceHistory)
            .filter_by(ticker=ticker)
            .order_by(PriceHistory.date)
            .all()
        )
        return [
            {
                "date": row.date,
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
            }
            for row in rows
        ]


def save_price_history_for_ticker(
    ticker: str, rows: list[dict], session_factory=SessionLocal
) -> None:
    """指定銘柄のPriceHistoryを全置換する（管理者向け）。既存行を全削除し、
    渡されたrowsを再挿入する（portfolio_management/storage.pyのsave_holdingsと
    同じ全置換パターン）。"""
    with session_factory() as session:
        session.query(PriceHistory).filter_by(ticker=ticker).delete()
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


def load_fundamentals_snapshots_for_ticker(
    ticker: str, session_factory=SessionLocal
) -> list[dict]:
    """指定銘柄のfundamentalsスナップショットを全件DBから読み込む（管理者向け）。"""
    with session_factory() as session:
        rows = (
            session.query(FundamentalsSnapshot)
            .filter_by(ticker=ticker)
            .order_by(FundamentalsSnapshot.snapshot_date)
            .all()
        )
        return [
            {
                "snapshot_date": row.snapshot_date,
                "name": row.name,
                "trailing_pe": row.trailing_pe,
                "price_to_book": row.price_to_book,
                "dividend_yield": row.dividend_yield,
                "market_cap": row.market_cap,
                "return_on_equity": row.return_on_equity,
                "revenue_growth": row.revenue_growth,
            }
            for row in rows
        ]


def save_fundamentals_snapshots_for_ticker(
    ticker: str, rows: list[dict], session_factory=SessionLocal
) -> None:
    """指定銘柄のFundamentalsSnapshotを全置換する（管理者向け）。既存行を全削除し、
    渡されたrowsを再挿入する。"""
    with session_factory() as session:
        session.query(FundamentalsSnapshot).filter_by(ticker=ticker).delete()
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
            "business_summary": row.business_summary,
        }


def save_company_profile_fields(
    ticker: str,
    name: str | None,
    sector: str | None,
    industry: str | None,
    business_summary: str | None,
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
        session.commit()
```

- [ ] **Step 4: テストを実行して通ることを確認する**

Run: `uv run pytest tests/test_stock_price_api.py -v -k "for_ticker or company_profile_fields"`
Expected: PASS（全8件）

- [ ] **Step 5: 全体テストスイートを実行して回帰が無いことを確認する**

Run: `uv run pytest -v`
Expected: PASS（全件）

- [ ] **Step 6: Commit**

```bash
git add data_api/stock_price_api.py tests/test_stock_price_api.py
git commit -m "feat: 市場データ（PriceHistory/FundamentalsSnapshot/CompanyProfile）の管理者向け読み書き関数を追加"
```

---

### Task 2: 管理者タブへの市場データ管理セクション追加

**Files:**
- Modify: `ai-stock-investing-tutorial/app/app_tabs/admin_tab.py`

**Interfaces:**
- Consumes: `data_api.stock_price_api.load_price_history_for_ticker`/`save_price_history_for_ticker`/`load_fundamentals_snapshots_for_ticker`/`save_fundamentals_snapshots_for_ticker`/`load_company_profile`/`save_company_profile_fields`（Task 1）

このタスクはUIウィジェットの結線でありユニットテスト対象外（既存の`app_tabs`の慣習どおり）。Step 4で手動起動して確認する。

- [ ] **Step 1: importを追加する**

`ai-stock-investing-tutorial/app/app_tabs/admin_tab.py`、変更前:

```python
from admin import delete_user, list_users, set_admin_status
from strategy_builder.storage import (
    delete_strategy_by_id,
    load_all_strategies,
    update_strategy_json_by_id,
)

from app_tabs.shared import get_current_user_id
```

変更後:

```python
from admin import delete_user, list_users, set_admin_status
from data_api.stock_price_api import (
    load_company_profile,
    load_fundamentals_snapshots_for_ticker,
    load_price_history_for_ticker,
    save_company_profile_fields,
    save_fundamentals_snapshots_for_ticker,
    save_price_history_for_ticker,
)
from strategy_builder.storage import (
    delete_strategy_by_id,
    load_all_strategies,
    update_strategy_json_by_id,
)

from app_tabs.shared import get_current_user_id
```

- [ ] **Step 2: `render_admin_tab`に市場データ管理セクションを追加する**

`ai-stock-investing-tutorial/app/app_tabs/admin_tab.py`、変更前:

```python
def render_admin_tab() -> None:
    logger.info("管理者タブを表示")
    st.header("管理者")
    _render_strategy_management()
    st.divider()
    _render_user_management()
```

変更後:

```python
def render_admin_tab() -> None:
    logger.info("管理者タブを表示")
    st.header("管理者")
    _render_strategy_management()
    st.divider()
    _render_user_management()
    st.divider()
    _render_market_data_management()
```

- [ ] **Step 3: `_render_market_data_management`関数を追加する**

`ai-stock-investing-tutorial/app/app_tabs/admin_tab.py`の末尾に追加:

```python
def _render_market_data_management() -> None:
    st.subheader("市場データ管理")
    ticker = st.text_input("銘柄コード（例: 7203.T）", key="admin_market_data_ticker")
    if not ticker:
        st.caption("銘柄コードを入力すると、株価履歴・fundamentals・企業プロファイルを編集できます。")
        return

    st.markdown("**株価履歴（PriceHistory）**")
    price_rows = load_price_history_for_ticker(ticker)
    price_df = pd.DataFrame(
        price_rows, columns=["date", "open", "high", "low", "close", "volume"]
    )
    edited_price_df = st.data_editor(
        price_df,
        num_rows="dynamic",
        hide_index=True,
        key=f"admin_price_history_editor_{ticker}",
    )
    if st.button("株価履歴を保存", key=f"admin_price_history_save_{ticker}"):
        # 追加行のうちdate未入力の行（保存準備がまだ整っていない空行）は除外する
        records = [r for r in edited_price_df.to_dict("records") if r.get("date")]
        save_price_history_for_ticker(ticker, records)
        st.success("株価履歴を保存しました。")
        st.rerun()

    st.markdown("**Fundamentalsスナップショット（FundamentalsSnapshot）**")
    fundamentals_rows = load_fundamentals_snapshots_for_ticker(ticker)
    fundamentals_df = pd.DataFrame(
        fundamentals_rows,
        columns=[
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
    edited_fundamentals_df = st.data_editor(
        fundamentals_df,
        num_rows="dynamic",
        hide_index=True,
        key=f"admin_fundamentals_editor_{ticker}",
    )
    if st.button("Fundamentalsスナップショットを保存", key=f"admin_fundamentals_save_{ticker}"):
        records = [r for r in edited_fundamentals_df.to_dict("records") if r.get("snapshot_date")]
        save_fundamentals_snapshots_for_ticker(ticker, records)
        st.success("Fundamentalsスナップショットを保存しました。")
        st.rerun()

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

- [ ] **Step 4: 構文確認**

Run: `uv run python -c "import ast; ast.parse(open('app_tabs/admin_tab.py', encoding='utf-8').read())"`
Expected: エラーなく終了する

- [ ] **Step 5: 全体テストスイートを実行して回帰が無いことを確認する**

Run: `uv run pytest -v`
Expected: PASS（全件）

- [ ] **Step 6: Commit**

```bash
git add app_tabs/admin_tab.py
git commit -m "feat: 管理者タブに市場データ管理セクションを追加"
```

---

### Task 3: 全体テスト・手動ブラウザ確認

このタスクは新規コードを書かず、フェーズC全体（＝管理者機能A/B/C全体）が実際のアプリで動くことを確認する。

**Files:** なし（確認のみ）

- [ ] **Step 1: 全体テストスイートを実行する**

Run: `uv run pytest -v`（`ai-stock-investing-tutorial/app`ディレクトリで）
Expected: 全件PASS

- [ ] **Step 2: 実データ（`data/app.db`）をバックアップする**

```bash
cp data/app.db data/app.db.backup-before-admin-phasec
```

- [ ] **Step 3: アプリを起動する**

```bash
uv run python -m streamlit run app.py
```

- [ ] **Step 4: ブラウザで動作確認する**

`http://localhost:8501`を開き、`admin`アカウントでログインして「管理者」タブの「市場データ管理」セクションで以下を確認する:

- 既に一度アプリで表示したことのある銘柄コード（例: 保有銘柄やスクリーニング結果に含まれる銘柄）を入力すると、株価履歴・fundamentals・企業プロファイルが表示される
- 株価履歴の1行を編集（例: `close`の値を変更）して「株価履歴を保存」→再読み込みしても変更が反映されていることを確認する
- 株価履歴の1行を削除（テーブルの行削除操作）して保存→該当日の行が無くなることを確認する
- 企業プロファイルのフォームで業種名を変更して保存→反映されることを確認する
- 未取得の銘柄コード（DBに何も無い）を入力すると、各テーブルが空の状態で表示され、エラーにならないことを確認する

- [ ] **Step 5: 問題なければバックアップを削除する**

```bash
rm -f data/app.db.backup-before-admin-phasec
```

（手動確認で問題が見つかった場合はバックアップから`data/app.db`を復元し、原因を調査する。このステップはコミットを伴わない）
