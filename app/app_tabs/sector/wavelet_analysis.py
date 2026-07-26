"""セクタータブ: ウェーブレット分析（時間変化するリード・ラグ）の描画。"""

import hashlib

import altair as alt
import pandas as pd
import streamlit as st

from common.cache import read_cache, write_cache
from data_api.llm_client import call_llm
from prompt_patterns.wavelet_explanation import generate_wavelet_explanation
from sector_analysis.wavelet import (
    compute_cross_wavelet_lead_lag,
    compute_dominant_lag_series,
    deserialize_sector_returns,
    summarize_band_snapshot,
)

from app_tabs.shared import CACHE_DIR


def render_wavelet_analysis(
    payload: dict, pairs: list[dict], sector_period: str, height: int
) -> None:
    """選択した2業種について、周期の長さ（短期・中期・長期）ごとに時間変化する
    先行・追随関係を可視化する。"""
    st.subheader(
        "ウェーブレット分析（時間変化するリード・ラグ）",
        help="時間の経過とともに変化する、業種間の先行・追随関係を可視化します。",
    )
    st.caption(
        "選択した2つの業種について、値動きの周期の長さ（短期・中期・長期）ごとに、"
        "どちらの業種がどれくらい先行しているかの時間変化を可視化します。"
        "色が薄い部分は関係の確からしさ（コヒーレンス）が低いことを示します。"
    )
    with st.expander("ウェーブレット分析とは？"):
        st.markdown(
            "通常の相関分析は「期間全体で1つの数値」を計算しますが、実際の"
            "値動きには短い周期（数日〜2週間程度）の動きと、長い周期"
            "（1〜6か月程度）の動きが混ざっています。ウェーブレット分析は、"
            "この値動きを周期の長さ（短期・中期・長期）ごとに分解し、周期ごとに"
            "「どちらの業種が先に動いたか」「どれくらい確からしい関係か"
            "（コヒーレンス）」を計算する手法です。\n\n"
            "**周期帯の目安**\n"
            "- 短期: 4〜10営業日程度（1〜2週間の値動き）\n"
            "- 中期: 10〜40営業日程度（2週間〜2か月の値動き）\n"
            "- 長期: 40〜120営業日程度（2〜6か月の値動き）\n\n"
            "**下のヒートマップの読み方**\n"
            "- 横軸: 日付\n"
            "- 縦軸: 周期の長さ（営業日）\n"
            "- 色: 正（青系）なら業種Aが先行、負（赤系）なら業種Bが先行\n"
            "- 色の濃さ: 関係の確からしさ（コヒーレンス）。薄いほど確からしさが"
            "低く、参考程度に留めてください\n\n"
            "下部の「支配的ラグ」の折れ線グラフは、選んだ周期帯の中で"
            "コヒーレンスの高い部分を重視した、平均的な先行・遅行日数の推移を"
            "示します。0より上なら業種Aが先行、0より下なら業種Bが先行して"
            "いたことを意味します。"
        )

    sector_options = sorted(payload["sector_returns"].keys())
    if len(sector_options) < 2:
        st.info("ウェーブレット分析には2業種以上のデータが必要です。")
    else:
        default_x = pairs[0]["leading_sector"] if pairs else sector_options[0]
        default_y = pairs[0]["lagging_sector"] if pairs else sector_options[1]
        if default_x not in sector_options:
            default_x = sector_options[0]
        if default_y not in sector_options or default_y == default_x:
            default_y = next(s for s in sector_options if s != default_x)

        col_a, col_b = st.columns(2)
        sector_select_help = (
            "比較したい2つの業種を選びます"
            "（デフォルトは相関上位ペアの先行・追随業種）。"
        )
        with col_a:
            sector_x = st.selectbox(
                "業種A",
                sector_options,
                index=sector_options.index(default_x),
                key="wavelet_sector_x",
                help=sector_select_help,
            )
        with col_b:
            sector_y = st.selectbox(
                "業種B",
                sector_options,
                index=sector_options.index(default_y),
                key="wavelet_sector_y",
                help=sector_select_help,
            )

        if st.button("ウェーブレット分析を実行"):
            all_series = deserialize_sector_returns(payload["sector_returns"])
            try:
                wavelet_df = compute_cross_wavelet_lead_lag(
                    all_series[sector_x], all_series[sector_y], sector_x, sector_y
                )
            except Exception:
                st.error("ウェーブレット分析の計算に失敗しました。")
                wavelet_df = pd.DataFrame()

            if wavelet_df.empty:
                st.warning(
                    "選択した2業種の共通データが不足しているため、分析できませんでした。"
                )
                st.session_state["wavelet_result"] = None
            else:
                st.session_state["wavelet_result"] = {
                    "df": wavelet_df,
                    "x": sector_x,
                    "y": sector_y,
                }

        wavelet_result = st.session_state.get("wavelet_result")
        if wavelet_result is not None:
            wavelet_df = wavelet_result["df"]

            heatmap = (
                alt.Chart(wavelet_df)
                .mark_rect()
                .encode(
                    x=alt.X("date:T", title=None),
                    y=alt.Y(
                        "period_days:O", title="周期（営業日）", sort="descending"
                    ),
                    color=alt.Color(
                        "lag_days:Q",
                        title=f"ラグ（正={wavelet_result['x']}が先行）",
                        scale=alt.Scale(scheme="redblue", domainMid=0),
                    ),
                    opacity=alt.Opacity(
                        "coherence:Q", scale=alt.Scale(domain=[0, 1], range=[0.05, 1])
                    ),
                    tooltip=[
                        "date:T",
                        "period_days:Q",
                        "band:N",
                        "coherence:Q",
                        "lag_days:Q",
                        "leading_sector:N",
                    ],
                )
                .properties(height=height)
                .interactive()
            )
            st.altair_chart(heatmap, width="stretch")

            band = st.selectbox(
                "周期帯",
                ["短期", "中期", "長期"],
                index=1,
                key="wavelet_band",
                help=(
                    "短期(4〜10営業日) / 中期(10〜40営業日) / 長期(40〜120営業日) "
                    "のいずれかを選び、その周期帯における支配的ラグの推移を"
                    "表示します。"
                ),
            )
            band_df = wavelet_df[wavelet_df["band"] == band]
            if band_df.empty:
                st.info("この周期帯には有効なデータがありませんでした。")
            else:
                dominant = compute_dominant_lag_series(band_df)
                line = (
                    alt.Chart(dominant)
                    .mark_line()
                    .encode(
                        x=alt.X("date:T", title=None),
                        y=alt.Y("dominant_lag_days:Q", title="支配的ラグ（日）"),
                    )
                    .properties(height=250)
                    .interactive()
                )
                st.altair_chart(line, width="stretch")

                # 直近シグナルの要約パネル（機械的な数値表示、AI不使用）。
                # 周期帯セレクトボックスの変更ごとに自動的に追従する。
                snapshot = summarize_band_snapshot(band_df)
                if snapshot is not None:
                    snap_lag = snapshot["dominant_lag_days"]
                    snap_leading = sector_x if snap_lag >= 0 else sector_y
                    snap_lagging = sector_y if snap_lag >= 0 else sector_x

                    col_lag, col_coherence = st.columns(2)
                    col_lag.metric("支配的ラグ（日）", f"{snap_lag:+.1f}")
                    col_coherence.metric(
                        "コヒーレンス", f"{snapshot['avg_coherence']:.2f}"
                    )
                    st.caption(
                        f"直近（{snapshot['date'].strftime('%Y-%m-%d')}）時点: "
                        f"{snap_leading} が {snap_lagging} に約{abs(snap_lag):.1f}営業日先行"
                        f"（コヒーレンス {snapshot['avg_coherence']:.2f}）"
                    )

                    # AI解説コメント（明示的ボタン起動、日次ファイルキャッシュ）。
                    # 表示中のペア・周期帯と異なる古いコメントを残さないよう、
                    # session_stateには生成時のキーも一緒に保持し、一致時のみ表示する。
                    wavelet_comment_key = (sector_x, sector_y, sector_period, band)
                    wavelet_comment_force_regenerate = st.checkbox(
                        "AI解説のキャッシュを無視して再生成する",
                        key="wavelet_comment_force_regenerate",
                    )
                    if st.button("AI解説を生成", key="wavelet_comment_button"):
                        comment_cache_key = "wavelet-comment-" + hashlib.sha256(
                            "-".join(
                                str(part) for part in wavelet_comment_key
                            ).encode("utf-8")
                        ).hexdigest()[:12]
                        cached_comment = (
                            None
                            if wavelet_comment_force_regenerate
                            else read_cache(CACHE_DIR, comment_cache_key)
                        )
                        if cached_comment is not None:
                            wavelet_comment_text = cached_comment
                        else:
                            wavelet_comment_text = generate_wavelet_explanation(
                                sector_x, sector_y, band, snapshot, call_llm=call_llm
                            )
                            write_cache(
                                CACHE_DIR, comment_cache_key, wavelet_comment_text
                            )
                        st.session_state["wavelet_comment"] = {
                            "key": wavelet_comment_key,
                            "text": wavelet_comment_text,
                        }

                    cached_state = st.session_state.get("wavelet_comment")
                    if (
                        cached_state is not None
                        and cached_state["key"] == wavelet_comment_key
                    ):
                        st.markdown(cached_state["text"])
