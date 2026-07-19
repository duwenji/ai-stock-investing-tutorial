import shutil
import subprocess


class ClaudeCLINotFoundError(RuntimeError):
    pass


class ClaudeCLIError(RuntimeError):
    pass


def check_claude_cli_available() -> None:
    if shutil.which("claude") is None:
        raise ClaudeCLINotFoundError(
            "Claude Code CLI（`claude`コマンド）が見つかりません。"
            "インストールとログインを確認してください。"
        )


def call_llm(prompt: str, timeout: int = 120) -> str:
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise ClaudeCLIError(f"Claude Code CLIの実行に失敗しました: {result.stderr.strip()}")
    return result.stdout.strip()
