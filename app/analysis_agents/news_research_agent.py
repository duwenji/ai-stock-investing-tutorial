import json

from data_api.llm_client import call_llm as default_call_llm


def build_news_sentiment_prompt(news_by_ticker: dict[str, list[dict]]) -> str:
    lines = [
        "以下は銘柄ごとの直近ニュース見出しです。",
        "各銘柄のニュースセンチメントを判定してください。",
        "出力は次の形式のJSONのみとしてください（説明文・コードブロック記法は不要です）。",
        '{"<ticker>": {"sentiment": "ポジティブ|ニュートラル|ネガティブ", "confidence": 0.0〜1.0}}',
        "",
    ]
    for ticker, items in news_by_ticker.items():
        titles = "\n".join(f"- {item['title']}" for item in items) or "- (ニュースなし)"
        lines.append(f"## {ticker}\n{titles}\n")
    return "\n".join(lines)


def research_news_batch(
    news_by_ticker: dict[str, list[dict]], call_llm=default_call_llm
) -> dict[str, dict]:
    prompt = build_news_sentiment_prompt(news_by_ticker)
    raw = call_llm(prompt)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {}

    return {
        ticker: result.get(ticker, {"sentiment": None, "confidence": None})
        for ticker in news_by_ticker
    }
