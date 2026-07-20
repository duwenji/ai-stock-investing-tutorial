# 銘柄詳細ダイアログ ローソク足・出来高表示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 銘柄詳細ダイアログの株価チャートを、終値のみの折れ線グラフからローソク足チャート（陽線・陰線色分け）＋出来高の棒グラフに置き換える。

**Architecture:** `stock_detail/detail.py` の `price_history` ペイロードを終値のみからOHLCV（始値・高値・安値・終値・出来高）に拡張し、`app.py` の `show_stock_detail_dialog` でAltair（Streamlit同梱、新規依存追加なし）を使ってローソク足＋出来高チャートを描画する。

**Tech Stack:** Python 3.14, Streamlit 1.59.2, Altair 6.2.2（インストール済み）, pandas, pytest。

## Global Constraints

- 新規外部依存は追加しない（Altairは既にインストール済み。`pyproject.toml` は変更しない）。
- `price_history` の新形式: `{"dates": list[str], "open": list[float], "high": list[float], "low": list[float], "close": list[float], "volume": list[float]}`。データが空の場合は全キー空リスト。
- `app.py` のUI部分は既存方針通り自動テスト対象外。
- 設計書: [docs/superpowers/specs/2026-07-20-stock-detail-candlestick-design.md](../specs/2026-07-20-stock-detail-candlestick-design.md)

---

## Task 1: `stock_detail/detail.py` の `price_history` をOHLCVに拡張する

**Files:**
- Modify: `stock_detail/detail.py`
- Modify: `tests/test_stock_detail.py`

**Interfaces:**
- Consumes: なし（既存の `fetch_price_history` が返す `pd.DataFrame` の `Open`/`High`/`Low`/`Close`/`Volume` 列をそのまま使う。yfinanceの `history()` はこれらの列を持つ）
- Produces: `generate_stock_detail(...)` の返り値 `price_history` が `{"dates": ..., "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}` になる（Task 2 の `app.py` が消費する）

- [ ] **Step 1: 既存テストをOHLCV形式に更新する（失敗する状態にする）**

`tests/test_stock_detail.py` の以下の関数:

```python
def _fake_history():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    return pd.DataFrame({"Close": [100.0, 101.0, 102.0]}, index=dates)
```

を次のように置き換える:

```python
def _fake_history():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    return pd.DataFrame(
        {
            "Open": [99.0, 100.5, 101.5],
            "High": [101.0, 102.0, 103.0],
            "Low": [98.5, 100.0, 101.0],
            "Close": [100.0, 101.0, 102.0],
            "Volume": [1000, 1200, 900],
        },
        index=dates,
    )
```

続けて、`test_generate_stock_detail_builds_payload_from_dependencies` 内の以下の部分:

```python
        "price_history": {
            "dates": ["2026-01-01T00:00:00", "2026-01-02T00:00:00", "2026-01-03T00:00:00"],
            "close": [100.0, 101.0, 102.0],
        },
```

を次のように置き換える:

```python
        "price_history": {
            "dates": ["2026-01-01T00:00:00", "2026-01-02T00:00:00", "2026-01-03T00:00:00"],
            "open": [99.0, 100.5, 101.5],
            "high": [101.0, 102.0, 103.0],
            "low": [98.5, 100.0, 101.0],
            "close": [100.0, 101.0, 102.0],
            "volume": [1000, 1200, 900],
        },
```

続けて、`test_generate_stock_detail_handles_empty_price_history` 内の以下の2箇所:

```python
        fetch_price_history=lambda ticker, period: pd.DataFrame({"Close": []}),
```

を

```python
        fetch_price_history=lambda ticker, period: pd.DataFrame(
            {"Open": [], "High": [], "Low": [], "Close": [], "Volume": []}
        ),
```

に、

```python
    assert result["price_history"] == {"dates": [], "close": []}
```

を

```python
    assert result["price_history"] == {
        "dates": [],
        "open": [],
        "high": [],
        "low": [],
        "close": [],
        "volume": [],
    }
```

に置き換える。

- [ ] **Step 2: テストを実行し、失敗することを確認する**

Run: `uv run pytest tests/test_stock_detail.py -v`
Expected: FAIL（`test_generate_stock_detail_builds_payload_from_dependencies` と `test_generate_stock_detail_handles_empty_price_history` が `price_history` の内容不一致で失敗する）

- [ ] **Step 3: `stock_detail/detail.py` を実装する**

`stock_detail/detail.py` の以下の部分:

```python
    if history.empty:
        price_history = {"dates": [], "close": []}
    else:
        price_history = {
            "dates": [d.isoformat() for d in history.index],
            "close": history["Close"].tolist(),
        }
```

を次のように置き換える:

```python
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
```

- [ ] **Step 4: テストを実行し、成功することを確認する**

