"""Claude Code CLI（`claude`コマンド）をサブプロセスとして呼び出し、
LLMへのプロンプト送信・応答取得を行うための薄いラッパーモジュール。"""

import logging
import shutil
import subprocess

import openai
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from common.logging_config import log_duration

logger = logging.getLogger(__name__)


class ClaudeCLINotFoundError(RuntimeError):
    """`claude`コマンドがPATH上に見つからない場合に送出する例外。"""

    pass


class ClaudeCLIError(RuntimeError):
    """`claude`コマンドの実行がエラー終了した場合に送出する例外。"""

    pass


class OpenAIAPIKeyMissingError(RuntimeError):
    """`llm_provider = "openai"` だが `openai_api_key` が未設定の場合に送出する例外。"""

    pass


class OpenAIAPIError(RuntimeError):
    """OpenAI APIの呼び出しがエラーとなった場合に送出する例外。"""

    pass


# LLMに毎回渡すシステムプロンプト。出力形式をアプリ側で制御しやすくするため、
# 指示外の余計な発言をしないよう厳密に指示している。
_SYSTEM_PROMPT = "あなたは指示に厳密に従うアシスタントです。指示された出力のみを返してください。"


def _get_secret(key: str, default: str | None = None) -> str | None:
    """`.streamlit/secrets.toml` から設定値を読む。secretsファイル自体が
    存在しない環境（フレッシュcloneでのpytest実行等）でも落ちないよう、
    その場合はdefaultにフォールバックする。"""
    try:
        return st.secrets.get(key, default)
    except StreamlitSecretNotFoundError:
        return default


def _get_provider() -> str:
    """LLM呼び出し先プロバイダを返す（`"claude_cli"` または `"openai"` を想定した
    生文字列。バリデーションは呼び出し側で行う）。"""
    return (_get_secret("llm_provider", "claude_cli") or "claude_cli").strip().lower()


def _resolve_claude_executable() -> str:
    """`claude`実行ファイルのパスを解決する。未インストール時は分かりやすい例外に変換する。"""
    executable = shutil.which("claude")
    if executable is None:
        raise ClaudeCLINotFoundError(
            "Claude Code CLI（`claude`コマンド）が見つかりません。"
            "インストールとログインを確認してください。"
        )
    return executable


def check_llm_available() -> None:
    """設定されたLLMプロバイダの利用可否を事前チェックするためのエントリポイント
    （結果は例外の有無で判定）。"""
    provider = _get_provider()
    if provider == "claude_cli":
        _resolve_claude_executable()
    elif provider == "openai":
        if not _get_secret("openai_api_key"):
            raise OpenAIAPIKeyMissingError(
                "OpenAI APIキーが設定されていません。"
                "`.streamlit/secrets.toml` に `openai_api_key = \"...\"` を設定してください。"
            )
    else:
        raise ValueError(f"未対応のllm_providerです: {provider}")


def _call_claude_cli(prompt: str, timeout: int) -> str:
    """Claude Code CLIにプロンプトを渡し、応答テキストを取得する。"""
    executable = _resolve_claude_executable()
    with log_duration(logger, f"Claude CLI呼び出し（prompt長={len(prompt)}）"):
        logger.info("Claude CLIリクエスト: %s", prompt)
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
        logger.info("Claude CLIレスポンス: %s", result.stdout)
    return result.stdout.strip()


def _call_openai(prompt: str, timeout: int) -> str:
    """OpenAI Chat Completions APIにプロンプトを渡し、応答テキストを取得する。"""
    api_key = _get_secret("openai_api_key")
    if not api_key:
        raise OpenAIAPIKeyMissingError(
            "OpenAI APIキーが設定されていません。"
            "`.streamlit/secrets.toml` に `openai_api_key = \"...\"` を設定してください。"
        )
    model = _get_secret("openai_model", "gpt-5")
    with log_duration(logger, f"OpenAI API呼び出し（model={model}, prompt長={len(prompt)}）"):
        logger.info("OpenAI APIリクエスト: %s", prompt)
        client = openai.OpenAI(api_key=api_key)
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                timeout=timeout,
            )
        except openai.OpenAIError as exc:
            raise OpenAIAPIError(f"OpenAI APIの呼び出しに失敗しました: {exc}") from exc
        response_text = completion.choices[0].message.content.strip()
        logger.info("OpenAI APIレスポンス: %s", response_text)
    return response_text


def call_llm(prompt: str, timeout: int = 120) -> str:
    """設定されたLLMプロバイダにプロンプトを渡し、応答テキストを取得する。

    各分析エージェントやコメント生成処理から共通のLLM呼び出し口として利用される。
    """
    provider = _get_provider()
    if provider == "claude_cli":
        return _call_claude_cli(prompt, timeout)
    elif provider == "openai":
        return _call_openai(prompt, timeout)
    else:
        raise ValueError(f"未対応のllm_providerです: {provider}")
