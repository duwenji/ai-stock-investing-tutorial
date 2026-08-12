"""セクタータブ: 相関上位ペアに対するAIコメントの表示。"""

import streamlit as st


def render_ai_comments(pairs: list[dict], comments: dict) -> None:
    """相関上位5ペアについて、過去データ上の傾向をAIが解説したコメントを表示する。"""
    # st.subheader()のhelp引数を指定すると見出しの横に(?)アイコンが付き、
    # ホバーすると補足説明がツールチップで表示される
    st.subheader(
        "相関上位5ペアのAIコメント",
        help=(
            "上記の上位5ペアについて、過去データ上の傾向をAIが解説した"
            "ものです。売買の推奨ではありません。"
        ),
    )
    for pair in pairs[:5]:
        key = f"{pair['leading_sector']}->{pair['lagging_sector']}"
        # st.write()はMarkdown記法（**太字**など）を解釈して整形表示する汎用の表示関数
        st.write(
            f"**{pair['leading_sector']} → {pair['lagging_sector']}**: "
            f"{comments.get(key, 'コメント生成失敗')}"
        )
