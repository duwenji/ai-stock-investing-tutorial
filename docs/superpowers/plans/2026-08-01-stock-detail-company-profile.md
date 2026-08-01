# 銘柄詳細ダイアログへの基本情報追加 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 銘柄詳細ダイアログに、業種・詳細業種（事実）と市場でのポジション・強み
（AIによる要約）からなる「基本情報」セクションを追加する。

**Architecture:** yfinanceから業種・事業内容を取得する新規関数を追加し、事業内容を
根拠にAIが市場ポジション・強みを日本語で要約する新規プロンプトを追加する。
`generate_stock_detail`がこれらを統合してpayloadに`profile`を追加し、
`show_stock_detail_dialog`が新しいセクションとして表示する。

**Tech Stack:** Python / yfinance / Streamlit / 既存の`data_api.llm_client.call_llm`

## Global Constraints

- 既存の`fetch_fundamentals`/`fetch_universe_fundamentals`（PER/PBR/ROE等の一括取得）
  は変更しない。
- 業種データは常にyfinanceの`sector`/`industry`（英語表記）のみを使う。既存の
  17業種分類`SECTOR_MAP`とは統合しない。
- `fetch_company_profile`は`fetch_universe_fundamentals`（228銘柄一括取得）には
  混ぜない。銘柄詳細を開いた単一銘柄でのみ呼び出す。
- `business_summary`が空の場合はLLMを呼ばず、固定の「情報なし」メッセージを使う。
- `show_stock_detail_dialog`のシグネチャ（`show_stock_detail_dialog(ticker, name)`）
  は変更しない。
- 設計の詳細は`docs/superpowers/specs/2026-08-01-stock-detail-company-profile-design.md`
  を正とする。

---

## Task 1: `fetch_company_profile`の追加

**Files:**
- Modify: `app/data_api/stock_price_api.py`（`fetch_fundamentals`関数の後に追加）
- Modify: `app/tests/test_stock_price_api.py`（`FakeTicker.info`にフィールド追加、
  テスト追加）

**Interfaces:**
- Produces: `data_api.stock_price_api.fetch_company_profile(ticker_symbol: str) -> dict`
  戻り値: `{"ticker": str, "sector": str | None, "industry": str | None, "business_summary": str | None}`

- [ ] **Step 1: `FakeTicker.info`にsector/industry/longBusinessSummaryを追加する**

`app/tests/test_stock_price_api.py`の`FakeTicker.info`プロパティを次のように変更する:

```python
    @property
    def info(self):
        return {
            "longName": "Fake Corp",
            "trailingPE": 12.3,
            "priceToBook": 1.1,
            "dividendYield": 0.02,
            "marketCap": 1_000_000,
            "returnOnEquity": 0.155,
            "revenueGrowth": 0.082,
            "sector": "Consumer Cyclical",
            "industry": "Auto Manufacturers",
            "longBusinessSummary": "Test business summary text.",
        }
```

（`EmptyInfoTicker`は`FakeTicker`を継承し`info`を`{}`で上書きしているため、
このステップの変更だけで自動的に「欠損時」のテストにも使える）

- [ ] **Step 2: 失敗するテストを書く**

`app/tests/test_stock_price_api.py`の末尾（`test_fetch_universe_price_histories_skips_empty_history`
の後）に追加する:

```python
def test_fetch_company_profile_maps_info_fields(monkeypatch):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    result = stock_price_api.fetch_company_profile("7203.T")
    assert result["ticker"] == "7203.T"
    assert result["sector"] == "Consumer Cyclical"
    assert result["industry"] == "Auto Manufacturers"
    assert result["business_summary"] == "Test business summary text."


def test_fetch_company_profile_missing_fields_return_none(monkeypatch):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", EmptyInfoTicker)
    result = stock_price_api.fetch_company_profile("7203.T")
    assert result["sector"] is None
    assert result["industry"] is None
    assert result["business_summary"] is None


def test_fetch_company_profile_logs_request_and_response(monkeypatch, caplog):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_company_profile("7203.T")

    assert "company profileリクエスト: ticker=7203.T" in caplog.text
    assert "company profileレスポンス: ticker=7203.T" in caplog.text
    assert "Auto Manufacturers" in caplog.text
```

