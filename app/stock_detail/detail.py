import json
from pathlib import Path

from analysis_agents.fundamental_agent import (
    analyze_fundamentals as default_analyze_fundamentals,
)
from analysis_agents.technical_agent import analyze_technical as default_analyze_technical
from common.cache import read_cache, write_cache
from data_api.llm_client import call_llm as default_call_llm
from data_api.stock_price_api import fetch_news as default_fetch_news
from data_api.stock_price_api import fetch_price_history as default_fetch_price_history
from prompt_patterns.stock_detail import build_stock_detail_prompt


def generate_stock_detail(
    ticker: str,
    name: str | None,
    cache_dir: Path,
    call_llm=default_call_llm,
    fetch_price_history=default_fetch_price_history,
    fetch_news=default_fetch_news,
    analyze_fundamentals=default_analyze_fundamentals,
    analyze_technical=default_analyze_technical,
) -> dict:
    cache_key = f"stock-detail-{ticker}"
    cached = read_cache(cache_dir, cache_key)
    if cached is not None:
        return json.loads(cached)

    history = fetch_price_history(ticker, period="6mo")
    fundamentals = analyze_fundamentals(ticker)
    technical = analyze_technical(history)
    news = fetch_news(ticker)

    if history.empty:
        price_history = {"dates": [], "open": [], "high": [], "low": [], "close": [], "volume": []}
    else:
        price_history = {
            "dates": [d.isoformat() for d in history.index],
            "open": history["Open"].tolist(),
            "high": history["High"].tolist(),
            "low": history["Low"].tolist(),
            "close": history["Close"].tolist(),
            "volume": history["Volume"].tolist(),
        }

    prompt = build_stock_detail_prompt(ticker, name, fundamentals, technical, news)
    comment = call_llm(prompt)

    payload = {
        "ticker": ticker,
        "name": name,
        "price_history": price_history,
        "fundamentals": fundamentals,
        "technical": technical,
        "news": news,
        "comment": comment,
    }
    write_cache(cache_dir, cache_key, json.dumps(payload, ensure_ascii=False))
    return payload
