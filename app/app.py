import hashlib
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from analysis_agents.fundamental_agent import analyze_fundamentals
from analysis_agents.news_research_agent import research_news_batch
from analysis_agents.technical_agent import analyze_technical
from common.cache import read_cache, write_cache
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
from screening.universe import UNIVERSE, UNIVERSE_NAMES

DATA_DIR = Path(__file__).parent / "data"
HOLDINGS_PATH = DATA_DIR / "holdings.json"
CACHE_DIR = DATA_DIR / "cache"


@st.cache_data(ttl=60 * 60 * 24)
def _cached_fetch_japanese_name(ticker: str) -> str | None:
    return fetch_japanese_name(ticker)


st.set_page_config(page_title="株投資リサーチアプリ", layout="wide")

try:
    check_claude_cli_available()
except Exception as exc:
    st.error(str(exc))
    st.stop()

st.sidebar.markdown(DISCLAIMER_NOTICE)

tab_portfolio, tab_screening, tab_backtest, tab_ranking = st.tabs(
    ["ポートフォリオ", "スクリーニング", "バックテスト", "一括バックテスト"]
)

with tab_portfolio:
    st.header("保有銘柄ポートフォリオ")

    if "holdings_rows" not in st.session_state:
        st.session_state["holdings_rows"] = load_holdings(HOLDINGS_PATH) or [
            {"ticker": "", "shares": 0, "cost": 0.0}
        ]

    candidate_names = build_candidate_names(
        st.session_state["holdings_rows"], resolve_name=_cached_fetch_japanese_name
    )

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

    if add_clicked and picked:
        picked_ticker = picked.split(" ", 1)[0]
        existing_tickers = {row.get("ticker") for row in st.session_state["holdings_rows"]}
        if picked_ticker in existing_tickers:
            st.info(f"{picked_ticker} は既に一覧にあります。")
        else:
            st.session_state["holdings_rows"].append(
                {"ticker": picked_ticker, "shares": 0, "cost": 0.0}
            )

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

    force_regenerate = st.checkbox("キャッシュを無視して再生成する")

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

            for holding in holdings:
                ticker = holding["ticker"]
                history = fetch_price_history(ticker, period="6mo")
                if not history.empty:
                    current_prices[ticker] = float(history["Close"].iloc[-1])
                    price_histories[ticker] = history["Close"]
                fundamentals_by_ticker[ticker] = analyze_fundamentals(ticker)
                technicals_by_ticker[ticker] = analyze_technical(history)
                news_by_ticker[ticker] = fetch_news(ticker)

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
        prompt = build_screening_prompt(condition_text)
        raw_filters = call_llm(prompt)
        filters = None
        try:
            filters = json.loads(strip_code_fence(raw_filters))
        except json.JSONDecodeError:
            st.error("条件の解釈に失敗しました。条件を言い換えて再度お試しください。")

        if filters is not None:
            st.subheader("AIが解釈した条件（適用前に確認してください）")
            st.json(filters)

            if st.button("この条件で絞り込む"):
                universe_df = fetch_universe_fundamentals(UNIVERSE, CACHE_DIR)
                universe_df["name"] = universe_df["ticker"].map(UNIVERSE_NAMES).fillna(
                    universe_df["name"]
                )
                result_df = apply_filters(universe_df, filters)

                st.subheader(f"絞り込み結果（{len(result_df)}件）")
                st.dataframe(
                    result_df,
                    column_config={
                        "ticker": st.column_config.TextColumn("銘柄コード"),
                        "name": st.column_config.TextColumn("銘柄名"),
                        "per": st.column_config.NumberColumn("PER"),
                        "pbr": st.column_config.NumberColumn("PBR"),
                        "dividend_yield_pct": st.column_config.NumberColumn("配当利回り(%)"),
                        "market_cap": st.column_config.NumberColumn("時価総額"),
                    },
                )

                comments = generate_screening_comments(result_df, call_llm=call_llm)
                st.subheader("銘柄ごとのAIコメント")
                for row in result_df.itertuples():
                    st.write(
                        f"**{row.ticker} {row.name}**: "
                        f"{comments.get(row.ticker, 'コメント生成失敗')}"
                    )

with tab_backtest:
    st.header("バックテスト")

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
        history = fetch_price_history(backtest_ticker, period=backtest_period)

        if history.empty or len(history) < strategy["min_days"]:
            st.error(
                "株価データが取得できないか、バックテストに必要な日数"
                f"（{strategy['min_days']}日）に満たないため実行できません。"
            )
        else:
            prices = history["Close"]

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

        holdings = load_holdings(HOLDINGS_PATH)
        holdings_tickers = [h["ticker"] for h in holdings if h.get("ticker")]
        target_tickers = sorted(set(UNIVERSE) | set(holdings_tickers))

        cache_key = "universe-backtest-" + hashlib.sha256(
            f"{ranking_strategy}-{ranking_period}-{transaction_cost_pct}-"
            f"{'-'.join(target_tickers)}".encode("utf-8")
        ).hexdigest()[:12]
        cached_payload = None if ranking_force_regenerate else read_cache(CACHE_DIR, cache_key)

        payload = json.loads(cached_payload) if cached_payload is not None else None

        if payload is None:
            prices_by_ticker = {}
            skipped_tickers = []
            progress = st.progress(0.0, text="株価データを取得中...")
            for i, ticker in enumerate(target_tickers):
                try:
                    history = fetch_price_history(ticker, period=ranking_period)
                except Exception:
                    skipped_tickers.append(ticker)
                    history = None
                if history is not None and not history.empty:
                    prices_by_ticker[ticker] = history["Close"]
                else:
                    if ticker not in skipped_tickers:
                        skipped_tickers.append(ticker)
                progress.progress(
                    (i + 1) / len(target_tickers),
                    text=f"株価データを取得中... ({i + 1}/{len(target_tickers)})",
                )
            progress.empty()

            if not prices_by_ticker:
                st.error("バックテスト可能な銘柄がありませんでした。")
                payload = None
            else:
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

            st.subheader(f"{ranking_strategy}（{payload['preset_label']}）ランキング")
            st.dataframe(
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
            )

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