- [ ] **Step 3: テストが失敗することを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_stock_price_api.py -k fetch_company_profile -v`
Expected: FAIL（`AttributeError: module 'data_api.stock_price_api' has no attribute 'fetch_company_profile'`）

- [ ] **Step 4: `fetch_company_profile`を実装する**

`app/data_api/stock_price_api.py`の`fetch_fundamentals`関数の直後に追加する:

```python
def fetch_company_profile(ticker_symbol: str) -> dict:
    """指定銘柄の業種・事業内容をyfinance経由で取得する。"""
    logger.info("company profileリクエスト: ticker=%s", ticker_symbol)
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info
    result = {
        "ticker": ticker_symbol,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "business_summary": info.get("longBusinessSummary"),
    }
    logger.info("company profileレスポンス: ticker=%s data=%s", ticker_symbol, result)
    return result
```

- [ ] **Step 5: テストを実行し、全てPASSすることを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_stock_price_api.py -v`
Expected: 全件PASS（既存テストも含め回帰なし）

- [ ] **Step 6: コミット**

```bash
cd app
git add data_api/stock_price_api.py tests/test_stock_price_api.py
git commit -m "$(cat <<'EOF'
fetch_company_profileを追加

銘柄詳細ダイアログの基本情報セクション向けに、yfinanceから業種・
詳細業種・事業内容の説明を取得する関数を新設する。
fetch_universe_fundamentals（228銘柄一括取得）には混ぜず、銘柄詳細を
開いた単一銘柄でのみ呼び出す。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `build_company_profile_prompt`の追加

**Files:**
- Modify: `app/prompt_patterns/stock_detail.py`（`build_stock_detail_prompt`の後に追加）
- Modify: `app/tests/test_stock_detail_prompt.py`

**Interfaces:**
- Consumes: なし（文字列組み立てのみ）
- Produces:
  `prompt_patterns.stock_detail.build_company_profile_prompt(ticker: str, name: str | None, sector: str | None, industry: str | None, business_summary: str) -> str`
  （`business_summary`は呼び出し元が空でないことを保証してから渡す前提）

- [ ] **Step 1: 失敗するテストを書く**

`app/tests/test_stock_detail_prompt.py`の末尾に追加する:

```python
from prompt_patterns.stock_detail import build_company_profile_prompt


def test_build_company_profile_prompt_includes_ticker_name_and_business_summary():
    prompt = build_company_profile_prompt(
        "AAA.T", "エーエー株式会社", "Technology", "Semiconductors", "Test business summary."
    )
    assert "AAA.T" in prompt
    assert "エーエー株式会社" in prompt
    assert "Technology" in prompt
    assert "Semiconductors" in prompt
    assert "Test business summary." in prompt


def test_build_company_profile_prompt_omits_name_when_none():
    prompt = build_company_profile_prompt("AAA.T", None, "Technology", "Semiconductors", "summary")
    assert "AAA.T" in prompt
    assert "（None）" not in prompt


def test_build_company_profile_prompt_handles_missing_sector_and_industry():
    prompt = build_company_profile_prompt("AAA.T", "エーエー株式会社", None, None, "summary")
    assert "不明" in prompt


def test_build_company_profile_prompt_instructs_no_directive_language():
    prompt = build_company_profile_prompt(
        "AAA.T", "エーエー株式会社", "Technology", "Semiconductors", "summary"
    )
    assert "断定的な投資判断" in prompt
