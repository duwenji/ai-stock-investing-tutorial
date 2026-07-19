import subprocess

import pytest

from data_api.llm_client import (
    ClaudeCLIError,
    ClaudeCLINotFoundError,
    call_llm,
    check_claude_cli_available,
)


def test_call_llm_returns_stdout_on_success(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "claude-executable")

    def fake_run(args, capture_output, text, timeout):
        assert args == ["claude-executable", "-p", "hello"]
        return subprocess.CompletedProcess(args, 0, stdout="response text\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert call_llm("hello") == "response text"


def test_call_llm_raises_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "claude-executable")

    def fake_run(args, capture_output, text, timeout):
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
