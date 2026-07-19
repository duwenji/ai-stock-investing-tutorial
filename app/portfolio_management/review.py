from common.disclaimer import DISCLAIMER_NOTICE
from data_api.llm_client import call_llm as default_call_llm
from portfolio_management.composition import analyze_portfolio_composition
from portfolio_management.risk import assess_risk
from prompt_patterns.report_generation import build_report_prompt


def build_holding_snapshot(
    holding: dict, fundamentals: dict, technical: dict, news_sentiment: dict
) -> dict:
    return {
        "ticker": holding["ticker"],
        "shares": holding["shares"],
        "cost": holding["cost"],
        "per": fundamentals.get("per"),
        "pbr": fundamentals.get("pbr"),
        "technical_signal": technical.get("signal"),
        "news_sentiment": news_sentiment.get("sentiment"),
        "news_confidence": news_sentiment.get("confidence"),
    }


def generate_portfolio_review(
    holdings: list[dict],
    current_prices: dict[str, float],
    price_histories: dict,
    fundamentals_by_ticker: dict[str, dict],
    technicals_by_ticker: dict[str, dict],
    news_sentiment_by_ticker: dict[str, dict],
    call_llm=default_call_llm,
) -> str:
    composition = analyze_portfolio_composition(holdings, current_prices)
    risk = assess_risk(price_histories)
    snapshots = [
        build_holding_snapshot(
            holding,
            fundamentals_by_ticker.get(holding["ticker"], {}),
            technicals_by_ticker.get(holding["ticker"], {}),
            news_sentiment_by_ticker.get(holding["ticker"], {}),
        )
        for holding in holdings
    ]

    facts = {"composition": composition, "risk": risk, "holdings": snapshots}
    prompt = build_report_prompt(facts)
    commentary = call_llm(prompt)

    sections = [
        DISCLAIMER_NOTICE,
        "",
        "# ポートフォリオ統合レビュー",
        "",
        commentary,
        "",
        "---",
        "",
        DISCLAIMER_NOTICE,
    ]
    return "\n".join(sections)
