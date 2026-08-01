# AI戦略ビルダー Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 投資アイデアの自由入力 → AIとの対話によるスクリーニング条件構築 → 簡易バックテスト検証 →
最新データでの銘柄選定実行、を一気通貫で行う新規タブ「AI戦略ビルダー」を
`ai-stock-investing-tutorial/app` に追加する。

**Architecture:** 既存5タブ・既存モジュールは変更せず（セクター分析の共通処理切り出しを除く）、
新規パッケージ `app/strategy_builder/`（純粋ロジック）と `app/prompt_patterns/strategy_dialogue.py`
（対話プロンプト）を土台に、新規タブ `app/app_tabs/strategy_builder_tab.py` がそれらを
Streamlit UIとして組み立てる。既存のセクターローテーション分析の重い処理は
`app_tabs/shared.py::run_or_load_sector_rotation()` として切り出し、セクタータブと
AI戦略ビルダータブの両方から共有する。

**Tech Stack:** Python 3.14 / Streamlit 1.59+ / pandas / yfinance / Altair / 既存の
`data_api.llm_client.call_llm`（Claude Code CLIサブプロセス呼び出し、変更なし）

## Global Constraints

- 既存5タブ（ポートフォリオ／スクリーニング／バックテスト／一括バックテスト／
  セクターローテーション）のUI・動作を変更しない。
- 既存の `apply_filters`（`prompt_patterns/screening.py`、field/記号演算子スキーマ）は変更しない。
  戦略JSON（indicator/operatorスキーマ）は新規モジュール `strategy_builder/conditions.py` で
  独立して扱う。
- `data_api/llm_client.py` の `call_llm` のシグネチャ・システムプロンプトは変更しない。
  ペルソナ指示はユーザープロンプト本文に埋め込む。
- バックテスト・セクターローテーション分析の期間セレクトボックスは `["1y", "2y"]` の2択とする
  （依頼書の「5〜10年」から、簡易バックテストとの相性を考慮して短縮したもの）。
- 新規データファイルは `app/data/strategies.json`（`holdings.json`と同様、未コミット運用）。
- UIタブファイル自体は既存踏襲で自動テスト対象外とする（このリポジトリに
  `streamlit.testing.v1.AppTest` の利用実績はなく、`app_tabs/*.py` は現状すべて未テスト）。
  ロジックモジュール（`strategy_builder/*`, `prompt_patterns/strategy_dialogue.py`,
  `data_api/stock_price_api.py`の追加分）はpytestで単体テストする。
- 設計の背景・データ制約・機能仕様の詳細は
  `docs/superpowers/specs/2026-08-01-ai-strategy-builder-design.md` を正とする。

---

## Task 1: `fetch_fundamentals`/`fetch_universe_fundamentals` にROE・売上高伸び率を追加

**Files:**
- Modify: `app/data_api/stock_price_api.py:39-53`（`fetch_fundamentals`）
- Modify: `app/data_api/stock_price_api.py:107-148`（`fetch_universe_fundamentals`）
- Test: `app/tests/test_stock_price_api.py`

**Interfaces:**
- Produces: `fetch_fundamentals(ticker_symbol) -> dict` の戻り値に
  `"return_on_equity": float | None`, `"revenue_growth": float | None` を追加（生の小数値、
  yfinanceの`returnOnEquity`/`revenueGrowth`をそのまま渡す）。
  `fetch_universe_fundamentals(...) -> pd.DataFrame` の戻り値に
  `"roe_pct": float | None`, `"revenue_growth_pct": float | None` 列を追加
  （生の小数値を100倍したパーセント表示用の値）。

- [ ] **Step 1: 既存テストが通ることを確認するベースラインを取る**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_stock_price_api.py -v`
Expected: 既存の全テストがPASS（この時点ではまだ変更していないため）

- [ ] **Step 2: 失敗するテストを書く（`fetch_fundamentals`がROE・売上高伸び率を返すこと）**

`app/tests/test_stock_price_api.py` の `FakeTicker.info` プロパティを次のように変更する
（`"returnOnEquity": 0.155, "revenueGrowth": 0.082` を追加）:

```python
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
            "returnOnEquity": 0.155,
            "revenueGrowth": 0.082,
        }
```

`test_fetch_fundamentals_maps_info_fields` に次のアサーションを追加する:

```python
def test_fetch_fundamentals_maps_info_fields(monkeypatch):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", FakeTicker)
    result = stock_price_api.fetch_fundamentals("7203.T")
    assert result["ticker"] == "7203.T"
    assert result["name"] == "Fake Corp"
    assert result["trailing_pe"] == 12.3
    assert result["price_to_book"] == 1.1
    assert result["dividend_yield"] == 0.02
    assert result["market_cap"] == 1_000_000
    assert result["return_on_equity"] == 0.155
    assert result["revenue_growth"] == 0.082
```

`test_fetch_fundamentals_missing_fields_return_none` に次のアサーションを追加する:

```python
def test_fetch_fundamentals_missing_fields_return_none(monkeypatch):
    monkeypatch.setattr(stock_price_api.yf, "Ticker", EmptyInfoTicker)
    result = stock_price_api.fetch_fundamentals("7203.T")
    assert result["trailing_pe"] is None
    assert result["price_to_book"] is None
    assert result["return_on_equity"] is None
    assert result["revenue_growth"] is None
```

- [ ] **Step 2b: 上記テストが失敗することを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_stock_price_api.py -k fetch_fundamentals_maps_info_fields -v`
Expected: FAIL（`KeyError: 'return_on_equity'`）

- [ ] **Step 3: `fetch_fundamentals`を実装する**

`app/data_api/stock_price_api.py` の `fetch_fundamentals` 関数を次のように変更する:

```python
def fetch_fundamentals(ticker_symbol: str) -> dict:
    """指定銘柄のファンダメンタルズ指標（PER・PBR・配当利回り・ROE・売上高伸び率等）を取得する。"""
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
        "return_on_equity": info.get("returnOnEquity"),
        "revenue_growth": info.get("revenueGrowth"),
    }
    logger.info("fundamentalsレスポンス: ticker=%s data=%s", ticker_symbol, result)
    return result
```

- [ ] **Step 4: テストを実行し、Step 2のテストがPASSすることを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_stock_price_api.py -k fetch_fundamentals -v`
Expected: PASS

- [ ] **Step 5: `fetch_universe_fundamentals`がroe_pct/revenue_growth_pctを返す失敗するテストを書く**

`app/tests/test_stock_price_api.py` に次のテストを追加する:

```python
def test_fetch_universe_fundamentals_converts_roe_and_revenue_growth_to_pct(tmp_path):
    def fake_fetch_fundamentals(ticker_symbol):
        return {
            "ticker": ticker_symbol,
            "name": ticker_symbol,
            "trailing_pe": 10.0,
            "price_to_book": 1.0,
            "dividend_yield": 0.02,
            "market_cap": 1,
            "return_on_equity": 0.155,
            "revenue_growth": 0.082,
        }

    df = stock_price_api.fetch_universe_fundamentals(
        ["AAA.T"], tmp_path, fetch_fundamentals=fake_fetch_fundamentals
    )
    assert df["roe_pct"].tolist() == [15.5]
    assert df["revenue_growth_pct"].tolist() == [8.2]


def test_fetch_universe_fundamentals_handles_missing_roe_and_revenue_growth(tmp_path):
    def fake_fetch_fundamentals(ticker_symbol):
        return {
            "ticker": ticker_symbol,
            "name": ticker_symbol,
            "trailing_pe": 10.0,
            "price_to_book": 1.0,
            "dividend_yield": 0.02,
            "market_cap": 1,
            "return_on_equity": None,
            "revenue_growth": None,
        }

    df = stock_price_api.fetch_universe_fundamentals(
        ["AAA.T"], tmp_path, fetch_fundamentals=fake_fetch_fundamentals
    )
    assert df["roe_pct"].iloc[0] is None or pd.isna(df["roe_pct"].iloc[0])
    assert df["revenue_growth_pct"].iloc[0] is None or pd.isna(df["revenue_growth_pct"].iloc[0])
```

- [ ] **Step 5b: 上記テストが失敗することを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_stock_price_api.py -k roe_and_revenue_growth -v`
Expected: FAIL（`KeyError: 'roe_pct'`）

- [ ] **Step 6: `fetch_universe_fundamentals`を実装する**

`app/data_api/stock_price_api.py` に、`fetch_universe_fundamentals`関数の直前へ
ヘルパー関数を追加する:

```python
def _to_pct(value: float | None) -> float | None:
    """yfinanceが小数（例: 0.155 = 15.5%）で返す指標を、パーセント表示用に100倍する。"""
    return None if value is None else value * 100
```

`fetch_universe_fundamentals` 内の `rows.append(...)` ブロックを次のように変更する:

```python
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
                    # returnOnEquity/revenueGrowthは小数（例: 0.155 = 15.5%）で
                    # 返るため、dividend_yieldと異なり100倍してパーセント表示用にする。
                    "roe_pct": _to_pct(data.get("return_on_equity")),
                    "revenue_growth_pct": _to_pct(data.get("revenue_growth")),
                }
            )
```

- [ ] **Step 7: テストを実行し、全てPASSすることを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_stock_price_api.py -v`
Expected: 全件PASS（既存テストも含め回帰なし）

- [ ] **Step 8: コミット**

```bash
cd app
git add data_api/stock_price_api.py tests/test_stock_price_api.py
git commit -m "$(cat <<'EOF'
fetch_fundamentalsにROE・売上高伸び率を追加

AI戦略ビルダー機能のスクリーニング条件でROE・売上高伸び率を
扱えるようにする。既存フィールドは変更しないため、既存の
スクリーニングタブの挙動には影響しない。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `fetch_universe_price_histories` の追加

**Files:**
- Modify: `app/data_api/stock_price_api.py`（末尾に関数追加）
- Test: `app/tests/test_stock_price_api.py`

**Interfaces:**
- Consumes: `common.cache.read_cache/write_cache`, `common.concurrency.map_concurrently`,
  `common.logging_config.log_duration`（すべて既存、`fetch_universe_fundamentals`と同じ依存）
- Produces: `fetch_universe_price_histories(tickers: list[str], period: str, cache_dir: Path, fetch_price_history=fetch_price_history) -> dict[str, pd.Series]`
  （銘柄コード→終値時系列。取得失敗銘柄は結果から除外）

- [ ] **Step 1: 失敗するテストを書く**

`app/tests/test_stock_price_api.py` の末尾に追加する:

```python
def test_fetch_universe_price_histories_uses_cache_on_second_call(tmp_path):
    call_count = {"n": 0}
    dates = pd.date_range("2026-01-01", periods=3, freq="D")

    def fake_fetch_price_history(ticker_symbol, period="1mo"):
        call_count["n"] += 1
        return pd.DataFrame({"Close": [10.0, 11.0, 12.0]}, index=dates)

    tickers = ["AAA.T", "BBB.T"]
    result1 = stock_price_api.fetch_universe_price_histories(
        tickers, "1y", tmp_path, fetch_price_history=fake_fetch_price_history
    )
    assert call_count["n"] == 2
    assert result1["AAA.T"].tolist() == [10.0, 11.0, 12.0]

    result2 = stock_price_api.fetch_universe_price_histories(
        tickers, "1y", tmp_path, fetch_price_history=fake_fetch_price_history
    )
    assert call_count["n"] == 2
    assert result2["AAA.T"].tolist() == [10.0, 11.0, 12.0]


def test_fetch_universe_price_histories_skips_failed_ticker(tmp_path):
    dates = pd.date_range("2026-01-01", periods=2, freq="D")

    def fake_fetch_price_history(ticker_symbol, period="1mo"):
        if ticker_symbol == "BAD.T":
            raise ValueError("boom")
        return pd.DataFrame({"Close": [1.0, 2.0]}, index=dates)

    result = stock_price_api.fetch_universe_price_histories(
        ["AAA.T", "BAD.T"], "1y", tmp_path, fetch_price_history=fake_fetch_price_history
    )
    assert list(result.keys()) == ["AAA.T"]


def test_fetch_universe_price_histories_skips_empty_history(tmp_path):
    def fake_fetch_price_history(ticker_symbol, period="1mo"):
        return pd.DataFrame({"Close": []})

    result = stock_price_api.fetch_universe_price_histories(
        ["AAA.T"], "1y", tmp_path, fetch_price_history=fake_fetch_price_history
    )
    assert result == {}
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_stock_price_api.py -k fetch_universe_price_histories -v`
Expected: FAIL（`AttributeError: module 'data_api.stock_price_api' has no attribute 'fetch_universe_price_histories'`）

- [ ] **Step 3: 実装する**

`app/data_api/stock_price_api.py` の末尾（`fetch_universe_fundamentals`関数の後）に追加する:

