# セクター間ネットワーク（全ペア俯瞰・Mermaid表示）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** セクターローテーションタブに、全136業種ペアのウェーブレット分析結果を一括計算し、周期帯（短期/中期/長期）ごとに「どの業種が誰をリードしているか」をMermaidの有向グラフで俯瞰できる、新セクション「業種間ネットワーク（全ペア俯瞰）」を追加する。

**Architecture:** `sector_analysis/wavelet.py`に全ペア一括計算・集約を行う純粋関数`compute_all_pairs_dominant_lag`を追加する。新規モジュール`sector_analysis/network.py`に、集約結果からMermaid定義文字列を生成する純粋関数`build_mermaid_lead_lag_graph`を実装する。`app.py`のセクターローテーションタブの「分析を実行」フローに全ペア一括計算を統合し、既存の相関ヒートマップ・AIコメントセクションの直後、既存の2業種選択ウェーブレット・ドリルダウンの直前に新UIセクションを追加する。既存の相関ベースの分析・2業種ドリルダウン・AI解説機能は変更しない。

**Tech Stack:** Python 3.14, pandas, numpy, pywt (既存)、streamlit-mermaid (新規依存)、altair, pytest, uv

## Global Constraints

- 新規の実行時依存は`streamlit-mermaid`のみ追加する（`pywavelets`は既存依存のまま）
- Mermaidグラフのエッジクリックによる既存2業種ドリルダウンへの選択自動反映は実装しない
- 個別ペアの統計的有意性検定は実装しない
- 周期帯をまたいだ統合表示は実装しない（短期/中期/長期を切り替え表示する）
- 既存の相関ベース`pairs`・2業種選択ウェーブレット・ドリルダウン・AI解説機能（`sector_analysis/correlation.py`、既存の`app.py`ウェーブレットセクション、`prompt_patterns/wavelet_explanation.py`）は変更しない
- 旧スキーマキャッシュ（`sector_returns`または`network_pairs`のいずれかが欠けている）は読み込み時にキャッシュミス扱いとして再計算する
- `window_days`のデフォルトは20、コヒーレンス閾値のデフォルトは0.5、周期帯セレクトボックスのデフォルトは中期

---

### Task 1: `sector_analysis/wavelet.py` — 全ペア一括計算・集約

**Files:**
- Modify: `sector_analysis/wavelet.py`
- Test: `tests/test_sector_wavelet.py`

**Interfaces:**
- Consumes: 既存の`compute_cross_wavelet_lead_lag`、`compute_dominant_lag_series`、`PERIOD_BANDS`（すべて同ファイル内で定義済み）
- Produces:
  - `compute_all_pairs_dominant_lag(sector_returns: dict[str, pd.Series], window_days: int = 20) -> pd.DataFrame`（列: `sector_x, sector_y, band, dominant_lag_days, mean_coherence, leading_sector, lagging_sector, lag_days_abs`）
  - 後続タスク（Task 2, 3）はこのシンボルをそのまま利用する。

- [ ] **Step 1: 失敗するテストを書く**

まず`tests/test_sector_wavelet.py`冒頭のimport文を以下に変更する（`compute_all_pairs_dominant_lag`を追加）:

```python
from sector_analysis.wavelet import (
    classify_period_band,
    compute_all_pairs_dominant_lag,
    compute_cross_wavelet_lead_lag,
    compute_dominant_lag_series,
    deserialize_sector_returns,
    serialize_sector_returns,
    summarize_band_snapshot,
)
```

次に、`tests/test_sector_wavelet.py`の末尾に以下のテスト関数を追加する:

