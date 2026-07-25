# ウェーブレット分析 直近シグナル要約＋AI解説コメント 設計書

## 概要・目的

[セクターローテーション ウェーブレット分析](2026-07-21-sector-rotation-wavelet-design.md)は、業種ペアの時間×周期ごとのリード・ラグをヒートマップと支配的ラグの折れ線グラフで可視化するところまでを実装済みである。しかし、グラフを読み取って「結局いま何が起きているか」を判断するのはユーザー任せになっており、他のタブ（相関上位ペア、バックテスト、一括バックテスト等）が備える「数値の要約」「AIによる解説」に相当するものがない。

本機能は、既存のウェーブレット計算結果（`compute_cross_wavelet_lead_lag` / `compute_dominant_lag_series`）を土台に、(a) 選択中の周期帯における直近シグナルを機械的に要約するパネルと、(b) その要約をLLMに解釈させる解説コメントを追加し、「ウェーブレット分析の活用方法」を画面上で完結させる。

既存の相関ヒートマップ・リード/ラグ表・上位5ペアAIコメント・ウェーブレットのヒートマップ/折れ線グラフは変更しない。本機能はウェーブレット分析セクションの末尾（折れ線グラフの直後）に追加する。

## スコープ

- v1で実装する:
  - `sector_analysis/wavelet.py`: `compute_dominant_lag_series` に `avg_coherence`（バンド内の周期方向の単純平均コヒーレンス）列を追加し、新規関数 `summarize_band_snapshot` を追加
  - `prompt_patterns/wavelet_explanation.py`（新設）: `build_wavelet_prompt` / `generate_wavelet_explanation`
  - `app.py`: ウェーブレット分析セクションに直近シグナル要約パネル（自動表示）とAI解説コメント（ボタン起動・日次ファイルキャッシュ）を追加
- v1で実装しない（将来課題）:
  - 複数バンド（短期・中期・長期）を横断した総合コメントの生成（v1は選択中の1バンドのみ）
  - 過去の方向一貫性（例: 過去N日のうち何%が同じ向きだったか）などの追加統計量
  - ウェーブレット分析結果に基づくスクリーニング・ランキングへの統合

## データ層 — `sector_analysis/wavelet.py`

### `compute_dominant_lag_series` の拡張

既存の戻り値カラム `date`, `dominant_lag_days` に加えて `avg_coherence` を追加する。

```python
def compute_dominant_lag_series(band_df: pd.DataFrame) -> pd.DataFrame:
    """(既存docstringに追記)
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
```

既存の呼び出し元（`app.py`の折れ線グラフ描画）は`dominant_lag_days`列のみ参照しているため、列追加による破壊的変更はない。

### 新規関数 `summarize_band_snapshot`

```python
def summarize_band_snapshot(band_df: pd.DataFrame) -> dict | None:
    """特定周期帯のDataFrameから、直近日付における支配的ラグとバンド平均
    コヒーレンスのスナップショットを返す。有効なデータがなければNoneを返す。

    戻り値: {"date": pd.Timestamp, "dominant_lag_days": float, "avg_coherence": float}
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

この関数の戻り値が、要約パネル表示とAIコメント生成プロンプトの共通入力になる（表示内容とAIコメントの数値的な根拠が一致することを保証する）。

## プロンプト層 — `prompt_patterns/wavelet_explanation.py`（新設）

既存の`sector_rotation.py`と同じ構成方針（事実データはPython側で計算済み、LLMは解釈のみ）を踏襲する。他のバッチ処理コメント関数と異なり、単一ペア・単一バンドの1回呼び出しのためJSON出力は要求せず、プレーンテキストをそのまま返す。

```python
from data_api.llm_client import call_llm as default_call_llm


def build_wavelet_prompt(
    sector_x: str, sector_y: str, band: str, snapshot: dict
) -> str:
    """2業種・1周期帯のウェーブレット分析スナップショットから、解説コメント生成用の
    プロンプトを組み立てる。
    """
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

JSONパースが不要なため、他のコメント生成関数と違いパース失敗時のフォールバック分岐は発生しない（`call_llm`自体が失敗した場合は呼び出し元の`ClaudeCLIError`が伝播する）。

## UI層 — `app.py`

既存の「支配的ラグ」折れ線グラフ（`band_df`を使う`if`ブロックの内側、`band_df.empty`でない場合）の直後に追加する。

### ① 直近シグナル要約パネル（自動表示）

