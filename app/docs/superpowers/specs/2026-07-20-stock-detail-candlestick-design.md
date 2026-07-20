# 銘柄詳細ダイアログ ローソク足・出来高表示 設計書

## 概要・目的

[2026-07-20-stock-detail-dialog-design.md](2026-07-20-stock-detail-dialog-design.md) で実装した銘柄詳細ダイアログの株価チャートは、終値のみの単純な折れ線グラフ（`st.line_chart`）だった。値動きの実態（始値・高値・安値・終値）と売買の勢いが読み取れないため、ローソク足チャートと出来高チャートに置き換える。

## スコープ

- v1で実装する:
  - `stock_detail/detail.py` の `price_history` を、終値のみから始値・高値・安値・終値・出来高（OHLCV）を含む形に拡張する
  - `app.py` の `show_stock_detail_dialog` で、既存の折れ線グラフをローソク足チャートに置き換え、その下に出来高の棒グラフを追加する
- v1で実装しない（将来課題）:
  - 期間切り替え（現状固定の6ヶ月間のまま）
  - 移動平均線のチャートへの重ね描画

## 技術選定

チャート描画にはAltair（Streamlitが内部依存として既にインストール済み、`pyproject.toml`への新規依存追加不要）を使う。`mark_rule`（高値・安値のヒゲ）と`mark_bar`（始値・終値の実体）を陽線＝緑・陰線＝赤で色分けして重ね合わせ、ローソク足を自前構築する。出来高は同じ日付軸を共有する別の`mark_bar`チャートとして下に並べる。Plotly（`go.Candlestick`）は完成度の高いローソク足を宣言的に書けるが新規依存追加が必要なため、既存依存のみで完結するAltairを採用する。

## コアロジック — `stock_detail/detail.py`

### `generate_stock_detail` の `price_history` 形式変更

現状:
```python
{"dates": list[str], "close": list[float]}
```

変更後:
```python
{
    "dates": list[str],
    "open": list[float],
    "high": list[float],
    "low": list[float],
    "close": list[float],
    "volume": list[float],
}
```

データが空の場合は全キーが空リスト。日次キャッシュ（`stock-detail-{ticker}`）は既存の仕組みのまま日付が変わると自然に入れ替わるため、旧形式キャッシュの移行処理は不要（当日中に旧形式のキャッシュが残っていた場合、ダイアログ側で`KeyError`にならないよう、新形式のキー（`open`/`high`/`low`/`volume`）に対しては`.get(...)`ではなく通常の辞書アクセスのままとする — 当日分のキャッシュは本改修のデプロイと同時に更新されるため実運用上は旧形式が残らない）。

## UI設計 — `app.py`

### `show_stock_detail_dialog` のチャート部分を置き換える

現状の該当部分:
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

変更後:
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

`app.py` の先頭に `import altair as alt` を追加する。

## エラーハンドリング

既存方針を踏襲: `price_history["dates"]` が空の場合は従来通り「株価データを取得できませんでした。」を表示し、チャート部分のみスキップする。

## テスト方針

- `tests/test_stock_detail.py`: 既存テスト（`test_generate_stock_detail_builds_payload_from_dependencies`、`test_generate_stock_detail_handles_empty_price_history`、`test_generate_stock_detail_uses_cache_and_skips_dependency_calls`）のフェイク `fetch_price_history` を `Open`/`High`/`Low`/`Close`/`Volume` を含む `DataFrame` に更新し、期待する `price_history` の形をOHLCV形式に更新する
- `app.py` のチャート描画部分は既存方針通り自動テスト対象外。`uv run python -m streamlit run app.py` を起動し、銘柄詳細ダイアログでローソク足と出来高が正しく表示されること（陽線・陰線の色分け含む）を手動確認する

## v1スコープ外（将来課題）

- 期間切り替えUI
- 移動平均線の重ね描画
