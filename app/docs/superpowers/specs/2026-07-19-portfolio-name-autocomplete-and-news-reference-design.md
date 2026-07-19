# ポートフォリオ銘柄名オートコンプリート & ニュース参照機能 設計書

## 概要・目的

既存の[ポートフォリオ管理・スクリーニング統合アプリ](2026-07-19-portfolio-screening-app-design.md)に対する2つの改善。

1. 保有銘柄ポートフォリオでティッカーコードを手入力する際、銘柄名を自動補完できるようにする。現状は `st.data_editor` にティッカーコードを直接手入力するのみで、銘柄名は一切表示されない。
2. ポートフォリオレビューが提示するニュースセンチメント判定（ポジティブ/ニュートラル/ネガティブ）について、その根拠となった収集ニュース（見出し・発行元）を参照できるようにする。現状は `research_news_batch` が判定に使うだけで、収集した生ニュースはUIのどこにも表示されない。

対象は既存アプリのポートフォリオタブのみ。スクリーニングタブは対象外。

## 機能1: 銘柄名オートコンプリート

### 候補範囲

- `screening/universe.py` の `UNIVERSE`（主要44銘柄）+ 現在保有中の銘柄（`holdings.json`）を候補とする。
- 任意の未知ティッカーを動的に名前解決する機能は対象外（都度API呼び出しが発生し応答が遅くなるため）。
- ティッカーコード自体は自由入力欄のまま維持し、候補にない銘柄も引き続き手入力で保有登録できる。

### データ

`screening/universe.py` に `UNIVERSE_NAMES: dict[str, str]` を追加する（ティッカー→銘柄名）。既存の44銘柄の名前はソースコード中のコメントとして既に存在するため、それを実データ化するだけで済む。既存の `UNIVERSE`（`list[str]`、スクリーニング機能で使用中）は変更しない。

### 候補統合ロジック（新規 `portfolio_management/ticker_names.py`）

```python
def build_candidate_names(
    holdings: list[dict],
    universe_names: dict[str, str] = UNIVERSE_NAMES,
    fetch_fundamentals=default_fetch_fundamentals,
) -> dict[str, str]:
    ...
```

- `universe_names` をベースに、`holdings` 内のティッカーで `universe_names` に無いものがあれば `fetch_fundamentals(ticker)["name"]` で名前解決して追加する。
- 名前解決に失敗した場合（`None` が返る場合）はそのティッカーを候補から除外する（UI側で空欄表示にする必要をなくす）。
- 純粋関数として実装し、`fetch_fundamentals` を差し替え可能にすることで既存のテストパターン（`fetch_universe_fundamentals` と同様）を踏襲する。

`app.py` 側では `st.cache_data(ttl=60 * 60 * 24)` で `fetch_fundamentals` 相当の名前解決をラップし、同一ティッカーへの再フェッチを防ぐ。

### UI変更（`app.py` ポートフォリオタブ）

1. 保有銘柄をセッション状態 `st.session_state["holdings_rows"]` で管理する（初回のみ `load_holdings()` から初期化）。これは「検索して追加」ボタンから外部的に行を追加するために必要。
2. 表の上に「銘柄を検索して追加」の `st.selectbox`（選択肢は `"7203.T トヨタ自動車"` の形式。コード・名前どちらの部分文字列でも絞り込み可能というStreamlit標準の挙動を利用）＋「追加」ボタンを設置する。選択して追加すると `{"ticker": ..., "shares": 0, "cost": 0.0}` が `holdings_rows` に追加される（既に同一ティッカーがあれば追加せず `st.info` で通知）。
3. `holdings_rows` から作る DataFrame に読み取り専用の「銘柄名」列を追加する（`candidate_names.get(ticker, "")` で算出、`st.column_config.TextColumn(disabled=True)`）。
4. `st.data_editor` の列順は `ticker, 銘柄名, shares, cost` とする。
5. 「保有銘柄を保存」ボタン押下時は、保存対象から「銘柄名」列を除外し、従来通り `ticker/shares/cost` のみを `holdings.json` に書き込む。保存後 `st.session_state["holdings_rows"]` も更新する。

### 既知の制限

- ティッカー列を検索ボックス経由でなく直接手打ちで書き換えた場合、「銘柄名」列はそのリビジョンでは古い値を表示し続け、次の操作（保存・追加など、Streamlitの再実行契機）で更新される。運用上は検索ボックスからの追加が主な使い方になる想定であり、許容する。

## 機能2: 収集ニュースの参照

### データ取得の拡張（`data_api/stock_price_api.py`）

`fetch_news` の返却する各ニュース項目に `"link": item.get("link")` を追加する（記事URLを保持し、UIでクリック可能にするため）。

### キャッシュ形式の変更（`app.py`）

現状、ポートフォリオレビューのキャッシュ（`common/cache.py` 経由）はレポート本文（Markdown文字列）のみを保存している。これを次のJSON構造に変更する。

```json
{
  "report": "<Markdown文字列>",
  "news_by_ticker": {"7203.T": [{"title": ..., "publisher": ..., "link": ...}, ...]},
  "news_sentiment_by_ticker": {"7203.T": {"sentiment": "ポジティブ", "confidence": 0.7}}
}
```

理由: キャッシュヒット時にニュースを再取得すると、その時点の最新ニュース（表示用）とキャッシュされたレポート中のセンチメント判定（生成当時のニュースに基づく）がずれてしまう。生成時に使ったニュースをレポートと一緒に保存することで、表示内容の整合性を保つ。

`common/cache.py` 自体（`read_cache`/`write_cache`）は文字列を扱う汎用ヘルパーのままとし、変更しない。JSON化・パースは `app.py` 側の呼び出しコードで行う。

### UI変更

- `st.markdown(report)` の下に「参照ニュース」セクションを追加する。
- 保有銘柄ごとに `st.expander(f"{ticker} の参照ニュース（センチメント: {sentiment_label}）")` を設置する。
- 展開内には各ニュースをタイトル・発行元の箇条書きで表示し、`link` があればタイトルをMarkdownリンクにする。
- ニュースが0件の銘柄は「ニュースが取得できませんでした。」と表示する。

## テスト方針

- `tests/test_universe.py`: `UNIVERSE_NAMES` が `UNIVERSE` の全ティッカーを過不足なく網羅していることを検証するテストを追加する。
- 新規 `tests/test_ticker_names.py`: `build_candidate_names` について、(1) UNIVERSE内銘柄の名前がそのまま候補に入ること、(2) UNIVERSE外の保有銘柄が `fetch_fundamentals` 経由で解決されること、(3) 名前解決に失敗した銘柄が候補から除外されること、(4) UNIVERSE内の名前が優先され保有銘柄側の解決結果で上書きされないこと、をテストする（`fetch_fundamentals` はフェイク関数に差し替え）。
- `tests/test_stock_price_api.py`: `test_fetch_news_returns_title_and_publisher` を更新し、`link` フィールドが結果に含まれることを検証する（`FakeTicker.news` フィクスチャに `link` キーを追加）。
- `app.py` はロジックを持たせずテスト可能な関数への薄い呼び出しに留める既存方針を踏襲するため、UI変更自体は自動テスト対象外とし、`streamlit run app.py` での手動確認で検証する。

## v1スコープ外（将来課題）

- 任意ティッカーの動的名前解決によるオートコンプリート候補の拡張
- ニュース本文の全文表示・要約（現状は見出し・発行元・リンクのみ）
- ニュースセンチメントの履歴比較（日をまたいだ推移表示）
