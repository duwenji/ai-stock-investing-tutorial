# セクターローテーション ウェーブレット分析 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** セクターローテーションタブに、連続ウェーブレット変換（CWT）に基づくクロスウェーブレット・コヒーレンスと位相差を使い、選択した2業種について「時間×周期の長さ」ごとの先行・追随関係を可視化する、オンデマンドのドリルダウンセクションを追加する。

**Architecture:** 新規モジュール`sector_analysis/wavelet.py`に、CWT計算・コヒーレンス/ラグ算出・帯域分類・キャッシュ用シリアライズの純粋関数群を実装する。`app.py`のセクターローテーションタブに、既存のキャッシュpayloadへ`sector_returns`を追加保存する変更と、新しいUIセクション（業種選択・ヒートマップ・帯域別の支配的ラグ折れ線グラフ）を追加する。既存の相関上位ペア一覧・AIコメント機能は変更しない。

**Tech Stack:** Python 3.14, pandas, numpy, pywt (PyWavelets, 新規依存), altair, pytest, uv

## Global Constraints

- 新規の実行時依存は`pywt`（PyPI配布名`pywavelets`）のみ。scipy等その他の新規依存は追加しない
- モンテカルロ法によるコヒーレンスの統計的有意性検定は実装しない
- 平滑化は時間軸方向のみ（スケール軸方向の平滑化は行わない）
- 136業種ペア全体の一括ウェーブレット計算は行わない（選択した2業種のみのオンデマンド計算）
- 既存の相関上位ペア一覧・AIコメント機能（`sector_analysis/correlation.py`, `prompt_patterns/sector_rotation.py`）は変更しない
- 既存の`sector-rotation-*`キャッシュ（`sector_returns`キーを持たない旧スキーマ）は、読み込み時にキャッシュミス扱いとして再計算する

---

### Task 1: `sector_analysis/wavelet.py` — ウェーブレット計算とシリアライズヘルパー

**Files:**
- Create: `sector_analysis/wavelet.py`
- Test: `tests/test_sector_wavelet.py`

**Interfaces:**
- Consumes: `pd.Series`（業種別日次リターン系列、`sector_analysis/correlation.py`の`compute_sector_returns`と同じ形）
- Produces:
  - `PERIOD_BANDS: dict[str, tuple[float, float]]`
  - `classify_period_band(period_days: float) -> str | None`
  - `compute_cross_wavelet_lead_lag(series_x, series_y, sector_x_name, sector_y_name, min_period_days=4.0, max_period_days=120.0, voices_per_octave=4) -> pd.DataFrame`（列: `date, period_days, band, coherence, lag_days, leading_sector`）
  - `compute_dominant_lag_series(band_df: pd.DataFrame) -> pd.DataFrame`（列: `date, dominant_lag_days`）
  - `serialize_sector_returns(sector_returns: dict[str, pd.Series]) -> dict[str, dict[str, list]]`
  - `deserialize_sector_returns(data: dict[str, dict[str, list]]) -> dict[str, pd.Series]`
  - 後続タスク（`app.py`）はこれら6つのシンボルをそのまま利用する。

- [ ] **Step 1: 新規依存`pywavelets`を追加する**

```bash
cd app
uv add pywavelets
```

Expected: `pyproject.toml`の`dependencies`に`"pywavelets>=1.9.0"`（実際に解決されたバージョン）が追加され、`uv.lock`が更新される。

- [ ] **Step 2: 失敗するテストを書く**

`tests/test_sector_wavelet.py` を新規作成する:

```python
import numpy as np
import pandas as pd

from sector_analysis.wavelet import (
    classify_period_band,
    compute_cross_wavelet_lead_lag,
    compute_dominant_lag_series,
    deserialize_sector_returns,
    serialize_sector_returns,
)


def test_classify_period_band_boundaries():
    assert classify_period_band(4.0) == "短期"
    assert classify_period_band(9.9) == "短期"
    assert classify_period_band(10.0) == "中期"
    assert classify_period_band(39.9) == "中期"
    assert classify_period_band(40.0) == "長期"
    assert classify_period_band(120.0) == "長期"
    assert classify_period_band(3.9) is None
    assert classify_period_band(120.1) is None


def test_compute_cross_wavelet_lead_lag_detects_known_lag():
    n = 240
    t = np.arange(n)
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    period = 20.0
    shift = 5
    base = pd.Series(np.sin(2 * np.pi * t / period), index=dates)
    # laggedはbaseよりshift日遅れて追随する（＝baseが先行）
    lagged = pd.Series(np.sin(2 * np.pi * (t - shift) / period), index=dates)

    df = compute_cross_wavelet_lead_lag(base, lagged, "X", "Y")

    assert not df.empty
    near_period = df[(df["period_days"] >= 15) & (df["period_days"] <= 25)]
    assert not near_period.empty
    median_lag = near_period["lag_days"].median()
    assert abs(median_lag - shift) < 3
    assert (near_period["leading_sector"] == "X").mean() > 0.6


def test_compute_cross_wavelet_lead_lag_coherence_bounds():
    n = 240
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    rng = np.random.default_rng(0)
    x = pd.Series(rng.normal(size=n), index=dates)
    y = pd.Series(rng.normal(size=n), index=dates)

    df = compute_cross_wavelet_lead_lag(x, y, "X", "Y")

    assert not df.empty
    assert (df["coherence"] >= 0).all()
    assert (df["coherence"] <= 1).all()


def test_compute_cross_wavelet_lead_lag_returns_empty_for_insufficient_data():
    dates = pd.date_range("2025-01-01", periods=10, freq="D")
    x = pd.Series(np.arange(10, dtype=float), index=dates)
    y = pd.Series(np.arange(10, dtype=float), index=dates)

    df = compute_cross_wavelet_lead_lag(x, y, "X", "Y")

    assert list(df.columns) == [
        "date", "period_days", "band", "coherence", "lag_days", "leading_sector",
    ]
    assert df.empty


def test_compute_dominant_lag_series_weights_by_coherence():
    dates = pd.date_range("2025-01-01", periods=2, freq="D")
    band_df = pd.DataFrame(
        {
            "date": [dates[0], dates[0], dates[1], dates[1]],
            "lag_days": [10.0, 0.0, 5.0, 5.0],
            "coherence": [1.0, 0.0, 0.5, 0.5],
        }
    )

    result = compute_dominant_lag_series(band_df)

    assert list(result["dominant_lag_days"]) == [10.0, 5.0]


def test_serialize_deserialize_sector_returns_round_trip():
    dates = pd.date_range("2025-01-01", periods=3, freq="D")
    original = {"業種X": pd.Series([0.01, np.nan, -0.02], index=dates)}

    data = serialize_sector_returns(original)
    restored = deserialize_sector_returns(data)

    pd.testing.assert_series_equal(
        restored["業種X"], original["業種X"], check_names=False
    )
```

- [ ] **Step 3: テストを実行し、失敗することを確認する**

Run: `cd app && uv run pytest tests/test_sector_wavelet.py -v`
Expected: `ModuleNotFoundError: No module named 'sector_analysis.wavelet'` でFAIL

- [ ] **Step 4: `sector_analysis/wavelet.py`を実装する**

