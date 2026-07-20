# 銘柄詳細ダイアログ（表クリックで詳細表示） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** スクリーニング結果表・一括バックテストのランキング表の行クリック、およびポートフォリオの保有銘柄表の「詳細」ボタンから、銘柄詳細情報（株価チャート・ファンダメンタルズ・テクニカル・ニュース・AI総合分析コメント）をモーダルダイアログで表示できるようにする。

**Architecture:** データ取得・分析・AI総合コメント生成のオーケストレーションを新規モジュール `stock_detail/detail.py` に集約し、既存の `data_api`/`analysis_agents`/`common/cache.py` をそのまま再利用する。プロンプト生成は既存パターンに従い `prompt_patterns/stock_detail.py` に置く。`app.py` には `@st.dialog` で装飾した共通のダイアログ関数と、行選択イベントをダイアログ表示に変換する共通ヘルパーを追加し、3つのタブから呼び出す。

**Tech Stack:** Python 3.14, Streamlit 1.59.2（`st.dataframe` の `on_select`/`selection_mode` による行クリック選択、`st.dialog` によるモーダル）, pandas, pytest。

## Global Constraints

- インストール済み Streamlit は 1.59.2。`st.data_editor` は `on_select` 非対応のため、ポートフォリオタブの保有銘柄表（`st.data_editor`）は行クリックではなく行ごとの「詳細」ボタン方式とする。
- 対象は3表のみ: スクリーニング結果表、一括バックテストのランキング表（行クリック）、ポートフォリオの保有銘柄表（詳細ボタン）。バックテストタブの単一銘柄比較表は対象外。
- 日次キャッシュは既存 `common/cache.py`（`read_cache`/`write_cache`、キーは日付付きファイル名で自動管理）をそのまま使う。銘柄詳細のキャッシュキーは `f"stock-detail-{ticker}"`。
- 新規関数は既存コードベースの DI（依存注入）パターン（例: `fetch_universe_fundamentals(tickers, cache_dir, fetch_fundamentals=fetch_fundamentals)`）を踏襲し、`call_llm` や各 `fetch_*`/`analyze_*` をデフォルト引数として注入可能にする。
- `app.py` のUI部分は既存方針通り自動テスト対象外（`tests/` にはロジックモジュールのみのテストを追加する）。
- 設計書: [docs/superpowers/specs/2026-07-20-stock-detail-dialog-design.md](../specs/2026-07-20-stock-detail-dialog-design.md)

---

## Task 1: プロンプト生成 `prompt_patterns/stock_detail.py`

**Files:**
- Create: `prompt_patterns/stock_detail.py`
- Test: `tests/test_stock_detail_prompt.py`

**Interfaces:**
- Consumes: なし（`fundamentals`/`technical`/`news` は呼び出し側が渡す素朴な dict/list）
- Produces: `build_stock_detail_prompt(ticker: str, name: str | None, fundamentals: dict, technical: dict, news: list[dict]) -> str`（Task 2 が消費する）

- [ ] **Step 1: Write the failing tests**

`tests/test_stock_detail_prompt.py` を新規作成する。

```python
from prompt_patterns.stock_detail import build_stock_detail_prompt


def test_build_stock_detail_prompt_includes_ticker_name_and_facts():
    fundamentals = {"per": 12.0, "pbr": 1.1, "dividend_yield": 2.5}
    technical = {"signal": "強気"}
    news = [{"title": "好決算を発表", "publisher": "日経", "link": "https://example.com/1"}]

    prompt = build_stock_detail_prompt("AAA.T", "エーエー株式会社", fundamentals, technical, news)

    assert "AAA.T" in prompt
    assert "エーエー株式会社" in prompt
    assert "12.0" in prompt
    assert "1.1" in prompt
    assert "2.5" in prompt
    assert "強気" in prompt
    assert "好決算を発表" in prompt


def test_build_stock_detail_prompt_omits_name_when_none():
    prompt = build_stock_detail_prompt("AAA.T", None, {}, {}, [])
    assert "AAA.T" in prompt
    assert "（None）" not in prompt


def test_build_stock_detail_prompt_shows_placeholder_when_no_news():
    prompt = build_stock_detail_prompt("AAA.T", "エーエー株式会社", {}, {}, [])
    assert "(ニュースなし)" in prompt


def test_build_stock_detail_prompt_instructs_no_directive_language():
    prompt = build_stock_detail_prompt("AAA.T", "エーエー株式会社", {}, {}, [])
    assert "断定的な売買判断" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_stock_detail_prompt.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'prompt_patterns.stock_detail'`）