```python
def test_compute_all_pairs_dominant_lag_detects_known_lag_direction_and_magnitude():
    n = 240
    t = np.arange(n)
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    period = 20.0
    shift = 5
    a = pd.Series(np.sin(2 * np.pi * t / period), index=dates)
    # bはaよりshift日遅れて追随する（＝aが先行）
    b = pd.Series(np.sin(2 * np.pi * (t - shift) / period), index=dates)

    result = compute_all_pairs_dominant_lag({"A": a, "B": b}, window_days=20)

    mid_band = result[(result["sector_x"] == "A") & (result["sector_y"] == "B") & (result["band"] == "中期")]
    assert not mid_band.empty
    row = mid_band.iloc[0]
    assert row["leading_sector"] == "A"
    assert row["lagging_sector"] == "B"
    assert abs(row["dominant_lag_days"] - shift) < 3
    assert abs(row["lag_days_abs"] - shift) < 3
    assert 0.0 <= row["mean_coherence"] <= 1.0


def test_compute_all_pairs_dominant_lag_skips_pairs_with_insufficient_data():
    n = 240
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    rng = np.random.default_rng(0)
    a = pd.Series(rng.normal(size=n), index=dates)
    b = pd.Series(rng.normal(size=n), index=dates)
    # cは10日分しかデータがなく、a・bとの共通非欠損データが不足する
    short_dates = pd.date_range("2025-01-01", periods=10, freq="D")
    c = pd.Series(np.arange(10, dtype=float), index=short_dates)

    result = compute_all_pairs_dominant_lag({"A": a, "B": b, "C": c}, window_days=20)

    assert not result.empty
    assert not ((result["sector_x"] == "C") | (result["sector_y"] == "C")).any()
    assert ((result["sector_x"] == "A") & (result["sector_y"] == "B")).any()


def test_compute_all_pairs_dominant_lag_skips_pair_that_raises(monkeypatch):
    import sector_analysis.wavelet as wavelet_module

    n = 240
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    rng = np.random.default_rng(2)
    sector_returns = {
        name: pd.Series(rng.normal(size=n), index=dates) for name in ["A", "B", "C"]
    }

    original = wavelet_module.compute_cross_wavelet_lead_lag

    def flaky(series_x, series_y, sector_x_name, sector_y_name, **kwargs):
        if {sector_x_name, sector_y_name} == {"A", "B"}:
            raise RuntimeError("boom")
        return original(series_x, series_y, sector_x_name, sector_y_name, **kwargs)

    monkeypatch.setattr(wavelet_module, "compute_cross_wavelet_lead_lag", flaky)

    result = wavelet_module.compute_all_pairs_dominant_lag(sector_returns, window_days=20)

    assert not ((result["sector_x"] == "A") & (result["sector_y"] == "B")).any()
    assert (
        ((result["sector_x"] == "A") & (result["sector_y"] == "C")).any()
        or ((result["sector_x"] == "B") & (result["sector_y"] == "C")).any()
    )


def test_compute_all_pairs_dominant_lag_mean_coherence_within_bounds():
    n = 240
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    rng = np.random.default_rng(1)
    sector_returns = {
        name: pd.Series(rng.normal(size=n), index=dates) for name in ["A", "B", "C"]
    }

    result = compute_all_pairs_dominant_lag(sector_returns, window_days=20)

    assert not result.empty
    assert (result["mean_coherence"] >= 0).all()
    assert (result["mean_coherence"] <= 1).all()


def test_compute_all_pairs_dominant_lag_returns_empty_for_single_sector():
    dates = pd.date_range("2025-01-01", periods=240, freq="D")
    result = compute_all_pairs_dominant_lag({"A": pd.Series(np.zeros(240), index=dates)})

    assert list(result.columns) == [
        "sector_x",
        "sector_y",
        "band",
        "dominant_lag_days",
        "mean_coherence",
        "leading_sector",
        "lagging_sector",
        "lag_days_abs",
    ]
    assert result.empty
```

- [ ] **Step 2: テストを実行し、失敗することを確認する**

Run: `cd app && uv run pytest tests/test_sector_wavelet.py -v`
Expected: 新規追加した5件が`ImportError: cannot import name 'compute_all_pairs_dominant_lag'`でFAIL

- [ ] **Step 3: `sector_analysis/wavelet.py`に`compute_all_pairs_dominant_lag`を実装する**

ファイル冒頭に`import itertools`を追加する（`import numpy as np`の前）。

ファイル末尾（`summarize_band_snapshot`の後）に以下を追加する:

```python
def compute_all_pairs_dominant_lag(
    sector_returns: dict[str, pd.Series],
    window_days: int = 20,
) -> pd.DataFrame:
    """全業種ペアについてウェーブレット分析を一括実行し、周期帯ごとに
    直近window_days営業日のコヒーレンス加重平均ラグに集約する。

    個別ペアの計算で例外が発生した場合、またはデータ不足で
    compute_cross_wavelet_lead_lagが空のDataFrameを返した場合は、
    そのペアを結果から除外し処理を継続する。
    """
    columns = [
        "sector_x",
        "sector_y",
        "band",
        "dominant_lag_days",
        "mean_coherence",
        "leading_sector",
        "lagging_sector",
        "lag_days_abs",
    ]
    rows = []
    sectors = sorted(sector_returns.keys())
    for sector_x, sector_y in itertools.combinations(sectors, 2):
        try:
            pair_df = compute_cross_wavelet_lead_lag(
                sector_returns[sector_x], sector_returns[sector_y], sector_x, sector_y
            )
        except Exception:
            continue
        if pair_df.empty:
            continue

        for band in PERIOD_BANDS:
            band_df = pair_df[pair_df["band"] == band]
            if band_df.empty:
                continue
            per_date = compute_dominant_lag_series(band_df)
            if per_date.empty:
                continue

            windowed = per_date.tail(window_days)
            weight_total = windowed["avg_coherence"].sum()
            if weight_total <= 0:
                continue

            dominant_lag_days = (
                windowed["dominant_lag_days"] * windowed["avg_coherence"]
            ).sum() / weight_total
            mean_coherence = windowed["avg_coherence"].mean()
            leading_sector = sector_x if dominant_lag_days >= 0 else sector_y
            lagging_sector = sector_y if dominant_lag_days >= 0 else sector_x

            rows.append(
                {
                    "sector_x": sector_x,
                    "sector_y": sector_y,
                    "band": band,
                    "dominant_lag_days": dominant_lag_days,
                    "mean_coherence": mean_coherence,
                    "leading_sector": leading_sector,
                    "lagging_sector": lagging_sector,
                    "lag_days_abs": abs(dominant_lag_days),
                }
            )

    return pd.DataFrame(rows, columns=columns)
```

- [ ] **Step 4: テストを実行し、パスすることを確認する**

Run: `cd app && uv run pytest tests/test_sector_wavelet.py -v`
Expected: 全件PASS（既存分含め計14件）

- [ ] **Step 5: コミット**

```bash
cd app
git add sector_analysis/wavelet.py tests/test_sector_wavelet.py
git commit -m "feat: 全業種ペアのウェーブレット分析を一括集約するcompute_all_pairs_dominant_lagを追加"
```

---

### Task 2: `sector_analysis/network.py` — Mermaidグラフ生成

**Files:**
- Create: `sector_analysis/network.py`
- Test: `tests/test_sector_network.py`

**Interfaces:**
- Consumes: `pd.DataFrame`（Task 1の`compute_all_pairs_dominant_lag`と同じ列構成: `sector_x, sector_y, band, dominant_lag_days, mean_coherence, leading_sector, lagging_sector, lag_days_abs`）
- Produces:
  - `build_mermaid_lead_lag_graph(pairs_df: pd.DataFrame, band: str, coherence_threshold: float) -> str | None`
  - 後続タスク（Task 3）はこのシンボルをそのまま利用する。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_sector_network.py`を新規作成する:

```python
import pandas as pd

from sector_analysis.network import build_mermaid_lead_lag_graph


def _make_pairs_df(rows: list[dict]) -> pd.DataFrame:
    columns = [
        "sector_x",
        "sector_y",
        "band",
        "dominant_lag_days",
        "mean_coherence",
        "leading_sector",
        "lagging_sector",
        "lag_days_abs",
    ]
    return pd.DataFrame(rows, columns=columns)


def test_build_mermaid_lead_lag_graph_filters_by_coherence_threshold():
    pairs_df = _make_pairs_df(
        [
            {
                "sector_x": "A",
                "sector_y": "B",
                "band": "中期",
                "dominant_lag_days": 5.0,
                "mean_coherence": 0.8,
                "leading_sector": "A",
                "lagging_sector": "B",
                "lag_days_abs": 5.0,
            },
            {
                "sector_x": "C",
                "sector_y": "D",
                "band": "中期",
                "dominant_lag_days": 2.0,
                "mean_coherence": 0.3,
                "leading_sector": "C",
                "lagging_sector": "D",
                "lag_days_abs": 2.0,
            },
        ]
    )

    result = build_mermaid_lead_lag_graph(pairs_df, band="中期", coherence_threshold=0.5)

    assert result is not None
    assert "flowchart" in result
    assert '"A"' in result
    assert '"B"' in result
    assert '"C"' not in result
    assert '"D"' not in result


