"""セクタータブ: 業種間相関ヒートマップの描画。"""

import altair as alt
import pandas as pd
import streamlit as st


def render_heatmap(pairs: list[dict], height: int) -> None:
    """相関ペアの一覧から対称な相関行列（ヒートマップ用）を組み立てて描画する。"""
    sectors = sorted(
        {pair["leading_sector"] for pair in pairs}
        | {pair["lagging_sector"] for pair in pairs}
    )
    # 相関行列はA→BとB→Aで同じ値になる（対称行列）ため、対角成分を1.0で
    # 初期化した上で、各ペアの値を[a,b]と[b,a]の両方に書き込んで作る
    corr_matrix = pd.DataFrame(1.0, index=sectors, columns=sectors)
    for pair in pairs:
        a, b = pair["leading_sector"], pair["lagging_sector"]
        value = abs(pair["correlation"])
        corr_matrix.loc[a, b] = value
        corr_matrix.loc[b, a] = value

    # Altairのheatmapはlong形式を要求するため、行列をmeltして変換する
    heatmap_df = (
        corr_matrix.reset_index()
        .melt(id_vars="index", var_name="sector_b", value_name="correlation")
        .rename(columns={"index": "sector_a"})
    )

    # help=でsubheaderの横に(?)アイコンを表示し、ホバーで補足説明を出す
    st.subheader(
        "業種間相関ヒートマップ",
        help=(
            "17業種の組み合わせについて、最も強く連動するタイミング"
            "（リード・ラグ）における相関の強さを、色の濃さで示します。"
        ),
    )
    heatmap = (
        alt.Chart(heatmap_df)
        .mark_rect()
        .encode(
            x=alt.X("sector_a:N", title=None),
            y=alt.Y("sector_b:N", title=None),
            color=alt.Color(
                "correlation:Q", scale=alt.Scale(scheme="reds", domain=[0, 1])
            ),
            tooltip=["sector_a", "sector_b", "correlation"],
        )
        .properties(height=height)
        .interactive()
    )
    # st.altair_chart()はAltairのグラフオブジェクトをそのままブラウザに描画する
    # Streamlit専用API。width="stretch"は親コンテナの横幅いっぱいに広げる指定
    st.altair_chart(heatmap, width="stretch")
