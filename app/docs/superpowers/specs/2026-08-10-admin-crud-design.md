# 管理者機能（データCRUD） 設計書

## 概要・目的

`docs/superpowers/specs/2026-08-10-database-multiuser-auth-design.md`の3フェーズ完了により、アプリは複数ユーザー対応・認証済みになった。しかし現状、`admin`アカウント（フェーズ1移行スクリプトで作成した最初のユーザー）も他の自己登録ユーザーと全く同じ権限しか持たず、自分自身のデータしかCRUDできない。

本設計は、`admin`アカウントに管理者権限を持たせ、(1) 全ユーザーの保存済み戦略の閲覧・編集・削除、(2) ユーザーアカウント自体の一覧・admin権限付与剥奪・削除、(3) 市場データ（株価履歴・fundamentalsスナップショット・企業プロファイル）の手動編集、の3つの管理機能を追加する。

## 背景（既存の`app/`との整合）

- ユーザー個別データの永続化は`user_id`引数を取るCRUD関数群（`portfolio_management/storage.py`・`strategy_builder/storage.py`）で統一されており、本設計もこのパターンに従う
- `db/engine.py`の`init_db()`は既に「既存テーブルへの列追加をALTER TABLEで吸収する」軽量マイグレーション（`_ensure_user_name_columns`）の前例があり、本設計の`is_admin`列追加もこれに倣う
- `portfolio_tab.py`の保有銘柄編集は「全削除→編集後の内容を再挿入」という全置換保存パターンを既に採用しており、本設計の市場データ編集（`PriceHistory`/`FundamentalsSnapshot`）もこれに倣う
- SQLiteの外部キー制約は有効化していない（フェーズ1の設計判断）ため、ユーザー削除時の関連データ削除はアプリ側で明示的に行う必要がある

## スコープ

- v1で実装する:
  - 認可基盤: `User.is_admin`列、既存DBへの自動列追加＋最古ユーザーへの自動付与、`app.py`の管理者タブ表示ゲート
  - 戦略管理: 全ユーザーの保存済み戦略の一覧表示・削除・`strategy_json`編集
  - ユーザー管理: 全ユーザー一覧（`is_admin`含む）・admin権限付与剥奪・アカウント削除（関連データも削除）・自分自身への誤操作防止
  - 市場データ管理: 銘柄コード指定での`PriceHistory`/`FundamentalsSnapshot`/`CompanyProfile`の検索・編集・削除
- v1で実装しない（将来課題）:
  - 保有銘柄（holdings）・セクター表示設定（sector_display_settings）の管理者CRUD（ヒアリングで対象外と確定）
  - 監査ログ（誰がいつ何を変更したかの記録）
  - 複数管理者間の権限レベル分け（全admin権限は同一）

---

## データモデル変更

```
User（列追加）
  ...（既存列）
  is_admin: bool（デフォルトFalse）
  -- 既存DBには db/engine.py の init_db() でALTER TABLE追加。
  -- 追加要否に関わらず、DB内にis_admin=Trueのユーザーが1人もいない場合のみ、
  -- MIN(id)のユーザー（既存DBなら現行のadminアカウント、新規DBなら最初の
  -- 登録ユーザー）にis_admin=Trueを自動付与する（1人でもadminがいれば何もしない
  -- ＝以後の手動でのadmin権限変更を上書きしない）。
```

新規テーブルは無し。既存の`Strategy`/`PriceHistory`/`FundamentalsSnapshot`/`CompanyProfile`/`User`テーブルをそのまま利用する。

---

## フェーズA: 認可基盤・戦略管理

### 目的

`is_admin`列を追加し、`app.py`に管理者専用タブの表示ゲートを実装する。あわせて、最も要望の強い「全ユーザーの戦略管理」を同フェーズで実装する。

### 実装対象

- `db/models.py`: `User`に`is_admin: Mapped[bool] = mapped_column(default=False, nullable=False)`を追加
- `db/engine.py`: `init_db()`に`_ensure_admin_column(engine)`を追加。`PRAGMA table_info`で`is_admin`列の有無を確認し、無ければ`ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0`で追加する。続けて`_grant_admin_to_first_user_if_none_exists(engine)`を呼び、`SELECT COUNT(*) FROM users WHERE is_admin = 1`が0件の場合のみ`UPDATE users SET is_admin = 1 WHERE id = (SELECT MIN(id) FROM users)`を実行する。列の追加要否とは独立してこの判定を行うことで、「既存DBに列を追加するケース」と「`create_all()`で最初から列を持つ新規DBのケース」の両方で最初のユーザーが自動的に管理者になる。1人でも管理者が存在すればこの処理は何もしない（以後の手動でのadmin権限変更を上書きしない）
- `auth.py`の`build_credentials`が返すユーザー情報には影響しない（`is_admin`は認証情報ではなくアプリ内の認可情報のため、`credentials`辞書には含めない）
- `app.py`: ログイン成功後、`get_user_id`で取得した`user_id`に加えて`is_admin`も取得する新関数`auth.get_is_admin(username, session_factory=SessionLocal) -> bool`を呼び、`st.session_state["is_admin"]`に保存。`st.tabs`のタブリストを`is_admin`が`True`の場合のみ「管理者」タブを追加する形に変更
- `strategy_builder/storage.py`に管理者向け関数を追加:
  - `load_all_strategies(session_factory=SessionLocal) -> list[dict]`: `Strategy`と`User`をJOINし`id`/`user_id`/`username`/`strategy_name`/`strategy_json`（パース済みdict）/`created_at`を返す
  - `delete_strategy_by_id(strategy_id: int, session_factory=SessionLocal) -> None`
  - `update_strategy_json_by_id(strategy_id: int, strategy_json_str: str, session_factory=SessionLocal) -> None`: `json.loads`でパース（失敗時は`json.JSONDecodeError`をそのまま送出し呼び出し元でエラー表示）。パース結果に`strategy_name`キーがあれば`Strategy.strategy_name`列も同期する
