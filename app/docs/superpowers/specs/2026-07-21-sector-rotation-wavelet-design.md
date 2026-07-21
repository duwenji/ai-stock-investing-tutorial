# セクターローテーション ウェーブレット分析 設計書

## 概要・目的

[セクターローテーション分析](2026-07-20-sector-rotation-design.md)の実装後の手動確認で、既存のリード・ラグ計算（`sector_analysis/correlation.py`の`compute_lead_lag_pairs`、全期間固定の時差相関）には次の課題があることが判明した: 相関上位ペアがラグ0日（同時相関 = 市場全体の地合い）に偏り、業種固有の先行・追随シグナルが埋もれてしまう。

本機能では、連続ウェーブレット変換（CWT）に基づくクロスウェーブレット・コヒーレンスと位相差を用いて、業種ペアの値動きの関係を「時間 × サイクルの長さ（周期）」の2次元で分解する。これにより、市場全体の地合いのような短期の同時性と、業種固有のより長い周期を持つ先行・追随関係を区別し、かつ「いつ、どちらの業種が先行していたか」の時間変化を可視化する。

既存タブと同じ設計方針を踏襲する: 事実データの計算はPython側で行い、その解釈はUI上の数値・図として提示する（本機能はAIコメントを新設しない）。売買の推奨・指示は行わない（[DISCLAIMER.md](../../../../DISCLAIMER.md)準拠）。

既存の[相関上位ペア一覧・AIコメント](2026-07-20-sector-rotation-design.md)は変更しない。本機能はセクターローテーションタブに追加する、オンデマンドのドリルダウンセクションである。

## スコープ

- v1で実装する:
  - `sector_analysis/wavelet.py`: 2業種の日次リターン系列から、時間×周期ごとのクロスウェーブレット・コヒーレンスと符号付きラグを計算する`compute_cross_wavelet_lead_lag`
  - `app.py`: セクターローテーションタブに「ウェーブレット分析（時間変化するリード・ラグ）」セクションを追加（業種ペア選択・コヒーレンス/ラグのヒートマップ・周期帯選択・支配的ラグの時系列折れ線グラフ）
  - 既存の`sector-rotation-*`キャッシュpayloadに`sector_returns`（業種別リターン系列）を追加し、ドリルダウン時の再取得を不要にする
  - 新規依存: `pywt`（PyWavelets）をpyproject.tomlに追加
- v1で実装しない（将来課題）:
  - モンテカルロ法によるコヒーレンスの統計的有意性検定（`pycwt`にあるような検定）
  - スケール軸方向の平滑化（時間軸方向の平滑化のみ実装する簡略版）
  - 136業種ペア全体を一括でウェーブレット計算する機能（本機能は選択した2業種のみのオンデマンド計算）
  - ウェーブレット分析結果に基づくAIコメント生成

## コアロジック — `sector_analysis/wavelet.py`（新設）

### 期間バンド定数

```python
PERIOD_BANDS: dict[str, tuple[float, float]] = {
    "短期": (4.0, 10.0),
    "中期": (10.0, 40.0),
    "長期": (40.0, 120.0),
}
```

- 単位は営業日。短期は1〜2週間程度、中期は1〜2ヶ月程度、長期は2〜6ヶ月程度のサイクルに相当する

### `compute_cross_wavelet_lead_lag`

```python
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

    series_x, series_yは日付インデックスを共通に持つ日次リターン系列（欠損可）。
    共通の非欠損データ数がmax_period_days * 2未満の場合は空のDataFrameを返す。
    """
```