def test_build_mermaid_lead_lag_graph_filters_by_band():
    pairs_df = _make_pairs_df(
        [
            {
                "sector_x": "A",
                "sector_y": "B",
                "band": "短期",
                "dominant_lag_days": 5.0,
                "mean_coherence": 0.9,
                "leading_sector": "A",
                "lagging_sector": "B",
                "lag_days_abs": 5.0,
            }
        ]
    )

    result = build_mermaid_lead_lag_graph(pairs_df, band="中期", coherence_threshold=0.5)

    assert result is None


def test_build_mermaid_lead_lag_graph_returns_none_when_no_edges_meet_threshold():
    pairs_df = _make_pairs_df(
        [
            {
                "sector_x": "A",
                "sector_y": "B",
                "band": "中期",
                "dominant_lag_days": 2.0,
                "mean_coherence": 0.1,
                "leading_sector": "A",
                "lagging_sector": "B",
                "lag_days_abs": 2.0,
            }
        ]
    )

    result = build_mermaid_lead_lag_graph(pairs_df, band="中期", coherence_threshold=0.5)

    assert result is None


def test_build_mermaid_lead_lag_graph_returns_none_for_empty_dataframe():
    pairs_df = _make_pairs_df([])

    result = build_mermaid_lead_lag_graph(pairs_df, band="中期", coherence_threshold=0.5)

    assert result is None


def test_build_mermaid_lead_lag_graph_uses_synthetic_node_ids_for_special_characters():
    pairs_df = _make_pairs_df(
        [
            {
                "sector_x": "電機・精密",
                "sector_y": "情報通信・サービスその他",
                "band": "中期",
                "dominant_lag_days": 3.0,
                "mean_coherence": 0.9,
                "leading_sector": "電機・精密",
                "lagging_sector": "情報通信・サービスその他",
                "lag_days_abs": 3.0,
            }
        ]
    )

    result = build_mermaid_lead_lag_graph(pairs_df, band="中期", coherence_threshold=0.5)

    assert result is not None
    # ノード定義行にラベルとして業種名が入る
    assert '["電機・精密"]' in result
    assert '["情報通信・サービスその他"]' in result
    # エッジ行はS0 -->|...| S1のような合成IDを使い、業種名を直接IDに使わない
    edge_lines = [line for line in result.splitlines() if "-->" in line]
    assert len(edge_lines) == 1
    assert edge_lines[0].strip().startswith("S")
    assert "電機・精密 -->" not in result
```

- [ ] **Step 2: テストを実行し、失敗することを確認する**

Run: `cd app && uv run pytest tests/test_sector_network.py -v`
Expected: `ModuleNotFoundError: No module named 'sector_analysis.network'`でFAIL

- [ ] **Step 3: `sector_analysis/network.py`を実装する**

```python
import pandas as pd


def build_mermaid_lead_lag_graph(
    pairs_df: pd.DataFrame,
    band: str,
    coherence_threshold: float,
) -> str | None:
    """周期帯・コヒーレンス閾値でフィルタした業種間リード・ラグ関係を
    Mermaidの有向グラフ定義（flowchart LR）として返す。

    pairs_dfはcompute_all_pairs_dominant_lagの戻り値と同じ列構成を持つ
    （sector_x, sector_y, band, dominant_lag_days, mean_coherence,
    leading_sector, lagging_sector, lag_days_abs）。
    フィルタ後にエッジが0件の場合はNoneを返す。
    """
    if pairs_df.empty:
        return None

    filtered = pairs_df[
        (pairs_df["band"] == band) & (pairs_df["mean_coherence"] >= coherence_threshold)
    ]
    if filtered.empty:
        return None

    # 業種名は「・」等Mermaidのノードid規則に使えない文字を含みうるため、
    # S0, S1, ...の合成idを割り当て、業種名はラベルとしてのみ使う
    sectors = sorted(set(filtered["leading_sector"]) | set(filtered["lagging_sector"]))
    node_ids = {sector: f"S{i}" for i, sector in enumerate(sectors)}

    lines = ["flowchart LR"]
    for sector, node_id in node_ids.items():
        lines.append(f'    {node_id}["{sector}"]')
    for _, row in filtered.iterrows():
        leading_id = node_ids[row["leading_sector"]]
        lagging_id = node_ids[row["lagging_sector"]]
        label = f'{row["lag_days_abs"]:.1f}日 / coh {row["mean_coherence"]:.2f}'
        lines.append(f'    {leading_id} -->|"{label}"| {lagging_id}')

    return "\n".join(lines)