- [ ] **Step 3: Implement `prompt_patterns/stock_detail.py`**

```python
def build_stock_detail_prompt(
    ticker: str, name: str | None, fundamentals: dict, technical: dict, news: list[dict]
) -> str:
    news_titles = "\n".join(f"- {item.get('title')}" for item in news) or "- (ニュースなし)"
    label = f"{ticker}（{name}）" if name else ticker
    return (
        f"銘柄 {label} について、以下のファンダメンタルズ・テクニカル・ニュース見出しを踏まえて、"
        "投資家向けの総合分析コメントを日本語で3〜4文程度で作成してください。"
        "断定的な売買判断は含めないでください。\n\n"
        f"PER: {fundamentals.get('per')}\n"
        f"PBR: {fundamentals.get('pbr')}\n"
        f"配当利回り: {fundamentals.get('dividend_yield')}\n"
        f"テクニカルシグナル: {technical.get('signal')}\n"
        f"直近ニュース見出し:\n{news_titles}\n"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_stock_detail_prompt.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add prompt_patterns/stock_detail.py tests/test_stock_detail_prompt.py
git commit -m "feat: add stock detail prompt builder"
```

---

## Task 2: データ統合 `stock_detail/detail.py`

**Files:**
- Create: `stock_detail/__init__.py`（空ファイル。他パッケージ `screening/__init__.py` と同じ）
- Create: `stock_detail/detail.py`
- Test: `tests/test_stock_detail.py`

**Interfaces:**
- Consumes: `build_stock_detail_prompt`（Task 1）、`analyze_fundamentals(ticker_symbol) -> dict`（`analysis_agents/fundamental_agent.py`）、`analyze_technical(price_history) -> dict`（`analysis_agents/technical_agent.py`）、`fetch_price_history(ticker_symbol, period) -> pd.DataFrame`・`fetch_news(ticker_symbol) -> list[dict]`（`data_api/stock_price_api.py`）、`call_llm(prompt) -> str`（`data_api/llm_client.py`）、`read_cache`/`write_cache`（`common/cache.py`）
- Produces: `generate_stock_detail(ticker: str, name: str | None, cache_dir: Path, call_llm=..., fetch_price_history=..., fetch_news=..., analyze_fundamentals=..., analyze_technical=...) -> dict`（Task 3 が `app.py` から呼び出す）。返り値の形:
  ```python
  {
      "ticker": str,
      "name": str | None,
      "price_history": {"dates": list[str], "close": list[float]},
      "fundamentals": dict,
      "technical": dict,
      "news": list[dict],
      "comment": str,
  }
  ```

- [ ] **Step 1: Write the failing tests**

`stock_detail/__init__.py` を空ファイルとして作成する。

`tests/test_stock_detail.py` を新規作成する。

```python
import pandas as pd

from stock_detail.detail import generate_stock_detail


def _fake_history():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    return pd.DataFrame({"Close": [100.0, 101.0, 102.0]}, index=dates)


def test_generate_stock_detail_builds_payload_from_dependencies(tmp_path):
    result = generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=lambda prompt: "テスト用の総合コメントです。",
        fetch_price_history=lambda ticker, period: _fake_history(),
        fetch_news=lambda ticker: [
            {"title": "ニュース1", "publisher": "社", "link": "http://example.com"}
        ],
        analyze_fundamentals=lambda ticker: {"per": 12.0, "pbr": 1.1, "dividend_yield": 2.5},
        analyze_technical=lambda history: {"ma_short": 101.0, "ma_long": 100.0, "signal": "強気"},
    )

    assert result == {
        "ticker": "AAA.T",
        "name": "エーエー株式会社",
        "price_history": {
            "dates": ["2026-01-01T00:00:00", "2026-01-02T00:00:00", "2026-01-03T00:00:00"],
            "close": [100.0, 101.0, 102.0],
        },
        "fundamentals": {"per": 12.0, "pbr": 1.1, "dividend_yield": 2.5},
        "technical": {"ma_short": 101.0, "ma_long": 100.0, "signal": "強気"},
        "news": [{"title": "ニュース1", "publisher": "社", "link": "http://example.com"}],
        "comment": "テスト用の総合コメントです。",
    }


def test_generate_stock_detail_handles_empty_price_history(tmp_path):
    result = generate_stock_detail(
        "AAA.T",
        None,
        tmp_path,
        call_llm=lambda prompt: "コメント",
        fetch_price_history=lambda ticker, period: pd.DataFrame({"Close": []}),
        fetch_news=lambda ticker: [],
        analyze_fundamentals=lambda ticker: {"per": None, "pbr": None, "dividend_yield": None},
        analyze_technical=lambda history: {"ma_short": None, "ma_long": None, "signal": "データ不足"},
    )

    assert result["price_history"] == {"dates": [], "close": []}
    assert result["news"] == []
    assert result["name"] is None


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
    )
    assert result["comment"] == "初回コメント"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_stock_detail.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'stock_detail'`）

