# ログ出力機能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `app/logs/`配下に日次ローテーションのログファイルを出力し、各タブの主要操作・外部I/O（LLM・株価API）・キャッシュのヒット/ミス・分析/バックテスト処理の「開始/完了（所要時間）」を追跡できるようにする。

**Architecture:** 新規モジュール`common/logging_config.py`に、ルートロガーへの`TimedRotatingFileHandler`設定（`setup_logging`, 冪等）と、開始/完了/失敗をワンライナーで記録するcontextmanager（`log_duration`）を実装する。既存の各モジュール（`common/cache.py`, `data_api/*.py`, `portfolio_management/backtest.py`, `sector_analysis/*.py`, `stock_detail/detail.py`, `app_tabs/*.py`）に`logger = logging.getLogger(__name__)`と`log_duration`呼び出しを追加する。頻繁に（銘柄単位で最大226回）呼ばれる関数（`analysis_agents/*.py`、`stock_price_api.py`の単体取得関数）はログ量が膨れるため対象外とする。

**Tech Stack:** Python標準ライブラリ`logging`のみ（新規pip依存追加なし）。pytest（`caplog`, `tmp_path`）。

## Global Constraints

- 新規pip依存を追加しない（`logging`は標準ライブラリ）
- ログレベルはINFO固定（環境変数での切り替えはv1スコープ外、[design doc](../specs/2026-07-26-app-logging-design.md)参照）
- コンソール（ターミナル）への出力はしない。ファイル（`app/logs/app.log`）のみ
- `TimedRotatingFileHandler(when="midnight", backupCount=30)`で日次ローテーション・30日保持
- `analysis_agents/*.py`と`data_api/stock_price_api.py`の単体取得関数（`fetch_price_history`/`fetch_fundamentals`/`fetch_news`/`fetch_japanese_name`）にはログを追加しない（`map_concurrently`で最大226回呼ばれログが膨れるため。design doc「対象外とする箇所」参照）
- `app_tabs/`配下のUI変更に自動テストは書かない（既存プロジェクト方針どおり、`uv run python -m streamlit run app.py`での手動確認とする）
- テスト実行コマンド: `uv run pytest -v`（作業ディレクトリは`ai-stock-investing-tutorial/app`）

---

## File Structure

- Create: `common/logging_config.py` — `setup_logging()` / `log_duration()`
- Test: `tests/test_logging_config.py`
- Modify: `app.py` — `setup_logging()`呼び出し追加
- Modify: `.gitignore` — `logs/`追加
- Modify: `common/cache.py` — キャッシュヒット/ミス/書き込みログ／Modify: `tests/test_cache.py`
- Modify: `data_api/llm_client.py` — `call_llm`の`log_duration`化／Modify: `tests/test_llm_client.py`
- Modify: `data_api/stock_price_api.py` — `fetch_universe_fundamentals`の`log_duration`化／Modify: `tests/test_stock_price_api.py`
- Modify: `portfolio_management/backtest.py` — `run_backtest_comparison`/`run_universe_backtest_ranking`の`log_duration`化／Modify: `tests/test_backtest.py`
- Modify: `sector_analysis/correlation.py` — `compute_sector_returns`/`compute_lead_lag_pairs`の`log_duration`化／Modify: `tests/test_sector_correlation.py`
- Modify: `sector_analysis/wavelet.py` — `compute_all_pairs_dominant_lag`の`log_duration`化／Modify: `tests/test_sector_wavelet.py`
- Modify: `stock_detail/detail.py` — `generate_stock_detail`の`log_duration`化／Modify: `tests/test_stock_detail.py`
- Modify: `app_tabs/backtest_tab.py`, `app_tabs/ranking_tab.py`, `app_tabs/portfolio_tab.py`, `app_tabs/screening_tab.py`, `app_tabs/sector/tab.py` — タブ表示ログ・主要操作の`log_duration`化・エラー分岐のwarningログ

---

### Task 1: `common/logging_config.py` — ロギング基盤

**Files:**
- Create: `common/logging_config.py`
- Test: `tests/test_logging_config.py`

**Interfaces:**
- Consumes: なし（標準ライブラリ`logging`/`pathlib`/`time`/`contextlib`のみ）
- Produces:
  - `LOG_DIR: Path`（`common/logging_config.py`から見て`../logs`、すなわち`app/logs`）
  - `setup_logging(log_dir: Path = LOG_DIR) -> None`
  - `log_duration(logger: logging.Logger, action: str)` — contextmanager
  - 以降の全タスクはこの2関数を`common.logging_config`からimportして使う

- [ ] **Step 1: Write the failing tests**

`tests/test_logging_config.py`を新規作成する:

```python
import logging

import pytest

from common.logging_config import log_duration, setup_logging


@pytest.fixture(autouse=True)
def _clean_root_logger():
    # setup_loggingはStreamlitの再実行のたびに呼ばれる想定のため、テスト間で
    # ルートロガーの状態（ハンドラ・レベル）が汚染されないようリセットする。
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    for handler in original_handlers:
        root_logger.removeHandler(handler)
    yield
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    for handler in original_handlers:
        root_logger.addHandler(handler)
    root_logger.setLevel(original_level)


def test_setup_logging_creates_log_file_with_message(tmp_path):
    log_dir = tmp_path / "logs"
    setup_logging(log_dir=log_dir)

    logging.getLogger("test_setup_logging_creates_log_file_with_message").info("hello")
    for handler in logging.getLogger().handlers:
        handler.flush()

    log_file = log_dir / "app.log"
    assert log_file.exists()
    assert "hello" in log_file.read_text(encoding="utf-8")


def test_setup_logging_is_idempotent(tmp_path):
    log_dir = tmp_path / "logs"
    setup_logging(log_dir=log_dir)
    setup_logging(log_dir=log_dir)

    assert len(logging.getLogger().handlers) == 1


def test_log_duration_logs_start_and_completion(caplog):
    logger = logging.getLogger("test_log_duration_success")
    with caplog.at_level(logging.INFO, logger="test_log_duration_success"):
        with log_duration(logger, "テスト処理"):
            pass

    assert "テスト処理を開始" in caplog.text
    assert "テスト処理が完了しました" in caplog.text


def test_log_duration_logs_failure_and_reraises(caplog):
    logger = logging.getLogger("test_log_duration_failure")
    with caplog.at_level(logging.INFO, logger="test_log_duration_failure"):
        with pytest.raises(ValueError):
            with log_duration(logger, "失敗処理"):
                raise ValueError("boom")

    assert "失敗処理を開始" in caplog.text
    assert "失敗処理が失敗しました" in caplog.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `ai-stock-investing-tutorial/app`): `uv run pytest tests/test_logging_config.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'common.logging_config'`

- [ ] **Step 3: Write the implementation**

`common/logging_config.py`を新規作成する:

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_logging_config.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add common/logging_config.py tests/test_logging_config.py
git commit -m "$(cat <<'EOF'
Add logging infrastructure (setup_logging, log_duration)

Sets up a daily-rotating file handler under app/logs/ (idempotent
across Streamlit's script reruns) and a context manager that logs
start/completion/failure with elapsed time for later use across the
app's tabs, external I/O, cache, and analysis modules.
EOF
)"
```

---

### Task 2: `app.py`への配線と`.gitignore`更新

**Files:**
- Modify: `app.py:1-13`（importとロガー初期化）, `app.py:20`（`set_page_config`の直前）
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `common.logging_config.setup_logging`（Task 1で実装済み）
- Produces: なし（`app.py`はエントリーポイントであり、他タスクから参照されない）

- [ ] **Step 1: `.gitignore`に`logs/`を追加**

`.gitignore`の`# Runtime data`セクション（`data/`の行）の直後に追加する:

現在:
```
# Runtime data
data/
```

変更後:
```
# Runtime data
data/
logs/
```

- [ ] **Step 2: `app.py`に`setup_logging()`呼び出しを追加**

`app.py:1-29`を以下のように変更する。既存の`import streamlit as st`より前に`import logging`を追加し、`common.logging_config`のimportを追加、`st.set_page_config(...)`の直前で`setup_logging()`とロガー初期化・起動ログを追加する。

現在（`app.py:1-27`）:
```python
"""日本株を対象としたAI投資リサーチアプリのエントリーポイント（Streamlit）。

ポートフォリオ管理・スクリーニング・バックテスト・一括バックテストランキング・
セクターローテーション分析の各機能をタブ形式のUIとしてまとめ、
株価/ファンダメンタルズ/ニュース取得とLLM（Claude）によるコメント生成を組み合わせて提供する。
各タブの描画処理は app_tabs 配下のモジュールに分割している。
"""

import streamlit as st

from common.disclaimer import DISCLAIMER_NOTICE
from data_api.llm_client import check_claude_cli_available

from app_tabs.backtest_tab import render_backtest_tab
from app_tabs.portfolio_tab import render_portfolio_tab
from app_tabs.ranking_tab import render_ranking_tab
from app_tabs.screening_tab import render_screening_tab
from app_tabs.sector import render_sector_tab

st.set_page_config(page_title="株投資リサーチアプリ", layout="wide")

# Claude CLIが利用できない環境ではLLM機能が動作しないため、起動時点でチェックしてアプリを止める
try:
    check_claude_cli_available()
except Exception as exc:
    st.error(str(exc))
    st.stop()
```

変更後:
```python
"""日本株を対象としたAI投資リサーチアプリのエントリーポイント（Streamlit）。

ポートフォリオ管理・スクリーニング・バックテスト・一括バックテストランキング・
セクターローテーション分析の各機能をタブ形式のUIとしてまとめ、
株価/ファンダメンタルズ/ニュース取得とLLM（Claude）によるコメント生成を組み合わせて提供する。
各タブの描画処理は app_tabs 配下のモジュールに分割している。
"""

import logging

import streamlit as st

from common.disclaimer import DISCLAIMER_NOTICE
from common.logging_config import setup_logging
from data_api.llm_client import check_claude_cli_available

from app_tabs.backtest_tab import render_backtest_tab
from app_tabs.portfolio_tab import render_portfolio_tab
from app_tabs.ranking_tab import render_ranking_tab
from app_tabs.screening_tab import render_screening_tab
from app_tabs.sector import render_sector_tab

setup_logging()
logger = logging.getLogger(__name__)
# StreamlitはユーザーがUI操作するたびにapp.pyを再実行するため、このログは
# 起動時だけでなく再実行のたびに出る。以降のログとの時系列対応付けに使う。
logger.info("app.pyを実行しました")

st.set_page_config(page_title="株投資リサーチアプリ", layout="wide")

# Claude CLIが利用できない環境ではLLM機能が動作しないため、起動時点でチェックしてアプリを止める
try:
    check_claude_cli_available()
except Exception as exc:
    st.error(str(exc))
    st.stop()
```

- [ ] **Step 3: アプリを起動して動作確認**

Run: `uv run python -m streamlit run app.py`

確認項目:
1. `ai-stock-investing-tutorial/app/logs/app.log`が新規作成される
2. ファイルに`[INFO] app: app.pyを実行しました`という行が記録されている
3. ブラウザでタブを切り替える・チェックボックスを操作するなど、Streamlitの再実行が起きる操作をすると、同じログ行が追記される（1行だけ増える。ハンドラが重複登録されて複数行同時に増えたりしないことを確認）