```

このファイルの1行目のimport文（`from prompt_patterns.stock_detail import build_stock_detail_prompt`）
はそのまま残し、上記の新しいimport文を追加する形にする（2つのimport文が並ぶ）。

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_stock_detail_prompt.py -k company_profile -v`
Expected: FAIL（`ImportError: cannot import name 'build_company_profile_prompt'`）

- [ ] **Step 3: `build_company_profile_prompt`を実装する**

`app/prompt_patterns/stock_detail.py`の末尾（`build_stock_detail_prompt`関数の後）に
追加する:

```python
def build_company_profile_prompt(
    ticker: str,
    name: str | None,
    sector: str | None,
    industry: str | None,
    business_summary: str,
) -> str:
    # yfinance由来の事業内容説明（英語）を根拠に、市場での立ち位置・強みを
    # 日本語で要約させる。business_summaryが空の場合はこの関数を呼ばない
    # （呼び出し元でガードする）。
    label = f"{ticker}（{name}）" if name else ticker
    return (
        f"銘柄 {label} について、以下の事業内容の説明を踏まえて、"
        "市場での立ち位置や強みを日本語で3〜4文程度で要約してください。"
        "断定的な投資判断は含めないでください。\n\n"
        f"業種: {sector or '不明'}\n"
        f"詳細業種: {industry or '不明'}\n"
        f"事業内容: {business_summary}\n"
    )
```

- [ ] **Step 4: テストを実行し、全てPASSすることを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_stock_detail_prompt.py -v`
Expected: 全件PASS

- [ ] **Step 5: コミット**

```bash
cd app
git add prompt_patterns/stock_detail.py tests/test_stock_detail_prompt.py
git commit -m "$(cat <<'EOF'
build_company_profile_promptを追加

事業内容の説明（yfinance由来）を根拠に、市場での立ち位置・強みを
日本語で要約させるプロンプトを、既存のstock_detail向けプロンプト
モジュールに追加する。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `generate_stock_detail`への統合

**Files:**
- Modify: `app/stock_detail/detail.py`
- Modify: `app/tests/test_stock_detail.py`

**Interfaces:**
- Consumes: `data_api.stock_price_api.fetch_company_profile`（Task 1）,
  `prompt_patterns.stock_detail.build_company_profile_prompt`（Task 2）
- Produces: `generate_stock_detail(...)`の戻り値（payload）に
  `"profile": {"sector": str | None, "industry": str | None, "profile_comment": str}`
  キーを追加する。`fetch_company_profile`引数（デフォルト:
  `data_api.stock_price_api.fetch_company_profile`）を新設する。

- [ ] **Step 1: 失敗するテストを書く（新規payloadフィールド）**

`app/tests/test_stock_detail.py`の`test_generate_stock_detail_builds_payload_from_dependencies`
を次の内容に置き換える:

```python
def test_generate_stock_detail_builds_payload_from_dependencies(tmp_path):
    def fake_call_llm(prompt):
        if "市場での立ち位置" in prompt:
            return "テスト用のプロフィール要約です。"
        return "テスト用の総合コメントです。"

    result = generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=fake_call_llm,
        fetch_price_history=lambda ticker, period: _fake_history(),
        fetch_news=lambda ticker: [
            {"title": "ニュース1", "publisher": "社", "link": "http://example.com"}
        ],
        analyze_fundamentals=lambda ticker: {"per": 12.0, "pbr": 1.1, "dividend_yield": 2.5},
        analyze_technical=lambda history: {"ma_short": 101.0, "ma_long": 100.0, "signal": "強気"},
        fetch_company_profile=lambda ticker: {
            "ticker": ticker,
            "sector": "Consumer Cyclical",
            "industry": "Auto Manufacturers",
            "business_summary": "Test business summary.",
        },
    )

    assert result == {
        "ticker": "AAA.T",
        "name": "エーエー株式会社",
        "price_history": {
            "dates": ["2026-01-01T00:00:00", "2026-01-02T00:00:00", "2026-01-03T00:00:00"],
            "open": [99.0, 100.5, 101.5],
            "high": [101.0, 102.0, 103.0],
            "low": [98.5, 100.0, 101.0],
            "close": [100.0, 101.0, 102.0],
            "volume": [1000, 1200, 900],
        },
        "fundamentals": {"per": 12.0, "pbr": 1.1, "dividend_yield": 2.5},
        "technical": {"ma_short": 101.0, "ma_long": 100.0, "signal": "強気"},
        "news": [{"title": "ニュース1", "publisher": "社", "link": "http://example.com"}],
        "comment": "テスト用の総合コメントです。",
        "profile": {
            "sector": "Consumer Cyclical",
            "industry": "Auto Manufacturers",
            "profile_comment": "テスト用のプロフィール要約です。",
        },
    }
```

