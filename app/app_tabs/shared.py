"""複数タブ間で共有するキャッシュ付きデータ取得関数・銘柄詳細ダイアログ・
テーブル選択ヘルパー・セクターローテーション分析の共通実行処理、
および保存先パスの定数。
"""

import hashlib
import json
import logging
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from analysis_agents.fundamental_agent import analyze_fundamentals
from common.cache import read_cache, write_cache
from common.concurrency import map_concurrently
from common.disclaimer import DISCLAIMER_NOTICE
from common.logging_config import log_duration
from data_api.llm_client import call_llm
from data_api.stock_price_api import (
    fetch_japanese_name,
    fetch_news,
    fetch_price_history,
    load_all_company_profiles,
)
from prompt_patterns.sector_rotation import generate_sector_rotation_comments
from sector_analysis.correlation import compute_lead_lag_pairs, compute_sector_returns
from sector_analysis.wavelet import compute_all_pairs_dominant_lag, serialize_sector_returns
from stock_detail.detail import generate_stock_detail

logger = logging.getLogger(__name__)

# API取得結果のキャッシュを保存するディレクトリ構成
APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"

def get_current_user_id() -> int:
    """ログイン中のユーザーのIDを返す。app.pyがログイン成功時に
    st.session_state["user_id"]を設定するため、このタブ描画コードに到達する時点では
    必ず設定済み。"""
    return st.session_state["user_id"]


@st.cache_data(ttl=60)
def cached_fetch_japanese_name(ticker: str) -> str | None:
    """銘柄名はDB（CompanyProfile）で全ユーザー共有・長期キャッシュされているため、
    ここでは同一セッション内の連続rerunでDB問い合わせを繰り返さない薄い前段
    キャッシュとして短時間だけ保持する。"""
    return fetch_japanese_name(ticker)


@st.cache_data(ttl=60)
def cached_fetch_price_history(ticker: str, period: str):
    """株価履歴はDB（PriceHistory）で全ユーザー共有・長期キャッシュされているため、
    ここでは同一セッション内の連続rerunでDB問い合わせを繰り返さない薄い前段
    キャッシュとして短時間だけ保持する。"""
    return fetch_price_history(ticker, period=period)


@st.cache_data(ttl=60)
def cached_analyze_fundamentals(ticker: str) -> dict:
    """ファンダメンタルズはDB（FundamentalsSnapshot）で全ユーザー共有・長期
    キャッシュされているため、ここでは同一セッション内の連続rerunでDB問い合わせを
    繰り返さない薄い前段キャッシュとして短時間だけ保持する。"""
    return analyze_fundamentals(ticker)


@st.cache_data(ttl=60)
def cached_fetch_news(ticker: str) -> list[dict]:
    """ニュースはDB（TickerNews）に蓄積されるため、ここでは同一セッション内の
    連続rerunでDB問い合わせを繰り返さない薄い前段キャッシュとして短時間だけ
    保持する。"""
    return fetch_news(ticker)


