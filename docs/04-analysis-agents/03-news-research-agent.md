# ニュースリサーチエージェント

## この教材で身につくこと

- 複数のニュース記事を1件ずつセンチメント分析する設計方法
- 個別分析の結果をプログラム側で集計するパターン
- 大量の記事を1つの巨大プロンプトにまとめることのリスク

## 概要

ニュースリサーチエージェントは、対象銘柄に関する複数の記事を
取得し、記事ごとにセンチメントを判定したうえで、
全体の傾向を件数と代表例として集計するプログラムです。

## 位置づけ

センチメント判定には [02-prompt-patterns/02-news-sentiment-prompts.md](../02-prompt-patterns/02-news-sentiment-prompts.md)
で学んだプロンプトパターンをそのまま再利用します。
構造化出力の取得方法は [03-data-api/03-structured-output.md](../03-data-api/03-structured-output.md)
を参照してください。

## 主要概念・パラメータ解説

### エージェントの処理フロー

| ステップ | 処理内容 |
|---------|---------|
| 1. 記事取得 | `fetch_recent_news(query)` で記事一覧を取得 |
| 2. 個別分析 | 記事ごとにセンチメント判定プロンプトを実行 |
| 3. 集計 | positive/negative/neutralの件数と代表見出しを集計 |
| 4. サマリ生成 | 集計結果を1つのdictにまとめて返す |

### fetch_recent_newsの戻り値の形

| キー | 型 | 内容 |
|------|-----|------|
| `title` | `str` | 記事見出し |
| `body` | `str` | 記事本文（抜粋） |
| `published_at` | `str` | 公開日時（ISO 8601形式を想定） |

> `fetch_recent_news` は実際にはニュースAPI等を呼び出す関数です。
> API連携部分は本教材の範囲外のため、ここではインターフェースのみ示します。

## 実ソースコード

### 記事取得のインターフェース

```python
def fetch_recent_news(query: str) -> list[dict]:
    """
    企業名/ティッカーに関連する直近ニュースを取得する。
    実装は利用するニュースAPIに依存するため、ここでは
    戻り値の形だけを示すプレースホルダーとする。
    """
    raise NotImplementedError("ニュースAPIとの連携は別途実装してください")
```

### 個別分析と集計

```python
from llm_client import call_llm_structured  # 03-structured-outputで定義
from news_sentiment_prompts import (  # 02-news-sentiment-promptsで定義
    build_sentiment_prompt,
    SENTIMENT_TOOL_SCHEMA,
)


def analyze_news_sentiment(query: str) -> dict:
    articles = fetch_recent_news(query)

    results = []
    for article in articles:
        prompt = build_sentiment_prompt(article["title"], article["body"])
        sentiment = call_llm_structured(prompt, tool_schema=SENTIMENT_TOOL_SCHEMA)
        results.append({**sentiment, "title": article["title"]})

    summary = {"positive": [], "negative": [], "neutral": []}
    for r in results:
        summary[r["sentiment"]].append(r["title"])

    return {
        "query": query,
        "total_articles": len(articles),
        "counts": {k: len(v) for k, v in summary.items()},
        "examples": {k: v[:3] for k, v in summary.items()},
    }
```

### 実行結果例

```python
summary = analyze_news_sentiment("トヨタ自動車")
```

```json
{
  "query": "トヨタ自動車",
  "total_articles": 12,
  "counts": { "positive": 5, "negative": 3, "neutral": 4 },
  "examples": {
    "positive": [
      "トヨタ、EV新工場の稼働率が計画を上回る",
      "トヨタ株、増配発表を受け上昇"
    ],
    "negative": [
      "トヨタ、一部サプライヤーで品質問題が発覚"
    ],
    "neutral": [
      "トヨタ、来月の決算発表日程を公表"
    ]
  }
}
```

### 良い例 / 悪い例

```text
悪い例:
記事12件の見出しと本文をすべて1つのプロンプトに詰め込み、
「全体のセンチメントを教えてください」と一度に依頼する
→ 記事間で論調が異なる場合に信号が混ざりやすく、
  記事数が増えるとコンテキスト上限にも達しやすい
```

```text
良い例:
記事を1件ずつセンチメント判定し、結果をPython側で
件数集計・代表例抽出する
→ 各記事の判定根拠が個別に検証可能で、
  記事数が増えても集計処理は線形にスケールする
```

## 演習課題

1. `analyze_news_sentiment` の集計結果に、直近3日以内の記事だけを
   対象とするフィルタを追加せよ
2. センチメントが偏った場合（例: negativeが80%以上）に
   警告フラグを立てる処理を追加せよ
3. 記事本文が長すぎる場合に、要約してからセンチメント判定に
   渡す前処理ステップを設計せよ

## 理解度チェック

- [ ] 複数記事のセンチメントを1つの巨大プロンプトで
      分析すべきでない理由を説明できる
- [ ] `analyze_news_sentiment` の集計処理がどこで
      行われているか説明できる
- [ ] `fetch_recent_news` が本教材でプレースホルダーになっている
      理由を説明できる

---

投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。

[← 前へ: テクニカル分析エージェント](02-technical-analysis-agent.md) | [次へ: 株式データMCPサーバー構築 →](04-mcp-server-for-stock-data.md)