```python
def fetch_universe_price_histories(
    tickers: list[str],
    period: str,
    cache_dir: Path,
    fetch_price_history=fetch_price_history,
) -> dict[str, pd.Series]:
    """複数銘柄の終値時系列をまとめて取得し、{ticker: pd.Series} として返す。

    strategy_builderの簡易バックテスト・銘柄選定実行画面で、絞り込み後の
    銘柄群の株価をまとめて取得する用途に使う。取得失敗・空データの銘柄は
    結果から除外する。
    """
    cache_key = "universe-prices-" + hashlib.sha256(
        f"{period}-{'-'.join(sorted(tickers))}".encode("utf-8")
    ).hexdigest()[:12]
    cached = read_cache(cache_dir, cache_key)
    if cached is not None:
        payload = json.loads(cached)
        return {
            ticker: pd.Series(
                data["values"], index=pd.to_datetime(data["dates"]), name="Close"
            )
            for ticker, data in payload.items()
        }

    with log_duration(logger, f"ユニバース株価一括取得（{len(tickers)}銘柄, period={period}）"):
        results = map_concurrently(
            tickers, lambda ticker: fetch_price_history(ticker, period=period)
        )
        prices_by_ticker: dict[str, pd.Series] = {}
        for ticker in tickers:
            history = results[ticker]
            if isinstance(history, Exception) or history is None or history.empty:
                continue
            prices_by_ticker[ticker] = history["Close"]

        write_cache(
            cache_dir,
            cache_key,
            json.dumps(
                {
                    ticker: {
                        "dates": [d.isoformat() for d in series.index],
                        "values": [float(v) for v in series],
                    }
                    for ticker, series in prices_by_ticker.items()
                }
            ),
        )
    return prices_by_ticker
```

Note: この関数は `common.concurrency.map_concurrently` を使うため、ファイル冒頭の
importに `from common.concurrency import map_concurrently` を追加する必要がある
（現状の `stock_price_api.py` はこのimportを持たない）。

- [ ] **Step 4: テストを実行し、全てPASSすることを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_stock_price_api.py -v`
Expected: 全件PASS

- [ ] **Step 5: コミット**

```bash
cd app
git add data_api/stock_price_api.py tests/test_stock_price_api.py
git commit -m "$(cat <<'EOF'
fetch_universe_price_historiesを追加

AI戦略ビルダーの簡易バックテスト・銘柄選定実行画面で、絞り込み後の
複数銘柄の株価をまとめて取得できるようにする
（fetch_universe_fundamentalsと同じ並行取得＋キャッシュのパターン）。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `render_mermaid` を `app_tabs/shared.py` に切り出す

**Files:**
- Modify: `app/app_tabs/shared.py`
- Modify: `app/app_tabs/sector/network_diagram.py`

**Interfaces:**
- Produces: `app_tabs.shared.render_mermaid(code: str, height: int = 400) -> None`
  （`app_tabs/sector/network_diagram.py`のprivate関数`_render_mermaid`を公開化して移動したもの。
  シグネチャ・実装は変更しない）

このタスクにはUI描画の直接テストがない（既存の`app_tabs/*.py`はいずれも未テスト）。
既存の回帰テストスイートが通ることと、インポートが解決することで検証する。

- [ ] **Step 1: `app_tabs/shared.py` に `render_mermaid` を追加する**

`app/app_tabs/shared.py` の末尾（`handle_table_selection`関数の後）に追加する:

```python
def render_mermaid(code: str, height: int = 400) -> None:
    """Mermaidコード文字列を、CDN経由のmermaid.js + svg-pan-zoom.jsを使って
    ドラッグパン・ホイールズーム可能なHTML埋め込みとして描画する。

    セクタータブの業種間ネットワーク図・AI戦略ビルダータブの選定銘柄向け
    業種ネットワーク図の両方から共通で呼ばれる。"""
    html = f"""
    <style>
      html, body {{ margin: 0; padding: 0; height: 100%; }}
      .mermaid {{ width: 100%; height: 100%; }}
      .mermaid svg {{
        width: 100% !important;
        height: 100% !important;
        max-width: none !important;
      }}
    </style>
    <div class="mermaid">{code}</div>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/svg-pan-zoom@3/dist/svg-pan-zoom.min.js"></script>
    <script>
      mermaid.initialize({{ startOnLoad: false }});
      mermaid.run({{ querySelector: ".mermaid" }}).then(function () {{
        var svgEl = document.querySelector(".mermaid svg");
        if (svgEl) {{
          var pz = svgPanZoom(svgEl, {{
            zoomEnabled: true,
            controlIconsEnabled: true,
            fit: false,
            center: true,
          }});
          var sizes = pz.getSizes();
          if (sizes.viewBox.height > 0 && sizes.viewBox.width > 0) {{
            var scaleToHeight = sizes.height / sizes.viewBox.height;
            var scaleToWidth = sizes.width / sizes.viewBox.width;
            pz.zoom(Math.min(scaleToHeight, scaleToWidth * 2));
            pz.center();
          }}
        }}
      }});
    </script>
    """
    st.iframe(html, height=height)
```

- [ ] **Step 2: `network_diagram.py` からローカル定義を削除し、共有版を使う**

`app/app_tabs/sector/network_diagram.py` の内容を次の内容で置き換える（`_render_mermaid`
関数を削除し、`app_tabs.shared.render_mermaid` を使う）:

```python
"""セクタータブ: 業種間ネットワーク（全ペア俯瞰）の描画。"""

import pandas as pd
import streamlit as st

from sector_analysis.network import build_mermaid_lead_lag_graph

from app_tabs.shared import render_mermaid


def render_network_diagram(network_pairs: list[dict], height: int) -> None:
    """全業種ペアの直近のウェーブレット分析結果を集約し、リード・ラグのネットワーク図として描画する。"""
    st.subheader(
        "業種間ネットワーク（全ペア俯瞰）",
        help=(
            "全業種ペアについて、直近20営業日のウェーブレット分析結果を集約し、"
            "周期の長さごとにどの業種が誰をリードしているかを俯瞰します。"
        ),
    )
    st.caption(
        "コヒーレンス（関係の確からしさ）が閾値以上のペアのみを矢印で表示します。"
        "矢印の元が先行業種、矢印の先が追随業種です。"
    )

    network_df = pd.DataFrame(network_pairs)
    col_band, col_threshold = st.columns(2)
    with col_band:
        network_band = st.selectbox(
            "周期帯", ["短期", "中期", "長期"], index=1, key="network_band"
        )
    with col_threshold:
        network_threshold = st.slider(
            "コヒーレンス閾値（これ以上のペアのみ表示）",
            0.0,
            1.0,
            0.5,
            0.05,
            key="network_threshold",
        )

    mermaid_code = build_mermaid_lead_lag_graph(
        network_df, network_band, network_threshold
    )
    if mermaid_code is None:
        st.info(
            "十分な確信度を持つ関係が見つかりませんでした。閾値を下げてみてください。"
        )
    else:
        render_mermaid(mermaid_code, height=height)
```

- [ ] **Step 3: インポートが解決することを確認する**

Run: `cd app && .venv/Scripts/python.exe -c "import app_tabs.shared; import app_tabs.sector.network_diagram"`
Expected: エラーなく終了する

- [ ] **Step 4: 既存の回帰テストスイートを実行する**

Run: `cd app && .venv/Scripts/python.exe -m pytest -v`
Expected: 全件PASS（既存テストのみで、まだ`app_tabs`向けの新規テストはない）

- [ ] **Step 5: コミット**

```bash
cd app
git add app_tabs/shared.py app_tabs/sector/network_diagram.py
git commit -m "$(cat <<'EOF'
render_mermaidをapp_tabs/shared.pyに切り出す

AI戦略ビルダータブでも業種間ネットワーク図を描画できるよう、
セクタータブのnetwork_diagram.pyにprivate実装されていたMermaid
描画処理を共有ヘルパーとして公開する。動作は変更しない。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `run_or_load_sector_rotation` を `app_tabs/shared.py` に切り出す

**Files:**
- Modify: `app/app_tabs/shared.py`
- Modify: `app/app_tabs/sector/tab.py`

**Interfaces:**
- Consumes: `sector_analysis.correlation.compute_lead_lag_pairs/compute_sector_returns`,
  `sector_analysis.wavelet.compute_all_pairs_dominant_lag/serialize_sector_returns`,
  `prompt_patterns.sector_rotation.generate_sector_rotation_comments`,
  `screening.sectors.SECTOR_MAP`, `screening.universe.UNIVERSE`（すべて既存、変更なし）
- Produces: `app_tabs.shared.run_or_load_sector_rotation(period: str, force_regenerate: bool) -> dict | None`
  （戻り値は既存の`sector_payload`と同じキー構成に加え、新規キー
  `"ticker_latest_return_pct": dict[str, float]` を持つ。分析可能な銘柄が0件ならNone。
  副作用として `st.session_state["sector_payload"]` を更新する）

このタスクも直接の自動テストは持たない（UI/セッション状態に依存する処理のため）。
既存の回帰テストスイートで、`sector_analysis`側の純粋ロジックに変更がないことを確認する。

- [ ] **Step 1: `app_tabs/shared.py` に `run_or_load_sector_rotation` を追加する**

`app/app_tabs/shared.py` の先頭import部分を次のように変更する（既存のimportに追記する形。
`hashlib`, `json`, `logging`と、セクター分析関連のimportを追加する）:

```python
"""複数タブ間で共有するキャッシュ付きデータ取得関数・銘柄詳細ダイアログ・
テーブル選択ヘルパー・セクターローテーション分析の共通実行処理、
および保存先パスの定数。
"""

import hashlib
import json
import logging
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from analysis_agents.fundamental_agent import analyze_fundamentals
from common.cache import read_cache, write_cache
from common.concurrency import map_concurrently
from common.disclaimer import DISCLAIMER_NOTICE
from common.logging_config import log_duration
from data_api.llm_client import call_llm
from data_api.stock_price_api import fetch_japanese_name, fetch_news, fetch_price_history
from prompt_patterns.sector_rotation import generate_sector_rotation_comments
from screening.sectors import SECTOR_MAP
from screening.universe import UNIVERSE
from sector_analysis.correlation import compute_lead_lag_pairs, compute_sector_returns
from sector_analysis.wavelet import compute_all_pairs_dominant_lag, serialize_sector_returns
from stock_detail.detail import generate_stock_detail

logger = logging.getLogger(__name__)

# 保有銘柄データやAPI取得結果のキャッシュを保存するディレクトリ構成
APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
HOLDINGS_PATH = DATA_DIR / "holdings.json"
SECTOR_DISPLAY_SETTINGS_PATH = DATA_DIR / "sector_display_settings.json"
CACHE_DIR = DATA_DIR / "cache"
```

（`@st.cache_data`でデコレートされた既存の4関数、`show_stock_detail_dialog`,
`handle_table_selection`, Task 3で追加した`render_mermaid`はそのまま変更しない）

ファイル末尾に追加する:

```python
def run_or_load_sector_rotation(period: str, force_regenerate: bool) -> dict | None:
    """セクターローテーション分析を実行または既存キャッシュから読み込み、
    ペイロード（pairs/sector_returns/network_pairs/comments/
    ticker_latest_return_pct等）を返す。分析可能な銘柄が1件もない場合はNoneを返す。

    セクタータブ・AI戦略ビルダータブの両方から呼ばれる共通処理。同一の
    period・UNIVERSEであればディスクキャッシュを共有し、二重計算を避ける。
    実行結果は st.session_state["sector_payload"] にも保存する。
    """
    cache_key = "sector-rotation-" + hashlib.sha256(
        f"{period}-{'-'.join(sorted(UNIVERSE))}".encode("utf-8")
    ).hexdigest()[:12]
    cached_payload = None if force_regenerate else read_cache(CACHE_DIR, cache_key)
    payload = json.loads(cached_payload) if cached_payload is not None else None
    if payload is not None and (
        "sector_returns" not in payload
        or "network_pairs" not in payload
        or "ticker_latest_return_pct" not in payload
    ):
        # 旧スキーマ（ticker_latest_return_pct未保存等）のキャッシュは再計算して移行する
        payload = None

    if payload is None:
        with log_duration(logger, f"セクターローテーション分析実行（{period}）"):
            skipped_tickers = []
            prices_by_ticker = {}
            with st.spinner(f"株価データを取得中...（{len(UNIVERSE)}銘柄）"):
                price_results = map_concurrently(
                    UNIVERSE, lambda ticker: cached_fetch_price_history(ticker, period)
                )
            for ticker in UNIVERSE:
                history = price_results[ticker]
                if isinstance(history, Exception) or history is None or history.empty:
                    skipped_tickers.append(ticker)
                else:
                    prices_by_ticker[ticker] = history["Close"]

            if not prices_by_ticker:
                logger.warning("セクターローテーション分析実行不可（対象銘柄が0件）")
                return None

            # 業種集計前の銘柄別直近日次リターン（AI戦略ビルダーの
            # 「本日の値上がり銘柄」検出に使う）
            ticker_latest_return_pct: dict[str, float] = {}
            for ticker, prices in prices_by_ticker.items():
                daily_returns = prices.pct_change()
                if len(daily_returns) >= 2 and pd.notna(daily_returns.iloc[-1]):
                    ticker_latest_return_pct[ticker] = float(daily_returns.iloc[-1] * 100)

            sector_returns = compute_sector_returns(prices_by_ticker, SECTOR_MAP)
            excluded_sectors = sorted(set(SECTOR_MAP.values()) - set(sector_returns.keys()))
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
                "ticker_latest_return_pct": ticker_latest_return_pct,
            }
            write_cache(CACHE_DIR, cache_key, json.dumps(payload, ensure_ascii=False))

    st.session_state["sector_payload"] = payload
    return payload