- [ ] **Step 4: 既存の自動テストが壊れていないことを確認**

Run: `uv run pytest -v`
Expected: 既存の全テストがPASS

- [ ] **Step 5: Commit**

```bash
git add app.py .gitignore
git commit -m "$(cat <<'EOF'
Wire up logging setup in app.py

Calls setup_logging() at startup so all subsequent modules can log to
app/logs/app.log, and ignores the runtime-generated logs/ directory.
EOF
)"
```

---

### Task 3: `common/cache.py` — キャッシュのヒット/ミス/書き込みログ

**Files:**
- Modify: `common/cache.py`
- Test: `tests/test_cache.py`

**Interfaces:**
- Consumes: なし（`logging`標準ライブラリのみ。`log_duration`は使わない — 単発イベントのため）
- Produces: なし（挙動は変わらず、ログ出力のみ追加）

- [ ] **Step 1: Write the failing tests**

`tests/test_cache.py`の末尾に追加する:

```python
import logging

from common.cache import read_cache, write_cache


def test_read_cache_returns_none_when_not_cached(tmp_path):
    assert read_cache(tmp_path, "some-key") is None


def test_write_then_read_cache_roundtrip(tmp_path):
    write_cache(tmp_path, "some-key", "cached content")
    assert read_cache(tmp_path, "some-key") == "cached content"


def test_different_keys_are_stored_separately(tmp_path):
    write_cache(tmp_path, "key-a", "content a")
    write_cache(tmp_path, "key-b", "content b")
    assert read_cache(tmp_path, "key-a") == "content a"
    assert read_cache(tmp_path, "key-b") == "content b"


def test_read_cache_miss_logs_info(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger="common.cache"):
        read_cache(tmp_path, "missing-key")
    assert "キャッシュミス: missing-key" in caplog.text


def test_read_cache_hit_logs_info(tmp_path, caplog):
    write_cache(tmp_path, "hit-key", "content")
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="common.cache"):
        read_cache(tmp_path, "hit-key")
    assert "キャッシュヒット: hit-key" in caplog.text


def test_write_cache_logs_info(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger="common.cache"):
        write_cache(tmp_path, "write-key", "content")
    assert "キャッシュ書き込み: write-key" in caplog.text
```

（先頭3つの`test_read_cache_returns_none_when_not_cached`等は既存テストと同一内容。ファイル全体を上記で置き換える形にする）

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run pytest tests/test_cache.py -v`
Expected: 既存3件はPASS、新規3件（ログ関連）はFAIL（`assert "..." in caplog.text`が失敗、caplog.textが空のため）

- [ ] **Step 3: Write the implementation**

`common/cache.py`を以下に置き換える:

```python
# LLM呼び出し結果などをファイルベースで日次キャッシュするためのユーティリティ。
# 同じ日であれば再利用し、無駄なAPI呼び出し（コスト・レイテンシ）を避ける。
import datetime
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def get_cache_path(cache_dir: Path, key: str) -> Path:
    # キャッシュを日付単位で分けることで、日をまたいだ古い情報を自然に無効化する。
    today = datetime.date.today().isoformat()
    return Path(cache_dir) / f"{today}-{key}.txt"


def read_cache(cache_dir: Path, key: str) -> str | None:
    path = get_cache_path(cache_dir, key)
    if path.exists():
        logger.info("キャッシュヒット: %s", key)
        return path.read_text(encoding="utf-8")
    logger.info("キャッシュミス: %s", key)
    return None


def write_cache(cache_dir: Path, key: str, content: str) -> None:
    path = get_cache_path(cache_dir, key)
    # キャッシュディレクトリが未作成の場合に備え、書き込み前に作成しておく。
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.info("キャッシュ書き込み: %s", key)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cache.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add common/cache.py tests/test_cache.py
git commit -m "$(cat <<'EOF'
Log cache hit/miss/write events

Every read_cache/write_cache call now logs which cache key was hit,
missed, or written, so the log can show which downstream calls (LLM,
price API, analysis) were skipped versus actually executed.
EOF
)"
```

---

### Task 4: `data_api/llm_client.py` — `call_llm`の所要時間ログ

**Files:**
- Modify: `data_api/llm_client.py`
- Test: `tests/test_llm_client.py`

**Interfaces:**
- Consumes: `common.logging_config.log_duration`（Task 1で実装済み）
- Produces: なし（`call_llm`のシグネチャ・戻り値は変更しない）

- [ ] **Step 1: Write the failing tests**

`tests/test_llm_client.py`の先頭に`import logging`を追加し、末尾に2件のテストを追加する:

```python
import logging
import subprocess

import pytest

from data_api.llm_client import (
    ClaudeCLIError,
    ClaudeCLINotFoundError,
    call_llm,
    check_claude_cli_available,
)


# ... 既存の5テスト（test_call_llm_returns_stdout_on_success 等）はそのまま ...


def test_call_llm_logs_duration_on_success(monkeypatch, caplog):
    monkeypatch.setattr("shutil.which", lambda name: "claude-executable")

    def fake_run(args, input, capture_output, text, encoding, timeout):
        return subprocess.CompletedProcess(args, 0, stdout="response text\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with caplog.at_level(logging.INFO, logger="data_api.llm_client"):
        call_llm("hello")

    assert "Claude CLI呼び出し" in caplog.text
    assert "を開始" in caplog.text
    assert "が完了しました" in caplog.text


def test_call_llm_logs_failure_on_nonzero_exit(monkeypatch, caplog):
    monkeypatch.setattr("shutil.which", lambda name: "claude-executable")

    def fake_run(args, input, capture_output, text, encoding, timeout):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with caplog.at_level(logging.INFO, logger="data_api.llm_client"):
        with pytest.raises(ClaudeCLIError):
            call_llm("hello")

    assert "が失敗しました" in caplog.text
```

（`# ... 既存の5テスト ... `の行はコメントであり実際には既存の5関数定義をそのまま残す。ファイル冒頭のimport文だけ`import logging`を足す点に注意）

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run pytest tests/test_llm_client.py -v`
Expected: 既存5件はPASS、新規2件はFAIL（caplog.textが空のため）

- [ ] **Step 3: Write the implementation**

`data_api/llm_client.py`を以下に置き換える:

```python
"""Claude Code CLI（`claude`コマンド）をサブプロセスとして呼び出し、
LLMへのプロンプト送信・応答取得を行うための薄いラッパーモジュール。"""

import logging
import shutil
import subprocess

from common.logging_config import log_duration

logger = logging.getLogger(__name__)


class ClaudeCLINotFoundError(RuntimeError):
    """`claude`コマンドがPATH上に見つからない場合に送出する例外。"""

    pass


class ClaudeCLIError(RuntimeError):
    """`claude`コマンドの実行がエラー終了した場合に送出する例外。"""

    pass


# LLMに毎回渡すシステムプロンプト。出力形式をアプリ側で制御しやすくするため、
# 指示外の余計な発言をしないよう厳密に指示している。
_SYSTEM_PROMPT = "あなたは指示に厳密に従うアシスタントです。指示された出力のみを返してください。"


def _resolve_claude_executable() -> str:
    """`claude`実行ファイルのパスを解決する。未インストール時は分かりやすい例外に変換する。"""
    executable = shutil.which("claude")
    if executable is None:
        raise ClaudeCLINotFoundError(
            "Claude Code CLI（`claude`コマンド）が見つかりません。"
            "インストールとログインを確認してください。"
        )
    return executable


def check_claude_cli_available() -> None:
    """CLI利用可否を事前チェックするためのエントリポイント（結果は例外の有無で判定）。"""
    _resolve_claude_executable()


def call_llm(prompt: str, timeout: int = 120) -> str:
    """Claude Code CLIにプロンプトを渡し、応答テキストを取得する。

    各分析エージェントやコメント生成処理から共通のLLM呼び出し口として利用される。
    """
    executable = _resolve_claude_executable()
    # プロンプト本文は機密情報や長大なJSONを含みうるためログに出さず、長さのみ記録する。
    with log_duration(logger, f"Claude CLI呼び出し（prompt長={len(prompt)}）"):
        # Prompt is passed via stdin, not argv: on Windows, `claude` resolves to
        # an npm .cmd shim, whose batch-argument relay corrupts arguments that
        # contain embedded double quotes (our JSON-format prompts do).
        result = subprocess.run(
            [executable, "--system-prompt", _SYSTEM_PROMPT, "-p"],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
        if result.returncode != 0:
            # 非ゼロ終了はCLI側のエラー（未ログイン、タイムアウト等）とみなし、
            # 標準エラー出力を含めて呼び出し元に伝播する。
            raise ClaudeCLIError(f"Claude Code CLIの実行に失敗しました: {result.stderr.strip()}")
    return result.stdout.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_client.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add data_api/llm_client.py tests/test_llm_client.py
git commit -m "$(cat <<'EOF'
Log Claude CLI call duration and failures

Wraps call_llm's subprocess invocation in log_duration so the log
shows how long each LLM call took (and why it failed), without ever
logging prompt contents.
EOF
)"
```

---

### Task 5: `data_api/stock_price_api.py` — ユニバース一括取得の所要時間ログ

**Files:**
- Modify: `data_api/stock_price_api.py`
- Test: `tests/test_stock_price_api.py`

**Interfaces:**
- Consumes: `common.logging_config.log_duration`（Task 1で実装済み）
- Produces: なし（`fetch_universe_fundamentals`のシグネチャ・戻り値は変更しない）

- [ ] **Step 1: Write the failing test**

`tests/test_stock_price_api.py`の先頭に`import logging`を追加し、末尾に1件追加する:

```python
import logging

# ... 既存のimport（pandas, data_api.stock_price_api）はそのまま ...


def test_fetch_universe_fundamentals_logs_duration(tmp_path, caplog):
    def fake_fetch_fundamentals(ticker_symbol):
        return {
            "ticker": ticker_symbol,
            "name": ticker_symbol,
            "trailing_pe": 10.0,
            "price_to_book": 1.0,
            "dividend_yield": 0.02,
            "market_cap": 1,
        }

    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_universe_fundamentals(
            ["AAA.T"], tmp_path, fetch_fundamentals=fake_fetch_fundamentals
        )

    assert "ユニバースfundamentals一括取得" in caplog.text
    assert "を開始" in caplog.text
    assert "が完了しました" in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_stock_price_api.py -v`
Expected: 既存テストはPASS、新規テストはFAIL（caplog.textが空のため）

- [ ] **Step 3: Write the implementation**

`data_api/stock_price_api.py`の先頭のimportブロックとdocstringを次のように変更する（`import logging`追加、`common.logging_config`のimport追加、モジュールレベルの`logger`定義追加）:

現在（`data_api/stock_price_api.py:1-16`）:
```python
"""yfinanceおよびYahoo!ファイナンス（日本版）から株価・ファンダメンタルズ・
ニュース等の市場データを取得するAPIラッパー群。取得結果のキャッシュ・
複数銘柄の並行取得もあわせて提供する。"""

import hashlib
import json
import re
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

from common.cache import read_cache, write_cache
from common.concurrency import map_concurrently
```

変更後:
```python
"""yfinanceおよびYahoo!ファイナンス（日本版）から株価・ファンダメンタルズ・
ニュース等の市場データを取得するAPIラッパー群。取得結果のキャッシュ・
複数銘柄の並行取得もあわせて提供する。"""

import hashlib
import json
import logging
import re
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

from common.cache import read_cache, write_cache
from common.concurrency import map_concurrently
from common.logging_config import log_duration

logger = logging.getLogger(__name__)
```

続けて`fetch_universe_fundamentals`本体（`data_api/stock_price_api.py:88-129`）を次のように変更する。キャッシュ取得までは変更せず、`map_concurrently`呼び出し以降を`log_duration`で包む:

現在:
```python
def fetch_universe_fundamentals(
    tickers: list[str],
    cache_dir: Path,
    fetch_fundamentals=fetch_fundamentals,
) -> pd.DataFrame:
    """複数銘柄のファンダメンタルズをまとめて取得し、DataFrameとして返す。

    セクター分析などスクリーニング用途で銘柄集合全体を扱うため、
    キャッシュと並行取得によって繰り返し呼び出しのコストを抑える。
    """
    # 銘柄集合ごとに一意なキャッシュキーを作る（順序に依らないようソートしてハッシュ化）
    cache_key = "universe-" + hashlib.sha256(
        "-".join(sorted(tickers)).encode("utf-8")
    ).hexdigest()[:12]
    cached = read_cache(cache_dir, cache_key)
    if cached is not None:
        return pd.DataFrame(json.loads(cached))

    # 銘柄数が多いと逐次取得は遅いため、複数銘柄を並行してAPI取得する
    results = map_concurrently(tickers, fetch_fundamentals)
    rows = []
    for ticker_symbol in tickers:
        data = results[ticker_symbol]
        # 個別銘柄の取得失敗（例外）は全体を止めず、その銘柄だけスキップする
        if isinstance(data, Exception):
            continue
        rows.append(
            {
                "ticker": data.get("ticker", ticker_symbol),
                "name": data.get("name"),
                "per": data.get("trailing_pe"),
                "pbr": data.get("price_to_book"),
                # yfinance's dividendYield is already a percentage number
                # (e.g. 3.45 means 3.45%), not a fraction to scale up.
                "dividend_yield_pct": data.get("dividend_yield"),
                "market_cap": data.get("market_cap"),
            }
        )
    df = pd.DataFrame(rows)
    write_cache(cache_dir, cache_key, df.to_json(orient="records", force_ascii=False))
    return df
```

変更後:
```python
def fetch_universe_fundamentals(
    tickers: list[str],
    cache_dir: Path,
    fetch_fundamentals=fetch_fundamentals,
) -> pd.DataFrame:
    """複数銘柄のファンダメンタルズをまとめて取得し、DataFrameとして返す。

    セクター分析などスクリーニング用途で銘柄集合全体を扱うため、
    キャッシュと並行取得によって繰り返し呼び出しのコストを抑える。
    """
    # 銘柄集合ごとに一意なキャッシュキーを作る（順序に依らないようソートしてハッシュ化）
    cache_key = "universe-" + hashlib.sha256(
        "-".join(sorted(tickers)).encode("utf-8")
    ).hexdigest()[:12]
    cached = read_cache(cache_dir, cache_key)
    if cached is not None:
        return pd.DataFrame(json.loads(cached))

    with log_duration(logger, f"ユニバースfundamentals一括取得（{len(tickers)}銘柄）"):
        # 銘柄数が多いと逐次取得は遅いため、複数銘柄を並行してAPI取得する
        results = map_concurrently(tickers, fetch_fundamentals)
        rows = []
        for ticker_symbol in tickers:
            data = results[ticker_symbol]
            # 個別銘柄の取得失敗（例外）は全体を止めず、その銘柄だけスキップする
            if isinstance(data, Exception):
                continue
            rows.append(
                {
                    "ticker": data.get("ticker", ticker_symbol),
                    "name": data.get("name"),
                    "per": data.get("trailing_pe"),
                    "pbr": data.get("price_to_book"),
                    # yfinance's dividendYield is already a percentage number
                    # (e.g. 3.45 means 3.45%), not a fraction to scale up.
                    "dividend_yield_pct": data.get("dividend_yield"),
                    "market_cap": data.get("market_cap"),
                }
            )
        df = pd.DataFrame(rows)
        write_cache(cache_dir, cache_key, df.to_json(orient="records", force_ascii=False))
    return df
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_stock_price_api.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add data_api/stock_price_api.py tests/test_stock_price_api.py
git commit -m "$(cat <<'EOF'
Log duration of universe-wide fundamentals fetch

fetch_universe_fundamentals is the one place that fans out to all 226
universe tickers in a single call, so it's safe to log its start/end
without flooding the log the way per-ticker logging would.
EOF
)"
```

---

### Task 6: `portfolio_management/backtest.py` — バックテスト計算の所要時間ログ

**Files:**
- Modify: `portfolio_management/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `common.logging_config.log_duration`（Task 1で実装済み）
- Produces: なし（`run_backtest_comparison`/`run_universe_backtest_ranking`のシグネチャ・戻り値は変更しない）

