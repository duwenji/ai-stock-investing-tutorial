# LLMプロバイダ切り替え（Claude Code CLI / OpenAI API）設計

## 背景・目的

現在、全LLM呼び出しは `data_api/llm_client.py` の `call_llm()` を経由し、`claude`コマンド（Claude Code CLI）のサブプロセス実行で行っている。OpenAI APIも使えるようにし、どちらを使うかをアプリ設定で切り替え可能にする。

`call_llm(prompt, timeout=120) -> str` は15箇所以上（各タブ・エージェント・プロンプトパターン）から呼ばれているため、この公開シグネチャは変更せず、呼び出し元は無修正で済むようにする。

## スコープ外

- 実行中のアプリでの動的切り替え（管理画面からのプロバイダ変更）。切り替えは`.streamlit/secrets.toml`を書き換えてアプリを再起動する運用とする（ユーザー確認済み）。
- OpenAI以外の追加プロバイダ（Gemini等）。
- リクエストごと・エージェントごとに異なるプロバイダを使い分ける機能。

## A. 設定

`.streamlit/secrets.toml`（既存の`auth_cookie_key`と同じファイル、`.gitignore`対象）に以下を追加する。

```toml
auth_cookie_key = "..."       # 既存
llm_provider = "claude_cli"   # 省略可。"claude_cli"（デフォルト） | "openai"
openai_api_key = "sk-..."     # llm_provider = "openai" の場合必須
openai_model = "gpt-5"        # 省略可。デフォルト "gpt-5"
```

`.env.example`は削除する（現状「OpenAI/Anthropic APIキーを使用しません」という誤った説明のコメントのみで実体が無く、設定方法が`.streamlit/secrets.toml`に一本化されるため不要）。

### secrets未設定環境への配慮

`llm_client.py`は現状streamlitに依存しない純粋モジュールとして`pytest`から直接テストされている（`tests/test_llm_client.py`）。`.streamlit/secrets.toml`が存在しない環境（フレッシュcloneでのpytest実行等）で`st.secrets`にアクセスすると`StreamlitSecretNotFoundError`が送出されるため、これを捕捉してデフォルト値にフォールバックする小さなヘルパーを設ける。

```python
def _get_secret(key: str, default: str | None = None) -> str | None:
    try:
        return st.secrets.get(key, default)
    except StreamlitSecretNotFoundError:
        return default
```

secrets未設定時は`llm_provider`のデフォルト`"claude_cli"`にフォールバックする（secrets不要な既存動作を維持）。テストからは`monkeypatch.setattr(st, "secrets", {...})`でプレーンな辞書に差し替えることで、実ファイル無しにopenai経路も含めてテスト可能。

## B. `data_api/llm_client.py` の変更

### 現状

`call_llm()` はClaude CLI呼び出しのみを行う。`check_claude_cli_available()` はCLIの存在確認のみ行い、`app.py`が起動時に呼んでいる。

### 変更内容

- `import streamlit as st` と `from streamlit.errors import StreamlitSecretNotFoundError` を追加。
- `_get_provider() -> str`: `_get_secret("llm_provider", "claude_cli")` を正規化（`strip().lower()`）して返す。
- 既存のClaude CLI呼び出しロジック（`_resolve_claude_executable`、`ClaudeCLINotFoundError`、`ClaudeCLIError`、subprocess実行部分）はそのまま維持し、`_call_claude_cli(prompt, timeout) -> str` として切り出す。
- OpenAI呼び出しを新設: `openai`パッケージの`OpenAI`クライアントを使い、`chat.completions.create(model=openai_model, messages=[{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": prompt}], timeout=timeout)` を呼ぶ`_call_openai(prompt, timeout) -> str`を追加。レスポンスは`response.choices[0].message.content.strip()`を返す。
  - 新規例外 `OpenAIAPIKeyMissingError(RuntimeError)`: `openai_api_key`未設定時に送出。
  - 新規例外 `OpenAIAPIError(RuntimeError)`: `openai.OpenAIError`系（認証エラー・レート制限・タイムアウト等、すべて`openai.OpenAIError`のサブクラス）を捕捉し、元のメッセージを含めてラップして送出。
- `check_claude_cli_available()` を `check_llm_available()` にリネーム。`_get_provider()`の値に応じて、`"claude_cli"`ならCLIの存在確認（既存ロジック）、`"openai"`なら`openai_api_key`の設定確認（無ければ`OpenAIAPIKeyMissingError`）を行う。未知のprovider値は`ValueError`。
- `call_llm(prompt, timeout=120) -> str` は公開シグネチャを維持したまま、`_get_provider()`の値で`_call_claude_cli`/`_call_openai`に振り分ける。未知のprovider値は`ValueError`。ログ出力（`log_duration`）は現状通り行うが、メッセージにプロバイダ名を含める（例: `f"LLM呼び出し（provider={provider}, prompt長={len(prompt)}）"`）。

### テスト（`tests/test_llm_client.py`）

- 既存のClaude CLI経路テスト（成功・非0終了・CLI未検出・ログ検証）は`monkeypatch.setattr(st, "secrets", {})`（またはprovider未設定＝デフォルト）で維持しつつ、関数名変更（`check_claude_cli_available` → `check_llm_available`）に追従する。
- OpenAI経路の新規テスト:
  - `llm_provider="openai"` かつ `openai_api_key`未設定で`check_llm_available()`が`OpenAIAPIKeyMissingError`を送出すること。
  - `openai_api_key`設定済みで`check_llm_available()`が例外を送出しないこと。
  - `openai.OpenAI`をmonkeypatchし、`call_llm()`が`chat.completions.create`に正しいmodel/messagesを渡し、レスポンステキストを返すこと。
  - `openai.OpenAI`のmonkeypatch先で例外（`openai.APIError`相当）を送出させ、`call_llm()`が`OpenAIAPIError`に変換して送出すること。
  - 未知の`llm_provider`値で`call_llm()`/`check_llm_available()`が`ValueError`を送出すること。

## C. `app.py` の変更

`from data_api.llm_client import check_claude_cli_available` を `check_llm_available` に変更し、呼び出し箇所（`try: check_llm_available() except Exception as exc: st.error(...); st.stop()`）もリネームに追従する。ロジック自体（例外を`st.error`表示して`st.stop()`）は変更しない。

## D. 依存関係

`pyproject.toml`の`dependencies`に`openai`を追加する。

## E. ドキュメント更新

- `README.md`: 「必要な環境」節にOpenAI APIを使う場合の説明を追加し、「セットアップ」節の`.streamlit/secrets.toml`作成手順に`llm_provider`/`openai_api_key`/`openai_model`の設定例を追記する。
- `docs/app-design.md`: `check_claude_cli_available` → `check_llm_available`への言及を更新し、プロバイダ切り替えの仕組み（`llm_provider`設定、`_call_claude_cli`/`_call_openai`への振り分け）を追記する。