```

- [ ] **Step 2: `app_tabs/sector/tab.py` を簡素化する**

`app/app_tabs/sector/tab.py` の内容全体を次の内容で置き換える（`if run_clicked:` 内の
キャッシュ確認・並列株価取得・分析計算・キャッシュ書き込みのロジックを
`run_or_load_sector_rotation`呼び出し1行に置き換え、不要になったimportを削除する）:

```python
"""セクタータブ: セクターローテーション分析のエントリーポイント。
表示設定・分析実行（データ取得・キャッシュ）を担当し、個別グラフの描画は
app_tabs.sector 配下の各モジュールに委譲する。
"""

import logging

import pandas as pd
import streamlit as st

from common.disclaimer import DISCLAIMER_NOTICE
from sector_analysis.display_settings import (
    load_sector_display_settings,
    save_sector_display_settings,
)

from app_tabs.sector.ai_comments import render_ai_comments
from app_tabs.sector.heatmap import render_heatmap
from app_tabs.sector.network_diagram import render_network_diagram
from app_tabs.sector.pairs_table import render_pairs_table
from app_tabs.sector.wavelet_analysis import render_wavelet_analysis
from app_tabs.shared import SECTOR_DISPLAY_SETTINGS_PATH, run_or_load_sector_rotation

logger = logging.getLogger(__name__)


def render_sector_tab() -> None:
    logger.info("セクターローテーションタブを表示")
    st.header("セクターローテーション")
    st.caption(
        "UNIVERSE銘柄を17業種に分類し、業種間の値動きの時差相関（リード・ラグ）を"
        "過去の株価データから計算します。あくまで過去の統計的傾向であり、"
        "将来の値動きを保証するものではありません。"
    )

    display_settings = load_sector_display_settings(SECTOR_DISPLAY_SETTINGS_PATH)
    section_labels = {
        "heatmap": "業種間相関ヒートマップ",
        "pairs_table": "リード・ラグ上位ペア",
        "ai_comments": "相関上位5ペアのAIコメント",
        "network_diagram": "業種間ネットワーク（全ペア俯瞰）",
        "wavelet_analysis": "ウェーブレット分析",
    }
    with st.expander("表示設定"):
        st.caption(
            "表示のON/OFFと並び順を指定できます"
            "（設定は次回起動時も保持されます）。"
        )
        editor_df = pd.DataFrame(
            [
                {
                    "key": key,
                    "セクション": label,
                    "表示": display_settings["visible"][key],
                    "順序": display_settings["order"][key],
                }
                for key, label in section_labels.items()
            ]
        )
        edited_df = st.data_editor(
            editor_df,
            column_config={
                "key": None,
                "セクション": st.column_config.TextColumn(disabled=True),
                "表示": st.column_config.CheckboxColumn(),
                "順序": st.column_config.NumberColumn(min_value=1, max_value=5, step=1),
            },
            hide_index=True,
            key="sector_section_editor",
        )
        new_visible = {
            key: bool(value) for key, value in zip(edited_df["key"], edited_df["表示"])
        }
        new_order = {
            key: (
                int(value)
                if pd.notna(value)
                else display_settings["order"][key]
            )
            for key, value in zip(edited_df["key"], edited_df["順序"])
        }

        new_height = dict(display_settings["height"])
        height_specs = [
            ("heatmap", "業種間相関ヒートマップの高さ (px)"),
            ("network_diagram", "業種間ネットワークの高さ (px)"),
            ("wavelet_analysis", "ウェーブレット分析ヒートマップの高さ (px)"),
        ]
        for key, label in height_specs:
            if new_visible[key]:
                new_height[key] = st.slider(
                    label,
                    250,
                    900,
                    display_settings["height"][key],
                    50,
                    key=f"sector_height_{key}",
                )

        new_display_settings = {
            "visible": new_visible,
            "order": new_order,
            "height": new_height,
        }
        if new_display_settings != display_settings:
            save_sector_display_settings(SECTOR_DISPLAY_SETTINGS_PATH, new_display_settings)
            display_settings = new_display_settings

    col_period, col_regen, col_run = st.columns(3)
    with col_period:
        sector_period = st.selectbox(
            "取得期間",
            ["6mo", "1y", "2y"],
            index=1,
            key="sector_period",
            help=(
                "株価データを取得する期間です。長いほど長期の周期（サイクル）分析の"
                "精度が上がりますが、取得に時間がかかります。"
            ),
        )
    with col_regen:
        sector_force_regenerate = st.checkbox(
            "キャッシュを無視して再生成する",
            key="sector_force_regenerate",
            help=(
                "前回と同じ期間で分析済みの場合、通常は保存済みの結果を再利用します。"
                "最新データで計算し直したいときにチェックしてください。"
            ),
        )
    with col_run:
        run_clicked = st.button(
            "分析を実行",
            help=(
                "初回実行時は228銘柄のデータ取得のため30秒程度かかります"
                "（2回目以降はキャッシュにより高速です）。"
            ),
        )

    if run_clicked:
        payload = run_or_load_sector_rotation(sector_period, sector_force_regenerate)
        if payload is None:
            st.error("分析可能な銘柄がありませんでした。")

    if st.session_state.get("sector_payload") is not None:
        payload = st.session_state["sector_payload"]
        pairs = payload["pairs"]

        if not pairs:
            st.info("有効な業種ペアがありませんでした。")

        section_renderers = {
            "heatmap": lambda: render_heatmap(pairs, display_settings["height"]["heatmap"]),
            "pairs_table": lambda: render_pairs_table(pairs),
            "ai_comments": lambda: render_ai_comments(pairs, payload["comments"]),
            "network_diagram": lambda: render_network_diagram(
                payload["network_pairs"], display_settings["height"]["network_diagram"]
            ),
            "wavelet_analysis": lambda: render_wavelet_analysis(
                payload, pairs, sector_period, display_settings["height"]["wavelet_analysis"]
            ),
        }
        ordered_keys = sorted(
            section_renderers, key=lambda k: display_settings["order"][k]
        )
        for key in ordered_keys:
            if key in ("heatmap", "pairs_table", "ai_comments") and not pairs:
                continue
            if display_settings["visible"][key]:
                section_renderers[key]()

        if payload["skipped_tickers"]:
            st.info(
                "データ取得・データ不足によりスキップした銘柄: "
                + ", ".join(payload["skipped_tickers"])
            )
        if payload["excluded_sectors"]:
            st.info(
                "構成銘柄が取得できず分析から除外した業種: "
                + ", ".join(payload["excluded_sectors"])
            )

        st.markdown(DISCLAIMER_NOTICE)
```

- [ ] **Step 3: インポートが解決することを確認する**

Run: `cd app && .venv/Scripts/python.exe -c "import app_tabs.shared; import app_tabs.sector.tab"`
Expected: エラーなく終了する

- [ ] **Step 4: 既存の回帰テストスイートを実行する**

Run: `cd app && .venv/Scripts/python.exe -m pytest -v`
Expected: 全件PASS

- [ ] **Step 5: コミット**

```bash
cd app
git add app_tabs/shared.py app_tabs/sector/tab.py
git commit -m "$(cat <<'EOF'
run_or_load_sector_rotationをapp_tabs/shared.pyに切り出す

AI戦略ビルダータブでもセクターローテーション分析を実行・再利用
できるよう、セクタータブに埋め込まれていた分析実行ロジックを
共有関数として切り出す。ticker_latest_return_pct（銘柄別の
直近日次リターン）を戻り値に追加する。既存の動作は変更しない。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `strategy_builder` パッケージと `storage.py` の作成

**Files:**
- Create: `app/strategy_builder/__init__.py`
- Create: `app/strategy_builder/storage.py`
- Test: `app/tests/test_strategy_builder_storage.py`

**Interfaces:**
- Produces: `strategy_builder.storage.load_strategies(path: Path) -> list[dict]`,
  `strategy_builder.storage.save_strategy(path: Path, strategy: dict) -> None`
  （`strategy`は最低限`"strategy_name": str`キーを持つdict）

- [ ] **Step 1: パッケージと空のテストファイルを作る**

Run:
```bash
cd app
mkdir strategy_builder
type nul > strategy_builder\__init__.py
```
（Windows/PowerShellの場合。bashなら `mkdir -p strategy_builder && touch strategy_builder/__init__.py`）

- [ ] **Step 2: 失敗するテストを書く**

`app/tests/test_strategy_builder_storage.py` を新規作成する:

```python
import json

from strategy_builder.storage import load_strategies, save_strategy


def test_load_strategies_returns_empty_list_when_file_missing(tmp_path):
    assert load_strategies(tmp_path / "missing.json") == []


def test_load_strategies_returns_empty_list_on_malformed_json(tmp_path):
    path = tmp_path / "strategies.json"
    path.write_text("not json", encoding="utf-8")
    assert load_strategies(path) == []


def test_load_strategies_returns_empty_list_when_not_a_list(tmp_path):
    path = tmp_path / "strategies.json"
    path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    assert load_strategies(path) == []


def test_save_strategy_appends_new_strategy(tmp_path):
    path = tmp_path / "strategies.json"
    save_strategy(path, {"strategy_name": "割安成長株", "conditions": []})
    assert load_strategies(path) == [{"strategy_name": "割安成長株", "conditions": []}]


def test_save_strategy_overwrites_existing_strategy_with_same_name(tmp_path):
    path = tmp_path / "strategies.json"
    save_strategy(path, {"strategy_name": "割安成長株", "conditions": [1]})
    save_strategy(path, {"strategy_name": "割安成長株", "conditions": [2]})
    strategies = load_strategies(path)
    assert len(strategies) == 1
    assert strategies[0]["conditions"] == [2]


def test_save_strategy_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "strategies.json"
    save_strategy(path, {"strategy_name": "A", "conditions": []})
    assert path.exists()
```

- [ ] **Step 3: テストが失敗することを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_strategy_builder_storage.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'strategy_builder.storage'`）

- [ ] **Step 4: `storage.py`を実装する**

`app/strategy_builder/storage.py` を新規作成する:

```python
"""確定済み投資戦略（AI戦略ビルダー機能）をJSONファイルとして永続化・読み込みするモジュール。"""

import json
from pathlib import Path


def load_strategies(path: Path) -> list[dict]:
    """保存済み戦略の一覧をJSONファイルから読み込む。ファイルが存在しない、
    JSONとして壊れている、あるいは想定外の形式（リストでない）の場合は、
    エラーにせず空リストを返す。"""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return data


def save_strategy(path: Path, strategy: dict) -> None:
    """戦略を1件、保存済み一覧に追記する。同名（strategy_name）の戦略が
    既にあれば上書きする。保存先ディレクトリが存在しない場合は作成し、
    日本語をそのまま読める形式（ensure_ascii=False）で整形して書き出す。"""
    strategies = load_strategies(path)
    name = strategy.get("strategy_name")
    strategies = [s for s in strategies if s.get("strategy_name") != name]
    strategies.append(strategy)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(strategies, ensure_ascii=False, indent=2), encoding="utf-8"
    )
```

- [ ] **Step 5: テストを実行し、全てPASSすることを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_strategy_builder_storage.py -v`
Expected: 全件PASS

- [ ] **Step 6: コミット**

```bash
cd app
git add strategy_builder/__init__.py strategy_builder/storage.py tests/test_strategy_builder_storage.py
git commit -m "$(cat <<'EOF'
AI戦略ビルダー: 戦略JSONの保存・読込モジュールを追加

portfolio_management/storage.pyと同パターンで、確定済み戦略を
strategies.jsonに永続化するstrategy_builder/storage.pyを新設する。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `strategy_builder/conditions.py` の作成

**Files:**
- Create: `app/strategy_builder/conditions.py`
- Test: `app/tests/test_strategy_builder_conditions.py`

**Interfaces:**
- Consumes: なし（pandas標準のみ）
- Produces:
  - `strategy_builder.conditions.apply_strategy_conditions(df: pd.DataFrame, strategy: dict) -> pd.DataFrame`
  - `strategy_builder.conditions.sort_by_strategy(df: pd.DataFrame, strategy: dict) -> pd.DataFrame`
  - `strategy_builder.conditions.build_match_reason(row: pd.Series, conditions: list[dict]) -> str`
  - 戦略JSONの`indicator`は `"PER", "PBR", "ROE", "DIVIDEND_YIELD", "REVENUE_GROWTH", "MARKET_CAP"` のいずれか、
    `operator`は `"LESS_THAN", "LESS_EQUAL", "GREATER_THAN", "GREATER_EQUAL", "EQUALS"` のいずれか。
    DataFrameは`per`, `pbr`, `roe_pct`, `dividend_yield_pct`, `revenue_growth_pct`, `market_cap`
    列を持つ想定（Task 1で`fetch_universe_fundamentals`に追加済み）。

- [ ] **Step 1: 失敗するテストを書く**

`app/tests/test_strategy_builder_conditions.py` を新規作成する:

```python
import pandas as pd