- [ ] **Step 1: Write the failing tests**

`tests/test_backtest.py`の先頭に`import logging`を追加し、末尾に2件追加する:

```python
import logging

# ... 既存のimport（pandas, common.disclaimer, portfolio_management.backtest）はそのまま ...


def test_run_backtest_comparison_logs_duration(caplog):
    dates = pd.date_range("2026-01-01", periods=80, freq="D")
    prices = pd.Series(range(100, 180), index=dates, dtype=float)

    with caplog.at_level(logging.INFO, logger="portfolio_management.backtest"):
        run_backtest_comparison(
            prices, run_ma_crossover_backtest, STRATEGIES["移動平均クロスオーバー"]["presets"]
        )

    assert "バックテスト比較計算" in caplog.text
    assert "を開始" in caplog.text
    assert "が完了しました" in caplog.text


def test_run_universe_backtest_ranking_logs_duration(caplog):
    dates = pd.date_range("2026-01-01", periods=80, freq="D")
    prices_by_ticker = {"AAA.T": pd.Series(range(100, 180), index=dates, dtype=float)}

    with caplog.at_level(logging.INFO, logger="portfolio_management.backtest"):
        run_universe_backtest_ranking(
            prices_by_ticker, run_ma_crossover_backtest, {"short_window": 5, "long_window": 25}
        )

    assert "ユニバース一括バックテスト" in caplog.text
    assert "を開始" in caplog.text
    assert "が完了しました" in caplog.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_backtest.py -v`
Expected: 既存テストはPASS、新規2件はFAIL（caplog.textが空のため）

- [ ] **Step 3: Write the implementation**

`portfolio_management/backtest.py`冒頭のimportブロック（`portfolio_management/backtest.py:1-9`）を次のように変更する:

現在:
```python
"""複数のテクニカル戦略（MA・RSI・MACD・ボリンジャーバンド）を対象に、
過去の株価系列でベクトル化バックテストを実行し、成績指標やLLMによる
解説文を生成するモジュール。"""

import pandas as pd

from common.disclaimer import DISCLAIMER_NOTICE
from data_api.llm_client import call_llm as default_call_llm
from prompt_patterns.backtest_explanation import build_backtest_prompt
```

変更後:
```python
"""複数のテクニカル戦略（MA・RSI・MACD・ボリンジャーバンド）を対象に、
過去の株価系列でベクトル化バックテストを実行し、成績指標やLLMによる
解説文を生成するモジュール。"""

import logging

import pandas as pd

from common.disclaimer import DISCLAIMER_NOTICE
from common.logging_config import log_duration
from data_api.llm_client import call_llm as default_call_llm
from prompt_patterns.backtest_explanation import build_backtest_prompt

logger = logging.getLogger(__name__)
```

`run_backtest_comparison`（`portfolio_management/backtest.py:191-202`）を次のように変更する:

現在:
```python
def run_backtest_comparison(
    prices: pd.Series,
    backtest_func,
    presets: list[tuple[str, dict]],
    transaction_cost_pct: float = 0.0,
) -> dict[str, dict]:
    """同一戦略の複数プリセット（パラメータ設定）でバックテストを実行し、
    プリセット名ごとの成績を比較できる形でまとめる。"""
    return {
        label: backtest_func(prices, transaction_cost_pct=transaction_cost_pct, **params)
        for label, params in presets
    }
```

変更後:
```python
def run_backtest_comparison(
    prices: pd.Series,
    backtest_func,
    presets: list[tuple[str, dict]],
    transaction_cost_pct: float = 0.0,
) -> dict[str, dict]:
    """同一戦略の複数プリセット（パラメータ設定）でバックテストを実行し、
    プリセット名ごとの成績を比較できる形でまとめる。"""
    with log_duration(logger, f"バックテスト比較計算（プリセット{len(presets)}件）"):
        return {
            label: backtest_func(prices, transaction_cost_pct=transaction_cost_pct, **params)
            for label, params in presets
        }
```

`run_universe_backtest_ranking`（`portfolio_management/backtest.py:237-260`）を次のように変更する:

現在:
```python
def run_universe_backtest_ranking(
    prices_by_ticker: dict[str, pd.Series],
    backtest_func,
    preset_params: dict,
    transaction_cost_pct: float = 0.0,
    min_days: int = 0,
) -> list[dict]:
    """銘柄ユニバース全体に同一戦略・同一パラメータでバックテストを行い、
    リスク調整後リターン（収益率÷最大ドローダウン）でランキングする。"""
    rows = []
    for ticker, prices in prices_by_ticker.items():
        # データ期間が短すぎる銘柄は戦略が機能しないため除外する。
        if len(prices) < min_days:
            continue
        result = backtest_func(prices, transaction_cost_pct=transaction_cost_pct, **preset_params)
        drawdown = abs(result["max_drawdown_pct"])
        # ドローダウンが0の場合はゼロ除算を避け、収益率をそのまま指標とする。
        risk_adjusted_return = (
            result["total_return_pct"] / drawdown if drawdown else result["total_return_pct"]
        )
        rows.append(
            {"ticker": ticker, **result, "risk_adjusted_return": round(risk_adjusted_return, 2)}
        )
    return sorted(rows, key=lambda row: row["risk_adjusted_return"], reverse=True)
```

変更後:
```python
def run_universe_backtest_ranking(
    prices_by_ticker: dict[str, pd.Series],
    backtest_func,
    preset_params: dict,
    transaction_cost_pct: float = 0.0,
    min_days: int = 0,
) -> list[dict]:
    """銘柄ユニバース全体に同一戦略・同一パラメータでバックテストを行い、
    リスク調整後リターン（収益率÷最大ドローダウン）でランキングする。"""
    with log_duration(logger, f"ユニバース一括バックテスト（{len(prices_by_ticker)}銘柄）"):
        rows = []
        for ticker, prices in prices_by_ticker.items():
            # データ期間が短すぎる銘柄は戦略が機能しないため除外する。
            if len(prices) < min_days:
                continue
            result = backtest_func(
                prices, transaction_cost_pct=transaction_cost_pct, **preset_params
            )
            drawdown = abs(result["max_drawdown_pct"])
            # ドローダウンが0の場合はゼロ除算を避け、収益率をそのまま指標とする。
            risk_adjusted_return = (
                result["total_return_pct"] / drawdown if drawdown else result["total_return_pct"]
            )
            rows.append(
                {
                    "ticker": ticker,
                    **result,
                    "risk_adjusted_return": round(risk_adjusted_return, 2),
                }
            )
        return sorted(rows, key=lambda row: row["risk_adjusted_return"], reverse=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_backtest.py -v`
