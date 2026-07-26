"""ポートフォリオタブ: 保有銘柄の管理とAIレビュー生成。"""

import hashlib
import json

import pandas as pd
import streamlit as st

from analysis_agents.news_research_agent import research_news_batch
from analysis_agents.technical_agent import analyze_technical
from common.cache import read_cache, write_cache
from common.concurrency import map_concurrently
from data_api.llm_client import call_llm
from portfolio_management.review import generate_portfolio_review
from portfolio_management.storage import load_holdings, save_holdings
from portfolio_management.ticker_names import build_candidate_names

from app_tabs.shared import (
    CACHE_DIR,
    HOLDINGS_PATH,
    cached_analyze_fundamentals,
    cached_fetch_japanese_name,
    cached_fetch_news,
    cached_fetch_price_history,
    show_stock_detail_dialog,
)


def render_portfolio_tab() -> None:
    st.header("保有銘柄ポートフォリオ")

    # 初回表示時は保存済みの保有銘柄をロードし、なければ空行を1つ用意して編集を開始できるようにする
    if "holdings_rows" not in st.session_state:
        st.session_state["holdings_rows"] = load_holdings(HOLDINGS_PATH) or [
            {"ticker": "", "shares": 0, "cost": 0.0}
        ]

    candidate_names = build_candidate_names(
        st.session_state["holdings_rows"], resolve_name=cached_fetch_japanese_name
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

    st.caption(
        "銘柄を削除するには、行左端のチェックボックスで対象行を選択してから "
        "キーボードの Delete キー（または行選択時に表示されるゴミ箱アイコン）を押してください。"
        "削除後は「保有銘柄を保存」ボタンを押すと確定します。"
    )
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

    # 保有銘柄から選んで詳細ダイアログを開く
    if holdings:
        st.subheader("銘柄詳細を見る")
        detail_options = [
            f"{holding['ticker']} {candidate_names.get(holding['ticker'], '')}"
            for holding in holdings
        ]
        detail_col, button_col = st.columns([4, 1])
        with detail_col:
            picked_detail = st.selectbox(
                "詳細を見る銘柄を選択",
                detail_options,
                key="portfolio_detail_select",
                label_visibility="collapsed",
            )
        with button_col:
            if st.button("詳細", key="portfolio_detail_button") and picked_detail:
                detail_ticker = picked_detail.split(" ", 1)[0]
                show_stock_detail_dialog(detail_ticker, candidate_names.get(detail_ticker, ""))

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
                history = cached_fetch_price_history(ticker, "6mo")
                fundamentals = cached_analyze_fundamentals(ticker)
                technical = analyze_technical(history)
                news = cached_fetch_news(ticker)
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