`app/tests/test_stock_detail.py`の残り4つの既存テストにも、
`fetch_company_profile`引数を追加する（デフォルト実装は実際にyfinanceへ
アクセスしてしまうため、必ずフェイクを渡す）。

`test_generate_stock_detail_handles_empty_price_history`を次のように変更する
（`fetch_company_profile`引数を追加。sector/industry/business_summaryをすべて
Noneにすることで、後述のプロフィールLLM呼び出しスキップの検証も兼ねる）:

```python
def test_generate_stock_detail_handles_empty_price_history(tmp_path):
    result = generate_stock_detail(
        "AAA.T",
        None,
        tmp_path,
        call_llm=lambda prompt: "コメント",
        fetch_price_history=lambda ticker, period: pd.DataFrame(
            {"Open": [], "High": [], "Low": [], "Close": [], "Volume": []}
        ),
        fetch_news=lambda ticker: [],
        analyze_fundamentals=lambda ticker: {"per": None, "pbr": None, "dividend_yield": None},
        analyze_technical=lambda history: {"ma_short": None, "ma_long": None, "signal": "データ不足"},
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": None, "industry": None, "business_summary": None
        },
    )

    assert result["price_history"] == {
        "dates": [],
        "open": [],
        "high": [],
        "low": [],
        "close": [],
        "volume": [],
    }
    assert result["news"] == []
    assert result["name"] is None
    assert result["profile"]["profile_comment"] == "事業内容の情報が取得できませんでした。"
```

`test_generate_stock_detail_uses_cache_and_skips_dependency_calls`を次のように
変更する（初回呼び出しに`fetch_company_profile`のフェイクを追加し、
キャッシュヒット時の2回目呼び出しでは`fail`を渡してプロフィール取得も
呼ばれないことを確認する）:

```python
def test_generate_stock_detail_uses_cache_and_skips_dependency_calls(tmp_path):
    call_count = {"n": 0}

    def counting_fetch_price_history(ticker, period):
        call_count["n"] += 1
        return _fake_history()

    generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=lambda prompt: "初回コメント",
        fetch_price_history=counting_fetch_price_history,
        fetch_news=lambda ticker: [],
        analyze_fundamentals=lambda ticker: {"per": 1, "pbr": 1, "dividend_yield": 1},
        analyze_technical=lambda history: {"ma_short": 1, "ma_long": 1, "signal": "強気"},
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
        },
    )
    assert call_count["n"] == 1

    def fail(*args, **kwargs):
        raise AssertionError("キャッシュヒット時は依存関数が呼ばれてはいけない")

    result = generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=fail,
        fetch_price_history=fail,
        fetch_news=fail,
        analyze_fundamentals=fail,
        analyze_technical=fail,
        fetch_company_profile=fail,
    )
    assert result["comment"] == "初回コメント"
```

`test_generate_stock_detail_ignores_stale_cache_missing_ohlcv`に
`fetch_company_profile`引数を追加する:

```python
def test_generate_stock_detail_ignores_stale_cache_missing_ohlcv(tmp_path):
    stale_payload = {
        "ticker": "AAA.T",
        "name": "エーエー株式会社",
        "price_history": {
            "dates": ["2026-01-01T00:00:00"],
            "close": [100.0],
        },
        "fundamentals": {"per": 1, "pbr": 1, "dividend_yield": 1},
        "technical": {"ma_short": 1, "ma_long": 1, "signal": "強気"},
        "news": [],
        "comment": "旧形式のキャッシュ",
    }
    write_cache(tmp_path, "stock-detail-AAA.T", json.dumps(stale_payload, ensure_ascii=False))

    result = generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=lambda prompt: "再生成後のコメント",
        fetch_price_history=lambda ticker, period: _fake_history(),
        fetch_news=lambda ticker: [],
        analyze_fundamentals=lambda ticker: {"per": 1, "pbr": 1, "dividend_yield": 1},
        analyze_technical=lambda history: {"ma_short": 1, "ma_long": 1, "signal": "強気"},
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
        },
    )

    assert result["comment"] == "再生成後のコメント"
    assert result["price_history"]["open"] == [99.0, 100.5, 101.5]
```

`test_generate_stock_detail_logs_duration_on_cache_miss`に
`fetch_company_profile`引数を追加する:

```python
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
            fetch_company_profile=lambda ticker: {
                "ticker": ticker, "sector": None, "industry": None, "business_summary": None
            },
        )

    assert "銘柄詳細生成（AAA.T）" in caplog.text
    assert "を開始" in caplog.text
    assert "が完了しました" in caplog.text
```

最後に、新しいテストとして次を末尾に追加する（旧形式キャッシュ＝`profile`
キーが無いキャッシュが再生成されることの確認）:

```python
def test_generate_stock_detail_ignores_stale_cache_missing_profile(tmp_path):
    stale_payload = {
        "ticker": "AAA.T",
        "name": "エーエー株式会社",
        "price_history": {
            "dates": ["2026-01-01T00:00:00", "2026-01-02T00:00:00", "2026-01-03T00:00:00"],
            "open": [99.0, 100.5, 101.5],
            "high": [101.0, 102.0, 103.0],
            "low": [98.5, 100.0, 101.0],
            "close": [100.0, 101.0, 102.0],
            "volume": [1000, 1200, 900],
        },
        "fundamentals": {"per": 1, "pbr": 1, "dividend_yield": 1},
        "technical": {"ma_short": 1, "ma_long": 1, "signal": "強気"},
        "news": [],
        "comment": "profileキーが無い旧形式のキャッシュ",
    }
    write_cache(tmp_path, "stock-detail-AAA.T", json.dumps(stale_payload, ensure_ascii=False))

    result = generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=lambda prompt: "再生成後のコメント",
        fetch_price_history=lambda ticker, period: _fake_history(),
        fetch_news=lambda ticker: [],
        analyze_fundamentals=lambda ticker: {"per": 1, "pbr": 1, "dividend_yield": 1},
        analyze_technical=lambda history: {"ma_short": 1, "ma_long": 1, "signal": "強気"},
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
        },
    )

    assert result["comment"] == "再生成後のコメント"
    assert "profile" in result
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_stock_detail.py -v`
Expected: 複数件FAIL（`TypeError: generate_stock_detail() got an unexpected keyword argument 'fetch_company_profile'`）

- [ ] **Step 3: `generate_stock_detail`を実装する**

`app/stock_detail/detail.py`の内容全体を次の内容で置き換える:

```python
"""個別銘柄の詳細画面向けに、株価・ファンダメンタルズ・テクニカル分析・
ニュース・LLMによる講評コメント・基本情報（業種・市場ポジション）を
1つにまとめて生成するモジュール。"""

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
from data_api.stock_price_api import fetch_company_profile as default_fetch_company_profile
from data_api.stock_price_api import fetch_news as default_fetch_news
from data_api.stock_price_api import fetch_price_history as default_fetch_price_history
from prompt_patterns.stock_detail import build_company_profile_prompt, build_stock_detail_prompt

logger = logging.getLogger(__name__)

_NO_PROFILE_MESSAGE = "事業内容の情報が取得できませんでした。"


def generate_stock_detail(
    ticker: str,
    name: str | None,
    cache_dir: Path,
    call_llm=default_call_llm,
    fetch_price_history=default_fetch_price_history,
    fetch_news=default_fetch_news,
    analyze_fundamentals=default_analyze_fundamentals,
    analyze_technical=default_analyze_technical,
    fetch_company_profile=default_fetch_company_profile,
) -> dict:
    """指定銘柄の詳細情報一式を組み立てる。

    依存する各取得・分析処理は引数でデフォルト実装を上書きできるようにし、
    テスト時にモック差し替えしやすくしている。
    """
    # 生成にはLLM呼び出しを含みコストが高いため、キャッシュがあれば再利用する。
    # 旧バージョンのキャッシュ（price_historyにopenキーが無い、またはprofile
    # キーが無いもの）は無効として扱う。
    cache_key = f"stock-detail-{ticker}"
    cached = read_cache(cache_dir, cache_key)
    if cached is not None:
        payload = json.loads(cached)
        if "open" in payload["price_history"] and "profile" in payload:
            return payload

    with log_duration(logger, f"銘柄詳細生成（{ticker}）"):
        # 移動平均線（特に75日線）の計算バッファとして、表示に必要な6ヶ月分より
        # 長めの2年分を取得する。
        history = fetch_price_history(ticker, period="2y")
        fundamentals = analyze_fundamentals(ticker)
        technical = analyze_technical(history)
        news = fetch_news(ticker)
        company_profile = fetch_company_profile(ticker)

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

        # 事業内容の説明が無ければLLMを呼ばず、固定メッセージにする
        business_summary = company_profile.get("business_summary")
        if business_summary:
            profile_prompt = build_company_profile_prompt(
                ticker,
                name,
                company_profile.get("sector"),
                company_profile.get("industry"),
                business_summary,
            )
            profile_comment = call_llm(profile_prompt)
        else:
            profile_comment = _NO_PROFILE_MESSAGE

        payload = {
            "ticker": ticker,
            "name": name,
            "price_history": price_history,
            "fundamentals": fundamentals,
            "technical": technical,
            "news": news,
            "comment": comment,
            "profile": {
                "sector": company_profile.get("sector"),
                "industry": company_profile.get("industry"),
                "profile_comment": profile_comment,
            },
        }
        write_cache(cache_dir, cache_key, json.dumps(payload, ensure_ascii=False))
        return payload
```

- [ ] **Step 4: テストを実行し、全てPASSすることを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_stock_detail.py -v`
Expected: 全件PASS

- [ ] **Step 5: コミット**

```bash
cd app
git add stock_detail/detail.py tests/test_stock_detail.py
git commit -m "$(cat <<'EOF'
generate_stock_detailに基本情報（業種・市場ポジション）を統合

fetch_company_profileとbuild_company_profile_promptを組み合わせ、
payloadに"profile"（業種・詳細業種・AIによる市場ポジション/強みの要約）
を追加する。事業内容が取得できない銘柄はLLMを呼ばず固定メッセージに
する。旧形式（profileキーが無い）キャッシュは自動的に再生成される。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 銘柄詳細ダイアログのUI表示

**Files:**
- Modify: `app/app_tabs/shared.py`（`show_stock_detail_dialog`関数）

**Interfaces:**
- Consumes: `generate_stock_detail(...)`の戻り値の`"profile"`キー（Task 3）
- Produces: なし（UI描画のみ）

このタスクは既存の`show_stock_detail_dialog`と同様にUI描画であり、直接の
自動テストは持たない（既存の`app_tabs/*.py`はいずれも未テスト）。
全体テストスイートの回帰確認と、AppTestによる初回描画の例外なし確認で検証する。