Expected: 全テストPASS（既存 + 新規2件）

- [ ] **Step 5: Commit**

```bash
git add portfolio_management/backtest.py tests/test_backtest.py
git commit -m "$(cat <<'EOF'
Log duration of backtest comparison and universe ranking

Both functions run once per button press (looping internally over
presets/tickers), so wrapping them in log_duration gives per-run
timing without per-ticker log noise.
EOF
)"
```

---

### Task 7: `sector_analysis/correlation.py` と `sector_analysis/wavelet.py` — 分析処理の所要時間ログ

**Files:**
- Modify: `sector_analysis/correlation.py`
- Test: `tests/test_sector_correlation.py`
- Modify: `sector_analysis/wavelet.py`
- Test: `tests/test_sector_wavelet.py`

**Interfaces:**
- Consumes: `common.logging_config.log_duration`（Task 1で実装済み）
- Produces: なし（各関数のシグネチャ・戻り値は変更しない）

- [ ] **Step 1: Write the failing test for `compute_sector_returns`/`compute_lead_lag_pairs`**

`tests/test_sector_correlation.py`の先頭に`import logging`を追加し、末尾に2件追加する:

```python
import logging

# ... 既存のimport（numpy, pandas, sector_analysis.correlation）はそのまま ...


def test_compute_sector_returns_logs_duration(caplog):
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    prices_by_ticker = {"A.T": pd.Series([100.0, 101.0, 102.0, 101.5, 103.0], index=dates)}
    sector_map = {"A.T": "業種X"}

    with caplog.at_level(logging.INFO, logger="sector_analysis.correlation"):
        compute_sector_returns(prices_by_ticker, sector_map)

    assert "業種別リターン集計" in caplog.text
    assert "を開始" in caplog.text
    assert "が完了しました" in caplog.text


def test_compute_lead_lag_pairs_logs_duration(caplog):
    dates = pd.date_range("2026-01-01", periods=30, freq="D")
    sector_returns = {
        "業種X": pd.Series(range(30), index=dates, dtype=float),
        "業種Y": pd.Series(range(30, 60), index=dates, dtype=float),
    }

    with caplog.at_level(logging.INFO, logger="sector_analysis.correlation"):
        compute_lead_lag_pairs(sector_returns, max_lag_days=5)

    assert "リード・ラグ相関計算" in caplog.text
    assert "を開始" in caplog.text
    assert "が完了しました" in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sector_correlation.py -v`
Expected: 既存テストはPASS、新規2件はFAIL（caplog.textが空のため）

- [ ] **Step 3: Write the implementation for `sector_analysis/correlation.py`**

`sector_analysis/correlation.py`冒頭（`sector_analysis/correlation.py:1-9`）を次のように変更する:

現在:
```python
"""業種（セクター）単位の値動きを分析するためのモジュール。

個別銘柄の株価から業種ごとの日次リターンを合成し、業種間の
先行・遅行関係（どの業種が他の業種の値動きを先取りしているか）を
時差相関によって推定する。
"""

import pandas as pd
```

変更後:
```python
"""業種（セクター）単位の値動きを分析するためのモジュール。

個別銘柄の株価から業種ごとの日次リターンを合成し、業種間の
先行・遅行関係（どの業種が他の業種の値動きを先取りしているか）を
時差相関によって推定する。
"""

import logging

import pandas as pd

from common.logging_config import log_duration

logger = logging.getLogger(__name__)
```

`compute_sector_returns`（`sector_analysis/correlation.py:11-33`）を次のように変更する:

現在:
```python
def compute_sector_returns(
    prices_by_ticker: dict[str, pd.Series],
    sector_map: dict[str, str],
) -> dict[str, pd.Series]:
    """業種ごとに構成銘柄の日次リターンを等ウエイト平均した系列を返す。

    prices_by_tickerに存在しない銘柄はスキップする。構成銘柄が0件になった
    業種はキーごと結果から除外する。
    """
    # 業種ごとに構成銘柄のリターン系列をまとめる
    returns_by_sector: dict[str, list[pd.Series]] = {}
    for ticker, sector in sector_map.items():
        prices = prices_by_ticker.get(ticker)
        if prices is None or prices.empty:
            continue
        returns_by_sector.setdefault(sector, []).append(prices.pct_change())

    # 業種内の各銘柄リターンを日次で等ウエイト平均し、業種代表リターンを算出
    sector_returns: dict[str, pd.Series] = {}
    for sector, series_list in returns_by_sector.items():
        combined = pd.concat(series_list, axis=1)
        sector_returns[sector] = combined.mean(axis=1, skipna=True)
    return sector_returns
```

変更後:
```python
def compute_sector_returns(
    prices_by_ticker: dict[str, pd.Series],
    sector_map: dict[str, str],
) -> dict[str, pd.Series]:
    """業種ごとに構成銘柄の日次リターンを等ウエイト平均した系列を返す。

    prices_by_tickerに存在しない銘柄はスキップする。構成銘柄が0件になった
    業種はキーごと結果から除外する。
    """
    with log_duration(logger, "業種別リターン集計"):
        # 業種ごとに構成銘柄のリターン系列をまとめる
        returns_by_sector: dict[str, list[pd.Series]] = {}
        for ticker, sector in sector_map.items():
            prices = prices_by_ticker.get(ticker)
            if prices is None or prices.empty:
                continue
            returns_by_sector.setdefault(sector, []).append(prices.pct_change())

        # 業種内の各銘柄リターンを日次で等ウエイト平均し、業種代表リターンを算出
        sector_returns: dict[str, pd.Series] = {}
        for sector, series_list in returns_by_sector.items():
            combined = pd.concat(series_list, axis=1)
            sector_returns[sector] = combined.mean(axis=1, skipna=True)
        return sector_returns
```

`compute_lead_lag_pairs`（`sector_analysis/correlation.py:36-92`）を次のように変更する。関数本体全体を`with log_duration(...)`で囲み、インデントを4スペース深くする（中身は一切変更しない）:

現在の冒頭・末尾:
```python
def compute_lead_lag_pairs(
    sector_returns: dict[str, pd.Series],
    max_lag_days: int = 20,
) -> list[dict]:
    """業種の全ペア（重複なし）について、時差相関が最大となるラグを求める。
    ...
    """
    sectors = sorted(sector_returns.keys())
    pairs: list[dict] = []

    for i in range(len(sectors)):
        ...

    pairs.sort(key=lambda pair: abs(pair["correlation"]), reverse=True)
    return pairs
```

変更後の冒頭・末尾（`...`部分の中身は完全に同一、インデントだけ4スペース深くする）:
```python
def compute_lead_lag_pairs(
    sector_returns: dict[str, pd.Series],
    max_lag_days: int = 20,
) -> list[dict]:
    """業種の全ペア（重複なし）について、時差相関が最大となるラグを求める。
    ...
    """
    with log_duration(logger, f"リード・ラグ相関計算（{len(sector_returns)}業種）"):
        sectors = sorted(sector_returns.keys())
        pairs: list[dict] = []

        for i in range(len(sectors)):
            ...

        pairs.sort(key=lambda pair: abs(pair["correlation"]), reverse=True)
        return pairs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sector_correlation.py -v`
Expected: 全テストPASS

- [ ] **Step 5: Write the failing test for `compute_all_pairs_dominant_lag`**

`tests/test_sector_wavelet.py`の先頭に`import logging`を追加し、末尾に1件追加する:

```python
import logging

# ... 既存のimport（numpy, pandas, sector_analysis.wavelet）はそのまま ...


def test_compute_all_pairs_dominant_lag_logs_duration(caplog):
    dates = pd.date_range("2026-01-01", periods=250, freq="D")
    sector_returns = {
        "業種X": pd.Series(range(250), index=dates, dtype=float) * 0.001,
        "業種Y": pd.Series(range(250), index=dates, dtype=float) * 0.001,
    }

    with caplog.at_level(logging.INFO, logger="sector_analysis.wavelet"):
        compute_all_pairs_dominant_lag(sector_returns)

    assert "ウェーブレット全ペア計算" in caplog.text
    assert "を開始" in caplog.text
    assert "が完了しました" in caplog.text
```

（`tests/test_sector_wavelet.py`の既存importに`compute_all_pairs_dominant_lag`が無ければ追加する）

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/test_sector_wavelet.py -v`
Expected: 既存テストはPASS、新規1件はFAIL（caplog.textが空のため）

- [ ] **Step 7: Write the implementation for `sector_analysis/wavelet.py`**

`sector_analysis/wavelet.py`冒頭のimportブロック（`sector_analysis/wavelet.py:1-7`）を次のように変更する:

現在:
```python
import itertools

import numpy as np
import pandas as pd
import pywt

WAVELET = "cmor1.5-1.0"
```

変更後:
```python
import itertools
import logging

import numpy as np
import pandas as pd
import pywt

from common.logging_config import log_duration

logger = logging.getLogger(__name__)

WAVELET = "cmor1.5-1.0"
```

`compute_all_pairs_dominant_lag`（`sector_analysis/wavelet.py:167-233`）本体全体を`log_duration`で囲む。冒頭・末尾は以下のとおり（`...`部分の中身は完全に同一、インデントだけ4スペース深くする）:

現在の冒頭・末尾:
```python
def compute_all_pairs_dominant_lag(
    sector_returns: dict[str, pd.Series],
    window_days: int = 20,
) -> pd.DataFrame:
    """全業種ペアについてウェーブレット分析を一括実行し、周期帯ごとに
    直近window_days営業日のコヒーレンス加重平均ラグに集約する。
    ...
    """
    columns = [
        "sector_x",
        ...
    ]
    rows = []
    sectors = sorted(sector_returns.keys())
    for sector_x, sector_y in itertools.combinations(sectors, 2):
        ...

    return pd.DataFrame(rows, columns=columns)
```

変更後:
```python
def compute_all_pairs_dominant_lag(
    sector_returns: dict[str, pd.Series],
    window_days: int = 20,
) -> pd.DataFrame:
    """全業種ペアについてウェーブレット分析を一括実行し、周期帯ごとに
    直近window_days営業日のコヒーレンス加重平均ラグに集約する。
    ...
    """
    with log_duration(logger, f"ウェーブレット全ペア計算（{len(sector_returns)}業種）"):
        columns = [
            "sector_x",
            ...
        ]
        rows = []
        sectors = sorted(sector_returns.keys())
        for sector_x, sector_y in itertools.combinations(sectors, 2):
            ...

        return pd.DataFrame(rows, columns=columns)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_sector_wavelet.py -v`
Expected: 全テストPASS

- [ ] **Step 9: Commit**

```bash
git add sector_analysis/correlation.py sector_analysis/wavelet.py tests/test_sector_correlation.py tests/test_sector_wavelet.py
git commit -m "$(cat <<'EOF'
Log duration of sector rotation analysis steps