from strategy_builder.conditions import (
    apply_strategy_conditions,
    build_match_reason,
    sort_by_strategy,
)


def test_apply_strategy_conditions_filters_rows_matching_all_conditions():
    df = pd.DataFrame(
        [
            {"ticker": "AAA", "per": 12.0, "roe_pct": 15.0},
            {"ticker": "BBB", "per": 20.0, "roe_pct": 5.0},
        ]
    )
    strategy = {
        "conditions": [
            {"indicator": "PER", "operator": "LESS_THAN", "value": 15},
            {"indicator": "ROE", "operator": "GREATER_THAN", "value": 10},
        ]
    }
    result = apply_strategy_conditions(df, strategy)
    assert result["ticker"].tolist() == ["AAA"]


def test_apply_strategy_conditions_ignores_unknown_indicator():
    df = pd.DataFrame([{"ticker": "AAA", "per": 12.0}])
    strategy = {"conditions": [{"indicator": "UNKNOWN", "operator": "LESS_THAN", "value": 5}]}
    result = apply_strategy_conditions(df, strategy)
    assert result["ticker"].tolist() == ["AAA"]


def test_apply_strategy_conditions_ignores_unknown_operator():
    df = pd.DataFrame([{"ticker": "AAA", "per": 12.0}])
    strategy = {"conditions": [{"indicator": "PER", "operator": "UNKNOWN_OP", "value": 5}]}
    result = apply_strategy_conditions(df, strategy)
    assert result["ticker"].tolist() == ["AAA"]


def test_apply_strategy_conditions_excludes_missing_values():
    df = pd.DataFrame([{"ticker": "AAA", "per": None}])
    strategy = {"conditions": [{"indicator": "PER", "operator": "LESS_THAN", "value": 15}]}
    result = apply_strategy_conditions(df, strategy)
    assert result.empty


def test_apply_strategy_conditions_supports_equals_operator():
    df = pd.DataFrame([{"ticker": "AAA", "market_cap": 100}, {"ticker": "BBB", "market_cap": 200}])
    strategy = {"conditions": [{"indicator": "MARKET_CAP", "operator": "EQUALS", "value": 100}]}
    result = apply_strategy_conditions(df, strategy)
    assert result["ticker"].tolist() == ["AAA"]


def test_sort_by_strategy_sorts_descending_by_indicator():
    df = pd.DataFrame([{"ticker": "AAA", "roe_pct": 5.0}, {"ticker": "BBB", "roe_pct": 15.0}])
    strategy = {"sort_by": "ROE", "order": "DESC"}
    result = sort_by_strategy(df, strategy)
    assert result["ticker"].tolist() == ["BBB", "AAA"]


def test_sort_by_strategy_sorts_ascending_when_order_is_asc():
    df = pd.DataFrame([{"ticker": "AAA", "roe_pct": 5.0}, {"ticker": "BBB", "roe_pct": 15.0}])
    strategy = {"sort_by": "ROE", "order": "ASC"}
    result = sort_by_strategy(df, strategy)
    assert result["ticker"].tolist() == ["AAA", "BBB"]


def test_sort_by_strategy_returns_unchanged_when_sort_by_unknown():
    df = pd.DataFrame([{"ticker": "AAA", "roe_pct": 5.0}])
    strategy = {"sort_by": "UNKNOWN", "order": "DESC"}
    result = sort_by_strategy(df, strategy)
    assert result["ticker"].tolist() == ["AAA"]


def test_build_match_reason_includes_actual_value_and_threshold():
    row = pd.Series({"per": 12.3, "roe_pct": 15.2})
    conditions = [
        {"indicator": "PER", "operator": "LESS_THAN", "value": 15},
        {"indicator": "ROE", "operator": "GREATER_THAN", "value": 10},
    ]
    reason = build_match_reason(row, conditions)
    assert "PER 12.3（条件: 15未満）" in reason
    assert "ROE 15.2（条件: 10より大）" in reason


def test_build_match_reason_skips_missing_values():
    row = pd.Series({"per": None, "roe_pct": 15.2})
    conditions = [
        {"indicator": "PER", "operator": "LESS_THAN", "value": 15},
        {"indicator": "ROE", "operator": "GREATER_THAN", "value": 10},
    ]
    reason = build_match_reason(row, conditions)
    assert "PER" not in reason
    assert "ROE 15.2（条件: 10より大）" in reason


def test_build_match_reason_returns_placeholder_when_no_conditions_match():
    row = pd.Series({"per": 12.3})
    reason = build_match_reason(
        row, [{"indicator": "UNKNOWN", "operator": "LESS_THAN", "value": 1}]
    )
    assert reason == "条件詳細なし"
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_strategy_builder_conditions.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: `conditions.py`を実装する**

`app/strategy_builder/conditions.py` を新規作成する:

```python
"""AI戦略ビルダーが生成する戦略JSON（indicator/operatorスキーマ）を、
実際のDataFrameへの絞り込み・並び替え・判定理由生成に変換するモジュール。

既存の prompt_patterns/screening.py が使う field/記号演算子スキーマとは
別スキーマとして扱う（依頼書のシステムプロンプトが定めるJSON形式に準拠する）。
"""

import operator

import pandas as pd

# indicator名（大文字表記）→ DataFrameの列名。
_INDICATOR_COLUMNS: dict[str, str] = {
    "PER": "per",
    "PBR": "pbr",
    "ROE": "roe_pct",
    "DIVIDEND_YIELD": "dividend_yield_pct",
    "REVENUE_GROWTH": "revenue_growth_pct",
    "MARKET_CAP": "market_cap",
}

# indicatorの日本語表示ラベル（判定理由の文字列生成に使う）。
_INDICATOR_LABELS: dict[str, str] = {
    "PER": "PER",
    "PBR": "PBR",
    "ROE": "ROE",
    "DIVIDEND_YIELD": "配当利回り",
    "REVENUE_GROWTH": "売上高伸び率",
    "MARKET_CAP": "時価総額",
}

# operator名 → (比較関数, 判定理由に使う日本語表現)。
_OPERATORS: dict[str, tuple] = {
    "LESS_THAN": (operator.lt, "未満"),
    "LESS_EQUAL": (operator.le, "以下"),
    "GREATER_THAN": (operator.gt, "より大"),
    "GREATER_EQUAL": (operator.ge, "以上"),
    "EQUALS": (operator.eq, "と一致"),
}


def apply_strategy_conditions(df: pd.DataFrame, strategy: dict) -> pd.DataFrame:
    """戦略JSONの`conditions`を順に適用し、絞り込んだDataFrameを返す。

    存在しないindicatorや未知のoperatorは無視してスキップすることで、
    LLM出力のゆれがあっても処理全体を落とさない（既存のapply_filtersと同方針）。
    """
    result = df
    for condition in strategy.get("conditions", []):
        indicator = condition.get("indicator")
        op_name = condition.get("operator")
        value = condition.get("value")
        column = _INDICATOR_COLUMNS.get(indicator)
        op_entry = _OPERATORS.get(op_name)
        if column is None or column not in result.columns or op_entry is None:
            continue
        op_func, _ = op_entry
        mask = result[column].notna() & op_func(result[column], value)
        result = result[mask]
    return result


def sort_by_strategy(df: pd.DataFrame, strategy: dict) -> pd.DataFrame:
    """戦略JSONの`sort_by`/`order`でDataFrameを並び替える。

    `sort_by`が既知のindicatorに対応する列でない場合は、並び替えを行わず
    そのまま返す。
    """
    sort_by = strategy.get("sort_by")
    column = _INDICATOR_COLUMNS.get(sort_by)
    if column is None or column not in df.columns:
        return df
    ascending = strategy.get("order") != "DESC"
    return df.sort_values(column, ascending=ascending)


def build_match_reason(row: pd.Series, conditions: list[dict]) -> str:
    """1銘柄の判定理由を、条件ごとの実際の値と閾値から機械的に組み立てる。

    LLMを呼ばず決定的に生成することで、判定理由の正確性と再現性を保証する。
    """
    parts = []
    for condition in conditions:
        indicator = condition.get("indicator")
        op_name = condition.get("operator")
        value = condition.get("value")
        column = _INDICATOR_COLUMNS.get(indicator)
        op_entry = _OPERATORS.get(op_name)
        if column is None or column not in row.index or op_entry is None:
            continue
        actual = row[column]
        if pd.isna(actual):
            continue
        _, op_label = op_entry
        label = _INDICATOR_LABELS.get(indicator, indicator)
        parts.append(f"{label} {round(float(actual), 1)}（条件: {value}{op_label}）")
    return " / ".join(parts) if parts else "条件詳細なし"
```

- [ ] **Step 4: テストを実行し、全てPASSすることを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_strategy_builder_conditions.py -v`
Expected: 全件PASS

- [ ] **Step 5: コミット**

```bash
cd app
git add strategy_builder/conditions.py tests/test_strategy_builder_conditions.py
git commit -m "$(cat <<'EOF'
AI戦略ビルダー: 戦略JSON条件の適用・並び替え・判定理由生成を追加

依頼書のシステムプロンプトが定めるindicator/operatorスキーマの
戦略JSONを、DataFrameへの絞り込み・並び替えと、条件ごとの実際の
値を含む判定理由文字列に変換するconditions.pyを新設する。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `strategy_builder/backtest.py` の作成

**Files:**
- Create: `app/strategy_builder/backtest.py`
- Test: `app/tests/test_strategy_builder_backtest.py`

**Interfaces:**
- Consumes: なし（pandas標準のみ）
- Produces: `strategy_builder.backtest.run_strategy_backtest(prices_by_ticker: dict[str, pd.Series]) -> dict`
  戻り値のキー: `total_return_pct: float`, `max_drawdown_pct: float`, `win_rate_pct: float`,
  `equity_curve: pd.Series`, `ticker_returns: dict[str, float]`

- [ ] **Step 1: 失敗するテストを書く**

`app/tests/test_strategy_builder_backtest.py` を新規作成する:

```python
import pandas as pd

from strategy_builder.backtest import run_strategy_backtest


def test_run_strategy_backtest_computes_equal_weight_return_and_flat_drawdown():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    prices_by_ticker = {
        "AAA.T": pd.Series([100.0, 110.0, 121.0], index=dates),
        "BBB.T": pd.Series([50.0, 50.0, 55.0], index=dates),
    }
    result = run_strategy_backtest(prices_by_ticker)
    assert result["total_return_pct"] == 15.5
    assert result["max_drawdown_pct"] == 0.0
    assert result["win_rate_pct"] == 100.0
    assert result["ticker_returns"] == {"AAA.T": 21.0, "BBB.T": 10.0}
    assert result["equity_curve"].tolist() == [100.0, 105.0, 115.5]


def test_run_strategy_backtest_computes_max_drawdown_for_single_ticker_dip():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices_by_ticker = {"AAA.T": pd.Series([100.0, 130.0, 90.0, 120.0], index=dates)}
    result = run_strategy_backtest(prices_by_ticker)
    assert result["total_return_pct"] == 20.0
    assert result["max_drawdown_pct"] == -30.77
    assert result["win_rate_pct"] == 100.0


def test_run_strategy_backtest_handles_staggered_start_dates():
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    prices_by_ticker = {
        "AAA.T": pd.Series([100.0] * 5, index=dates),
        "BBB.T": pd.Series([50.0, 55.0, 60.0], index=dates[2:]),
    }
    result = run_strategy_backtest(prices_by_ticker)
    assert result["equity_curve"].tolist() == [100.0, 100.0, 100.0, 105.0, 110.0]
    assert result["ticker_returns"] == {"AAA.T": 0.0, "BBB.T": 20.0}
    assert result["win_rate_pct"] == 50.0


def test_run_strategy_backtest_returns_zeroed_result_for_empty_input():
    result = run_strategy_backtest({})
    assert result["total_return_pct"] == 0.0
    assert result["max_drawdown_pct"] == 0.0
    assert result["win_rate_pct"] == 0.0
    assert result["equity_curve"].empty
    assert result["ticker_returns"] == {}


def test_run_strategy_backtest_skips_ticker_with_insufficient_data():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    prices_by_ticker = {
        "AAA.T": pd.Series([100.0, 110.0, 121.0], index=dates),
        "SHORT.T": pd.Series([10.0], index=dates[:1]),
    }
    result = run_strategy_backtest(prices_by_ticker)
    assert "SHORT.T" not in result["ticker_returns"]
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_strategy_builder_backtest.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: `backtest.py`を実装する**

`app/strategy_builder/backtest.py` を新規作成する:

```python
"""AI戦略ビルダーの簡易バックテスト: 現在の財務指標で選定した銘柄群を、
過去に遡って均等金額で購入・保有し続けた場合の資産推移をシミュレーションする。

過去の各時点で同条件を満たしていたかは考慮しないため、ルックアヘッド
バイアスを含む簡易シミュレーションである（詳細は設計書を参照）。
"""

import logging

import pandas as pd

from common.logging_config import log_duration

logger = logging.getLogger(__name__)


