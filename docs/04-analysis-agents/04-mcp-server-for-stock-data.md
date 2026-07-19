# 株式データMCPサーバー構築

## この教材で身につくこと

- MCP（Model Context Protocol）の役割と基本構成の理解
- `FastMCP` を使った最小構成のMCPサーバー実装方法
- ツール設計の粒度（単機能ツール vs 万能ツール）の判断基準

## 概要

MCP（Model Context Protocol）は、AIクライアントが外部ツールを
発見・呼び出すための標準プロトコルです。
株価取得処理をMCPサーバーのツールとして公開すると、
Claude DesktopやClaude CodeなどMCP対応クライアントのLLMが、
必要に応じて自動的にそのツールを呼び出せるようになります。
AI製品ごとに個別の連携コードを書く必要がなくなる点が利点です。

## 位置づけ

これまでの教材で作成した `fetch_fundamentals` や
`compute_ma_crossover` の元になっている、
[03-data-api/01-stock-price-api.md](../03-data-api/01-stock-price-api.md)
のyfinance連携をMCPツールとして再構成します。

## 主要概念・パラメータ解説

### MCPサーバーの基本構成

[QUICK-REFERENCE.md](../../QUICK-REFERENCE.md) で示した構成に従います。

```text
mcp-stock-server/
  ├── server.py            # MCPサーバー本体（ツール登録）
  ├── tools/
  │   ├── price.py          # 株価取得ツール
  │   └── fundamentals.py   # 財務指標取得ツール
  └── requirements.txt
```

### FastMCPの主要要素

| 要素 | 役割 |
|------|------|
| `FastMCP("サーバー名")` | サーバーインスタンスの作成 |
| `@mcp.tool()` | 関数をMCPツールとして公開するデコレータ |
| 関数のdocstring | クライアントLLMに渡されるツールの説明文になる |
| 型ヒント | 引数の型情報がツールのスキーマとして公開される |
| `mcp.run()` | サーバープロセスの起動 |

## 実ソースコード

### ツール本体（tools/price.py）

```python
import yfinance as yf


def get_stock_price(ticker: str) -> dict:
    """指定したティッカーシンボルの直近株価を取得する"""
    info = yf.Ticker(ticker).fast_info
    return {
        "ticker": ticker,
        "last_price": info.last_price,
        "currency": info.currency,
    }
```

### サーバー本体（server.py）

```python
from mcp.server.fastmcp import FastMCP
from tools.price import get_stock_price

mcp = FastMCP("stock-data-server")
mcp.tool()(get_stock_price)

if __name__ == "__main__":
    mcp.run()
```

### requirements.txt

```text
mcp
yfinance
```

### サーバーの起動

```bash
cd mcp-stock-server
pip install -r requirements.txt
python server.py
```

### MCPクライアントへの登録例

以下はMCP対応クライアントの設定ファイルに登録するイメージです。
実際のキー名・形式は利用するクライアントのバージョンにより
異なるため、各クライアントの公式ドキュメントを確認してください。

```json
{
  "mcpServers": {
    "stock-data": {
      "command": "python",
      "args": ["mcp-stock-server/server.py"]
    }
  }
}
```

### クライアントからの呼び出し例

MCPクライアント側のLLMが `get_stock_price` ツールを選択し、
`ticker` 引数を渡して呼び出した際の応答イメージです。

```json
{
  "tool": "get_stock_price",
  "arguments": { "ticker": "7203.T" },
  "result": {
    "ticker": "7203.T",
    "last_price": 2984.5,
    "currency": "JPY"
  }
}
```

### 良い例 / 悪い例

```text
悪い例:
get_stock_data(ticker, mode) のような1つの万能ツールを作り、
modeに"price"/"fundamentals"/"news"を渡して切り替える
→ 引数の意味が曖昧で、呼び出し側LLMがmodeの値を
  誤って選択しやすい
```

```text
良い例:
get_stock_price(ticker) と get_fundamentals(ticker) を
別々の単機能ツールとして定義する
→ 各ツールの役割が明確なため、呼び出し側LLMが
  質問内容に応じて正しいツールを選択しやすい
```

## 演習課題

1. `tools/fundamentals.py` に `get_fundamentals(ticker: str) -> dict`
   を実装し、`server.py` に登録せよ
2. `get_stock_price` にティッカーが存在しない場合のエラー処理を
   追加せよ
3. MCPクライアントから「トヨタの株価を教えて」と聞かれた場合に、
   `get_stock_price` がどう呼び出されるか流れを図示せよ

## 理解度チェック

- [ ] MCPが解決する課題（クライアントごとの個別連携）を
      説明できる
- [ ] `@mcp.tool()` を付けた関数がどのように公開されるか
      説明できる
- [ ] ツールを単機能に分割するメリットを説明できる

---

投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。

[← 前へ: ニュースリサーチエージェント](03-news-research-agent.md) | [次へ: ポートフォリオ管理 →](../05-portfolio-management/00-README.md)
