# data_api 外部送受信内容ログ 設計書

## 概要・目的

[2026-07-26-app-logging-design.md](2026-07-26-app-logging-design.md)で`app/logs/`へのログ出力基盤（`common/logging_config.py`）を導入し、`data_api/llm_client.py`・`data_api/stock_price_api.py`にも処理時間（開始/完了/所要時間）のログを追加した。しかし現状は**所要時間のみ**で、実際に外部へ何を送り、何を受け取ったかという内容は記録されない。

Claude CLIへのプロンプト内容や、yfinance・Yahoo!ファイナンス（日本版）から実際に取得したデータの中身を後から確認できるようにするため、`data_api`配下の各関数に送受信内容そのもののログを追加する。

## スコープ

- v1で実装する:
  - `data_api/llm_client.py::call_llm`: 送信するプロンプト全文・受信した応答テキスト全文をログ
  - `data_api/stock_price_api.py`の全関数（`fetch_price_history`／`fetch_fundamentals`／`fetch_news`／`fetch_japanese_name`）: リクエスト内容・レスポンス内容をログ。226銘柄一括処理で呼ばれる銘柄単位の関数も対象に含める（前回の所要時間ログでは意図的に除外していたが、今回は明示的に含める）
  - データ量の大きいレスポンス（株価履歴OHLCV全件、Yahoo!ファイナンスのHTMLページ全文）も要約せず全件ログする
- v1で実装しない（将来課題）:
  - ログレベルやサイズによる出力制御（今回は無条件で全件出力）
  - `analysis_agents/*.py`・`app_tabs/*.py`など、data_api以外の層への送受信内容ログの拡張

## ログ内容の設計

すべてINFOレベル、`logging.getLogger(__name__)`をそのまま使用。既存の`log_duration`（開始/完了/所要時間）はそのまま残し、それとは別に送受信内容のログ行を追加する。失敗時は`log_duration`が`logger.exception`でスタックトレース込みに記録するため、レスポンスログは**成功時のみ**出力し二重記録を避ける。

### `llm_client.py::call_llm`

- 送信直前: `logger.info("Claude CLIリクエスト: %s", prompt)`
- 成功時（`returncode == 0`）: `logger.info("Claude CLIレスポンス: %s", result.stdout)`
- 現状の「プロンプト本文は機密情報を含みうるため長さのみ記録する」というコメント・実装（`log_duration`のaction文字列に`prompt長=...`のみ含める形）は、本設計により全文記録に変更するため削除する。

### `stock_price_api.py`

`fetch_price_history`・`fetch_fundamentals`・`fetch_news`は`yfinance`ライブラリ経由でHTTP通信の詳細が見えないため、「リクエスト」は関数への入力引数、「レスポンス」は関数の戻り値をログ対象とする。`fetch_japanese_name`のみ`requests`で直接HTTP通信するため、実際のURL・生レスポンステキストをログできる。

| 関数 | リクエストログ | レスポンスログ（成功時のみ） |
| --- | --- | --- |
| `fetch_price_history(ticker_symbol, period)` | `logger.info("株価履歴リクエスト: ticker=%s period=%s", ...)` | `logger.info("株価履歴レスポンス: ticker=%s data=%s", ticker_symbol, df.to_json(orient="records", date_format="iso"))` |
| `fetch_fundamentals(ticker_symbol)` | `logger.info("fundamentalsリクエスト: ticker=%s", ...)` | `logger.info("fundamentalsレスポンス: ticker=%s data=%s", ticker_symbol, result)`（`result`は戻り値の辞書） |
| `fetch_news(ticker_symbol, limit)` | `logger.info("newsリクエスト: ticker=%s limit=%s", ...)` | `logger.info("newsレスポンス: ticker=%s data=%s", ticker_symbol, result)`（`result`は戻り値のリスト） |
| `fetch_japanese_name(ticker_symbol)` | `logger.info("日本語銘柄名リクエスト: url=%s", url)` | 成功時: `logger.info("日本語銘柄名レスポンス: url=%s body=%s", url, response.text)`。通信失敗時（`RequestException`）: `logger.warning("日本語銘柄名取得失敗: url=%s", url)` |

`fetch_universe_fundamentals`は内部で`fetch_fundamentals`を`map_concurrently`経由で最大226回呼ぶため、`fetch_fundamentals`自体にリクエスト/レスポンスログを追加すれば、一括処理1回あたり最大452行（226銘柄 × リクエスト/レスポンス各1行）がログに追加される。これは前回の所要時間ログ設計で意図的に除外していた挙動だが、本機能では明示的に許容する。

## テスト方針

- 既存のテスト（`tests/test_llm_client.py`・`tests/test_stock_price_api.py`）に、`caplog`でリクエスト/レスポンスの内容がログに含まれることを検証するテストを追加する
  - `call_llm`: 送信したプロンプト文字列・受信したレスポンス文字列がそれぞれログに含まれることを確認
  - `fetch_price_history`/`fetch_fundamentals`/`fetch_news`: 呼び出し引数（ticker等）とレスポンス内容の一部（例: 特定のフィールド値）がログに含まれることを確認
  - `fetch_japanese_name`: 送信URL・受信したHTMLレスポンス文字列がログに含まれることを確認
- 手動確認: `uv run python -m streamlit run app.py`でいずれかのタブを操作し、`app/logs/app.log`にプロンプト全文・取得データ全件が記録されることを目視確認する

## v1スコープ外（将来課題）

- ログサイズに応じた出力制御（切り詰め・レベル分離など）
- data_api以外の層（analysis_agents、app_tabs等）への送受信内容ログの拡張
