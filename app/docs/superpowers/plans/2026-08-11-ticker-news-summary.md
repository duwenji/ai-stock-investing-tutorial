# ticker_news本文（summary）保存・活用 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ticker_news`にyfinance由来の記事要約（`summary`）を保存し、AI総合コメント・Q&A回答用プロンプト・画面表示（日本語訳付き）の3箇所で活用する。

**Architecture:** (1) `TickerNews`モデルに`summary`列を追加し、既存DBには`_ensure_ticker_news_summary_column`でALTER TABLE追加する。(2) `data_api/stock_price_api.py`の`_fetch_news_from_yfinance`/`_insert_new_ticker_news`/`fetch_news`が`summary`を取得・保存・返却する。(3) `prompt_patterns/stock_detail.py`の`build_stock_detail_prompt`と`prompt_patterns/qa_routing.py`の`build_news_answer_prompt`が、見出しの下に`summary`（英文）を付記する。(4) 画面表示専用に、`stock_detail/detail.py`の`generate_stock_detail`が新規`build_news_summary_translation_prompt`で全記事の要約を1回の`call_llm`呼び出しで日本語に一括翻訳し、応答を`@@@`区切りで分割して各記事に`summary_ja`を追加する（件数不一致時はスキップし警告ログのみ）。(5) `app_tabs/shared.py`の関連ニュース一覧が、`summary_ja`（無ければ英文`summary`）をexpanderで表示する。

**Tech Stack:** Python, SQLAlchemy, pytest, yfinance, 既存の`data_api/llm_client.call_llm`（Claude Code CLI呼び出し）

## Global Constraints

- リンク先ページの全文スクレイピングは行わない（サイトごとの構造差・著作権リスクのため見送り。設計のスコープ外）。
- `summary`はDB保存・AIプロンプト投入時とも英語のまま（トリミングしない、翻訳しない）。翻訳するのは画面表示専用の`summary_ja`のみ。
- 既存に蓄積済みの`ticker_news`行への`summary`バックフィルは行わない（今後の新規記事から自然に蓄積）。
- Alembic等のマイグレーションツールは使わない。既存の`_add_column_if_missing`ヘルパー経由のALTER TABLEパターンに従う。
- Streamlit UI描画部分（`app_tabs/shared.py`）は既存コードベースの慣習上ユニットテスト対象外（Task 7で手動確認する）。

---

## File Structure

- Modify: `db/models.py` — `TickerNews`に`summary`列を追加
- Modify: `db/engine.py` — `_ensure_ticker_news_summary_column`を追加し`init_db`から呼ぶ
- Modify: `tests/test_db_engine.py` — 列追加の回帰テスト
- Modify: `data_api/stock_price_api.py` — `_fetch_news_from_yfinance`/`_insert_new_ticker_news`/`fetch_news`が`summary`を扱う
- Modify: `tests/test_stock_price_api.py` — フィクスチャ・アサーション更新
- Modify: `prompt_patterns/stock_detail.py` — `build_stock_detail_prompt`が要約を付記、`build_news_summary_translation_prompt`を追加
- Modify: `prompt_patterns/qa_routing.py` — `build_news_answer_prompt`が要約を付記
- Modify: `tests/test_stock_detail_prompt.py` / `tests/test_qa_routing.py` — 要約付記・翻訳プロンプトのテスト
- Modify: `stock_detail/detail.py` — `generate_stock_detail`が要約を一括翻訳し`summary_ja`をマージ
- Modify: `tests/test_stock_detail.py` — 翻訳マージのテスト
- Modify: `app_tabs/shared.py` — 関連ニュース一覧にexpanderで要約表示

---

### Task 1: DBスキーマに`summary`列を追加する

**Files:**
- Modify: `db/models.py`
- Modify: `db/engine.py`
- Modify: `tests/test_db_engine.py`

