# DB化・複数ユーザー対応・認証導入 設計書

## 概要・目的

現状の`app/`は完全にローカル単一ユーザー向けであり、永続化は`data/holdings.json`・`data/strategies.json`・`data/sector_display_settings.json`（ユーザー個別データ）と`data/cache/`配下のファイルキャッシュ（市場データ・LLM生成コンテンツ）のみで、ユーザーという概念も認証も存在しない。

本設計は、実際に複数人へアプリを公開・共有できるようにするため、(1) SQLite+SQLAlchemyによるDB基盤の導入、(2) 市場データ（株価・fundamentals・企業概要・ニュース・日本語銘柄名）の全ユーザー共有DBキャッシュ化、(3) `streamlit-authenticator`によるログイン・自己サービス新規登録、の3点を扱う。デプロイ先は未定のため、まずはローカルでの複数ユーザー対応（ローカルDBファイル・ローカルStreamlitプロセス）に限定する。

3フェーズは依存関係があり（フェーズ1のDB基盤がフェーズ2・3の土台）、優先順位（フェーズ1→2→3）の順に個別のプラン作成・実装・テストサイクルを回すことを想定する。

## 背景（既存の`app/`との整合）

- **ユーザー個別データ**: `portfolio_management/storage.py`（holdings）・`strategy_builder/storage.py`（strategies）・`sector_analysis/display_settings.py`（表示設定）が、それぞれ`path: Path`引数を受け取りJSONファイルを読み書きする同型の関数群として実装されている。
- **市場データ取得**: `data_api/stock_price_api.py`の`fetch_price_history`/`fetch_fundamentals`/`fetch_company_profile`/`fetch_news`/`fetch_japanese_name`は、`app_tabs/shared.py`の`st.cache_data`ラッパー（30分〜24時間TTL、プロセス内メモリのみ）でしか鮮度管理されておらず、`fetch_universe_fundamentals`/`fetch_universe_price_histories`（228銘柄一括）のみ`common/cache.py`の当日分ファイルキャッシュを持つ。
- **LLM生成コンテンツのキャッシュ**: `stock_detail/detail.py`（銘柄詳細のAI講評）・`portfolio_tab.py`（ポートフォリオレビュー）・`backtest_tab.py`/`ranking_tab.py`（バックテスト解説）・`wavelet_analysis.py`（ウェーブレット解説）は、いずれも`common/cache.py`の当日分ファイルキャッシュを使う。これらは生データではなく生成コンテンツであり、本設計では変更しない。
- **LLM呼び出し方式**: `data_api/llm_client.py`経由でClaude Code CLIをサブプロセス実行する。ホストマシン上の単一ログインセッションを前提とし、本設計でもこの方式・単一の共有バックエンドとしての性質は変更しない（ユーザーごとのAPIキー等は導入しない）。
- **既存データの.gitignore**: `app/.gitignore`は既に`data/`ディレクトリ全体を除外しているため、新設する`data/app.db`（SQLiteファイル）も追加設定なしでリポジトリ管理外になる。

## スコープ

- v1で実装する:
  - フェーズ1: `db/`パッケージ（`engine.py`・`models.py`・`init_db()`）、`User`/`Holding`/`Strategy`/`SectorDisplaySetting`テーブル、既存`*/storage.py`のDB化（`path`引数→`user_id`引数）、既存JSONからの一回限り移行スクリプト
  - フェーズ2: `PriceHistory`/`FundamentalsSnapshot`/`CompanyProfile`/`TickerNews`テーブル、`data_api/stock_price_api.py`のread-through化、`fetch_universe_fundamentals`/`fetch_universe_price_histories`のDBクエリ化（専用ファイルキャッシュ廃止）
  - フェーズ3: `streamlit-authenticator`導入、`app.py`へのログインゲート、自己サービス新規登録、全タブへの`user_id`配線
- v1で実装しない（将来課題）:
  - クラウド/PaaSへのデプロイ設定（デプロイ先が未定のため）
  - Alembic等の本格的なスキーママイグレーションツール（`create_all()`による素朴な初期化のみ）
  - パスワードリセット（ログアウト状態からのメール送信によるリセット）。メール送信基盤を用意しないため、v1はログイン中のパスワード変更のみ対応し、忘れた場合の救済は将来課題とする
  - メールアドレスの検証（登録は受け付けるが、確認メール送信は行わない）
  - 市場データの増分（差分日付のみ）フェッチ最適化。v1は「鮮度切れなら期間全体を再取得してupsert」という単純な方式に留める
  - 本設計内容のdocs/チュートリアル化（別セッションで検討）

---

## データモデル（SQLite、SQLAlchemy ORM）