- [ ] **Step 1: 「基本情報」セクションを追加する**

`app/app_tabs/shared.py`の`show_stock_detail_dialog`関数内、
`st.subheader(f"{ticker} {detail.get('name') or ''}")`の直後に追加する:

```python
    st.subheader(f"{ticker} {detail.get('name') or ''}")

    profile = detail.get("profile") or {}
    st.subheader("基本情報")
    profile_col1, profile_col2 = st.columns(2)
    profile_col1.write(f"業種: {profile.get('sector') or '―'}")
    profile_col2.write(f"詳細業種: {profile.get('industry') or '―'}")
    st.caption("AIによる市場ポジション・強みの要約")
    st.write(profile.get("profile_comment") or "―")
```

（この直後に既存の`price_history = detail["price_history"]`以降のチャート
描画コードがそのまま続く。それより後のコード・既存のPER/PBR/配当利回り
メトリクス・AI総合分析コメント・関連ニュースのセクションは変更しない）

- [ ] **Step 2: インポートが解決することを確認する**

Run: `cd app && .venv/Scripts/python.exe -c "import app_tabs.shared; print('OK')"`
Expected: `OK`が出力される（構文エラーなし）

- [ ] **Step 3: AppTestでアプリ全体が例外なく初回描画されることを確認する**

Run:
```bash
cd app
PYTHONPATH="$(pwd)" .venv/Scripts/python.exe -c "
from streamlit.testing.v1 import AppTest
at = AppTest.from_file('app.py', default_timeout=60)
at.run()
print('exception:', at.exception)
print('num tabs:', len(at.tabs))
"
```
Expected: `exception: ElementList()`（空、＝例外なし）、`num tabs: 6`

（`show_stock_detail_dialog`自体は`@st.dialog`のためボタンクリック等の
イベントが無ければ呼ばれないが、この確認は既存タブ・AI戦略ビルダータブの
初回描画に回帰がないことを保証する）

- [ ] **Step 4: 全体テストスイートを実行する**

Run: `cd app && .venv/Scripts/python.exe -m pytest -q`
Expected: 全件PASS（既存テスト＋Task 1〜3で追加したテストすべて）

- [ ] **Step 5: `streamlit run`で手動確認する**

Run: `cd app && .venv/Scripts/python.exe -m streamlit run app.py`

ブラウザで次を確認する（Claude Code CLIがログイン済みである前提）:

1. いずれかのタブ（例: スクリーニング）で銘柄行をクリックし、銘柄詳細ダイアログを開く
2. 銘柄名見出しの直後に「基本情報」セクションが表示される
3. 「業種」「詳細業種」が英語表記で表示される（yfinanceでデータが取得できる銘柄の場合）
4. 「AIによる市場ポジション・強みの要約」に日本語の要約文が表示される
5. その下に既存の株価チャート・PER/PBR等・AI総合分析コメント・関連ニュースが
   従来通り表示される

Expected: 上記すべてがエラーなく動作する。動作しない場合は原因を修正してから次に進む。

- [ ] **Step 6: コミット**

```bash
cd app
git add app_tabs/shared.py
git commit -m "$(cat <<'EOF'
銘柄詳細ダイアログに基本情報セクションを追加

業種・詳細業種（yfinance由来の事実）と、AIによる市場ポジション・
強みの要約を、銘柄名見出しの直後に表示する。既存のAI総合分析コメント
と同様、事実とAIの考察を分離して表示する。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## 実装完了後の最終確認

- [ ] **Run:** `cd app && .venv/Scripts/python.exe -m pytest -v`
  **Expected:** 全テストPASS（既存テスト + 本計画で追加したテストすべて）
- [ ] **Run:** `cd app && .venv/Scripts/python.exe -m streamlit run app.py` で起動し、
  Task 4 Step 5のゴールデンパスチェックリストを再確認する