- [ ] **Step 3: Implement `stock_detail/detail.py`**

```python
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


def generate_stock_detail(
    ticker: str,
    name: str | None,
    cache_dir: Path,
    call_llm=default_call_llm,
    fetch_price_history=default_fetch_price_history,
    fetch_news=default_fetch_news,
    analyze_fundamentals=default_analyze_fundamentals,
    analyze_technical=default_analyze_technical,
) -> dict:
    cache_key = f"stock-detail-{ticker}"
    cached = read_cache(cache_dir, cache_key)
    if cached is not None:
        return json.loads(cached)

    history = fetch_price_history(ticker, period="6mo")
    fundamentals = analyze_fundamentals(ticker)
    technical = analyze_technical(history)
    news = fetch_news(ticker)

    if history.empty:
        price_history = {"dates": [], "close": []}
    else:
        price_history = {
            "dates": [d.isoformat() for d in history.index],
            "close": history["Close"].tolist(),
        }

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
Expected: PASS（3 passed）

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `uv run pytest -v`
Expected: すべてPASS（既存テストに影響なし）

- [ ] **Step 6: Commit**

```bash
git add stock_detail/__init__.py stock_detail/detail.py tests/test_stock_detail.py
git commit -m "feat: add generate_stock_detail data/AI-comment orchestrator"
```

---

## Task 3: `app.py` — 共通ダイアログと行選択ヘルパーを追加

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: `generate_stock_detail`（Task 2）
- Produces: `show_stock_detail_dialog(ticker: str, name: str | None) -> None`、`_handle_table_selection(state_key: str, event, df: pd.DataFrame) -> None`（Task 4・5・6 が呼び出す）

このタスクでは表示ロジックのみを追加し、まだどのタブからも呼び出さない（Task 4〜6で配線する）。

- [ ] **Step 1: インポートを追加する**

`app.py` の以下の行:

```python
from screening.universe import UNIVERSE, UNIVERSE_NAMES

DATA_DIR = Path(__file__).parent / "data"
```

を次のように変更する:

```python
from screening.universe import UNIVERSE, UNIVERSE_NAMES
from stock_detail.detail import generate_stock_detail

DATA_DIR = Path(__file__).parent / "data"
```

- [ ] **Step 2: ダイアログ関数と選択ヘルパーを追加する**

`app.py` の以下の行:

```python
tab_portfolio, tab_screening, tab_backtest, tab_ranking = st.tabs(
    ["ポートフォリオ", "スクリーニング", "バックテスト", "一括バックテスト"]
)

with tab_portfolio:
```

を次のように変更する（`st.tabs(...)` と `with tab_portfolio:` の間に新しい2関数を挿入する）:

```python
tab_portfolio, tab_screening, tab_backtest, tab_ranking = st.tabs(
    ["ポートフォリオ", "スクリーニング", "バックテスト", "一括バックテスト"]
)


@st.dialog("銘柄詳細情報", width="large")
def show_stock_detail_dialog(ticker: str, name: str | None) -> None:
    with st.spinner("銘柄情報を取得中..."):
        detail = generate_stock_detail(ticker, name, CACHE_DIR, call_llm=call_llm)

    st.subheader(f"{ticker} {detail.get('name') or ''}")

    price_history = detail["price_history"]
    if price_history["dates"]:
        chart_df = pd.DataFrame(
            {"Close": price_history["close"]},
            index=pd.to_datetime(price_history["dates"]),
        )
        st.line_chart(chart_df)
    else:
        st.info("株価データを取得できませんでした。")

    fundamentals = detail["fundamentals"]
    col1, col2, col3 = st.columns(3)
    col1.metric("PER", fundamentals.get("per") if fundamentals.get("per") is not None else "―")
    col2.metric("PBR", fundamentals.get("pbr") if fundamentals.get("pbr") is not None else "―")
    col3.metric(
        "配当利回り(%)",
        fundamentals.get("dividend_yield")
        if fundamentals.get("dividend_yield") is not None
        else "―",
    )

    st.write(f"テクニカルシグナル: **{detail['technical'].get('signal')}**")

    st.subheader("AI総合分析コメント")
    st.write(detail["comment"])

    st.subheader("関連ニュース")
    news_items = detail["news"]
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

    st.markdown(DISCLAIMER_NOTICE)


