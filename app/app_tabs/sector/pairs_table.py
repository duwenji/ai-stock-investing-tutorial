"""セクタータブ: リード・ラグ上位ペアの一覧表示。"""

import pandas as pd
import streamlit as st


def render_pairs_table(pairs: list[dict]) -> None:
    """相関が強い順に、どちらの業種が何営業日先行して動く傾向があったかを一覧表示する。"""
    # help=でsubheaderの横に(?)アイコンを表示し、ホバーで補足説明を出す
    st.subheader(
        "リード・ラグ上位ペア",
        help=(
            "相関が強い順に、どちらの業種が何営業日先行して動く傾向が"
            "あったかを一覧表示します。"
        ),
    )
    pairs_df = pd.DataFrame(pairs)[
        ["leading_sector", "lagging_sector", "lag_days", "correlation"]
    ]
    # st.dataframe()はDataFrameをソート・スクロール可能な表として表示する。
    # column_configで列ごとの表示名や型（テキスト/数値）を指定でき、
    # hide_index=Trueでpandas標準の連番インデックス列を非表示にする
    st.dataframe(
        pairs_df,
        column_config={
            "leading_sector": st.column_config.TextColumn("先行業種"),
            "lagging_sector": st.column_config.TextColumn("追随業種"),
            "lag_days": st.column_config.NumberColumn("ラグ（営業日）"),
            "correlation": st.column_config.NumberColumn("相関係数"),
        },
        hide_index=True,
    )

    # st.expander()は折りたたみ可能なセクションを作る。初期状態は閉じており、
    # クリックすると開いて中の部品（ここではst.markdown）が表示される
    with st.expander("リード・ラグの読み方"):
        st.markdown(
            "「先行業種」の値動きに、「追随業種」が「ラグ（営業日）」で"
            "示した日数だけ遅れて追随する傾向が、指定した期間の株価データ"
            "から確認されたことを示します。\n\n"
            "例えば「先行業種: 建設・資材、追随業種: 機械、ラグ: 0日、"
            "相関係数: 0.87」であれば、建設・資材セクターの値動きと"
            "機械セクターの値動きが、同じ営業日にほぼ同じ方向へ動く傾向が"
            "強かったことを意味します。\n\n"
            "**注意:** 上位ペアの多くはラグ0日（同時相関）になりやすい"
            "傾向があります。これは業種固有の先行・追随関係というより、"
            "市場全体の地合い（同じ日に多くの業種が一緒に動く傾向）を"
            "反映している可能性があります。特定の周期の長さ"
            "（短期・中期・長期）ごとに、より業種固有の先行・追随関係を"
            "確認したい場合は、下部の「ウェーブレット分析」もあわせて"
            "ご覧ください。"
        )
