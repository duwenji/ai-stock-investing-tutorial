# ポートフォリオ銘柄名オートコンプリート & ニュース参照機能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 保有銘柄ポートフォリオに銘柄名オートコンプリート機能を追加し、ポートフォリオレビューが提示するニュースセンチメント判定の根拠となった収集ニュースをUI上で参照できるようにする。

**Architecture:** 既存の `screening/universe.py` にティッカー→銘柄名の辞書を追加し、新規 `portfolio_management/ticker_names.py` でUNIVERSE＋保有銘柄の候補統合ロジックを純粋関数として実装する。`app.py` はその関数を呼び出し、検索ボックス＋読み取り専用の銘柄名列というUIを構築する（ロジックを持たせない既存方針を踏襲）。ニュース参照は `fetch_news` にリンクフィールドを追加し、ポートフォリオレビューのキャッシュペイロードをレポート本文単体からレポート＋ニュース＋センチメントのJSON構造に変更することで実現する。

**Tech Stack:** Python, Streamlit, pandas, yfinance, pytest（`uv run pytest -v`）

## Global Constraints

- `screening.UNIVERSE`（`list[str]`）のインターフェースは変更しない（スクリーニング機能が依存しているため）。
- `holdings.json` のスキーマ `[{"ticker": str, "shares": int, "cost": float}, ...]` は変更しない（銘柄名は保存せず毎回導出する）。
- `common/cache.py`（`read_cache`/`write_cache`）は文字列を扱う汎用ヘルパーのまま変更しない。JSONのシリアライズ/デシリアライズは呼び出し側（`app.py`）で行う。
- `app.py` はロジックを持たせず、テスト可能な関数への薄い呼び出しに留める既存方針を踏襲する（プロジェクトREADME・既存設計書に明記された方針）。
- テストコマンドは `uv run pytest -v`。アプリ起動確認は `uv run streamlit run app.py`。

参照仕様書: [2026-07-19-portfolio-name-autocomplete-and-news-reference-design.md](../specs/2026-07-19-portfolio-name-autocomplete-and-news-reference-design.md)

---

### Task 1: UNIVERSE_NAMES辞書の追加

**Files:**
- Modify: `screening/universe.py`
- Test: `tests/test_universe.py`

**Interfaces:**
- Produces: `screening.universe.UNIVERSE_NAMES: dict[str, str]`（ティッカー→銘柄名、`UNIVERSE` の全44ティッカーを網羅）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_universe.py` の先頭のimportを次のように変更する:

```python
from screening.universe import UNIVERSE, UNIVERSE_NAMES
```

ファイル末尾に以下のテストを追加する:

```python
def test_universe_names_cover_all_tickers():
    assert set(UNIVERSE_NAMES.keys()) == set(UNIVERSE)


def test_universe_names_have_non_empty_values():
    assert all(isinstance(name, str) and name for name in UNIVERSE_NAMES.values())
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `uv run pytest tests/test_universe.py -v`
Expected: `test_universe_names_cover_all_tickers` と `test_universe_names_have_non_empty_values` が `ImportError: cannot import name 'UNIVERSE_NAMES'` で失敗する。

- [ ] **Step 3: 実装する**

`screening/universe.py` の `UNIVERSE` リスト定義の下に、以下を追加する（コメントにある既存の銘柄名をそのまま辞書化）:

```python
UNIVERSE_NAMES: dict[str, str] = {
    "7203.T": "トヨタ自動車",
    "7267.T": "ホンダ",
    "7201.T": "日産自動車",
    "6758.T": "ソニーグループ",
    "6861.T": "キーエンス",
    "6501.T": "日立製作所",
    "6503.T": "三菱電機",
    "6752.T": "パナソニックHD",
    "6902.T": "デンソー",
    "6971.T": "京セラ",
    "8035.T": "東京エレクトロン",
    "6273.T": "SMC",
    "9432.T": "NTT",
    "9433.T": "KDDI",
    "9434.T": "ソフトバンク",
    "9984.T": "ソフトバンクグループ",
    "8306.T": "三菱UFJフィナンシャル・グループ",
    "8316.T": "三井住友フィナンシャルグループ",
    "8411.T": "みずほフィナンシャルグループ",
    "8766.T": "東京海上HD",
    "8058.T": "三菱商事",
    "8031.T": "三井物産",
    "8001.T": "伊藤忠商事",
    "2914.T": "JT",
    "4502.T": "武田薬品工業",
    "4519.T": "中外製薬",
    "4568.T": "第一三共",
    "3382.T": "セブン&アイ・ホールディングス",
    "9843.T": "ニトリHD",
    "8267.T": "イオン",
    "4901.T": "富士フイルムHD",
    "7751.T": "キヤノン",
    "7011.T": "三菱重工業",
    "6301.T": "コマツ",
    "5108.T": "ブリヂストン",
    "4063.T": "信越化学工業",
    "6367.T": "ダイキン工業",
    "9020.T": "JR東日本",
    "9022.T": "JR東海",
    "9101.T": "日本郵船",
    "8801.T": "三井不動産",
    "8802.T": "三菱地所",
    "6098.T": "リクルートHD",
    "4661.T": "オリエンタルランド",
}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run pytest tests/test_universe.py -v`
Expected: 全テストPASS

- [ ] **Step 5: コミット**

```bash
git add screening/universe.py tests/test_universe.py
git commit -m "feat: add UNIVERSE_NAMES ticker-to-name mapping"
```

---

### Task 2: 候補統合ロジック（build_candidate_names）の実装

**Files:**
- Create: `portfolio_management/ticker_names.py`
- Test: `tests/test_ticker_names.py`

**Interfaces:**
- Consumes: `screening.universe.UNIVERSE_NAMES: dict[str, str]`（Task 1で作成）、`data_api.stock_price_api.fetch_fundamentals(ticker_symbol: str) -> dict`（既存、`"name"` キーを含む）
- Produces: `portfolio_management.ticker_names.build_candidate_names(holdings: list[dict], universe_names: dict[str, str] = UNIVERSE_NAMES, fetch_fundamentals=default_fetch_fundamentals) -> dict[str, str]`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_ticker_names.py` を新規作成:

```python
from portfolio_management.ticker_names import build_candidate_names


def test_returns_universe_names_when_no_extra_holdings():
    result = build_candidate_names([], universe_names={"7203.T": "トヨタ自動車"})
    assert result == {"7203.T": "トヨタ自動車"}


def test_resolves_names_for_holdings_outside_universe():
    holdings = [{"ticker": "AAA.T", "shares": 10, "cost": 100.0}]

    def fake_fetch_fundamentals(ticker):
        assert ticker == "AAA.T"
        return {"name": "Fake Corp"}

    result = build_candidate_names(
        holdings,
        universe_names={"7203.T": "トヨタ自動車"},
        fetch_fundamentals=fake_fetch_fundamentals,
    )
    assert result == {"7203.T": "トヨタ自動車", "AAA.T": "Fake Corp"}


def test_excludes_holdings_whose_name_cannot_be_resolved():
    holdings = [{"ticker": "BBB.T", "shares": 10, "cost": 100.0}]

    result = build_candidate_names(
        holdings,
        universe_names={},
        fetch_fundamentals=lambda ticker: {"name": None},
    )
    assert result == {}


def test_universe_name_is_not_overwritten_by_holding_lookup():
    holdings = [{"ticker": "7203.T", "shares": 10, "cost": 100.0}]

    def fake_fetch_fundamentals(ticker):
        raise AssertionError("universe内のティッカーはfetch_fundamentalsを呼ばない")

    result = build_candidate_names(
        holdings,
        universe_names={"7203.T": "トヨタ自動車"},
        fetch_fundamentals=fake_fetch_fundamentals,
    )
    assert result == {"7203.T": "トヨタ自動車"}
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `uv run pytest tests/test_ticker_names.py -v`
Expected: `ModuleNotFoundError: No module named 'portfolio_management.ticker_names'` で全件失敗する。

- [ ] **Step 3: 実装する**

`portfolio_management/ticker_names.py` を新規作成:

```python
from data_api.stock_price_api import fetch_fundamentals as default_fetch_fundamentals
from screening.universe import UNIVERSE_NAMES


def build_candidate_names(
    holdings: list[dict],
    universe_names: dict[str, str] = UNIVERSE_NAMES,
    fetch_fundamentals=default_fetch_fundamentals,
) -> dict[str, str]:
    candidates = dict(universe_names)
    for holding in holdings:
        ticker = holding.get("ticker")
        if not ticker or ticker in candidates:
            continue
        name = fetch_fundamentals(ticker).get("name")
        if name:
            candidates[ticker] = name
    return candidates
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run pytest tests/test_ticker_names.py -v`
Expected: 全テストPASS

- [ ] **Step 5: コミット**

```bash
git add portfolio_management/ticker_names.py tests/test_ticker_names.py
git commit -m "feat: add build_candidate_names for ticker name lookup"
```

---

### Task 3: fetch_newsにlinkフィールドを追加

**Files:**
- Modify: `data_api/stock_price_api.py`
- Test: `tests/test_stock_price_api.py`

**Interfaces:**
- Produces: `fetch_news(ticker_symbol: str, limit: int = 5) -> list[dict]` の各要素に `"link": str | None` を追加（既存の `"title"`, `"publisher"` に加える）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_stock_price_api.py` の `FakeTicker.news` プロパティを次のように変更する:

```python
    @property
    def news(self):
        return [
            {"title": "Headline 1", "publisher": "Pub", "link": "https://example.com/1"},
            {"title": "Headline 2", "publisher": "Pub2", "link": "https://example.com/2"},
        ]
```

`test_fetch_news_returns_title_and_publisher` を次のテストで置き換える:

```python
def test_fetch_news_returns_title_publisher_and_link(monkeypatch):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    news = stock_price_api.fetch_news("7203.T", limit=1)
    assert news == [
        {"title": "Headline 1", "publisher": "Pub", "link": "https://example.com/1"}
    ]
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `uv run pytest tests/test_stock_price_api.py -v`
Expected: `test_fetch_news_returns_title_publisher_and_link` が `AssertionError`（`link` キーが結果に含まれず辞書が一致しない）で失敗する。

- [ ] **Step 3: 実装する**

`data_api/stock_price_api.py` の `fetch_news` を次のように変更する:

```python
def fetch_news(ticker_symbol: str, limit: int = 5) -> list[dict]:
    ticker = yf.Ticker(ticker_symbol)
    news_items = ticker.news or []
    return [
        {
            "title": item.get("title"),
            "publisher": item.get("publisher"),
            "link": item.get("link"),
        }
        for item in news_items[:limit]
    ]
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run pytest tests/test_stock_price_api.py -v`
Expected: 全テストPASS

- [ ] **Step 5: コミット**

```bash
git add data_api/stock_price_api.py tests/test_stock_price_api.py
git commit -m "feat: include article link in fetch_news results"
```

---

### Task 4: ポートフォリオタブに検索追加ボックスと銘柄名列を実装

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: `portfolio_management.ticker_names.build_candidate_names`（Task 2）、`data_api.stock_price_api.fetch_fundamentals`（既存）
- Produces: `st.session_state["holdings_rows"]: list[dict]`（このタブ内の以降の処理・Task 5が参照する編集中の保有銘柄一覧）

このタスクはStreamlit UIのみの変更であり、プロジェクトの既存方針（`app.py` はロジックを持たせずUI表示に専念、UI自体は自動テスト対象外）に従い、自動テストではなく手動確認で検証する。

- [ ] **Step 1: importを追加する**

`app.py` の以下の行:

```python
from data_api.stock_price_api import fetch_news, fetch_price_history, fetch_universe_fundamentals
from portfolio_management.review import generate_portfolio_review
from portfolio_management.storage import load_holdings, save_holdings
```

を次のように変更する:

```python
from data_api.stock_price_api import (
    fetch_fundamentals,
    fetch_news,
    fetch_price_history,
    fetch_universe_fundamentals,
)
from portfolio_management.review import generate_portfolio_review
from portfolio_management.storage import load_holdings, save_holdings
from portfolio_management.ticker_names import build_candidate_names
```