compute_sector_returns, compute_lead_lag_pairs, and
compute_all_pairs_dominant_lag each run once per analysis execution
(looping internally over sectors/pairs), so wrapping them gives a
per-step timing breakdown without per-pair log noise.
EOF
)"
```

---

### Task 8: `stock_detail/detail.py` — 銘柄詳細生成の所要時間ログ

**Files:**
- Modify: `stock_detail/detail.py`
- Test: `tests/test_stock_detail.py`

**Interfaces:**
- Consumes: `common.logging_config.log_duration`（Task 1で実装済み）
- Produces: なし（`generate_stock_detail`のシグネチャ・戻り値は変更しない）

- [ ] **Step 1: Write the failing test**

`tests/test_stock_detail.py`の先頭に`import logging`を追加し、末尾に1件追加する:

```python
import logging

# ... 既存のimport（json, pandas, common.cache, stock_detail.detail）はそのまま ...


def test_generate_stock_detail_logs_duration_on_cache_miss(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger="stock_detail.detail"):
        generate_stock_detail(
            "AAA.T",
            "エーエー株式会社",
            tmp_path,
            call_llm=lambda prompt: "コメント",
            fetch_price_history=lambda ticker, period: _fake_history(),
            fetch_news=lambda ticker: [],
            analyze_fundamentals=lambda ticker: {},
            analyze_technical=lambda history: {},
        )

    assert "銘柄詳細生成（AAA.T）" in caplog.text
    assert "を開始" in caplog.text
    assert "が完了しました" in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_stock_detail.py -v`
Expected: 既存テストはPASS、新規1件はFAIL（caplog.textが空のため）

- [ ] **Step 3: Write the implementation**

`stock_detail/detail.py`冒頭のimportブロック（`stock_detail/detail.py:1-16`）を次のように変更する:

現在:
```python
"""個別銘柄の詳細画面向けに、株価・ファンダメンタルズ・テクニカル分析・
ニュース・LLMによる講評コメントを1つにまとめて生成するモジュール。"""

import json
from pathlib import Path

from analysis_agents.fundamental_agent import (
    analyze_fundamentals as default_analyze_fundamentals,
)
from analysis_agents.technical_agent import analyze_technical as default_analyze_technical
from common.cache import read_cache, write_cache
from data_api.llm_client import call_llm as default_call_llm
from data_api.stock_price_api import fetch_news as default_fetch_news
from data_api.stock_price_api import fetch_price_history as default_fetch_price_history
from prompt_patterns.stock_detail import build_stock_detail_prompt
```

変更後:
```python
"""個別銘柄の詳細画面向けに、株価・ファンダメンタルズ・テクニカル分析・
ニュース・LLMによる講評コメントを1つにまとめて生成するモジュール。"""

import json
import logging
from pathlib import Path

from analysis_agents.fundamental_agent import (
    analyze_fundamentals as default_analyze_fundamentals,
)
from analysis_agents.technical_agent import analyze_technical as default_analyze_technical
from common.cache import read_cache, write_cache
from common.logging_config import log_duration
from data_api.llm_client import call_llm as default_call_llm
from data_api.stock_price_api import fetch_news as default_fetch_news
from data_api.stock_price_api import fetch_price_history as default_fetch_price_history
from prompt_patterns.stock_detail import build_stock_detail_prompt

logger = logging.getLogger(__name__)
```

`generate_stock_detail`（`stock_detail/detail.py:18-79`）のキャッシュミス以降を次のように変更する:

現在:
```python
    # 生成にはLLM呼び出しを含みコストが高いため、キャッシュがあれば再利用する。
    # 旧バージョンのキャッシュ（price_historyにopenキーが無いもの）は無効として扱う。
    cache_key = f"stock-detail-{ticker}"
    cached = read_cache(cache_dir, cache_key)
    if cached is not None:
        payload = json.loads(cached)
        if "open" in payload["price_history"]:
            return payload

    # 移動平均線（特に75日線）の計算バッファとして、表示に必要な6ヶ月分より
    # 長めの2年分を取得する。
    history = fetch_price_history(ticker, period="2y")
    fundamentals = analyze_fundamentals(ticker)
    technical = analyze_technical(history)
    news = fetch_news(ticker)

    # チャート描画用に、pandasのDataFrameをJSONシリアライズ可能な
    # プレーンな辞書（日付文字列＋各系列のリスト）に変換する
    if history.empty:
        price_history = {"dates": [], "open": [], "high": [], "low": [], "close": [], "volume": []}
    else:
        price_history = {
            "dates": [d.isoformat() for d in history.index],
            "open": history["Open"].tolist(),
            "high": history["High"].tolist(),
            "low": history["Low"].tolist(),
            "close": history["Close"].tolist(),
            "volume": history["Volume"].tolist(),
        }

    # ここまでに集めたファンダメンタルズ・テクニカル・ニュースをプロンプトに
    # まとめ、LLMに銘柄の講評コメントを生成させる
    prompt = build_stock_detail_prompt(ticker, name, fundamentals, technical, news)
    comment = call_llm(prompt)

    payload = {
        "ticker": ticker,
        "name": name,
        "price_history": price_history,
        "fundamentals": fundamentals,
        "technical": technical,
        "news": news,
        "comment": comment,
    }
    write_cache(cache_dir, cache_key, json.dumps(payload, ensure_ascii=False))
    return payload
```

変更後:
```python
    # 生成にはLLM呼び出しを含みコストが高いため、キャッシュがあれば再利用する。
    # 旧バージョンのキャッシュ（price_historyにopenキーが無いもの）は無効として扱う。
    cache_key = f"stock-detail-{ticker}"
    cached = read_cache(cache_dir, cache_key)
    if cached is not None:
        payload = json.loads(cached)
        if "open" in payload["price_history"]:
            return payload

    with log_duration(logger, f"銘柄詳細生成（{ticker}）"):
        # 移動平均線（特に75日線）の計算バッファとして、表示に必要な6ヶ月分より
        # 長めの2年分を取得する。
        history = fetch_price_history(ticker, period="2y")
        fundamentals = analyze_fundamentals(ticker)
        technical = analyze_technical(history)
        news = fetch_news(ticker)

        # チャート描画用に、pandasのDataFrameをJSONシリアライズ可能な
        # プレーンな辞書（日付文字列＋各系列のリスト）に変換する
        if history.empty:
            price_history = {
                "dates": [], "open": [], "high": [], "low": [], "close": [], "volume": []
            }
        else:
            price_history = {
                "dates": [d.isoformat() for d in history.index],
                "open": history["Open"].tolist(),
                "high": history["High"].tolist(),
                "low": history["Low"].tolist(),
                "close": history["Close"].tolist(),
                "volume": history["Volume"].tolist(),
            }

        # ここまでに集めたファンダメンタルズ・テクニカル・ニュースをプロンプトに
        # まとめ、LLMに銘柄の講評コメントを生成させる
        prompt = build_stock_detail_prompt(ticker, name, fundamentals, technical, news)
        comment = call_llm(prompt)

        payload = {
            "ticker": ticker,
            "name": name,
            "price_history": price_history,
            "fundamentals": fundamentals,
            "technical": technical,
            "news": news,
            "comment": comment,
        }
        write_cache(cache_dir, cache_key, json.dumps(payload, ensure_ascii=False))
        return payload
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_stock_detail.py -v`
Expected: 全テストPASS

- [ ] **Step 5: Commit**

```bash
git add stock_detail/detail.py tests/test_stock_detail.py
git commit -m "$(cat <<'EOF'
Log duration of stock detail generation on cache miss

Wraps the price/fundamentals/technical/news fetch plus the LLM
commentary call for a single ticker's detail dialog.
EOF
)"
```

---

### Task 9: `app_tabs/` — タブ表示・主要操作のログ

**Files:**
- Modify: `app_tabs/backtest_tab.py`
- Modify: `app_tabs/ranking_tab.py`
- Modify: `app_tabs/portfolio_tab.py`
- Modify: `app_tabs/screening_tab.py`
- Modify: `app_tabs/sector/tab.py`

**Interfaces:**
- Consumes: `common.logging_config.log_duration`（Task 1で実装済み）
- Produces: なし（このタスクが最終タスク。UI変更のため自動テストは追加しない）

- [ ] **Step 1: `backtest_tab.py`にログを追加**

`app_tabs/backtest_tab.py`全体を以下に置き換える（importに`logging`・`common.logging_config.log_duration`を追加、`logger`定義追加、`render_backtest_tab`冒頭にログ追加、データ不足エラー分岐に`logger.warning`追加、実行本体を`log_duration`で包む。それ以外のロジックは一切変更しない）:

```python
"""バックテストタブ: 単一銘柄・単一戦略のバックテスト実行。"""

import hashlib
import logging

import pandas as pd
import streamlit as st

from common.cache import read_cache, write_cache
from common.logging_config import log_duration
from portfolio_management.backtest import (
    STRATEGIES,
    generate_backtest_explanation,
    run_backtest_comparison,
)

from app_tabs.shared import CACHE_DIR, cached_fetch_price_history

logger = logging.getLogger(__name__)


def render_backtest_tab() -> None:
    logger.info("バックテストタブを表示")
    st.header("バックテスト")

    # 単一銘柄・単一戦略に対するバックテスト条件の入力
    backtest_strategy = st.selectbox(
        "戦略", list(STRATEGIES.keys()), key="backtest_strategy"
    )
    backtest_ticker = st.text_input(
        "銘柄コード", placeholder="7203.T", key="backtest_ticker"
    )
    backtest_period = st.selectbox(
        "取得期間", ["1y", "3y", "5y"], index=1, key="backtest_period"
    )
    apply_transaction_cost = st.checkbox(
        "取引コストを考慮する（1回あたり0.1%）", key="backtest_cost_checkbox"
    )
    backtest_force_regenerate = st.checkbox(
        "キャッシュを無視して再生成する", key="backtest_force_regenerate"
    )

    if backtest_ticker and st.button("バックテストを実行"):
        strategy = STRATEGIES[backtest_strategy]
        transaction_cost_pct = 0.1 if apply_transaction_cost else 0.0
        history = cached_fetch_price_history(backtest_ticker, backtest_period)

        # 戦略が要求する最低データ日数を満たさない場合は実行できない旨を伝える
        if history.empty or len(history) < strategy["min_days"]:
            logger.warning(
                "バックテスト実行不可（%s, データ日数不足または取得失敗）", backtest_ticker
            )
            st.error(
                "株価データが取得できないか、バックテストに必要な日数"
                f"（{strategy['min_days']}日）に満たないため実行できません。"
            )
        else:
            with log_duration(
                logger, f"バックテスト実行（{backtest_ticker}, {backtest_strategy}）"
            ):
                prices = history["Close"]

                # 戦略のプリセットパラメータごとに成績を比較する
                comparison = run_backtest_comparison(
                    prices, strategy["func"], strategy["presets"], transaction_cost_pct
                )
                comparison_df = pd.DataFrame(comparison).T
                comparison_df.index.name = "パラメータ組"

                st.subheader("パラメータ組ごとの比較")
                st.dataframe(
                    comparison_df,
                    column_config={
                        "total_return_pct": st.column_config.NumberColumn("累積リターン(%)"),
                        "benchmark_return_pct": st.column_config.NumberColumn("ベンチマーク(%)"),
                        "win_rate_pct": st.column_config.NumberColumn("勝率(%)"),
                        "max_drawdown_pct": st.column_config.NumberColumn("最大DD(%)"),
                        "trade_days": st.column_config.NumberColumn("取引日数"),
                    },
                )

                # バックテスト条件（戦略・銘柄・期間・コスト）が同一ならAI解説をキャッシュ再利用する
                cache_key = "backtest-" + hashlib.sha256(
                    f"{backtest_strategy}-{backtest_ticker}-{backtest_period}-{transaction_cost_pct}".encode(
                        "utf-8"
                    )
                ).hexdigest()[:12]
                cached_explanation = (
                    None if backtest_force_regenerate else read_cache(CACHE_DIR, cache_key)
                )

                if cached_explanation is not None:
                    explanation = cached_explanation
                else:
                    explanation = generate_backtest_explanation(
                        backtest_ticker,
                        prices,
                        backtest_func=strategy["func"],
                        strategy_name=backtest_strategy,
                        presets=strategy["presets"],
                        transaction_cost_pct=transaction_cost_pct,
                    )
                    write_cache(CACHE_DIR, cache_key, explanation)

                st.markdown(explanation)
