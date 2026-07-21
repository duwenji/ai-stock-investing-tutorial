"""日本株を対象としたAI投資リサーチアプリのエントリーポイント（Streamlit）。

ポートフォリオ管理・スクリーニング・バックテスト・一括バックテストランキング・
セクターローテーション分析の各機能をタブ形式のUIとしてまとめ、
株価/ファンダメンタルズ/ニュース取得とLLM（Claude）によるコメント生成を組み合わせて提供する。
"""

import hashlib
import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from analysis_agents.fundamental_agent import analyze_fundamentals
from analysis_agents.news_research_agent import research_news_batch
from analysis_agents.technical_agent import analyze_technical
from common.cache import read_cache, write_cache
from common.concurrency import map_concurrently
from common.disclaimer import DISCLAIMER_NOTICE
from common.json_parsing import strip_code_fence
from data_api.llm_client import call_llm, check_claude_cli_available
from data_api.stock_price_api import (
    fetch_japanese_name,
    fetch_news,
    fetch_price_history,
    fetch_universe_fundamentals,
)
from portfolio_management.backtest import (
    STRATEGIES,
    generate_backtest_explanation,
    run_backtest_comparison,
    run_universe_backtest_ranking,
)
from portfolio_management.review import generate_portfolio_review
from portfolio_management.storage import load_holdings, save_holdings
from portfolio_management.ticker_names import build_candidate_names
from prompt_patterns.backtest_explanation import generate_ranking_comments
from prompt_patterns.screening import (
    apply_filters,
    build_screening_prompt,
    generate_screening_comments,
)
from prompt_patterns.sector_rotation import generate_sector_rotation_comments
from screening.sectors import SECTOR_MAP
from screening.universe import UNIVERSE, UNIVERSE_NAMES
from sector_analysis.correlation import compute_lead_lag_pairs, compute_sector_returns
from sector_analysis.wavelet import (
    compute_cross_wavelet_lead_lag,
    compute_dominant_lag_series,
    deserialize_sector_returns,
    serialize_sector_returns,
)
from stock_detail.detail import generate_stock_detail

# 保有銘柄データやAPI取得結果のキャッシュを保存するディレクトリ構成
DATA_DIR = Path(__file__).parent / "data"
HOLDINGS_PATH = DATA_DIR / "holdings.json"
CACHE_DIR = DATA_DIR / "cache"


@st.cache_data(ttl=60 * 60 * 24)
def _cached_fetch_japanese_name(ticker: str) -> str | None:
    """銘柄名はほぼ変化しないため、1日単位でキャッシュして外部API呼び出しを抑える。"""
    return fetch_japanese_name(ticker)


@st.cache_data(ttl=60 * 30)
def _cached_fetch_price_history(ticker: str, period: str):
    """株価履歴は頻繁な再取得が不要なため、30分キャッシュして表示速度と負荷を両立する。"""
    return fetch_price_history(ticker, period=period)


@st.cache_data(ttl=60 * 30)
def _cached_analyze_fundamentals(ticker: str) -> dict:
    """ファンダメンタルズ分析結果を30分キャッシュし、同一銘柄への重複計算を避ける。"""
    return analyze_fundamentals(ticker)


@st.cache_data(ttl=60 * 30)
def _cached_fetch_news(ticker: str) -> list[dict]:
    """ニュース取得結果を30分キャッシュし、同一銘柄への重複リクエストを避ける。"""
    return fetch_news(ticker)


st.set_page_config(page_title="株投資リサーチアプリ", layout="wide")

# Claude CLIが利用できない環境ではLLM機能が動作しないため、起動時点でチェックしてアプリを止める
try:
    check_claude_cli_available()
except Exception as exc:
    st.error(str(exc))
    st.stop()

st.sidebar.markdown(DISCLAIMER_NOTICE)

# 5つの主要機能をタブとして構成する
tab_portfolio, tab_screening, tab_backtest, tab_ranking, tab_sector = st.tabs(
    ["ポートフォリオ", "スクリーニング", "バックテスト", "一括バックテスト", "セクターローテーション"]
)


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


