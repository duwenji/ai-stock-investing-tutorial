# ログ出力機能 設計書

## 概要・目的

本アプリ（`ai-stock-investing-tutorial/app`）には現時点でロギングの仕組みが無く、`st.error`によるユーザー向けエラー表示以外に処理の記録が残らない。株価/ニュース取得（yfinance・Yahoo!ファイナンス日本版スクレイピング）やClaude Code CLIサブプロセス呼び出しなど外部依存が多く、動作が遅い・失敗する場合に「どのタブの、どの処理が、どれくらいの時間でどうなったか」を後から追跡できるようにするため、`app/logs/`配下にファイルベースのログ出力を追加する。

対象読者は開発者本人（個人利用アプリ）であり、Streamlitのターミナル出力とは分離してファイルに記録することで、後からゆっくり見返せるようにすることを主眼とする。

## スコープ

- v1で実装する:
  - `common/logging_config.py`（新設）: `setup_logging()`（ルートロガーへの日次ローテーションファイルハンドラ設定、冪等）と`log_duration()`（開始/完了/失敗を記録するcontextmanager）
  - `app.py`冒頭での`setup_logging()`呼び出し
  - 以下の各層への`logger = logging.getLogger(__name__)`とログ呼び出しの追加（詳細は「呼び出し箇所一覧」参照）
    - `app_tabs/*_tab.py`・`app_tabs/sector/tab.py`: タブ表示・主要ボタン操作
    - `data_api/llm_client.py`・`data_api/stock_price_api.py`（`fetch_universe_fundamentals`のみ）: 外部I/O
    - `common/cache.py`: キャッシュのヒット/ミス/書き込み
    - `portfolio_management/backtest.py`・`sector_analysis/correlation.py`・`sector_analysis/wavelet.py`・`stock_detail/detail.py`: 分析・バックテスト処理
  - `.gitignore`に`logs/`を追加
- v1で実装しない（将来課題）:
  - ログレベルの環境変数による切り替え（今回はINFO固定）
  - コンソール（ターミナル）への同時出力
  - `analysis_agents/*.py`や`stock_price_api.py`の銘柄単体取得関数（`fetch_price_history`等）への個別ログ付与（理由は「対象外とする箇所」参照）
  - ログの構造化（JSON Lines化）・外部ログ収集サービスとの連携

## 基盤設計 — `common/logging_config.py`

`portfolio_management/storage.py`や`sector_analysis/display_settings.py`と同様、ファイルパスを引数で受け取れる形にしてテスト容易性を確保する。

```python
"""アプリ全体のロギング設定。app/logs/配下への日次ローテーションファイル出力と、
処理の開始/完了/所要時間を一箇所で記録するためのcontextmanagerを提供する。"""

import logging
import time
from contextlib import contextmanager
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(log_dir: Path = LOG_DIR) -> None:
    """ルートロガーにファイルハンドラを設定する。

    Streamlitはユーザー操作のたびにapp.pyを再実行するため、この関数も
    そのたびに呼ばれる。ハンドラが既に設定済みなら何もせず、重複登録
    （＝ログの多重出力）を防ぐ。
    """
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    log_dir.mkdir(parents=True, exist_ok=True)
    handler = TimedRotatingFileHandler(
        log_dir / "app.log",
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))

    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)


@contextmanager
def log_duration(logger: logging.Logger, action: str):
    """actionの開始・完了（所要時間付き）をINFOログに、例外発生時は
    所要時間付きでERRORログ（スタックトレース込み）に記録する。
    例外は再送出し、呼び出し元の既存のエラーハンドリング（st.error等）は変えない。
    """
    logger.info("%sを開始", action)
    start = time.perf_counter()
    try:
        yield
    except Exception:
        elapsed = time.perf_counter() - start
        logger.exception("%sが失敗しました（%.2f秒）", action, elapsed)
        raise
    else:
        elapsed = time.perf_counter() - start
        logger.info("%sが完了しました（%.2f秒）", action, elapsed)
```

`app.py`冒頭（`import streamlit as st`の直後）で1回呼ぶ:

```python
from common.logging_config import setup_logging

setup_logging()
```

## ログファイルの配置・ローテーション

- 保存先: `app/logs/app.log`（`LOG_DIR`は`common/logging_config.py`から見て`app/logs`を指す）
- `TimedRotatingFileHandler(when="midnight", backupCount=30)`により、日付が変わるタイミングで`app.log`が`app.log.YYYY-MM-DD`にリネームされ、31日目以降の最古のファイルは自動削除される
- フォーマット: `2026-07-26 10:00:00,000 [INFO] app_tabs.backtest_tab: バックテスト実行を開始`
- `.gitignore`に`logs/`を追加（`data/`と同様の扱い）

## 呼び出し箇所一覧

### 各タブの主要操作（`app_tabs/`）

| ファイル | 追加箇所 | 内容 |
| --- | --- | --- |
| `backtest_tab.py` | `render_backtest_tab`冒頭 | `logger.info("バックテストタブを表示")` |
| 〃 | `st.button("バックテストを実行")`のif節内 | `with log_duration(logger, f"バックテスト実行（{backtest_ticker}, {backtest_strategy}）")`で`run_backtest_comparison`〜解説生成までを包む |
| `ranking_tab.py` | `render_ranking_tab`冒頭 | `logger.info("一括バックテストタブを表示")` |
| 〃 | `if payload is None:`ブロック（株価取得〜ランキング計算） | `log_duration(logger, f"一括バックテスト実行（{ranking_strategy}, {len(target_tickers)}銘柄）")`で包む |
| `portfolio_tab.py` | `render_portfolio_tab`冒頭 | `logger.info("ポートフォリオタブを表示")` |
| 〃 | `if payload is None:`ブロック（データ取得〜レビュー生成） | `log_duration(logger, f"ポートフォリオレビュー生成（{len(holdings)}銘柄）")`で包む |
| `screening_tab.py` | `render_screening_tab`冒頭 | `logger.info("スクリーニングタブを表示")` |
| 〃 | `st.button("この条件で絞り込む")`のif節内 | `log_duration(logger, "スクリーニング絞り込み実行")`で包む |
| `sector/tab.py` | `render_sector_tab`冒頭 | `logger.info("セクターローテーションタブを表示")` |
| 〃 | `if payload is None:`ブロック（株価取得〜コメント生成） | `log_duration(logger, f"セクターローテーション分析実行（{sector_period}）")`で包む |

