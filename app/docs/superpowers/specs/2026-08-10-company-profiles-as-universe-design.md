# company_profiles を銘柄ユニバースの単一情報源にする 設計

## 背景・目的

`screening/universe.py`（`UNIVERSE`・`UNIVERSE_NAMES`）と `screening/sectors.py`（`SECTOR_MAP`）は、日経225+既存銘柄・約228銘柄のティッカー一覧、日本語名、東証17業種区分を、それぞれ独立したPython辞書として手動維持している。これらは同じ約228銘柄を3つの並行した手作業データとして持ち、更新時は互いに同期する必要がある（`sectors.py`冒頭に「UNIVERSE更新時はこのファイルも合わせて更新すること」というコメントがある通り）。

一方、直近の company_profiles 外部キー導入作業により、`company_profiles` テーブルは `ticker`（主キー）・`name`・`sector`・`industry`・`business_summary` を持つ、全ユーザー共有の銘柄マスタとして既に機能し始めている（price_history/fundamentals_snapshots/ticker_news/holdings への書き込み時に自動でスタブ行が作られる）。

本設計は、`UNIVERSE`/`UNIVERSE_NAMES`/`SECTOR_MAP` を廃止し、`company_profiles` を「アプリが分析対象とする銘柄」の単一の情報源にする。銘柄の追加・分類は今後 `company_profiles` への手動データ投入（管理者CRUD画面での編集、または本設計で追加するシードデータ）で行う。スクリーニング/ランキング/戦略ビルダー/セクターローテーションが対象銘柄を絞り込みすぎず、`company_profiles` に存在する銘柄であれば無関係なもの（例: 過去に一度だけ検索された銘柄）が混ざっても許容する（ユーザー確認済み）。

## スコープ外

- `company_profiles.sector`/`.industry`（yfinance由来のグローバルな業種分類）は変更しない。今回追加する `sector_jp`（東証17業種区分）とは別軸のまま併存する。
- スクリーニング/ランキング/戦略ビルダー/セクターローテーションの機能自体（UI・ロジック）は変更しない。対象銘柄の取得元を差し替えるのみ。
- 定期自動更新スケジューラ（別途検討中）は本設計に含まない。

## 1. データモデル・シードデータ

### 1.1 `company_profiles.sector_jp` 列の追加

`db/models.py::CompanyProfile` に `sector_jp: Mapped[str | None] = mapped_column(nullable=True)` を追加する（東証17業種区分。`sector`/`industry`とは別の列）。

既存DBへの反映は、FK追加時に確立した「軽量マイグレーション」パターンではなく、`users.is_admin`追加と同じ `ALTER TABLE ADD COLUMN` パターンを使う（FKを伴わない単純な列追加のため、テーブル再作成は不要）。`db/engine.py::init_db()` に `_ensure_company_profile_sector_jp_column(engine)` を追加し、`_ensure_admin_column` と同様に `PRAGMA table_info(company_profiles)` で確認して無ければ追加する。

### 1.2 シードデータファイル

現行の `UNIVERSE_NAMES`（228銘柄のticker→日本語名）と `SECTOR_MAP`（228銘柄のticker→東証17業種）を、`app/db/seed_company_profiles.csv`（列: `ticker,name,sector_jp`）という静的データファイルに変換する。このファイルはリポジトリにコミットし、`screening/universe.py`/`screening/sectors.py` 削除後も残す。

**配置場所の注意**: `app/.gitignore` は `data/` を丸ごとランタイムデータとして除外している（`app.db`・キャッシュ等）。`app/data/` 配下に置くと誤ってgit管理外になりコミットされないため、シードファイルは読み込み元の `db/engine.py` と同じ `app/db/` 配下に置く。

### 1.3 シード投入ロジック

`db/engine.py::init_db()` の最後に `_seed_default_company_profiles(engine)` を追加する。動作:

1. `app/db/seed_company_profiles.csv` を読み込む。
2. 各行について、`company_profiles` に該当tickerの行が無ければ `(ticker, name, sector_jp)` で新規作成する。
3. 該当tickerの行が既にあるが `name`/`sector_jp` が `NULL` の場合（例: `ensure_company_profile_stub` が作ったスタブ行、または今回のFK移行で孤児tickerとして補完された行）は、`NULL` のフィールドのみシード値で埋める。既に値が入っている列（実際にyfinanceから取得済みの値や管理者が編集した値）は上書きしない。

この設計により、新規インストール（空DB）でも、今回のFK移行を経た既存DB（一部tickerが既にスタブ行として存在する状態）でも、同じロジックで正しく補完される。