def _handle_table_selection(state_key: str, event, df: pd.DataFrame) -> None:
    current = event.selection.rows[0] if event.selection.rows else None
    if current != st.session_state.get(state_key):
        st.session_state[state_key] = current
        if current is not None and current < len(df):
            row = df.iloc[current]
            show_stock_detail_dialog(row["ticker"], row.get("name") or "")


with tab_portfolio:
```

- [ ] **Step 3: 構文チェック**

Run: `uv run python -m py_compile app.py`
Expected: エラーなし（出力なしで終了）

- [ ] **Step 4: 既存テストに影響がないことを確認**

Run: `uv run pytest -v`
Expected: すべてPASS

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "feat: add shared stock detail dialog and row-selection helper"
```

---

## Task 4: `app.py` — スクリーニングタブに行クリックを配線する

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: `_handle_table_selection`・`show_stock_detail_dialog`（Task 3）

**Files:**
- Modify: `app.py`

- [ ] **Step 1: スクリーニングタブのブロックを置き換える**

`app.py` の以下のブロック（`with tab_screening:` から、その `with` ブロックの末尾 `st.write(...)` まで）:

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
            filters = json.loads(strip_code_fence(raw_filters))
        except json.JSONDecodeError:
            st.error("条件の解釈に失敗しました。条件を言い換えて再度お試しください。")

        if filters is not None:
            st.subheader("AIが解釈した条件（適用前に確認してください）")
            st.json(filters)

            if st.button("この条件で絞り込む"):
                universe_df = fetch_universe_fundamentals(UNIVERSE, CACHE_DIR)
                universe_df["name"] = universe_df["ticker"].map(UNIVERSE_NAMES).fillna(
                    universe_df["name"]
                )
                result_df = apply_filters(universe_df, filters)

                st.subheader(f"絞り込み結果（{len(result_df)}件）")
                st.dataframe(
                    result_df,
                    column_config={
                        "ticker": st.column_config.TextColumn("銘柄コード"),
                        "name": st.column_config.TextColumn("銘柄名"),
                        "per": st.column_config.NumberColumn("PER"),
                        "pbr": st.column_config.NumberColumn("PBR"),
                        "dividend_yield_pct": st.column_config.NumberColumn("配当利回り(%)"),
                        "market_cap": st.column_config.NumberColumn("時価総額"),
                    },
                )

                comments = generate_screening_comments(result_df, call_llm=call_llm)
                st.subheader("銘柄ごとのAIコメント")
                for row in result_df.itertuples():
                    st.write(
                        f"**{row.ticker} {row.name}**: "
                        f"{comments.get(row.ticker, 'コメント生成失敗')}"
                    )
