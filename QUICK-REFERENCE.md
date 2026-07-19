# クイックリファレンス

チュートリアル全体で扱うAPI・ライブラリ・概念の早見表です。

## 主要ライブラリ

| ライブラリ | 用途 | インストール |
|-----------|------|--------------|
| `yfinance` | 株価・財務データ取得 | `pip install yfinance` |
| `anthropic` | Claude APIクライアント | `pip install anthropic` |
| `openai` | OpenAI APIクライアント | `pip install openai` |
| `pandas` | 時系列データ処理 | `pip install pandas` |
| `mcp` | MCPサーバー/クライアントSDK | `pip install mcp` |

## LLM APIの基本呼び出し比較

| 項目 | Anthropic (Claude) | OpenAI |
|------|--------------------|--------|
| クライアント | `anthropic.Anthropic()` | `openai.OpenAI()` |
| メッセージ送信 | `client.messages.create()` | `client.chat.completions.create()` |
| ツール呼び出し | `tools` パラメータ + `tool_use` | `tools` パラメータ + `tool_calls` |
| 構造化出力 | `tool_use` で強制 | `response_format={"type":"json_schema"}` |

## プロンプト設計パターン早見表

| パターン | 用途 | 詳細 |
|---------|------|------|
| 決算書要約 | 決算短信・有価証券報告書の要点抽出 | [02-prompt-patterns/01](docs/02-prompt-patterns/01-earnings-summary-prompts.md) |
| センチメント分析 | ニュース記事の株価インパクト評価 | [02-prompt-patterns/02](docs/02-prompt-patterns/02-news-sentiment-prompts.md) |
| スクリーニング条件言語化 | 自然文をフィルタ条件に変換 | [02-prompt-patterns/03](docs/02-prompt-patterns/03-stock-screening-prompts.md) |
| レポート自動生成 | 複数データソースを統合したレポート化 | [02-prompt-patterns/04](docs/02-prompt-patterns/04-report-generation-prompts.md) |

## 生成AI活用の核心ルール

| # | 原則 | 内容 |
|---|------|------|
| 1 | 一次情報で裏付け | AI出力は必ず開示情報・公式データで検証する |
| 2 | 構造化出力を使う | 自由文ではなくJSON/Tool useで解析可能な形にする |
| 3 | 知識カットオフに注意 | 最新の株価・ニュースは必ずAPI経由で取得する |
| 4 | コストを見積もる | トークン数とAPI呼び出し回数を事前に見積もる |
| 5 | 投資助言と誤解させない | 出力に免責事項・不確実性を明記する |

## MCPサーバー設計の基本構成

```
mcp-stock-server/
  ├── server.py       # MCPサーバー本体（ツール定義）
  ├── tools/
  │   ├── price.py     # 株価取得ツール
  │   └── fundamentals.py # 財務指標取得ツール
  └── requirements.txt
```
