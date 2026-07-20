from prompt_patterns.stock_detail import build_stock_detail_prompt


def test_build_stock_detail_prompt_includes_ticker_name_and_facts():
    fundamentals = {"per": 12.0, "pbr": 1.1, "dividend_yield": 2.5}
    technical = {"signal": "強気"}
    news = [{"title": "好決算を発表", "publisher": "日経", "link": "https://example.com/1"}]

    prompt = build_stock_detail_prompt("AAA.T", "エーエー株式会社", fundamentals, technical, news)

    assert "AAA.T" in prompt
    assert "エーエー株式会社" in prompt
    assert "12.0" in prompt
    assert "1.1" in prompt
    assert "2.5" in prompt
    assert "強気" in prompt
    assert "好決算を発表" in prompt


def test_build_stock_detail_prompt_omits_name_when_none():
    prompt = build_stock_detail_prompt("AAA.T", None, {}, {}, [])
    assert "AAA.T" in prompt
    assert "（None）" not in prompt


def test_build_stock_detail_prompt_shows_placeholder_when_no_news():
    prompt = build_stock_detail_prompt("AAA.T", "エーエー株式会社", {}, {}, [])
    assert "(ニュースなし)" in prompt


def test_build_stock_detail_prompt_instructs_no_directive_language():
    prompt = build_stock_detail_prompt("AAA.T", "エーエー株式会社", {}, {}, [])
    assert "断定的な売買判断" in prompt