**Interfaces:**
- Produces: `TickerNews.summary: str | None`。`_ensure_ticker_news_summary_column(engine: Engine) -> None`（既存DBに列が無ければALTER TABLEで追加）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_db_engine.py`の末尾に追加（既存の`test_init_db_adds_sector_jp_column_to_existing_company_profiles_table`と同じ形。FKを既に持つ「アップグレード済みだがsummary列が無い」状態を再現するため、`FOREIGN KEY`句を明示する）:

```python
def test_init_db_adds_summary_column_to_existing_ticker_news_table(tmp_path):
    from sqlalchemy import text

    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with engine.connect() as connection:
        connection.execute(
            text(
                "CREATE TABLE ticker_news ("
                "id INTEGER PRIMARY KEY, ticker TEXT NOT NULL, title TEXT, "
                "publisher TEXT, link TEXT, fetched_at DATETIME, "
                "FOREIGN KEY(ticker) REFERENCES company_profiles (ticker))"
            )
        )
        connection.commit()

    init_db(engine)

    with engine.connect() as connection:
        columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(ticker_news)")).fetchall()
        }
    assert "summary" in columns
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_db_engine.py::test_init_db_adds_summary_column_to_existing_ticker_news_table -v`
Expected: FAIL（`summary`列が存在しないため`assert "summary" in columns`が失敗）

- [ ] **Step 3: `TickerNews`モデルに`summary`列を追加する**

`db/models.py`の`TickerNews`クラス（`link`列の直後）を変更:

```python
    link: Mapped[str | None] = mapped_column(nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime.datetime] = mapped_column(default=_utcnow)
```

- [ ] **Step 4: `db/engine.py`に列追加マイグレーションを実装する**

`_ensure_company_profile_sector_jp_column`の直後に追加:

```python
def _ensure_ticker_news_summary_column(engine: Engine) -> None:
    with engine.connect() as connection:
        existing_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(ticker_news)")).fetchall()
        }
        _add_column_if_missing(connection, "ticker_news", existing_columns, "summary", "TEXT")
        connection.commit()
```

`init_db`内の呼び出し順を変更（`_ensure_company_profile_sector_jp_column(engine)`の直後に追加）:

```python
    _ensure_market_data_foreign_keys(engine)
    _ensure_company_profile_sector_jp_column(engine)
    _ensure_ticker_news_summary_column(engine)
    _seed_default_company_profiles(engine)
```

`init_db`のdocstring末尾に一文追加:

```
ticker_newsにsummary列（yfinance由来の記事要約。ニュース活用強化に伴う追加）が
無ければ追加する。
```

- [ ] **Step 5: テストを実行して成功を確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_db_engine.py -v`
Expected: PASS（新規テストを含む全テスト）

- [ ] **Step 6: コミット**

```bash
git add app/db/models.py app/db/engine.py app/tests/test_db_engine.py
git commit -m "feat: ticker_newsにニュース要約(summary)列を追加"
```

---

### Task 2: yfinanceから要約を取得しDBに保存・返却する

**Files:**
- Modify: `data_api/stock_price_api.py`
- Modify: `tests/test_stock_price_api.py`

**Interfaces:**
- Consumes: Task 1の`TickerNews.summary`列。
- Produces: `_fetch_news_from_yfinance`が返す各dict・`fetch_news`が返す各dictに`"summary": str | None`キーが追加される。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_stock_price_api.py`の`FakeTicker.news`と`MissingNewsFieldsTicker.news`を変更:

```python
    @property
    def news(self):
        return [
            {
                "content": {
                    "title": "Headline 1",
                    "provider": {"displayName": "Pub"},
                    "clickThroughUrl": {"url": "https://example.com/1"},
                    "summary": "Summary text 1",
                }
            },
            {
                "content": {
                    "title": "Headline 2",
                    "provider": {"displayName": "Pub2"},
                    "clickThroughUrl": {"url": "https://example.com/2"},
                    "summary": "Summary text 2",
                }
            },
        ]


