# data_api 外部送受信内容ログ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `data_api/llm_client.py`・`data_api/stock_price_api.py`の各関数に、外部サービス（Claude CLI・yfinance・Yahoo!ファイナンス日本版）へのリクエスト内容とレスポンス内容そのものをINFOログとして記録し、`app/logs/app.log`から後から確認できるようにする。

**Architecture:** 既存の`common/logging_config.py`（[2026-07-26-app-logging.md](2026-07-26-app-logging.md)で導入済み）の`logger = logging.getLogger(__name__)`をそのまま使い、各関数の処理の冒頭でリクエスト内容を、正常終了直前でレスポンス内容をそれぞれ`logger.info`する。既存の`log_duration`（所要時間ログ）はそのまま残し、内容ログはその内側に追加する形にする。失敗時は`log_duration`が`logger.exception`で記録するため、レスポンスログは成功時のみ出力し二重記録を避ける。

**Tech Stack:** Python標準ライブラリ`logging`のみ（新規pip依存追加なし）。pytest（`caplog`）。

## Global Constraints

- ログレベルはINFO固定（既存の`common/logging_config.py`の方針を踏襲）
- レスポンス内容は要約・切り詰めをせず全件・全文をログに出す（株価履歴OHLCV全件、Yahoo!ファイナンスHTML全文を含む）。ログファイルの行が長くなること・226銘柄一括処理でログが数百行増えることは許容する（[design doc](../specs/2026-07-26-data-api-send-receive-logging-design.md)参照）
- 失敗時（例外発生）はレスポンス内容ログを出力しない（`log_duration`の`logger.exception`と二重記録しない）
- `yfinance`経由の関数（`fetch_price_history`/`fetch_fundamentals`/`fetch_news`）は生HTTPが見えないため、「リクエスト」は関数への入力引数、「レスポンス」は関数の戻り値をログ対象とする。`fetch_japanese_name`のみ`requests`による実際のURL・生レスポンステキストをログする
- テスト実行コマンド: `uv run pytest -v`（作業ディレクトリは`ai-stock-investing-tutorial/app`）

---

## File Structure

- Modify: `data_api/llm_client.py` — `call_llm`にリクエスト/レスポンス内容ログを追加／Modify: `tests/test_llm_client.py`
- Modify: `data_api/stock_price_api.py` — `fetch_price_history`/`fetch_fundamentals`/`fetch_news`/`fetch_japanese_name`にリクエスト/レスポンス内容ログを追加／Modify: `tests/test_stock_price_api.py`

---

### Task 1: `data_api/llm_client.py` — Claude CLIの送受信内容ログ

**Files:**
- Modify: `data_api/llm_client.py`
- Test: `tests/test_llm_client.py`

**Interfaces:**
- Consumes: なし（既存の`logger`・`log_duration`をそのまま使用）
- Produces: なし（`call_llm`のシグネチャ・戻り値は変更しない）

- [ ] **Step 1: Write the failing tests**

`tests/test_llm_client.py`の末尾に追加する:

```python
def test_call_llm_logs_request_and_response_content(monkeypatch, caplog):
    monkeypatch.setattr("shutil.which", lambda name: "claude-executable")

    def fake_run(args, input, capture_output, text, encoding, timeout):
        return subprocess.CompletedProcess(args, 0, stdout="response text\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with caplog.at_level(logging.INFO, logger="data_api.llm_client"):
        call_llm("this is the prompt content")

    assert "Claude CLIリクエスト: this is the prompt content" in caplog.text
    assert "Claude CLIレスポンス: response text" in caplog.text


def test_call_llm_does_not_log_response_on_failure(monkeypatch, caplog):
    monkeypatch.setattr("shutil.which", lambda name: "claude-executable")

    def fake_run(args, input, capture_output, text, encoding, timeout):
        return subprocess.CompletedProcess(
            args, 1, stdout="should not be logged", stderr="boom"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    with caplog.at_level(logging.INFO, logger="data_api.llm_client"):
        with pytest.raises(ClaudeCLIError):
            call_llm("prompt")

    assert "Claude CLIリクエスト: prompt" in caplog.text
    assert "Claude CLIレスポンス" not in caplog.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `ai-stock-investing-tutorial/app`): `uv run pytest tests/test_llm_client.py -v`
Expected: 既存9件はPASS、新規2件はFAIL（`caplog.text`にリクエスト/レスポンスの行が含まれないため）

- [ ] **Step 3: Write the implementation**

`data_api/llm_client.py`の`call_llm`関数（現在の45〜69行目）を次のように変更する。既存の「プロンプト本文は機密情報や長大なJSONを含みうるためログに出さず、長さのみ記録する。」というコメントは削除し、リクエスト全文・レスポンス全文をログする行を追加する:

現在:
```python
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