def _handle_table_selection(state_key: str, event, df: pd.DataFrame) -> None:
    """データフレーム表の行選択イベントを処理する共通ヘルパー。
    選択行の変化をセッション状態に記録し、新たに選択された銘柄の詳細ダイアログを開く。
    """
    current = event.selection.rows[0] if event.selection.rows else None
    if current != st.session_state.get(state_key):
        st.session_state[state_key] = current
        if current is not None and current < len(df):
            row = df.iloc[current]
            show_stock_detail_dialog(row["ticker"], row.get("name") or "")


with tab_portfolio:
    st.header("保有銘柄ポートフォリオ")

    # 初回表示時は保存済みの保有銘柄をロードし、なければ空行を1つ用意して編集を開始できるようにする
    if "holdings_rows" not in st.session_state:
        st.session_state["holdings_rows"] = load_holdings(HOLDINGS_PATH) or [
            {"ticker": "", "shares": 0, "cost": 0.0}
        ]

    candidate_names = build_candidate_names(
        st.session_state["holdings_rows"], resolve_name=_cached_fetch_japanese_name
    )

    # 銘柄コード/銘柄名で検索し、選択した銘柄を保有一覧に追加するUI
    st.subheader("銘柄を検索して追加")
    search_col, add_col = st.columns([4, 1])
    with search_col:
        search_options = [""] + [
            f"{ticker} {name}" for ticker, name in sorted(candidate_names.items())
        ]
        picked = st.selectbox(
            "銘柄コードまたは銘柄名で検索",
            search_options,
            key="ticker_search_box",
            label_visibility="collapsed",
        )
    with add_col:
        add_clicked = st.button("追加")

    # 選択済み銘柄が一覧になければ保有銘柄リストに追加する（重複追加は防止）
    if add_clicked and picked:
        picked_ticker = picked.split(" ", 1)[0]
        existing_tickers = {row.get("ticker") for row in st.session_state["holdings_rows"]}
        if picked_ticker in existing_tickers:
            st.info(f"{picked_ticker} は既に一覧にあります。")
        else:
            st.session_state["holdings_rows"].append(
                {"ticker": picked_ticker, "shares": 0, "cost": 0.0}
            )

    # 表示用に銘柄名列を付加した編集可能テーブルを構築する
    display_df = pd.DataFrame(st.session_state["holdings_rows"])
    display_df["銘柄名"] = display_df["ticker"].map(
        lambda ticker: candidate_names.get(ticker, "")
    )
    display_df = display_df[["ticker", "銘柄名", "shares", "cost"]]

    edited_df = st.data_editor(
        display_df,
        num_rows="dynamic",
        key="holdings_editor",
        column_config={
            "ticker": st.column_config.TextColumn("銘柄コード"),
            "銘柄名": st.column_config.TextColumn("銘柄名", disabled=True),
            "shares": st.column_config.NumberColumn("保有株数"),
            "cost": st.column_config.NumberColumn("取得単価"),
        },
    )

    holdings = load_holdings(HOLDINGS_PATH)

    # 編集内容をファイルに保存し、セッション状態と表示中の保有銘柄も最新化する
    if st.button("保有銘柄を保存"):
        new_holdings = [
            {"ticker": row["ticker"], "shares": row["shares"], "cost": row["cost"]}
            for row in edited_df.to_dict(orient="records")
            if row.get("ticker")
        ]
        save_holdings(HOLDINGS_PATH, new_holdings)
        st.session_state["holdings_rows"] = new_holdings
        st.success("保存しました。")
        holdings = new_holdings

    # 保有銘柄ごとに詳細ダイアログを開くためのボタン一覧
    if holdings:
        st.subheader("銘柄詳細を見る")
        for i, holding in enumerate(holdings):
            ticker = holding["ticker"]
            name = candidate_names.get(ticker, "")
            col_ticker, col_name, col_button = st.columns([2, 4, 2])
            col_ticker.write(ticker)
            col_name.write(name)
            if col_button.button("詳細", key=f"portfolio_detail_{i}_{ticker}"):
                show_stock_detail_dialog(ticker, name)

    force_regenerate = st.checkbox("キャッシュを無視して再生成する")

    # ポートフォリオ全体のAIレビューを生成する。コストの高いデータ取得・LLM呼び出しを
    # 伴うため、保有銘柄構成から作ったキャッシュキーで結果を再利用できるようにする
    if holdings and st.button("レビューを生成"):
        cache_key = "portfolio-review-" + hashlib.sha256(
            "-".join(f"{h['ticker']}:{h['shares']}:{h['cost']}" for h in holdings).encode("utf-8")
        ).hexdigest()[:12]
        cached_payload = None if force_regenerate else read_cache(CACHE_DIR, cache_key)
        try:
            payload = json.loads(cached_payload) if cached_payload is not None else None
        except json.JSONDecodeError:
            # 旧バージョン（レポート本文のみを保存する形式）のキャッシュは無視して再生成する
            payload = None

        if payload is None:
            current_prices = {}
            price_histories = {}
            fundamentals_by_ticker = {}
            technicals_by_ticker = {}
            news_by_ticker = {}

            def _fetch_holding_data(ticker: str):
                """1銘柄分の株価履歴・ファンダメンタルズ・テクニカル・ニュースをまとめて取得する。
                並列実行（map_concurrently）から呼び出される単位関数。
                """
                history = _cached_fetch_price_history(ticker, "6mo")
                fundamentals = _cached_analyze_fundamentals(ticker)
                technical = analyze_technical(history)
                news = _cached_fetch_news(ticker)
                return history, fundamentals, technical, news

            # 保有銘柄すべてのデータ取得を並列化し、待ち時間を短縮する
            holding_tickers = [holding["ticker"] for holding in holdings]
            with st.spinner("保有銘柄データを取得中..."):
                holding_results = map_concurrently(holding_tickers, _fetch_holding_data)

            # 取得に失敗した銘柄（例外）はレビュー対象から除外する
            for ticker in holding_tickers:
                result = holding_results[ticker]
                if isinstance(result, Exception):
                    continue
                history, fundamentals, technical, news = result
                if not history.empty:
                    current_prices[ticker] = float(history["Close"].iloc[-1])
                    price_histories[ticker] = history["Close"]
                fundamentals_by_ticker[ticker] = fundamentals
                technicals_by_ticker[ticker] = technical
                news_by_ticker[ticker] = news

            # 銘柄ごとのニュースをまとめてLLMに渡し、センチメントを一括判定する
            news_sentiment_by_ticker = research_news_batch(news_by_ticker, call_llm=call_llm)

            report = generate_portfolio_review(
                holdings,
                current_prices,
                price_histories,
                fundamentals_by_ticker,
                technicals_by_ticker,
                news_sentiment_by_ticker,
                names_by_ticker=candidate_names,
                call_llm=call_llm,
            )
            payload = {
                "report": report,
                "news_by_ticker": news_by_ticker,
                "news_sentiment_by_ticker": news_sentiment_by_ticker,
            }
            write_cache(CACHE_DIR, cache_key, json.dumps(payload, ensure_ascii=False))

        st.markdown(payload["report"])

        # センチメント判定の根拠となったニュースを銘柄ごとに折りたたみ表示する
        st.subheader("参照ニュース（センチメント判定の元データ）")
        for holding in holdings:
            ticker = holding["ticker"]
            sentiment_info = payload["news_sentiment_by_ticker"].get(ticker, {})
            sentiment_label = sentiment_info.get("sentiment") or "不明"
            news_items = payload["news_by_ticker"].get(ticker, [])
            with st.expander(f"{ticker} の参照ニュース（センチメント: {sentiment_label}）"):
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

