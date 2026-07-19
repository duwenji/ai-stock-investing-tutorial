import shutil
import subprocess


class ClaudeCLINotFoundError(RuntimeError):
    pass


class ClaudeCLIError(RuntimeError):
    pass


_SYSTEM_PROMPT = "あなたは指示に厳密に従うアシスタントです。指示された出力のみを返してください。"


def _resolve_claude_executable() -> str:
    executable = shutil.which("claude")
    if executable is None:
        raise ClaudeCLINotFoundError(
            "Claude Code CLI（`claude`コマンド）が見つかりません。"
            "インストールとログインを確認してください。"
        )
    return executable


def check_claude_cli_available() -> None:
    _resolve_claude_executable()


def call_llm(prompt: str, timeout: int = 120) -> str:
    executable = _resolve_claude_executable()
    # Prompt is passed via stdin, not argv: on Windows, `claude` resolves to
    # an npm .cmd shim, whose batch-argument relay corrupts arguments that
    # contain embedded double quotes (our JSON-format prompts do).
    result = subprocess.run(
        [executable, "--system-prompt", _SYSTEM_PROMPT, "-p"],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise ClaudeCLIError(f"Claude Code CLIの実行に失敗しました: {result.stderr.strip()}")
    return result.stdout.strip()
