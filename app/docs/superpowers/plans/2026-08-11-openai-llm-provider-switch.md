# LLMプロバイダ切り替え（Claude Code CLI / OpenAI API） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `data_api/llm_client.py` の `call_llm()` をプロバイダ非依存にし、`.streamlit/secrets.toml` の `llm_provider` 設定でClaude Code CLIとOpenAI APIを切り替え可能にする。

**Architecture:** `call_llm(prompt, timeout=120) -> str` の公開シグネチャは変更せず、内部で `_get_provider()`（`st.secrets` 読み取り、`StreamlitSecretNotFoundError`時はデフォルト`"claude_cli"`にフォールバック）の値により `_call_claude_cli()` / `_call_openai()` に振り分ける。呼び出し元15箇所は無修正。

**Tech Stack:** Python 3.14, Streamlit（`st.secrets`）, `openai` パッケージ（Chat Completions API）, pytest + `monkeypatch`

## Global Constraints

- 設定は `.streamlit/secrets.toml` に集約する（`.env`は導入しない）。キー: `llm_provider`（省略可、デフォルト`"claude_cli"`）、`openai_api_key`（`llm_provider="openai"`時必須）、`openai_model`（省略可、デフォルト`"gpt-5"`）。
- `call_llm(prompt: str, timeout: int = 120) -> str` の公開シグネチャ・戻り値は変更しない。
- `check_claude_cli_available()` は `check_llm_available()` にリネームする。
- secretsファイルが存在しない環境でも `pytest` が通ること（`StreamlitSecretNotFoundError` を捕捉してデフォルトにフォールバック）。
- 動的な実行中切り替え（管理画面UI）はスコープ外。切り替えは設定変更＋再起動。

---

### Task 1: 依存関係の追加

**Files:**
- Modify: `ai-stock-investing-tutorial/app/pyproject.toml`

**Interfaces:**
- Produces: `openai` パッケージがインストール済みであること（以降のタスクが `import openai` を使う）

- [ ] **Step 1: `pyproject.toml` の `dependencies` に `openai` を追加する**

`ai-stock-investing-tutorial/app/pyproject.toml` の `dependencies` 配列（`"bcrypt>=5.0.0",` の直後などアルファベット順の適切な位置）に以下を追加する:

```toml
    "openai>=2.7.0",
```

- [ ] **Step 2: 依存関係をインストールする**

Run: `cd ai-stock-investing-tutorial/app && uv sync`
Expected: `openai` パッケージが `.venv` にインストールされる（エラーなく完了する）

- [ ] **Step 3: Commit**

```bash
cd ai-stock-investing-tutorial/app
git add pyproject.toml uv.lock
git commit -m "chore: OpenAI Python SDKを依存関係に追加"
```

---

### Task 2: `llm_client.py` にプロバイダ設定読み取りを追加

**Files:**
- Modify: `ai-stock-investing-tutorial/app/data_api/llm_client.py`
- Test: `ai-stock-investing-tutorial/app/tests/test_llm_client.py`

**Interfaces:**
- Consumes: なし（Task 1で`openai`パッケージがインストール済み）
- Produces:
  - `_get_secret(key: str, default: str | None = None) -> str | None`
  - `_get_provider() -> str`（正規化済み、`"claude_cli"` または `"openai"` などの生文字列。バリデーションはTask 4で行う）

このタスクでは設定読み取りのヘルパーのみを追加する（既存の`call_llm`/`check_claude_cli_available`の中身はまだ変更しない）。

- [ ] **Step 1: 失敗するテストを書く**

`ai-stock-investing-tutorial/app/tests/test_llm_client.py` の先頭 import 群に以下を追加:

```python
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from data_api.llm_client import _get_provider, _get_secret
```

ファイル末尾に以下のテストを追加:

```python
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
```

- [ ] **Step 2: テストを実行し、失敗することを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/test_llm_client.py -v -k "get_secret or get_provider"`
Expected: FAIL（`_get_provider`/`_get_secret` が存在しない、`ImportError`）

- [ ] **Step 3: 最小実装を追加する**

`ai-stock-investing-tutorial/app/data_api/llm_client.py` の先頭付近（`import subprocess` の後）に以下を追加:

```python
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError
```

`_SYSTEM_PROMPT` の定義の後に以下の関数を追加:

```python
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
```

- [ ] **Step 4: テストを実行し、成功することを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/test_llm_client.py -v -k "get_secret or get_provider"`
Expected: PASS（5件）