@st.dialog("銘柄詳細情報", width="large")
def show_stock_detail_dialog(ticker: str, name: str | None) -> None:
    """銘柄の株価チャート・ファンダメンタルズ・テクニカル・AIコメント・関連ニュースを
    1つのモーダルにまとめて表示する。各タブの一覧から銘柄をクリックした際の共通詳細画面として使う。
    """
    with st.spinner("銘柄情報を取得中..."):
        detail = generate_stock_detail(ticker, name, CACHE_DIR, call_llm=call_llm)

    st.subheader(f"{ticker} {detail.get('name') or ''}")

    profile = detail.get("profile") or {}
    st.subheader("基本情報")
    profile_col1, profile_col2 = st.columns(2)
    profile_col1.write(f"業種: {profile.get('sector') or '―'}")
    profile_col2.write(f"詳細業種: {profile.get('industry') or '―'}")
    st.caption("AIによる市場ポジション・強みの要約")
    st.write(profile.get("profile_comment") or "―")

    price_history = detail["price_history"]
    technical = detail["technical"]
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

        # RSI・ADX・ATR%は移動平均線と同様、計算バッファ込みの全期間の時系列を
        # 保持しておき、表示直前に価格チャートと同じ直近6ヶ月へ絞り込むことで
        # チャート開始時点から途切れなく、かつ価格チャートと日付軸を揃えて描画する。
        indicator_df = pd.DataFrame(
            {
                "date": pd.to_datetime(price_history["dates"]),
                "rsi": technical.get("rsi_series"),
                "adx": technical.get("adx_series"),
                "atr_pct": technical.get("atr_pct_series"),
            }
        )
        indicator_df = indicator_df[indicator_df["date"] >= display_start].reset_index(drop=True)

        st.caption("RSI(14日) ― 破線は買われすぎ(70)／売られすぎ(30)の目安")
        rsi_line = alt.Chart(indicator_df).mark_line(strokeWidth=1.5, color="#1f77b4").encode(
            x=alt.X("date:T", title=None),
            y=alt.Y("rsi:Q", title="RSI", scale=alt.Scale(domain=[0, 100])),
        )
        rsi_thresholds = alt.Chart(pd.DataFrame({"y": [70, 30]})).mark_rule(
            strokeDash=[4, 2], color="gray"
        ).encode(y="y:Q")
        st.altair_chart((rsi_line + rsi_thresholds).properties(height=120), width="stretch")

        st.caption("ADX(14日) ― 破線は強いトレンドの目安(25)")
        adx_line = alt.Chart(indicator_df).mark_line(strokeWidth=1.5, color="#9467bd").encode(
            x=alt.X("date:T", title=None), y=alt.Y("adx:Q", title="ADX")
        )
        adx_threshold = alt.Chart(pd.DataFrame({"y": [25]})).mark_rule(
            strokeDash=[4, 2], color="gray"
        ).encode(y="y:Q")
        st.altair_chart((adx_line + adx_threshold).properties(height=120), width="stretch")

        st.caption("ATR(14日, 終値比%) ― 値動きの大きさ")
        atr_chart = alt.Chart(indicator_df).mark_line(strokeWidth=1.5, color="#ff7f0e").encode(
            x=alt.X("date:T", title=None), y=alt.Y("atr_pct:Q", title="ATR(%)")
        )
        st.altair_chart(atr_chart.properties(height=120), width="stretch")
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

    st.write(f"テクニカルシグナル（移動平均線）: **{technical.get('signal')}**")

    # RSI・ADX・ATR・OBVを、それぞれ「勢い」「トレンド強さ」「値動きの大きさ」
    # 「出来高の裏付け」を表すテクニカル指標としてメトリクス表示する（グラフは上部に表示済み）
    rsi_col, adx_col, atr_col, obv_col = st.columns(4)
    rsi = technical.get("rsi")
    rsi_col.metric(
        "RSI(14日)", f"{rsi}" if rsi is not None else "―", technical.get("rsi_signal") or "―"
    )
    adx = technical.get("adx")
    adx_col.metric(
        "ADX(14日)", f"{adx}" if adx is not None else "―", technical.get("adx_signal") or "―"
    )
    atr_pct = technical.get("atr_pct")
    atr_col.metric(
        "ATR(14日)",
        f"{atr_pct}%" if atr_pct is not None else "―",
        technical.get("atr_signal") or "―",
    )
    obv_col.metric("OBV(出来高)", technical.get("obv_signal") or "―")

    st.subheader("AI総合分析コメント")
    st.write(detail["comment"])

    # 分析の根拠となった関連ニュースを一覧表示する
    st.subheader("関連ニュース")
    news_items = detail["news"]
    if not news_items:
        st.write("ニュースが取得できませんでした。")
    for item in news_items:
        title = item.get("title_ja") or item.get("title") or "(タイトルなし)"
        publisher = item.get("publisher") or "?"
        link = item.get("link")
        if link:
            st.markdown(f"- [{title}]({link})（{publisher}）")
        else:
            st.markdown(f"- {title}（{publisher}）")
        # 要約は日本語訳（summary_ja）を優先し、翻訳が無ければ英文原文（summary）を表示する
        summary_text = item.get("summary_ja") or item.get("summary")
        if summary_text:
            with st.expander("要約を見る"):
                st.write(summary_text)

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