```

- [ ] **Step 2: `ranking_tab.py`にログを追加**

`app_tabs/ranking_tab.py`の冒頭import・`render_ranking_tab`冒頭・データ取得ブロックを次のように変更する（`import logging`、`common.logging_config.log_duration`追加、`logger`定義、タブ表示ログ、対象銘柄0件エラー分岐に`logger.warning`、`if payload is None:`ブロック本体を`log_duration`で包む。それ以外は一切変更しない）:

現在（`app_tabs/ranking_tab.py:1-103`の該当部分）:
```python
"""一括バックテストタブ: ユニバース銘柄+保有銘柄を対象にした戦略ランキング。"""

import hashlib
import json

import pandas as pd
import streamlit as st

from common.cache import read_cache, write_cache
from common.concurrency import map_concurrently
from common.disclaimer import DISCLAIMER_NOTICE
from data_api.llm_client import call_llm
from portfolio_management.backtest import STRATEGIES, run_universe_backtest_ranking
from portfolio_management.storage import load_holdings
from portfolio_management.ticker_names import build_candidate_names
from prompt_patterns.backtest_explanation import generate_ranking_comments
from screening.universe import UNIVERSE

from app_tabs.shared import (
    CACHE_DIR,
    HOLDINGS_PATH,
    cached_fetch_japanese_name,
    cached_fetch_price_history,
    handle_table_selection,
)


def render_ranking_tab() -> None:
    st.header("複数銘柄一括バックテスト・ランキング")
    st.caption(
        "主要銘柄（UNIVERSE）と保有銘柄を対象に、選択した戦略の標準プリセットで"
        "バックテストし、リスク調整済みリターン（累積リターン÷|最大ドローダウン|）の高い順に並べます。"
    )

    ranking_strategy = st.selectbox(
        "戦略", list(STRATEGIES.keys()), key="ranking_strategy"
    )
    ranking_period = st.selectbox(
        "取得期間", ["1y", "3y", "5y"], index=1, key="ranking_period"
    )
    ranking_apply_cost = st.checkbox(
        "取引コストを考慮する（1回あたり0.1%）", key="ranking_cost_checkbox"
    )
    ranking_force_regenerate = st.checkbox(
        "キャッシュを無視して再生成する", key="ranking_force_regenerate"
    )

    if st.button("一括バックテストを実行"):
        strategy = STRATEGIES[ranking_strategy]
        transaction_cost_pct = 0.1 if ranking_apply_cost else 0.0

        # 分析対象はユニバース銘柄と保有銘柄の和集合とする
        holdings = load_holdings(HOLDINGS_PATH)
        holdings_tickers = [h["ticker"] for h in holdings if h.get("ticker")]
        target_tickers = sorted(set(UNIVERSE) | set(holdings_tickers))

        # 戦略・期間・コスト・対象銘柄集合が同一なら結果をキャッシュから再利用する
        cache_key = "universe-backtest-" + hashlib.sha256(
            f"{ranking_strategy}-{ranking_period}-{transaction_cost_pct}-"
            f"{'-'.join(target_tickers)}".encode("utf-8")
        ).hexdigest()[:12]
        cached_payload = None if ranking_force_regenerate else read_cache(CACHE_DIR, cache_key)

        payload = json.loads(cached_payload) if cached_payload is not None else None

        if payload is None:
            prices_by_ticker = {}
            skipped_tickers = []
            # 多数の銘柄の株価取得を並列化して待ち時間を短縮する
            with st.spinner(f"株価データを取得中...（{len(target_tickers)}銘柄）"):
                price_results = map_concurrently(
                    target_tickers,
                    lambda ticker: cached_fetch_price_history(ticker, ranking_period),
                )
            # データ取得に失敗・不足した銘柄はランキング対象から除外し、後で案内する
            for ticker in target_tickers:
                history = price_results[ticker]
                if isinstance(history, Exception) or history is None or history.empty:
                    skipped_tickers.append(ticker)
                else:
                    prices_by_ticker[ticker] = history["Close"]

            if not prices_by_ticker:
                st.error("バックテスト可能な銘柄がありませんでした。")
                payload = None
            else:
                # 標準プリセット（先頭のパラメータ組）で全銘柄を横並び比較しランキング化する
                standard_label, standard_params = strategy["presets"][0]
                ranking_rows = run_universe_backtest_ranking(
                    prices_by_ticker,
                    strategy["func"],
                    standard_params,
                    transaction_cost_pct=transaction_cost_pct,
                    min_days=strategy["min_days"],
                )
                comments = generate_ranking_comments(ranking_rows[:5], call_llm=call_llm)
                payload = {
                    "ranking_rows": ranking_rows,
                    "skipped_tickers": skipped_tickers,
                    "comments": comments,
                    "preset_label": standard_label,
                }
                write_cache(CACHE_DIR, cache_key, json.dumps(payload, ensure_ascii=False))

        if payload is not None:
            # 再実行後もランキング結果を表示し続けられるようセッションに保持する
            st.session_state["ranking_payload"] = payload
            st.session_state["ranking_strategy_label"] = ranking_strategy
            st.session_state["ranking_selected_row"] = None
            st.session_state["ranking_table"] = {"selection": {"rows": [], "columns": []}}
```

変更後（この部分のみ差し替え。以降の表示ロジック`if st.session_state.get("ranking_payload") is not None:`〜末尾は一切変更しない）:
```python
"""一括バックテストタブ: ユニバース銘柄+保有銘柄を対象にした戦略ランキング。"""

import hashlib
import json
import logging

import pandas as pd
import streamlit as st

from common.cache import read_cache, write_cache
from common.concurrency import map_concurrently
from common.disclaimer import DISCLAIMER_NOTICE
from common.logging_config import log_duration
from data_api.llm_client import call_llm
from portfolio_management.backtest import STRATEGIES, run_universe_backtest_ranking
from portfolio_management.storage import load_holdings
from portfolio_management.ticker_names import build_candidate_names
from prompt_patterns.backtest_explanation import generate_ranking_comments
from screening.universe import UNIVERSE

from app_tabs.shared import (
    CACHE_DIR,
    HOLDINGS_PATH,
    cached_fetch_japanese_name,
    cached_fetch_price_history,
    handle_table_selection,
)

logger = logging.getLogger(__name__)


def render_ranking_tab() -> None:
    logger.info("一括バックテストタブを表示")
    st.header("複数銘柄一括バックテスト・ランキング")
    st.caption(
        "主要銘柄（UNIVERSE）と保有銘柄を対象に、選択した戦略の標準プリセットで"
        "バックテストし、リスク調整済みリターン（累積リターン÷|最大ドローダウン|）の高い順に並べます。"
    )

    ranking_strategy = st.selectbox(
        "戦略", list(STRATEGIES.keys()), key="ranking_strategy"
    )
    ranking_period = st.selectbox(
        "取得期間", ["1y", "3y", "5y"], index=1, key="ranking_period"
    )
    ranking_apply_cost = st.checkbox(
        "取引コストを考慮する（1回あたり0.1%）", key="ranking_cost_checkbox"
    )
    ranking_force_regenerate = st.checkbox(
        "キャッシュを無視して再生成する", key="ranking_force_regenerate"
    )

    if st.button("一括バックテストを実行"):
        strategy = STRATEGIES[ranking_strategy]
        transaction_cost_pct = 0.1 if ranking_apply_cost else 0.0

        # 分析対象はユニバース銘柄と保有銘柄の和集合とする
        holdings = load_holdings(HOLDINGS_PATH)
        holdings_tickers = [h["ticker"] for h in holdings if h.get("ticker")]
        target_tickers = sorted(set(UNIVERSE) | set(holdings_tickers))

        # 戦略・期間・コスト・対象銘柄集合が同一なら結果をキャッシュから再利用する
        cache_key = "universe-backtest-" + hashlib.sha256(
            f"{ranking_strategy}-{ranking_period}-{transaction_cost_pct}-"
            f"{'-'.join(target_tickers)}".encode("utf-8")
        ).hexdigest()[:12]
        cached_payload = None if ranking_force_regenerate else read_cache(CACHE_DIR, cache_key)

        payload = json.loads(cached_payload) if cached_payload is not None else None

        if payload is None:
            with log_duration(
                logger, f"一括バックテスト実行（{ranking_strategy}, {len(target_tickers)}銘柄）"
            ):
                prices_by_ticker = {}
                skipped_tickers = []
                # 多数の銘柄の株価取得を並列化して待ち時間を短縮する
                with st.spinner(f"株価データを取得中...（{len(target_tickers)}銘柄）"):
                    price_results = map_concurrently(
                        target_tickers,
                        lambda ticker: cached_fetch_price_history(ticker, ranking_period),
                    )
                # データ取得に失敗・不足した銘柄はランキング対象から除外し、後で案内する
                for ticker in target_tickers:
                    history = price_results[ticker]
                    if isinstance(history, Exception) or history is None or history.empty:
                        skipped_tickers.append(ticker)
                    else:
                        prices_by_ticker[ticker] = history["Close"]

                if not prices_by_ticker:
                    logger.warning("一括バックテスト実行不可（対象銘柄が0件）")
                    st.error("バックテスト可能な銘柄がありませんでした。")
                    payload = None
                else:
                    # 標準プリセット（先頭のパラメータ組）で全銘柄を横並び比較しランキング化する
                    standard_label, standard_params = strategy["presets"][0]
                    ranking_rows = run_universe_backtest_ranking(
                        prices_by_ticker,
                        strategy["func"],
                        standard_params,
                        transaction_cost_pct=transaction_cost_pct,
                        min_days=strategy["min_days"],
                    )
                    comments = generate_ranking_comments(ranking_rows[:5], call_llm=call_llm)
                    payload = {
                        "ranking_rows": ranking_rows,
                        "skipped_tickers": skipped_tickers,
                        "comments": comments,
                        "preset_label": standard_label,
                    }
                    write_cache(CACHE_DIR, cache_key, json.dumps(payload, ensure_ascii=False))

        if payload is not None:
            # 再実行後もランキング結果を表示し続けられるようセッションに保持する
            st.session_state["ranking_payload"] = payload
            st.session_state["ranking_strategy_label"] = ranking_strategy
            st.session_state["ranking_selected_row"] = None
            st.session_state["ranking_table"] = {"selection": {"rows": [], "columns": []}}