```
User
  id (PK)
  username (unique, not null)
  email (unique, nullable)
  hashed_password (not null)
  created_at

Holding
  id (PK)
  user_id (FK -> User.id)
  ticker, shares, cost

Strategy
  id (PK)
  user_id (FK -> User.id)
  strategy_name
  strategy_json      -- 既存strategies.jsonの1レコードとほぼ同じ構造をそのままJSON文字列で保持
  created_at

SectorDisplaySetting
  user_id (PK, FK -> User.id)
  visible_json / order_json / height_json   -- 既存の入れ子dict構造をそのままJSON文字列で保持

PriceHistory
  id (PK)
  ticker, date, open, high, low, close, volume
  UNIQUE(ticker, date)
  -- 日次追記。既存日付は上書きせず、新しい日付のみ挿入（時系列蓄積）

FundamentalsSnapshot
  id (PK)
  ticker, snapshot_date, trailing_pe, price_to_book, dividend_yield,
  market_cap, roe_pct, revenue_growth_pct
  UNIQUE(ticker, snapshot_date)
  -- 1日1スナップショットとして追記蓄積。同日分が既にあれば再取得しない

CompanyProfile
  ticker (PK)
  name, name_updated_at              -- fetch_japanese_nameが更新（スクレイピング由来）
  sector, industry, business_summary, profile_updated_at   -- fetch_company_profileが更新（yfinance .info由来）
  -- 取得元が異なる2グループのカラムを1レコードにまとめ、鮮度（*_updated_at）は個別管理。
  -- ほぼ不変のデータのため時系列蓄積はせず最新値のみ保持（TTL切れで該当グループのみ再取得）

TickerNews
  id (PK)
  ticker, title, publisher, link, fetched_at
  UNIQUE(ticker, link)
  -- 取得のたびにyfinanceを叩き、未知の記事（linkで重複判定）のみ追記。
  -- linkが取得できない記事は (ticker, title, publisher) の組でフォールバック重複判定
```

`Holding`はticker/shares/costの3カラムのみと単純なため正規化。`Strategy`/`SectorDisplaySetting`は既存JSONの内部構造（`indicator`/`operator`スキーマ等）が複雑なため、正規化せず1カラムJSONとして保持しPython側で`json.loads`/`dumps`する。

---

## フェーズ1: DB基盤（ユーザー個別データのDB化）

### 目的

`holdings.json`/`strategies.json`/`sector_display_settings.json`のJSONファイル永続化をSQLiteに置き換える。この段階ではまだ認証を導入せず、移行スクリプトが作成する単一のデフォルトユーザーに固定して動作確認する（次フェーズ以降の土台）。

### 実装対象

- `db/engine.py`: SQLAlchemyエンジン（`sqlite:///data/app.db`）・セッション生成・`init_db()`（`Base.metadata.create_all()`）
- `db/models.py`: `User`/`Holding`/`Strategy`/`SectorDisplaySetting`の宣言的モデル
- `portfolio_management/storage.py`: `load_holdings(path)`/`save_holdings(path, holdings)` → `load_holdings(user_id)`/`save_holdings(user_id, holdings)`にシグネチャ変更。関数名・戻り値の形（`list[dict]`）は維持し、呼び出し側の変更を「引数を`HOLDINGS_PATH`から`user_id`に差し替える」だけに留める
- `strategy_builder/storage.py`・`sector_analysis/display_settings.py`も同様の方針でDB化
- `app_tabs/portfolio_tab.py`・`app_tabs/strategy_builder_tab.py`・`app_tabs/qa_tab.py`・`app_tabs/ranking_tab.py`・`app_tabs/sector/tab.py`: `HOLDINGS_PATH`等の定数渡しを`user_id`渡しに変更。この段階では`user_id`はハードコードされたデフォルトユーザーのID（フェーズ3で認証済みユーザーIDに置き換え）
- `scripts/migrate_to_db.py`（一回限り、手動実行）: `init_db()` → 対話的に管理者アカウント（ユーザー名・パスワード・任意のメールアドレス）を作成 → 既存の`holdings.json`/`strategies.json`/`sector_display_settings.json`があればその`user_id`に紐付けてDBへ挿入 → 移行後、元JSONファイルは削除せず`.migrated`拡張子でリネームして温存

### テスト

- `tests/test_db_storage.py`: `sqlite:///:memory:`または`tmp_path`上の一時DBを使い、`load_holdings`/`save_holdings`等のCRUDと、2ユーザー分のデータが互いに混ざらないことを検証
- `tests/test_migrate_to_db.py`: 既存JSON形式からのデータ移行が正しく行われることを検証

---

## フェーズ2: 市場データのDB化

### 目的

`data_api/stock_price_api.py`の各`fetch_*`関数を、DBを鮮度チェック付きの永続キャッシュとして使う**read-through**方式に変更する。全ユーザー・全プロセス再起動をまたいで市場データを共有・蓄積できるようにする。

### 実装対象

