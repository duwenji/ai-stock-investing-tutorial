# 銘柄詳細情報のキャッシュをDBと整合させる 設計書

## 概要・目的

管理者機能フェーズCの手動確認中、管理者タブの「市場データ管理」で銘柄詳細ダイアログと異なるデータが表示される現象が見つかった。原因は`stock_detail/detail.py`の`generate_stock_detail`が、株価履歴・fundamentals・ニュース・企業プロファイルの「生データ」を`comment`（LLM講評）ごと1つの日次ファイルキャッシュ（`stock-detail-{ticker}`）にまとめて保持しており、このキャッシュがフェーズ2で導入したDB read-through方式（`fetch_price_history`等が持つ適切な鮮度管理）より古い日付・別経路で作られている場合、DBの実データと食い違って見えることにある。

本設計は、生データのキャッシュをこのファイルキャッシュから除去し、フェーズ2のDB read-through方式に一本化する。LLM講評コメントのみ、コストが高いため引き続き軽量な日次ファイルキャッシュに残す。

## スコープ

- v1で実装する:
  - `generate_stock_detail`から生データの結合キャッシュ（`stock-detail-{ticker}`、旧形式マイグレーション判定含む）を削除し、`fetch_price_history`/`analyze_fundamentals`/`fetch_news`/`fetch_company_profile`を毎回直接呼ぶ
  - LLM講評（`comment`・`profile_comment`）のみ、`stock-detail-comment-{ticker}`という別キーで日次ファイルキャッシュする
  - `app_tabs/shared.py`の`show_stock_detail_dialog`が使う`fetch_news`を、`data_api.stock_price_api.fetch_news`（毎回yfinance）から`cached_fetch_news`（60秒の薄い前段キャッシュ）に差し替える（ダイアログの連続オープンでの過剰リクエストを抑える）
- v1で実装しない（将来課題）:
  - `fetch_price_history`/`analyze_fundamentals`/`fetch_company_profile`についても同様に薄い前段キャッシュ（`cached_fetch_price_history`等）を`generate_stock_detail`に適用すること（今回はDB read-through自体の整合性回復が目的のため、追加の前段キャッシュ導入はスコープ外）

## 実装対象

- `stock_detail/detail.py`: `generate_stock_detail`を全面改修。生データキャッシュ（`read_cache`/`write_cache`呼び出しと旧形式判定ロジック）を削除し、LLM講評2件のみを`{"comment": ..., "profile_comment": ...}`としてキャッシュする形に変更
- `app_tabs/shared.py`: `show_stock_detail_dialog`内の`generate_stock_detail(...)`呼び出しに`fetch_news=cached_fetch_news`を追加

## テスト方針

- `tests/test_stock_detail.py`: 生データキャッシュの旧形式マイグレーション判定を検証していた3テスト（`test_generate_stock_detail_ignores_stale_cache_missing_ohlcv`/`_missing_profile`/`_missing_technical_series`）は該当ロジックが無くなるため削除する。キャッシュ挙動を検証するテストは「2回目呼び出しでLLMは呼ばれないが、生データ取得関数は呼ばれる」ことを検証する形に書き換える
- `app_tabs`配下のUI結線部分（`show_stock_detail_dialog`の呼び出し引数変更）はユニットテスト対象外（既存の慣習どおり）
