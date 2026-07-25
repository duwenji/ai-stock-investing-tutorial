# ウェーブレット分析 直近シグナル要約＋AI解説コメント Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** セクターローテーションタブのウェーブレット分析セクションに、選択中の周期帯における「直近シグナルの要約パネル」（機械的な数値表示）と「AI解説コメント」（LLMによる解釈、日次キャッシュ付き）を追加する。

**Architecture:** `sector_analysis/wavelet.py` の集計関数を拡張して直近スナップショット（支配的ラグ・バンド平均コヒーレンス）を計算する純粋関数を追加し、新規 `prompt_patterns/wavelet_explanation.py` がそのスナップショットからLLM解説コメントを生成する。`app.py` は両者を呼び出し、既存の「支配的ラグ」折れ線グラフの直後にパネルとAIコメントUIを追加するだけの薄い接続層に留める。

**Tech Stack:** Python 3.14 / pandas / Streamlit / pytest（`call_llm`はモック化してテスト）。新規外部依存は追加しない。

## Global Constraints

- `compute_dominant_lag_series` の既存呼び出し元（`app.py`の折れ線グラフ描画、既存テスト）を壊さない列追加のみ行う（既存カラム `date`, `dominant_lag_days` は維持）。
- AIコメント生成関数はJSON出力を要求せず、プレーンテキストをそのまま返す（他のバッチコメント関数と異なるパターン）。
- AIコメントは明示的なボタン押下でのみ生成する。周期帯セレクトボックスの変更だけで自動的にLLM呼び出しを発生させない。
- 表示中の業種ペア・周期帯と異なる古いAIコメントを画面に残さない（`(sector_x, sector_y, sector_period, band)` の一致を確認してから表示する）。
- 個別の免責文はAIコメント直下に追加しない。既存のタブ末尾 `DISCLAIMER_NOTICE` に委ねる。
- キャッシュは他タブと同じ日次ファイルキャッシュ方式（`common/cache.py::read_cache` / `write_cache`、キーは `"wavelet-comment-" + sha256(...)[:12]`）を使う。

---

### Task 1: `sector_analysis/wavelet.py` — `avg_coherence` 列と `summarize_band_snapshot`

**Files:**
- Modify: `ai-stock-investing-tutorial/app/sector_analysis/wavelet.py`
- Test: `ai-stock-investing-tutorial/app/tests/test_sector_wavelet.py`

**Interfaces:**
- Consumes: 既存の `compute_dominant_lag_series(band_df: pd.DataFrame) -> pd.DataFrame`（列: `date`, `lag_days`, `coherence` を持つDataFrameを入力とする）
- Produces:
  - `compute_dominant_lag_series(band_df) -> pd.DataFrame`（戻り値の列に `avg_coherence: float` を追加。既存の `date`, `dominant_lag_days` は維持）
  - `summarize_band_snapshot(band_df: pd.DataFrame) -> dict | None`（戻り値: `{"date": pd.Timestamp, "dominant_lag_days": float, "avg_coherence": float}`、データなしなら `None`）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_sector_wavelet.py` の `test_compute_dominant_lag_series_weights_by_coherence` の直後に、以下を追加する（`summarize_band_snapshot` のインポートも追加する）。

```python
from sector_analysis.wavelet import (
    classify_period_band,
    compute_cross_wavelet_lead_lag,
    compute_dominant_lag_series,
    deserialize_sector_returns,
    serialize_sector_returns,
    summarize_band_snapshot,
)
```

```python
def test_compute_dominant_lag_series_includes_avg_coherence():
    dates = pd.date_range("2025-01-01", periods=2, freq="D")
    band_df = pd.DataFrame(
        {
            "date": [dates[0], dates[0], dates[1], dates[1]],
            "lag_days": [10.0, 0.0, 5.0, 5.0],
            "coherence": [1.0, 0.0, 0.5, 0.3],
        }
    )

    result = compute_dominant_lag_series(band_df)

    assert list(result["avg_coherence"]) == [0.5, 0.4]


