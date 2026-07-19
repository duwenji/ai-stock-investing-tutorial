# レート制限・コスト管理

## この教材で身につくこと

- トークン数の概算方法と日本語特有の注意点
- API呼び出しコストの見積もり方の考え方
- レート制限エラーへの指数バックオフによる再試行実装
- 呼び出し回数・コストを抑える実務上のテクニック

## 概要

LLM APIはトークン数と呼び出し回数に応じて課金されます。
数十〜数百銘柄を1件ずつ問い合わせるコードは、想定以上の
コストやレート制限エラー（429）に直面しやすくなります。

この教材では、コストを見積もる考え方と、レート制限に対する
再試行実装、呼び出し回数を抑えるテクニックを学びます。

## 位置づけ

この教材は03-data-apiカテゴリの最後です。
02-llm-api-integration.mdの `call_llm(prompt: str) -> str` と、
03-structured-output.mdの構造化出力を前提に、実運用で
壊れない呼び出し方法を学びます。

次の04-analysis-agentsでは、複数銘柄を扱うエージェントを
構築しますが、その前提としてここで学ぶコスト管理・レート制限
対応が必要になります。

## 主要概念・パラメータ解説

### トークン数の目安

| 言語 | 目安 | 備考 |
|------|------|------|
| 英語 | 約4文字で1トークン | トークン効率が比較的良い |
| 日本語 | 1〜2文字で1トークンになることが多い | 同じ内容でも英語よりトークン数が増えやすい |

日本語のプロンプトを設計する際は、英語より少ない文字数でも
多くのトークンを消費する前提で見積もる必要があります。

### コスト見積もりの考え方

| 要素 | 内容 |
|------|------|
| 入力トークン数 | システムプロンプト・データを含むプロンプト全体の量 |
| 出力トークン数 | `max_tokens` で上限を設定し、実際の生成量で課金される |
| 単価（1トークンあたりの料金） | モデルごとに異なり、変更されることがある |
| 呼び出し回数 | 銘柄数 × 分析回数などの掛け算で見積もる |

> 料金は変更されるため、本教材では具体的な単価を記載しません。
> 必ず公式ページで最新の料金を確認してください。

### コスト削減の主なテクニック

| テクニック | 内容 |
|-----------|------|
| バッチ処理でAPI呼び出し回数を削減 | 複数銘柄を1回のプロンプトにまとめて問い合わせる |
| プロンプトを簡潔にする | 不要な文脈・重複した説明を削る |
| キャッシュして同じ問い合わせを繰り返さない | 同一入力の結果を保存し、再利用する |
| `max_tokens` を用途に応じて絞る | 分類など短い出力で十分なタスクは小さく設定する |

## 実ソースコード（Python / プロンプト例）

```python
import os
import random
import time

import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def call_llm(prompt: str) -> str:
    """Claude APIにプロンプトを送信し、応答テキストを返す。"""
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def call_llm_with_backoff(
    prompt: str,
    max_retries: int = 5,
    base_delay: float = 1.0,
) -> str:
    """レート制限エラー時に指数バックオフで再試行するラッパー。"""
    for attempt in range(max_retries):
        try:
            return call_llm(prompt)
        except anthropic.RateLimitError:
            delay = base_delay * (2**attempt) + random.uniform(0, 1)
            print(f"レート制限中: {delay:.1f}秒後に再試行します（{attempt + 1}回目）")
            time.sleep(delay)
    raise RuntimeError("再試行回数の上限に達しました")


if __name__ == "__main__":
    text = call_llm_with_backoff("トヨタ自動車の直近ニュースを1文で要約してください。")
    print(text)
```

### 悪い例

数百銘柄をループで1件ずつ問い合わせており、再試行もキャッシュも
ありません。銘柄数がそのままAPI呼び出し回数になり、コストと
レート制限エラーのリスクが増大します。

```python
# 悪い例: 数百銘柄を1件ずつ問い合わせ、再試行もキャッシュもない
results = {}
for symbol in ticker_list:  # 数百件
    prompt = f"{symbol}のニュースセンチメントを判定してください。"
    results[symbol] = call_llm(prompt)  # 呼び出し回数が銘柄数と同じになる
```

### 良い例

複数銘柄をまとめて1回のプロンプトに含め、キャッシュと
バックオフ付きの呼び出しを併用しています。

```python
# 良い例: 複数銘柄を1回のプロンプトにまとめ、キャッシュも併用する
cache: dict[str, str] = {}


def analyze_batch(symbols: list[str]) -> None:
    targets = [s for s in symbols if s not in cache]
    if not targets:
        return
    prompt = "次の銘柄ごとにニュースセンチメントを判定してください: " + ", ".join(targets)
    result_text = call_llm_with_backoff(prompt)
    for symbol in targets:
        cache[symbol] = result_text  # 実際にはsymbol単位にパースして格納する
```

### 実行結果例

```text
レート制限中: 1.4秒後に再試行します（1回目）
レート制限中: 2.7秒後に再試行します（2回目）
トヨタ自動車は北米工場への追加投資を発表した。
```

## 演習課題

1. `call_llm_with_backoff` に、再試行上限に達した際のログ出力を
   追加してください。
2. `analyze_batch` を拡張し、応答テキストを銘柄ごとにパースして
   `cache` に個別格納するようにしてください（03-structured-output.md
   の構造化出力を活用してください）。
3. 100銘柄を1件ずつ問い合わせる場合と、10銘柄ずつバッチ化する場合で、
   API呼び出し回数がどう変わるか計算してください。

## 理解度チェック

- [ ] 日本語プロンプトが英語よりトークンを消費しやすい理由を説明できる
- [ ] 指数バックオフがレート制限対策として有効な理由を説明できる
- [ ] バッチ処理とキャッシュがコスト削減にどう寄与するか説明できる

---

投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。

[← 前へ: 構造化出力・Tool use](03-structured-output.md) | [次へ: 04-analysis-agents →](../04-analysis-agents/00-README.md)
