import pandas as pd

from prompt_patterns.wavelet_explanation import (
    build_wavelet_prompt,
    generate_wavelet_explanation,
)


def _snapshot(lag_days: float = 3.2, avg_coherence: float = 0.62) -> dict:
    return {
        "date": pd.Timestamp("2026-07-24"),
        "dominant_lag_days": lag_days,
        "avg_coherence": avg_coherence,
    }


def test_build_wavelet_prompt_includes_snapshot_data_and_no_directive_language():
    prompt = build_wavelet_prompt("電機・精密", "機械", "中期", _snapshot())

    assert "電機・精密" in prompt
    assert "機械" in prompt
    assert "中期" in prompt
    assert "2026-07-24" in prompt
    assert "3.2" in prompt
    assert "0.62" in prompt
    assert "過去" in prompt
    assert "将来" in prompt
    assert "売買" in prompt


def test_build_wavelet_prompt_negative_lag_swaps_leading_sector():
    prompt = build_wavelet_prompt("電機・精密", "機械", "中期", _snapshot(lag_days=-4.0))

    assert "機械が電機・精密に先行" in prompt


def test_generate_wavelet_explanation_returns_stripped_llm_output():
    fake_call_llm = lambda prompt: "  先行して動く傾向があります。  \n"

    result = generate_wavelet_explanation(
        "電機・精密", "機械", "中期", _snapshot(), call_llm=fake_call_llm
    )

    assert result == "先行して動く傾向があります。"