処理内容:
1. `series_x`, `series_y`を共通の日付インデックスに揃え、欠損値を除去する（`pd.concat([...], axis=1).dropna()`）
2. データ数が`max_period_days * 2`未満なら空のDataFrame（列だけを持つ）を返す
3. `min_period_days`から`max_period_days`まで、1オクターブあたり`voices_per_octave`個のスケールを対数間隔で生成し、`pywt.scale2frequency("cmor1.5-1.0", scales)`の逆数からスケールごとの周期（営業日）を求める
4. `pywt.cwt`で複素モルレーウェーブレット（`cmor1.5-1.0`）により`Wx`, `Wy`（複素数、shape = (スケール数, 時点数)）を計算する
5. クロスウェーブレット`Wxy = Wx * np.conj(Wy)`を計算する
6. 時間軸方向にスケール依存の窓幅（そのスケールの周期に比例、boxcarフィルタ、numpyの累積和で自前実装。scipy等の新規依存は追加しない）で`Wx * conj(Wx)`, `Wy * conj(Wy)`, `Wxy`をそれぞれ平滑化する
7. コヒーレンス = `|smooth(Wxy)|^2 / (smooth(|Wx|^2) * smooth(|Wy|^2))`を計算し、`[0, 1]`にクリップする（数値誤差対策）
8. 位相差 = `np.angle(smooth(Wxy))`から、スケールごとの周期を使い`lag_days = phase / (2 * np.pi) * period_days`を計算する
   - `lag_days > 0`: `sector_x_name`が先行し`sector_y_name`が`lag_days`営業日遅れて追随
   - `lag_days < 0`: `sector_y_name`が先行し`sector_x_name`が`abs(lag_days)`営業日遅れて追随
   - `leading_sector`列にどちらの業種名が先行しているかを文字列で記録する
9. 各スケールの周期を`PERIOD_BANDS`に基づき`band`列（短期/中期/長期、範囲外は除外）に分類する
10. tidy long-form DataFrameとして返す。列: `date`, `period_days`, `band`, `coherence`, `lag_days`, `leading_sector`

### 依存関係

- `pyproject.toml`の`dependencies`に`"pywt>=1.9.0"`を追加する（PyPI配布名は`pywavelets`だがインポート名は`pywt`。`uv add pywavelets`で追加する）
- `numpy`, `pandas`は既存の間接依存（streamlit経由）をそのまま利用する。scipy等の追加依存はしない

## UI設計 — `app.py`

既存の「相関上位5ペアのAIコメント」セクションの直後、`DISCLAIMER_NOTICE`表示の前に新セクションを追加する。

```python
st.subheader("ウェーブレット分析（時間変化するリード・ラグ）")
st.caption(
    "選択した2つの業種について、値動きの周期の長さ（短期・中期・長期）ごとに、"
    "どちらの業種がどれくらい先行しているかの時間変化を可視化します。"
    "色が薄い部分は関係の確からしさ（コヒーレンス）が低いことを示します。"
)

sector_options = sorted(payload["sector_returns"].keys())
default_x = pairs[0]["leading_sector"] if pairs else sector_options[0]
default_y = pairs[0]["lagging_sector"] if pairs else sector_options[1]

col_a, col_b = st.columns(2)
with col_a:
    sector_x = st.selectbox("業種A", sector_options, index=sector_options.index(default_x))
with col_b:
    sector_y = st.selectbox("業種B", sector_options, index=sector_options.index(default_y))

if st.button("ウェーブレット分析を実行"):
    series_x = _series_from_payload(payload["sector_returns"][sector_x])
    series_y = _series_from_payload(payload["sector_returns"][sector_y])
    try:
        wavelet_df = compute_cross_wavelet_lead_lag(series_x, series_y, sector_x, sector_y)
    except Exception:
        st.error("ウェーブレット分析の計算に失敗しました。")
        wavelet_df = pd.DataFrame()

    if wavelet_df.empty:
        st.warning("選択した2業種の共通データが不足しているため、分析できませんでした。")
    else:
        st.session_state["wavelet_result"] = {"df": wavelet_df, "x": sector_x, "y": sector_y}

if st.session_state.get("wavelet_result") is not None:
    result = st.session_state["wavelet_result"]
    wavelet_df = result["df"]

    heatmap = (
        alt.Chart(wavelet_df)
        .mark_rect()
        .encode(
            x=alt.X("date:T", title=None),
            y=alt.Y("period_days:O", title="周期（営業日）", sort="descending"),
            color=alt.Color(
                "lag_days:Q",
                title="ラグ（正=業種Aが先行）",
                scale=alt.Scale(scheme="redblue", domainMid=0),
            ),
            opacity=alt.Opacity("coherence:Q", scale=alt.Scale(domain=[0, 1], range=[0.05, 1])),
            tooltip=["date:T", "period_days:Q", "band:N", "coherence:Q", "lag_days:Q", "leading_sector:N"],
        )
        .properties(height=400)
    )
    st.altair_chart(heatmap, width="stretch")

    band = st.selectbox("周期帯", ["短期", "中期", "長期"], index=1, key="wavelet_band")
    band_df = wavelet_df[wavelet_df["band"] == band]
    if not band_df.empty:
        weighted = (
            band_df.groupby("date")
            .apply(lambda g: (g["lag_days"] * g["coherence"]).sum() / g["coherence"].sum())
            .reset_index(name="dominant_lag_days")
        )
        line = (
            alt.Chart(weighted)
            .mark_line()
            .encode(x=alt.X("date:T", title=None), y=alt.Y("dominant_lag_days:Q", title="支配的ラグ（日）"))
            .properties(height=250)
        )
        st.altair_chart(line, width="stretch")
```