- [ ] **Step 5: Commit**

```bash
cd ai-stock-investing-tutorial/app
git add data_api/llm_client.py tests/test_llm_client.py
git commit -m "feat: LLMプロバイダ設定の読み取りヘルパーを追加"
```

---

### Task 3: Claude CLI呼び出しロジックを `_call_claude_cli` に切り出す

**Files:**
- Modify: `ai-stock-investing-tutorial/app/data_api/llm_client.py`
- Test: `ai-stock-investing-tutorial/app/tests/test_llm_client.py`

**Interfaces:**
- Consumes: なし
- Produces: `_call_claude_cli(prompt: str, timeout: int) -> str`（既存の`call_llm`のClaude CLI呼び出し本体そのまま。例外は`ClaudeCLINotFoundError`/`ClaudeCLIError`のまま）

既存の`call_llm()`の中身を関数名を変えて移すだけのリファクタリング。挙動・ログメッセージは変更しない。既存テストは全て通り続ける必要がある。

- [ ] **Step 1: 既存の`call_llm`本体を`_call_claude_cli`にリネームする**

`ai-stock-investing-tutorial/app/data_api/llm_client.py` の既存の `call_llm` 関数（下記）を:

```python
def call_llm(prompt: str, timeout: int = 120) -> str:
    """Claude Code CLIにプロンプトを渡し、応答テキストを取得する。

    各分析エージェントやコメント生成処理から共通のLLM呼び出し口として利用される。
    """
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
```

以下に置き換える（関数名を`_call_claude_cli`に変更するのみ、中身は無変更）:

```python
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


def call_llm(prompt: str, timeout: int = 120) -> str:
    """設定されたLLMプロバイダにプロンプトを渡し、応答テキストを取得する。

    各分析エージェントやコメント生成処理から共通のLLM呼び出し口として利用される。
    """
    return _call_claude_cli(prompt, timeout)
```

（`_call_openai`への振り分けはTask 5で追加する。このタスクの時点では`call_llm`は常に`_call_claude_cli`を呼ぶ。）

- [ ] **Step 2: 既存テストを実行し、全て通ることを確認する（回帰確認）**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/test_llm_client.py -v`
Expected: PASS（既存の`call_llm`系テストが全て通る。関数名変更のみで公開インターフェースは同一のため、既存テストは無修正で通る）

- [ ] **Step 3: Commit**

```bash
cd ai-stock-investing-tutorial/app
git add data_api/llm_client.py
git commit -m "refactor: Claude CLI呼び出し本体を_call_claude_cliに切り出し"
```

---

### Task 4: OpenAI API呼び出しを追加

**Files:**
- Modify: `ai-stock-investing-tutorial/app/data_api/llm_client.py`
- Test: `ai-stock-investing-tutorial/app/tests/test_llm_client.py`

**Interfaces:**
- Consumes: `_get_secret`（Task 2）、`_SYSTEM_PROMPT`（既存定数）
- Produces:
  - `class OpenAIAPIKeyMissingError(RuntimeError)`
  - `class OpenAIAPIError(RuntimeError)`
  - `_call_openai(prompt: str, timeout: int) -> str`

- [ ] **Step 1: 失敗するテストを書く**

`ai-stock-investing-tutorial/app/tests/test_llm_client.py` の import 群に追加:

```python
import openai

from data_api.llm_client import (
    OpenAIAPIError,
    OpenAIAPIKeyMissingError,
    _call_openai,
)
```

ファイル末尾に以下のテストを追加:

```python
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
```

`_SYSTEM_PROMPT`をテストファイルからも参照できるよう、import群に以下を追加する:

```python
from data_api.llm_client import _SYSTEM_PROMPT
```

- [ ] **Step 2: テストを実行し、失敗することを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/test_llm_client.py -v -k "call_openai"`
Expected: FAIL（`OpenAIAPIError`/`OpenAIAPIKeyMissingError`/`_call_openai`が存在しない、`ImportError`）

- [ ] **Step 3: 実装する**

`ai-stock-investing-tutorial/app/data_api/llm_client.py` の先頭 import 群に追加:

```python
import openai
```

`ClaudeCLIError`クラス定義の後に以下の例外クラスを追加:

```python
class OpenAIAPIKeyMissingError(RuntimeError):
    """`llm_provider = "openai"` だが `openai_api_key` が未設定の場合に送出する例外。"""

    pass


class OpenAIAPIError(RuntimeError):
    """OpenAI APIの呼び出しがエラーとなった場合に送出する例外。"""

    pass
```