```

を次のように置き換える:

```python
with tab_screening:
    st.header("銘柄スクリーニング")

    condition_text = st.text_input(
        "スクリーニング条件を自然言語で入力してください",
        placeholder="PERが15倍以下で配当利回りが3%以上",
    )

    if condition_text:
        if st.session_state.get("screening_condition_text") != condition_text:
            prompt = build_screening_prompt(condition_text)
            raw_filters = call_llm(prompt)
            st.session_state["screening_condition_text"] = condition_text
            try:
                st.session_state["screening_filters"] = json.loads(strip_code_fence(raw_filters))
                st.session_state["screening_filters_error"] = False
            except json.JSONDecodeError:
                st.session_state["screening_filters"] = None
                st.session_state["screening_filters_error"] = True

        filters = st.session_state.get("screening_filters")
        if st.session_state.get("screening_filters_error"):
            st.error("条件の解釈に失敗しました。条件を言い換えて再度お試しください。")

        if filters is not None:
            st.subheader("AIが解釈した条件（適用前に確認してください）")
            st.json(filters)

            if st.button("この条件で絞り込む"):
                universe_df = fetch_universe_fundamentals(UNIVERSE, CACHE_DIR)
                universe_df["name"] = universe_df["ticker"].map(UNIVERSE_NAMES).fillna(
                    universe_df["name"]
                )
                result_df = apply_filters(universe_df, filters)
                comments = generate_screening_comments(result_df, call_llm=call_llm)

                st.session_state["screening_result_df"] = result_df
                st.session_state["screening_comments"] = comments
                st.session_state["screening_selected_row"] = None
                st.session_state["screening_result_table"] = {
                    "selection": {"rows": [], "columns": []}
                }

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
                "per": st.column_config.NumberColumn("PER"),
                "pbr": st.column_config.NumberColumn("PBR"),
                "dividend_yield_pct": st.column_config.NumberColumn("配当利回り(%)"),
                "market_cap": st.column_config.NumberColumn("時価総額"),
            },
            on_select="rerun",
            selection_mode="single-row",
            key="screening_result_table",
        )
        _handle_table_selection("screening_selected_row", event, result_df)

        st.subheader("銘柄ごとのAIコメント")
        for row in result_df.itertuples():
            st.write(
                f"**{row.ticker} {row.name}**: "
                f"{comments.get(row.ticker, 'コメント生成失敗')}"
            )
```

**補足（挙動の変化）:**
- 条件文（`condition_text`）が変わっていない限り、AI条件解釈（`call_llm`）は再実行されない（既存は毎リランで再実行していた）。行クリックによる追加リランでLLM呼び出しが増えるのを防ぐための必須修正。
- 絞り込み結果は `st.session_state["screening_result_df"]` に保存され、ボタンクリック時だけでなく行クリック後のリランでも表示され続ける。
- 新しく絞り込みを実行するたびに `st.session_state["screening_result_table"]` を空の選択状態にリセットする。これによりStreamlitの公式サポート機能（ウィジェットの `key` に対応する `session_state` へ `{"selection": {"rows": [...]}}` を代入するとプログラム的に選択状態を上書きできる）を使い、新しい検索結果に前回の選択位置が誤って残る（＝クリックしていないのにダイアログが開く）事故を防ぐ。

- [ ] **Step 2: 構文チェック**

Run: `uv run python -m py_compile app.py`
Expected: エラーなし

- [ ] **Step 3: 既存テストに影響がないことを確認**

Run: `uv run pytest -v`
Expected: すべてPASS

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: wire row-click stock detail dialog into screening tab"
```

---

## Task 5: `app.py` — 一括バックテストタブに行クリックを配線する

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: `_handle_table_selection`・`show_stock_detail_dialog`（Task 3）

- [ ] **Step 1: 一括バックテストタブの実行ボタン以降のブロックを置き換える**

`app.py` の以下のブロック（`if st.button("一括バックテストを実行"):` から、その `with tab_ranking:` ブロックの末尾 `st.markdown(DISCLAIMER_NOTICE)` まで）:

```python
    if st.button("一括バックテストを実行"):
        strategy = STRATEGIES[ranking_strategy]
        transaction_cost_pct = 0.1 if ranking_apply_cost else 0.0

        holdings = load_holdings(HOLDINGS_PATH)
        holdings_tickers = [h["ticker"] for h in holdings if h.get("ticker")]
        target_tickers = sorted(set(UNIVERSE) | set(holdings_tickers))

        cache_key = "universe-backtest-" + hashlib.sha256(
            f"{ranking_strategy}-{ranking_period}-{transaction_cost_pct}-"
            f"{'-'.join(target_tickers)}".encode("utf-8")
        ).hexdigest()[:12]
        cached_payload = None if ranking_force_regenerate else read_cache(CACHE_DIR, cache_key)

        payload = json.loads(cached_payload) if cached_payload is not None else None

        if payload is None:
            prices_by_ticker = {}
            skipped_tickers = []
            progress = st.progress(0.0, text="株価データを取得中...")
            for i, ticker in enumerate(target_tickers):
                try:
                    history = fetch_price_history(ticker, period=ranking_period)
                except Exception:
                    skipped_tickers.append(ticker)
                    history = None
                if history is not None and not history.empty:
                    prices_by_ticker[ticker] = history["Close"]
                else:
                    if ticker not in skipped_tickers:
                        skipped_tickers.append(ticker)
                progress.progress(
                    (i + 1) / len(target_tickers),
                    text=f"株価データを取得中... ({i + 1}/{len(target_tickers)})",
                )
            progress.empty()

            if not prices_by_ticker:
                st.error("バックテスト可能な銘柄がありませんでした。")
                payload = None
            else:
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
            candidate_names = build_candidate_names(
                load_holdings(HOLDINGS_PATH), resolve_name=_cached_fetch_japanese_name
            )
            ranking_df = pd.DataFrame(payload["ranking_rows"])
            ranking_df["name"] = ranking_df["ticker"].map(candidate_names).fillna("")
            ranking_df.insert(0, "順位", range(1, len(ranking_df) + 1))
            ranking_df = ranking_df[
                [
                    "順位",
                    "ticker",
                    "name",
                    "total_return_pct",
                    "benchmark_return_pct",
                    "win_rate_pct",
                    "max_drawdown_pct",
                    "risk_adjusted_return",
                ]
            ]

            st.subheader(f"{ranking_strategy}（{payload['preset_label']}）ランキング")
            st.dataframe(
                ranking_df,
                column_config={
                    "ticker": st.column_config.TextColumn("銘柄コード"),
                    "name": st.column_config.TextColumn("銘柄名"),
                    "total_return_pct": st.column_config.NumberColumn("累積リターン(%)"),
                    "benchmark_return_pct": st.column_config.NumberColumn("ベンチマーク(%)"),
                    "win_rate_pct": st.column_config.NumberColumn("勝率(%)"),
                    "max_drawdown_pct": st.column_config.NumberColumn("最大DD(%)"),
                    "risk_adjusted_return": st.column_config.NumberColumn("リスク調整済みリターン"),
                },
                hide_index=True,
            )

            if payload["skipped_tickers"]:
                st.info(
                    "データ取得・データ不足によりスキップした銘柄: "
                    + ", ".join(payload["skipped_tickers"])
                )

            st.subheader("上位5銘柄のAIコメント")
            for row in payload["ranking_rows"][:5]:
                ticker = row["ticker"]
                st.write(f"**{ticker}**: {payload['comments'].get(ticker, 'コメント生成失敗')}")

            st.markdown(DISCLAIMER_NOTICE)
```

を次のように置き換える:

```python
    if st.button("一括バックテストを実行"):
        strategy = STRATEGIES[ranking_strategy]
        transaction_cost_pct = 0.1 if ranking_apply_cost else 0.0

        holdings = load_holdings(HOLDINGS_PATH)
        holdings_tickers = [h["ticker"] for h in holdings if h.get("ticker")]
        target_tickers = sorted(set(UNIVERSE) | set(holdings_tickers))

        cache_key = "universe-backtest-" + hashlib.sha256(
            f"{ranking_strategy}-{ranking_period}-{transaction_cost_pct}-"
            f"{'-'.join(target_tickers)}".encode("utf-8")
        ).hexdigest()[:12]
        cached_payload = None if ranking_force_regenerate else read_cache(CACHE_DIR, cache_key)

        payload = json.loads(cached_payload) if cached_payload is not None else None

        if payload is None:
            prices_by_ticker = {}
            skipped_tickers = []
            progress = st.progress(0.0, text="株価データを取得中...")
            for i, ticker in enumerate(target_tickers):
                try:
                    history = fetch_price_history(ticker, period=ranking_period)
                except Exception:
                    skipped_tickers.append(ticker)
                    history = None
                if history is not None and not history.empty:
                    prices_by_ticker[ticker] = history["Close"]
                else:
                    if ticker not in skipped_tickers:
                        skipped_tickers.append(ticker)
                progress.progress(
                    (i + 1) / len(target_tickers),
                    text=f"株価データを取得中... ({i + 1}/{len(target_tickers)})",
                )
            progress.empty()

            if not prices_by_ticker:
                st.error("バックテスト可能な銘柄がありませんでした。")
                payload = None
            else:
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
            st.session_state["ranking_payload"] = payload
            st.session_state["ranking_strategy_label"] = ranking_strategy
            st.session_state["ranking_selected_row"] = None
            st.session_state["ranking_table"] = {"selection": {"rows": [], "columns": []}}

    if st.session_state.get("ranking_payload") is not None:
        payload = st.session_state["ranking_payload"]
        ranking_strategy_label = st.session_state["ranking_strategy_label"]

        candidate_names = build_candidate_names(
            load_holdings(HOLDINGS_PATH), resolve_name=_cached_fetch_japanese_name
        )
        ranking_df = pd.DataFrame(payload["ranking_rows"])
        ranking_df["name"] = ranking_df["ticker"].map(candidate_names).fillna("")
        ranking_df.insert(0, "順位", range(1, len(ranking_df) + 1))
        ranking_df = ranking_df[
            [
                "順位",
                "ticker",
                "name",
                "total_return_pct",
                "benchmark_return_pct",
                "win_rate_pct",
                "max_drawdown_pct",
                "risk_adjusted_return",
            ]
        ]

        st.subheader(f"{ranking_strategy_label}（{payload['preset_label']}）ランキング")
        st.caption("行をクリックすると銘柄詳細を表示します。")
        event = st.dataframe(
            ranking_df,
            column_config={
                "ticker": st.column_config.TextColumn("銘柄コード"),
                "name": st.column_config.TextColumn("銘柄名"),
                "total_return_pct": st.column_config.NumberColumn("累積リターン(%)"),
                "benchmark_return_pct": st.column_config.NumberColumn("ベンチマーク(%)"),
                "win_rate_pct": st.column_config.NumberColumn("勝率(%)"),
                "max_drawdown_pct": st.column_config.NumberColumn("最大DD(%)"),
                "risk_adjusted_return": st.column_config.NumberColumn("リスク調整済みリターン"),
            },
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="ranking_table",
        )
        _handle_table_selection("ranking_selected_row", event, ranking_df)

        if payload["skipped_tickers"]:
            st.info(
                "データ取得・データ不足によりスキップした銘柄: "
                + ", ".join(payload["skipped_tickers"])
            )

        st.subheader("上位5銘柄のAIコメント")
        for row in payload["ranking_rows"][:5]:
            ticker = row["ticker"]
            st.write(f"**{ticker}**: {payload['comments'].get(ticker, 'コメント生成失敗')}")

        st.markdown(DISCLAIMER_NOTICE)
```

