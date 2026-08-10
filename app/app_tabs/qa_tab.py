"""AI質問箱タブ: 自由記述の投資質問をカテゴリに応じて既存の分析エージェント
へ振り分けて回答する（Routingパターン）。"""

import logging

import streamlit as st

from analysis_agents.technical_agent import analyze_technical
from common.disclaimer import DISCLAIMER_NOTICE
from data_api.llm_client import call_llm
from portfolio_management.composition import analyze_portfolio_composition
from portfolio_management.risk import assess_risk
from portfolio_management.storage import load_holdings
from prompt_patterns.qa_routing import (
    build_fundamental_answer_prompt,
    build_general_answer_prompt,
    build_news_answer_prompt,
    build_portfolio_answer_prompt,
    build_technical_answer_prompt,
    classify_question,
)

from app_tabs.shared import (
    DEFAULT_USER_ID,
    cached_analyze_fundamentals,
    cached_fetch_news,
    cached_fetch_price_history,
)

logger = logging.getLogger(__name__)

_CATEGORY_LABELS = {
    "fundamental": "ファンダメンタルズ",
    "technical": "テクニカル",
    "news": "ニュース",
    "portfolio": "ポートフォリオ全体",
    "general": "一般的な質問",
}


def _build_portfolio_facts() -> tuple[dict, dict] | None:
    """保有銘柄一覧から構成比・リスク指標を計算する。保有銘柄が無ければNoneを返す。"""
    holdings = load_holdings(DEFAULT_USER_ID)
    if not holdings:
        return None

    current_prices: dict[str, float] = {}
    price_histories: dict = {}
    for holding in holdings:
        history = cached_fetch_price_history(holding["ticker"], "6mo")
        if not history.empty:
            current_prices[holding["ticker"]] = float(history["Close"].iloc[-1])
            price_histories[holding["ticker"]] = history["Close"]

    composition = analyze_portfolio_composition(holdings, current_prices)
    risk = assess_risk(price_histories)
    return composition, risk


def render_qa_tab() -> None:
    logger.info("AI質問箱タブを表示")
    st.header("AI投資質問箱")
    st.caption(
        "自由な言葉で投資に関する質問を入力してください。個別銘柄について"
        "聞く場合は銘柄コードも入力してください。"
    )

    ticker = st.text_input("銘柄コード（任意）", placeholder="7203.T", key="qa_ticker")
    question = st.text_area(
        "質問", placeholder="この銘柄は割安ですか？", key="qa_question"
    )

    if not st.button("質問する", disabled=not question):
        return

    with st.spinner("質問を分類しています..."):
        category = classify_question(question, call_llm=call_llm)

    note = None
    if category in ("fundamental", "technical", "news") and not ticker:
        note = "個別銘柄について聞く場合は銘柄コードを入力してください。一般的な回答を表示します。"
        category = "general"

    with st.spinner("回答を生成しています..."):
        if category == "fundamental":
            fundamentals = cached_analyze_fundamentals(ticker)
            prompt = build_fundamental_answer_prompt(question, fundamentals)
        elif category == "technical":
            history = cached_fetch_price_history(ticker, "6mo")
            technical = analyze_technical(history)
            prompt = build_technical_answer_prompt(question, technical)
        elif category == "news":
            news = cached_fetch_news(ticker)
            prompt = build_news_answer_prompt(question, news)
        elif category == "portfolio":
            facts = _build_portfolio_facts()
            if facts is None:
                st.info("保有銘柄が未登録です。ポートフォリオタブで銘柄を追加してください。")
                return
            composition, risk = facts
            prompt = build_portfolio_answer_prompt(question, composition, risk)
        else:
            prompt = build_general_answer_prompt(question)

        answer = call_llm(prompt)

    st.subheader(f"分類: {_CATEGORY_LABELS.get(category, category)}")
    if note:
        st.caption(note)
    st.write(answer)
    st.markdown(DISCLAIMER_NOTICE)