`_call_claude_cli`の後（`call_llm`の前）に以下を追加:

```python
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
```

- [ ] **Step 4: テストを実行し、成功することを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/test_llm_client.py -v -k "call_openai"`
Expected: PASS（4件）

- [ ] **Step 5: Commit**

```bash
cd ai-stock-investing-tutorial/app
git add data_api/llm_client.py tests/test_llm_client.py
git commit -m "feat: OpenAI Chat Completions API呼び出しを追加"
```

---

### Task 5: `call_llm`/`check_llm_available` をプロバイダで振り分ける

**Files:**
- Modify: `ai-stock-investing-tutorial/app/data_api/llm_client.py`
- Modify: `ai-stock-investing-tutorial/app/app.py`
- Test: `ai-stock-investing-tutorial/app/tests/test_llm_client.py`

**Interfaces:**
- Consumes: `_get_provider`（Task 2）、`_call_claude_cli`（Task 3）、`_call_openai`（Task 4）
- Produces: `call_llm(prompt: str, timeout: int = 120) -> str`（振り分け版）、`check_llm_available() -> None`（`check_claude_cli_available`のリネーム＋振り分け）

- [ ] **Step 1: 失敗するテストを書く**

`ai-stock-investing-tutorial/app/tests/test_llm_client.py` の import を更新する。既存の:

```python
from data_api.llm_client import (
    ClaudeCLIError,
    ClaudeCLINotFoundError,
    call_llm,
    check_claude_cli_available,
)
```

を以下に置き換える:

```python
from data_api.llm_client import (
    ClaudeCLIError,
    ClaudeCLINotFoundError,
    OpenAIAPIError,
    OpenAIAPIKeyMissingError,
    _SYSTEM_PROMPT,
    _call_openai,
    call_llm,
    check_llm_available,
)
```

（Task 4で追加した個別importと重複する行はまとめる）

既存の `test_check_claude_cli_available_raises_when_missing` と `test_check_claude_cli_available_passes_when_found` を以下に置き換える（Claude CLIがデフォルトプロバイダなので、既存の`shutil.which`ベースの挙動を明示的に`llm_provider`未設定＝デフォルトの状態で検証する形にする）:

```python
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
```

既存の`call_llm`系テスト（`test_call_llm_returns_stdout_on_success`等、Claude CLI経路のもの）はすべて `monkeypatch.setattr(st, "secrets", {})` を先頭に追加し、デフォルトプロバイダ（`claude_cli`）で動作することを明示する。

- [ ] **Step 2: テストを実行し、失敗することを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/test_llm_client.py -v`
Expected: FAIL（`check_llm_available`が存在しない`ImportError`、および振り分け未実装によるテスト失敗）

- [ ] **Step 3: 実装する**

`ai-stock-investing-tutorial/app/data_api/llm_client.py` の既存の `check_claude_cli_available` と `call_llm` を以下に置き換える:

```python
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
```

`ai-stock-investing-tutorial/app/app.py` の以下の箇所を:

```python
from data_api.llm_client import check_claude_cli_available
```

```python
try:
    check_claude_cli_available()
except Exception as exc:
    st.error(str(exc))
    st.stop()
```

それぞれ以下に置き換える:

```python
from data_api.llm_client import check_llm_available
```

```python
try:
    check_llm_available()
except Exception as exc:
    st.error(str(exc))
    st.stop()
```

- [ ] **Step 4: テストを実行し、成功することを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/test_llm_client.py -v`
Expected: PASS（全件）

- [ ] **Step 5: プロジェクト全体のテストを実行し、回帰がないことを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest -v`
Expected: PASS（全件。`app.py`のimport変更が他モジュールに影響していないことを確認）

- [ ] **Step 6: Commit**

```bash
cd ai-stock-investing-tutorial/app
git add data_api/llm_client.py app.py tests/test_llm_client.py
git commit -m "feat: llm_providerに応じてClaude CLI/OpenAIを振り分ける"
```

---

### Task 6: 設定ドキュメント・`.env.example`削除

**Files:**
- Delete: `ai-stock-investing-tutorial/app/.env.example`
- Modify: `ai-stock-investing-tutorial/app/README.md`
- Modify: `ai-stock-investing-tutorial/app/docs/app-design.md`

**Interfaces:**
- Consumes: なし（ドキュメントのみの変更）
- Produces: なし

