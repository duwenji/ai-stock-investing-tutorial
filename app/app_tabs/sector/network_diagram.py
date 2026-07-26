"""セクタータブ: 業種間ネットワーク（全ペア俯瞰）の描画。"""

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from sector_analysis.network import build_mermaid_lead_lag_graph


def _render_mermaid(code: str, height: int = 400) -> None:
    """Mermaidコード文字列を、CDN経由のmermaid.js + svg-pan-zoom.jsを使って
    ドラッグパン・ホイールズーム可能なHTML埋め込みとして描画する。"""
    html = f"""
    <style>
      html, body {{ margin: 0; padding: 0; height: 100%; }}
      .mermaid {{ width: 100%; height: 100%; }}
      .mermaid svg {{
        width: 100% !important;
        height: 100% !important;
        max-width: none !important;
      }}
    </style>
    <div class="mermaid">{code}</div>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/svg-pan-zoom@3/dist/svg-pan-zoom.min.js"></script>
    <script>
      mermaid.initialize({{ startOnLoad: false }});
      mermaid.run({{ querySelector: ".mermaid" }}).then(function () {{
        var svgEl = document.querySelector(".mermaid svg");
        if (svgEl) {{
          var pz = svgPanZoom(svgEl, {{
            zoomEnabled: true,
            controlIconsEnabled: true,
            fit: false,
            center: true,
          }});
          // 業種間ネットワーク図はflowchart LRのため横に広がりやすく、
          // 単純なfit（縦横とも収まる最大倍率）だと幅で頭打ちになり、
          // 高さを増やしても余白が増えるだけになる。縦方向を優先して
          // 拡大しつつ、疎な（ノードが少ない）図で拡大しすぎないよう
          // 「全体表示時の倍率の2倍」を上限にする。はみ出した部分は
          // ドラッグ・ホイールで閲覧できる。
          var sizes = pz.getSizes();
          if (sizes.viewBox.height > 0 && sizes.viewBox.width > 0) {{
            var scaleToHeight = sizes.height / sizes.viewBox.height;
            var scaleToWidth = sizes.width / sizes.viewBox.width;
            pz.zoom(Math.min(scaleToHeight, scaleToWidth * 2));
            pz.center();
          }}
        }}
      }});
    </script>
    """
    components.html(html, height=height, scrolling=True)


def render_network_diagram(network_pairs: list[dict], height: int) -> None:
    """全業種ペアの直近のウェーブレット分析結果を集約し、リード・ラグのネットワーク図として描画する。"""
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

    network_df = pd.DataFrame(network_pairs)
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
        _render_mermaid(mermaid_code, height=height)
