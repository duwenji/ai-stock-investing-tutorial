# LLM API(Claude/OpenAI)のPython連携

## この教材で身につくこと

- Claude API（`anthropic`）とOpenAI API（`openai`）の最小呼び出し方法
- 2つのSDKのリクエスト・レスポンス形状の違い
- APIキーを環境変数から安全に読み込む方法
- 以降の教材で共通利用する `call_llm(prompt: str) -> str` の実装

## 概要

01-stock-price-api.mdで取得した株価データや、02-prompt-patternsで
設計したプロンプトは、実際にLLM APIへ送信して初めて分析結果になります。
この教材では、Claude APIとOpenAI APIそれぞれの最小コードを示し、
両者の違いを比較します。

## 位置づけ

この教材は03-data-apiカテゴリの2番目です。
01-stock-price-api.mdで取得したデータを実際にLLMへ渡す土台となります。

ここで定義する `call_llm(prompt: str) -> str` は、02-prompt-patterns
（決算要約・センチメント分析等）で示したプロンプトの実行部分に対応し、
次の03-structured-output.md、04-rate-limit-and-cost.md、さらに
04-analysis-agentsの各エージェントでも共通して使われます。

> 関連: API直叩き/SDK/CLIサブプロセスという呼び出し方式の選定基準を
> 体系的に学びたい場合は
> [genai-app-integration-tutorial: API/SDK/CLIサブプロセス方式の比較](https://github.com/duwenji/genai-app-integration-tutorial/blob/master/docs/01-invocation-and-architecture/02-api-sdk-vs-cli-subprocess.md)
> を参照してください（`app/`の完成版アプリはCLIサブプロセス方式を採用しています）。

## 主要概念・パラメータ解説

### 2つのSDKの比較

| 項目 | Anthropic (Claude) | OpenAI |
|------|--------------------|--------|
| インストール | `pip install anthropic` | `pip install openai` |
| クライアント初期化 | `anthropic.Anthropic(api_key=...)` | `openai.OpenAI(api_key=...)` |
| APIキー環境変数（慣例） | `ANTHROPIC_API_KEY` | `OPENAI_API_KEY` |
| モデル指定例 | `model="claude-sonnet-5"` | `model="gpt-5"` |
| メッセージ送信 | `client.messages.create()` | `client.chat.completions.create()` |
| 応答テキストの取り出し | `response.content[0].text` | `response.choices[0].message.content` |
| `max_tokens` | 必須パラメータ | 省略可能（省略時はモデル既定値） |

### メッセージ形式の共通点

両SDKとも、会話履歴は `role` と `content` を持つ辞書のリストで表現します。

```python
messages = [{"role": "user", "content": "プロンプト本文"}]
```

## 実ソースコード（Python / プロンプト例）

```python
import os

import anthropic
import openai


def call_llm(prompt: str) -> str:
    """Claude APIにプロンプトを送信し、応答テキストを返す。

    以降の教材（構造化出力・レート制限管理・分析エージェント）で
    共通利用する基本関数。
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def call_llm_openai(prompt: str) -> str:
    """OpenAI APIにプロンプトを送信し、応答テキストを返す（比較用）。"""
    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model="gpt-5",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


if __name__ == "__main__":
    answer = call_llm("トヨタ自動車の主な事業内容を1文で説明してください。")
    print(answer)
```

### 悪い例

APIキーをソースコードに直接書き込み、確認のためログにも
出力してしまっています。この状態でGitにコミットすると、
キーが漏えいします。

```python
# 悪い例: APIキーをハードコーディングし、ログにも出力する
API_KEY = "YOUR_API_KEY"  # 実際にはこの場所に本物のキー文字列が書かれてしまう
client = anthropic.Anthropic(api_key=API_KEY)
print(f"接続に使用したキー: {API_KEY}")
```

### 良い例

環境変数から読み込み、キーの値を一切ログ・出力に含めません。

```python
# 良い例: 環境変数から読み込み、値は一切ログに出さない
api_key = os.environ["ANTHROPIC_API_KEY"]
client = anthropic.Anthropic(api_key=api_key)
```

### 実行結果例

```text
トヨタ自動車は、乗用車・商用車の開発・製造・販売を中心に、
金融サービスや次世代モビリティ事業も展開する総合自動車メーカーです。
```

## 演習課題

1. `call_llm` に `max_tokens` を引数として渡せるように拡張してください。
2. `call_llm_openai` を使い、同じプロンプトをClaudeとOpenAIの
   両方に送信して応答を比較するコードを書いてください。
3. `ANTHROPIC_API_KEY` が未設定の場合に、分かりやすいエラー
   メッセージを表示するようにコードを修正してください。

## 理解度チェック

- [ ] ClaudeとOpenAIで応答テキストの取り出し方が違う理由を説明できる
- [ ] APIキーを環境変数から読み込むべき理由を説明できる
- [ ] `call_llm(prompt: str) -> str` が以降の教材でどう使われるか説明できる

---

投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。

[← 前へ: 株価データAPI連携](01-stock-price-api.md) | [次へ: 構造化出力・Tool use →](03-structured-output.md)
