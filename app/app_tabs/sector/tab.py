"""セクタータブ: セクターローテーション分析のエントリーポイント。
表示設定・分析実行（データ取得・キャッシュ）を担当し、個別グラフの描画は
app_tabs.sector 配下の各モジュールに委譲する。
"""

import hashlib
import json

import pandas as pd
import streamlit as st

from common.cache import read_cache, write_cache
from common.concurrency import map_concurrently
from common.disclaimer import DISCLAIMER_NOTICE
from data_api.llm_client import call_llm
from prompt_patterns.sector_rotation import generate_sector_rotation_comments
from screening.sectors import SECTOR_MAP
from screening.universe import UNIVERSE
from sector_analysis.correlation import compute_lead_lag_pairs, compute_sector_returns
from sector_analysis.display_settings import (
    load_sector_display_settings,
    save_sector_display_settings,
)
from sector_analysis.wavelet import compute_all_pairs_dominant_lag, serialize_sector_returns

from app_tabs.sector.ai_comments import render_ai_comments
from app_tabs.sector.heatmap import render_heatmap
from app_tabs.sector.network_diagram import render_network_diagram
from app_tabs.sector.pairs_table import render_pairs_table
from app_tabs.sector.wavelet_analysis import render_wavelet_analysis
from app_tabs.shared import CACHE_DIR, SECTOR_DISPLAY_SETTINGS_PATH, cached_fetch_price_history


def render_sector_tab() -> None:
    st.header("セクターローテーション")
    st.caption(
        "UNIVERSE銘柄を17業種に分類し、業種間の値動きの時差相関（リード・ラグ）を"
        "過去の株価データから計算します。あくまで過去の統計的傾向であり、"
        "将来の値動きを保証するものではありません。"
    )

    display_settings = load_sector_display_settings(SECTOR_DISPLAY_SETTINGS_PATH)
    section_labels = {
        "heatmap": "業種間相関ヒートマップ",
        "pairs_table": "リード・ラグ上位ペア",
        "ai_comments": "相関上位5ペアのAIコメント",
        "network_diagram": "業種間ネットワーク（全ペア俯瞰）",
        "wavelet_analysis": "ウェーブレット分析",
    }
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
            save_sector_display_settings(SECTOR_DISPLAY_SETTINGS_PATH, new_display_settings)
            display_settings = new_display_settings

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
        run_clicked = st.button(
            "分析を実行",
            help=(
                "初回実行時は228銘柄のデータ取得のため30秒程度かかります"
                "（2回目以降はキャッシュにより高速です）。"
            ),
        )

    if run_clicked:
        # 取得期間と対象ユニバースが同一なら分析結果をキャッシュから再利用する
        cache_key = "sector-rotation-" + hashlib.sha256(
            f"{sector_period}-{'-'.join(sorted(UNIVERSE))}".encode("utf-8")
        ).hexdigest()[:12]
        cached_payload = (
            None if sector_force_regenerate else read_cache(CACHE_DIR, cache_key)
        )
        payload = json.loads(cached_payload) if cached_payload is not None else None
        if payload is not None and (
            "sector_returns" not in payload or "network_pairs" not in payload
        ):
            # 旧スキーマのキャッシュ（sector_returns/network_pairs未保存）は再計算して移行する
            payload = None

        if payload is None:
            skipped_tickers = []
            prices_by_ticker = {}
            # ユニバース全銘柄の株価取得を並列化して待ち時間を短縮する
            with st.spinner(f"株価データを取得中...（{len(UNIVERSE)}銘柄）"):
                price_results = map_concurrently(
                    UNIVERSE,
                    lambda ticker: cached_fetch_price_history(ticker, sector_period),
                )
            # データ取得に失敗・不足した銘柄は分析対象から除外する
            for ticker in UNIVERSE:
                history = price_results[ticker]
                if isinstance(history, Exception) or history is None or history.empty:
                    skipped_tickers.append(ticker)
                else:
                    prices_by_ticker[ticker] = history["Close"]

            if not prices_by_ticker:
                st.error("分析可能な銘柄がありませんでした。")
                payload = None
            else:
                # 銘柄別リターンを業種別に集約し、業種間のリード・ラグ相関を算出する
                sector_returns = compute_sector_returns(prices_by_ticker, SECTOR_MAP)
                excluded_sectors = sorted(
                    set(SECTOR_MAP.values()) - set(sector_returns.keys())
                )
                pairs = compute_lead_lag_pairs(sector_returns, max_lag_days=20)
                with st.spinner("ネットワーク図データを計算中（136ペア）..."):
                    network_pairs_df = compute_all_pairs_dominant_lag(sector_returns)
                comments = generate_sector_rotation_comments(pairs[:5], call_llm=call_llm)
                payload = {
                    "pairs": pairs,
                    "skipped_tickers": skipped_tickers,
                    "excluded_sectors": excluded_sectors,
                    "comments": comments,
                    "sector_returns": serialize_sector_returns(sector_returns),
                    "network_pairs": network_pairs_df.to_dict("records"),
                }
                write_cache(CACHE_DIR, cache_key, json.dumps(payload, ensure_ascii=False))

        if payload is not None:
            st.session_state["sector_payload"] = payload

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
