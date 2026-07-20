# 複数銘柄のニュース見出しをまとめてLLMに渡し、銘柄ごとのニュースセンチメントを
# 一括判定させるエージェント。個別にAPI呼び出しするより効率的にセンチメントを得られる。
import json

from common.json_parsing import strip_code_fence
from data_api.llm_client import call_llm as default_call_llm


def build_news_sentiment_prompt(news_by_ticker: dict[str, list[dict]]) -> str:
    # 全銘柄分のニュース見出しを1つのプロンプトにまとめてバッチ処理し、
    # 後段でticker単位にパースできるようJSON形式での出力を指示する。
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
        result = json.loads(strip_code_fence(raw))
    except json.JSONDecodeError:
        # LLM応答が不正な場合は空の結果として扱い、以降のフォールバック処理に委ねる。
        result = {}

    # LLMが一部の銘柄について結果を返さなかった場合でも、
    # 呼び出し元が全銘柄分のキーを期待できるようNoneで埋めて補完する。
    return {
        ticker: result.get(ticker, {"sentiment": None, "confidence": None})
        for ticker in news_by_ticker
    }