各タブのエラー分岐（例: `st.error(...)`を呼んでいる箇所）には、直前・直後に`logger.warning(...)`を追加し、エラー内容をログにも残す（例: `backtest_tab.py`のデータ不足エラー、`ranking_tab.py`/`sector/tab.py`の「対象銘柄が0件」エラー、`screening_tab.py`のJSON解析失敗）。

### 外部I/O（`data_api/`）

| ファイル | 関数 | 内容 |
| --- | --- | --- |
| `llm_client.py` | `call_llm` | `log_duration(logger, f"Claude CLI呼び出し（prompt長={len(prompt)}）")`で`subprocess.run`を包む。プロンプト本文は出力しない（機密情報・長大なJSONを含みうるため） |
| `stock_price_api.py` | `fetch_universe_fundamentals` | `log_duration(logger, f"ユニバースfundamentals一括取得（{len(tickers)}銘柄）")`で`map_concurrently`呼び出しを包む。キャッシュヒット時は`common/cache.py`側のログで足りるため、ここでの追加ログは不要 |

### キャッシュのヒット/ミス（`common/cache.py`）

| 関数 | 内容 |
| --- | --- |
| `read_cache` | ヒット時: `logger.info("キャッシュヒット: %s", key)` / ミス（ファイル不在）時: `logger.info("キャッシュミス: %s", key)` |
| `write_cache` | `logger.info("キャッシュ書き込み: %s", key)` |

### 分析・バックテスト処理

| ファイル | 関数 | 内容 |
| --- | --- | --- |
| `portfolio_management/backtest.py` | `run_backtest_comparison` | `log_duration(logger, f"バックテスト比較計算（プリセット{len(presets)}件）")`で本体を包む |
| 〃 | `run_universe_backtest_ranking` | `log_duration(logger, f"ユニバース一括バックテスト（{len(prices_by_ticker)}銘柄）")`で本体を包む |
| `sector_analysis/correlation.py` | `compute_sector_returns` | `log_duration(logger, "業種別リターン集計")`で本体を包む |
| 〃 | `compute_lead_lag_pairs` | `log_duration(logger, f"リード・ラグ相関計算（{len(sector_returns)}業種）")`で本体を包む |
| `sector_analysis/wavelet.py` | `compute_all_pairs_dominant_lag` | `log_duration(logger, f"ウェーブレット全ペア計算（{len(sector_returns)}業種）")`で本体を包む |
| `stock_detail/detail.py` | `generate_stock_detail` | `log_duration(logger, f"銘柄詳細生成（{ticker}）")`でキャッシュミス後の取得〜LLM呼び出しブロックを包む |

### 対象外とする箇所（意図的な除外）

| 箇所 | 除外理由 |
| --- | --- |
| `analysis_agents/*.py`（fundamental/technical/news_research） | `portfolio_tab.py`の`_fetch_holding_data`や`stock_price_api.py`内で保有銘柄・ユニバース銘柄ごとに`map_concurrently`で繰り返し呼ばれる（最大226回/回）。個別にログを仕込むとログファイルが1回の分析実行で数百行単位に膨れ、「流れを追う」目的に対してノイズになる |
| `stock_price_api.py`の`fetch_price_history`・`fetch_fundamentals`・`fetch_news`・`fetch_japanese_name` | 同上。`ranking_tab.py`/`sector/tab.py`では`map_concurrently(target_tickers, ...)`で最大226回呼ばれる。バッチ側（呼び出し元のタブ、または`fetch_universe_fundamentals`）で1回だけ集計ログを出す方針とする |

## テスト方針

- `tests/test_logging_config.py`（新設）:
  - `setup_logging(log_dir=tmp_path)`呼び出し後、`tmp_path/app.log`が作成され、ログメッセージが書き込まれることを確認
  - `setup_logging`を2回連続で呼んでも、ルートロガーのハンドラ数が1のままであること（冪等性）を確認
  - テスト間でロガー状態が汚染されないよう、各テストの前後でルートロガーのハンドラをクリアするfixtureを用意する
  - `log_duration`が正常終了時に開始/完了のINFOログを記録すること、例外発生時に開始/失敗のログ（`logger.exception`相当）を記録しつつ元の例外を再送出することを、`caplog`で検証
- 既存の各モジュールへのログ呼び出し追加自体は、ログ出力の有無がテストの成否に影響しないよう既存テストへの影響はない想定（ログはassertion対象にしない）。念のため`uv run pytest`を実行し既存テストがすべて通ることを確認する
- 手動確認: `uv run python -m streamlit run app.py`で各タブを一通り操作し、`app/logs/app.log`に想定通りの行（タブ表示・処理開始/完了・キャッシュヒット/ミス）が記録されることを目視確認する

## v1スコープ外（将来課題）

- ログレベルを環境変数（例: `LOG_LEVEL`）で切り替えられるようにする
- ターミナルへの同時出力（開発時の即時確認用）
- 銘柄単位の詳細ログ（現状は意図的に除外。必要になった場合はサンプリングやDEBUGレベル分離を別途検討）
- ログの構造化・外部ログ収集基盤への連携
