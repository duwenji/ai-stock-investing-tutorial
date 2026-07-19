# ポートフォリオ管理・スクリーニング統合アプリ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ai-stock-investing-tutorial/app/` に、保有銘柄のポートフォリオレビューと自然言語スクリーニングを1つのStreamlit Webアプリで提供する、実際に使える個人用ツールを構築する。

**Architecture:** Streamlit単一アプリ（`st.tabs` でポートフォリオ／スクリーニングを切替）。バックエンドは `data_api` / `analysis_agents` / `prompt_patterns` / `portfolio_management` / `screening` / `common` の素のPythonパッケージとして実装し、`app.py` はそれらを呼び出すだけの薄いUI層にする。

**Tech Stack:** Python 3.14（`uv` 管理）、Streamlit、yfinance、pandas、pytest。LLM呼び出しはOpenAI/Anthropic APIではなく、Claude Code CLI（`claude` コマンド）をサブプロセスとして実行する。

参照spec: [app/docs/superpowers/specs/2026-07-19-portfolio-screening-app-design.md](../specs/2026-07-19-portfolio-screening-app-design.md)

## Global Constraints

- 実行対象は個人ローカル実行のWebアプリ。認証・複数ユーザー対応は行わない。
- 対象市場は日本株（`.T` サフィックス）中心。
- アーキテクチャはStreamlit単一アプリ + `st.tabs` によるタブ切替（マルチページ化・FastAPI分離は行わない）。
- LLM連携は Claude Code CLI（`claude` コマンド）をサブプロセスとして呼び出す。`subprocess.run` は必ずリスト引数で呼び出し、`shell=True` は使用しない。
- モジュール構成は `data_api` / `analysis_agents` / `prompt_patterns` / `portfolio_management` / `screening` / `common` のパッケージ名を踏襲する。
- `common.disclaimer.DISCLAIMER_NOTICE` を、生成する全レポート・レビュー本文の冒頭・末尾に必ず挿入する。
- スクリーニング対象ユニバースは固定の主要40〜50銘柄（日経225構成銘柄のうち時価総額上位、セクター分散を考慮）とする。日経225全銘柄は対象にしない。
- パッケージ管理は `uv` を使用する（Python 3.14系）。
- v1スコープ外: MCPサーバー化、メール/Slack通知、複数ユーザー対応・認証、日経225全銘柄対応、バックテスト機能。
- 特記のない限り、コマンドはリポジトリルート `ai-stock-investing-tutorial/` で実行する想定。`app/` 内で実行するコマンドには `cd app &&` を明記する。

---

### Task 1: プロジェクトscaffolding（uvプロジェクト初期化）

**Files:**
- Create: `app/pyproject.toml`（`uv init` が生成）
- Create: `app/.gitignore`（`uv init` が生成、`data/` を追記）
- Create: `app/.env.example`
- Create: `app/common/__init__.py`, `app/data_api/__init__.py`, `app/analysis_agents/__init__.py`, `app/prompt_patterns/__init__.py`, `app/portfolio_management/__init__.py`, `app/screening/__init__.py`
- Create: `app/tests/test_smoke.py`
- Delete: `app/main.py`（`uv init --app` が生成する不要なひな形）

**Interfaces:**
- Produces: `uv run pytest`（`app/` 内）でテストが実行できる状態。以降の全タスクはこのpytest設定に依存する。

- [ ] **Step 1: uvプロジェクトを初期化する**

Run:
```bash
cd app && uv init --app --name stock-advisor-app
```
Expected: `pyproject.toml`, `main.py`, `.python-version`, `README.md`, `.gitignore` が `app/` 直下に生成される。

- [ ] **Step 2: 不要なひな形ファイルを削除する**

Run:
```bash
cd app && rm main.py
```

- [ ] **Step 3: 依存パッケージを追加する**

Run:
```bash
cd app && uv add streamlit yfinance pandas
cd app && uv add --dev pytest
```
Expected: `pyproject.toml` の `dependencies` / `[dependency-groups] dev` に追加され、`app/uv.lock` が生成される。

- [ ] **Step 4: pytest設定を `pyproject.toml` に追記する**

`app/pyproject.toml` の末尾に以下を追記する。

```toml

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 5: パッケージディレクトリと `__init__.py` を作成する**

Run:
```bash
cd app && mkdir -p common data_api analysis_agents prompt_patterns portfolio_management screening tests
cd app && touch common/__init__.py data_api/__init__.py analysis_agents/__init__.py prompt_patterns/__init__.py portfolio_management/__init__.py screening/__init__.py
```

- [ ] **Step 6: `.env.example` を作成する**

Create `app/.env.example`:
```
# このアプリはOpenAI/Anthropic APIキーを使用しません。
# LLM呼び出しはClaude Code CLI（`claude`コマンド）のサブプロセス実行で行います。
# `claude` コマンドがインストール・ログイン済みであることを確認してください。
```

- [ ] **Step 7: `.gitignore` に実行時データを追記する**

`app/.gitignore` の末尾に以下を追記する。
```
data/
```

- [ ] **Step 8: スモークテストを書いて設定を検証する**

Create `app/tests/test_smoke.py`:
```python
def test_smoke():
    assert True
```

- [ ] **Step 9: テストを実行し、設定が正しいことを確認する**

Run:
```bash
cd app && uv run pytest -v
```
Expected: `tests/test_smoke.py::test_smoke PASSED`、`1 passed`

- [ ] **Step 10: コミットする**

```bash
git add app
git commit -m "feat: scaffold stock-advisor-app uv project"
```

---

### Task 2: `common/disclaimer.py` — 免責事項定数

**Files:**
- Create: `app/common/disclaimer.py`
- Test: `app/tests/test_disclaimer.py`

**Interfaces:**
- Produces: `DISCLAIMER_NOTICE: str`（`common.disclaimer` からimportして使う。後続の `prompt_patterns.report_generation`, `portfolio_management.review`, `app.py` が利用する）

- [ ] **Step 1: 失敗するテストを書く**

Create `app/tests/test_disclaimer.py`:
```python
from common.disclaimer import DISCLAIMER_NOTICE


def test_disclaimer_notice_mentions_not_investment_advice():
    assert "投資助言ではありません" in DISCLAIMER_NOTICE


def test_disclaimer_notice_mentions_educational_purpose():
    assert "教育目的" in DISCLAIMER_NOTICE
```

- [ ] **Step 2: テストを実行し失敗を確認する**

Run: `cd app && uv run pytest tests/test_disclaimer.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'common.disclaimer'`）

- [ ] **Step 3: 実装する**

Create `app/common/disclaimer.py`:
```python
DISCLAIMER_NOTICE = (
    "本レポートは教育目的の情報提供であり、投資助言ではありません。"
    "個別銘柄の売買を推奨するものではなく、AIによる考察には誤りが"
    "含まれる可能性があります。投資判断は自己責任で、一次情報の"
    "確認のうえ行ってください。"
)
```

- [ ] **Step 4: テストを実行し成功を確認する**

Run: `cd app && uv run pytest tests/test_disclaimer.py -v`
Expected: `2 passed`

- [ ] **Step 5: コミットする**

```bash
git add app/common/disclaimer.py app/tests/test_disclaimer.py
git commit -m "feat: add disclaimer notice constant"
```

---

### Task 3: `common/cache.py` — 日付キー付きファイルキャッシュ

**Files:**
- Create: `app/common/cache.py`
- Test: `app/tests/test_cache.py`

**Interfaces:**
- Produces: `get_cache_path(cache_dir: Path, key: str) -> Path`, `read_cache(cache_dir: Path, key: str) -> str | None`, `write_cache(cache_dir: Path, key: str, content: str) -> None`（`data_api.stock_price_api.fetch_universe_fundamentals` と `app.py` のポートフォリオレビューキャッシュが利用する）

- [ ] **Step 1: 失敗するテストを書く**

Create `app/tests/test_cache.py`:
```python
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
```

- [ ] **Step 2: テストを実行し失敗を確認する**

Run: `cd app && uv run pytest tests/test_cache.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'common.cache'`）

- [ ] **Step 3: 実装する**

Create `app/common/cache.py`:
```python
import datetime
from pathlib import Path