class MissingNewsFieldsTicker(FakeTicker):
    @property
    def news(self):
        return [{"content": {"title": "Headline only"}}]
```

`test_fetch_news_returns_title_publisher_and_link`と`test_fetch_news_handles_missing_nested_fields`を変更:

```python
def test_fetch_news_returns_title_publisher_link_and_summary(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    news = stock_price_api.fetch_news("7203.T", limit=1, session_factory=session_factory)
    assert news == [
        {
            "title": "Headline 1",
            "publisher": "Pub",
            "link": "https://example.com/1",
            "summary": "Summary text 1",
        }
    ]


def test_fetch_news_handles_missing_nested_fields(monkeypatch, tmp_path):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", MissingNewsFieldsTicker)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    news = stock_price_api.fetch_news("7203.T", limit=1, session_factory=session_factory)
    assert news == [
        {"title": "Headline only", "publisher": None, "link": None, "summary": None}
    ]
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_stock_price_api.py::test_fetch_news_returns_title_publisher_link_and_summary tests/test_stock_price_api.py::test_fetch_news_handles_missing_nested_fields -v`
Expected: FAIL（戻り値に`summary`キーが無いため辞書比較が失敗）

- [ ] **Step 3: `_fetch_news_from_yfinance`が`summary`を抽出するようにする**

`data_api/stock_price_api.py`の`_fetch_news_from_yfinance`内の`result.append(...)`を変更:

```python
        result.append(
            {
                "title": content.get("title"),
                "publisher": provider.get("displayName"),
                "link": link_info.get("url"),
                "summary": content.get("summary"),
            }
        )
```

- [ ] **Step 4: `_insert_new_ticker_news`が`summary`を保存するようにする**

`_insert_new_ticker_news`内の`TickerNews(...)`を変更:

```python
        session.add(
            TickerNews(
                ticker=ticker_symbol,
                title=item.get("title"),
                publisher=item.get("publisher"),
                link=link,
                summary=item.get("summary"),
            )
        )
```

- [ ] **Step 5: `fetch_news`の戻り値に`summary`を含める**

`fetch_news`内の戻り値リスト内包表記を変更:

```python
        return [
            {
                "title": row.title,
                "publisher": row.publisher,
                "link": row.link,
                "summary": row.summary,
            }
            for row in rows
        ]
```

- [ ] **Step 6: テストを実行して成功を確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_stock_price_api.py -v`
Expected: PASS（全テスト。特に重複排除系テストが`summary`追加後も無回帰であることを確認）

- [ ] **Step 7: コミット**

```bash
git add app/data_api/stock_price_api.py app/tests/test_stock_price_api.py
git commit -m "feat: ニュース取得でyfinanceのsummaryを保存・返却する"
```

---

### Task 3: AI総合コメント用プロンプトに要約を付記する

**Files:**
- Modify: `prompt_patterns/stock_detail.py`
- Modify: `tests/test_stock_detail_prompt.py`

**Interfaces:**
- Consumes: Task 2の`fetch_news`が返す`summary`キー付きdict。
- Produces: `build_stock_detail_prompt`の出力に、`summary`がある記事は見出し行の下に`  要約: {summary}`行が追加される（変更なし: 関数シグネチャ）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_stock_detail_prompt.py`に追加:

```python
def test_build_stock_detail_prompt_includes_news_summary_when_present():
    news = [{"title": "好決算を発表", "publisher": "日経", "summary": "Sales grew 20%."}]
    prompt = build_stock_detail_prompt("AAA.T", "エーエー株式会社", {}, {}, news)
    assert "要約: Sales grew 20%." in prompt


def test_build_stock_detail_prompt_omits_summary_line_when_absent():
    news = [{"title": "好決算を発表", "publisher": "日経"}]
    prompt = build_stock_detail_prompt("AAA.T", "エーエー株式会社", {}, {}, news)
    assert "要約:" not in prompt
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_stock_detail_prompt.py::test_build_stock_detail_prompt_includes_news_summary_when_present -v`
Expected: FAIL（`要約:`が出力に含まれない）

- [ ] **Step 3: `build_stock_detail_prompt`が要約を付記するようにする**

`prompt_patterns/stock_detail.py`の`build_stock_detail_prompt`直前にヘルパーを追加し、本体を変更:

```python
def _format_news_lines(news: list[dict]) -> str:
    # 見出しに続けて要約（あれば）を1行付記する。要約が無い記事は見出しのみ。
    lines = []
    for item in news:
        line = f"- {item.get('title')}"
        summary = item.get("summary")
        if summary:
            line += f"\n  要約: {summary}"
        lines.append(line)
    return "\n".join(lines) or "- (ニュースなし)"


def build_stock_detail_prompt(
    ticker: str, name: str | None, fundamentals: dict, technical: dict, news: list[dict]
) -> str:
    news_lines = _format_news_lines(news)
    label = f"{ticker}（{name}）" if name else ticker
    return (
        f"銘柄 {label} について、以下のファンダメンタルズ・テクニカル・ニュース見出しを踏まえて、"
        "投資家向けの総合分析コメントを日本語で3〜4文程度で作成してください。"
        "断定的な売買判断は含めないでください。\n\n"
        f"PER: {fundamentals.get('per')}\n"
        f"PBR: {fundamentals.get('pbr')}\n"
        f"配当利回り: {fundamentals.get('dividend_yield')}\n"
        f"テクニカルシグナル（移動平均線）: {technical.get('signal')}\n"
        f"RSI(14日、勢い): {technical.get('rsi')}（{technical.get('rsi_signal') or '不明'}）\n"
        f"ADX(14日、トレンドの強さ): {technical.get('adx')}（{technical.get('adx_signal') or '不明'}）\n"
        f"ATR(14日、値動きの大きさ、値幅%): {technical.get('atr_pct')}%"
        f"（{technical.get('atr_signal') or '不明'}）\n"
        f"OBV(出来高、値動きの裏付け): {technical.get('obv_signal') or '不明'}\n"
        f"直近ニュース見出し:\n{news_lines}\n"
    )
```

- [ ] **Step 4: テストを実行して成功を確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_stock_detail_prompt.py -v`
Expected: PASS（既存テストも含め全て）

- [ ] **Step 5: コミット**

```bash
git add app/prompt_patterns/stock_detail.py app/tests/test_stock_detail_prompt.py
git commit -m "feat: AI総合コメント用プロンプトにニュース要約を付記する"
```

---

### Task 4: Q&Aタブのニュース回答用プロンプトに要約を付記する

**Files:**
- Modify: `prompt_patterns/qa_routing.py`
- Modify: `tests/test_qa_routing.py`

**Interfaces:**
- Consumes: Task 2の`fetch_news`が返す`summary`キー付きdict。
- Produces: `build_news_answer_prompt`の出力に、`summary`がある記事は見出し行の下に`  要約: {summary}`行が追加される（変更なし: 関数シグネチャ）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_qa_routing.py`に追加:

```python
def test_build_news_answer_prompt_includes_summary_when_present():
    prompt = build_news_answer_prompt(
        "最近のニュースは？",
        [{"title": "好決算を発表", "publisher": "X", "summary": "Sales grew 20%."}],
    )
    assert "要約: Sales grew 20%." in prompt


def test_build_news_answer_prompt_omits_summary_line_when_absent():
    prompt = build_news_answer_prompt(
        "最近のニュースは？", [{"title": "好決算を発表", "publisher": "X"}]
    )
    assert "要約:" not in prompt
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_qa_routing.py::test_build_news_answer_prompt_includes_summary_when_present -v`
Expected: FAIL

- [ ] **Step 3: `build_news_answer_prompt`が要約を付記するようにする**

`prompt_patterns/qa_routing.py`の`build_news_answer_prompt`を変更:

```python
def _format_news_lines(news: list[dict]) -> str:
    lines = []
    for item in news:
        line = f"- {item['title']}"
        summary = item.get("summary")
        if summary:
            line += f"\n  要約: {summary}"
        lines.append(line)
    return "\n".join(lines) or "- (ニュースなし)"


def build_news_answer_prompt(question: str, news: list[dict]) -> str:
    lines = _format_news_lines(news)
    return (
        "以下は対象銘柄の直近ニュース見出しです"
        "（Python側で取得済みのため再取得は不要です）。\n\n"
        f"{lines}\n\n"
        "この情報をもとに、次の質問に日本語で答えてください。"
        "断定的な売買判断は含めないでください。\n\n"
        f"質問: {question}"
    )
```

- [ ] **Step 4: テストを実行して成功を確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_qa_routing.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add app/prompt_patterns/qa_routing.py app/tests/test_qa_routing.py
git commit -m "feat: Q&Aニュース回答用プロンプトにニュース要約を付記する"
```

---

### Task 5: 要約の日本語一括翻訳用プロンプト関数を追加する

**Files:**
- Modify: `prompt_patterns/stock_detail.py`
- Modify: `tests/test_stock_detail_prompt.py`

**Interfaces:**
- Produces: `build_news_summary_translation_prompt(summaries: list[str]) -> str`。入力の英文要約リストを、区切り文字`@@@`で連結し、同じ順序・同じ件数で日本語訳を返すよう指示するプロンプトを組み立てる。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_stock_detail_prompt.py`に追加（importに`build_news_summary_translation_prompt`を追加）:

```python
from prompt_patterns.stock_detail import (
    build_company_profile_prompt,
    build_news_summary_translation_prompt,
    build_stock_detail_prompt,
)


def test_build_news_summary_translation_prompt_includes_summaries_and_separator():
    prompt = build_news_summary_translation_prompt(["Summary A", "Summary B"])
    assert "Summary A" in prompt
    assert "Summary B" in prompt
    assert "@@@" in prompt
    assert "日本語に翻訳してください" in prompt
    assert "同じ順序・同じ件数" in prompt
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_stock_detail_prompt.py::test_build_news_summary_translation_prompt_includes_summaries_and_separator -v`
Expected: FAIL（`ImportError`: `build_news_summary_translation_prompt`が存在しない）

- [ ] **Step 3: `build_news_summary_translation_prompt`を実装する**

`prompt_patterns/stock_detail.py`の末尾に追加:

```python
def build_news_summary_translation_prompt(summaries: list[str]) -> str:
    # 画面表示専用の日本語訳を1回のLLM呼び出しでまとめて生成するためのプロンプト。
    # 区切り文字@@@で入力と同じ順序・同じ件数の翻訳文を返すよう厳密に指示する
    # （呼び出し元が応答を分割して各記事に割り当てるため、件数のズレは致命的）。
    separator = "@@@"
    joined = f"\n{separator}\n".join(summaries)
    return (
        "以下は英文のニュース要約です。各要約を日本語に翻訳してください。\n"
        f"翻訳文の間は区切り文字「{separator}」だけの行を挟み、"
        "入力と同じ順序・同じ件数で出力してください。"
        "翻訳文以外の説明や前置きは出力しないでください。\n\n"
        f"{joined}"
    )
```

- [ ] **Step 4: テストを実行して成功を確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_stock_detail_prompt.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add app/prompt_patterns/stock_detail.py app/tests/test_stock_detail_prompt.py
git commit -m "feat: ニュース要約の日本語一括翻訳用プロンプトを追加"
```

---

### Task 6: `generate_stock_detail`で要約を一括翻訳し`summary_ja`をマージする

**Files:**
- Modify: `stock_detail/detail.py`
- Modify: `tests/test_stock_detail.py`

**Interfaces:**
- Consumes: Task 5の`build_news_summary_translation_prompt(summaries: list[str]) -> str`、既存の`call_llm(prompt: str) -> str`。
- Produces: `generate_stock_detail`が返すpayloadの`news`各要素に、翻訳できた場合のみ`"summary_ja": str`キーが追加される（翻訳対象が無い場合・件数不一致の場合は追加されない）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_stock_detail.py`に追加（`import logging`は既存）:

```python
def test_generate_stock_detail_translates_news_summaries_and_merges_summary_ja(tmp_path):
    def fake_call_llm(prompt):
        if "日本語に翻訳してください" in prompt:
            return "翻訳文1@@@翻訳文2"
        if "市場での立ち位置" in prompt:
            return "プロフィール要約"
        return "総合コメント"

    result = generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=fake_call_llm,
        fetch_price_history=lambda ticker, period: _fake_history(),
        fetch_news=lambda ticker: [
            {
                "title": "ニュース1",
                "publisher": "社1",
                "link": "http://example.com/1",
                "summary": "Summary 1",
            },
            {
                "title": "ニュース2",
                "publisher": "社2",
                "link": "http://example.com/2",
                "summary": "Summary 2",
            },
        ],
        analyze_fundamentals=lambda ticker: {"per": 12.0, "pbr": 1.1, "dividend_yield": 2.5},
        analyze_technical=lambda history: {"ma_short": 101.0, "ma_long": 100.0, "signal": "強気"},
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
        },
    )

    assert result["news"][0]["summary_ja"] == "翻訳文1"
    assert result["news"][1]["summary_ja"] == "翻訳文2"