with tab_screening:
    st.header("銘柄スクリーニング")

    condition_text = st.text_input(
        "スクリーニング条件を自然言語で入力してください",
        placeholder="PERが15倍以下で配当利回りが3%以上",
    )

    if condition_text:
        # 入力条件が前回から変わった場合のみLLMを呼び出し、自然言語条件を
        # 構造化フィルタ（JSON）に変換する。変わっていなければ結果をセッションから再利用する
        if st.session_state.get("screening_condition_text") != condition_text:
            prompt = build_screening_prompt(condition_text)
            raw_filters = call_llm(prompt)
            st.session_state["screening_condition_text"] = condition_text
            try:
                st.session_state["screening_filters"] = json.loads(strip_code_fence(raw_filters))
                st.session_state["screening_filters_error"] = False
            except json.JSONDecodeError:
                # LLMの出力が不正なJSONだった場合はエラーとして扱い、フィルタなしにする
                st.session_state["screening_filters"] = None
                st.session_state["screening_filters_error"] = True

        filters = st.session_state.get("screening_filters")
        if st.session_state.get("screening_filters_error"):
            st.error("条件の解釈に失敗しました。条件を言い換えて再度お試しください。")

        if filters is not None:
            # 実際に適用する前にAIが解釈した条件をユーザーに確認させる
            st.subheader("AIが解釈した条件（適用前に確認してください）")
            st.json(filters)

            # ユニバース銘柄のファンダメンタルズを取得し、条件でフィルタしてAIコメントを付与する
            if st.button("この条件で絞り込む"):
                universe_df = fetch_universe_fundamentals(UNIVERSE, CACHE_DIR)
                universe_df["name"] = universe_df["ticker"].map(UNIVERSE_NAMES).fillna(
                    universe_df["name"]
                )
                result_df = apply_filters(universe_df, filters)
                comments = generate_screening_comments(result_df, call_llm=call_llm)

                st.session_state["screening_result_df"] = result_df
                st.session_state["screening_comments"] = comments
                st.session_state["screening_selected_row"] = None
                st.session_state["screening_result_table"] = {
                    "selection": {"rows": [], "columns": []}
                }

    # 絞り込み結果があれば、選択可能な一覧表と銘柄ごとのAIコメントを表示する
    if st.session_state.get("screening_result_df") is not None:
        result_df = st.session_state["screening_result_df"]
        comments = st.session_state["screening_comments"]

        st.subheader(f"絞り込み結果（{len(result_df)}件）")
        st.caption("行をクリックすると銘柄詳細を表示します。")
        event = st.dataframe(
            result_df,
            column_config={
                "ticker": st.column_config.TextColumn("銘柄コード"),
                "name": st.column_config.TextColumn("銘柄名"),
                "per": st.column_config.NumberColumn("PER"),
                "pbr": st.column_config.NumberColumn("PBR"),
                "dividend_yield_pct": st.column_config.NumberColumn("配当利回り(%)"),
                "market_cap": st.column_config.NumberColumn("時価総額"),
            },
            on_select="rerun",
            selection_mode="single-row",
            key="screening_result_table",
        )
        _handle_table_selection("screening_selected_row", event, result_df)

        st.subheader("銘柄ごとのAIコメント")
        for row in result_df.itertuples():
            st.write(
                f"**{row.ticker} {row.name}**: "
                f"{comments.get(row.ticker, 'コメント生成失敗')}"
            )

