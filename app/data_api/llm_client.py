"""Claude Code CLI（`claude`コマンド）をサブプロセスとして呼び出し、
LLMへのプロンプト送信・応答取得を行うための薄いラッパーモジュール。"""

import logging
import shutil
import subprocess

from common.logging_config import log_duration

logger = logging.getLogger(__name__)


class ClaudeCLINotFoundError(RuntimeError):
    """`claude`コマンドがPATH上に見つからない場合に送出する例外。"""

    pass


class ClaudeCLIError(RuntimeError):
    """`claude`コマンドの実行がエラー終了した場合に送出する例外。"""

    pass


# LLMに毎回渡すシステムプロンプト。出力形式をアプリ側で制御しやすくするため、
# 指示外の余計な発言をしないよう厳密に指示している。
_SYSTEM_PROMPT = "あなたは指示に厳密に従うアシスタントです。指示された出力のみを返してください。"


def _resolve_claude_executable() -> str:
    """`claude`実行ファイルのパスを解決する。未インストール時は分かりやすい例外に変換する。"""
    executable = shutil.which("claude")
    if executable is None:
        raise ClaudeCLINotFoundError(
            "Claude Code CLI（`claude`コマンド）が見つかりません。"
            "インストールとログインを確認してください。"
        )
    return executable


def check_claude_cli_available() -> None:
    """CLI利用可否を事前チェックするためのエントリポイント（結果は例外の有無で判定）。"""
    _resolve_claude_executable()


def call_llm(prompt: str, timeout: int = 120) -> str:
    """Claude Code CLIにプロンプトを渡し、応答テキストを取得する。

    各分析エージェントやコメント生成処理から共通のLLM呼び出し口として利用される。
    """
    executable = _resolve_claude_executable()
    # プロンプト本文は機密情報や長大なJSONを含みうるためログに出さず、長さのみ記録する。
    with log_duration(logger, f"Claude CLI呼び出し（prompt長={len(prompt)}）"):
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
            # 非ゼロ終了はCLI側のエラー（未ログイン、タイムアウト等）とみなし、
            # 標準エラー出力を含めて呼び出し元に伝播する。
            raise ClaudeCLIError(f"Claude Code CLIの実行に失敗しました: {result.stderr.strip()}")
    return result.stdout.strip()
