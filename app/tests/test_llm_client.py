import logging
import subprocess

import openai
import pytest
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from data_api.llm_client import (
    _SYSTEM_PROMPT,
    ClaudeCLIError,
    ClaudeCLINotFoundError,
    OpenAIAPIError,
    OpenAIAPIKeyMissingError,
    _call_openai,
    _get_provider,
    _get_secret,
    call_llm,
    check_llm_available,
)


def test_call_llm_returns_stdout_on_success(monkeypatch):
    monkeypatch.setattr(st, "secrets", {})
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
    monkeypatch.setattr(st, "secrets", {})
    monkeypatch.setattr("shutil.which", lambda name: "claude-executable")

    def fake_run(args, input, capture_output, text, encoding, timeout):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ClaudeCLIError):
        call_llm("hello")


def test_call_llm_raises_when_cli_not_found(monkeypatch):
    monkeypatch.setattr(st, "secrets", {})
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(ClaudeCLINotFoundError):
        call_llm("hello")


def test_check_llm_available_raises_when_claude_cli_missing(monkeypatch):
    monkeypatch.setattr(st, "secrets", {})
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(ClaudeCLINotFoundError):
        check_llm_available()


def test_check_llm_available_passes_when_claude_cli_found(monkeypatch):
    monkeypatch.setattr(st, "secrets", {})
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/claude")
    check_llm_available()


def test_check_llm_available_raises_when_openai_key_missing(monkeypatch):
    monkeypatch.setattr(st, "secrets", {"llm_provider": "openai"})
    with pytest.raises(OpenAIAPIKeyMissingError):
        check_llm_available()


def test_check_llm_available_passes_when_openai_key_present(monkeypatch):
    monkeypatch.setattr(
        st, "secrets", {"llm_provider": "openai", "openai_api_key": "test-key"}
    )
    check_llm_available()


def test_check_llm_available_raises_on_unknown_provider(monkeypatch):
    monkeypatch.setattr(st, "secrets", {"llm_provider": "unknown"})
    with pytest.raises(ValueError):
        check_llm_available()


def test_call_llm_dispatches_to_openai_when_configured(monkeypatch):
    monkeypatch.setattr(
        st, "secrets", {"llm_provider": "openai", "openai_api_key": "test-key"}
    )

    def fake_call_openai(prompt, timeout):
        assert prompt == "hello"
        assert timeout == 120
        return "openai response"

    monkeypatch.setattr("data_api.llm_client._call_openai", fake_call_openai)
    assert call_llm("hello") == "openai response"


def test_call_llm_raises_on_unknown_provider(monkeypatch):
    monkeypatch.setattr(st, "secrets", {"llm_provider": "unknown"})
    with pytest.raises(ValueError):
        call_llm("hello")


def test_call_llm_logs_duration_on_success(monkeypatch, caplog):
    monkeypatch.setattr(st, "secrets", {})
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
    monkeypatch.setattr(st, "secrets", {})
    monkeypatch.setattr("shutil.which", lambda name: "claude-executable")

    def fake_run(args, input, capture_output, text, encoding, timeout):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with caplog.at_level(logging.INFO, logger="data_api.llm_client"):
        with pytest.raises(ClaudeCLIError):
            call_llm("hello")

    assert "が失敗しました" in caplog.text


def test_call_llm_logs_request_and_response_content(monkeypatch, caplog):
    monkeypatch.setattr(st, "secrets", {})
    monkeypatch.setattr("shutil.which", lambda name: "claude-executable")

    def fake_run(args, input, capture_output, text, encoding, timeout):
        return subprocess.CompletedProcess(args, 0, stdout="response text\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with caplog.at_level(logging.INFO, logger="data_api.llm_client"):
        call_llm("this is the prompt content")

    assert "Claude CLIリクエスト: this is the prompt content" in caplog.text
    assert "Claude CLIレスポンス: response text" in caplog.text


def test_call_llm_does_not_log_response_on_failure(monkeypatch, caplog):
    monkeypatch.setattr(st, "secrets", {})
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


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


def test_call_openai_returns_response_text(monkeypatch):
    monkeypatch.setattr(st, "secrets", {"openai_api_key": "test-key", "openai_model": "gpt-5"})

    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _FakeCompletion("  response text  \n")

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, api_key):
            captured["api_key"] = api_key
            self.chat = FakeChat()

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)

    assert _call_openai("hello", 120) == "response text"
    assert captured["api_key"] == "test-key"
    assert captured["model"] == "gpt-5"
    assert captured["timeout"] == 120
    assert captured["messages"] == [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "hello"},
    ]


def test_call_openai_uses_default_model_when_unset(monkeypatch):
    monkeypatch.setattr(st, "secrets", {"openai_api_key": "test-key"})

    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _FakeCompletion("ok")

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, api_key):
            self.chat = FakeChat()

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)

    _call_openai("hello", 120)
    assert captured["model"] == "gpt-5"


def test_call_openai_raises_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(st, "secrets", {})
    with pytest.raises(OpenAIAPIKeyMissingError):
        _call_openai("hello", 120)


def test_call_openai_wraps_openai_errors(monkeypatch):
    monkeypatch.setattr(st, "secrets", {"openai_api_key": "test-key"})

    class FakeCompletions:
        def create(self, **kwargs):
            raise openai.APIConnectionError(request=None)

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, api_key):
            self.chat = FakeChat()

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)

    with pytest.raises(OpenAIAPIError):
        _call_openai("hello", 120)