- `app_tabs/admin_tab.py`（新規）: 「管理者」タブのエントリーポイント。この段階では戦略管理セクションのみ実装（一覧表→行選択→`strategy_json`を`st.text_area`で編集→保存/削除ボタン）
- `app.py`に`render_admin_tab`のインポート・呼び出しを追加

### テスト

- `tests/test_db_engine.py`: `is_admin`列の自動追加＋既存DBでのMIN(id)ユーザーへの自動付与、既に列がある場合は上書きしないことを検証
- `tests/test_auth.py`: `get_is_admin`のテスト追加
- `tests/test_strategy_builder_storage.py`: `load_all_strategies`（複数ユーザー分がusername付きで返る）・`delete_strategy_by_id`・`update_strategy_json_by_id`（正常系・不正JSON時の例外・strategy_name同期）を検証

---

## フェーズB: ユーザーアカウント管理

### 目的

管理者が全ユーザーを一覧し、admin権限の付与剥奪・アカウント削除を行えるようにする。

### 実装対象

- `admin.py`（新規モジュール、`auth.py`とは役割分離: `auth.py`は認証フロー連携、`admin.py`は管理者操作）:
  - `list_users(session_factory=SessionLocal) -> list[dict]`: `id`/`username`/`email`/`created_at`/`is_admin`
  - `set_admin_status(user_id: int, is_admin: bool, session_factory=SessionLocal) -> None`
  - `delete_user(user_id: int, session_factory=SessionLocal) -> None`: `User`本体に加え、紐づく`Holding`/`Strategy`/`SectorDisplaySetting`を同一トランザクションで削除する
- `app_tabs/admin_tab.py`にユーザー管理セクションを追加: 一覧表（`st.dataframe`）＋行選択でadmin権限トグル・削除ボタン。**ログイン中の自分自身のユーザーIDと一致する行は、admin権限剥奪・削除のボタンを無効化する**（誤操作でadmin不在になることを防ぐ）

### テスト

- `tests/test_admin.py`（新規）: `list_users`・`set_admin_status`・`delete_user`（関連するHolding/Strategy/SectorDisplaySettingも削除されることを検証）

---

## フェーズC: 市場データ管理

### 目的

管理者が銘柄コード指定で株価履歴・fundamentalsスナップショット・企業プロファイルを検索・編集・削除できるようにする。

### 実装対象

- `data_api/stock_price_api.py`に管理者向け関数を追加:
  - `load_price_history_for_ticker(ticker: str, session_factory=SessionLocal) -> list[dict]`
  - `save_price_history_for_ticker(ticker: str, rows: list[dict], session_factory=SessionLocal) -> None`: 該当銘柄の既存`PriceHistory`行を全削除し、渡された`rows`を再挿入する（`portfolio_management/storage.py`の`save_holdings`と同じ全置換パターン）
  - `load_fundamentals_snapshots_for_ticker(ticker: str, session_factory=SessionLocal) -> list[dict]`
  - `save_fundamentals_snapshots_for_ticker(ticker: str, rows: list[dict], session_factory=SessionLocal) -> None`: 同様に全置換
  - `load_company_profile(ticker: str, session_factory=SessionLocal) -> dict | None`
  - `save_company_profile_fields(ticker: str, name, sector, industry, business_summary, session_factory=SessionLocal) -> None`: 既存行を直接UPDATE（無ければ新規作成）
- `app_tabs/admin_tab.py`に市場データ管理セクションを追加: 銘柄コード入力欄→検索ボタンで3テーブル分のデータを取得し、`PriceHistory`/`FundamentalsSnapshot`は`st.data_editor(num_rows="dynamic")`、`CompanyProfile`はフォーム入力で編集→保存ボタンでそれぞれの`save_*`関数を呼ぶ

### テスト

- `tests/test_stock_price_api.py`: `load_price_history_for_ticker`/`save_price_history_for_ticker`（全置換の動作、他銘柄のデータに影響しないこと）、`load_fundamentals_snapshots_for_ticker`/`save_fundamentals_snapshots_for_ticker`、`load_company_profile`/`save_company_profile_fields`（新規作成・既存更新の両方）を検証

---

## 横断的な考慮事項

- **`app_tabs/admin_tab.py`のUI結線部分はユニットテスト対象外**（既存の`app_tabs`の慣習どおり）。各フェーズの新規関数（DB操作ロジック）のみユニットテストする
- **既存の`admin`ユーザーが自動的に管理者になる**: フェーズAの`_ensure_admin_column`により、この設計を最初にリリースした時点でDBに存在する最古のユーザー（現状は`id=1`の`admin`アカウント）が自動的に`is_admin=True`になる。以後の管理者追加はフェーズBのユーザー管理画面から行う
- **`pyproject.toml`**: 新規依存追加は無し（既存のSQLAlchemy/Streamlitのみで実装可能）
