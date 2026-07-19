from common.disclaimer import DISCLAIMER_NOTICE
from prompt_patterns.report_generation import build_report_prompt


def test_build_report_prompt_includes_facts_and_disclaimer():
    facts = {"composition": {"total_value": 100000}}
    prompt = build_report_prompt(facts)
    assert "100000" in prompt
    assert DISCLAIMER_NOTICE in prompt
    assert "売買の推奨" in prompt
