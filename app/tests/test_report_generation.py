from prompt_patterns.report_generation import build_report_prompt


def test_build_report_prompt_includes_facts_and_no_advice_instruction():
    # 免責文言（DISCLAIMER_NOTICE）は表示用レポート側（review.py）で別途付与されるため、
    # LLM向けプロンプトには含めずトークンを節約する。
    facts = {"composition": {"total_value": 100000}}
    prompt = build_report_prompt(facts)
    assert "100000" in prompt
    assert "売買の推奨" in prompt


def test_build_report_prompt_instructs_ticker_name_format():
    facts = {"composition": {"total_value": 100000}}
    prompt = build_report_prompt(facts)
    assert "銘柄コード（銘柄名）" in prompt