def run_strategy_backtest(prices_by_ticker: dict[str, pd.Series]) -> dict:
    """各銘柄の株価をその銘柄自身の開始日=100に正規化し、日次で銘柄平均を
    とった「等金額購入・保有」の資産推移から、累積リターン・最大ドローダウン・
    勝率を算出する。

    勝率は「期間トータルリターンがプラスだった銘柄数の割合」と定義する
    （買い持ち戦略にはポジション0/1の概念がないため、単一銘柄・テクニカル
    戦略向けの portfolio_management.backtest._finalize_backtest とは
    勝率の定義が異なる）。

    銘柄によって株価データの開始日が異なる場合（新規上場等）は、共通の
    日付インデックスのunion上でNaNを許容し、平均計算はskipnaで行う。

    prices_by_tickerが空、または全銘柄が2営業日未満のデータしか
    持たない場合は空の結果（equity_curveが空のSeries）を返す。
    """
    with log_duration(logger, f"戦略バックテスト計算（{len(prices_by_ticker)}銘柄）"):
        normalized_series = {}
        ticker_returns: dict[str, float] = {}
        for ticker, prices in prices_by_ticker.items():
            valid = prices.dropna()
            if len(valid) < 2:
                continue
            start = valid.iloc[0]
            if start == 0:
                continue
            normalized_series[ticker] = prices / start * 100
            ticker_returns[ticker] = round((valid.iloc[-1] / start - 1) * 100, 2)

        if not normalized_series:
            return {
                "total_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "win_rate_pct": 0.0,
                "equity_curve": pd.Series(dtype=float),
                "ticker_returns": {},
            }

        combined = pd.concat(normalized_series.values(), axis=1)
        equity_curve = combined.mean(axis=1, skipna=True).dropna()

        total_return_pct = round(
            (equity_curve.iloc[-1] / equity_curve.iloc[0] - 1) * 100, 2
        )
        running_max = equity_curve.cummax()
        drawdown = equity_curve / running_max - 1
        max_drawdown_pct = round(drawdown.min() * 100, 2)
        win_rate_pct = round(
            sum(1 for r in ticker_returns.values() if r > 0)
            / len(ticker_returns)
            * 100,
            2,
        )

        return {
            "total_return_pct": total_return_pct,
            "max_drawdown_pct": max_drawdown_pct,
            "win_rate_pct": win_rate_pct,
            "equity_curve": equity_curve,
            "ticker_returns": ticker_returns,
        }
```

- [ ] **Step 4: テストを実行し、全てPASSすることを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_strategy_builder_backtest.py -v`
Expected: 全件PASS

- [ ] **Step 5: コミット**

```bash
cd app
git add strategy_builder/backtest.py tests/test_strategy_builder_backtest.py
git commit -m "$(cat <<'EOF'
AI戦略ビルダー: 簡易バックテスト計算モジュールを追加

選定銘柄群を均等金額で購入・保有した場合の資産推移から、
累積リターン・最大ドローダウン・勝率（期間トータルリターンが
プラスだった銘柄割合）を算出するbacktest.pyを新設する。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `strategy_builder/sector_insight.py` の作成

**Files:**
- Create: `app/strategy_builder/sector_insight.py`
- Test: `app/tests/test_strategy_builder_sector_insight.py`

**Interfaces:**
- Consumes: なし（標準のみ。Task 4で追加される`ticker_latest_return_pct`と`network_pairs`の
  スキーマに依存: `network_pairs`の各要素は`sector_analysis.wavelet.compute_all_pairs_dominant_lag`
  と同じキー`leading_sector`, `lagging_sector`, `band`, `mean_coherence`, `lag_days_abs`を持つ）
- Produces:
  - `strategy_builder.sector_insight.find_top_gaining_tickers(ticker_latest_return_pct: dict[str, float], top_n: int = 5) -> list[dict]`
  - `strategy_builder.sector_insight.find_dominant_lagging_sector(network_pairs: list[dict], leading_sector: str, coherence_threshold: float = 0.5) -> dict | None`
  - `strategy_builder.sector_insight.build_watchlist_from_rotation(ticker_latest_return_pct: dict[str, float], network_pairs: list[dict], sector_map: dict[str, str], universe_names: dict[str, str], top_n: int = 5, coherence_threshold: float = 0.5) -> dict`
    戻り値: `{"idea_text": str | None, "candidates": list[dict]}`

- [ ] **Step 1: 失敗するテストを書く**

`app/tests/test_strategy_builder_sector_insight.py` を新規作成する:

```python
from strategy_builder.sector_insight import (
    build_watchlist_from_rotation,
    find_dominant_lagging_sector,
    find_top_gaining_tickers,
)


def test_find_top_gaining_tickers_sorts_descending_and_limits():
    returns = {"AAA.T": 1.0, "BBB.T": 5.0, "CCC.T": 3.0}
    result = find_top_gaining_tickers(returns, top_n=2)
    assert result == [
        {"ticker": "BBB.T", "return_pct": 5.0},
        {"ticker": "CCC.T", "return_pct": 3.0},
    ]


def test_find_dominant_lagging_sector_picks_highest_coherence_across_bands():
    pairs = [
        {"leading_sector": "銀行", "lagging_sector": "保険", "band": "短期",
         "mean_coherence": 0.4, "lag_days_abs": 2.0},
        {"leading_sector": "銀行", "lagging_sector": "保険", "band": "中期",
         "mean_coherence": 0.7, "lag_days_abs": 5.2},
        {"leading_sector": "保険", "lagging_sector": "銀行", "band": "長期",
         "mean_coherence": 0.9, "lag_days_abs": 10.0},
    ]
    result = find_dominant_lagging_sector(pairs, "銀行", coherence_threshold=0.5)
    assert result["band"] == "中期"
    assert result["lagging_sector"] == "保険"


def test_find_dominant_lagging_sector_returns_none_below_threshold():
    pairs = [
        {"leading_sector": "銀行", "lagging_sector": "保険", "band": "短期",
         "mean_coherence": 0.3, "lag_days_abs": 2.0},
    ]
    assert find_dominant_lagging_sector(pairs, "銀行", coherence_threshold=0.5) is None


def test_find_dominant_lagging_sector_returns_none_when_no_pairs_for_sector():
    pairs = [
        {"leading_sector": "保険", "lagging_sector": "銀行", "band": "短期",
         "mean_coherence": 0.9, "lag_days_abs": 2.0},
    ]
    assert find_dominant_lagging_sector(pairs, "銀行", coherence_threshold=0.5) is None


def test_build_watchlist_from_rotation_returns_candidates_and_idea_text():
    ticker_latest_return_pct = {"7203.T": 3.5, "8306.T": 1.0}
    network_pairs = [
        {"leading_sector": "輸送用機器", "lagging_sector": "電気機器", "band": "中期",
         "mean_coherence": 0.6, "lag_days_abs": 6.1},
    ]
    sector_map = {
        "7203.T": "輸送用機器",
        "8306.T": "銀行",
        "6758.T": "電気機器",
        "6501.T": "電気機器",
    }
    universe_names = {"6758.T": "ソニーグループ", "6501.T": "日立製作所"}

    result = build_watchlist_from_rotation(
        ticker_latest_return_pct, network_pairs, sector_map, universe_names
    )

    assert result["idea_text"] is not None
    assert "輸送用機器" in result["idea_text"]
    assert "電気機器" in result["idea_text"]
    assert {c["ticker"] for c in result["candidates"]} == {"6758.T", "6501.T"}
    assert result["candidates"][0]["leading_sector"] == "輸送用機器"


def test_build_watchlist_from_rotation_returns_none_idea_when_no_pair_found():
    result = build_watchlist_from_rotation(
        {"7203.T": 3.5}, [], {"7203.T": "輸送用機器"}, {}
    )
    assert result == {"idea_text": None, "candidates": []}


def test_build_watchlist_from_rotation_skips_gainer_without_sector_and_tries_next():
    ticker_latest_return_pct = {"UNKNOWN.T": 9.9, "7203.T": 3.5}
    network_pairs = [
        {"leading_sector": "輸送用機器", "lagging_sector": "電気機器", "band": "中期",
         "mean_coherence": 0.6, "lag_days_abs": 6.1},
    ]
    sector_map = {"7203.T": "輸送用機器", "6758.T": "電気機器"}
    result = build_watchlist_from_rotation(
        ticker_latest_return_pct, network_pairs, sector_map, {}
    )
    assert result["idea_text"] is not None
    assert {c["ticker"] for c in result["candidates"]} == {"6758.T"}
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_strategy_builder_sector_insight.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: `sector_insight.py`を実装する**

`app/strategy_builder/sector_insight.py` を新規作成する:

```python
"""業種間リード・ラグ関係（セクターローテーション分析）を使い、本日の
値上がり銘柄から「後日注意すべき業種・銘柄」を提案するモジュール。

セクターローテーションタブ・AI戦略ビルダータブが共有する分析結果
（app_tabs.shared.run_or_load_sector_rotation の戻り値）を入力とする。
このモジュール自体はStreamlit・データ取得に依存しない純粋ロジックとする。
"""


def find_top_gaining_tickers(
    ticker_latest_return_pct: dict[str, float], top_n: int = 5
) -> list[dict]:
    """直近日次リターンが高い順に上位top_n銘柄を返す。"""
    ranked = sorted(
        ticker_latest_return_pct.items(), key=lambda item: item[1], reverse=True
    )
    return [
        {"ticker": ticker, "return_pct": round(return_pct, 2)}
        for ticker, return_pct in ranked[:top_n]
    ]


def find_dominant_lagging_sector(
    network_pairs: list[dict],
    leading_sector: str,
    coherence_threshold: float = 0.5,
) -> dict | None:
    """指定業種が先行業種（leading_sector）となるペアの中から、
    コヒーレンス（mean_coherence）が閾値以上でもっとも高いものを返す。
    該当ペアが無ければNoneを返す。
    """
    candidates = [
        pair
        for pair in network_pairs
        if pair.get("leading_sector") == leading_sector
        and pair.get("mean_coherence", 0) >= coherence_threshold
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda pair: pair["mean_coherence"])


def build_watchlist_from_rotation(
    ticker_latest_return_pct: dict[str, float],
    network_pairs: list[dict],
    sector_map: dict[str, str],
    universe_names: dict[str, str],
    top_n: int = 5,
    coherence_threshold: float = 0.5,
) -> dict:
    """本日の値上がり銘柄→先行業種→追随業種→候補銘柄、の順に洗い出し、
    投資アイデア文と候補銘柄一覧を返す。

    値上がり上位銘柄を順に試し、先行・追随関係が見つかった最初の1件を採用する。
    該当する関係が1件も見つからない場合は
    `{"idea_text": None, "candidates": []}` を返す。
    """
    top_gainers = find_top_gaining_tickers(ticker_latest_return_pct, top_n=top_n)

    for gainer in top_gainers:
        leading_sector = sector_map.get(gainer["ticker"])
        if leading_sector is None:
            continue
        pair = find_dominant_lagging_sector(
            network_pairs, leading_sector, coherence_threshold=coherence_threshold
        )
        if pair is None:
            continue

        lagging_sector = pair["lagging_sector"]
        candidates = [
            {
                "ticker": ticker,
                "name": universe_names.get(ticker, ticker),
                "sector": lagging_sector,
                "leading_sector": leading_sector,
                "lag_days": round(pair["lag_days_abs"], 1),
                "band": pair["band"],
            }
            for ticker, sector in sector_map.items()
            if sector == lagging_sector
        ]
        idea_text = (
            f"本日、業種「{leading_sector}」の銘柄（{gainer['ticker']}など）が"
            f"値上がりしました（直近日次リターン{gainer['return_pct']}%）。"
            f"過去の業種間分析では、{leading_sector}は業種「{lagging_sector}」に対し"
            f"平均{round(pair['lag_days_abs'], 1)}日先行する関係が見られます"
            f"（{pair['band']}、コヒーレンス{round(pair['mean_coherence'], 2)}）。"
            f"{lagging_sector}業種の中で財務健全性の高い銘柄に注目したい。"
        )
        return {"idea_text": idea_text, "candidates": candidates}

    return {"idea_text": None, "candidates": []}
```

- [ ] **Step 4: テストを実行し、全てPASSすることを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_strategy_builder_sector_insight.py -v`
Expected: 全件PASS

- [ ] **Step 5: コミット**

```bash
cd app
git add strategy_builder/sector_insight.py tests/test_strategy_builder_sector_insight.py
git commit -m "$(cat <<'EOF'
AI戦略ビルダー: 業種ローテーションからの注目銘柄提案モジュールを追加

本日の値上がり銘柄→先行業種→過去のリード・ラグ分析で追随が
見込まれる業種→その業種の候補銘柄、を洗い出すsector_insight.pyを
新設する。機能①のアイデア入力画面から利用する。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `prompt_patterns/strategy_dialogue.py` の作成

**Files:**
- Create: `app/prompt_patterns/strategy_dialogue.py`
- Test: `app/tests/test_strategy_dialogue_prompt.py`