def test_summarize_band_snapshot_returns_latest_snapshot():
    dates = pd.date_range("2025-01-01", periods=2, freq="D")
    band_df = pd.DataFrame(
        {
            "date": [dates[0], dates[0], dates[1], dates[1]],
            "lag_days": [10.0, 0.0, 5.0, 5.0],
            "coherence": [1.0, 0.0, 0.5, 0.3],
        }
    )

    snapshot = summarize_band_snapshot(band_df)

    assert snapshot == {
        "date": dates[1],
        "dominant_lag_days": 5.0,
        "avg_coherence": 0.4,
    }


def test_summarize_band_snapshot_returns_none_for_empty_df():
    band_df = pd.DataFrame(columns=["date", "lag_days", "coherence"])

    assert summarize_band_snapshot(band_df) is None
```

- [ ] **Step 2: テストを実行し、失敗することを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/test_sector_wavelet.py -v`
Expected: `ImportError: cannot import name 'summarize_band_snapshot'`（`summarize_band_snapshot` が未定義のため）で失敗する。

- [ ] **Step 3: 最小限の実装を書く**

`sector_analysis/wavelet.py` の `compute_dominant_lag_series` 関数を以下に置き換える。

```python
def compute_dominant_lag_series(band_df: pd.DataFrame) -> pd.DataFrame:
    """特定周期帯のDataFrame（date, lag_days, coherenceを含む）から、
    日付ごとのコヒーレンス加重平均ラグを計算する。コヒーレンス合計が0の日付は除外する。

    avg_coherenceは、その日付における対象バンド内の周期（スケール）方向の
    コヒーレンス単純平均（重み付けなし）。dominant_lag_daysの重み付けとは
    独立した「その日のバンド全体の確からしさ」の目安として扱う。
    """
    weighted = band_df.assign(_weighted_lag=band_df["lag_days"] * band_df["coherence"])
    agg = weighted.groupby("date").agg(
        _weighted_sum=("_weighted_lag", "sum"),
        _weight_total=("coherence", "sum"),
        avg_coherence=("coherence", "mean"),
    )
    agg = agg[agg["_weight_total"] > 0]
    agg["dominant_lag_days"] = agg["_weighted_sum"] / agg["_weight_total"]
    return agg.reset_index()[["date", "dominant_lag_days", "avg_coherence"]]


def summarize_band_snapshot(band_df: pd.DataFrame) -> dict | None:
    """特定周期帯のDataFrameから、直近日付における支配的ラグとバンド平均
    コヒーレンスのスナップショットを返す。有効なデータがなければNoneを返す。
    """
    dominant = compute_dominant_lag_series(band_df)
    if dominant.empty:
        return None
    last = dominant.iloc[-1]
    return {
        "date": last["date"],
        "dominant_lag_days": float(last["dominant_lag_days"]),
        "avg_coherence": float(last["avg_coherence"]),
    }
```

- [ ] **Step 4: テストを実行し、成功することを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/test_sector_wavelet.py -v`
Expected: 全テストPASS（既存の `test_compute_dominant_lag_series_weights_by_coherence` を含む）。

- [ ] **Step 5: コミット**

```bash
cd ai-stock-investing-tutorial
git add app/sector_analysis/wavelet.py app/tests/test_sector_wavelet.py
git commit -m "$(cat <<'EOF'
Add avg_coherence and summarize_band_snapshot to sector_analysis/wavelet

Gives the wavelet drilldown a single latest-signal snapshot (dominant
lag + band-average coherence) that both a UI summary panel and an AI
explanation prompt can share as their common source of truth.
EOF
)"
```

---

### Task 2: `prompt_patterns/wavelet_explanation.py` — AI解説プロンプト生成

**Files:**
- Create: `ai-stock-investing-tutorial/app/prompt_patterns/wavelet_explanation.py`
- Test: `ai-stock-investing-tutorial/app/tests/test_wavelet_explanation_prompt.py`

**Interfaces:**
- Consumes: Task 1の `summarize_band_snapshot` が返す `dict`（`{"date": pd.Timestamp, "dominant_lag_days": float, "avg_coherence": float}`）。`data_api.llm_client.call_llm(prompt: str) -> str`（既存関数、デフォルト引数として使用）。
- Produces:
  - `build_wavelet_prompt(sector_x: str, sector_y: str, band: str, snapshot: dict) -> str`
  - `generate_wavelet_explanation(sector_x: str, sector_y: str, band: str, snapshot: dict, call_llm=default_call_llm) -> str`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_wavelet_explanation_prompt.py` を新規作成する。