- [ ] **Step 1: `.env.example`を削除する**

```bash
cd ai-stock-investing-tutorial/app
git rm .env.example
```

- [ ] **Step 2: `README.md`を更新する**

`ai-stock-investing-tutorial/app/README.md` の「必要な環境」節（17〜21行目）:

```markdown
## 必要な環境

- Python 3.14系（[uv](https://docs.astral.sh/uv/)で管理）
- [Claude Code CLI](https://docs.claude.com/claude-code)（`claude`コマンド）がインストール・ログイン済みであること
  - LLM呼び出しはOpenAI/Anthropic APIキーを使わず、`claude -p`のサブプロセス実行で行います
```

を以下に置き換える:

```markdown
## 必要な環境

- Python 3.14系（[uv](https://docs.astral.sh/uv/)で管理）
- LLM呼び出しは、`.streamlit/secrets.toml`の`llm_provider`設定によりいずれかを選択します（デフォルトは`claude_cli`）:
  - `claude_cli`（デフォルト）: [Claude Code CLI](https://docs.claude.com/claude-code)（`claude`コマンド）がインストール・ログイン済みであること
  - `openai`: OpenAI APIキーが必要（`.streamlit/secrets.toml`に設定）
```

「セットアップ」節（23〜35行目）の`.streamlit/secrets.toml`作成手順の後に、以下を追記する:

```markdown
LLMプロバイダを切り替える場合は、`.streamlit/secrets.toml`に以下を追記してください（省略時は`claude_cli`が使われます）。

```toml
llm_provider = "openai"       # "claude_cli"（デフォルト） | "openai"
openai_api_key = "sk-..."     # llm_provider = "openai" の場合必須
openai_model = "gpt-5"        # 省略可。デフォルト "gpt-5"
```
```

「構成」節（61〜74行目）の以下の行:

```
data_api/                   # yfinance連携・LLM連携（Claude Code CLI）
```

を以下に置き換える:

```
data_api/                   # yfinance連携・LLM連携（Claude Code CLI / OpenAI API切り替え）
```

「テスト」節の直前にある「構成」節末尾の以下の行:

```
tests/                      # pytest（yfinance・Claude Code CLI呼び出しはモック化）
```

を以下に置き換える:

```
tests/                      # pytest（yfinance・LLM呼び出しはモック化）
```

- [ ] **Step 3: `docs/app-design.md`を更新する**

`ai-stock-investing-tutorial/app/docs/app-design.md` の54行目:

```
    llm_client.py                # call_llm, check_claude_cli_available（Claude Code CLIサブプロセス呼び出し）
```

を以下に置き換える:

```
    llm_client.py                # call_llm, check_llm_available（Claude Code CLI / OpenAI APIをllm_provider設定で切り替え）
```

323行目:

```
共通の起動時チェックとして、`app.py` はStreamlit描画前に `check_claude_cli_available()` を呼び、Claude Code CLIが見つからない場合は `st.error` を表示して `st.stop()` で処理を止める（7タブ＋銘柄詳細ダイアログすべての前提条件）。
```

を以下に置き換える:

```
共通の起動時チェックとして、`app.py` はStreamlit描画前に `check_llm_available()` を呼び、設定済みLLMプロバイダ（`.streamlit/secrets.toml`の`llm_provider`、デフォルト`claude_cli`）が利用できない場合は `st.error` を表示して `st.stop()` で処理を止める（7タブ＋銘柄詳細ダイアログすべての前提条件）。
```

「### 5.1 LLM連携（Claude Code CLI）」の見出しと本文（該当箇所は`## 5. 横断的な設計事項`の直下）:

```
### 5.1 LLM連携（Claude Code CLI）

- `call_llm(prompt, timeout=120)` は `_resolve_claude_executable()`（内部で `shutil.which("claude")`）で解決した実行パスを使い、`subprocess.run([executable, "--system-prompt", ..., "-p"], input=prompt, ...)` の形でプロンプトを**標準入力経由**で渡す。Windowsでは `claude` がnpmの `.cmd` シムに解決されバッチ引数展開でダブルクォート入りのJSONプロンプトが壊れるため、あえてargvではなくstdin経由にしている。
- CLI未検出時は `ClaudeCLINotFoundError`（`shutil.which` が `None` を返した場合）、サブプロセスの非0終了時は `ClaudeCLIError` を送出する。前者は起動時の `check_claude_cli_available()` と、`call_llm()` 呼び出し直前の両方で発生しうる（アプリ起動後にCLIが削除された場合など）。
- 起動時に `check_claude_cli_available()` でCLIの存在を確認し、無ければ全機能を使わせずアプリを停止する。
```