```

- [ ] **Step 4: テストを実行し、パスすることを確認する**

Run: `cd app && uv run pytest tests/test_sector_network.py -v`
Expected: 5件PASS

- [ ] **Step 5: コミット**

```bash
cd app
git add sector_analysis/network.py tests/test_sector_network.py
git commit -m "feat: 業種間リード・ラグ関係をMermaidグラフとして生成するbuild_mermaid_lead_lag_graphを追加"
```

---

### Task 3: `app.py` — 全ペア一括計算の統合とUIセクション追加

**Files:**
- Modify: `pyproject.toml`（`streamlit-mermaid`依存追加）
- Modify: `app.py`

**Interfaces:**
- Consumes: `sector_analysis.wavelet.compute_all_pairs_dominant_lag`（Task 1）、`sector_analysis.network.build_mermaid_lead_lag_graph`（Task 2）、`streamlit_mermaid.st_mermaid`、既存の`sector_returns`（ローカル変数）・`pairs`・`payload`・`CACHE_DIR`・`read_cache`/`write_cache`
- Produces: なし（UIセクションの追加のみ）

このタスクはUI配線のみのため、既存方針（`app.py`はロジックを持たせず薄い呼び出しに留め、自動テスト対象外・手動確認）に従いTDDステップは適用しない。Task 4で手動確認する。

- [ ] **Step 1: 新規依存`streamlit-mermaid`を追加する**

```bash
cd app
uv add streamlit-mermaid
```

Expected: `pyproject.toml`の`dependencies`に`"streamlit-mermaid>=..."`（実際に解決されたバージョン）が追加され、`uv.lock`が更新される。

- [ ] **Step 2: importを追加する**

`app.py`の`from sector_analysis.wavelet import (...)`ブロック（現状51〜56行目付近）を以下に変更する:

現状:
```python
from sector_analysis.wavelet import (
    compute_cross_wavelet_lead_lag,
    compute_dominant_lag_series,
    deserialize_sector_returns,
    serialize_sector_returns,
    summarize_band_snapshot,
)
```

変更後:
```python
from sector_analysis.network import build_mermaid_lead_lag_graph
from sector_analysis.wavelet import (
    compute_all_pairs_dominant_lag,
    compute_cross_wavelet_lead_lag,
    compute_dominant_lag_series,
    deserialize_sector_returns,
    serialize_sector_returns,
    summarize_band_snapshot,
)
```

さらに、`from streamlit_mermaid import st_mermaid`を`import streamlit as st`の直後に追加する。

- [ ] **Step 3: キャッシュ読み込み時のスキーマ移行チェックを拡張する**

現状（`app.py:759-761`付近）:
```python
        if payload is not None and "sector_returns" not in payload:
            # 旧スキーマのキャッシュ（sector_returns未保存）は再計算して移行する
            payload = None
```

変更後:
```python
        if payload is not None and (
            "sector_returns" not in payload or "network_pairs" not in payload
        ):
            # 旧スキーマのキャッシュ（sector_returns/network_pairs未保存）は再計算して移行する
            payload = None
```

- [ ] **Step 4: 全ペア一括計算をpayloadに追加する**

現状（`app.py:785-798`付近）:
```python
                sector_returns = compute_sector_returns(prices_by_ticker, SECTOR_MAP)
                excluded_sectors = sorted(
                    set(SECTOR_MAP.values()) - set(sector_returns.keys())
                )
                pairs = compute_lead_lag_pairs(sector_returns, max_lag_days=20)
                comments = generate_sector_rotation_comments(pairs[:5], call_llm=call_llm)
                payload = {
                    "pairs": pairs,
                    "skipped_tickers": skipped_tickers,
                    "excluded_sectors": excluded_sectors,
                    "comments": comments,
                    "sector_returns": serialize_sector_returns(sector_returns),
                }
                write_cache(CACHE_DIR, cache_key, json.dumps(payload, ensure_ascii=False))
```

変更後:
```python
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

- [ ] **Step 5: 新UIセクション「業種間ネットワーク（全ペア俯瞰）」を追加する**