def render_mermaid(code: str, height: int = 400) -> None:
    """Mermaidコード文字列を、CDN経由のmermaid.js + svg-pan-zoom.jsを使って
    ドラッグパン・ホイールズーム可能なHTML埋め込みとして描画する。

    セクタータブの業種間ネットワーク図・AI戦略ビルダータブの選定銘柄向け
    業種ネットワーク図の両方から共通で呼ばれる。"""
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
    st.iframe(html, height=height)


def run_or_load_sector_rotation(period: str, force_regenerate: bool) -> dict | None:
    """セクターローテーション分析を実行または既存キャッシュから読み込み、
    ペイロード（pairs/sector_returns/network_pairs/comments/
    ticker_latest_return_pct等）を返す。分析可能な銘柄が1件もない場合はNoneを返す。

    対象銘柄は company_profiles のうち sector_jp（東証17業種区分）が設定されて
    いるものに限る（業種バケット化が前提の分析のため）。

    セクタータブ・AI戦略ビルダータブの両方から呼ばれる共通処理。同一の
    period・対象銘柄集合であればディスクキャッシュを共有し、二重計算を避ける。
    実行結果は st.session_state["sector_payload"] にも保存する。
    """
    company_profiles = load_all_company_profiles()
    sector_jp_by_ticker = {
        p["ticker"]: p["sector_jp"] for p in company_profiles if p["sector_jp"]
    }
    sector_universe = sorted(sector_jp_by_ticker)

    cache_key = "sector-rotation-" + hashlib.sha256(
        f"{period}-{'-'.join(sector_universe)}".encode("utf-8")
    ).hexdigest()[:12]
    cached_payload = None if force_regenerate else read_cache(CACHE_DIR, cache_key)
    payload = json.loads(cached_payload) if cached_payload is not None else None
    if payload is not None and (
        "sector_returns" not in payload
        or "network_pairs" not in payload
        or "ticker_latest_return_pct" not in payload
    ):
        # 旧スキーマ（ticker_latest_return_pct未保存等）のキャッシュは再計算して移行する
        payload = None

    if payload is None:
        with log_duration(logger, f"セクターローテーション分析実行（{period}）"):
            skipped_tickers = []
            prices_by_ticker = {}
            with st.spinner(f"株価データを取得中...（{len(sector_universe)}銘柄）"):
                price_results = map_concurrently(
                    sector_universe, lambda ticker: cached_fetch_price_history(ticker, period)
                )
            for ticker in sector_universe:
                history = price_results[ticker]
                if isinstance(history, Exception) or history is None or history.empty:
                    skipped_tickers.append(ticker)
                else:
                    prices_by_ticker[ticker] = history["Close"]

            if not prices_by_ticker:
                logger.warning("セクターローテーション分析実行不可（対象銘柄が0件）")
                return None

            # 業種集計前の銘柄別直近日次リターン（AI戦略ビルダーの
            # 「本日の値上がり銘柄」検出に使う）
            ticker_latest_return_pct: dict[str, float] = {}
            for ticker, prices in prices_by_ticker.items():
                daily_returns = prices.pct_change()
                if len(daily_returns) >= 2 and pd.notna(daily_returns.iloc[-1]):
                    ticker_latest_return_pct[ticker] = float(daily_returns.iloc[-1] * 100)

            sector_returns = compute_sector_returns(prices_by_ticker, sector_jp_by_ticker)
            excluded_sectors = sorted(
                set(sector_jp_by_ticker.values()) - set(sector_returns.keys())
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
                "ticker_latest_return_pct": ticker_latest_return_pct,
            }
            write_cache(CACHE_DIR, cache_key, json.dumps(payload, ensure_ascii=False))

    st.session_state["sector_payload"] = payload
    return payload