変更後:
```python
def call_llm(prompt: str, timeout: int = 120) -> str:
    """Claude Code CLIにプロンプトを渡し、応答テキストを取得する。

    各分析エージェントやコメント生成処理から共通のLLM呼び出し口として利用される。
    """
    executable = _resolve_claude_executable()
    with log_duration(logger, f"Claude CLI呼び出し（prompt長={len(prompt)}）"):
        logger.info("Claude CLIリクエスト: %s", prompt)
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
        logger.info("Claude CLIレスポンス: %s", result.stdout)
    return result.stdout.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_client.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add data_api/llm_client.py tests/test_llm_client.py
git commit -m "$(cat <<'EOF'
Log full request/response content for Claude CLI calls

call_llm now logs the complete prompt sent and the complete response
received (success only — failures are already captured with full
context by log_duration's exception logging). Supersedes the earlier
length-only logging, which undersold what's needed to debug prompt
issues after the fact.
EOF
)"
```

---

### Task 2: `data_api/stock_price_api.py` — yfinance/Yahoo!ファイナンスの送受信内容ログ

**Files:**
- Modify: `data_api/stock_price_api.py`
- Test: `tests/test_stock_price_api.py`

**Interfaces:**
- Consumes: なし（既存の`logger`をそのまま使用）
- Produces: なし（各関数のシグネチャ・戻り値は変更しない）

- [ ] **Step 1: Write the failing tests**

`tests/test_stock_price_api.py`の末尾に追加する:

```python
def test_fetch_price_history_logs_request_and_response(monkeypatch, caplog):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_price_history("7203.T", period="1mo")

    assert "株価履歴リクエスト: ticker=7203.T period=1mo" in caplog.text
    assert "株価履歴レスポンス: ticker=7203.T" in caplog.text
    assert "101" in caplog.text


def test_fetch_fundamentals_logs_request_and_response(monkeypatch, caplog):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_fundamentals("7203.T")

    assert "fundamentalsリクエスト: ticker=7203.T" in caplog.text
    assert "fundamentalsレスポンス: ticker=7203.T" in caplog.text
    assert "Fake Corp" in caplog.text


def test_fetch_news_logs_request_and_response(monkeypatch, caplog):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_news("7203.T", limit=1)

    assert "newsリクエスト: ticker=7203.T limit=1" in caplog.text
    assert "newsレスポンス: ticker=7203.T" in caplog.text
    assert "Headline 1" in caplog.text


def test_fetch_japanese_name_logs_request_and_response(monkeypatch, caplog):
    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(
            "<title>シャープ(株)【6753】：株価・株式情報（夜間PTS含む） - Yahoo!ファイナンス</title>"
        )

    monkeypatch.setattr(stock_price_api.requests, "get", fake_get)
    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_japanese_name("6753.T")

    assert "日本語銘柄名リクエスト: url=https://finance.yahoo.co.jp/quote/6753.T" in caplog.text
    assert "日本語銘柄名レスポンス: url=https://finance.yahoo.co.jp/quote/6753.T" in caplog.text
    assert "シャープ" in caplog.text


def test_fetch_japanese_name_logs_warning_on_request_failure(monkeypatch, caplog):
    def raise_error(url, headers=None, timeout=None):
        raise stock_price_api.requests.RequestException("network error")

    monkeypatch.setattr(stock_price_api.requests, "get", raise_error)
    with caplog.at_level(logging.INFO, logger="data_api.stock_price_api"):
        stock_price_api.fetch_japanese_name("6753.T")

    assert "日本語銘柄名取得失敗: url=https://finance.yahoo.co.jp/quote/6753.T" in caplog.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_stock_price_api.py -v`