```python
import numpy as np
import pandas as pd
import pywt

WAVELET = "cmor1.5-1.0"

PERIOD_BANDS: dict[str, tuple[float, float]] = {
    "短期": (4.0, 10.0),
    "中期": (10.0, 40.0),
    "長期": (40.0, 120.0),
}


def classify_period_band(period_days: float) -> str | None:
    """周期（営業日）をPERIOD_BANDSに基づき短期/中期/長期に分類する。

    範囲外（4未満、または120超）の場合はNoneを返す。
    """
    bands = list(PERIOD_BANDS.items())
    for index, (band, (lo, hi)) in enumerate(bands):
        is_last = index == len(bands) - 1
        in_range = lo <= period_days <= hi if is_last else lo <= period_days < hi
        if in_range:
            return band
    return None


def serialize_sector_returns(
    sector_returns: dict[str, pd.Series],
) -> dict[str, dict[str, list]]:
    """業種別リターン系列の辞書を、JSON保存可能な辞書に変換する。NaNはNoneに変換する。"""
    return {
        sector: {
            "dates": [d.isoformat() for d in series.index],
            "values": [None if pd.isna(v) else float(v) for v in series],
        }
        for sector, series in sector_returns.items()
    }


def deserialize_sector_returns(
    data: dict[str, dict[str, list]],
) -> dict[str, pd.Series]:
    """serialize_sector_returnsの逆変換。Noneはnp.nanに戻す。"""
    result: dict[str, pd.Series] = {}
    for sector, payload in data.items():
        values = [np.nan if v is None else v for v in payload["values"]]
        index = pd.to_datetime(payload["dates"])
        result[sector] = pd.Series(values, index=index)
    return result


def _build_scales(
    min_period_days: float, max_period_days: float, voices_per_octave: int
) -> tuple[np.ndarray, np.ndarray]:
    num_octaves = np.log2(max_period_days / min_period_days)
    n_scales = max(2, int(round(num_octaves * voices_per_octave)) + 1)
    periods = np.geomspace(min_period_days, max_period_days, n_scales)
    center_freq = pywt.central_frequency(WAVELET)
    scales = center_freq * periods  # sampling_period = 1日
    return scales, periods


def _smooth_along_time(coeffs: np.ndarray, periods: np.ndarray) -> np.ndarray:
    # スケール（周期）ごとに、その周期の長さに比例した窓幅のboxcarフィルタで
    # 時間軸方向に平滑化する。コヒーレンス計算に必須（平滑化なしでは常に1になる）。
    smoothed = np.empty_like(coeffs)
    for i, period in enumerate(periods):
        window = max(1, int(round(period)))
        kernel = np.ones(window) / window
        pad_left = window // 2
        pad_right = window - pad_left - 1
        padded = np.pad(coeffs[i], (pad_left, pad_right), mode="edge")
        smoothed[i] = np.convolve(padded, kernel, mode="valid")
    return smoothed


def compute_cross_wavelet_lead_lag(
    series_x: pd.Series,
    series_y: pd.Series,
    sector_x_name: str,
    sector_y_name: str,
    min_period_days: float = 4.0,
    max_period_days: float = 120.0,
    voices_per_octave: int = 4,
) -> pd.DataFrame:
    """2業種の日次リターン系列から、時間×周期ごとのクロスウェーブレット・
    コヒーレンスと符号付きラグ（どちらの業種が何営業日先行するか）を計算する。

    lag_days > 0はsector_x_nameが先行、lag_days < 0はsector_y_nameが先行することを示す。
    共通の非欠損データ数がmax_period_days * 2未満の場合は空のDataFrameを返す。
    """
    columns = ["date", "period_days", "band", "coherence", "lag_days", "leading_sector"]
    combined = pd.concat([series_x.rename("x"), series_y.rename("y")], axis=1).dropna()
    if len(combined) < max_period_days * 2:
        return pd.DataFrame(columns=columns)

    scales, periods = _build_scales(min_period_days, max_period_days, voices_per_octave)
    coeffs_x, _ = pywt.cwt(combined["x"].to_numpy(), scales, WAVELET, sampling_period=1.0)
    coeffs_y, _ = pywt.cwt(combined["y"].to_numpy(), scales, WAVELET, sampling_period=1.0)

    sxx = _smooth_along_time(coeffs_x * np.conj(coeffs_x), periods).real
    syy = _smooth_along_time(coeffs_y * np.conj(coeffs_y), periods).real
    sxy = _smooth_along_time(coeffs_x * np.conj(coeffs_y), periods)

    with np.errstate(divide="ignore", invalid="ignore"):
        coherence = np.abs(sxy) ** 2 / (sxx * syy)
    coherence = np.clip(np.nan_to_num(coherence, nan=0.0), 0.0, 1.0)

    phase = np.angle(sxy)
    lag_days = phase / (2 * np.pi) * periods[:, None]

    n_scales, n_time = lag_days.shape
    dates = combined.index
    band_per_scale = [classify_period_band(p) for p in periods]
    lag_flat = lag_days.flatten()

    df = pd.DataFrame(
        {
            "date": np.tile(dates.values, n_scales),
            "period_days": np.repeat(periods, n_time),
            "band": np.repeat(band_per_scale, n_time),
            "coherence": coherence.flatten(),
            "lag_days": lag_flat,
            "leading_sector": np.where(lag_flat >= 0, sector_x_name, sector_y_name),
        }
    )
    return df[df["band"].notna()].reset_index(drop=True)


def compute_dominant_lag_series(band_df: pd.DataFrame) -> pd.DataFrame:
    """特定周期帯のDataFrame（date, lag_days, coherenceを含む）から、
    日付ごとのコヒーレンス加重平均ラグを計算する。コヒーレンス合計が0の日付は除外する。
    """
    weighted = band_df.assign(_weighted_lag=band_df["lag_days"] * band_df["coherence"])
    agg = weighted.groupby("date").agg(
        _weighted_sum=("_weighted_lag", "sum"), _weight_total=("coherence", "sum")
    )
    agg = agg[agg["_weight_total"] > 0]
    agg["dominant_lag_days"] = agg["_weighted_sum"] / agg["_weight_total"]
    return agg.reset_index()[["date", "dominant_lag_days"]]
```

- [ ] **Step 5: テストを実行し、パスすることを確認する**

Run: `cd app && uv run pytest tests/test_sector_wavelet.py -v`
Expected: 6件PASS

- [ ] **Step 6: コミット**

```bash
cd app
git add pyproject.toml uv.lock sector_analysis/wavelet.py tests/test_sector_wavelet.py
git commit -m "feat: ウェーブレット分析によるセクター間の時間変化するリード・ラグ計算を追加"
```

