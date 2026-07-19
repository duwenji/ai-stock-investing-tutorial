import shutil
import subprocess


class ClaudeCLINotFoundError(RuntimeError):
    pass


class ClaudeCLIError(RuntimeError):
    pass


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
    result = subprocess.run(
        [executable, "-p", prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise ClaudeCLIError(f"Claude Code CLIの実行に失敗しました: {result.stderr.strip()}")
    return result.stdout.strip()