with tab_backtest:
    st.header("バックテスト")

    # 単一銘柄・単一戦略に対するバックテスト条件の入力
    backtest_strategy = st.selectbox(
        "戦略", list(STRATEGIES.keys()), key="backtest_strategy"
    )
    backtest_ticker = st.text_input(
        "銘柄コード", placeholder="7203.T", key="backtest_ticker"
    )
    backtest_period = st.selectbox(
        "取得期間", ["1y", "3y", "5y"], index=1, key="backtest_period"
    )
    apply_transaction_cost = st.checkbox(
        "取引コストを考慮する（1回あたり0.1%）", key="backtest_cost_checkbox"
    )
    backtest_force_regenerate = st.checkbox(
        "キャッシュを無視して再生成する", key="backtest_force_regenerate"
    )

    if backtest_ticker and st.button("バックテストを実行"):
        strategy = STRATEGIES[backtest_strategy]
        transaction_cost_pct = 0.1 if apply_transaction_cost else 0.0
        history = _cached_fetch_price_history(backtest_ticker, backtest_period)

        # 戦略が要求する最低データ日数を満たさない場合は実行できない旨を伝える
        if history.empty or len(history) < strategy["min_days"]:
            st.error(
                "株価データが取得できないか、バックテストに必要な日数"
                f"（{strategy['min_days']}日）に満たないため実行できません。"
            )
        else:
            prices = history["Close"]

            # 戦略のプリセットパラメータごとに成績を比較する
            comparison = run_backtest_comparison(
                prices, strategy["func"], strategy["presets"], transaction_cost_pct
            )
            comparison_df = pd.DataFrame(comparison).T
            comparison_df.index.name = "パラメータ組"

            st.subheader("パラメータ組ごとの比較")
            st.dataframe(
                comparison_df,
                column_config={
                    "total_return_pct": st.column_config.NumberColumn("累積リターン(%)"),
                    "benchmark_return_pct": st.column_config.NumberColumn("ベンチマーク(%)"),
                    "win_rate_pct": st.column_config.NumberColumn("勝率(%)"),
                    "max_drawdown_pct": st.column_config.NumberColumn("最大DD(%)"),
                    "trade_days": st.column_config.NumberColumn("取引日数"),
                },
            )

            # バックテスト条件（戦略・銘柄・期間・コスト）が同一ならAI解説をキャッシュ再利用する
            cache_key = "backtest-" + hashlib.sha256(
                f"{backtest_strategy}-{backtest_ticker}-{backtest_period}-{transaction_cost_pct}".encode(
                    "utf-8"
                )
            ).hexdigest()[:12]
            cached_explanation = (
                None if backtest_force_regenerate else read_cache(CACHE_DIR, cache_key)
            )

            if cached_explanation is not None:
                explanation = cached_explanation
            else:
                explanation = generate_backtest_explanation(
                    backtest_ticker,
                    prices,
                    backtest_func=strategy["func"],
                    strategy_name=backtest_strategy,
                    presets=strategy["presets"],
                    transaction_cost_pct=transaction_cost_pct,
                )
                write_cache(CACHE_DIR, cache_key, explanation)

            st.markdown(explanation)

