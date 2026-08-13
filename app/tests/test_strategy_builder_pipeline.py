import pandas as pd

import strategy_builder.pipeline as pipeline


def test_run_pipeline_applies_steps_in_order(monkeypatch):
    def fake_add_one(candidates_df, params, cache_dir):
        candidates_df = candidates_df.copy()
        candidates_df["value"] = candidates_df.get("value", 0) + params.get("amount", 1)
        return candidates_df

    monkeypatch.setattr(pipeline, "PIPELINE_FUNCTIONS", {"ADD": {"run": fake_add_one}})

    result_df, trace = pipeline.run_pipeline(
        [{"function": "ADD", "params": {"amount": 3}}, {"function": "ADD", "params": {"amount": 2}}],
        ["AAA.T"],
        cache_dir=None,
    )

    assert result_df["value"].iloc[0] == 5
    assert trace == ["開始: 1件", "ADD: 1件→1件", "ADD: 1件→1件"]


def test_run_pipeline_resets_candidates_on_unknown_function():
    result_df, trace = pipeline.run_pipeline(
        [{"function": "UNKNOWN", "params": {}}], ["AAA.T"], cache_dir=None
    )

    assert result_df["ticker"].tolist() == []
    assert trace == ["開始: 1件", "UNKNOWN: 未知の関数のため候補をリセット"]


def test_run_pipeline_resets_candidates_after_retries_exhausted(monkeypatch):
    monkeypatch.setattr(pipeline.time, "sleep", lambda seconds: None)

    def failing_step(candidates_df, params, cache_dir):
        raise ValueError("boom")

    def passthrough_step(candidates_df, params, cache_dir):
        return candidates_df

    monkeypatch.setattr(
        pipeline,
        "PIPELINE_FUNCTIONS",
        {"FAIL": {"run": failing_step}, "PASS": {"run": passthrough_step}},
    )

    result_df, trace = pipeline.run_pipeline(
        [{"function": "FAIL", "params": {}}, {"function": "PASS", "params": {}}],
        ["AAA.T"],
        cache_dir=None,
    )

    assert result_df["ticker"].tolist() == []
    assert trace == [
        "開始: 1件",
        "FAIL: 3回リトライしても失敗のため候補をリセット",
        "PASS: 0件→0件",
    ]


def test_run_pipeline_retries_transient_failure_and_recovers(monkeypatch):
    monkeypatch.setattr(pipeline.time, "sleep", lambda seconds: None)

    attempts = {"count": 0}

    def flaky_step(candidates_df, params, cache_dir):
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise ConnectionError("transient")
        return candidates_df

    monkeypatch.setattr(pipeline, "PIPELINE_FUNCTIONS", {"FLAKY": {"run": flaky_step}})

    result_df, trace = pipeline.run_pipeline(
        [{"function": "FLAKY", "params": {}}], ["AAA.T"], cache_dir=None
    )

    assert attempts["count"] == 2
    assert result_df["ticker"].tolist() == ["AAA.T"]
    assert trace == ["開始: 1件", "FLAKY: 1件→1件"]


def test_run_pipeline_reduces_row_count_across_steps(monkeypatch):
    def keep_first_only(candidates_df, params, cache_dir):
        return candidates_df.head(1)

    monkeypatch.setattr(pipeline, "PIPELINE_FUNCTIONS", {"KEEP_FIRST": {"run": keep_first_only}})

    result_df, trace = pipeline.run_pipeline(
        [{"function": "KEEP_FIRST", "params": {}}], ["AAA.T", "BBB.T"], cache_dir=None
    )

    assert result_df["ticker"].tolist() == ["AAA.T"]
    assert trace == ["開始: 2件", "KEEP_FIRST: 2件→1件"]
