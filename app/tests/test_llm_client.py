import logging
import subprocess

import pytest
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from data_api.llm_client import (
    ClaudeCLIError,
    ClaudeCLINotFoundError,
    _get_provider,
    _get_secret,
    call_llm,
    check_claude_cli_available,
)


def test_call_llm_returns_stdout_on_success(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "claude-executable")

    def fake_run(args, input, capture_output, text, encoding, timeout):
        assert args[0] == "claude-executable"
        assert args[-1] == "-p"
        assert "--system-prompt" in args
        assert input == "hello"
        return subprocess.CompletedProcess(args, 0, stdout="response text\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert call_llm("hello") == "response text"


def test_call_llm_raises_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "claude-executable")

    def fake_run(args, input, capture_output, text, encoding, timeout):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ClaudeCLIError):
        call_llm("hello")


def test_call_llm_raises_when_cli_not_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(ClaudeCLINotFoundError):
        call_llm("hello")


def test_check_claude_cli_available_raises_when_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(ClaudeCLINotFoundError):
        check_claude_cli_available()


def test_check_claude_cli_available_passes_when_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/claude")
    check_claude_cli_available()


def test_call_llm_logs_duration_on_success(monkeypatch, caplog):
    monkeypatch.setattr("shutil.which", lambda name: "claude-executable")

    def fake_run(args, input, capture_output, text, encoding, timeout):
        return subprocess.CompletedProcess(args, 0, stdout="response text\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with caplog.at_level(logging.INFO, logger="data_api.llm_client"):
        call_llm("hello")

    assert "Claude CLI呼び出し" in caplog.text
    assert "を開始" in caplog.text
    assert "が完了しました" in caplog.text


def test_call_llm_logs_failure_on_nonzero_exit(monkeypatch, caplog):
    monkeypatch.setattr("shutil.which", lambda name: "claude-executable")

    def fake_run(args, input, capture_output, text, encoding, timeout):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with caplog.at_level(logging.INFO, logger="data_api.llm_client"):
        with pytest.raises(ClaudeCLIError):
            call_llm("hello")

    assert "が失敗しました" in caplog.text


def test_call_llm_logs_request_and_response_content(monkeypatch, caplog):
    monkeypatch.setattr("shutil.which", lambda name: "claude-executable")

    def fake_run(args, input, capture_output, text, encoding, timeout):
        return subprocess.CompletedProcess(args, 0, stdout="response text\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with caplog.at_level(logging.INFO, logger="data_api.llm_client"):
        call_llm("this is the prompt content")

    assert "Claude CLIリクエスト: this is the prompt content" in caplog.text
    assert "Claude CLIレスポンス: response text" in caplog.text


def test_call_llm_does_not_log_response_on_failure(monkeypatch, caplog):
    monkeypatch.setattr("shutil.which", lambda name: "claude-executable")

    def fake_run(args, input, capture_output, text, encoding, timeout):
        return subprocess.CompletedProcess(
            args, 1, stdout="should not be logged", stderr="boom"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    with caplog.at_level(logging.INFO, logger="data_api.llm_client"):
        with pytest.raises(ClaudeCLIError):
            call_llm("prompt")

    assert "Claude CLIリクエスト: prompt" in caplog.text
    assert "Claude CLIレスポンス" not in caplog.text


def test_get_secret_returns_value_when_present(monkeypatch):
    monkeypatch.setattr(st, "secrets", {"llm_provider": "openai"})
    assert _get_secret("llm_provider") == "openai"


def test_get_secret_returns_default_when_key_missing(monkeypatch):
    monkeypatch.setattr(st, "secrets", {})
    assert _get_secret("llm_provider", "claude_cli") == "claude_cli"


def test_get_secret_returns_default_when_secrets_file_missing(monkeypatch):
    class RaisingSecrets:
        def get(self, key, default=None):
            raise StreamlitSecretNotFoundError("no secrets file")

    monkeypatch.setattr(st, "secrets", RaisingSecrets())
    assert _get_secret("llm_provider", "claude_cli") == "claude_cli"


def test_get_provider_defaults_to_claude_cli(monkeypatch):
    monkeypatch.setattr(st, "secrets", {})
    assert _get_provider() == "claude_cli"


def test_get_provider_normalizes_case_and_whitespace(monkeypatch):
    monkeypatch.setattr(st, "secrets", {"llm_provider": "  OpenAI  "})
    assert _get_provider() == "openai"