---

### Task 2: `app.py`にウェーブレット分析セクションを追加する

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: `sector_analysis.wavelet.compute_cross_wavelet_lead_lag` / `compute_dominant_lag_series` / `serialize_sector_returns` / `deserialize_sector_returns`（Task 1）、既存の`sector_returns`（ローカル変数）・`pairs`・`payload`・`CACHE_DIR`・`read_cache`/`write_cache`
- Produces: なし（UIセクションの追加のみ）

このタスクはUI配線のみのため、既存方針（`app.py`はロジックを持たせず薄い呼び出しに留め、自動テスト対象外・手動確認）に従いTDDステップは適用しない。Task 3で手動確認する。

- [ ] **Step 1: importを追加する**

`app.py`の48行目（`from sector_analysis.correlation import compute_lead_lag_pairs, compute_sector_returns`）の直後に以下を追加する:

```python
from sector_analysis.wavelet import (
    compute_cross_wavelet_lead_lag,
    compute_dominant_lag_series,
    deserialize_sector_returns,
    serialize_sector_returns,
)
```

- [ ] **Step 2: キャッシュ読み込み時に旧スキーマを再計算扱いにする**

現状（`app.py:724-727`付近）:
```python
        cached_payload = (
            None if sector_force_regenerate else read_cache(CACHE_DIR, cache_key)
        )
        payload = json.loads(cached_payload) if cached_payload is not None else None
```

変更後:
```python
        cached_payload = (
            None if sector_force_regenerate else read_cache(CACHE_DIR, cache_key)
        )
        payload = json.loads(cached_payload) if cached_payload is not None else None
        if payload is not None and "sector_returns" not in payload:
            # 旧スキーマのキャッシュ（sector_returns未保存）は再計算して移行する
            payload = None
```

- [ ] **Step 3: payloadに`sector_returns`を追加保存する**

現状（`app.py:750-763`付近）:
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

- [ ] **Step 4: ウェーブレット分析セクションを追加する**

現状のファイル末尾付近、`if pairs: ... else: st.info("有効な業種ペアがありませんでした。")`ブロックの直後・`if payload["skipped_tickers"]:`の直前（`app.py:831-833`付近）に、以下を挿入する:

```python

        st.subheader("ウェーブレット分析（時間変化するリード・ラグ）")
        st.caption(
            "選択した2つの業種について、値動きの周期の長さ（短期・中期・長期）ごとに、"
            "どちらの業種がどれくらい先行しているかの時間変化を可視化します。"
            "色が薄い部分は関係の確からしさ（コヒーレンス）が低いことを示します。"
        )

        sector_options = sorted(payload["sector_returns"].keys())
        if len(sector_options) < 2:
            st.info("ウェーブレット分析には2業種以上のデータが必要です。")
        else:
            default_x = pairs[0]["leading_sector"] if pairs else sector_options[0]
            default_y = pairs[0]["lagging_sector"] if pairs else sector_options[1]
            if default_x not in sector_options:
                default_x = sector_options[0]
            if default_y not in sector_options or default_y == default_x:
                default_y = next(s for s in sector_options if s != default_x)

            col_a, col_b = st.columns(2)
            with col_a:
                sector_x = st.selectbox(
                    "業種A",
                    sector_options,
                    index=sector_options.index(default_x),
                    key="wavelet_sector_x",
                )
            with col_b:
                sector_y = st.selectbox(
                    "業種B",
                    sector_options,
                    index=sector_options.index(default_y),
                    key="wavelet_sector_y",
                )

            if st.button("ウェーブレット分析を実行"):
                all_series = deserialize_sector_returns(payload["sector_returns"])
                try:
                    wavelet_df = compute_cross_wavelet_lead_lag(
                        all_series[sector_x], all_series[sector_y], sector_x, sector_y
                    )
                except Exception:
                    st.error("ウェーブレット分析の計算に失敗しました。")
                    wavelet_df = pd.DataFrame()

                if wavelet_df.empty:
                    st.warning(
                        "選択した2業種の共通データが不足しているため、分析できませんでした。"
                    )
                    st.session_state["wavelet_result"] = None
                else:
                    st.session_state["wavelet_result"] = {
                        "df": wavelet_df,
                        "x": sector_x,
                        "y": sector_y,
                    }

            wavelet_result = st.session_state.get("wavelet_result")
            if wavelet_result is not None:
                wavelet_df = wavelet_result["df"]

                heatmap = (
                    alt.Chart(wavelet_df)
                    .mark_rect()
                    .encode(
                        x=alt.X("date:T", title=None),
                        y=alt.Y("period_days:O", title="周期（営業日）", sort="descending"),
                        color=alt.Color(
                            "lag_days:Q",
                            title=f"ラグ（正={wavelet_result['x']}が先行）",
                            scale=alt.Scale(scheme="redblue", domainMid=0),
                        ),
                        opacity=alt.Opacity(
                            "coherence:Q", scale=alt.Scale(domain=[0, 1], range=[0.05, 1])
                        ),
                        tooltip=[
                            "date:T",
                            "period_days:Q",
                            "band:N",
                            "coherence:Q",
                            "lag_days:Q",
                            "leading_sector:N",
                        ],
                    )
                    .properties(height=400)
                )
                st.altair_chart(heatmap, width="stretch")

                band = st.selectbox(
                    "周期帯", ["短期", "中期", "長期"], index=1, key="wavelet_band"
                )
                band_df = wavelet_df[wavelet_df["band"] == band]
                if band_df.empty:
                    st.info("この周期帯には有効なデータがありませんでした。")
                else:
                    dominant = compute_dominant_lag_series(band_df)
                    line = (
                        alt.Chart(dominant)
                        .mark_line()
                        .encode(
                            x=alt.X("date:T", title=None),
                            y=alt.Y("dominant_lag_days:Q", title="支配的ラグ（日）"),
                        )
                        .properties(height=250)
                    )
                    st.altair_chart(line, width="stretch")
```

