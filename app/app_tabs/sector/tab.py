"""セクタータブ: セクターローテーション分析のエントリーポイント。
表示設定・分析実行（データ取得・キャッシュ）を担当し、個別グラフの描画は
app_tabs.sector 配下の各モジュールに委譲する。
"""

import logging

import pandas as pd
import streamlit as st

from common.disclaimer import DISCLAIMER_NOTICE
from sector_analysis.display_settings import (
    load_sector_display_settings,
    save_sector_display_settings,
)

from app_tabs.sector.ai_comments import render_ai_comments
from app_tabs.sector.heatmap import render_heatmap
from app_tabs.sector.network_diagram import render_network_diagram
from app_tabs.sector.pairs_table import render_pairs_table
from app_tabs.sector.wavelet_analysis import render_wavelet_analysis
from app_tabs.shared import get_current_user_id, run_or_load_sector_rotation

logger = logging.getLogger(__name__)


def render_sector_tab() -> None:
    logger.info("セクターローテーションタブを表示")
    # StreamlitはUI操作のたびにこのスクリプトを再実行（rerun）するため、
    # この関数もタブが表示されるたびに毎回最初から呼び直される
    st.header("セクターローテーション")
    st.caption(
        "UNIVERSE銘柄を17業種に分類し、業種間の値動きの時差相関（リード・ラグ）を"
        "過去の株価データから計算します。あくまで過去の統計的傾向であり、"
        "将来の値動きを保証するものではありません。"
    )

    display_settings = load_sector_display_settings(get_current_user_id())
    section_labels = {
        "heatmap": "業種間相関ヒートマップ",
        "pairs_table": "リード・ラグ上位ペア",
        "ai_comments": "相関上位5ペアのAIコメント",
        "network_diagram": "業種間ネットワーク（全ペア俯瞰）",
        "wavelet_analysis": "ウェーブレット分析",
    }
    # st.expander()は折りたたみ可能なセクションを作る。表示設定という
    # 頻繁には使わない機能を初期状態で隠しておき、画面をすっきりさせるために使う
    with st.expander("表示設定"):
        st.caption(
            "表示のON/OFFと並び順を指定できます"
            "（設定は次回起動時も保持されます）。"
        )
        editor_df = pd.DataFrame(
            [
                {
                    "key": key,
                    "セクション": label,
                    "表示": display_settings["visible"][key],
                    "順序": display_settings["order"][key],
                }
                for key, label in section_labels.items()
            ]
        )
        # st.data_editor()はDataFrameをそのまま編集可能な表として表示するウィジェット。
        # 戻り値は編集後のDataFrame。column_configで列ごとの表示方法を指定でき、
        # "key": Noneのように値をNoneにすると列自体が非表示になり、
        # TextColumn(disabled=True)は列を表示したまま編集だけ不可にする
        edited_df = st.data_editor(
            editor_df,
            column_config={
                "key": None,
                "セクション": st.column_config.TextColumn(disabled=True),
                "表示": st.column_config.CheckboxColumn(),
                "順序": st.column_config.NumberColumn(min_value=1, max_value=5, step=1),
            },
            hide_index=True,
            key="sector_section_editor",
        )
        new_visible = {
            key: bool(value) for key, value in zip(edited_df["key"], edited_df["表示"])
        }
        new_order = {
            key: (
                int(value)
                if pd.notna(value)
                else display_settings["order"][key]
            )
            for key, value in zip(edited_df["key"], edited_df["順序"])
        }

        new_height = dict(display_settings["height"])
        height_specs = [
            ("heatmap", "業種間相関ヒートマップの高さ (px)"),
            ("network_diagram", "業種間ネットワークの高さ (px)"),
            ("wavelet_analysis", "ウェーブレット分析ヒートマップの高さ (px)"),
        ]
        for key, label in height_specs:
            if new_visible[key]:
                # key=f"sector_height_{key}"のようにループ内でキーを動的に組み立て、
                # 3つのスライダーそれぞれに一意なsession_stateキーを与えている
                # （同じキーを使い回すとStreamlitがウィジェットを区別できずエラーになる）
                new_height[key] = st.slider(
                    label,
                    250,
                    900,
                    display_settings["height"][key],
                    50,
                    key=f"sector_height_{key}",
                )

        new_display_settings = {
            "visible": new_visible,
            "order": new_order,
            "height": new_height,
        }
        if new_display_settings != display_settings:
            save_sector_display_settings(get_current_user_id(), new_display_settings)
            display_settings = new_display_settings

    # st.columns(3)は横並びの3つのコンテナ（列）を作る。取得期間・キャッシュ設定・
    # 実行ボタンを1行に横並びで配置するために使う
    col_period, col_regen, col_run = st.columns(3)
    with col_period:
        sector_period = st.selectbox(
            "取得期間",
            ["6mo", "1y", "2y"],
            index=1,
            key="sector_period",
            help=(
                "株価データを取得する期間です。長いほど長期の周期（サイクル）分析の"
                "精度が上がりますが、取得に時間がかかります。"
            ),
        )
    with col_regen:
        sector_force_regenerate = st.checkbox(
            "キャッシュを無視して再生成する",
            key="sector_force_regenerate",
            help=(
                "前回と同じ期間で分析済みの場合、通常は保存済みの結果を再利用します。"
                "最新データで計算し直したいときにチェックしてください。"
            ),
        )
    with col_run:
        # st.button()はクリックされた直後の1回のrerunだけTrueを返す。
        # 押していない状態やページの再読み込みでは常にFalseになる
        run_clicked = st.button(
            "分析を実行",
            help=(
                "初回実行時は228銘柄のデータ取得のため30秒程度かかります"
                "（2回目以降はキャッシュにより高速です）。"
            ),
        )

    if run_clicked:
        # run_or_load_sector_rotation()の内部で計算結果をキャッシュしており、
        # 同じ期間で分析済みなら重い相関計算・データ取得をやり直さずに済む
        payload = run_or_load_sector_rotation(sector_period, sector_force_regenerate)
        if payload is None:
            st.error("分析可能な銘柄がありませんでした。")

    # run_or_load_sector_rotation()が結果をst.session_state["sector_payload"]にも
    # 保存しているため、「分析を実行」ボタンを押していないrerun（表示設定を
    # 変えたときなど）でも、前回の分析結果を使ってこの下の描画を続けられる
    if st.session_state.get("sector_payload") is not None:
        payload = st.session_state["sector_payload"]
        pairs = payload["pairs"]

        if not pairs:
            st.info("有効な業種ペアがありませんでした。")

        section_renderers = {
            "heatmap": lambda: render_heatmap(pairs, display_settings["height"]["heatmap"]),
            "pairs_table": lambda: render_pairs_table(pairs),
            "ai_comments": lambda: render_ai_comments(pairs, payload["comments"]),
            "network_diagram": lambda: render_network_diagram(
                payload["network_pairs"], display_settings["height"]["network_diagram"]
            ),
            "wavelet_analysis": lambda: render_wavelet_analysis(
                payload, pairs, sector_period, display_settings["height"]["wavelet_analysis"]
            ),
        }
        ordered_keys = sorted(
            section_renderers, key=lambda k: display_settings["order"][k]
        )
        for key in ordered_keys:
            if key in ("heatmap", "pairs_table", "ai_comments") and not pairs:
                continue
            if display_settings["visible"][key]:
                section_renderers[key]()

        if payload["skipped_tickers"]:
            st.info(
                "データ取得・データ不足によりスキップした銘柄: "
                + ", ".join(payload["skipped_tickers"])
            )
        if payload["excluded_sectors"]:
            st.info(
                "構成銘柄が取得できず分析から除外した業種: "
                + ", ".join(payload["excluded_sectors"])
            )

        st.markdown(DISCLAIMER_NOTICE)