既存の、相関ペアの`if pairs: ... else: st.info("有効な業種ペアがありませんでした。")`ブロックの直後・既存の`st.subheader("ウェーブレット分析（時間変化するリード・ラグ）", ...)`の直前（`app.py:901-904`付近）に、以下を挿入する:

現状:
```python
        else:
            st.info("有効な業種ペアがありませんでした。")

        st.subheader(
            "ウェーブレット分析（時間変化するリード・ラグ）",
```

変更後:
```python
        else:
            st.info("有効な業種ペアがありませんでした。")

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

        network_df = pd.DataFrame(payload["network_pairs"])
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
            st_mermaid(mermaid_code)

        st.subheader(
            "ウェーブレット分析（時間変化するリード・ラグ）",
```

- [ ] **Step 6: 既存テストスイートを実行し、副作用がないことを確認する**

Run: `cd app && uv run pytest -v`
Expected: 全件PASS（`app.py`はテスト対象外のため件数に変化はない）

- [ ] **Step 7: コミット**

```bash
cd app
git add pyproject.toml uv.lock app.py
git commit -m "feat: セクターローテーションタブに業種間ネットワーク（全ペア俯瞰・Mermaid）セクションを追加"
```

---

### Task 4: UI動作の手動確認

**Files:** なし（コード変更なし、動作確認のみ）

**Interfaces:**
- Consumes: Task 1〜3で実装した一式
- Produces: なし（確認結果をこのタスクの完了条件とする）

- [ ] **Step 1: アプリを起動し、セクターローテーションタブで分析を実行する**

Run: `cd app && uv run python -m streamlit run app.py`

手順:
1. セクターローテーションタブを開き、「キャッシュを無視して再生成する」をチェックした状態で「分析を実行」をクリックする
2. 「ネットワーク図データを計算中（136ペア）...」のスピナーが表示され、完了後に「業種間ネットワーク（全ペア俯瞰）」セクションが表示されることを確認する
3. デフォルト（周期帯: 中期、閾値: 0.5）でMermaidグラフが描画される、または「十分な確信度を持つ関係が見つかりませんでした。」の情報メッセージが表示されることを確認する

Expected: エラーなく表示される

- [ ] **Step 2: 周期帯・閾値の操作を確認する**

周期帯セレクトボックスを短期・長期に切り替え、コヒーレンス閾値スライダーを0付近まで下げる。

Expected:
- 周期帯切り替えでMermaidグラフの内容（ノード・エッジ）が変化する
- 閾値を下げるとエッジ数が増え、上げるとエッジ数が減る、または閾値0.95等で「十分な確信度を持つ関係が見つかりませんでした。」に切り替わる
- ブラウザコンソールにエラーが出ていないこと

- [ ] **Step 3: キャッシュ移行を確認する**

Task 1〜3実装前に生成された既存の`data/cache/*-sector-rotation-*.txt`が存在する場合、それを使って「キャッシュを無視して再生成する」をチェックせずに「分析を実行」をクリックし、`network_pairs`キーがないため自動的に再計算されること（かつエラーにならないこと）を確認する。該当ファイルがない場合はこのステップをスキップしてよい。

- [ ] **Step 4: 既存セクション・他タブに影響がないことを確認する**

既存の「業種間相関ヒートマップ」「リード・ラグ上位ペア」「相関上位5ペアのAIコメント」「ウェーブレット分析（時間変化するリード・ラグ）」（2業種選択ドリルダウン、AI解説含む）、およびポートフォリオ・スクリーニング・バックテスト・一括バックテストの各タブが、これまで通り動作することを確認する。

Expected: 既存機能に回帰がない。`uv run pytest`が全件PASSすることも併せて確認する。

---

## Global Constraintsの確認（実装完了時のチェックリスト）

- [ ] 新規の実行時依存が`streamlit-mermaid`のみであること（`pyproject.toml`確認）
- [ ] `sector_analysis/correlation.py`、既存の2業種ドリルダウン・AI解説関連コードに変更がないこと
- [ ] エッジクリック連携・統計的有意性検定・周期帯統合表示を実装していないこと
- [ ] 旧スキーマキャッシュ（`sector_returns`または`network_pairs`なし）が再計算されること（Task 4 Step 3で確認）
- [ ] `uv run pytest`が全件PASSすること