```

- [ ] **Step 3: `portfolio_tab.py`にログを追加**

`app_tabs/portfolio_tab.py`に以下の変更を行う（他の行は一切変更しない）。

冒頭import（`app_tabs/portfolio_tab.py:1-26`）に`logging`と`logger`を追加:

現在:
```python
"""ポートフォリオタブ: 保有銘柄の管理とAIレビュー生成。"""

import hashlib
import json

import pandas as pd
import streamlit as st

from analysis_agents.news_research_agent import research_news_batch
from analysis_agents.technical_agent import analyze_technical
from common.cache import read_cache, write_cache
from common.concurrency import map_concurrently
from data_api.llm_client import call_llm
from portfolio_management.review import generate_portfolio_review
from portfolio_management.storage import load_holdings, save_holdings
from portfolio_management.ticker_names import build_candidate_names

from app_tabs.shared import (
    CACHE_DIR,
    HOLDINGS_PATH,
    cached_analyze_fundamentals,
    cached_fetch_japanese_name,
    cached_fetch_news,
    cached_fetch_price_history,
    handle_table_selection,
)


def render_portfolio_tab() -> None:
    st.header("保有銘柄ポートフォリオ")
```

変更後:
```python
"""ポートフォリオタブ: 保有銘柄の管理とAIレビュー生成。"""

import hashlib
import json
import logging

import pandas as pd
import streamlit as st

from analysis_agents.news_research_agent import research_news_batch
from analysis_agents.technical_agent import analyze_technical
from common.cache import read_cache, write_cache
from common.concurrency import map_concurrently
from common.logging_config import log_duration
from data_api.llm_client import call_llm
from portfolio_management.review import generate_portfolio_review
from portfolio_management.storage import load_holdings, save_holdings
from portfolio_management.ticker_names import build_candidate_names

from app_tabs.shared import (
    CACHE_DIR,
    HOLDINGS_PATH,
    cached_analyze_fundamentals,
    cached_fetch_japanese_name,
    cached_fetch_news,
    cached_fetch_price_history,
    handle_table_selection,
)

logger = logging.getLogger(__name__)


def render_portfolio_tab() -> None:
    logger.info("ポートフォリオタブを表示")
    st.header("保有銘柄ポートフォリオ")
```

レビュー生成ブロック（`app_tabs/portfolio_tab.py:132-196`）の`if payload is None:`本体を`log_duration`で包む:

現在:
```python
        if payload is None:
            current_prices = {}
            price_histories = {}
            fundamentals_by_ticker = {}
            technicals_by_ticker = {}
            news_by_ticker = {}

            def _fetch_holding_data(ticker: str):
                """1銘柄分の株価履歴・ファンダメンタルズ・テクニカル・ニュースをまとめて取得する。
                並列実行（map_concurrently）から呼び出される単位関数。
                """
                history = cached_fetch_price_history(ticker, "6mo")
                fundamentals = cached_analyze_fundamentals(ticker)
                technical = analyze_technical(history)
                news = cached_fetch_news(ticker)
                return history, fundamentals, technical, news

            # 保有銘柄すべてのデータ取得を並列化し、待ち時間を短縮する
            holding_tickers = [holding["ticker"] for holding in holdings]
            with st.spinner("保有銘柄データを取得中..."):
                holding_results = map_concurrently(holding_tickers, _fetch_holding_data)

            # 取得に失敗した銘柄（例外）はレビュー対象から除外する
            for ticker in holding_tickers:
                result = holding_results[ticker]
                if isinstance(result, Exception):
                    continue
                history, fundamentals, technical, news = result
                if not history.empty:
                    current_prices[ticker] = float(history["Close"].iloc[-1])
                    price_histories[ticker] = history["Close"]
                fundamentals_by_ticker[ticker] = fundamentals
                technicals_by_ticker[ticker] = technical
                news_by_ticker[ticker] = news

            # 銘柄ごとのニュースをまとめてLLMに渡し、センチメントを一括判定する
            news_sentiment_by_ticker = research_news_batch(news_by_ticker, call_llm=call_llm)

            report = generate_portfolio_review(
                holdings,
                current_prices,
                price_histories,
                fundamentals_by_ticker,
                technicals_by_ticker,
                news_sentiment_by_ticker,
                names_by_ticker=candidate_names,
                call_llm=call_llm,
            )
            payload = {
                "report": report,
                "news_by_ticker": news_by_ticker,
                "news_sentiment_by_ticker": news_sentiment_by_ticker,
            }
            write_cache(CACHE_DIR, cache_key, json.dumps(payload, ensure_ascii=False))
```

変更後:
```python
        if payload is None:
            with log_duration(logger, f"ポートフォリオレビュー生成（{len(holdings)}銘柄）"):
                current_prices = {}
                price_histories = {}
                fundamentals_by_ticker = {}
                technicals_by_ticker = {}
                news_by_ticker = {}

                def _fetch_holding_data(ticker: str):
                    """1銘柄分の株価履歴・ファンダメンタルズ・テクニカル・ニュースをまとめて取得する。
                    並列実行（map_concurrently）から呼び出される単位関数。
                    """
                    history = cached_fetch_price_history(ticker, "6mo")
                    fundamentals = cached_analyze_fundamentals(ticker)
                    technical = analyze_technical(history)
                    news = cached_fetch_news(ticker)
                    return history, fundamentals, technical, news

                # 保有銘柄すべてのデータ取得を並列化し、待ち時間を短縮する
                holding_tickers = [holding["ticker"] for holding in holdings]
                with st.spinner("保有銘柄データを取得中..."):
                    holding_results = map_concurrently(holding_tickers, _fetch_holding_data)

                # 取得に失敗した銘柄（例外）はレビュー対象から除外する
                for ticker in holding_tickers:
                    result = holding_results[ticker]
                    if isinstance(result, Exception):
                        continue
                    history, fundamentals, technical, news = result
                    if not history.empty:
                        current_prices[ticker] = float(history["Close"].iloc[-1])
                        price_histories[ticker] = history["Close"]
                    fundamentals_by_ticker[ticker] = fundamentals
                    technicals_by_ticker[ticker] = technical
                    news_by_ticker[ticker] = news

                # 銘柄ごとのニュースをまとめてLLMに渡し、センチメントを一括判定する
                news_sentiment_by_ticker = research_news_batch(news_by_ticker, call_llm=call_llm)

                report = generate_portfolio_review(
                    holdings,
                    current_prices,
                    price_histories,
                    fundamentals_by_ticker,
                    technicals_by_ticker,
                    news_sentiment_by_ticker,
                    names_by_ticker=candidate_names,
                    call_llm=call_llm,
                )
                payload = {
                    "report": report,
                    "news_by_ticker": news_by_ticker,
                    "news_sentiment_by_ticker": news_sentiment_by_ticker,
                }
                write_cache(CACHE_DIR, cache_key, json.dumps(payload, ensure_ascii=False))
```

- [ ] **Step 4: `screening_tab.py`にログを追加**

`app_tabs/screening_tab.py`全体を以下に置き換える（importに`logging`・`common.logging_config.log_duration`追加、`logger`定義、タブ表示ログ、JSON解析失敗の分岐に`logger.warning`追加、「この条件で絞り込む」ボタンの本体を`log_duration`で包む。それ以外は一切変更しない）:

```python
"""スクリーニングタブ: 自然言語条件によるユニバース銘柄の絞り込み。"""

import json
import logging

import streamlit as st

from common.json_parsing import strip_code_fence
from common.logging_config import log_duration
from data_api.llm_client import call_llm
from data_api.stock_price_api import fetch_universe_fundamentals
from prompt_patterns.screening import (
    apply_filters,
    build_screening_prompt,
    generate_screening_comments,
)
from screening.sectors import SECTOR_MAP
from screening.universe import UNIVERSE, UNIVERSE_NAMES

from app_tabs.shared import CACHE_DIR, handle_table_selection

logger = logging.getLogger(__name__)


def render_screening_tab() -> None:
    logger.info("スクリーニングタブを表示")
    st.header("銘柄スクリーニング")

    condition_text = st.text_input(
        "スクリーニング条件を自然言語で入力してください",
        placeholder="PERが15倍以下で配当利回りが3%以上",
    )

    if condition_text:
        # 入力条件が前回から変わった場合のみLLMを呼び出し、自然言語条件を
        # 構造化フィルタ（JSON）に変換する。変わっていなければ結果をセッションから再利用する
        if st.session_state.get("screening_condition_text") != condition_text:
            prompt = build_screening_prompt(
                condition_text, sectors=sorted(set(SECTOR_MAP.values()))
            )
            raw_filters = call_llm(prompt)
            st.session_state["screening_condition_text"] = condition_text
            try:
                st.session_state["screening_filters"] = json.loads(strip_code_fence(raw_filters))
                st.session_state["screening_filters_error"] = False
            except json.JSONDecodeError:
                # LLMの出力が不正なJSONだった場合はエラーとして扱い、フィルタなしにする
                logger.warning("スクリーニング条件のJSON解析に失敗しました")
                st.session_state["screening_filters"] = None
                st.session_state["screening_filters_error"] = True

        filters = st.session_state.get("screening_filters")
        if st.session_state.get("screening_filters_error"):
            st.error("条件の解釈に失敗しました。条件を言い換えて再度お試しください。")

        if filters is not None:
            # 実際に適用する前にAIが解釈した条件をユーザーに確認させる
            st.subheader("AIが解釈した条件（適用前に確認してください）")
            st.json(filters)

            # ユニバース銘柄のファンダメンタルズを取得し、条件でフィルタしてAIコメントを付与する
            if st.button("この条件で絞り込む"):
                with log_duration(logger, "スクリーニング絞り込み実行"):
                    universe_df = fetch_universe_fundamentals(UNIVERSE, CACHE_DIR)
                    universe_df["name"] = universe_df["ticker"].map(UNIVERSE_NAMES).fillna(
                        universe_df["name"]
                    )
                    universe_df["sector"] = universe_df["ticker"].map(SECTOR_MAP)
                    result_df = apply_filters(universe_df, filters)
                    comments = generate_screening_comments(result_df, call_llm=call_llm)

                    st.session_state["screening_result_df"] = result_df
                    st.session_state["screening_comments"] = comments
                    st.session_state["screening_selected_row"] = None
                    st.session_state["screening_result_table"] = {
                        "selection": {"rows": [], "columns": []}
                    }

    # 絞り込み結果があれば、選択可能な一覧表と銘柄ごとのAIコメントを表示する
    if st.session_state.get("screening_result_df") is not None:
        result_df = st.session_state["screening_result_df"]
        comments = st.session_state["screening_comments"]

        st.subheader(f"絞り込み結果（{len(result_df)}件）")
        st.caption("行をクリックすると銘柄詳細を表示します。")
        event = st.dataframe(
            result_df,
            column_config={
                "ticker": st.column_config.TextColumn("銘柄コード"),
                "name": st.column_config.TextColumn("銘柄名"),
                "sector": st.column_config.TextColumn("業種"),
                "per": st.column_config.NumberColumn("PER"),
                "pbr": st.column_config.NumberColumn("PBR"),
                "dividend_yield_pct": st.column_config.NumberColumn("配当利回り(%)"),
                "market_cap": st.column_config.NumberColumn("時価総額"),
            },
            on_select="rerun",
            selection_mode="single-row",
            key="screening_result_table",
        )
        handle_table_selection("screening_selected_row", event, result_df)

        st.subheader("銘柄ごとのAIコメント")
        for row in result_df.itertuples():
            st.write(
                f"**{row.ticker} {row.name}**: "
                f"{comments.get(row.ticker, 'コメント生成失敗')}"
            )
