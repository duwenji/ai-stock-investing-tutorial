from pathlib import Path

import pandas as pd
import streamlit as st

from analysis_agents.fundamental_agent import analyze_fundamentals
from analysis_agents.news_research_agent import research_news_batch
from analysis_agents.technical_agent import analyze_technical
from common.cache import read_cache, write_cache
from common.disclaimer import DISCLAIMER_NOTICE
from data_api.llm_client import call_llm, check_claude_cli_available
from data_api.stock_price_api import fetch_news, fetch_price_history
from portfolio_management.review import generate_portfolio_review
from portfolio_management.storage import load_holdings, save_holdings

DATA_DIR = Path(__file__).parent / "data"
HOLDINGS_PATH = DATA_DIR / "holdings.json"
CACHE_DIR = DATA_DIR / "cache"

st.set_page_config(page_title="株投資リサーチアプリ", layout="wide")

try:
    check_claude_cli_available()
except Exception as exc:
    st.error(str(exc))
    st.stop()

st.sidebar.markdown(DISCLAIMER_NOTICE)

tab_portfolio, tab_screening = st.tabs(["ポートフォリオ", "スクリーニング"])

with tab_portfolio:
    st.header("保有銘柄ポートフォリオ")

    holdings = load_holdings(HOLDINGS_PATH)
    holdings_df = pd.DataFrame(holdings or [{"ticker": "", "shares": 0, "cost": 0.0}])
    edited_df = st.data_editor(holdings_df, num_rows="dynamic", key="holdings_editor")

    if st.button("保有銘柄を保存"):
        new_holdings = [
            row for row in edited_df.to_dict(orient="records") if row.get("ticker")
        ]
        save_holdings(HOLDINGS_PATH, new_holdings)
        st.success("保存しました。")
        holdings = new_holdings

    force_regenerate = st.checkbox("キャッシュを無視して再生成する")

    if holdings and st.button("レビューを生成"):
        cache_key = "portfolio-review-" + "-".join(
            f"{h['ticker']}:{h['shares']}:{h['cost']}" for h in holdings
        )
        cached_report = None if force_regenerate else read_cache(CACHE_DIR, cache_key)

        if cached_report is not None:
            report = cached_report
        else:
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
                call_llm=call_llm,
            )
            write_cache(CACHE_DIR, cache_key, report)

        st.markdown(report)

with tab_screening:
    st.info("準備中です。")