with tab_ranking:
    st.header("複数銘柄一括バックテスト・ランキング")
    st.caption(
        "主要銘柄（UNIVERSE）と保有銘柄を対象に、選択した戦略の標準プリセットで"
        "バックテストし、リスク調整済みリターン（累積リターン÷|最大ドローダウン|）の高い順に並べます。"
    )

    ranking_strategy = st.selectbox(
        "戦略", list(STRATEGIES.keys()), key="ranking_strategy"
    )
    ranking_period = st.selectbox(
        "取得期間", ["1y", "3y", "5y"], index=1, key="ranking_period"
    )
    ranking_apply_cost = st.checkbox(
        "取引コストを考慮する（1回あたり0.1%）", key="ranking_cost_checkbox"
    )
    ranking_force_regenerate = st.checkbox(
        "キャッシュを無視して再生成する", key="ranking_force_regenerate"
    )

    if st.button("一括バックテストを実行"):
        strategy = STRATEGIES[ranking_strategy]
        transaction_cost_pct = 0.1 if ranking_apply_cost else 0.0

        # 分析対象はユニバース銘柄と保有銘柄の和集合とする
        holdings = load_holdings(HOLDINGS_PATH)
        holdings_tickers = [h["ticker"] for h in holdings if h.get("ticker")]
        target_tickers = sorted(set(UNIVERSE) | set(holdings_tickers))

        # 戦略・期間・コスト・対象銘柄集合が同一なら結果をキャッシュから再利用する
        cache_key = "universe-backtest-" + hashlib.sha256(
            f"{ranking_strategy}-{ranking_period}-{transaction_cost_pct}-"
            f"{'-'.join(target_tickers)}".encode("utf-8")
        ).hexdigest()[:12]
        cached_payload = None if ranking_force_regenerate else read_cache(CACHE_DIR, cache_key)

        payload = json.loads(cached_payload) if cached_payload is not None else None

        if payload is None:
            prices_by_ticker = {}
            skipped_tickers = []
            # 多数の銘柄の株価取得を並列化して待ち時間を短縮する
            with st.spinner(f"株価データを取得中...（{len(target_tickers)}銘柄）"):
                price_results = map_concurrently(
                    target_tickers,
                    lambda ticker: _cached_fetch_price_history(ticker, ranking_period),
                )
            # データ取得に失敗・不足した銘柄はランキング対象から除外し、後で案内する
            for ticker in target_tickers:
                history = price_results[ticker]
                if isinstance(history, Exception) or history is None or history.empty:
                    skipped_tickers.append(ticker)
                else:
                    prices_by_ticker[ticker] = history["Close"]

            if not prices_by_ticker:
                st.error("バックテスト可能な銘柄がありませんでした。")
                payload = None
            else:
                # 標準プリセット（先頭のパラメータ組）で全銘柄を横並び比較しランキング化する
                standard_label, standard_params = strategy["presets"][0]
                ranking_rows = run_universe_backtest_ranking(
                    prices_by_ticker,
                    strategy["func"],
                    standard_params,
                    transaction_cost_pct=transaction_cost_pct,
                    min_days=strategy["min_days"],
                )
                comments = generate_ranking_comments(ranking_rows[:5], call_llm=call_llm)
                payload = {
                    "ranking_rows": ranking_rows,
                    "skipped_tickers": skipped_tickers,
                    "comments": comments,
                    "preset_label": standard_label,
                }
                write_cache(CACHE_DIR, cache_key, json.dumps(payload, ensure_ascii=False))

        if payload is not None:
            # 再実行後もランキング結果を表示し続けられるようセッションに保持する
            st.session_state["ranking_payload"] = payload
            st.session_state["ranking_strategy_label"] = ranking_strategy
            st.session_state["ranking_selected_row"] = None
            st.session_state["ranking_table"] = {"selection": {"rows": [], "columns": []}}

    if st.session_state.get("ranking_payload") is not None:
        payload = st.session_state["ranking_payload"]
        ranking_strategy_label = st.session_state["ranking_strategy_label"]

        candidate_names = build_candidate_names(
            load_holdings(HOLDINGS_PATH), resolve_name=_cached_fetch_japanese_name
        )
        ranking_df = pd.DataFrame(payload["ranking_rows"])
        ranking_df["name"] = ranking_df["ticker"].map(candidate_names).fillna("")
        ranking_df.insert(0, "順位", range(1, len(ranking_df) + 1))
        ranking_df = ranking_df[
            [
                "順位",
                "ticker",
                "name",
                "total_return_pct",
                "benchmark_return_pct",
                "win_rate_pct",
                "max_drawdown_pct",
                "risk_adjusted_return",
            ]
        ]

        st.subheader(f"{ranking_strategy_label}（{payload['preset_label']}）ランキング")
        st.caption("行をクリックすると銘柄詳細を表示します。")
        event = st.dataframe(
            ranking_df,
            column_config={
                "ticker": st.column_config.TextColumn("銘柄コード"),
                "name": st.column_config.TextColumn("銘柄名"),
                "total_return_pct": st.column_config.NumberColumn("累積リターン(%)"),
                "benchmark_return_pct": st.column_config.NumberColumn("ベンチマーク(%)"),
                "win_rate_pct": st.column_config.NumberColumn("勝率(%)"),
                "max_drawdown_pct": st.column_config.NumberColumn("最大DD(%)"),
                "risk_adjusted_return": st.column_config.NumberColumn("リスク調整済みリターン"),
            },
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="ranking_table",
        )
        _handle_table_selection("ranking_selected_row", event, ranking_df)

        if payload["skipped_tickers"]:
            st.info(
                "データ取得・データ不足によりスキップした銘柄: "
                + ", ".join(payload["skipped_tickers"])
            )

        st.subheader("上位5銘柄のAIコメント")
        for row in payload["ranking_rows"][:5]:
            ticker = row["ticker"]
            st.write(f"**{ticker}**: {payload['comments'].get(ticker, 'コメント生成失敗')}")

        st.markdown(DISCLAIMER_NOTICE)