- [ ] **Step 2: キャッシュ付き名前解決関数をモジュールレベルに追加する**

`CACHE_DIR = DATA_DIR / "cache"` の行の直後に追加する:

```python
CACHE_DIR = DATA_DIR / "cache"


@st.cache_data(ttl=60 * 60 * 24)
def _cached_fetch_fundamentals(ticker: str) -> dict:
    return fetch_fundamentals(ticker)
```

- [ ] **Step 3: ポートフォリオタブの保有銘柄編集部分を置き換える**

`with tab_portfolio:` ブロック内の、以下の既存コード（`st.header` の直後から `edited_df = st.data_editor(...)` までの3行）:

```python
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
```

を次のように置き換える:

```python
with tab_portfolio:
    st.header("保有銘柄ポートフォリオ")

    if "holdings_rows" not in st.session_state:
        st.session_state["holdings_rows"] = load_holdings(HOLDINGS_PATH) or [
            {"ticker": "", "shares": 0, "cost": 0.0}
        ]

    candidate_names = build_candidate_names(
        st.session_state["holdings_rows"], fetch_fundamentals=_cached_fetch_fundamentals
    )

    st.subheader("銘柄を検索して追加")
    search_col, add_col = st.columns([4, 1])
    with search_col:
        search_options = [""] + [
            f"{ticker} {name}" for ticker, name in sorted(candidate_names.items())
        ]
        picked = st.selectbox(
            "銘柄コードまたは銘柄名で検索",
            search_options,
            key="ticker_search_box",
            label_visibility="collapsed",
        )
    with add_col:
        add_clicked = st.button("追加")

    if add_clicked and picked:
        picked_ticker = picked.split(" ", 1)[0]
        existing_tickers = {row.get("ticker") for row in st.session_state["holdings_rows"]}
        if picked_ticker in existing_tickers:
            st.info(f"{picked_ticker} は既に一覧にあります。")
        else:
            st.session_state["holdings_rows"].append(
                {"ticker": picked_ticker, "shares": 0, "cost": 0.0}
            )

    display_df = pd.DataFrame(st.session_state["holdings_rows"])
    display_df["銘柄名"] = display_df["ticker"].map(
        lambda ticker: candidate_names.get(ticker, "")
    )
    display_df = display_df[["ticker", "銘柄名", "shares", "cost"]]

    edited_df = st.data_editor(
        display_df,
        num_rows="dynamic",
        key="holdings_editor",
        column_config={
            "銘柄名": st.column_config.TextColumn("銘柄名", disabled=True),
        },
    )

    holdings = load_holdings(HOLDINGS_PATH)

    if st.button("保有銘柄を保存"):
        new_holdings = [
            {"ticker": row["ticker"], "shares": row["shares"], "cost": row["cost"]}
            for row in edited_df.to_dict(orient="records")
            if row.get("ticker")
        ]
        save_holdings(HOLDINGS_PATH, new_holdings)
        st.session_state["holdings_rows"] = new_holdings
        st.success("保存しました。")
        holdings = new_holdings
```

（この直後に続く `force_regenerate = st.checkbox(...)` 以降は変更しない。）

- [ ] **Step 4: 既存テストが壊れていないことを確認**

Run: `uv run pytest -v`
Expected: 全テストPASS（`app.py` 自体にユニットテストは無いが、他モジュールに影響がないことを確認する）

- [ ] **Step 5: 手動確認**

Run: `uv run streamlit run app.py`

ブラウザで以下を確認する:
1. ポートフォリオタブの表の上に「銘柄を検索して追加」が表示され、"7203.T トヨタ自動車" のような候補がドロップダウンに出る。
2. 候補を選んで「追加」を押すと、表に新しい行（株数0・取得単価0.0）が追加される。
3. 表の「銘柄名」列が、UNIVERSE内のティッカーに対して自動的に銘柄名を表示する（読み取り専用で編集不可）。
4. 「保有銘柄を保存」を押すと `data/holdings.json` に `ticker/shares/cost` のみが保存され、「銘柄名」キーは含まれない。

- [ ] **Step 6: コミット**

