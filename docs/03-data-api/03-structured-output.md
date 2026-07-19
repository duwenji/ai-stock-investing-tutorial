# JSON構造化出力・Tool use

## この教材で身につくこと

- 自由文パースが壊れやすい理由
- AnthropicのTool useで出力形式を強制する方法
- OpenAIの構造化出力（`response_format`）の概要
- センチメント分析結果をスキーマ化して確実にパースする実装

## 概要

LLMに「JSON形式で出力してください」と指示するだけでは、
Markdownのコードフェンス（```json ... ```）や前置きの文章が
混ざることがあり、`json.loads()` が例外を投げる原因になります。

Tool use（Anthropic）や構造化出力（OpenAI）を使うと、APIレベルで
出力形式を強制でき、後続処理でパース失敗を心配する必要がなくなります。

## 位置づけ

この教材は03-data-apiカテゴリの3番目です。
02-llm-api-integration.mdの `call_llm(prompt: str) -> str` は
自由文（文字列）を返しますが、この教材では代わりに構造化データを
確実に取得する方法を学びます。

02-prompt-patterns/02-news-sentiment-prompts.mdで設計した
センチメント判定プロンプトを、ここでは `sentiment` / `confidence` /
`reason` の3フィールドを持つスキーマとして実装します。次の
04-rate-limit-and-cost.mdでも、この構造化出力を前提にコストを
見積もります。

## 主要概念・パラメータ解説

### 自由文パース vs 構造化出力

| 観点 | 自由文パース | 構造化出力（Tool use / スキーマ） |
|------|-------------|-----------------------------------|
| 実装方法 | プロンプトで「JSON形式で」と指示するのみ | JSON Schemaを`tools`や`response_format`で指定 |
| 安定性 | 壊れやすい正規表現・文字列処理が必要 | スキーマ通りの構造が保証される |
| エラー検知 | 壊れて初めて気づく（実行時例外） | スキーマ違反時にAPIレベルで検知できる |
| Markdownフェンス混入 | 混ざりやすく`json.loads()`が失敗しうる | 混入しない |
| Anthropicでの実現方法 | なし | `tools` + `tool_choice`で特定ツールの呼び出しを強制 |
| OpenAIでの実現方法 | なし | `response_format={"type": "json_schema", ...}` |

### Anthropic Tool useの流れ

1. `tools` にJSON Schemaを持つツール定義を渡す
2. `tool_choice` で該当ツールの呼び出しを強制する
3. レスポンスの `content` から `type == "tool_use"` のブロックを探す
4. `block.input` に、スキーマ通りの辞書が入っている

## 実ソースコード（Python / プロンプト例）

```python
import json
import os

import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SENTIMENT_TOOL = {
    "name": "report_sentiment",
    "description": "ニュース記事のセンチメント判定結果を報告する。",
    "input_schema": {
        "type": "object",
        "properties": {
            "sentiment": {
                "type": "string",
                "enum": ["positive", "negative", "neutral"],
                "description": "株価への影響方向",
            },
            "confidence": {
                "type": "number",
                "description": "判定の確信度（0.0〜1.0）",
            },
            "reason": {
                "type": "string",
                "description": "判定根拠を本文から1〜2文で要約",
            },
        },
        "required": ["sentiment", "confidence", "reason"],
    },
}


def analyze_sentiment(article_text: str) -> dict:
    """ニュース記事を解析し、構造化されたセンチメント結果を返す。"""
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1024,
        tools=[SENTIMENT_TOOL],
        tool_choice={"type": "tool", "name": "report_sentiment"},
        messages=[{
            "role": "user",
            "content": f"以下のニュース記事のセンチメントを判定してください。\n\n{article_text}",
        }],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input
    raise ValueError("tool_useブロックが見つかりません")


if __name__ == "__main__":
    article = "トヨタ自動車が通期業績予想を上方修正したと発表した。"
    result = analyze_sentiment(article)
    print(json.dumps(result, ensure_ascii=False, indent=2))
```

OpenAIでは、同じスキーマを `response_format` に渡すことで
同様の効果が得られます（概要レベルの参考実装）。

```python
# OpenAI: response_formatで構造化出力を強制する（イメージ）
response = openai_client.chat.completions.create(
    model="gpt-5",
    messages=[{"role": "user", "content": prompt}],
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "sentiment_result",
            "schema": SENTIMENT_TOOL["input_schema"],
        },
    },
)
result = json.loads(response.choices[0].message.content)
```

### 悪い例

自由文で「JSON形式で」と頼み、そのまま `json.loads()` に
渡しています。Markdownのコードフェンスや前置き文が混ざると
例外が発生します。

```python
# 悪い例: 自由文でJSON形式を頼み、そのままパースする
prompt = "次の記事のセンチメントをJSON形式で出力してください。\n\n" + article_text
raw_text = call_llm(prompt)
result = json.loads(raw_text)  # ```json ... ``` などが混ざると例外になる
```

### 良い例

Tool useでスキーマを強制した、上記の `analyze_sentiment` 関数を
使います。出力形式がAPIレベルで保証されるため、パース失敗を
気にする必要がありません。

### 実行結果例

```text
{
  "sentiment": "positive",
  "confidence": 0.82,
  "reason": "通期業績予想の上方修正は増益見通しを示すため、株価にはポジティブな材料と判断した。"
}
```

## 演習課題

1. `SENTIMENT_TOOL` のスキーマに `impacted_sector`（影響セクター名）
   フィールドを追加してください。
2. `analyze_sentiment` が `tool_use` ブロックを見つけられなかった
   場合の挙動を、例外ではなくデフォルト値を返す実装に変更してください。
3. 自由文パース版と構造化出力版で、それぞれどのようなテストケースを
   書くべきか比較してください。

## 理解度チェック

- [ ] 自由文パースが失敗しやすい典型的なパターンを説明できる
- [ ] `tool_choice` で特定のツール呼び出しを強制する目的を説明できる
- [ ] `block.input` からスキーマ通りのデータを取得する流れを説明できる

---

投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。

[← 前へ: LLM APIのPython連携](02-llm-api-integration.md) | [次へ: レート制限・コスト管理 →](04-rate-limit-and-cost.md)