with tab_sector:
    st.header("セクターローテーション")
    st.caption(
        "UNIVERSE銘柄を17業種に分類し、業種間の値動きの時差相関（リード・ラグ）を"
        "過去の株価データから計算します。あくまで過去の統計的傾向であり、"
        "将来の値動きを保証するものではありません。"
    )

    sector_period = st.selectbox(
        "取得期間", ["6mo", "1y", "2y"], index=1, key="sector_period"
    )
    sector_force_regenerate = st.checkbox(
        "キャッシュを無視して再生成する", key="sector_force_regenerate"
    )

    if st.button("分析を実行"):
        # 取得期間と対象ユニバースが同一なら分析結果をキャッシュから再利用する
        cache_key = "sector-rotation-" + hashlib.sha256(
            f"{sector_period}-{'-'.join(sorted(UNIVERSE))}".encode("utf-8")
        ).hexdigest()[:12]
        cached_payload = (
            None if sector_force_regenerate else read_cache(CACHE_DIR, cache_key)
        )
        payload = json.loads(cached_payload) if cached_payload is not None else None
        if payload is not None and "sector_returns" not in payload:
            # 旧スキーマのキャッシュ（sector_returns未保存）は再計算して移行する
            payload = None

        if payload is None:
            skipped_tickers = []
            prices_by_ticker = {}
            # ユニバース全銘柄の株価取得を並列化して待ち時間を短縮する
            with st.spinner(f"株価データを取得中...（{len(UNIVERSE)}銘柄）"):
                price_results = map_concurrently(
                    UNIVERSE,
                    lambda ticker: _cached_fetch_price_history(ticker, sector_period),
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
                comments = generate_sector_rotation_comments(pairs[:5], call_llm=call_llm)
                payload = {
                    "pairs": pairs,
                    "skipped_tickers": skipped_tickers,
                    "excluded_sectors": excluded_sectors,
                    "comments": comments,
                    "sector_returns": serialize_sector_returns(sector_returns),
                }
                write_cache(CACHE_DIR, cache_key, json.dumps(payload, ensure_ascii=False))

        if payload is not None:
            st.session_state["sector_payload"] = payload

    if st.session_state.get("sector_payload") is not None:
        payload = st.session_state["sector_payload"]
        pairs = payload["pairs"]

        if pairs:
            # 相関ペアの一覧から対称な相関行列（ヒートマップ用）を組み立てる
            sectors = sorted(
                {pair["leading_sector"] for pair in pairs}
                | {pair["lagging_sector"] for pair in pairs}
            )
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

            st.subheader("業種間相関ヒートマップ")
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
                .properties(height=500)
            )
            st.altair_chart(heatmap, width="stretch")

            st.subheader("リード・ラグ上位ペア")
            pairs_df = pd.DataFrame(pairs)[
                ["leading_sector", "lagging_sector", "lag_days", "correlation"]
            ]
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

            st.subheader("相関上位5ペアのAIコメント")
            for pair in pairs[:5]:
                key = f"{pair['leading_sector']}->{pair['lagging_sector']}"
                st.write(
                    f"**{pair['leading_sector']} → {pair['lagging_sector']}**: "
                    f"{payload['comments'].get(key, 'コメント生成失敗')}"
                )
        else:
            st.info("有効な業種ペアがありませんでした。")

        st.subheader("ウェーブレット分析（時間変化するリード・ラグ）")
        st.caption(
            "選択した2つの業種について、値動きの周期の長さ（短期・中期・長期）ごとに、"
            "どちらの業種がどれくらい先行しているかの時間変化を可視化します。"
            "色が薄い部分は関係の確からしさ（コヒーレンス）が低いことを示します。"
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
            with col_a:
                sector_x = st.selectbox(
                    "業種A",
                    sector_options,
                    index=sector_options.index(default_x),
                    key="wavelet_sector_x",
                )
            with col_b:
                sector_y = st.selectbox(
                    "業種B",
                    sector_options,
                    index=sector_options.index(default_y),
                    key="wavelet_sector_y",
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
                        y=alt.Y("period_days:O", title="周期（営業日）", sort="descending"),
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
                    .properties(height=400)
                )
                st.altair_chart(heatmap, width="stretch")

                band = st.selectbox(
                    "周期帯", ["短期", "中期", "長期"], index=1, key="wavelet_band"
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
                    )
                    st.altair_chart(line, width="stretch")

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