```python
import pandas as pd

from prompt_patterns.wavelet_explanation import (
    build_wavelet_prompt,
    generate_wavelet_explanation,
)


def _snapshot(lag_days: float = 3.2, avg_coherence: float = 0.62) -> dict:
    return {
        "date": pd.Timestamp("2026-07-24"),
        "dominant_lag_days": lag_days,
        "avg_coherence": avg_coherence,
    }


def test_build_wavelet_prompt_includes_snapshot_data_and_no_directive_language():
    prompt = build_wavelet_prompt("電機・精密", "機械", "中期", _snapshot())

    assert "電機・精密" in prompt
    assert "機械" in prompt
    assert "中期" in prompt
    assert "2026-07-24" in prompt
    assert "3.2" in prompt
    assert "0.62" in prompt
    assert "過去" in prompt
    assert "将来" in prompt
    assert "売買" in prompt


def test_build_wavelet_prompt_negative_lag_swaps_leading_sector():
    prompt = build_wavelet_prompt("電機・精密", "機械", "中期", _snapshot(lag_days=-4.0))

    assert "機械が電機・精密に先行" in prompt


def test_generate_wavelet_explanation_returns_stripped_llm_output():
    fake_call_llm = lambda prompt: "  先行して動く傾向があります。  \n"

    result = generate_wavelet_explanation(
        "電機・精密", "機械", "中期", _snapshot(), call_llm=fake_call_llm
    )

    assert result == "先行して動く傾向があります。"
```

- [ ] **Step 2: テストを実行し、失敗することを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/test_wavelet_explanation_prompt.py -v`
Expected: `ModuleNotFoundError: No module named 'prompt_patterns.wavelet_explanation'` で失敗する。

- [ ] **Step 3: 最小限の実装を書く**

`prompt_patterns/wavelet_explanation.py` を新規作成する。

```python
# 選択した2業種・1周期帯のウェーブレット分析スナップショット（直近の支配的ラグ・
# コヒーレンス）をLLMに解説させるプロンプトを組み立てるモジュール。
# ウェーブレット計算自体はPython側（sector_analysis/wavelet.py）で完了させる。
from data_api.llm_client import call_llm as default_call_llm


def build_wavelet_prompt(
    sector_x: str, sector_y: str, band: str, snapshot: dict
) -> str:
    # 事前に算出済みの直近スナップショットをそのまま渡し、LLMには解釈のみ任せる。
    date_str = snapshot["date"].strftime("%Y-%m-%d")
    lag = snapshot["dominant_lag_days"]
    coherence = snapshot["avg_coherence"]
    leading = sector_x if lag >= 0 else sector_y
    lagging = sector_y if lag >= 0 else sector_x
    return (
        f"以下は業種「{sector_x}」と業種「{sector_y}」について、周期帯「{band}」における"
        "ウェーブレット分析（クロスウェーブレット・コヒーレンスと位相差）の直近時点の"
        "計算結果です（Python側で計算済みのため再計算は不要です）。\n\n"
        f"- 日付: {date_str}\n"
        f"- 支配的ラグ: 約{abs(lag):.1f}営業日（{leading}が{lagging}に先行）\n"
        f"- コヒーレンス（関係の確からしさ、0〜1）: {coherence:.2f}\n\n"
        "この結果について、投資家向けの解説コメントを日本語で3〜4文程度で作成してください。\n"
        "以下を必ず含めてください。\n"
        "1. 上記の先行・追随関係とコヒーレンスの水準（高い/中程度/低い）が何を意味するかの説明\n"
        "2. これはあくまで過去の統計的傾向であり、将来の値動きを保証するものではないこと\n\n"
        # 統計的傾向の紹介にとどめ、売買を促す表現を避けさせる。
        "出力は事実の説明と教育的な考察にとどめ、「買うべき」「今すぐこの業種を"
        "売買すべき」のような指示的な表現は使わないでください。\n"
        "出力形式: コメント本文のみをプレーンテキストで出力してください。"
        "コードブロックや前置きは不要です。"
    )


def generate_wavelet_explanation(
    sector_x: str,
    sector_y: str,
    band: str,
    snapshot: dict,
    call_llm=default_call_llm,
) -> str:
    prompt = build_wavelet_prompt(sector_x, sector_y, band, snapshot)
    return call_llm(prompt).strip()