**補足（挙動の変化）:**
- `payload` の表示部分をボタン分岐の外側に移し、`st.session_state["ranking_payload"]` を経由して行クリック後のリランでも表示され続けるようにした。
- 見出しに使う戦略名は、実行時点の `ranking_strategy_label`（session_state保存済み）を使う。実行後にセレクトボックスの選択を変えても、表示中の結果とラベルの不整合が起きない（実行前と同じ既存の意図を維持）。
- 新しく実行するたびに `st.session_state["ranking_table"]` を空の選択状態にリセットし、前回の選択位置が新しい結果に残らないようにする（スクリーニングタブと同じ理由）。

- [ ] **Step 2: 構文チェック**

Run: `uv run python -m py_compile app.py`
Expected: エラーなし

- [ ] **Step 3: 既存テストに影響がないことを確認**

Run: `uv run pytest -v`
Expected: すべてPASS

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: wire row-click stock detail dialog into ranking tab"
```

---

## Task 6: `app.py` — ポートフォリオタブに詳細ボタンを追加する

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: `show_stock_detail_dialog`（Task 3）

- [ ] **Step 1: 保有銘柄保存ブロックの直後に詳細ボタン一覧を追加する**

`app.py` の以下のブロック:

```python
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

    force_regenerate = st.checkbox("キャッシュを無視して再生成する")
```

を次のように変更する（保存ブロックと `force_regenerate` の間に新しいブロックを挿入する）:

```python
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

    if holdings:
        st.subheader("銘柄詳細を見る")
        for holding in holdings:
            ticker = holding["ticker"]
            name = candidate_names.get(ticker, "")
            col_ticker, col_name, col_button = st.columns([2, 4, 2])
            col_ticker.write(ticker)
            col_name.write(name)
            if col_button.button("詳細", key=f"portfolio_detail_{ticker}"):
                show_stock_detail_dialog(ticker, name)

    force_regenerate = st.checkbox("キャッシュを無視して再生成する")
```

`candidate_names` はポートフォリオタブの冒頭（`candidate_names = build_candidate_names(...)`）で既に定義済みの変数をそのまま再利用する。

- [ ] **Step 2: 構文チェック**

Run: `uv run python -m py_compile app.py`
Expected: エラーなし

- [ ] **Step 3: 既存テストに影響がないことを確認**

Run: `uv run pytest -v`
Expected: すべてPASS

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: add per-row stock detail button to portfolio holdings"
```

---

## Task 7: README更新

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 「機能」節に銘柄詳細ダイアログの説明を追記する**

`README.md` の以下の行:

```markdown
- **ポートフォリオ**タブ: 保有銘柄（ティッカー・株数・取得単価）を登録し、構成比・損益・リスク（ボラティリティ・相関）・ファンダメンタル・テクニカル・ニュースセンチメントを統合したレビューレポートを生成します。
- **スクリーニング**タブ: 自然言語の条件（例:「PERが15倍以下で配当利回りが3%以上」）を入力すると、主要銘柄（[screening/universe.py](screening/universe.py)、44銘柄）の中から条件に合う銘柄を絞り込みます。AIが解釈した条件は適用前に必ず画面で確認できます。
```

を次のように変更する:

```markdown
- **ポートフォリオ**タブ: 保有銘柄（ティッカー・株数・取得単価）を登録し、構成比・損益・リスク（ボラティリティ・相関）・ファンダメンタル・テクニカル・ニュースセンチメントを統合したレビューレポートを生成します。保有銘柄一覧の各行にある「詳細」ボタンから、個別銘柄の詳細情報（株価チャート・ファンダメンタルズ・AI総合分析コメントなど）をモーダル表示できます。
- **スクリーニング**タブ: 自然言語の条件（例:「PERが15倍以下で配当利回りが3%以上」）を入力すると、主要銘柄（[screening/universe.py](screening/universe.py)、44銘柄）の中から条件に合う銘柄を絞り込みます。AIが解釈した条件は適用前に必ず画面で確認できます。絞り込み結果の行をクリックすると、個別銘柄の詳細情報をモーダル表示できます。
```

続けて、`README.md` の以下の行:

```markdown
- **一括バックテスト**タブ: 主要銘柄（UNIVERSE、58銘柄）と保有銘柄を対象に、選択した戦略の標準プリセットで一括バックテストし、リスク調整済みリターン（累積リターン÷|最大ドローダウン|）の高い順にランキング表示します。上位5銘柄にはAIによる一言コメントを表示します。
```

を次のように変更する:

```markdown
- **一括バックテスト**タブ: 主要銘柄（UNIVERSE、58銘柄）と保有銘柄を対象に、選択した戦略の標準プリセットで一括バックテストし、リスク調整済みリターン（累積リターン÷|最大ドローダウン|）の高い順にランキング表示します。上位5銘柄にはAIによる一言コメントを表示します。ランキング表の行をクリックすると、個別銘柄の詳細情報をモーダル表示できます。
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document stock detail dialog in feature list"
```

---

## Task 8: 全体テストと手動確認

**Files:** なし（検証のみ）

- [ ] **Step 1: 全自動テストを実行する**

Run: `uv run pytest -v`
Expected: すべてPASS

- [ ] **Step 2: アプリを起動する**

Run: `uv run python -m streamlit run app.py`
Expected: `http://localhost:8501` が起動し、ブラウザで開ける

- [ ] **Step 3: スクリーニングタブを手動確認する**

1. スクリーニング条件（例:「PERが15倍以下」）を入力し、「この条件で絞り込む」を押す
2. 結果表の行をクリックし、「銘柄詳細情報」ダイアログが開くこと（株価チャート・PER/PBR/配当利回り・テクニカルシグナル・関連ニュース・AI総合分析コメント・免責事項が表示される）を確認する
3. ダイアログを閉じ（背景クリックまたは×）、他の操作（例: 何もせず再度画面を触る）でダイアログが勝手に再度開かないことを確認する
4. 別の行をクリックし、別銘柄のダイアログが開くことを確認する
5. 新しい条件で再度絞り込みを実行し、以前のクリック位置が新しい結果に引き継がれてダイアログが自動的に開かないことを確認する

- [ ] **Step 4: 一括バックテストタブを手動確認する**

1. 戦略・取得期間を選択し、「一括バックテストを実行」を押す
2. ランキング表の行をクリックし、詳細ダイアログが開くことを確認する
3. Step 3-3, 3-4, 3-5 と同様の確認を行う

- [ ] **Step 5: ポートフォリオタブを手動確認する**

1. 銘柄を1件以上追加し、「保有銘柄を保存」を押す
2. 「銘柄詳細を見る」に表示された各行の「詳細」ボタンを押し、詳細ダイアログが開くことを確認する
3. `st.data_editor` の株数・取得単価をインライン編集し、保存後も編集内容が保持されること（既存機能の回帰がないこと）を確認する

- [ ] **Step 6: アプリを停止する**

`Ctrl+C` でStreamlitサーバーを停止する。