```python
snapshot = summarize_band_snapshot(band_df)
if snapshot is not None:
    lag = snapshot["dominant_lag_days"]
    leading = wavelet_result["x"] if lag >= 0 else wavelet_result["y"]
    lagging = wavelet_result["y"] if lag >= 0 else wavelet_result["x"]

    col_lag, col_coherence = st.columns(2)
    col_lag.metric("支配的ラグ（日）", f"{lag:+.1f}")
    col_coherence.metric("コヒーレンス", f"{snapshot['avg_coherence']:.2f}")
    st.caption(
        f"直近（{snapshot['date'].strftime('%Y-%m-%d')}）時点: "
        f"{leading} が {lagging} に約{abs(lag):.1f}営業日先行"
        f"（コヒーレンス {snapshot['avg_coherence']:.2f}）"
    )
```

- 周期帯セレクトボックス（`wavelet_band`）を変更するたびにStreamlitが再実行され、`band_df`も再計算されるため、要約パネルは自動的に追従する（ボタン不要）
- `dominant_lag_days`の符号は既存ヒートマップの凡例（正=業種Aが先行）と統一する

### ② AI解説コメント（ボタン起動・日次キャッシュ）

```python
wavelet_comment_key = (wavelet_result["x"], wavelet_result["y"], sector_period, band)

wavelet_comment_force_regenerate = st.checkbox(
    "AI解説のキャッシュを無視して再生成する", key="wavelet_comment_force_regenerate"
)
if snapshot is not None and st.button("AI解説を生成", key="wavelet_comment_button"):
    comment_cache_key = "wavelet-comment-" + hashlib.sha256(
        "-".join(str(part) for part in wavelet_comment_key).encode("utf-8")
    ).hexdigest()[:12]
    cached_comment = (
        None if wavelet_comment_force_regenerate else read_cache(CACHE_DIR, comment_cache_key)
    )
    if cached_comment is not None:
        comment = cached_comment
    else:
        comment = generate_wavelet_explanation(
            wavelet_result["x"], wavelet_result["y"], band, snapshot, call_llm=call_llm
        )
        write_cache(CACHE_DIR, comment_cache_key, comment)
    st.session_state["wavelet_comment"] = {"key": wavelet_comment_key, "text": comment}

cached_state = st.session_state.get("wavelet_comment")
if cached_state is not None and cached_state["key"] == wavelet_comment_key:
    st.markdown(cached_state["text"])
```

- キャッシュキーは業種ペア・取得期間・周期帯のみに依存する（他タブと同じ日次ファイルキャッシュ方式。日付が変われば自動的に再生成対象になる）
- **表示中のペア・周期帯と一致する場合のみ**AIコメントを表示する（`cached_state["key"] == wavelet_comment_key`のガード）。業種ペアや周期帯を切り替えると、再度「AI解説を生成」を押すまでコメント欄は非表示に戻る。ボタン押下ごとにLLM呼び出しコストが発生する「明示的アクションのみ実行」方針を維持しつつ、切替後に古い選択に対するコメントが誤って表示され続ける状態を防ぐ
- 個別の免責文は追加せず、タブ末尾の`DISCLAIMER_NOTICE`表示に委ねる（既存の「相関上位5ペアのAIコメント」等と同じ扱い）
- `import hashlib`は既に`app.py`冒頭でインポート済み

## エラーハンドリング

| 事象 | 挙動 |
| --- | --- |
| 選択中バンドの`band_df`が空（既存の「この周期帯には有効なデータがありませんでした」分岐） | `summarize_band_snapshot`は呼ばれず、要約パネル・AI解説ボタンとも表示しない |
| `generate_wavelet_explanation`（`call_llm`）が例外を送出 | 既存の`call_llm`呼び出しパターンと同様、例外は捕捉せず伝播させる（Streamlitがエラー表示。他の単発AI呼び出し箇所と同じ扱いで、本機能のみ特別扱いしない） |

## テスト方針

- `tests/test_sector_wavelet.py` に追加:
  - `compute_dominant_lag_series`が`avg_coherence`列を含み、値が`[0, 1]`の範囲であることを検証
  - `summarize_band_snapshot`が最新日付のスナップショットを正しく返すことを検証（既知の`lag_days`・`coherence`を持つ簡単な`band_df`で検証）
  - `summarize_band_snapshot`が空の`band_df`に対して`None`を返すことを検証
- `tests/test_wavelet_explanation_prompt.py`（新設、`test_sector_rotation_prompt.py`と同構成）:
  - `build_wavelet_prompt`が業種名・周期帯・日付・ラグ・コヒーレンスの値をプロンプトに含み、「過去」「将来」「売買」といった禁止表現の説明を含むことを検証
  - `generate_wavelet_explanation`がモック化した`call_llm`の戻り値をそのまま（`strip()`済みで）返すことを検証
- UI（要約パネルの表示・AI解説ボタンの挙動）は既存方針通り自動テスト対象外。`uv run python -m streamlit run app.py`で手動確認する