**Interfaces:**
- Consumes: `common.json_parsing.strip_code_fence(text: str) -> str`（既存）
- Produces:
  - `prompt_patterns.strategy_dialogue.build_dialogue_prompt(history: list[dict]) -> str`
    （`history`は`[{"role": "user"|"assistant", "content": str}, ...]`）
  - `prompt_patterns.strategy_dialogue.parse_dialogue_response(raw: str) -> dict`
    戻り値: `{"kind": "strategy", "strategy": dict}` または `{"kind": "question", "text": str}`

- [ ] **Step 1: 失敗するテストを書く**

`app/tests/test_strategy_dialogue_prompt.py` を新規作成する:

```python
from prompt_patterns.strategy_dialogue import build_dialogue_prompt, parse_dialogue_response


def test_build_dialogue_prompt_includes_persona_instructions():
    prompt = build_dialogue_prompt([{"role": "user", "content": "PERが低い銘柄"}])
    assert "クオンツ・アナリスト" in prompt
    assert "conditions" in prompt


def test_build_dialogue_prompt_includes_full_history_in_order():
    history = [
        {"role": "user", "content": "PERが低い銘柄"},
        {"role": "assistant", "content": "PERの閾値はいくつにしますか？"},
        {"role": "user", "content": "15倍以下で"},
    ]
    prompt = build_dialogue_prompt(history)
    user_pos = prompt.index("ユーザー: PERが低い銘柄")
    assistant_pos = prompt.index("AI: PERの閾値はいくつにしますか？")
    second_user_pos = prompt.index("ユーザー: 15倍以下で")
    assert user_pos < assistant_pos < second_user_pos


def test_parse_dialogue_response_detects_finalized_strategy_json():
    raw = (
        '```json\n{"strategy_name": "割安株", "conditions": '
        '[{"indicator": "PER", "operator": "LESS_THAN", "value": 15}], '
        '"sort_by": "PER", "order": "ASC"}\n```'
    )
    result = parse_dialogue_response(raw)
    assert result["kind"] == "strategy"
    assert result["strategy"]["strategy_name"] == "割安株"


def test_parse_dialogue_response_detects_question_text():
    raw = "PERの閾値はいくつにしますか？"
    result = parse_dialogue_response(raw)
    assert result == {"kind": "question", "text": "PERの閾値はいくつにしますか？"}


def test_parse_dialogue_response_treats_malformed_json_as_question():
    raw = "```json\n{not valid json\n```"
    result = parse_dialogue_response(raw)
    assert result["kind"] == "question"


def test_parse_dialogue_response_requires_conditions_key_for_strategy():
    raw = '{"strategy_name": "割安株"}'
    result = parse_dialogue_response(raw)
    assert result["kind"] == "question"
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_strategy_dialogue_prompt.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: `strategy_dialogue.py`を実装する**

`app/prompt_patterns/strategy_dialogue.py` を新規作成する:

```python
"""AI協調型のスクリーニングロジック構築（AI戦略ビルダー機能②）向けの
対話プロンプト構築・応答解析を行うモジュール。

data_api.llm_client.call_llm はターン単位のセッション状態を持たない
ステートレスなサブプロセス呼び出しのため、対話の各ターンで会話全履歴を
毎回プロンプトに含めて送信する。
"""

import json

from common.json_parsing import strip_code_fence

_PERSONA_INSTRUCTIONS = """\
あなた（AI）は、ユーザーの投資アイデアを厳密な「株式スクリーニング・バックテスト条件」へと
昇華させるプロのクオンツ・アナリストです。以下のステップに従ってユーザーをナビゲートしてください。

【ステップ1: アイデアの定量化】
ユーザーから「考え方」が入力されたら、それを歓迎し、以下の要素を具体化するための質問や提案を
1〜2個、短く行ってください。
1. 使用する財務指標（例: PER, PBR, ROE, DIVIDEND_YIELD, REVENUE_GROWTH のいずれか）
2. 具体的な数値の閾値（例: PBR 1倍未満、ROE 10%以上など）
このステップでは、説明文以外は出力しないでください。JSON形式は使わないでください。

【ステップ2: 構造化データの出力】
ユーザーと条件が合意できたら、それ以外の説明文を一切含めず、必ず次のJSON形式のみを
```json コードブロックで返してください。
```json
{
  "strategy_name": "確定した戦略名",
  "conditions": [
    {"indicator": "PER", "operator": "LESS_THAN", "value": 15},
    {"indicator": "ROE", "operator": "GREATER_THAN", "value": 10}
  ],
  "sort_by": "ROE",
  "order": "DESC"
}
```
indicatorはPER, PBR, ROE, DIVIDEND_YIELD, REVENUE_GROWTH, MARKET_CAPのいずれか、
operatorはLESS_THAN, LESS_EQUAL, GREATER_THAN, GREATER_EQUAL, EQUALSのいずれかを使ってください。
"""


def build_dialogue_prompt(history: list[dict]) -> str:
    """会話履歴（[{"role": "user"|"assistant", "content": str}, ...]）から、
    ペルソナ指示と会話全文を含む1回分のLLM呼び出し用プロンプトを組み立てる。
    """
    transcript_lines = [
        f"{'ユーザー' if turn['role'] == 'user' else 'AI'}: {turn['content']}"
        for turn in history
    ]
    transcript = "\n".join(transcript_lines)
    return f"{_PERSONA_INSTRUCTIONS}\n\n【これまでの会話】\n{transcript}\n\n【あなたの次の発言】"


def parse_dialogue_response(raw: str) -> dict:
    """LLM応答を判定する。

    JSONコードブロックとして解析でき、かつ`strategy_name`と`conditions`を
    含む場合は `{"kind": "strategy", "strategy": {...}}` を返す。
    それ以外は質問・提案テキストとして `{"kind": "question", "text": raw}` を返す。
    """
    try:
        parsed = json.loads(strip_code_fence(raw))
    except json.JSONDecodeError:
        return {"kind": "question", "text": raw.strip()}

    if (
        isinstance(parsed, dict)
        and "strategy_name" in parsed
        and "conditions" in parsed
    ):
        return {"kind": "strategy", "strategy": parsed}
    return {"kind": "question", "text": raw.strip()}
```

- [ ] **Step 4: テストを実行し、全てPASSすることを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest tests/test_strategy_dialogue_prompt.py -v`
Expected: 全件PASS

- [ ] **Step 5: コミット**

```bash
cd app
git add prompt_patterns/strategy_dialogue.py tests/test_strategy_dialogue_prompt.py
git commit -m "$(cat <<'EOF'
AI戦略ビルダー: 対話プロンプト構築・応答解析モジュールを追加

依頼書のクオンツ・アナリストのペルソナ指示をユーザープロンプト
本文に埋め込み、会話全履歴を毎ターン送信する方式でstrategy_dialogue.py
を新設する。JSON確定候補か質問テキストかを判別するparse_dialogue_response
を提供する。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: `strategy_builder_tab.py` の作成とアプリへの組み込み

**Files:**
- Create: `app/app_tabs/strategy_builder_tab.py`
- Modify: `app/app.py`

**Interfaces:**
- Consumes: すべてのTask 1〜9の成果物
  （`fetch_universe_fundamentals`/`fetch_universe_price_histories`,
  `run_or_load_sector_rotation`, `render_mermaid`,
  `strategy_builder.storage/conditions/backtest/sector_insight`,
  `prompt_patterns.strategy_dialogue`）
- Produces: `app_tabs.strategy_builder_tab.render_strategy_builder_tab() -> None`

このタスクはUIタブ全体の実装であり、既存の`app_tabs/*.py`と同様に直接の自動テストは
持たない。全体テストスイートの回帰確認と、`streamlit run`による手動確認で検証する。

- [ ] **Step 1: `strategy_builder_tab.py`を実装する**

`app/app_tabs/strategy_builder_tab.py` を新規作成する:

```python
"""AI戦略ビルダータブ: 投資アイデアの入力からAIとの対話によるロジック構築、
簡易バックテスト、最新データでの銘柄選定までを一気通貫で行う。
"""

import logging

import altair as alt
import pandas as pd
import streamlit as st

from common.disclaimer import DISCLAIMER_NOTICE
from data_api.llm_client import call_llm
from data_api.stock_price_api import (
    fetch_universe_fundamentals,
    fetch_universe_price_histories,
)
from prompt_patterns.strategy_dialogue import build_dialogue_prompt, parse_dialogue_response
from screening.sectors import SECTOR_MAP
from screening.universe import UNIVERSE, UNIVERSE_NAMES
from sector_analysis.network import build_mermaid_lead_lag_graph
from strategy_builder.backtest import run_strategy_backtest
from strategy_builder.conditions import (
    apply_strategy_conditions,
    build_match_reason,
    sort_by_strategy,
)
from strategy_builder.sector_insight import build_watchlist_from_rotation
from strategy_builder.storage import load_strategies, save_strategy

from app_tabs.shared import (
    CACHE_DIR,
    DATA_DIR,
    handle_table_selection,
    render_mermaid,
    run_or_load_sector_rotation,
)

logger = logging.getLogger(__name__)

STRATEGIES_PATH = DATA_DIR / "strategies.json"

_TEMPLATES = {
    "バリュー株": "PERが低く、PBRも割安な銘柄に投資したい。",
    "グロース株": "売上高の伸び率が高く、将来性のある成長株に投資したい。",
    "配当株": "配当利回りが高く、安定した配当が期待できる銘柄に投資したい。",
}


def _render_sector_rotation_suggestion() -> None:
    with st.expander("業種ローテーションから本日の注目銘柄を提案"):
        sector_period = st.selectbox(
            "分析期間", ["1y", "2y"], key="strategy_sector_period"
        )
        sector_force_regenerate = st.checkbox(
            "キャッシュを無視して再生成する", key="strategy_sector_force_regenerate"
        )
        if st.button("今すぐ分析を実行", key="strategy_run_sector_rotation"):
            with st.spinner("業種ローテーション分析を実行中..."):
                payload = run_or_load_sector_rotation(sector_period, sector_force_regenerate)
            if payload is None:
                st.error("分析可能な銘柄がありませんでした。")

        payload = st.session_state.get("sector_payload")
        if payload is None:
            st.info(
                "上のボタンで分析を実行すると、本日の値上がり銘柄から"
                "注目業種・銘柄を提案します。"
            )
            return

        watchlist = build_watchlist_from_rotation(
            payload.get("ticker_latest_return_pct", {}),
            payload.get("network_pairs", []),
            SECTOR_MAP,
            UNIVERSE_NAMES,
        )
        if watchlist["idea_text"] is None:
            st.info("十分な確信度を持つ業種間の関係が見つかりませんでした。")
            return

        st.write(watchlist["idea_text"])
        st.dataframe(
            pd.DataFrame(watchlist["candidates"]),
            column_config={
                "ticker": st.column_config.TextColumn("銘柄コード"),
                "name": st.column_config.TextColumn("銘柄名"),
                "sector": st.column_config.TextColumn("業種"),
                "leading_sector": st.column_config.TextColumn("先行業種"),
                "lag_days": st.column_config.NumberColumn("遅行日数"),
                "band": st.column_config.TextColumn("周期帯"),
            },
            hide_index=True,
        )
        if st.button("この案をアイデア欄に反映", key="strategy_apply_watchlist_idea"):
            st.session_state["strategy_idea_text"] = watchlist["idea_text"]
            st.rerun()


def _render_idea_input_section() -> None:
    st.subheader("① 投資アイデアを入力")
    st.caption(
        "自由な言葉で投資アイデアを入力してください。テンプレートボタンや、"
        "本日の値上がり銘柄からの提案も利用できます。"
    )

    template_cols = st.columns(len(_TEMPLATES))
    for col, (label, template_text) in zip(template_cols, _TEMPLATES.items()):
        with col:
            if st.button(label, key=f"strategy_template_{label}"):
                st.session_state["strategy_idea_text"] = template_text
                st.rerun()

    _render_sector_rotation_suggestion()

    st.text_area(
        "投資アイデア",
        key="strategy_idea_text",
        placeholder="例: PERが低く、ROEが高い成長株に投資したい",
        height=100,
    )

    if st.button("対話を始める", disabled=not st.session_state.get("strategy_idea_text")):
        st.session_state["strategy_chat_history"] = [
            {"role": "user", "content": st.session_state["strategy_idea_text"]}
        ]
        st.session_state["strategy_pending_strategy"] = None
        st.rerun()


def _render_dialogue_section() -> None:
    st.subheader("② AIとの対話でロジックを構築")

    saved_strategies = load_strategies(STRATEGIES_PATH)
    if saved_strategies:
        options = ["(新規に対話する)"] + [s["strategy_name"] for s in saved_strategies]
        picked = st.selectbox("保存済み戦略を開く", options, key="strategy_load_picker")
        if picked != "(新規に対話する)":
            picked_strategy = next(
                s for s in saved_strategies if s["strategy_name"] == picked
            )
            if st.button("この戦略を読み込む", key="strategy_load_picked"):
                st.session_state["strategy_confirmed"] = picked_strategy
                st.session_state["strategy_chat_history"] = []
                st.session_state["strategy_pending_strategy"] = None
                st.rerun()

    history = st.session_state.get("strategy_chat_history")
    if not history:
        st.caption("①でアイデアを入力し「対話を始める」を押すと、ここで対話が始まります。")
        return

    for turn in history:
        with st.chat_message(turn["role"]):
            st.write(turn["content"])

    pending = st.session_state.get("strategy_pending_strategy")

    # 最後のターンがユーザー発言で、まだ確定候補が無い場合のみLLMを呼ぶ。
    # （直前にAIの質問を表示済み、あるいは確定候補を表示中の再実行で
    # 重複してLLMを呼ばないようにするための判定）
    if history[-1]["role"] == "user" and pending is None:
        prompt = build_dialogue_prompt(history)
        with st.spinner("AIが回答を考えています..."):
            raw = call_llm(prompt)
        parsed = parse_dialogue_response(raw)
        if parsed["kind"] == "strategy":
            st.session_state["strategy_pending_strategy"] = parsed["strategy"]
        else:
            history.append({"role": "assistant", "content": parsed["text"]})
            st.session_state["strategy_chat_history"] = history
        st.rerun()

    if pending is not None:
        st.subheader("確定候補の戦略")
        st.json(pending)
        confirm_col, continue_col = st.columns(2)
        with confirm_col:
            if st.button("この条件で確定する", key="strategy_confirm_pending"):
                save_strategy(STRATEGIES_PATH, pending)
                st.session_state["strategy_confirmed"] = pending
                st.session_state["strategy_pending_strategy"] = None
                st.success(f"戦略「{pending['strategy_name']}」を保存しました。")
                st.rerun()
        with continue_col:
            if st.button("さらに対話を続ける", key="strategy_reject_pending"):
                history.append(
                    {
                        "role": "user",
                        "content": (
                            "まだ確定しません。もう少し条件について質問や"
                            "別の提案をしてください。"
                        ),
                    }
                )
                st.session_state["strategy_chat_history"] = history
                st.session_state["strategy_pending_strategy"] = None
                st.rerun()
        return

    user_reply = st.chat_input("AIへの返信を入力", key="strategy_chat_input")
    if user_reply:
        history.append({"role": "user", "content": user_reply})
        st.session_state["strategy_chat_history"] = history
        st.rerun()


def _render_backtest_section() -> None:
    strategy = st.session_state.get("strategy_confirmed")
    st.subheader("③ バックテスト検証")
    if strategy is None:
        st.caption("②で戦略を確定するか、保存済み戦略を読み込むと利用できます。")
        return

    st.write(f"対象戦略: **{strategy['strategy_name']}**")
    period = st.selectbox("バックテスト期間", ["1y", "2y"], key="strategy_backtest_period")

    if st.button("バックテストを実行", key="strategy_run_backtest"):
        with st.spinner("バックテストを実行中..."):
            universe_df = fetch_universe_fundamentals(UNIVERSE, CACHE_DIR)
            universe_df["name"] = universe_df["ticker"].map(UNIVERSE_NAMES).fillna(
                universe_df["name"]
            )
            matched_df = apply_strategy_conditions(universe_df, strategy)
            matched_tickers = matched_df["ticker"].tolist()

            if not matched_tickers:
                st.session_state["strategy_backtest_result"] = None
                st.error("この戦略の条件に合致する銘柄が現在ありませんでした。")
            else:
                prices_by_ticker = fetch_universe_price_histories(
                    matched_tickers, period, CACHE_DIR
                )
                result = run_strategy_backtest(prices_by_ticker)
                st.session_state["strategy_backtest_result"] = result

    result = st.session_state.get("strategy_backtest_result")
    if result is not None:
        metric_cols = st.columns(3)
        metric_cols[0].metric("累積リターン(%)", result["total_return_pct"])
        metric_cols[1].metric("最大ドローダウン(%)", result["max_drawdown_pct"])
        metric_cols[2].metric("勝率(%)", result["win_rate_pct"])

        equity_curve = result["equity_curve"]
        if not equity_curve.empty:
            chart_df = pd.DataFrame(
                {"date": equity_curve.index, "value": equity_curve.values}
            )
            chart = (
                alt.Chart(chart_df)
                .mark_line()
                .encode(x=alt.X("date:T", title="日付"), y=alt.Y("value:Q", title="資産推移（開始時=100）"))
            )
            st.altair_chart(chart, width="stretch")

        st.subheader("銘柄別トータルリターン")
        ticker_returns_df = pd.DataFrame(
            [
                {"ticker": ticker, "total_return_pct": value}
                for ticker, value in result["ticker_returns"].items()
            ]
        )
        st.dataframe(ticker_returns_df, hide_index=True)

        st.caption(
            "本バックテストは現在の財務指標で選んだ銘柄群を過去に遡って保有した想定であり、"
            "過去時点で同条件を満たしていたかは考慮していません（先読みバイアスあり）。"
        )
        st.markdown(DISCLAIMER_NOTICE)


def _render_screening_sector_network(result_df: pd.DataFrame) -> None:
    st.subheader("選定銘柄の業種ネットワーク")
    payload = st.session_state.get("sector_payload")
    if payload is None:
        period = st.selectbox(
            "分析期間", ["1y", "2y"], key="strategy_screening_sector_period"
        )
        if st.button("今すぐ分析を実行", key="strategy_screening_run_sector_rotation"):
            with st.spinner("業種ローテーション分析を実行中..."):
                payload = run_or_load_sector_rotation(period, force_regenerate=False)
            if payload is None:
                st.error("分析可能な銘柄がありませんでした。")
        if payload is None:
            st.info(
                "セクターローテーションタブ、または上のボタンで分析を実行すると、"
                "選定銘柄の業種ネットワークが表示されます。"
            )
            return

    selected_sectors = set(result_df["ticker"].map(SECTOR_MAP).dropna())
    network_df = pd.DataFrame(payload.get("network_pairs", []))
    if network_df.empty:
        st.info("業種間ネットワークのデータがありません。")
        return
    filtered_df = network_df[
        network_df["leading_sector"].isin(selected_sectors)
        | network_df["lagging_sector"].isin(selected_sectors)
    ]

    band = st.selectbox("周期帯", ["短期", "中期", "長期"], index=1, key="strategy_network_band")
    threshold = st.slider(
        "コヒーレンス閾値", 0.0, 1.0, 0.5, 0.05, key="strategy_network_threshold"
    )
    mermaid_code = build_mermaid_lead_lag_graph(filtered_df, band, threshold)
    if mermaid_code is None:
        st.info("十分な確信度を持つ関係が見つかりませんでした。閾値を下げてみてください。")
    else:
        render_mermaid(mermaid_code, height=400)


def _render_screening_section() -> None:
    strategy = st.session_state.get("strategy_confirmed")
    st.subheader("④ 最新データで銘柄選定を実行")
    if strategy is None:
        st.caption("②で戦略を確定するか、保存済み戦略を読み込むと利用できます。")
        return

    if st.button("最新データで銘柄選定を実行", key="strategy_run_screening"):
        with st.spinner("銘柄を絞り込み中..."):
            universe_df = fetch_universe_fundamentals(UNIVERSE, CACHE_DIR)
            universe_df["name"] = universe_df["ticker"].map(UNIVERSE_NAMES).fillna(
                universe_df["name"]
            )
            matched_df = apply_strategy_conditions(universe_df, strategy)
            matched_df = sort_by_strategy(matched_df, strategy)
            matched_df = matched_df.copy()
            matched_df["reason"] = matched_df.apply(
                lambda row: build_match_reason(row, strategy.get("conditions", [])), axis=1
            )

            price_by_ticker = fetch_universe_price_histories(
                matched_df["ticker"].tolist(), "1y", CACHE_DIR
            )

            def _current_price(ticker: str) -> float | None:
                series = price_by_ticker.get(ticker)
                if series is None:
                    return None
                valid = series.dropna()
                return round(float(valid.iloc[-1]), 1) if not valid.empty else None

            matched_df["current_price"] = matched_df["ticker"].map(_current_price)

            st.session_state["strategy_screening_result_df"] = matched_df
            st.session_state["strategy_screening_selected_row"] = None
            st.session_state["strategy_screening_result_table"] = {
                "selection": {"rows": [], "columns": []}
            }

    result_df = st.session_state.get("strategy_screening_result_df")
    if result_df is not None:
        st.caption(f"該当銘柄（{len(result_df)}件）。行をクリックすると銘柄詳細を表示します。")
        event = st.dataframe(
            result_df,
            column_config={
                "ticker": st.column_config.TextColumn("銘柄コード"),
                "name": st.column_config.TextColumn("銘柄名"),
                "current_price": st.column_config.NumberColumn("現在の株価"),
                "reason": st.column_config.TextColumn("判定理由"),
            },
            on_select="rerun",
            selection_mode="single-row",
            key="strategy_screening_result_table",
        )
        handle_table_selection("strategy_screening_selected_row", event, result_df)

        _render_screening_sector_network(result_df)


def render_strategy_builder_tab() -> None:
    logger.info("AI戦略ビルダータブを表示")
    st.header("AI戦略ビルダー")
    st.caption(
        "投資アイデアの入力からAIとの対話によるロジック構築、簡易バックテスト、"
        "最新データでの銘柄選定までを一気通貫で行います。"
    )

    if "strategy_idea_text" not in st.session_state:
        st.session_state["strategy_idea_text"] = ""
    if "strategy_chat_history" not in st.session_state:
        st.session_state["strategy_chat_history"] = []
    if "strategy_pending_strategy" not in st.session_state:
        st.session_state["strategy_pending_strategy"] = None
    if "strategy_confirmed" not in st.session_state:
        st.session_state["strategy_confirmed"] = None

    _render_idea_input_section()
    st.divider()
    _render_dialogue_section()
    st.divider()
    _render_backtest_section()
    st.divider()
    _render_screening_section()
    st.markdown(DISCLAIMER_NOTICE)
```

- [ ] **Step 2: `app.py`にタブを追加する**

`app/app.py` のimport部分（`from app_tabs.sector import render_sector_tab` の直後）に
追加する:

```python
from app_tabs.strategy_builder_tab import render_strategy_builder_tab
```

`st.tabs(...)` の呼び出し部分を次のように変更する:

```python
# 6つの主要機能をタブとして構成する
tab_portfolio, tab_screening, tab_backtest, tab_ranking, tab_sector, tab_strategy_builder = (
    st.tabs(
        [
            "ポートフォリオ",
            "スクリーニング",
            "バックテスト",
            "一括バックテスト",
            "セクターローテーション",
            "AI戦略ビルダー",
        ]
    )
)
```

`with tab_sector:` ブロックの直後に追加する:

```python
with tab_strategy_builder:
    render_strategy_builder_tab()
```

- [ ] **Step 3: インポートが解決することを確認する**

Run: `cd app && .venv/Scripts/python.exe -c "import app_tabs.strategy_builder_tab"`
Expected: エラーなく終了する

- [ ] **Step 4: 全体テストスイートを実行し、回帰がないことを確認する**

Run: `cd app && .venv/Scripts/python.exe -m pytest -v`
Expected: 全件PASS

- [ ] **Step 5: `streamlit run`で手動確認する**

Run: `cd app && .venv/Scripts/python.exe -m streamlit run app.py`

ブラウザで次のゴールデンパスを確認する（Claude Code CLIがログイン済みである前提）:

1. 「AI戦略ビルダー」タブが表示され、①〜④のセクションが順に表示される
2. テンプレートボタン「バリュー株」を押すとテキストエリアに定型文が入る
3. 「業種ローテーションから本日の注目銘柄を提案」を展開し「今すぐ分析を実行」を押すと、
   （初回は時間がかかるが）値上がり銘柄からの提案文と候補銘柄テーブルが表示される
4. 「対話を始める」を押すと②にAIからの質問が表示され、`st.chat_input`で返信すると
   会話が続く
5. AIが条件を確定JSONで返すと「確定候補の戦略」が表示され、「この条件で確定する」を
   押すと保存される
6. ③でバックテスト期間を選び「バックテストを実行」を押すと、指標3つ・資産推移グラフ・
   銘柄別リターン表が表示される
7. ④で「最新データで銘柄選定を実行」を押すと、銘柄コード・銘柄名・現在の株価・
   判定理由を含む一覧表が表示され、行クリックで既存の銘柄詳細ダイアログが開く
8. 既存の5タブ（ポートフォリオ／スクリーニング／バックテスト／一括バックテスト／
   セクターローテーション）が今まで通り動作することを確認する

Expected: 上記すべてがエラーなく動作する。動作しない場合は原因を修正してから次に進む。

- [ ] **Step 6: コミット**

```bash
cd app
git add app_tabs/strategy_builder_tab.py app.py
git commit -m "$(cat <<'EOF'
AI戦略ビルダータブを追加

投資アイデアの入力→AIとの対話によるロジック構築→簡易バックテスト
検証→最新データでの銘柄選定実行、を一気通貫で行う新規タブを追加する。
既存5タブの動作は変更しない。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: チュートリアルドキュメントの追加

**Files:**
- Create: `docs/06-real-world-examples/04-strategy-builder-agent.md`
- Modify: `docs/06-real-world-examples/00-README.md`
- Modify: `docs/06-real-world-examples/03-portfolio-advisor-agent.md`
- Modify: `MASTER-INDEX.md`

**Interfaces:** なし（ドキュメントのみ）

- [ ] **Step 1: 新規教材ページを作成する**

`docs/06-real-world-examples/04-strategy-builder-agent.md` を新規作成する:

```markdown
# AI戦略ビルダーエージェント

## この教材で身につくこと

- 曖昧な投資アイデアを、AIとの複数ターンの対話を通じて構造化条件に
  詰めていく設計パターン
- ステートレスなLLM呼び出し（`call_llm`）で対話UIを実現する方法
  （会話全履歴を毎ターン送信する）
- 「確定前にユーザーへ見せる」設計を、単発のJSON確認だけでなく
  対話プロセス全体に広げる考え方
- 財務指標ベースのスクリーニング戦略を、簡易的に過去の値動きで
  検証してから実運用（銘柄選定）に進める一気通貫のUI構成

## 概要

02-screening-dashboard.mdは「自然言語1文→JSON→絞り込み」という単発の
変換フローでした。このツールは、その前段に「AIとの対話でアイデアを
条件に詰める」ステップと、後段に「簡易バックテストで検証する」ステップを
加え、アイデアの入力から実践（銘柄選定）までを1つの画面で完結させます。

処理の流れは次の4ステップです。

1. ユーザーが自由記述で投資アイデアを入力する（テンプレートボタンや、
   業種間のリード・ラグ分析から本日の注目銘柄を提案する機能も使える）
2. AIとの対話で、財務指標と閾値を持つ構造化条件（JSON）に詰める
3. 現在の財務指標で選んだ銘柄群を過去に遡って保有した場合の
   資産推移を簡易シミュレーションする
4. 確定した条件を最新の市場データに適用し、該当銘柄と判定理由を一覧表示する

## 位置づけ

条件のJSON変換・絞り込みの考え方は
[02-screening-dashboard.md](02-screening-dashboard.md)の延長線上にありますが、
このツールでは条件の生成を**単発の変換ではなく複数ターンの対話**にし、
独自のJSONスキーマ（`indicator`/`operator`表記）を使います。

バックテストの考え方は
[05-portfolio-management/03-backtest-automation.md](../05-portfolio-management/03-backtest-automation.md)
と共通ですが、このツールでは単一銘柄のテクニカル戦略ではなく、
**複数銘柄を均等金額で購入・保有した場合の資産推移**を扱います。

業種間のリード・ラグ分析は
[05-portfolio-management/04-lead-lag-correlation.md](../05-portfolio-management/04-lead-lag-correlation.md)
で学んだ考え方をそのまま再利用し、「本日値上がりした業種の銘柄→過去の
分析で追随が見込まれる業種の銘柄」を洗い出す入力補助として使います。

## 主要概念・パラメータ解説

| 要素 | 目的 | 対応するコード |
|------|------|-----------------|
| 会話全履歴を毎ターン送信 | ステートレスな`call_llm`で対話を実現する | `build_dialogue_prompt` |
| JSON確定候補 vs 質問テキストの判別 | AIの応答が「まだ質問中」か「条件が確定した」かを見分ける | `parse_dialogue_response` |
| indicator/operatorスキーマ | 既存のfield/記号演算子スキーマとは独立した戦略JSON形式 | `strategy_builder/conditions.py` |
| 判定理由の決定的生成 | AIを呼ばず、実際の値と閾値から機械的に判定理由を組み立てる | `build_match_reason` |
| 均等金額購入・保有シミュレーション | 過去の各時点で条件を満たしていたかは考慮しない簡易バックテスト | `run_strategy_backtest` |
| 業種間リード・ラグからの銘柄提案 | 本日の値上がり銘柄→追随業種の候補銘柄を洗い出す | `sector_insight.py` |

## 実ソースコード（Python / プロンプト例）

### 対話プロンプトのペルソナ指示（抜粋）

```text
あなた（AI）は、ユーザーの投資アイデアを厳密な「株式スクリーニング・
バックテスト条件」へと昇華させるプロのクオンツ・アナリストです。

【ステップ1: アイデアの定量化】
使用する財務指標と具体的な数値の閾値を具体化するための質問や提案を
1〜2個、短く行ってください。

【ステップ2: 構造化データの出力】
条件が合意できたら、次のJSON形式のみを```json コードブロックで
返してください。
{
  "strategy_name": "確定した戦略名",
  "conditions": [
    {"indicator": "PER", "operator": "LESS_THAN", "value": 15}
  ],
  "sort_by": "ROE",
  "order": "DESC"
}
```

### 判定理由の決定的生成

```python
def build_match_reason(row: pd.Series, conditions: list[dict]) -> str:
    """1銘柄の判定理由を、条件ごとの実際の値と閾値から機械的に組み立てる。
    LLMを呼ばず決定的に生成することで、判定理由の正確性と再現性を保証する。"""
    parts = []
    for condition in conditions:
        column = _INDICATOR_COLUMNS.get(condition.get("indicator"))
        op_func, op_label = _OPERATORS.get(condition.get("operator"), (None, None))
        if column is None or op_func is None or column not in row.index:
            continue
        actual = row[column]
        if pd.isna(actual):
            continue
        label = _INDICATOR_LABELS.get(condition["indicator"], condition["indicator"])
        parts.append(f"{label} {round(float(actual), 1)}（条件: {condition['value']}{op_label}）")
    return " / ".join(parts) if parts else "条件詳細なし"
```

完全な実装は[`app/strategy_builder/`](../../app/strategy_builder/)、
起動コマンドは`app/`ディレクトリで次の通りです。

```bash
streamlit run app.py
```

### 悪い例

対話の各ターンでAIの応答をそのまま信頼し、確定JSONかどうかを
判別せずに直接スクリーニングへ適用しています。

```python
# 悪い例: 応答が質問なのか確定JSONなのか判別せずそのまま使う
raw = call_llm(prompt)
strategy = json.loads(raw)  # 質問テキストの場合ここで例外になる、
                             # あるいは不完全な条件のまま実行されてしまう
result_df = apply_strategy_conditions(universe_df, strategy)
```

### 良い例

`parse_dialogue_response`で応答の種類を判別し、確定候補はユーザーに
`st.json`で見せたうえで、明示的な「確定する」操作を経てから保存・適用します。

```python
parsed = parse_dialogue_response(raw)
if parsed["kind"] == "strategy":
    st.session_state["strategy_pending_strategy"] = parsed["strategy"]
    st.json(parsed["strategy"])  # 確認ステップ
    if st.button("この条件で確定する"):
        save_strategy(STRATEGIES_PATH, parsed["strategy"])
else:
    st.chat_message("assistant").write(parsed["text"])  # まだ対話を続ける
```

### 実行結果例

投資アイデア欄に「PERが低く、ROEが高い成長株」と入力して対話を始めると、
AIから「PERとROEの具体的な閾値を教えてください（例: PER 15倍以下、
ROE 10%以上など）」といった質問が返ります。閾値を伝えて合意すると、
次のJSONが確定候補として表示されます。

```json
{
  "strategy_name": "割安成長株戦略",
  "conditions": [
    {"indicator": "PER", "operator": "LESS_THAN", "value": 15},
    {"indicator": "ROE", "operator": "GREATER_THAN", "value": 10}
  ],
  "sort_by": "ROE",
  "order": "DESC"
}
```

「確定する」を押すとバックテスト・銘柄選定セクションが利用可能になり、
銘柄選定結果には「PER 12.3（条件: 15未満）／ROE 15.2（条件: 10より大）」
のような判定理由が銘柄ごとに表示されます。

## 演習課題

1. `_INDICATOR_COLUMNS`に新しい指標（例: 自己資本比率）を1つ追加し、
   `fetch_fundamentals`にも対応するデータ取得を追加してください。
2. `find_dominant_lagging_sector`のコヒーレンス閾値をUIから調整できる
   ようにし、閾値を上げると候補銘柄が減ることを確認してください。
3. 「悪い例」のコードを実際に動かした場合、対話の途中（AIがまだ質問を
   返している段階）でどのようなエラーになるか具体例を1つ考えてください。

## 理解度チェック

- [ ] ステートレスなLLM呼び出しで複数ターンの対話を実現する方法を説明できる
- [ ] AIの応答を「確定JSON」か「対話継続」かで判別する必要性を説明できる
- [ ] この簡易バックテストが持つルックアヘッドバイアスの内容を説明できる
- [ ] 判定理由をAIではなく決定的ロジックで生成する利点を説明できる

---

投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。

[← 前へ: 統合ポートフォリオアドバイザーエージェント](03-portfolio-advisor-agent.md) | [トップに戻る →](../../README.md)
```

- [ ] **Step 2: `00-README.md`の教材一覧・学習の進め方を更新する**

`docs/06-real-world-examples/00-README.md` の教材一覧テーブルに行を追加する:

```markdown
| 01 | [日次マーケットレポート自動生成ツール](01-daily-market-report-tool.md) | ウォッチリスト銘柄の朝の定型レポートをCLIで生成 | 株価API / ニュース分析 / レポート生成プロンプト |
| 02 | [スクリーニングダッシュボード](02-screening-dashboard.md) | 自然言語条件をStreamlit UIで絞り込み表示 | スクリーニングプロンプト / pandas / Streamlit |
| 03 | [統合ポートフォリオアドバイザーエージェント](03-portfolio-advisor-agent.md) | 保有銘柄の構成・リスク・ニュース・テクニカルを統合レポート化 | 全カテゴリの分析エージェント |
| 04 | [AI戦略ビルダーエージェント](04-strategy-builder-agent.md) | 投資アイデアの対話的な条件化から簡易バックテスト・銘柄選定まで一気通貫 | スクリーニングプロンプト / バックテスト / リード・ラグ分析 |
```

「学習の進め方」の節を次のように変更する:

```markdown
## 学習の進め方

01 → 04 の順に進めることを推奨します。

1. 01では単一の自動化フロー（データ取得 → LLM解説 → Markdown出力）を学びます。
2. 02では01の考え方をユーザー入力（自然言語条件）を起点とするUIに応用します。
3. 03では01・02の要素に加え、複数の分析エージェントを1つのレポートへ統合します。
4. 04では02の条件変換を複数ターンの対話に発展させ、簡易バックテストによる
   検証ステップを加えた一気通貫のツールにまとめます。
```

- [ ] **Step 3: `03-portfolio-advisor-agent.md`の末尾ナビゲーションを更新する**

`docs/06-real-world-examples/03-portfolio-advisor-agent.md` の末尾の行を変更する。

変更前:
```markdown
[← 前へ: スクリーニングダッシュボード](02-screening-dashboard.md) | [トップに戻る →](../../README.md)
```

変更後:
```markdown
[← 前へ: スクリーニングダッシュボード](02-screening-dashboard.md) | [次へ: AI戦略ビルダーエージェント →](04-strategy-builder-agent.md)
```

- [ ] **Step 4: `MASTER-INDEX.md`にリンクを追加する**

`MASTER-INDEX.md` の `docs/06-real-world-examples/03-portfolio-advisor-agent.md` の行の
直後に追加する:

```markdown
- [docs/06-real-world-examples/04-strategy-builder-agent.md](docs/06-real-world-examples/04-strategy-builder-agent.md) - AI戦略ビルダーエージェント
```

- [ ] **Step 5: リンク切れがないか目視確認する**

新規ファイル内の相対リンク（`02-screening-dashboard.md`,
`../05-portfolio-management/03-backtest-automation.md`,
`../05-portfolio-management/04-lead-lag-correlation.md`,
`../../app/strategy_builder/`, `../../DISCLAIMER.md`, `../../README.md`）が
実在するパスであることを確認する。

Run:
```bash
test -f "docs/06-real-world-examples/02-screening-dashboard.md" && echo OK
test -f "docs/05-portfolio-management/03-backtest-automation.md" && echo OK
test -f "docs/05-portfolio-management/04-lead-lag-correlation.md" && echo OK
test -d "app/strategy_builder" && echo OK
test -f "DISCLAIMER.md" && echo OK
test -f "README.md" && echo OK
```
Expected: 6行すべて`OK`

- [ ] **Step 6: コミット**

```bash
git add docs/06-real-world-examples/04-strategy-builder-agent.md \
        docs/06-real-world-examples/00-README.md \
        docs/06-real-world-examples/03-portfolio-advisor-agent.md \
        MASTER-INDEX.md
git commit -m "$(cat <<'EOF'
AI戦略ビルダーエージェントの教材ページを追加

06-real-world-examplesに04番目の教材として追加し、00-README・
MASTER-INDEX・既存教材のナビゲーションリンクを更新する。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## 実装完了後の最終確認

全11タスク完了後、次を実行して全体の健全性を確認する。

- [ ] **Run:** `cd app && .venv/Scripts/python.exe -m pytest -v`
  **Expected:** 全テストPASS（既存テスト + 本計画で追加したテストすべて）
- [ ] **Run:** `cd app && .venv/Scripts/python.exe -m streamlit run app.py` で起動し、
  6タブすべてがエラーなく表示されることを目視確認する
- [ ] Task 10 Step 5のゴールデンパスチェックリストを再確認する