- [ ] **Step 5: 既存テストスイートを実行し、副作用がないことを確認する**

Run: `cd app && uv run pytest -v`
Expected: 全件PASS（`app.py`はテスト対象外のため件数に変化はない）

- [ ] **Step 6: コミット**

```bash
cd app
git add app.py
git commit -m "feat: セクターローテーションタブにウェーブレット分析セクションを追加"
```

---

### Task 3: UI動作の手動確認

**Files:** なし（コード変更なし、動作確認のみ）

**Interfaces:**
- Consumes: Task 1〜2で実装した一式
- Produces: なし（確認結果をこのタスクの完了条件とする）

- [ ] **Step 1: アプリを起動し、セクターローテーションタブで分析を実行する**

Run: `cd app && uv run python -m streamlit run app.py`

手順:
1. セクターローテーションタブを開き、「キャッシュを無視して再生成する」をチェックした状態で「分析を実行」をクリックする
2. 完了後、「ウェーブレット分析（時間変化するリード・ラグ）」セクションが表示されることを確認する
3. 業種A・業種Bのデフォルト値が、リード・ラグ上位ペアの最上位（先行業種・追随業種）になっていることを確認する

Expected: エラーなく表示され、業種セレクトボックスに17業種（または実際に構成銘柄があった業種）が並ぶ

- [ ] **Step 2: ウェーブレット分析を実行し、結果を確認する**

「ウェーブレット分析を実行」をクリックする。
Expected:
- コヒーレンス×符号付きラグのヒートマップが表示される（低コヒーレンス部分は薄く表示される）
- 周期帯セレクトボックス（短期/中期/長期、デフォルト中期）を切り替えると、対応する支配的ラグの折れ線グラフが再描画される
- ブラウザコンソールにエラーが出ていないこと

- [ ] **Step 3: キャッシュ移行を確認する**

Task 1〜2実装前に生成された既存の`data/cache/*-sector-rotation-*.txt`が存在する場合、それを使って「キャッシュを無視して再生成する」をチェックせずに「分析を実行」をクリックし、`sector_returns`キーがないため自動的に再計算されること（かつエラーにならないこと）を確認する。該当ファイルがない場合はこのステップをスキップしてよい。

- [ ] **Step 4: 他のセクション・他タブに影響がないことを確認する**

既存の「業種間相関ヒートマップ」「リード・ラグ上位ペア」「相関上位5ペアのAIコメント」、およびポートフォリオ・スクリーニング・バックテスト・一括バックテストの各タブが、これまで通り動作することを確認する。

このタスクにチェックボックスの完了以外の成果物はない。

---

## Global Constraintsの確認（実装完了時のチェックリスト）

- [ ] 新規の実行時依存が`pywavelets`のみであること（`pyproject.toml`確認）
- [ ] `sector_analysis/correlation.py`・`prompt_patterns/sector_rotation.py`に変更がないこと
- [ ] モンテカルロ有意性検定・スケール軸平滑化・136ペア一括計算を実装していないこと
- [ ] 旧スキーマキャッシュ（`sector_returns`なし）が再計算されること（Task 3 Step 3で確認）
- [ ] `uv run pytest`が全件PASSすること
