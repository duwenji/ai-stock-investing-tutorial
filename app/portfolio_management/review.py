"""保有ポートフォリオの構成・リスク・個別銘柄情報（ファンダメンタルズ、
テクニカル、ニュースセンチメント）を集約し、LLMによる統合レビュー
レポートを生成するモジュール。portfolio_tab.pyから呼ばれる。
LLM呼び出しには時間・コストがかかるため、呼び出し側（portfolio_tab.py）で
common/cache.pyを使い、Streamlitの再実行のたびに呼び直さないようにしている。"""

from common.disclaimer import DISCLAIMER_NOTICE
from data_api.llm_client import call_llm as default_call_llm
from portfolio_management.composition import analyze_portfolio_composition
from portfolio_management.risk import assess_risk
from prompt_patterns.report_generation import build_report_prompt


def build_holding_snapshot(
    holding: dict, fundamentals: dict, technical: dict, news_sentiment: dict, name: str = None
) -> dict:
    """1銘柄分のレビュー用スナップショットを組み立てる。LLMへの入力材料
    となる、保有情報・ファンダメンタルズ・テクニカル・ニュースの要点のみを
    抜き出して1つの辞書にまとめる。"""
    return {
        "ticker": holding["ticker"],
        "name": name,
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
    names_by_ticker: dict[str, str] | None = None,
    call_llm=default_call_llm,
) -> str:
    """ポートフォリオの構成・リスク・銘柄別情報を集約したファクトを
    LLMに渡し、統合レビューレポート（Markdown）を生成する。
    免責事項を先頭と末尾に必ず付与する。

    call_llmはテスト時にダミー関数へ差し替えるための引数（デフォルトは本物のLLM呼び出し）。"""
    names_by_ticker = names_by_ticker or {}
    composition = analyze_portfolio_composition(holdings, current_prices)
    # 各保有銘柄の構成情報に銘柄名を補完する。
    for row in composition["holdings"]:
        row["name"] = names_by_ticker.get(row["ticker"])

    risk = assess_risk(price_histories)
    snapshots = [
        build_holding_snapshot(
            holding,
            fundamentals_by_ticker.get(holding["ticker"], {}),
            technicals_by_ticker.get(holding["ticker"], {}),
            news_sentiment_by_ticker.get(holding["ticker"], {}),
            names_by_ticker.get(holding["ticker"]),
        )
        for holding in holdings
    ]

    # LLMに渡す「事実（facts）」として、構成・リスク・銘柄詳細を1つにまとめる。
    # 銘柄名は composition["holdings"] と holdings の各 name フィールドに
    # 既に含まれているため、重複を避けるためここでは含めない（トークン節約）。
    facts = {
        "composition": composition,
        "risk": risk,
        "holdings": snapshots,
    }
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