def test_generate_stock_detail_skips_translation_call_when_no_news_have_summary(tmp_path):
    def fake_call_llm(prompt):
        assert "日本語に翻訳してください" not in prompt
        if "市場での立ち位置" in prompt:
            return "プロフィール要約"
        return "総合コメント"

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
            "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
        },
    )

    assert "summary_ja" not in result["news"][0]


def test_generate_stock_detail_leaves_summary_ja_unset_when_translation_count_mismatches(
    tmp_path, caplog
):
    def fake_call_llm(prompt):
        if "日本語に翻訳してください" in prompt:
            return "翻訳文1"  # 2件を渡したのに1件しか返さない異常応答を模す
        if "市場での立ち位置" in prompt:
            return "プロフィール要約"
        return "総合コメント"

    with caplog.at_level(logging.WARNING, logger="stock_detail.detail"):
        result = generate_stock_detail(
            "AAA.T",
            "エーエー株式会社",
            tmp_path,
            call_llm=fake_call_llm,
            fetch_price_history=lambda ticker, period: _fake_history(),
            fetch_news=lambda ticker: [
                {
                    "title": "ニュース1",
                    "publisher": "社1",
                    "link": "http://example.com/1",
                    "summary": "Summary 1",
                },
                {
                    "title": "ニュース2",
                    "publisher": "社2",
                    "link": "http://example.com/2",
                    "summary": "Summary 2",
                },
            ],
            analyze_fundamentals=lambda ticker: {"per": 12.0, "pbr": 1.1, "dividend_yield": 2.5},
            analyze_technical=lambda history: {
                "ma_short": 101.0, "ma_long": 100.0, "signal": "強気"
            },
            fetch_company_profile=lambda ticker: {
                "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
            },
        )

    assert "summary_ja" not in result["news"][0]
    assert "summary_ja" not in result["news"][1]
    assert "一致しませんでした" in caplog.text
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_stock_detail.py -k translat -v`
Expected: FAIL（`summary_ja`が存在しない／翻訳呼び出しが発生しない）

- [ ] **Step 3: `generate_stock_detail`に翻訳マージ処理を追加する**

`stock_detail/detail.py`のimportを変更:

```python
from prompt_patterns.stock_detail import (
    build_company_profile_prompt,
    build_news_summary_translation_prompt,
    build_stock_detail_prompt,
)
```

`news = fetch_news(ticker)`の直後（`company_profile = fetch_company_profile(ticker)`の前）に追加:

```python
        news = fetch_news(ticker)

        # 画面表示専用に、要約(summary)がある記事だけをまとめて1回のLLM呼び出しで
        # 日本語訳する。件数がズレた場合（LLMが指示通りの件数を返さなかった場合）は
        # 誤った記事に翻訳を割り当てるリスクを避け、summary_jaを付けずに諦める
        # （画面表示側は summary_ja が無ければ英文summaryにフォールバックする）。
        indices_with_summary = [i for i, item in enumerate(news) if item.get("summary")]
        if indices_with_summary:
            translation_prompt = build_news_summary_translation_prompt(
                [news[i]["summary"] for i in indices_with_summary]
            )
            translated_text = call_llm(translation_prompt)
            translated_summaries = [part.strip() for part in translated_text.split("@@@")]
            if len(translated_summaries) == len(indices_with_summary):
                for index, translated in zip(indices_with_summary, translated_summaries):
                    news[index]["summary_ja"] = translated
            else:
                logger.warning(
                    "ニュース要約の翻訳件数が入力件数と一致しませんでした"
                    "（入力%d件、応答%d件）: ticker=%s",
                    len(indices_with_summary),
                    len(translated_summaries),
                    ticker,
                )

        company_profile = fetch_company_profile(ticker)
