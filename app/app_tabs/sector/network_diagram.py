"""セクタータブ: 業種間ネットワーク（全ペア俯瞰）の描画。"""

import pandas as pd
import streamlit as st

from sector_analysis.network import build_mermaid_lead_lag_graph

from app_tabs.shared import render_mermaid


def render_network_diagram(network_pairs: list[dict], height: int) -> None:
    """全業種ペアの直近のウェーブレット分析結果を集約し、リード・ラグのネットワーク図として描画する。"""
    # help=でsubheaderの横に(?)アイコンを表示し、ホバーで補足説明を出す
    st.subheader(
        "業種間ネットワーク（全ペア俯瞰）",
        help=(
            "全業種ペアについて、直近20営業日のウェーブレット分析結果を集約し、"
            "周期の長さごとにどの業種が誰をリードしているかを俯瞰します。"
        ),
    )
    # st.caption()は補足説明用の小さめグレー文字を表示するStreamlit専用API
    st.caption(
        "コヒーレンス（関係の確からしさ）が閾値以上のペアのみを矢印で表示します。"
        "矢印の元が先行業種、矢印の先が追随業種です。"
    )

    network_df = pd.DataFrame(network_pairs)
    # st.columns(2)は横並びの2つのコンテナ（列）を作る。以降のwithブロックで
    # 各列に部品を配置すると、その部品はその列の幅の中だけに表示される
    col_band, col_threshold = st.columns(2)
    with col_band:
        # key=を指定するとウィジェットの選択状態がst.session_state["network_band"]に
        # 保存され、他のウィジェット操作でrerunが起きても選択内容が保持される
        network_band = st.selectbox(
            "周期帯", ["短期", "中期", "長期"], index=1, key="network_band"
        )
    with col_threshold:
        # スライダーの値もkey="network_threshold"でsession_stateに保持される。
        # 値を動かすたびに自動でrerunが走り、下のネットワーク図が再計算される
        network_threshold = st.slider(
            "コヒーレンス閾値（これ以上のペアのみ表示）",
            0.0,
            1.0,
            0.5,
            0.05,
            key="network_threshold",
        )

    # 選択した周期帯・閾値の条件に合う業種ペアだけを絞り込み、
    # Mermaid記法（矢印で先行→追随を表すflowchart）の文字列を組み立てる
    mermaid_code = build_mermaid_lead_lag_graph(
        network_df, network_band, network_threshold
    )
    if mermaid_code is None:
        st.info(
            "十分な確信度を持つ関係が見つかりませんでした。閾値を下げてみてください。"
        )
    else:
        # render_mermaidは本アプリ側で定義したヘルパー（app_tabs.shared）で、
        # Mermaid記法の文字列をブラウザ上で図として描画する
        render_mermaid(mermaid_code, height=height)