def get_cache_path(cache_dir: Path, key: str) -> Path:
    today = datetime.date.today().isoformat()
    return Path(cache_dir) / f"{today}-{key}.txt"


def read_cache(cache_dir: Path, key: str) -> str | None:
    path = get_cache_path(cache_dir, key)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def write_cache(cache_dir: Path, key: str, content: str) -> None:
    path = get_cache_path(cache_dir, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
```

- [ ] **Step 4: テストを実行し成功を確認する**

Run: `cd app && uv run pytest tests/test_cache.py -v`
Expected: `3 passed`

- [ ] **Step 5: コミットする**

```bash
git add app/common/cache.py app/tests/test_cache.py
git commit -m "feat: add date-keyed file cache helper"
```

---

### Task 4: `data_api/llm_client.py` — Claude Code CLI経由のcall_llm

**Files:**
- Create: `app/data_api/llm_client.py`
- Test: `app/tests/test_llm_client.py`

**Interfaces:**
- Produces: `class ClaudeCLINotFoundError(RuntimeError)`, `class ClaudeCLIError(RuntimeError)`, `check_claude_cli_available() -> None`, `call_llm(prompt: str, timeout: int = 120) -> str`（後続の全LLM呼び出し箇所が利用するデフォルト実装）

- [ ] **Step 1: 失敗するテストを書く**

Create `app/tests/test_llm_client.py`:
```python
import subprocess

import pytest

from data_api.llm_client import (
    ClaudeCLIError,
    ClaudeCLINotFoundError,
    call_llm,
    check_claude_cli_available,
)


def test_call_llm_returns_stdout_on_success(monkeypatch):
    def fake_run(args, capture_output, text, timeout):
        assert args == ["claude", "-p", "hello"]
        return subprocess.CompletedProcess(args, 0, stdout="response text\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert call_llm("hello") == "response text"


def test_call_llm_raises_on_nonzero_exit(monkeypatch):
    def fake_run(args, capture_output, text, timeout):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ClaudeCLIError):
        call_llm("hello")


def test_check_claude_cli_available_raises_when_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(ClaudeCLINotFoundError):
        check_claude_cli_available()


def test_check_claude_cli_available_passes_when_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/claude")
    check_claude_cli_available()
```

- [ ] **Step 2: テストを実行し失敗を確認する**

Run: `cd app && uv run pytest tests/test_llm_client.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'data_api.llm_client'`）

- [ ] **Step 3: 実装する**

Create `app/data_api/llm_client.py`:
```python
import shutil
import subprocess


class ClaudeCLINotFoundError(RuntimeError):
    pass


class ClaudeCLIError(RuntimeError):
    pass


def check_claude_cli_available() -> None:
    if shutil.which("claude") is None:
        raise ClaudeCLINotFoundError(
            "Claude Code CLI（`claude`コマンド）が見つかりません。"
            "インストールとログインを確認してください。"
        )


def call_llm(prompt: str, timeout: int = 120) -> str:
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise ClaudeCLIError(f"Claude Code CLIの実行に失敗しました: {result.stderr.strip()}")
    return result.stdout.strip()
```

- [ ] **Step 4: テストを実行し成功を確認する**

Run: `cd app && uv run pytest tests/test_llm_client.py -v`
Expected: `4 passed`

- [ ] **Step 5: コミットする**

```bash
git add app/data_api/llm_client.py app/tests/test_llm_client.py
git commit -m "feat: call LLM via Claude Code CLI subprocess"
```

---

### Task 5: `data_api/stock_price_api.py` — yfinance連携（基本関数）

**Files:**
- Create: `app/data_api/stock_price_api.py`
- Test: `app/tests/test_stock_price_api.py`

**Interfaces:**
- Produces: `fetch_price_history(ticker_symbol: str, period: str = "1mo") -> pd.DataFrame`, `fetch_fundamentals(ticker_symbol: str) -> dict`（キー: `ticker`, `name`, `trailing_pe`, `price_to_book`, `dividend_yield`, `market_cap`）, `fetch_news(ticker_symbol: str, limit: int = 5) -> list[dict]`（各要素は `{"title": str, "publisher": str}`）

- [ ] **Step 1: 失敗するテストを書く**

Create `app/tests/test_stock_price_api.py`:
```python
import pandas as pd

import data_api.stock_price_api as stock_price_api


class FakeTicker:
    def __init__(self, symbol):
        self.symbol = symbol

    def history(self, period="1mo"):
        return pd.DataFrame({"Close": [100, 101, 102]})

    @property
    def info(self):
        return {
            "longName": "Fake Corp",
            "trailingPE": 12.3,
            "priceToBook": 1.1,
            "dividendYield": 0.02,
            "marketCap": 1_000_000,
        }

    @property
    def news(self):
        return [
            {"title": "Headline 1", "publisher": "Pub"},
            {"title": "Headline 2", "publisher": "Pub2"},
        ]


class EmptyInfoTicker(FakeTicker):
    @property
    def info(self):
        return {}


def test_fetch_price_history_returns_dataframe(monkeypatch):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    df = stock_price_api.fetch_price_history("7203.T")
    assert list(df["Close"]) == [100, 101, 102]


def test_fetch_fundamentals_maps_info_fields(monkeypatch):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    result = stock_price_api.fetch_fundamentals("7203.T")
    assert result["ticker"] == "7203.T"
    assert result["name"] == "Fake Corp"
    assert result["trailing_pe"] == 12.3
    assert result["price_to_book"] == 1.1
    assert result["dividend_yield"] == 0.02
    assert result["market_cap"] == 1_000_000


def test_fetch_fundamentals_missing_fields_return_none(monkeypatch):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", EmptyInfoTicker)
    result = stock_price_api.fetch_fundamentals("7203.T")
    assert result["trailing_pe"] is None
    assert result["price_to_book"] is None


def test_fetch_news_returns_title_and_publisher(monkeypatch):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    news = stock_price_api.fetch_news("7203.T", limit=1)
    assert news == [{"title": "Headline 1", "publisher": "Pub"}]
```

- [ ] **Step 2: テストを実行し失敗を確認する**

Run: `cd app && uv run pytest tests/test_stock_price_api.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'data_api.stock_price_api'`）

- [ ] **Step 3: 実装する**

Create `app/data_api/stock_price_api.py`:
```python
import yfinance as yf


def fetch_price_history(ticker_symbol: str, period: str = "1mo"):
    ticker = yf.Ticker(ticker_symbol)
    return ticker.history(period=period)


def fetch_fundamentals(ticker_symbol: str) -> dict:
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info
    return {
        "ticker": ticker_symbol,
        "name": info.get("longName"),
        "trailing_pe": info.get("trailingPE"),
        "price_to_book": info.get("priceToBook"),
        "dividend_yield": info.get("dividendYield"),
        "market_cap": info.get("marketCap"),
    }


def fetch_news(ticker_symbol: str, limit: int = 5) -> list[dict]:
    ticker = yf.Ticker(ticker_symbol)
    news_items = ticker.news or []
    return [
        {"title": item.get("title"), "publisher": item.get("publisher")}
        for item in news_items[:limit]
    ]
```

- [ ] **Step 4: テストを実行し成功を確認する**

Run: `cd app && uv run pytest tests/test_stock_price_api.py -v`
Expected: `4 passed`

- [ ] **Step 5: コミットする**

```bash
git add app/data_api/stock_price_api.py app/tests/test_stock_price_api.py
git commit -m "feat: fetch price history, fundamentals, and news via yfinance"
```

---

### Task 6: `data_api/stock_price_api.py` 拡張 — `fetch_universe_fundamentals`（キャッシュ付き一括取得）

**Files:**
- Modify: `app/data_api/stock_price_api.py`
- Modify: `app/tests/test_stock_price_api.py`

**Interfaces:**
- Consumes: `common.cache.read_cache`, `common.cache.write_cache`（Task 3）, `fetch_fundamentals`（本ファイル、Task 5）
- Produces: `fetch_universe_fundamentals(tickers: list[str], cache_dir: Path, fetch_fundamentals=fetch_fundamentals) -> pd.DataFrame`（列: `ticker`, `name`, `per`, `pbr`, `dividend_yield_pct`, `market_cap`。`dividend_yield_pct` は `dividend_yield * 100` で百分率化したもの）。`screening` タブが利用する。

- [ ] **Step 1: 失敗するテストを書く**

`app/tests/test_stock_price_api.py` の末尾に追記する。
```python
def test_fetch_universe_fundamentals_uses_cache_on_second_call(tmp_path):
    call_count = {"n": 0}

    def fake_fetch_fundamentals(ticker_symbol):
        call_count["n"] += 1
        return {
            "ticker": ticker_symbol,
            "name": ticker_symbol,
            "trailing_pe": 10.0,
            "price_to_book": 1.0,
            "dividend_yield": 0.02,
            "market_cap": 1,
        }

    tickers = ["AAA.T", "BBB.T"]
    df1 = stock_price_api.fetch_universe_fundamentals(
        tickers, tmp_path, fetch_fundamentals=fake_fetch_fundamentals
    )
    assert call_count["n"] == 2
    assert df1["dividend_yield_pct"].tolist() == [2.0, 2.0]

    df2 = stock_price_api.fetch_universe_fundamentals(
        tickers, tmp_path, fetch_fundamentals=fake_fetch_fundamentals
    )
    assert call_count["n"] == 2
    assert df1["ticker"].tolist() == df2["ticker"].tolist()
```

- [ ] **Step 2: テストを実行し失敗を確認する**

Run: `cd app && uv run pytest tests/test_stock_price_api.py -v`
Expected: FAIL（`AttributeError: module 'data_api.stock_price_api' has no attribute 'fetch_universe_fundamentals'`）

- [ ] **Step 3: 実装する**

`app/data_api/stock_price_api.py` の先頭に以下のimportを追加する。
```python
import hashlib
import json
from pathlib import Path

import pandas as pd
import yfinance as yf

from common.cache import read_cache, write_cache
```

ファイル末尾に以下を追加する。
```python
def fetch_universe_fundamentals(
    tickers: list[str],
    cache_dir: Path,
    fetch_fundamentals=fetch_fundamentals,
) -> pd.DataFrame:
    cache_key = "universe-" + hashlib.sha256(
        "-".join(sorted(tickers)).encode("utf-8")
    ).hexdigest()[:12]
    cached = read_cache(cache_dir, cache_key)
    if cached is not None:
        return pd.DataFrame(json.loads(cached))

    rows = []
    for ticker_symbol in tickers:
        data = fetch_fundamentals(ticker_symbol)
        dividend_yield = data.get("dividend_yield")
        rows.append(
            {
                "ticker": data.get("ticker", ticker_symbol),
                "name": data.get("name"),
                "per": data.get("trailing_pe"),
                "pbr": data.get("price_to_book"),
                "dividend_yield_pct": dividend_yield * 100 if dividend_yield is not None else None,
                "market_cap": data.get("market_cap"),
            }
        )
    df = pd.DataFrame(rows)
    write_cache(cache_dir, cache_key, df.to_json(orient="records", force_ascii=False))
    return df
```

- [ ] **Step 4: テストを実行し成功を確認する**

Run: `cd app && uv run pytest tests/test_stock_price_api.py -v`
Expected: `5 passed`

- [ ] **Step 5: コミットする**

```bash
git add app/data_api/stock_price_api.py app/tests/test_stock_price_api.py
git commit -m "feat: batch-fetch universe fundamentals with daily cache"
```

---

### Task 7: `portfolio_management/storage.py` — 保有銘柄の永続化

**Files:**
- Create: `app/portfolio_management/storage.py`
- Test: `app/tests/test_storage.py`

**Interfaces:**
- Produces: `load_holdings(path: Path) -> list[dict]`, `save_holdings(path: Path, holdings: list[dict]) -> None`。保有銘柄は `{"ticker": str, "shares": int, "cost": float}` のリスト。

- [ ] **Step 1: 失敗するテストを書く**

Create `app/tests/test_storage.py`:
```python
from portfolio_management.storage import load_holdings, save_holdings


def test_load_holdings_missing_file_returns_empty_list(tmp_path):
    path = tmp_path / "holdings.json"
    assert load_holdings(path) == []


def test_save_then_load_holdings_roundtrip(tmp_path):
    path = tmp_path / "holdings.json"
    holdings = [{"ticker": "7203.T", "shares": 100, "cost": 2500.0}]
    save_holdings(path, holdings)
    assert load_holdings(path) == holdings


def test_load_holdings_corrupted_file_returns_empty_list(tmp_path):
    path = tmp_path / "holdings.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert load_holdings(path) == []
```

- [ ] **Step 2: テストを実行し失敗を確認する**

Run: `cd app && uv run pytest tests/test_storage.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'portfolio_management.storage'`）

- [ ] **Step 3: 実装する**

Create `app/portfolio_management/storage.py`:
```python
import json
from pathlib import Path


def load_holdings(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return data


def save_holdings(path: Path, holdings: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(holdings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
```

- [ ] **Step 4: テストを実行し成功を確認する**

Run: `cd app && uv run pytest tests/test_storage.py -v`
Expected: `3 passed`

- [ ] **Step 5: コミットする**

```bash
git add app/portfolio_management/storage.py app/tests/test_storage.py
git commit -m "feat: persist portfolio holdings to local JSON"
```

---

### Task 8: `portfolio_management/composition.py` — 構成比・損益の計算

**Files:**
- Create: `app/portfolio_management/composition.py`
- Test: `app/tests/test_composition.py`

**Interfaces:**
- Produces: `analyze_portfolio_composition(holdings: list[dict], current_prices: dict[str, float]) -> dict`（`{"holdings": [{"ticker", "shares", "cost", "current_price", "value", "pnl", "pnl_pct", "weight_pct"}, ...], "total_value": float}`）

- [ ] **Step 1: 失敗するテストを書く**

Create `app/tests/test_composition.py`:
```python
from portfolio_management.composition import analyze_portfolio_composition


def test_analyze_portfolio_composition_computes_weight_and_pnl():
    holdings = [
        {"ticker": "AAA", "shares": 100, "cost": 1000.0},
        {"ticker": "BBB", "shares": 50, "cost": 2000.0},
    ]
    current_prices = {"AAA": 1100.0, "BBB": 1900.0}

    result = analyze_portfolio_composition(holdings, current_prices)

    aaa = next(r for r in result["holdings"] if r["ticker"] == "AAA")
    bbb = next(r for r in result["holdings"] if r["ticker"] == "BBB")
    assert aaa["value"] == 110000.0
    assert bbb["value"] == 95000.0
    assert result["total_value"] == 205000.0
    assert aaa["pnl"] == 10000.0
    assert bbb["pnl"] == -5000.0
    assert round(aaa["weight_pct"], 1) == round(110000 / 205000 * 100, 1)


def test_analyze_portfolio_composition_handles_missing_price():
    holdings = [{"ticker": "CCC", "shares": 10, "cost": 500.0}]
    result = analyze_portfolio_composition(holdings, {})
    ccc = result["holdings"][0]
    assert ccc["current_price"] is None
    assert ccc["value"] is None
    assert ccc["pnl"] is None
    assert ccc["weight_pct"] is None
```

- [ ] **Step 2: テストを実行し失敗を確認する**

Run: `cd app && uv run pytest tests/test_composition.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'portfolio_management.composition'`）

- [ ] **Step 3: 実装する**

Create `app/portfolio_management/composition.py`:
```python
def analyze_portfolio_composition(
    holdings: list[dict], current_prices: dict[str, float]
) -> dict:
    rows = []
    total_value = 0.0
    for holding in holdings:
        ticker = holding["ticker"]
        shares = holding["shares"]
        cost = holding["cost"]
        price = current_prices.get(ticker)

        value = price * shares if price is not None else None
        pnl = (price - cost) * shares if price is not None else None
        pnl_pct = (
            (price - cost) / cost * 100 if price is not None and cost else None
        )

        rows.append(
            {
                "ticker": ticker,
                "shares": shares,
                "cost": cost,
                "current_price": price,
                "value": value,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
            }
        )
        if value is not None:
            total_value += value

    for row in rows:
        if row["value"] is not None and total_value:
            row["weight_pct"] = round(row["value"] / total_value * 100, 2)
        else:
            row["weight_pct"] = None

    return {"holdings": rows, "total_value": total_value}
```

- [ ] **Step 4: テストを実行し成功を確認する**

Run: `cd app && uv run pytest tests/test_composition.py -v`
Expected: `2 passed`

- [ ] **Step 5: コミットする**

```bash
git add app/portfolio_management/composition.py app/tests/test_composition.py
git commit -m "feat: compute portfolio composition and pnl"
```

---

### Task 9: `portfolio_management/risk.py` — ボラティリティ・相関の計算

**Files:**
- Create: `app/portfolio_management/risk.py`
- Test: `app/tests/test_risk.py`

**Interfaces:**
- Produces: `assess_risk(price_histories: dict[str, pd.Series]) -> dict`（`{"volatility_pct": {ticker: float}, "correlation": {ticker: {ticker: float}}, "portfolio_volatility_pct": float | None}`）

- [ ] **Step 1: 失敗するテストを書く**

Create `app/tests/test_risk.py`:
```python
import pandas as pd

from portfolio_management.risk import assess_risk


def test_assess_risk_identical_series_have_correlation_one():
    dates = pd.date_range("2026-01-01", periods=10, freq="D")
    series_a = pd.Series(
        [100, 101, 102, 101, 103, 104, 103, 105, 106, 107], index=dates
    )
    series_b = series_a.copy()

    result = assess_risk({"AAA": series_a, "BBB": series_b})

    assert result["correlation"]["AAA"]["BBB"] == 1.0


def test_assess_risk_returns_volatility_for_each_ticker():
    dates = pd.date_range("2026-01-01", periods=10, freq="D")
    series_a = pd.Series(
        [100, 101, 102, 101, 103, 104, 103, 105, 106, 107], index=dates
    )

    result = assess_risk({"AAA": series_a})

    assert "AAA" in result["volatility_pct"]
    assert result["volatility_pct"]["AAA"] > 0
```

- [ ] **Step 2: テストを実行し失敗を確認する**

Run: `cd app && uv run pytest tests/test_risk.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'portfolio_management.risk'`）

- [ ] **Step 3: 実装する**

Create `app/portfolio_management/risk.py`:
```python
import pandas as pd


def assess_risk(price_histories: dict[str, pd.Series]) -> dict:
    returns = pd.DataFrame(
        {ticker: series.pct_change().dropna() for ticker, series in price_histories.items()}
    )

    volatility_pct = (returns.std() * (252**0.5) * 100).round(2).to_dict()
    correlation = returns.corr().round(2).to_dict()

    portfolio_volatility_pct = None
    if len(returns.columns) > 0:
        portfolio_volatility_pct = round(
            returns.mean(axis=1).std() * (252**0.5) * 100, 2
        )

    return {
        "volatility_pct": volatility_pct,
        "correlation": correlation,
        "portfolio_volatility_pct": portfolio_volatility_pct,
    }
```

- [ ] **Step 4: テストを実行し成功を確認する**

Run: `cd app && uv run pytest tests/test_risk.py -v`
Expected: `2 passed`

- [ ] **Step 5: コミットする**

```bash
git add app/portfolio_management/risk.py app/tests/test_risk.py
git commit -m "feat: compute portfolio volatility and correlation"
```

---

### Task 10: `analysis_agents/fundamental_agent.py` — ファンダメンタル分析エージェント

**Files:**
- Create: `app/analysis_agents/fundamental_agent.py`
- Test: `app/tests/test_fundamental_agent.py`

**Interfaces:**
- Consumes: `data_api.stock_price_api.fetch_fundamentals`（Task 5、デフォルト引数として注入）
- Produces: `analyze_fundamentals(ticker_symbol: str, fetch_fundamentals=default_fetch_fundamentals) -> dict`（`{"ticker", "per", "pbr", "dividend_yield"}`）

- [ ] **Step 1: 失敗するテストを書く**

Create `app/tests/test_fundamental_agent.py`:
```python
from analysis_agents.fundamental_agent import analyze_fundamentals


def test_analyze_fundamentals_maps_fields_from_fetch_result():
    fake_fetch = lambda ticker: {
        "ticker": ticker,
        "trailing_pe": 12.3,
        "price_to_book": 1.1,
        "dividend_yield": 0.02,
    }

    result = analyze_fundamentals("7203.T", fetch_fundamentals=fake_fetch)

    assert result == {"ticker": "7203.T", "per": 12.3, "pbr": 1.1, "dividend_yield": 0.02}
```

- [ ] **Step 2: テストを実行し失敗を確認する**

Run: `cd app && uv run pytest tests/test_fundamental_agent.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'analysis_agents.fundamental_agent'`）

- [ ] **Step 3: 実装する**

Create `app/analysis_agents/fundamental_agent.py`:
```python
from data_api.stock_price_api import fetch_fundamentals as default_fetch_fundamentals


def analyze_fundamentals(
    ticker_symbol: str, fetch_fundamentals=default_fetch_fundamentals
) -> dict:
    data = fetch_fundamentals(ticker_symbol)
    return {
        "ticker": ticker_symbol,
        "per": data.get("trailing_pe"),
        "pbr": data.get("price_to_book"),
        "dividend_yield": data.get("dividend_yield"),
    }
```

- [ ] **Step 4: テストを実行し成功を確認する**

Run: `cd app && uv run pytest tests/test_fundamental_agent.py -v`
Expected: `1 passed`

- [ ] **Step 5: コミットする**

```bash
git add app/analysis_agents/fundamental_agent.py app/tests/test_fundamental_agent.py
git commit -m "feat: add fundamental analysis agent"
```

---

### Task 11: `analysis_agents/technical_agent.py` — テクニカル分析エージェント

**Files:**
- Create: `app/analysis_agents/technical_agent.py`
- Test: `app/tests/test_technical_agent.py`

**Interfaces:**
- Produces: `analyze_technical(price_history: pd.DataFrame, short_window: int = 25, long_window: int = 75) -> dict`（`{"ma_short", "ma_long", "signal"}`。`signal` は `"強気" | "弱気" | "中立" | "データ不足"`）

- [ ] **Step 1: 失敗するテストを書く**

Create `app/tests/test_technical_agent.py`:
```python
import pandas as pd

from analysis_agents.technical_agent import analyze_technical


def test_analyze_technical_signals_bullish_on_uptrend():
    prices = pd.DataFrame({"Close": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109]})
    result = analyze_technical(prices, short_window=2, long_window=5)
    assert result["signal"] == "強気"


def test_analyze_technical_returns_insufficient_data_when_too_short():
    prices = pd.DataFrame({"Close": [100, 101]})
    result = analyze_technical(prices, short_window=2, long_window=5)
    assert result["signal"] == "データ不足"
    assert result["ma_short"] is None
    assert result["ma_long"] is None
```

- [ ] **Step 2: テストを実行し失敗を確認する**

Run: `cd app && uv run pytest tests/test_technical_agent.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'analysis_agents.technical_agent'`）

- [ ] **Step 3: 実装する**

Create `app/analysis_agents/technical_agent.py`:
```python
import pandas as pd


def analyze_technical(
    price_history: pd.DataFrame, short_window: int = 25, long_window: int = 75
) -> dict:
    close = price_history["Close"]
    if len(close) < long_window:
        return {"ma_short": None, "ma_long": None, "signal": "データ不足"}

    ma_short = close.rolling(window=short_window).mean().iloc[-1]
    ma_long = close.rolling(window=long_window).mean().iloc[-1]

    if ma_short > ma_long:
        signal = "強気"
    elif ma_short < ma_long:
        signal = "弱気"
    else:
        signal = "中立"

    return {"ma_short": round(ma_short, 2), "ma_long": round(ma_long, 2), "signal": signal}
```

- [ ] **Step 4: テストを実行し成功を確認する**

Run: `cd app && uv run pytest tests/test_technical_agent.py -v`
Expected: `2 passed`

- [ ] **Step 5: コミットする**

```bash
git add app/analysis_agents/technical_agent.py app/tests/test_technical_agent.py
git commit -m "feat: add technical analysis agent using moving averages"
```

---

### Task 12: `analysis_agents/news_research_agent.py` — ニュースセンチメント（バッチ）

**Files:**
- Create: `app/analysis_agents/news_research_agent.py`
- Test: `app/tests/test_news_research_agent.py`

**Interfaces:**
- Consumes: `data_api.llm_client.call_llm`（Task 4、デフォルト引数として注入）
- Produces: `build_news_sentiment_prompt(news_by_ticker: dict[str, list[dict]]) -> str`, `research_news_batch(news_by_ticker: dict[str, list[dict]], call_llm=default_call_llm) -> dict[str, dict]`（各値は `{"sentiment": str | None, "confidence": float | None}`）

- [ ] **Step 1: 失敗するテストを書く**

Create `app/tests/test_news_research_agent.py`:
```python
from analysis_agents.news_research_agent import (
    build_news_sentiment_prompt,
    research_news_batch,
)


def test_build_news_sentiment_prompt_includes_ticker_and_titles():
    news_by_ticker = {"AAA.T": [{"title": "好決算", "publisher": "X"}]}
    prompt = build_news_sentiment_prompt(news_by_ticker)
    assert "AAA.T" in prompt
    assert "好決算" in prompt


def test_research_news_batch_parses_json_response():
    news_by_ticker = {"AAA.T": [{"title": "好決算", "publisher": "X"}]}
    fake_call_llm = lambda prompt: (
        '{"AAA.T": {"sentiment": "ポジティブ", "confidence": 0.7}}'
    )
    result = research_news_batch(news_by_ticker, call_llm=fake_call_llm)
    assert result["AAA.T"]["sentiment"] == "ポジティブ"
    assert result["AAA.T"]["confidence"] == 0.7


def test_research_news_batch_fallback_on_invalid_json():
    news_by_ticker = {"AAA.T": []}
    result = research_news_batch(news_by_ticker, call_llm=lambda prompt: "not json")
    assert result["AAA.T"]["sentiment"] is None
    assert result["AAA.T"]["confidence"] is None
```

- [ ] **Step 2: テストを実行し失敗を確認する**

Run: `cd app && uv run pytest tests/test_news_research_agent.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'analysis_agents.news_research_agent'`）

- [ ] **Step 3: 実装する**

Create `app/analysis_agents/news_research_agent.py`:
```python
import json

from data_api.llm_client import call_llm as default_call_llm


def build_news_sentiment_prompt(news_by_ticker: dict[str, list[dict]]) -> str:
    lines = [
        "以下は銘柄ごとの直近ニュース見出しです。",
        "各銘柄のニュースセンチメントを判定してください。",
        "出力は次の形式のJSONのみとしてください（説明文・コードブロック記法は不要です）。",
        '{"<ticker>": {"sentiment": "ポジティブ|ニュートラル|ネガティブ", "confidence": 0.0〜1.0}}',
        "",
    ]
    for ticker, items in news_by_ticker.items():
        titles = "\n".join(f"- {item['title']}" for item in items) or "- (ニュースなし)"
        lines.append(f"## {ticker}\n{titles}\n")
    return "\n".join(lines)


def research_news_batch(
    news_by_ticker: dict[str, list[dict]], call_llm=default_call_llm
) -> dict[str, dict]:
    prompt = build_news_sentiment_prompt(news_by_ticker)
    raw = call_llm(prompt)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {}

    return {
        ticker: result.get(ticker, {"sentiment": None, "confidence": None})
        for ticker in news_by_ticker
    }
```

- [ ] **Step 4: テストを実行し成功を確認する**

Run: `cd app && uv run pytest tests/test_news_research_agent.py -v`
Expected: `3 passed`

- [ ] **Step 5: コミットする**

```bash
git add app/analysis_agents/news_research_agent.py app/tests/test_news_research_agent.py
git commit -m "feat: batch news sentiment analysis via single LLM call"
```

---

### Task 13: `prompt_patterns/report_generation.py` — レポート生成プロンプト

**Files:**
- Create: `app/prompt_patterns/report_generation.py`
- Test: `app/tests/test_report_generation.py`

**Interfaces:**
- Consumes: `common.disclaimer.DISCLAIMER_NOTICE`（Task 2）
- Produces: `build_report_prompt(facts: dict) -> str`

- [ ] **Step 1: 失敗するテストを書く**

Create `app/tests/test_report_generation.py`:
```python
from common.disclaimer import DISCLAIMER_NOTICE
from prompt_patterns.report_generation import build_report_prompt


def test_build_report_prompt_includes_facts_and_disclaimer():
    facts = {"composition": {"total_value": 100000}}
    prompt = build_report_prompt(facts)
    assert "100000" in prompt
    assert DISCLAIMER_NOTICE in prompt
    assert "売買の推奨" in prompt
```

- [ ] **Step 2: テストを実行し失敗を確認する**

Run: `cd app && uv run pytest tests/test_report_generation.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'prompt_patterns.report_generation'`）

- [ ] **Step 3: 実装する**

Create `app/prompt_patterns/report_generation.py`:
```python
import json

from common.disclaimer import DISCLAIMER_NOTICE


def build_report_prompt(facts: dict) -> str:
    facts_json = json.dumps(facts, ensure_ascii=False, indent=2, default=str)
    return (
        "以下はポートフォリオの事実データ（Python側で計算済み）です。\n\n"
        f"{facts_json}\n\n"
        "このデータを見て、教育的な観察事項（例: 集中度が高い銘柄、"
        "ニュースセンチメントが弱い銘柄、テクニカルシグナルが弱含みの銘柄）を"
        "箇条書きで示してください。\n"
        "売買の推奨・指示・目標株価の提示は行わないでください。\n\n"
        f"{DISCLAIMER_NOTICE}"
    )
```

- [ ] **Step 4: テストを実行し成功を確認する**

Run: `cd app && uv run pytest tests/test_report_generation.py -v`
Expected: `1 passed`

- [ ] **Step 5: コミットする**

```bash
git add app/prompt_patterns/report_generation.py app/tests/test_report_generation.py
git commit -m "feat: add report generation prompt with fact/commentary separation"
```

---

### Task 14: `portfolio_management/review.py` — ポートフォリオレビューの統合

**Files:**
- Create: `app/portfolio_management/review.py`
- Test: `app/tests/test_review.py`

**Interfaces:**
- Consumes: `portfolio_management.composition.analyze_portfolio_composition`（Task 8）, `portfolio_management.risk.assess_risk`（Task 9）, `prompt_patterns.report_generation.build_report_prompt`（Task 13）, `common.disclaimer.DISCLAIMER_NOTICE`（Task 2）, `data_api.llm_client.call_llm`（Task 4、デフォルト引数）
- Produces: `build_holding_snapshot(holding: dict, fundamentals: dict, technical: dict, news_sentiment: dict) -> dict`, `generate_portfolio_review(holdings, current_prices, price_histories, fundamentals_by_ticker, technicals_by_ticker, news_sentiment_by_ticker, call_llm=default_call_llm) -> str`

- [ ] **Step 1: 失敗するテストを書く**

Create `app/tests/test_review.py`:
```python
import pandas as pd

from common.disclaimer import DISCLAIMER_NOTICE
from portfolio_management.review import build_holding_snapshot, generate_portfolio_review


def test_build_holding_snapshot_combines_all_sources():
    holding = {"ticker": "AAA.T", "shares": 100, "cost": 1000.0}
    fundamentals = {"per": 12.0, "pbr": 1.1}
    technical = {"signal": "強気"}
    news_sentiment = {"sentiment": "ポジティブ", "confidence": 0.7}

    snapshot = build_holding_snapshot(holding, fundamentals, technical, news_sentiment)

    assert snapshot == {
        "ticker": "AAA.T",
        "shares": 100,
        "cost": 1000.0,
        "per": 12.0,
        "pbr": 1.1,
        "technical_signal": "強気",
        "news_sentiment": "ポジティブ",
        "news_confidence": 0.7,
    }


def test_generate_portfolio_review_includes_disclaimer_and_commentary():
    holdings = [{"ticker": "AAA.T", "shares": 100, "cost": 1000.0}]
    current_prices = {"AAA.T": 1100.0}
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    price_histories = {"AAA.T": pd.Series([100, 101, 102, 103, 104], index=dates)}
    fundamentals_by_ticker = {"AAA.T": {"per": 12.0, "pbr": 1.1}}
    technicals_by_ticker = {"AAA.T": {"signal": "強気"}}
    news_sentiment_by_ticker = {"AAA.T": {"sentiment": "ポジティブ", "confidence": 0.7}}

    fake_call_llm = lambda prompt: "テスト用の考察文です。"

    report = generate_portfolio_review(
        holdings,
        current_prices,
        price_histories,
        fundamentals_by_ticker,
        technicals_by_ticker,
        news_sentiment_by_ticker,
        call_llm=fake_call_llm,
    )

    assert report.count(DISCLAIMER_NOTICE) == 2
    assert "テスト用の考察文です。" in report
```

- [ ] **Step 2: テストを実行し失敗を確認する**

Run: `cd app && uv run pytest tests/test_review.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'portfolio_management.review'`）

- [ ] **Step 3: 実装する**

Create `app/portfolio_management/review.py`:
```python
from common.disclaimer import DISCLAIMER_NOTICE
from data_api.llm_client import call_llm as default_call_llm
from portfolio_management.composition import analyze_portfolio_composition
from portfolio_management.risk import assess_risk
from prompt_patterns.report_generation import build_report_prompt


def build_holding_snapshot(
    holding: dict, fundamentals: dict, technical: dict, news_sentiment: dict
) -> dict:
    return {
        "ticker": holding["ticker"],
        "shares": holding["shares"],
        "cost": holding["cost"],
        "per": fundamentals.get("per"),
        "pbr": fundamentals.get("pbr"),
        "technical_signal": technical.get("signal"),
        "news_sentiment": news_sentiment.get("sentiment"),
        "news_confidence": news_sentiment.get("confidence"),
    }


def generate_portfolio_review(
    holdings: list[dict],
    current_prices: dict[str, float],
    price_histories: dict,
    fundamentals_by_ticker: dict[str, dict],
    technicals_by_ticker: dict[str, dict],
    news_sentiment_by_ticker: dict[str, dict],
    call_llm=default_call_llm,
) -> str:
    composition = analyze_portfolio_composition(holdings, current_prices)
    risk = assess_risk(price_histories)
    snapshots = [
        build_holding_snapshot(
            holding,
            fundamentals_by_ticker.get(holding["ticker"], {}),
            technicals_by_ticker.get(holding["ticker"], {}),
            news_sentiment_by_ticker.get(holding["ticker"], {}),
        )
        for holding in holdings
    ]

    facts = {"composition": composition, "risk": risk, "holdings": snapshots}
    prompt = build_report_prompt(facts)
    commentary = call_llm(prompt)

    sections = [
        DISCLAIMER_NOTICE,
        "",
        "# ポートフォリオ統合レビュー",
        "",
        commentary,
        "",
        "---",
        "",
        DISCLAIMER_NOTICE,
    ]
    return "\n".join(sections)
```

- [ ] **Step 4: テストを実行し成功を確認する**

Run: `cd app && uv run pytest tests/test_review.py -v`
Expected: `2 passed`

- [ ] **Step 5: コミットする**

```bash
git add app/portfolio_management/review.py app/tests/test_review.py
git commit -m "feat: integrate composition, risk, and agents into portfolio review"
```

---

### Task 15: `prompt_patterns/screening.py` — スクリーニング条件変換・フィルタ適用・コメント生成

**Files:**
- Create: `app/prompt_patterns/screening.py`
- Test: `app/tests/test_screening.py`

**Interfaces:**
- Consumes: `data_api.llm_client.call_llm`（Task 4、デフォルト引数）
- Produces: `build_screening_prompt(condition_text: str) -> str`, `apply_filters(df: pd.DataFrame, filters: list[dict]) -> pd.DataFrame`, `build_comment_prompt(result_df: pd.DataFrame) -> str`, `generate_screening_comments(result_df: pd.DataFrame, call_llm=default_call_llm) -> dict[str, str]`

- [ ] **Step 1: 失敗するテストを書く**

Create `app/tests/test_screening.py`:
```python
import pandas as pd

from prompt_patterns.screening import apply_filters, generate_screening_comments


def test_apply_filters_filters_rows_matching_all_conditions():
    df = pd.DataFrame(
        [
            {"ticker": "AAA", "per": 12.0, "pbr": 1.0, "dividend_yield_pct": 3.5},
            {"ticker": "BBB", "per": 20.0, "pbr": 2.0, "dividend_yield_pct": 1.0},
        ]
    )
    filters = [
        {"field": "per", "operator": "<=", "value": 15},
        {"field": "dividend_yield_pct", "operator": ">=", "value": 3},
    ]
    result = apply_filters(df, filters)
    assert result["ticker"].tolist() == ["AAA"]


def test_apply_filters_ignores_unknown_field():
    df = pd.DataFrame([{"ticker": "AAA", "per": 12.0}])
    filters = [{"field": "unknown_field", "operator": "<=", "value": 5}]
    result = apply_filters(df, filters)
    assert result["ticker"].tolist() == ["AAA"]


def test_apply_filters_excludes_missing_values():
    df = pd.DataFrame([{"ticker": "AAA", "per": None}])
    filters = [{"field": "per", "operator": "<=", "value": 15}]
    result = apply_filters(df, filters)
    assert result.empty


def test_generate_screening_comments_parses_json_response():
    df = pd.DataFrame([{"ticker": "AAA", "per": 12.0, "dividend_yield_pct": 3.5}])
    fake_call_llm = lambda prompt: '{"AAA": "割安感があります。"}'
    result = generate_screening_comments(df, call_llm=fake_call_llm)
    assert result == {"AAA": "割安感があります。"}


def test_generate_screening_comments_returns_empty_for_empty_df():
    df = pd.DataFrame(columns=["ticker", "per", "dividend_yield_pct"])
    result = generate_screening_comments(df, call_llm=lambda prompt: "{}")
    assert result == {}


def test_generate_screening_comments_fallback_on_invalid_json():
    df = pd.DataFrame([{"ticker": "AAA", "per": 12.0, "dividend_yield_pct": 3.5}])
    result = generate_screening_comments(df, call_llm=lambda prompt: "not json")
    assert result == {"AAA": "コメント生成失敗"}
```

- [ ] **Step 2: テストを実行し失敗を確認する**

Run: `cd app && uv run pytest tests/test_screening.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'prompt_patterns.screening'`）

- [ ] **Step 3: 実装する**

Create `app/prompt_patterns/screening.py`:
```python
import json
import operator

import pandas as pd

from data_api.llm_client import call_llm as default_call_llm

_OPERATORS = {
    "<=": operator.le,
    ">=": operator.ge,
    "<": operator.lt,
    ">": operator.gt,
    "==": operator.eq,
}


def build_screening_prompt(condition_text: str) -> str:
    return (
        "次の投資条件をJSON形式のフィルタ配列に変換してください。\n"
        "使用できるfieldは per（PER）、pbr（PBR）、dividend_yield_pct"
        "（配当利回り、単位はパーセントの数値。例: 3%なら3）のいずれかです。\n"
        '出力形式: [{"field": "per", "operator": "<=", "value": 15}] の'
        "ようなJSON配列のみを出力してください。説明文やコードブロック記法は不要です。\n\n"
        f"条件: {condition_text}"
    )


def apply_filters(df: pd.DataFrame, filters: list[dict]) -> pd.DataFrame:
    result = df
    for condition in filters:
        field = condition.get("field")
        op_symbol = condition.get("operator")
        value = condition.get("value")
        if field not in result.columns or op_symbol not in _OPERATORS:
            continue
        op_func = _OPERATORS[op_symbol]
        mask = result[field].notna() & op_func(result[field], value)
        result = result[mask]
    return result


def build_comment_prompt(result_df: pd.DataFrame) -> str:
    rows = result_df[["ticker", "per", "dividend_yield_pct"]].to_dict(orient="records")
    rows_json = json.dumps(rows, ensure_ascii=False)
    return (
        "以下の銘柄データを見て、銘柄ごとに投資家向けの一言コメントを"
        "日本語で1文ずつ作成してください。断定的な売買判断は含めないでください。\n"
        '出力形式: {"<ticker>": "<コメント>"} というJSONのみを出力してください。\n\n'
        f"{rows_json}"
    )


def generate_screening_comments(
    result_df: pd.DataFrame, call_llm=default_call_llm
) -> dict[str, str]:
    if result_df.empty:
        return {}

    prompt = build_comment_prompt(result_df)
    raw = call_llm(prompt)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {ticker: "コメント生成失敗" for ticker in result_df["ticker"]}
```

- [ ] **Step 4: テストを実行し成功を確認する**

Run: `cd app && uv run pytest tests/test_screening.py -v`
Expected: `6 passed`

- [ ] **Step 5: コミットする**

```bash
git add app/prompt_patterns/screening.py app/tests/test_screening.py
git commit -m "feat: add screening prompt, filter application, and batch comments"
```

---

### Task 16: `screening/universe.py` — 固定スクリーニングユニバース

**Files:**
- Create: `app/screening/universe.py`
- Test: `app/tests/test_universe.py`

**Interfaces:**
- Produces: `UNIVERSE: list[str]`（日経225構成銘柄のうち時価総額上位・セクター分散を考慮した44銘柄）

- [ ] **Step 1: 失敗するテストを書く**

Create `app/tests/test_universe.py`:
```python
from screening.universe import UNIVERSE


def test_universe_size_within_expected_range():
    assert 40 <= len(UNIVERSE) <= 50


def test_universe_tickers_are_unique():
    assert len(UNIVERSE) == len(set(UNIVERSE))


def test_universe_tickers_use_tokyo_exchange_suffix():
    assert all(ticker.endswith(".T") for ticker in UNIVERSE)
```

- [ ] **Step 2: テストを実行し失敗を確認する**

Run: `cd app && uv run pytest tests/test_universe.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'screening.universe'`）

- [ ] **Step 3: 実装する**

Create `app/screening/universe.py`:
```python
UNIVERSE: list[str] = [
    "7203.T",  # トヨタ自動車
    "7267.T",  # ホンダ
    "7201.T",  # 日産自動車
    "6758.T",  # ソニーグループ
    "6861.T",  # キーエンス
    "6501.T",  # 日立製作所
    "6503.T",  # 三菱電機
    "6752.T",  # パナソニックHD
    "6902.T",  # デンソー
    "6971.T",  # 京セラ
    "8035.T",  # 東京エレクトロン
    "6273.T",  # SMC
    "9432.T",  # NTT
    "9433.T",  # KDDI
    "9434.T",  # ソフトバンク
    "9984.T",  # ソフトバンクグループ
    "8306.T",  # 三菱UFJフィナンシャル・グループ
    "8316.T",  # 三井住友フィナンシャルグループ
    "8411.T",  # みずほフィナンシャルグループ
    "8766.T",  # 東京海上HD
    "8058.T",  # 三菱商事
    "8031.T",  # 三井物産
    "8001.T",  # 伊藤忠商事
    "2914.T",  # JT
    "4502.T",  # 武田薬品工業
    "4519.T",  # 中外製薬
    "4568.T",  # 第一三共
    "3382.T",  # セブン&アイ・ホールディングス
    "9843.T",  # ニトリHD
    "8267.T",  # イオン
    "4901.T",  # 富士フイルムHD
    "7751.T",  # キヤノン
    "7011.T",  # 三菱重工業
    "6301.T",  # コマツ
    "5108.T",  # ブリヂストン
    "4063.T",  # 信越化学工業
    "6367.T",  # ダイキン工業
    "9020.T",  # JR東日本
    "9022.T",  # JR東海
    "9101.T",  # 日本郵船
    "8801.T",  # 三井不動産
    "8802.T",  # 三菱地所
    "6098.T",  # リクルートHD
    "4661.T",  # オリエンタルランド
]
```

- [ ] **Step 4: テストを実行し成功を確認する**

Run: `cd app && uv run pytest tests/test_universe.py -v`
Expected: `3 passed`

- [ ] **Step 5: コミットする**

```bash
git add app/screening/universe.py app/tests/test_universe.py
git commit -m "feat: define fixed screening universe of major Tokyo-listed stocks"
```

---

### Task 17: `app.py` — Streamlitエントリーポイント（ポートフォリオタブ）

**Files:**
- Create: `app/app.py`

**Interfaces:**
- Consumes: `common.cache.{read_cache,write_cache}`（Task 3）, `common.disclaimer.DISCLAIMER_NOTICE`（Task 2）, `data_api.llm_client.{call_llm,check_claude_cli_available}`（Task 4）, `data_api.stock_price_api.{fetch_fundamentals,fetch_news,fetch_price_history}`（Task 5）, `analysis_agents.fundamental_agent.analyze_fundamentals`（Task 10）, `analysis_agents.technical_agent.analyze_technical`（Task 11）, `analysis_agents.news_research_agent.research_news_batch`（Task 12）, `portfolio_management.storage.{load_holdings,save_holdings}`（Task 7）, `portfolio_management.review.generate_portfolio_review`（Task 14）

このタスクはStreamlit UIのため自動テストは書かない（spec通り手動確認とする）。「テスト」はステップ2の手動起動確認に置き換える。

- [ ] **Step 1: `app.py` を実装する**

Create `app/app.py`:
```python
from pathlib import Path

import pandas as pd
import streamlit as st

from analysis_agents.fundamental_agent import analyze_fundamentals
from analysis_agents.news_research_agent import research_news_batch
from analysis_agents.technical_agent import analyze_technical
from common.cache import read_cache, write_cache
from common.disclaimer import DISCLAIMER_NOTICE
from data_api.llm_client import call_llm, check_claude_cli_available
from data_api.stock_price_api import fetch_news, fetch_price_history
from portfolio_management.review import generate_portfolio_review
from portfolio_management.storage import load_holdings, save_holdings

DATA_DIR = Path(__file__).parent / "data"
HOLDINGS_PATH = DATA_DIR / "holdings.json"
CACHE_DIR = DATA_DIR / "cache"

st.set_page_config(page_title="株投資リサーチアプリ", layout="wide")

try:
    check_claude_cli_available()
except Exception as exc:
    st.error(str(exc))
    st.stop()

st.sidebar.markdown(DISCLAIMER_NOTICE)

tab_portfolio, tab_screening = st.tabs(["ポートフォリオ", "スクリーニング"])

with tab_portfolio:
    st.header("保有銘柄ポートフォリオ")

    holdings = load_holdings(HOLDINGS_PATH)
    holdings_df = pd.DataFrame(holdings or [{"ticker": "", "shares": 0, "cost": 0.0}])
    edited_df = st.data_editor(holdings_df, num_rows="dynamic", key="holdings_editor")

    if st.button("保有銘柄を保存"):
        new_holdings = [
            row for row in edited_df.to_dict(orient="records") if row.get("ticker")
        ]
        save_holdings(HOLDINGS_PATH, new_holdings)
        st.success("保存しました。")
        holdings = new_holdings

    force_regenerate = st.checkbox("キャッシュを無視して再生成する")

    if holdings and st.button("レビューを生成"):
        cache_key = "portfolio-review-" + "-".join(
            f"{h['ticker']}:{h['shares']}:{h['cost']}" for h in holdings
        )
        cached_report = None if force_regenerate else read_cache(CACHE_DIR, cache_key)

        if cached_report is not None:
            report = cached_report
        else:
            current_prices = {}
            price_histories = {}
            fundamentals_by_ticker = {}
            technicals_by_ticker = {}
            news_by_ticker = {}

            for holding in holdings:
                ticker = holding["ticker"]
                history = fetch_price_history(ticker, period="6mo")
                if not history.empty:
                    current_prices[ticker] = float(history["Close"].iloc[-1])
                    price_histories[ticker] = history["Close"]
                fundamentals_by_ticker[ticker] = analyze_fundamentals(ticker)
                technicals_by_ticker[ticker] = analyze_technical(history)
                news_by_ticker[ticker] = fetch_news(ticker)

            news_sentiment_by_ticker = research_news_batch(news_by_ticker, call_llm=call_llm)

            report = generate_portfolio_review(
                holdings,
                current_prices,
                price_histories,
                fundamentals_by_ticker,
                technicals_by_ticker,
                news_sentiment_by_ticker,
                call_llm=call_llm,
            )
            write_cache(CACHE_DIR, cache_key, report)

        st.markdown(report)

with tab_screening:
    st.info("準備中です。")
```

- [ ] **Step 2: 手動でアプリを起動し、ポートフォリオタブを確認する**

Run: `cd app && uv run streamlit run app.py`

確認項目:
- ブラウザでアプリが開き、サイドバーに免責事項が表示される
- 「ポートフォリオ」タブでティッカー・株数・取得単価を入力し「保有銘柄を保存」を押すと `app/data/holdings.json` が作成される
- 「レビューを生成」を押すと、事実データとAIの考察が生成され、`DISCLAIMER_NOTICE` がレポートの冒頭・末尾両方に表示される
- 同じ保有内容で再度「レビューを生成」を押すとキャッシュから即座に表示される（ログ上でLLM呼び出しが発生しないことを確認する）
- 「キャッシュを無視して再生成する」にチェックを入れて再度生成すると、レポートが再生成される

確認後、Ctrl+Cでサーバーを停止する。

- [ ] **Step 3: コミットする**

```bash
git add app/app.py
git commit -m "feat: wire portfolio tab into Streamlit app"
```

---

### Task 18: `app.py` 拡張 — スクリーニングタブ

**Files:**
- Modify: `app/app.py`

**Interfaces:**
- Consumes: `prompt_patterns.screening.{build_screening_prompt,apply_filters,generate_screening_comments}`（Task 15）, `data_api.stock_price_api.fetch_universe_fundamentals`（Task 6）, `screening.universe.UNIVERSE`（Task 16）

- [ ] **Step 1: importを追加する**

`app/app.py` の先頭のimportブロックに以下を追加する。
```python
import json

from data_api.stock_price_api import fetch_universe_fundamentals
from prompt_patterns.screening import (
    apply_filters,
    build_screening_prompt,
    generate_screening_comments,
)
from screening.universe import UNIVERSE
```

- [ ] **Step 2: スクリーニングタブの中身を置き換える**

`app/app.py` の末尾にある以下のプレースホルダーを置き換える。

Before:
```python
with tab_screening:
    st.info("準備中です。")
```

After:
```python
with tab_screening:
    st.header("銘柄スクリーニング")

    condition_text = st.text_input(
        "スクリーニング条件を自然言語で入力してください",
        placeholder="PERが15倍以下で配当利回りが3%以上",
    )

    if condition_text:
        prompt = build_screening_prompt(condition_text)
        raw_filters = call_llm(prompt)
        filters = None
        try:
            filters = json.loads(raw_filters)
        except json.JSONDecodeError:
            st.error("条件の解釈に失敗しました。条件を言い換えて再度お試しください。")

        if filters is not None:
            st.subheader("AIが解釈した条件（適用前に確認してください）")
            st.json(filters)

            if st.button("この条件で絞り込む"):
                universe_df = fetch_universe_fundamentals(UNIVERSE, CACHE_DIR)
                result_df = apply_filters(universe_df, filters)

                st.subheader(f"絞り込み結果（{len(result_df)}件）")
                st.dataframe(result_df)

                comments = generate_screening_comments(result_df, call_llm=call_llm)
                st.subheader("銘柄ごとのAIコメント")
                for ticker in result_df["ticker"]:
                    st.write(f"**{ticker}**: {comments.get(ticker, 'コメント生成失敗')}")
```

- [ ] **Step 3: 手動でアプリを起動し、スクリーニングタブを確認する**

Run: `cd app && uv run streamlit run app.py`

確認項目:
- 「スクリーニング」タブで条件文（例:「PERが15倍以下で配当利回りが3%以上」）を入力すると、AIが解釈したJSONフィルタが表示される
- 「この条件で絞り込む」を押すまで実データへの絞り込みが行われないことを確認する
- ボタンを押すと絞り込み結果のテーブルと、銘柄ごとの一言AIコメントが表示される
- 同じユニバースで再度絞り込むと、`app/data/cache/` のキャッシュにより2回目のfundamentals取得が高速であることを確認する

確認後、Ctrl+Cでサーバーを停止する。

- [ ] **Step 4: コミットする**

```bash
git add app/app.py
git commit -m "feat: wire screening tab into Streamlit app"
```

---

### Task 19: 全体の自動テスト実行とエンドツーエンド確認

**Files:**
- （新規作成なし。既存ファイルの検証のみ）

- [ ] **Step 1: `claude` CLIが利用可能であることを確認する**

Run: `claude --version`
Expected: バージョン情報が出力される（インストール・ログイン済みであること）

- [ ] **Step 2: 自動テストをすべて実行する**

Run: `cd app && uv run pytest -v`
Expected: 全テストが `PASSED`（Task 1〜16で追加した全テストファイルが対象）

- [ ] **Step 3: アプリを起動し、一連の流れを通しで確認する**

Run: `cd app && uv run streamlit run app.py`

確認項目（Task 17・18の確認項目を通しで再確認する）:
1. 保有銘柄を2〜3件登録し保存する
2. ポートフォリオレビューを生成し、免責事項・事実データ・AIの考察が正しく表示されることを確認する
3. スクリーニング条件を入力し、確認ステップを経て絞り込み結果とAIコメントが表示されることを確認する
4. データ取得できない銘柄（存在しないティッカー等）を保有銘柄に含めても、アプリ全体がクラッシュせず「データ取得不可」として扱われることを確認する

確認後、Ctrl+Cでサーバーを停止する。

- [ ] **Step 4: 最終コミット（残差分があれば）**

```bash
git status
```
差分があれば内容を確認のうえコミットする。差分がなければこのステップは完了とする。

---

## Self-Review

**Spec coverage:**
- モジュール構成 → Task 1（scaffolding）、各タスクのCreateファイルがspecの`app/`構成と一致
- ポートフォリオタブのデータフロー（編集→レビュー生成→キャッシュ）→ Task 7, 8, 9, 14, 17
- スクリーニングタブのデータフロー（条件入力→確認→絞り込み→コメント）→ Task 6, 15, 16, 18
- Claude Code CLI連携・バッチ化 → Task 4, 12, 15
- データ永続化（holdings.json, cache/）→ Task 7, 3, 17
- エラーハンドリング（個別銘柄失敗・LLM失敗・CLI未検出・JSON破損）→ Task 4（CLI未検出）, 7（JSON破損）, 12・15（LLM応答パース失敗のフォールバック）, 17・18（アプリ起動時チェック・手動確認項目）
- 免責事項の冒頭・末尾挿入 → Task 13, 14でテストにより保証
- テスト方針（純粋関数はpytest、UIは手動）→ 全タスクに反映
- v1スコープ外の機能は実装タスクに含めていない

**Placeholder scan:** 「TBD」「後で実装」等の記述なし。全タスクに完全なコードを記載済み。

**Type consistency:** `analyze_fundamentals` の返り値キー（`per`, `pbr`, `dividend_yield`）、`analyze_technical` の返り値キー（`ma_short`, `ma_long`, `signal`）、`research_news_batch` の返り値キー（`sentiment`, `confidence`）が、Task 14 `build_holding_snapshot` の参照キーと一致することを確認済み。`fetch_universe_fundamentals` の出力列名（`per`, `pbr`, `dividend_yield_pct`）が Task 15 `apply_filters` / `build_comment_prompt` の参照列名と一致することを確認済み。