Run: `uv run pytest tests/test_stock_detail.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 全体テストで既存機能に影響がないことを確認する**

Run: `uv run pytest -v`
Expected: すべてPASS

- [ ] **Step 6: Commit**

```bash
git add stock_detail/detail.py tests/test_stock_detail.py
git commit -m "feat: expand stock detail price history to OHLCV"
```

---

## Task 2: `app.py` — ローソク足＋出来高チャートを描画する

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: `generate_stock_detail(...)` の `price_history`（Task 1、OHLCV形式）

- [ ] **Step 1: Altairのインポートを追加する**

`app.py` の以下の行:

```python
import pandas as pd
import streamlit as st
```

を次のように変更する:

```python
import altair as alt
import pandas as pd
import streamlit as st
```

- [ ] **Step 2: チャート描画部分をローソク足＋出来高に置き換える**

`app.py` の以下のブロック:

```python
    price_history = detail["price_history"]
    if price_history["dates"]:
        chart_df = pd.DataFrame(
            {"Close": price_history["close"]},
            index=pd.to_datetime(price_history["dates"]),
        )
        st.line_chart(chart_df)
    else:
        st.info("株価データを取得できませんでした。")
```

を次のように置き換える:

```python
    price_history = detail["price_history"]
    if price_history["dates"]:
        chart_df = pd.DataFrame(
            {
                "date": pd.to_datetime(price_history["dates"]),
                "open": price_history["open"],
                "high": price_history["high"],
                "low": price_history["low"],
                "close": price_history["close"],
                "volume": price_history["volume"],
            }
        )
        chart_df["direction"] = chart_df.apply(
            lambda row: "up" if row["close"] >= row["open"] else "down", axis=1
        )
        color_scale = alt.Scale(domain=["up", "down"], range=["#26a69a", "#ef5350"])

        base = alt.Chart(chart_df).encode(x=alt.X("date:T", title="日付"))
        wick = base.mark_rule().encode(
            y=alt.Y("low:Q", title="株価", scale=alt.Scale(zero=False)),
            y2="high:Q",
            color=alt.Color("direction:N", scale=color_scale, legend=None),
        )
        body = base.mark_bar().encode(
            y="open:Q",
            y2="close:Q",
            color=alt.Color("direction:N", scale=color_scale, legend=None),
        )
        st.altair_chart((wick + body).properties(height=300), width="stretch")

        volume_chart = (
            alt.Chart(chart_df)
            .mark_bar()
            .encode(
                x=alt.X("date:T", title=None),
                y=alt.Y("volume:Q", title="出来高"),
                color=alt.Color("direction:N", scale=color_scale, legend=None),
            )
            .properties(height=100)
        )
        st.altair_chart(volume_chart, width="stretch")
    else:
        st.info("株価データを取得できませんでした。")
```

- [ ] **Step 3: 構文チェック**

Run: `uv run python -m py_compile app.py`
Expected: エラーなし

- [ ] **Step 4: 既存テストに影響がないことを確認**

Run: `uv run pytest -v`
Expected: すべてPASS

- [ ] **Step 5: 実行時の動作確認（Streamlit AppTestで実データを使って検証）**

以下のワンショットスクリプトを実行し、例外が出ないこと・チャート要素が2つ（ローソク足・出来高）生成されることを確認する。

```bash
uv run python -c "
from streamlit.testing.v1 import AppTest
at = AppTest.from_file('app.py', default_timeout=180)
at.run()
print('initial exception:', at.exception)
holdings_buttons = [b for b in at.tabs[0].button if b.key and b.key.startswith('portfolio_detail_')]
holdings_buttons[0].click().run()
print('after detail click, exception:', at.exception)
"
```

Expected: 両方の `exception` が空（`ElementList()`）であること。`data/holdings.json` に保有銘柄が1件もない場合はこのステップをスキップし、Step 6の手動確認で代替する。

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "feat: render candlestick and volume chart in stock detail dialog"
```

---

## Task 3: 手動確認とREADME更新

**Files:**
- Modify: `README.md`

- [ ] **Step 1: README.mdのポートフォリオタブの説明を更新する**

`README.md` の以下の行:

```markdown
- **ポートフォリオ**タブ: 保有銘柄（ティッカー・株数・取得単価）を登録し、構成比・損益・リスク（ボラティリティ・相関）・ファンダメンタル・テクニカル・ニュースセンチメントを統合したレビューレポートを生成します。保有銘柄一覧の各行にある「詳細」ボタンから、個別銘柄の詳細情報（株価チャート・ファンダメンタルズ・AI総合分析コメントなど）をモーダル表示できます。
```

を次のように変更する:

```markdown
- **ポートフォリオ**タブ: 保有銘柄（ティッカー・株数・取得単価）を登録し、構成比・損益・リスク（ボラティリティ・相関）・ファンダメンタル・テクニカル・ニュースセンチメントを統合したレビューレポートを生成します。保有銘柄一覧の各行にある「詳細」ボタンから、個別銘柄の詳細情報（ローソク足・出来高チャート、ファンダメンタルズ、AI総合分析コメントなど）をモーダル表示できます。
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: mention candlestick and volume chart in feature list"
```

- [ ] **Step 3: アプリを起動して手動確認する**

Run: `uv run python -m streamlit run app.py`

1. いずれかのタブ（スクリーニング結果行クリック／ランキング行クリック／ポートフォリオの「詳細」ボタン）から銘柄詳細ダイアログを開く
2. ローソク足チャートが表示され、陽線（緑）・陰線（赤）が値動きに応じて色分けされていることを確認する
3. ローソク足の下に出来高の棒グラフが同じ日付軸で表示されていることを確認する
4. 株価データが取得できない銘柄（該当があれば）で「株価データを取得できませんでした。」が表示され、チャート部分のみスキップされることを確認する

- [ ] **Step 4: アプリを停止する**

`Ctrl+C` でStreamlitサーバーを停止する。
