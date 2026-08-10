# 市場データ定期更新バッチ 設計

## 背景・目的

`price_history`/`fundamentals_snapshots`/`ticker_news` は現状、ユーザーがUI操作（銘柄詳細表示・スクリーニング実行等）した時にオンデマンドで `data_api/stock_price_api.py` の `fetch_price_history`/`fetch_fundamentals`/`fetch_news` がread-through方式で取得・蓄積する仕組みになっている。UNIVERSE廃止により `company_profiles` が対象銘柄の単一の情報源になったことで、これらの銘柄を能動的に定期更新するバッチ処理が実装しやすくなった。

本設計は、(A) `fetch_price_history` に差分取得（既存データがあればその翌日以降のみをyfinanceへ問い合わせる）を追加し、(B) `company_profiles` の全銘柄を対象に `price_history`/`fundamentals_snapshots`/`ticker_news` を更新するバッチスクリプトと、それを起動するWindows用`.bat`を追加する。

## スコープ外

- Windowsタスクスケジューラへの登録作業そのもの（ユーザー自身が行う）。
- `fetch_fundamentals`/`fetch_news` 自体の取得ロジック変更（両者は既に「今日の分が無ければ取得」「毎回取得」という単純な仕様であり、差分取得の概念が無い）。

## A. `fetch_price_history` の差分取得

### 現状

`fetch_price_history` は対象tickerの最新日付が本日から1日以内なら何もせず、それより古い（またはデータが1件も無い）場合は常に `_MAX_FETCH_PERIOD`（5年）分をyfinanceからまとめて取得し、`_upsert_price_history` が「DBに無い日付のみ追加」する。つまり鮮度切れのたびに直近5年分を丸ごと問い合わせている。

### 変更内容

`_fetch_price_history_from_yfinance` に `start_date: datetime.date | None = None` を追加する。`start_date` 指定時は `ticker.history(start=start_date.isoformat())`（その日付以降のみ）、未指定時は従来通り `ticker.history(period=period)`（全量取得）を呼ぶ。ログメッセージは全量取得側の既存フォーマット（`"株価履歴リクエスト: ticker=%s period=%s"`）を変更せず、差分取得側には新しいログ行（`"株価履歴リクエスト（差分）: ticker=%s start_date=%s"`）を追加する。

`fetch_price_history` の鮮度切れ時の分岐を以下のように変更する:
- 当該tickerのデータが1件も無い（`latest_date_str is None`）→ 従来通り `period=_MAX_FETCH_PERIOD` で全量取得（差分の起点が無いため）。
- データはあるが古い（`latest_date_str` はあるが1日超経過）→ **新規**: `latest_date + 1日` を `start_date` として差分取得。

`_upsert_price_history` の「DBに無い日付のみ追加」ロジックは変更不要（取得範囲が変わっても安全に機能する）。

この変更は `fetch_price_history` の外部シグネチャ・戻り値を一切変えない内部実装のみの変更であり、UIタブ・`stock_detail`・`fetch_universe_price_histories` 等の既存呼び出し元はコード変更不要で恩恵を受ける。

### テスト

- 既存の `FakeTicker.history`・`CountingTicker.history`（2箇所）に `start=None` 引数を追加し、モックが新しい呼び出し形（`start=`指定）でも壊れないようにする。
- 新規: 古い日付のPriceHistory行が既にある状態で `fetch_price_history` を呼び、yfinance呼び出しに `start=` が渡され `period=` が渡されないことを検証するテスト。
- 新規: `start_date` が正しく「既存最新日付の翌日」になることを検証するテスト。
- 既存の `test_fetch_price_history_logs_request_and_response`（データ無し銘柄が対象）はログフォーマット不変のため無変更で通る想定。

## B. バッチスクリプト

### `scripts/update_market_data.py`

```
run_update(session_factory=SessionLocal) -> dict
```
が実処理を担う（`scripts/migrate_to_db.py` の個別関数がテストされているのと同じ方針で、この関数を直接テストする）。動作:

1. `setup_logging()`（`common.logging_config`）。
2. `init_db(engine)`（Streamlitアプリを一度も起動していない環境でもスキーマが整った状態を保証する）。
3. `tickers = [p["ticker"] for p in load_all_company_profiles(session_factory=session_factory)]`。
4. price_history → fundamentals → news の順に、それぞれ `map_concurrently(tickers, lambda t: fetch_xxx(t, session_factory=session_factory))` を実行する（`fetch_universe_fundamentals`/`fetch_universe_price_histories` などの既存の一括ヘルパーは使わない。これらは失敗した銘柄の情報を呼び出し元に返さず握りつぶすため、バッチの監視・ログ用途には不向き）。
5. 各フェーズごとに `results` を走査し、`isinstance(value, Exception)` で成功/失敗を分類。失敗した銘柄は `logger.warning("xxx取得失敗: ticker=%s error=%s", ticker, exc)` で個別にログし、フェーズ末尾に `"xxx取得完了: 成功N件 / 失敗M件"` を `logger.info` で出す。
6. 3フェーズ分の `{"price_history": {"success": N, "failed": [...]}, "fundamentals": {...}, "news": {...}}` 相当のサマリー辞書を返す。

`main()` は `run_update()` を呼び、いずれかのフェーズで失敗が1件でもあれば `sys.exit(1)`、無ければ `sys.exit(0)`。

### `scripts/update_market_data.bat`

```bat
@echo off
cd /d %~dp0..
uv run python -m scripts.update_market_data
exit /b %errorlevel%
```

`app/scripts/` からの相対起動でもどこからでも動くよう、バッチ自身のディレクトリから1つ上（`app/`）に移動してから実行する。

### テスト

`tests/test_update_market_data.py`（新規）。既存 `test_stock_price_api.py` と同じ `monkeypatch` + `FakeTicker` 方式で、`fetch_price_history`/`fetch_fundamentals`/`fetch_news` の3関数を直接差し替えて以下を検証する:

- `company_profiles` に登録された全tickerに対して各fetch関数が呼ばれること。
- いずれかのtickerで例外が発生しても他のtickerの処理が継続し、`run_update()` の戻り値に失敗として記録されること。
- 全て成功した場合と一部失敗した場合とで、`main()` の終了コードが0/1に分かれること（`sys.exit` をモックするか、`pytest.raises(SystemExit)` で検証）。

## 自己レビュー

- **プレースホルダ確認**: 無し。
- **整合性確認**: A（差分取得）はBの前提だが、A単体でも既存の全呼び出し元にとって無害な内部最適化として独立して価値がある。実装順はA→Bとする。
- **スコープ確認**: 1つの実装計画にまとめられる規模。
- **曖昧箇所確認**: `start_date` 計算時、`is_fresh` 判定が「1日以内」なので `latest_date+1` は必ず過去日になる（未来日にはならない）ことを確認済み。