### 1.4 データ整合性テストの移設

`tests/test_universe.py`/`tests/test_sectors.py` が検証していた不変条件（228件・重複無し・`.T`サフィックス・名前がすべて非空・17業種が過不足なくカバーされている等）を、新しい `tests/test_seed_company_profiles.py` で `seed_company_profiles.csv` に対して検証するテストに置き換える。

## 2. 共有クエリヘルパー・管理者CRUD

### 2.1 `load_all_company_profiles`

`data_api/stock_price_api.py` に追加:

```python
def load_all_company_profiles(session_factory=SessionLocal) -> list[dict]:
    """company_profilesの全行をticker順で返す（UNIVERSEの代替として、
    アプリが分析対象とする銘柄一覧の単一の情報源として使う）。"""
```

戻り値は `{"ticker", "name", "sector_jp", "sector", "industry", "business_summary"}` の辞書のリスト。以降の全呼び出し箇所はこの関数経由で対象銘柄を取得する。

### 2.2 管理者CRUD（`admin_tab.py`）への `sector_jp` 追加

`load_company_profile`/`save_company_profile_fields` に `sector_jp` を追加し、`_render_market_data_management` の企業プロファイルフォームに `sector_jp`（東証17業種区分）の `st.text_input` を1つ追加する。これにより、シードデータに含まれない新規銘柄も管理者が手動で東証17業種を分類できる。

## 3. 呼び出し箇所の置き換え・ファイル削除・テスト方針

### 3.1 置き換え対象

| ファイル | 現状 | 変更後 |
| --- | --- | --- |
| `app_tabs/screening_tab.py` | `UNIVERSE`/`UNIVERSE_NAMES`/`SECTOR_MAP` | `load_all_company_profiles()` から ticker一覧・name辞書（nameがNoneでないもののみ）・sector_jp辞書（sector_jpがNoneでないもののみ）を組み立てて使用 |
| `app_tabs/ranking_tab.py` | `set(UNIVERSE) \| set(holdings_tickers)` | `set(全ticker) \| set(holdings_tickers)` |
| `app_tabs/strategy_builder_tab.py` | `UNIVERSE`（2箇所）・`SECTOR_MAP`（4箇所） | 同上のticker一覧・sector_jp辞書に置き換え |
| `app_tabs/shared.py`（セクターローテーション） | `UNIVERSE`・`SECTOR_MAP` | **`sector_jp` が設定されているtickerのみ**を対象にする（セクター分析はそもそも分類が無い銘柄をバケット化できないため。かつ、無関係な保有銘柄追加のたびに対象集合＝日次キャッシュキーが変動するのを避ける） |
| `portfolio_management/ticker_names.py::build_candidate_names` | 引数 `universe_names: dict = UNIVERSE_NAMES`（モジュール定数のデフォルト引数） | 引数名を `known_names: dict \| None = None` に変更し、未指定時は `load_all_company_profiles()` から遅延構築（DBクエリなのでモジュール読み込み時の定数にはできないため） |

### 3.2 削除

- `screening/universe.py`
- `screening/sectors.py`
- `tests/test_universe.py`
- `tests/test_sectors.py`（不変条件は1.4の新テストに移設済み）

### 3.3 テスト方針

`screening_tab.py`/`ranking_tab.py`/`strategy_builder_tab.py`/`app_tabs/shared.py` は現状ユニットテストが無い（Streamlit UI層のため）。自動テストで担保するのは以下:

- `tests/test_ticker_names.py`: 引数名変更（`universe_names=` → `known_names=`）に追従。既存4件は明示的に辞書を渡しているため動作は変わらない。デフォルト値（未指定時に`load_all_company_profiles()`を呼ぶ経路）の新規テストを1件追加する。
- `tests/test_seed_company_profiles.py`（新規、1.4）
- `tests/test_db_engine.py`: `sector_jp`列追加マイグレーション、シード投入ロジック（新規/既存/一部NULL埋めの3パターン）のテストを追加。
- `data_api/stock_price_api.py`: `load_all_company_profiles`・`sector_jp`を含む`save_company_profile_fields`/`load_company_profile`のテストを追加。

上記4タブファイルについては自動テストが無いため、実装後に `streamlit run app.py` を起動し、スクリーニング・ランキング・戦略ビルダー・セクターローテーションの各タブを実際に操作して回帰が無いことを目視確認する。

## 未解決事項

なし（設計は3セクションともユーザー承認済み）。