- `db/models.py`に`PriceHistory`/`FundamentalsSnapshot`/`CompanyProfile`/`TickerNews`を追加
- `data_api/stock_price_api.py`:
  - `fetch_price_history(ticker, period)`: 対象tickerのDB上の最新日付が「本日から1日以内」ならDBから期間分を組み立てて返す（休場日には無駄な再フェッチが発生し得るが、単純さを優先しv1では許容する）。それより古い/データ無しならyfinanceから取得し`PriceHistory`へupsert（`UNIQUE(ticker, date)`衝突時は無視、既存行は上書きしない）した上でDBから返す
  - `fetch_fundamentals(ticker)`: 当日分の`FundamentalsSnapshot`があれば再利用。無ければyfinanceから取得し新規スナップショット行を追加
  - `fetch_company_profile(ticker)`: `CompanyProfile.profile_updated_at`が一定期間（例: 30日）以内なら再利用。古ければyfinanceから取得し該当カラムのみ更新
  - `fetch_japanese_name(ticker)`: `CompanyProfile.name_updated_at`が一定期間（例: 30日）以内なら再利用。古ければスクレイピングし該当カラムのみ更新
  - `fetch_news(ticker, limit)`: 毎回yfinanceから取得し、未知の記事のみ`TickerNews`へ追記。表示は`TickerNews`から`ticker`の最新`limit`件を返す（fetched_at降順）
  - `fetch_universe_fundamentals(tickers, ...)`: 対象tickerごとに`fetch_fundamentals`相当の鮮度チェックを`map_concurrently`で並行実行した上で、`FundamentalsSnapshot`から対象tickerの最新スナップショットを一括クエリして`DataFrame`を組み立てる。専用のファイルキャッシュ（`common/cache.py`の`universe-<hash>`エントリ）は廃止
  - `fetch_universe_price_histories(tickers, period, ...)`: 同様に鮮度チェックを並行実行した上で`PriceHistory`から一括クエリ。専用ファイルキャッシュ（`universe-prices-<hash>`）は廃止
- `app_tabs/shared.py`: `cached_fetch_price_history`等の`st.cache_data`ラッパーは残すが、DBが恒久的な共有ストアになったことを踏まえてTTLを短縮（同一セッション内の連続rerunで同じDB問い合わせを繰り返さないための薄い前段キャッシュという位置づけに変更）
- `stock_detail/detail.py`はロジック変更不要（内部で呼ぶ`fetch_price_history`等がDB backedになるだけで、`generate_stock_detail`自体の日次ファイルキャッシュ（LLM講評込みの結合ペイロード）はそのまま）

### テスト

- `tests/test_stock_price_api.py`（既存拡張）: yfinance呼び出しをモック化し、「DBに新鮮なデータがあればモック呼び出しがスキップされる」「無ければモックが呼ばれDBへupsertされる」の両分岐を検証。`PriceHistory`の`UNIQUE(ticker, date)`制約により重複日付が増えないことも確認
- `fetch_universe_fundamentals`/`fetch_universe_price_histories`: 一部tickerのみDB鮮度切れのケースで、鮮度切れ分だけ再フェッチされることを検証

---

## フェーズ3: 認証導入

### 目的

`streamlit-authenticator`を用いたログイン・ログアウト・自己サービス新規登録を導入し、フェーズ1で固定していたデフォルトユーザーを実際の認証済みユーザーに置き換える。

### 実装対象

- 依存追加: `streamlit-authenticator`
- 起動時、`User`テーブル全件から`streamlit-authenticator`が要求する`credentials`辞書（`{"usernames": {username: {"name":..., "password": hashed_password, "email":...}}}`）を組み立てる
- `app.py`冒頭、既存の`check_claude_cli_available()`ゲートと同じ並びに**ログインゲート**を追加:
  - `authenticator.login()` → `st.session_state["authentication_status"]`で分岐
  - `True`: サイドバーにログアウトボタン（`authenticator.logout()`）。以降7タブを描画し、`st.session_state["username"]`からDB引き当てた`user_id`を各タブ・`load_holdings`等に配線
  - `False`: `st.error`表示して`st.stop()`
  - `None`（未入力）: ログインフォームのみ表示して`st.stop()`
- **新規登録**: `authenticator.register_user()`ウィジェットをログイン画面に配置。登録成功時、ライブラリの`credentials`辞書に追加されたハッシュ済みパスワードを取り出し、`User`テーブルへINSERT（ライブラリ側の`credentials`はプロセス内のみで、永続化は`User`テーブル側で担当）
- Cookie署名キー（`cookie_key`）は`.streamlit/secrets.toml`に保存し、`app/.gitignore`へ`.streamlit/secrets.toml`を追加。ローカル初回セットアップ手順をREADMEに追記
- パスワード変更（ログイン中）: `authenticator.reset_password()`ウィジェットを追加し、変更後のハッシュ済みパスワードで`User.hashed_password`を更新

### テスト

- `tests/test_auth.py`: DBの`User`一覧から`credentials`辞書を組み立てるロジック、新規登録成功時のDB INSERT、パスワード変更時のDB UPDATEをユニットテストで検証（`streamlit-authenticator`のUIウィジェット自体はテスト対象外）

---

## 横断的な考慮事項

- **ログ**: `common/logging_config.py`のログにユーザー識別情報（username等）を含めるかは本設計では踏み込まない。必要であれば別途検討
- **LLM呼び出しの共有性**: フェーズ3導入後も、Claude Code CLIサブプロセスは全ユーザー共通の単一バックエンドのまま（ユーザーごとの利用量制限等は本設計のスコープ外）
- **`pyproject.toml`**: `sqlalchemy`・`streamlit-authenticator`を`dependencies`に追加
