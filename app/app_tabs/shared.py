"""複数タブ間で共有するキャッシュ付きデータ取得関数・銘柄詳細ダイアログ・
テーブル選択ヘルパー、および保存先パスの定数。
"""

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from analysis_agents.fundamental_agent import analyze_fundamentals
from common.disclaimer import DISCLAIMER_NOTICE
from data_api.llm_client import call_llm
from data_api.stock_price_api import fetch_japanese_name, fetch_news, fetch_price_history
from stock_detail.detail import generate_stock_detail

# 保有銘柄データやAPI取得結果のキャッシュを保存するディレクトリ構成
APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
HOLDINGS_PATH = DATA_DIR / "holdings.json"
SECTOR_DISPLAY_SETTINGS_PATH = DATA_DIR / "sector_display_settings.json"
CACHE_DIR = DATA_DIR / "cache"


@st.cache_data(ttl=60 * 60 * 24)
def cached_fetch_japanese_name(ticker: str) -> str | None:
    """銘柄名はほぼ変化しないため、1日単位でキャッシュして外部API呼び出しを抑える。"""
    return fetch_japanese_name(ticker)


@st.cache_data(ttl=60 * 30)
def cached_fetch_price_history(ticker: str, period: str):
    """株価履歴は頻繁な再取得が不要なため、30分キャッシュして表示速度と負荷を両立する。"""
    return fetch_price_history(ticker, period=period)


@st.cache_data(ttl=60 * 30)
def cached_analyze_fundamentals(ticker: str) -> dict:
    """ファンダメンタルズ分析結果を30分キャッシュし、同一銘柄への重複計算を避ける。"""
    return analyze_fundamentals(ticker)


@st.cache_data(ttl=60 * 30)
def cached_fetch_news(ticker: str) -> list[dict]:
    """ニュース取得結果を30分キャッシュし、同一銘柄への重複リクエストを避ける。"""
    return fetch_news(ticker)


@st.dialog("銘柄詳細情報", width="large")
def show_stock_detail_dialog(ticker: str, name: str | None) -> None:
    """銘柄の株価チャート・ファンダメンタルズ・テクニカル・AIコメント・関連ニュースを
    1つのモーダルにまとめて表示する。各タブの一覧から銘柄をクリックした際の共通詳細画面として使う。
    """
    with st.spinner("銘柄情報を取得中..."):
        detail = generate_stock_detail(ticker, name, CACHE_DIR, call_llm=call_llm)

    st.subheader(f"{ticker} {detail.get('name') or ''}")

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
        # 移動平均は表示範囲より前のデータも使って計算し、表示開始時点から
        # 途切れなく描画できるようにする（price_historyは2年分取得済み）。
        chart_df["ma5"] = chart_df["close"].rolling(window=5).mean()
        chart_df["ma25"] = chart_df["close"].rolling(window=25).mean()
        chart_df["ma75"] = chart_df["close"].rolling(window=75).mean()

        # 移動平均の計算バッファ分を除き、直近6ヶ月のみを表示する
        display_start = chart_df["date"].max() - pd.DateOffset(months=6)
        chart_df = chart_df[chart_df["date"] >= display_start].reset_index(drop=True)

        # 陽線/陰線を色分けするため、始値と終値の大小関係から方向を判定する
        chart_df["direction"] = chart_df.apply(
            lambda row: "up" if row["close"] >= row["open"] else "down", axis=1
        )
        color_scale = alt.Scale(domain=["up", "down"], range=["#26a69a", "#ef5350"])

        # ローソク足チャートをヒゲ（rule）と実体（bar）の2レイヤーで構成する
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

        ma_labels = {"ma5": "5日線", "ma25": "25日線", "ma75": "75日線"}
        ma_df = (
            chart_df.melt(
                id_vars=["date"],
                value_vars=list(ma_labels),
                var_name="MA",
                value_name="value",
            )
            .dropna(subset=["value"])
            .replace({"MA": ma_labels})
        )
        ma_color_scale = alt.Scale(
            domain=list(ma_labels.values()), range=["#1f77b4", "#ff7f0e", "#9467bd"]
        )
        ma_lines = alt.Chart(ma_df).mark_line(strokeWidth=1.5).encode(
            x="date:T",
            y="value:Q",
            color=alt.Color("MA:N", scale=ma_color_scale, title="移動平均線"),
        )

        st.altair_chart((wick + body + ma_lines).properties(height=300), width="stretch")

        # 出来高は価格チャートの下に別チャートとして表示する
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

    # 主要ファンダメンタルズ指標をメトリクスとして横並びに表示する
    fundamentals = detail["fundamentals"]
    col1, col2, col3 = st.columns(3)
    col1.metric("PER", fundamentals.get("per") if fundamentals.get("per") is not None else "―")
    col2.metric("PBR", fundamentals.get("pbr") if fundamentals.get("pbr") is not None else "―")
    col3.metric(
        "配当利回り(%)",
        fundamentals.get("dividend_yield")
        if fundamentals.get("dividend_yield") is not None
        else "―",
    )

    st.write(f"テクニカルシグナル: **{detail['technical'].get('signal')}**")

    st.subheader("AI総合分析コメント")
    st.write(detail["comment"])

    # 分析の根拠となった関連ニュースを一覧表示する
    st.subheader("関連ニュース")
    news_items = detail["news"]
    if not news_items:
        st.write("ニュースが取得できませんでした。")
    for item in news_items:
        title = item.get("title") or "(タイトルなし)"
        publisher = item.get("publisher") or "?"
        link = item.get("link")
        if link:
            st.markdown(f"- [{title}]({link})（{publisher}）")
        else:
            st.markdown(f"- {title}（{publisher}）")

    st.markdown(DISCLAIMER_NOTICE)


def handle_table_selection(state_key: str, event, df: pd.DataFrame) -> None:
    """データフレーム表の行選択イベントを処理する共通ヘルパー。
    選択行の変化をセッション状態に記録し、新たに選択された銘柄の詳細ダイアログを開く。
    """
    current = event.selection.rows[0] if event.selection.rows else None
    if current != st.session_state.get(state_key):
        st.session_state[state_key] = current
        if current is not None and current < len(df):
            row = df.iloc[current]
            show_stock_detail_dialog(row["ticker"], row.get("name") or "")
