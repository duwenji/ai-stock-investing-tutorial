from prompt_patterns.qa_routing import (
    build_fundamental_answer_prompt,
    build_general_answer_prompt,
    build_news_answer_prompt,
    build_portfolio_answer_prompt,
    build_technical_answer_prompt,
    classify_question,
)


def test_classify_question_returns_llm_label_when_known():
    fake_call_llm = lambda prompt: "technical"
    result = classify_question("移動平均はどうなってる？", call_llm=fake_call_llm)
    assert result == "technical"


def test_classify_question_falls_back_to_general_on_unknown_label():
    fake_call_llm = lambda prompt: "unknown_category"
    result = classify_question("よく分からない質問", call_llm=fake_call_llm)
    assert result == "general"


def test_classify_question_falls_back_to_general_on_empty_response():
    fake_call_llm = lambda prompt: "  "
    result = classify_question("質問", call_llm=fake_call_llm)
    assert result == "general"


def test_classify_question_strips_whitespace_from_label():
    fake_call_llm = lambda prompt: "  fundamental  \n"
    result = classify_question("PERは高い？", call_llm=fake_call_llm)
    assert result == "fundamental"


def test_build_fundamental_answer_prompt_includes_facts_and_question():
    prompt = build_fundamental_answer_prompt(
        "この銘柄は割安？", {"per": 12.0, "pbr": 1.1, "dividend_yield": 3.2}
    )
    assert "12.0" in prompt
    assert "1.1" in prompt
    assert "この銘柄は割安？" in prompt
    assert "断定的な売買判断" in prompt


def test_build_technical_answer_prompt_includes_facts_and_question():
    prompt = build_technical_answer_prompt(
        "上昇トレンド？", {"ma_short": 2500.0, "ma_long": 2400.0, "signal": "強気"}
    )
    assert "強気" in prompt
    assert "上昇トレンド？" in prompt
    assert "断定的な売買判断" in prompt


def test_build_news_answer_prompt_includes_headlines():
    prompt = build_news_answer_prompt(
        "最近のニュースは？", [{"title": "好決算を発表", "publisher": "X"}]
    )
    assert "好決算を発表" in prompt
    assert "最近のニュースは？" in prompt


def test_build_news_answer_prompt_handles_empty_news():
    prompt = build_news_answer_prompt("最近のニュースは？", [])
    assert "ニュースなし" in prompt


def test_build_news_answer_prompt_includes_summary_when_present():
    prompt = build_news_answer_prompt(
        "最近のニュースは？",
        [{"title": "好決算を発表", "publisher": "X", "summary": "Sales grew 20%."}],
    )
    assert "要約: Sales grew 20%." in prompt


def test_build_news_answer_prompt_omits_summary_line_when_absent():
    prompt = build_news_answer_prompt(
        "最近のニュースは？", [{"title": "好決算を発表", "publisher": "X"}]
    )
    assert "要約:" not in prompt


def test_build_portfolio_answer_prompt_includes_composition_and_risk():
    composition = {"holdings": [{"ticker": "AAA", "weight_pct": 40.0}], "total_value": 100000.0}
    risk = {"portfolio_volatility_pct": 18.5}
    prompt = build_portfolio_answer_prompt("リスクは高い？", composition, risk)
    assert "40.0" in prompt
    assert "18.5" in prompt
    assert "リスクは高い？" in prompt


def test_build_general_answer_prompt_includes_question():
    prompt = build_general_answer_prompt("PERとは何ですか？")
    assert "PERとは何ですか？" in prompt
    assert "断定的な" in prompt