Expected: 既存11件はPASS、新規5件はFAIL（`caplog.text`にリクエスト/レスポンスの行が含まれないため）

- [ ] **Step 3: Write the implementation**

`data_api/stock_price_api.py`の4関数（現在の26〜89行目）を次のように変更する。それぞれ冒頭にリクエストログ、戻り値確定後（`return`の直前）にレスポンスログを追加する:

現在:
```python
def fetch_price_history(ticker_symbol: str, period: str = "1mo"):
    """指定銘柄の株価時系列（OHLCV）をyfinance経由で取得する。"""
    ticker = yf.Ticker(ticker_symbol)
    return ticker.history(period=period)


def fetch_fundamentals(ticker_symbol: str) -> dict:
    """指定銘柄のファンダメンタルズ指標（PER・PBR・配当利回り等）を取得する。"""
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
    """指定銘柄に関連する最新ニュースを取得し、表示に必要な項目だけに整形する。"""
    ticker = yf.Ticker(ticker_symbol)
    news_items = ticker.news or []
    result = []
    for item in news_items[:limit]:
        # yfinanceのニュースレスポンスはネストしたcontent/provider構造のため、
        # 欠損があっても落ちないよう各階層でNone安全に取り出す
        content = item.get("content") or {}
        provider = content.get("provider") or {}
        link_info = content.get("clickThroughUrl") or content.get("canonicalUrl") or {}
        result.append(
            {
                "title": content.get("title"),
                "publisher": provider.get("displayName"),
                "link": link_info.get("url"),
            }
        )
    return result


def fetch_japanese_name(ticker_symbol: str) -> str | None:
    """Yahoo!ファイナンス（日本版）のページタイトルから日本語の銘柄名を取得する。

    yfinance（Yahoo Financeのグローバルデータ）は日本株の名前を英語でしか
    返さないため、日本語名専用にこの関数を使う。
    """
    url = f"https://finance.yahoo.co.jp/quote/{ticker_symbol}"
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        response.raise_for_status()
    except requests.RequestException:
        return None

    match = _YAHOO_JP_TITLE_RE.search(response.text)
    if not match:
        return None

    title = match.group(1)
    if "【" not in title:
        return None

    name = title.split("【", 1)[0].strip()
    return name or None
```

変更後:
```python
def fetch_price_history(ticker_symbol: str, period: str = "1mo"):
    """指定銘柄の株価時系列（OHLCV）をyfinance経由で取得する。"""
    logger.info("株価履歴リクエスト: ticker=%s period=%s", ticker_symbol, period)
    ticker = yf.Ticker(ticker_symbol)
    history = ticker.history(period=period)
    logger.info(
        "株価履歴レスポンス: ticker=%s data=%s",
        ticker_symbol,
        history.to_json(orient="records", date_format="iso"),
    )
    return history


def fetch_fundamentals(ticker_symbol: str) -> dict:
    """指定銘柄のファンダメンタルズ指標（PER・PBR・配当利回り等）を取得する。"""
    logger.info("fundamentalsリクエスト: ticker=%s", ticker_symbol)
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info
    result = {
        "ticker": ticker_symbol,
        "name": info.get("longName"),
        "trailing_pe": info.get("trailingPE"),
        "price_to_book": info.get("priceToBook"),
        "dividend_yield": info.get("dividendYield"),
        "market_cap": info.get("marketCap"),
    }
    logger.info("fundamentalsレスポンス: ticker=%s data=%s", ticker_symbol, result)
    return result


def fetch_news(ticker_symbol: str, limit: int = 5) -> list[dict]:
    """指定銘柄に関連する最新ニュースを取得し、表示に必要な項目だけに整形する。"""
    logger.info("newsリクエスト: ticker=%s limit=%s", ticker_symbol, limit)
    ticker = yf.Ticker(ticker_symbol)
    news_items = ticker.news or []
    result = []
    for item in news_items[:limit]:
        # yfinanceのニュースレスポンスはネストしたcontent/provider構造のため、
        # 欠損があっても落ちないよう各階層でNone安全に取り出す
        content = item.get("content") or {}
        provider = content.get("provider") or {}
        link_info = content.get("clickThroughUrl") or content.get("canonicalUrl") or {}
        result.append(
            {
                "title": content.get("title"),
                "publisher": provider.get("displayName"),
                "link": link_info.get("url"),
            }
        )
    logger.info("newsレスポンス: ticker=%s data=%s", ticker_symbol, result)
    return result


def fetch_japanese_name(ticker_symbol: str) -> str | None:
    """Yahoo!ファイナンス（日本版）のページタイトルから日本語の銘柄名を取得する。

    yfinance（Yahoo Financeのグローバルデータ）は日本株の名前を英語でしか
    返さないため、日本語名専用にこの関数を使う。
    """
    url = f"https://finance.yahoo.co.jp/quote/{ticker_symbol}"
    logger.info("日本語銘柄名リクエスト: url=%s", url)
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        response.raise_for_status()
    except requests.RequestException:
        logger.warning("日本語銘柄名取得失敗: url=%s", url)
        return None
    logger.info("日本語銘柄名レスポンス: url=%s body=%s", url, response.text)

    match = _YAHOO_JP_TITLE_RE.search(response.text)
    if not match:
        return None

    title = match.group(1)
    if "【" not in title:
        return None

    name = title.split("【", 1)[0].strip()
    return name or None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_stock_price_api.py -v`
