from analysis_agents.news_research_agent import (
    build_news_sentiment_prompt,
    research_news_batch,
)


def test_build_news_sentiment_prompt_includes_ticker_and_titles():
    news_by_ticker = {"AAA.T": [{"title": "好決算", "publisher": "X"}]}
    prompt = build_news_sentiment_prompt(news_by_ticker)
    assert "AAA.T" in prompt
    assert "好決算" in prompt


def test_research_news_batch_parses_json_response():
    news_by_ticker = {"AAA.T": [{"title": "好決算", "publisher": "X"}]}
    fake_call_llm = lambda prompt: (
        '{"AAA.T": {"sentiment": "ポジティブ", "confidence": 0.7}}'
    )
    result = research_news_batch(news_by_ticker, call_llm=fake_call_llm)
    assert result["AAA.T"]["sentiment"] == "ポジティブ"
    assert result["AAA.T"]["confidence"] == 0.7


def test_research_news_batch_fallback_on_invalid_json():
    news_by_ticker = {"AAA.T": []}
    result = research_news_batch(news_by_ticker, call_llm=lambda prompt: "not json")
    assert result["AAA.T"]["sentiment"] is None
    assert result["AAA.T"]["confidence"] is None


def test_research_news_batch_strips_code_fence():
    news_by_ticker = {"AAA.T": [{"title": "好決算", "publisher": "X"}]}
    fake_call_llm = lambda prompt: (
        '```json\n{"AAA.T": {"sentiment": "ポジティブ", "confidence": 0.7}}\n```'
    )
    result = research_news_batch(news_by_ticker, call_llm=fake_call_llm)
    assert result["AAA.T"]["sentiment"] == "ポジティブ"