```

- [ ] **Step 4: テストを実行して成功を確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_stock_detail.py -v`
Expected: PASS（新規3件＋既存の全テスト。既存テストは`fetch_news`が`summary`無しのdictを返すため翻訳呼び出しが発生せず無回帰）

- [ ] **Step 5: コミット**

```bash
git add app/stock_detail/detail.py app/tests/test_stock_detail.py
git commit -m "feat: 銘柄詳細生成でニュース要約を一括翻訳しsummary_jaを付与する"
```

---

### Task 7: 画面の関連ニュース一覧に要約表示を追加する

**Files:**
- Modify: `app_tabs/shared.py`

**Interfaces:**
- Consumes: Task 2の`summary`、Task 6の`summary_ja`（`detail["news"]`の各dict）。

- [ ] **Step 1: 関連ニュース一覧にexpanderを追加する**

`app_tabs/shared.py`の関連ニュース一覧（`for item in news_items:`ブロック）を変更:

```python
    for item in news_items:
        title = item.get("title") or "(タイトルなし)"
        publisher = item.get("publisher") or "?"
        link = item.get("link")
        if link:
            st.markdown(f"- [{title}]({link})（{publisher}）")
        else:
            st.markdown(f"- {title}（{publisher}）")
        # 要約は日本語訳（summary_ja）を優先し、翻訳が無ければ英文原文（summary）を表示する
        summary_text = item.get("summary_ja") or item.get("summary")
        if summary_text:
            with st.expander("要約を見る"):
                st.write(summary_text)
```

- [ ] **Step 2: アプリを起動し、手動で確認する**

Run: `cd app && .venv/Scripts/streamlit.exe run app.py`

- ログインし、銘柄詳細画面を開く。
- 「関連ニュース」一覧で、要約を持つ記事に「要約を見る」expanderが表示され、展開すると日本語訳（LLM呼び出しが成功する環境の場合）または英文要約（フォールバック時）が表示されることを確認する。
- 要約を持たない記事（`summary`が無い旧データ等）には従来通りexpanderが表示されないことを確認する。
- 起動したStreamlitプロセスを停止する（Ctrl+C）。

- [ ] **Step 3: 既存テストスイート全体を実行し、無回帰を確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest -v`
Expected: PASS（全テスト）

- [ ] **Step 4: コミット**

```bash
git add app/app_tabs/shared.py
git commit -m "feat: 関連ニュース一覧に要約表示（日本語訳優先）を追加"
```