```

- [ ] **Step 5: `sector/tab.py`にログを追加**

`app_tabs/sector/tab.py`に以下の変更を行う（他の行は一切変更しない）。

冒頭import（`app_tabs/sector/tab.py:1-32`）に`logging`と`logger`を追加、`render_sector_tab`冒頭にログを追加:

現在:
```python
"""セクタータブ: セクターローテーション分析のエントリーポイント。
表示設定・分析実行（データ取得・キャッシュ）を担当し、個別グラフの描画は
app_tabs.sector 配下の各モジュールに委譲する。
"""

import hashlib
import json

import pandas as pd
import streamlit as st

from common.cache import read_cache, write_cache
from common.concurrency import map_concurrently
from common.disclaimer import DISCLAIMER_NOTICE
from data_api.llm_client import call_llm
from prompt_patterns.sector_rotation import generate_sector_rotation_comments
from screening.sectors import SECTOR_MAP
from screening.universe import UNIVERSE
from sector_analysis.correlation import compute_lead_lag_pairs, compute_sector_returns
from sector_analysis.display_settings import (
    load_sector_display_settings,
    save_sector_display_settings,
)
from sector_analysis.wavelet import compute_all_pairs_dominant_lag, serialize_sector_returns

from app_tabs.sector.ai_comments import render_ai_comments
from app_tabs.sector.heatmap import render_heatmap
from app_tabs.sector.network_diagram import render_network_diagram
from app_tabs.sector.pairs_table import render_pairs_table
from app_tabs.sector.wavelet_analysis import render_wavelet_analysis
from app_tabs.shared import CACHE_DIR, SECTOR_DISPLAY_SETTINGS_PATH, cached_fetch_price_history


def render_sector_tab() -> None:
    st.header("セクターローテーション")
```

変更後:
```python
"""セクタータブ: セクターローテーション分析のエントリーポイント。
表示設定・分析実行（データ取得・キャッシュ）を担当し、個別グラフの描画は
app_tabs.sector 配下の各モジュールに委譲する。
"""

import hashlib
import json
import logging

import pandas as pd
import streamlit as st

from common.cache import read_cache, write_cache
from common.concurrency import map_concurrently
from common.disclaimer import DISCLAIMER_NOTICE
from common.logging_config import log_duration
from data_api.llm_client import call_llm
from prompt_patterns.sector_rotation import generate_sector_rotation_comments
from screening.sectors import SECTOR_MAP
from screening.universe import UNIVERSE
from sector_analysis.correlation import compute_lead_lag_pairs, compute_sector_returns
from sector_analysis.display_settings import (
    load_sector_display_settings,
    save_sector_display_settings,
)
from sector_analysis.wavelet import compute_all_pairs_dominant_lag, serialize_sector_returns

from app_tabs.sector.ai_comments import render_ai_comments
from app_tabs.sector.heatmap import render_heatmap
from app_tabs.sector.network_diagram import render_network_diagram
from app_tabs.sector.pairs_table import render_pairs_table
from app_tabs.sector.wavelet_analysis import render_wavelet_analysis
from app_tabs.shared import CACHE_DIR, SECTOR_DISPLAY_SETTINGS_PATH, cached_fetch_price_history

logger = logging.getLogger(__name__)


def render_sector_tab() -> None:
    logger.info("セクターローテーションタブを表示")
    st.header("セクターローテーション")
```

分析実行ブロック（`app_tabs/sector/tab.py:160-198`）の`if payload is None:`本体を`log_duration`で包む:

現在:
```python
        if payload is None:
            skipped_tickers = []
            prices_by_ticker = {}
            # ユニバース全銘柄の株価取得を並列化して待ち時間を短縮する
            with st.spinner(f"株価データを取得中...（{len(UNIVERSE)}銘柄）"):
                price_results = map_concurrently(
                    UNIVERSE,
                    lambda ticker: cached_fetch_price_history(ticker, sector_period),
                )
            # データ取得に失敗・不足した銘柄は分析対象から除外する
            for ticker in UNIVERSE:
                history = price_results[ticker]
                if isinstance(history, Exception) or history is None or history.empty:
                    skipped_tickers.append(ticker)
                else:
                    prices_by_ticker[ticker] = history["Close"]

            if not prices_by_ticker:
                st.error("分析可能な銘柄がありませんでした。")
                payload = None
            else:
                # 銘柄別リターンを業種別に集約し、業種間のリード・ラグ相関を算出する
                sector_returns = compute_sector_returns(prices_by_ticker, SECTOR_MAP)
                excluded_sectors = sorted(
                    set(SECTOR_MAP.values()) - set(sector_returns.keys())
                )
                pairs = compute_lead_lag_pairs(sector_returns, max_lag_days=20)
                with st.spinner("ネットワーク図データを計算中（136ペア）..."):
                    network_pairs_df = compute_all_pairs_dominant_lag(sector_returns)
                comments = generate_sector_rotation_comments(pairs[:5], call_llm=call_llm)
                payload = {
                    "pairs": pairs,
                    "skipped_tickers": skipped_tickers,
                    "excluded_sectors": excluded_sectors,
                    "comments": comments,
                    "sector_returns": serialize_sector_returns(sector_returns),
                    "network_pairs": network_pairs_df.to_dict("records"),
                }
                write_cache(CACHE_DIR, cache_key, json.dumps(payload, ensure_ascii=False))
```

変更後:
```python
        if payload is None:
            with log_duration(logger, f"セクターローテーション分析実行（{sector_period}）"):
                skipped_tickers = []
                prices_by_ticker = {}
                # ユニバース全銘柄の株価取得を並列化して待ち時間を短縮する
                with st.spinner(f"株価データを取得中...（{len(UNIVERSE)}銘柄）"):
                    price_results = map_concurrently(
                        UNIVERSE,
                        lambda ticker: cached_fetch_price_history(ticker, sector_period),
                    )
                # データ取得に失敗・不足した銘柄は分析対象から除外する
                for ticker in UNIVERSE:
                    history = price_results[ticker]
                    if isinstance(history, Exception) or history is None or history.empty:
                        skipped_tickers.append(ticker)
                    else:
                        prices_by_ticker[ticker] = history["Close"]

                if not prices_by_ticker:
                    logger.warning("セクターローテーション分析実行不可（対象銘柄が0件）")
                    st.error("分析可能な銘柄がありませんでした。")
                    payload = None
                else:
                    # 銘柄別リターンを業種別に集約し、業種間のリード・ラグ相関を算出する
                    sector_returns = compute_sector_returns(prices_by_ticker, SECTOR_MAP)
                    excluded_sectors = sorted(
                        set(SECTOR_MAP.values()) - set(sector_returns.keys())
                    )
                    pairs = compute_lead_lag_pairs(sector_returns, max_lag_days=20)
                    with st.spinner("ネットワーク図データを計算中（136ペア）..."):
                        network_pairs_df = compute_all_pairs_dominant_lag(sector_returns)
                    comments = generate_sector_rotation_comments(pairs[:5], call_llm=call_llm)
                    payload = {
                        "pairs": pairs,
                        "skipped_tickers": skipped_tickers,
                        "excluded_sectors": excluded_sectors,
                        "comments": comments,
                        "sector_returns": serialize_sector_returns(sector_returns),
                        "network_pairs": network_pairs_df.to_dict("records"),
                    }
                    write_cache(CACHE_DIR, cache_key, json.dumps(payload, ensure_ascii=False))
```

- [ ] **Step 6: 既存の自動テストが壊れていないことを確認**

Run: `uv run pytest -v`
Expected: 既存の全テストがPASS（`app_tabs/`はUI自動テスト対象外だが、他モジュールへの影響がないことを確認する）

- [ ] **Step 7: アプリを起動して動作確認**

Run: `uv run python -m streamlit run app.py`

確認項目（`app/logs/app.log`をエディタ等で開いて確認する）:
1. 5つのタブをそれぞれ一度開き、`バックテストタブを表示` / `一括バックテストタブを表示` / `ポートフォリオタブを表示` / `スクリーニングタブを表示` / `セクターローテーションタブを表示`のログ行が記録される
2. バックテストタブで銘柄コードを入力し「バックテストを実行」→ `バックテスト実行（...）を開始`〜`が完了しました（X.XX秒）`のペアが記録される。ログの前後に`Claude CLI呼び出しを開始`/`が完了しました`、`キャッシュヒット`または`キャッシュミス`のログも挟まれている
3. バックテストタブでデータ不足の銘柄コード（例: 上場直後の銘柄など、もしくは存在しないティッカー）を指定して実行 →`バックテスト実行不可`のWARNINGログが記録され、例外でアプリが落ちない
4. セクターローテーションタブで「分析を実行」→ `セクターローテーション分析実行（...）を開始`のログの中に`ユニバースfundamentals一括取得`は出ない（このタブは`fetch_universe_fundamentals`を使わないため）が、`業種別リターン集計`・`リード・ラグ相関計算`・`ウェーブレット全ペア計算`の開始/完了ログが順番に記録される
5. 一連の操作を通じてログファイルが1操作あたり数行〜十数行程度に収まっており（226銘柄分のログが個別に出力されるような暴走がない）、読みやすい

- [ ] **Step 8: Commit**

```bash
git add app_tabs/backtest_tab.py app_tabs/ranking_tab.py app_tabs/portfolio_tab.py app_tabs/screening_tab.py app_tabs/sector/tab.py
git commit -m "$(cat <<'EOF'
Log tab display and main operations across all five tabs

Each render_*_tab() now logs on display, and the button-triggered
heavy operation (backtest run, universe ranking, portfolio review,
screening filter, sector rotation analysis) is wrapped in
log_duration. Data-unavailable error branches also log a warning
alongside the existing st.error() message.
EOF
)"
```

---

## Self-Review Notes

- **Spec coverage:** design docの「呼び出し箇所一覧」の全行（各タブ主要操作／外部I/O／キャッシュ／分析・バックテスト処理）はTask 3〜9でカバーしている。「対象外とする箇所」（`analysis_agents/*.py`、`stock_price_api.py`の単体取得関数）はどのタスクでも変更しておらず、Global Constraintsに明記した。`.gitignore`更新はTask 2でカバー。テスト方針（`tests/test_logging_config.py`の冪等性・caplog検証）はTask 1でカバー。
- **Placeholder scan:** 各Stepのコードブロックは実際のコード（変更箇所は全文、変更のない既存関数本体の内部ループ等は元コードのまま引用）。「TBD」等のプレースホルダーは含まない。
- **Type consistency:** `log_duration(logger: logging.Logger, action: str)`のシグネチャはTask 1で定義した形をTask 3〜9まで一貫して使用している。`setup_logging(log_dir: Path = LOG_DIR) -> None`もTask 1〜2で一貫。