- `_series_from_payload`はキャッシュpayloadの`{"dates": [...], "values": [...]}`形式から`pd.Series`（`DatetimeIndex`付き）を復元するヘルパー関数（同じく`app.py`または`sector_analysis/wavelet.py`に追加）
- 業種選択のデフォルト値は既存の相関上位1ペアの先行・追随業種とする
- ウェーブレット計算はボタン押下毎に実行し、キャッシュしない（選択2業種のみの軽量計算のため）

## データ変更 — キャッシュpayloadへの`sector_returns`追加

既存の`sector-rotation-*`キャッシュpayloadは`pairs`, `skipped_tickers`, `excluded_sectors`, `comments`のみを保持しており、業種別リターン系列自体は保存していない。ドリルダウンで系列を都度228銘柄再取得することを避けるため、payloadに以下を追加する:

```python
payload["sector_returns"] = {
    sector: {
        "dates": [d.isoformat() for d in series.index],
        "values": [None if pd.isna(v) else v for v in series],
    }
    for sector, series in sector_returns.items()
}
```

### 既存キャッシュとの互換性

既存のキャッシュファイル（`sector_returns`キーを持たない）を読み込んだ場合、ウェーブレット分析セクションが動作しない。キャッシュ読み込み時に`"sector_returns" not in payload`であればキャッシュヒットとして扱わず、キャッシュミスと同様に再計算するように変更する（1回限りの透過的なスキーマ移行）。

```python
cached_payload = None if sector_force_regenerate else read_cache(CACHE_DIR, cache_key)
payload = json.loads(cached_payload) if cached_payload is not None else None
if payload is not None and "sector_returns" not in payload:
    payload = None  # 旧スキーマのキャッシュは再計算して移行する
```

## エラーハンドリング

| 事象 | 挙動 |
| --- | --- |
| 選択2業種の共通非欠損データ数が`max_period_days * 2`未満 | `compute_cross_wavelet_lead_lag`が空のDataFrameを返し、UIに警告表示、計算スキップ |
| ウェーブレット計算中の例外 | catchしてエラーメッセージ表示、他のセクション（相関ヒートマップ等）の表示には影響しない |
| 旧スキーマのキャッシュ（`sector_returns`なし） | キャッシュミス扱いとして再計算（上記参照） |

## テスト方針

- `tests/test_sector_wavelet.py`:
  - 既知の周期（例: 周期20日の正弦波）を持つ系列ペアで、一方を既知の日数だけシフトして作成し、対応する周期帯（中期）における支配的ラグ・`leading_sector`の向きが期待通り検出されることを検証
  - `coherence`列の値がすべて`[0, 1]`の範囲に収まることを検証
  - 完全に無相関なホワイトノイズ系列ペアでは、コヒーレンスが全般に低い値に留まることを検証（閾値による目安チェック、統計的検定はしない）
  - データ不足（系列長が`max_period_days * 2`未満）の場合に空のDataFrameが返ることを検証
  - `PERIOD_BANDS`に基づく`band`列の分類が正しいことを検証
- UI（ヒートマップ描画・ドリルダウン操作）は既存方針通り自動テスト対象外。`uv run python -m streamlit run app.py`で手動確認する

## v1スコープ外（将来課題）

- モンテカルロ法によるコヒーレンスの統計的有意性検定
- スケール軸方向の平滑化
- 136業種ペア全体の一括ウェーブレット計算・ランキングへの統合
- ウェーブレット分析結果に基づくAIコメント生成