```bash
git add app.py
git commit -m "feat: add ticker name autocomplete to portfolio holdings editor"
```

---

### Task 5: ポートフォリオレビューに参照ニュースを表示する

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: `fetch_news(ticker) -> list[dict]`（Task 3で `link` フィールド追加済み）、`research_news_batch(news_by_ticker, call_llm) -> dict[str, dict]`（既存）
- Produces: `common/cache.py` 経由で保存されるポートフォリオレビューキャッシュのペイロード形式を `{"report": str, "news_by_ticker": dict, "news_sentiment_by_ticker": dict}` のJSON文字列に変更する。

このタスクもUI変更が中心のため、Task 4と同様に手動確認で検証する。

- [ ] **Step 1: レビュー生成ブロックを置き換える**

`app.py` 内の以下の既存コード（`if holdings and st.button("レビューを生成"):` から `st.markdown(report)` まで）:

```python
    if holdings and st.button("レビューを生成"):
        cache_key = "portfolio-review-" + hashlib.sha256(
            "-".join(f"{h['ticker']}:{h['shares']}:{h['cost']}" for h in holdings).encode("utf-8")
        ).hexdigest()[:12]
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
```

を次のように置き換える:

```python
    if holdings and st.button("レビューを生成"):
        cache_key = "portfolio-review-" + hashlib.sha256(
            "-".join(f"{h['ticker']}:{h['shares']}:{h['cost']}" for h in holdings).encode("utf-8")
        ).hexdigest()[:12]
        cached_payload = None if force_regenerate else read_cache(CACHE_DIR, cache_key)

        if cached_payload is not None:
            payload = json.loads(cached_payload)
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
            payload = {
                "report": report,
                "news_by_ticker": news_by_ticker,
                "news_sentiment_by_ticker": news_sentiment_by_ticker,
            }
            write_cache(CACHE_DIR, cache_key, json.dumps(payload, ensure_ascii=False))

        st.markdown(payload["report"])

        st.subheader("参照ニュース（センチメント判定の元データ）")
        for holding in holdings:
            ticker = holding["ticker"]
            sentiment_info = payload["news_sentiment_by_ticker"].get(ticker, {})
            sentiment_label = sentiment_info.get("sentiment") or "不明"
            news_items = payload["news_by_ticker"].get(ticker, [])
            with st.expander(f"{ticker} の参照ニュース（センチメント: {sentiment_label}）"):
                if not news_items:
                    st.write("ニュースが取得できませんでした。")
                for item in news_items:
                    title = item.get("title") or "(タイトルなし)"
                    publisher = item.get("publisher") or "?"
                    link = item.get("link")
                    if link:
                        st.markdown(f"- [{title}]({link})（{publisher}）")
                    else:
                        st.markdown(f"- {title}（{publisher}）")
```

- [ ] **Step 2: 既存テストが壊れていないことを確認**

Run: `uv run pytest -v`
Expected: 全テストPASS

- [ ] **Step 3: 手動確認**

Run: `uv run streamlit run app.py`

ブラウザで以下を確認する:
1. 保有銘柄を1件以上登録した状態で「レビューを生成」を押し、レポートが表示されること。
2. レポートの下に「参照ニュース（センチメント判定の元データ）」の見出しと、銘柄ごとの折りたたみ欄が表示されること。
3. 各折りたたみ欄のタイトルに `センチメント: ...` が表示され、展開するとニュース見出し・発行元の一覧が表示されること。リンクがある場合はタイトルがクリック可能なリンクになっていること。
4. 「キャッシュを無視して再生成する」のチェックを外した状態で再度「レビューを生成」を押すと、同日中はキャッシュから即座に同じレポート・参照ニュースが再表示されること（`data/cache/` 内のファイルがJSON形式になっていることも確認する）。

- [ ] **Step 4: コミット**

```bash
git add app.py
git commit -m "feat: show reference news behind sentiment in portfolio review"
```

---

## 完了確認

- [ ] `uv run pytest -v` が全件PASSする
- [ ] `uv run streamlit run app.py` でポートフォリオタブの検索追加・銘柄名列・参照ニュースが期待通り動作する