を以下に置き換える:

```
### 5.1 LLM連携（Claude Code CLI / OpenAI API）

- `call_llm(prompt, timeout=120)` は `.streamlit/secrets.toml` の `llm_provider` 設定（省略時は `"claude_cli"`）に応じて `_call_claude_cli()` / `_call_openai()` に振り分ける、プロバイダ非依存の共通呼び出し口。
- `_call_claude_cli()` は `_resolve_claude_executable()`（内部で `shutil.which("claude")`）で解決した実行パスを使い、`subprocess.run([executable, "--system-prompt", ..., "-p"], input=prompt, ...)` の形でプロンプトを**標準入力経由**で渡す。Windowsでは `claude` がnpmの `.cmd` シムに解決されバッチ引数展開でダブルクォート入りのJSONプロンプトが壊れるため、あえてargvではなくstdin経由にしている。CLI未検出時は `ClaudeCLINotFoundError`、サブプロセスの非0終了時は `ClaudeCLIError` を送出する。
- `_call_openai()` は OpenAI Chat Completions API（`openai_model` 設定、省略時は `"gpt-5"`）にシステムプロンプト＋ユーザープロンプトの2メッセージで送信する。`openai_api_key` 未設定時は `OpenAIAPIKeyMissingError`、API呼び出し失敗時は `OpenAIAPIError` を送出する。
- 起動時に `check_llm_available()` で設定済みプロバイダの利用可否を確認し、不可なら全機能を使わせずアプリを停止する。
```

「### 5.5 エラーハンドリング一覧」の表の以下の行:

```
| Claude Code CLI未検出                                                                               | アプリ起動時に`st.error` 表示＋`st.stop()`（`ClaudeCLINotFoundError`）                                                                                  |
| LLMサブプロセスの非0終了                                                                            | `ClaudeCLIError` を送出（呼び出し元でエラー表示）                                                                                                           |
```

を以下に置き換える:

```
| Claude Code CLI未検出（`llm_provider = "claude_cli"`時）                                          | アプリ起動時に`st.error` 表示＋`st.stop()`（`ClaudeCLINotFoundError`）                                                                                  |
| LLMサブプロセスの非0終了（`llm_provider = "claude_cli"`時）                                         | `ClaudeCLIError` を送出（呼び出し元でエラー表示）                                                                                                           |
| OpenAI APIキー未設定（`llm_provider = "openai"`時）                                                 | アプリ起動時に`st.error` 表示＋`st.stop()`（`OpenAIAPIKeyMissingError`）                                                                                 |
| OpenAI API呼び出し失敗（`llm_provider = "openai"`時）                                               | `OpenAIAPIError` を送出（呼び出し元でエラー表示）                                                                                                           |
```

- [ ] **Step 4: 全テストを再実行し、ドキュメントのみの変更で回帰がないことを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest -v`
Expected: PASS（全件。ドキュメント変更のみのため念のための確認）

- [ ] **Step 5: Commit**

```bash
cd ai-stock-investing-tutorial/app
git add .env.example README.md docs/app-design.md
git commit -m "docs: LLMプロバイダ切り替え設定の説明を追記、不要な.env.exampleを削除"
```

---

## Self-Review Notes

- **spec Aセクション（設定）**: Task 1（依存追加）、Task 2（`_get_secret`/`_get_provider`）、Task 6（README/secrets.toml手順）でカバー。
- **spec Bセクション（`llm_client.py`変更）**: Task 3（`_call_claude_cli`切り出し）、Task 4（`_call_openai`＋例外クラス）、Task 5（`call_llm`/`check_llm_available`振り分け）でカバー。
- **spec Cセクション（`app.py`変更）**: Task 5 Step 3でカバー。
- **spec Dセクション（依存関係）**: Task 1でカバー。
- **spec Eセクション（ドキュメント更新）**: Task 6でカバー。
- 型・シグネチャの一貫性: `_call_claude_cli(prompt: str, timeout: int) -> str` と `_call_openai(prompt: str, timeout: int) -> str` は全タスクを通じて同一シグネチャ。`call_llm(prompt: str, timeout: int = 120) -> str` は公開シグネチャとして最初から最後まで不変。
