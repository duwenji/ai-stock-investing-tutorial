import pandas as pd

from common.disclaimer import DISCLAIMER_NOTICE
from portfolio_management.review import build_holding_snapshot, generate_portfolio_review


def test_build_holding_snapshot_combines_all_sources():
    holding = {"ticker": "AAA.T", "shares": 100, "cost": 1000.0}
    fundamentals = {"per": 12.0, "pbr": 1.1}
    technical = {"signal": "強気"}
    news_sentiment = {"sentiment": "ポジティブ", "confidence": 0.7}

    snapshot = build_holding_snapshot(holding, fundamentals, technical, news_sentiment)

    assert snapshot == {
        "ticker": "AAA.T",
        "shares": 100,
        "cost": 1000.0,
        "per": 12.0,
        "pbr": 1.1,
        "technical_signal": "強気",
        "news_sentiment": "ポジティブ",
        "news_confidence": 0.7,
    }


def test_generate_portfolio_review_includes_disclaimer_and_commentary():
    holdings = [{"ticker": "AAA.T", "shares": 100, "cost": 1000.0}]
    current_prices = {"AAA.T": 1100.0}
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    price_histories = {"AAA.T": pd.Series([100, 101, 102, 103, 104], index=dates)}
    fundamentals_by_ticker = {"AAA.T": {"per": 12.0, "pbr": 1.1}}
    technicals_by_ticker = {"AAA.T": {"signal": "強気"}}
    news_sentiment_by_ticker = {"AAA.T": {"sentiment": "ポジティブ", "confidence": 0.7}}

    fake_call_llm = lambda prompt: "テスト用の考察文です。"

    report = generate_portfolio_review(
        holdings,
        current_prices,
        price_histories,
        fundamentals_by_ticker,
        technicals_by_ticker,
        news_sentiment_by_ticker,
        call_llm=fake_call_llm,
    )

    assert report.count(DISCLAIMER_NOTICE) == 2
    assert "テスト用の考察文です。" in report