Expected: 16 passed

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `uv run pytest -v`
Expected: 全テストPASS（`fetch_universe_fundamentals`が内部で`fetch_fundamentals`を呼ぶため、既存の`test_fetch_universe_fundamentals_*`テストでも新たにリクエスト/レスポンスログが出力されるが、アサーション対象ではないため失敗はしない）

- [ ] **Step 6: アプリを起動して動作確認**

Run: `uv run python -m streamlit run app.py`

確認項目（`app/logs/app.log`を確認する）:
1. バックテストタブで銘柄コードを指定して実行 → `株価履歴リクエスト: ticker=... period=...`の直後に`株価履歴レスポンス: ticker=... data=[...]`（OHLCVデータのJSON全件）が記録される
2. ポートフォリオタブで銘柄を追加し「レビューを生成」→ `fundamentalsリクエスト`/`fundamentalsレスポンス`、`newsリクエスト`/`newsレスポンス`、`Claude CLIリクエスト`/`Claude CLIレスポンス`が銘柄ごと・LLM呼び出しごとに記録される
3. スクリーニングタブで一括絞り込みを実行 → `fundamentalsリクエスト`/`fundamentalsレスポンス`が対象銘柄数だけ（最大226組）記録され、ログファイルが数百行増える（想定通りの挙動であることを確認）
4. 存在しない銘柄コード等でYahoo!ファイナンスへのリクエストが失敗するケースがあれば、`日本語銘柄名取得失敗: url=...`のWARNINGログが記録される

- [ ] **Step 7: Commit**

```bash
git add data_api/stock_price_api.py tests/test_stock_price_api.py
git commit -m "$(cat <<'EOF'
Log full request/response content for yfinance/Yahoo Finance calls

fetch_price_history, fetch_fundamentals, fetch_news, and
fetch_japanese_name now log what was requested and what came back,
including per-ticker calls inside 226-ticker batch operations. This
intentionally reverses the earlier decision to exclude per-ticker
functions from logging, per explicit request to prioritize full
traceability of external data over log volume.
EOF
)"
```

---

## Self-Review Notes

- **Spec coverage:** design docの表（`call_llm`／`fetch_price_history`／`fetch_fundamentals`／`fetch_news`／`fetch_japanese_name`）はTask 1・2で全てカバーしている。「レスポンスログは成功時のみ」「226銘柄一括でもログ対象に含める」という設計上の決定はGlobal Constraintsおよび各Taskの実装・コミットメッセージに明記した。
- **Placeholder scan:** 各Stepのコードは実際のコード（変更箇所は全文）。プレースホルダーなし。
- **Type consistency:** 既存の`logger`（`logging.getLogger(__name__)`）・`log_duration`のシグネチャをそのまま利用し、新規に追加するインターフェースはない。