```

- [ ] **Step 4: テストを実行し、成功することを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/test_wavelet_explanation_prompt.py -v`
Expected: 全テストPASS。

- [ ] **Step 5: コミット**

```bash
cd ai-stock-investing-tutorial
git add app/prompt_patterns/wavelet_explanation.py app/tests/test_wavelet_explanation_prompt.py
git commit -m "$(cat <<'EOF'
Add prompt_patterns/wavelet_explanation for wavelet snapshot AI comments

Builds a single-pair, single-band explanation prompt from a
summarize_band_snapshot() result, following the same
facts-computed-in-python / LLM-interprets-only pattern as
prompt_patterns/sector_rotation.py.
EOF
)"
```

---

### Task 3: `app.py` — 要約パネルとAI解説コメントUIの追加

**Files:**
- Modify: `ai-stock-investing-tutorial/app/app.py`

**Interfaces:**
- Consumes:
  - Task 1: `sector_analysis.wavelet.summarize_band_snapshot(band_df) -> dict | None`
  - Task 2: `prompt_patterns.wavelet_explanation.generate_wavelet_explanation(sector_x, sector_y, band, snapshot, call_llm) -> str`
  - 既存: `common.cache.read_cache(cache_dir, key) -> str | None`, `common.cache.write_cache(cache_dir, key, content) -> None`, `data_api.llm_client.call_llm`（すでに `app.py` にインポート済み）
- Produces: UI変更のみ（他タスクから消費されるインターフェースなし）

- [ ] **Step 1: importを追加する**

`app.py` の既存インポートブロックを編集する。

`app.py:45` の直後（`from prompt_patterns.sector_rotation import generate_sector_rotation_comments` の次）に1行追加:

```python
from prompt_patterns.sector_rotation import generate_sector_rotation_comments
from prompt_patterns.wavelet_explanation import generate_wavelet_explanation
from screening.sectors import SECTOR_MAP
```

`app.py:49-54` の `from sector_analysis.wavelet import (...)` を以下に置き換える:

```python
from sector_analysis.wavelet import (
    compute_cross_wavelet_lead_lag,
    compute_dominant_lag_series,
    deserialize_sector_returns,
    serialize_sector_returns,
    summarize_band_snapshot,
)
```

- [ ] **Step 2: 既存の回帰テストを実行し、importエラーがないことを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/ -v`
Expected: 全テストPASS（`app.py`自体はテスト対象外だが、モジュールとして構文・import解決に問題がないことを次のステップの手動起動で確認するため、ここでは既存テストの回帰がないことのみ確認する）。

- [ ] **Step 3: 要約パネルとAIコメントUIを追加する**

`app.py` の以下の既存コード（ウェーブレット分析セクションの「支配的ラグ」折れ線グラフ部分、`compute_dominant_lag_series`呼び出しを含む`else`ブロック）を探す:

```python
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

これを以下に置き換える（末尾に要約パネルとAI解説コメントUIを追加、インデントは20スペース＝既存の`dominant = ...`行と同じ深さに揃える）:

```python
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

                    # 直近シグナルの要約パネル（機械的な数値表示、AI不使用）。
                    # 周期帯セレクトボックスの変更ごとに自動的に追従する。
                    snapshot = summarize_band_snapshot(band_df)
                    if snapshot is not None:
                        snap_lag = snapshot["dominant_lag_days"]
                        snap_leading = sector_x if snap_lag >= 0 else sector_y
                        snap_lagging = sector_y if snap_lag >= 0 else sector_x

                        col_lag, col_coherence = st.columns(2)
                        col_lag.metric("支配的ラグ（日）", f"{snap_lag:+.1f}")
                        col_coherence.metric("コヒーレンス", f"{snapshot['avg_coherence']:.2f}")
                        st.caption(
                            f"直近（{snapshot['date'].strftime('%Y-%m-%d')}）時点: "
                            f"{snap_leading} が {snap_lagging} に約{abs(snap_lag):.1f}営業日先行"
                            f"（コヒーレンス {snapshot['avg_coherence']:.2f}）"
                        )

                        # AI解説コメント（明示的ボタン起動、日次ファイルキャッシュ）。
                        # 表示中のペア・周期帯と異なる古いコメントを残さないよう、
                        # session_stateには生成時のキーも一緒に保持し、一致時のみ表示する。
                        wavelet_comment_key = (sector_x, sector_y, sector_period, band)
                        wavelet_comment_force_regenerate = st.checkbox(
                            "AI解説のキャッシュを無視して再生成する",
                            key="wavelet_comment_force_regenerate",
                        )
                        if st.button("AI解説を生成", key="wavelet_comment_button"):
                            comment_cache_key = "wavelet-comment-" + hashlib.sha256(
                                "-".join(str(part) for part in wavelet_comment_key).encode(
                                    "utf-8"
                                )
                            ).hexdigest()[:12]
                            cached_comment = (
                                None
                                if wavelet_comment_force_regenerate
                                else read_cache(CACHE_DIR, comment_cache_key)
                            )
                            if cached_comment is not None:
                                wavelet_comment_text = cached_comment
                            else:
                                wavelet_comment_text = generate_wavelet_explanation(
                                    sector_x, sector_y, band, snapshot, call_llm=call_llm
                                )
                                write_cache(CACHE_DIR, comment_cache_key, wavelet_comment_text)
                            st.session_state["wavelet_comment"] = {
                                "key": wavelet_comment_key,
                                "text": wavelet_comment_text,
                            }

                        cached_state = st.session_state.get("wavelet_comment")
                        if cached_state is not None and cached_state["key"] == wavelet_comment_key:
                            st.markdown(cached_state["text"])
```

- [ ] **Step 4: アプリを起動して手動確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run python -m streamlit run app.py`

ブラウザで以下を確認する:
1. 「セクターローテーション」タブを開き、取得期間を選んで「分析を実行」を押す
2. 「ウェーブレット分析（時間変化するリード・ラグ）」セクションで業種A・業種Bを選び、「ウェーブレット分析を実行」を押す
3. ヒートマップと支配的ラグの折れ線グラフの下に、「支配的ラグ（日）」「コヒーレンス」の2つのメトリクスと、直近シグナルの説明キャプションが表示されることを確認する
4. 周期帯セレクトボックス（短期/中期/長期）を切り替えると、要約パネルの数値が自動的に更新されることを確認する
5. 「AI解説を生成」を押すと、コメントが表示されることを確認する
6. 業種A・業種Bまたは周期帯を切り替えると、直前のAIコメントが消えることを確認する（表示され続けない）
7. 同じ組み合わせで再度「AI解説を生成」を押すと、（同日中は）キャッシュから即座に同じ文言が返ることを確認する
8. 「AI解説のキャッシュを無視して再生成する」にチェックを入れて再度押すと、LLMが再度呼び出されることを確認する（文言が変わりうる）

問題があれば実装を修正し、再度確認する。

- [ ] **Step 5: 全体テストスイートを実行する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/ -v`
Expected: 全テストPASS（回帰なし）。

- [ ] **Step 6: コミット**

```bash
cd ai-stock-investing-tutorial
git add app/app.py
git commit -m "$(cat <<'EOF'
Add latest-signal summary panel and AI comment to wavelet analysis UI

Surfaces summarize_band_snapshot() as a metrics panel under the
dominant-lag chart, plus an on-demand, cached AI explanation comment
scoped to the currently selected sector pair and period band so a
stale comment never lingers after switching selections.
EOF
)"
```

---

## Self-Review Notes

- **Spec coverage:** データ層（`avg_coherence` + `summarize_band_snapshot`）→ Task 1。プロンプト層（`wavelet_explanation.py`）→ Task 2。UI層（要約パネル・AIコメントボタン・キャッシュ・古いコメントのガード）→ Task 3。テスト方針の3ファイルすべてTask 1・2でカバー。UIの手動確認手順もTask 3 Step 4でカバー。
- **プレースホルダー確認:** 各ステップに実コードを記載済み。「後で実装」「適切なエラーハンドリングを追加」等の曖昧な指示なし。
- **型・シグネチャの一貫性:** `summarize_band_snapshot` の戻り値キー（`date`/`dominant_lag_days`/`avg_coherence`）はTask 1・2・3で一致。`build_wavelet_prompt` / `generate_wavelet_explanation` の引数順（`sector_x, sector_y, band, snapshot, call_llm`）もTask 2・3で一致。
