# 株価データAPI連携（yfinance）

## この教材で身につくこと

- `yfinance` を使った株価データ（OHLCV）の取得方法
- `.info` 辞書から財務指標（PER・PBR・配当利回り等）を取得する方法
- 日本株のティッカー記法（東証は `.T` サフィックス）
- `.info` の項目欠損に対する防御的なコーディング方法

## 概要

LLMは学習データの知識カットオフ以降の株価を知りません。
リアルタイムに近い株価・財務データが必要な場合は、Pythonから
データ取得APIを直接呼び出す必要があります。

`yfinance` はYahoo Financeの株価・財務データを無料で取得できる
Pythonライブラリです。個人利用・学習用途で広く使われていますが、
非公式ライブラリであるため、レスポンス構造が予告なく変わることが
あります。本番運用では有償の市場データAPIも検討してください。

## 位置づけ

この教材は03-data-apiカテゴリの最初の教材です。
01-fundamentals/03-data-freshness.mdで学んだ「知識カットオフ問題」を、
実際のPythonコードで解決する最初のステップにあたります。

次の02-llm-api-integration.mdでは、ここで取得したデータをLLM APIに
渡して分析させる方法を学びます。

## 主要概念・パラメータ解説

### ティッカーの記法

`yfinance.Ticker()` に渡すシンボルは、取引所ごとにサフィックスが
異なります。

| 市場 | サフィックス | 例 |
|------|--------------|-----|
| 東京証券取引所 | `.T` | `7203.T`（トヨタ自動車） |
| 米国市場（NYSE/NASDAQ） | なし | `AAPL` |
| 香港証券取引所 | `.HK` | `0700.HK` |

### `history()` の主なパラメータ

```python
yfinance.Ticker("7203.T").history(period="1mo")
```

| パラメータ | 説明 | 主な値 |
|-----------|------|--------|
| `period` | 取得期間 | `1d`, `5d`, `1mo`, `3mo`, `6mo`, `1y`, `2y`, `5y`, `10y`, `ytd`, `max` |
| `interval` | 足の間隔 | `1m`, `5m`, `15m`, `1h`, `1d`, `1wk`, `1mo` |
| `start` / `end` | 期間を日付で直接指定 | `"2026-01-01"` など |

戻り値は `Open` `High` `Low` `Close` `Volume` を列に持つ
pandasのDataFrameです。

### `.info` の主な財務指標フィールド

`.info` はYahoo Financeが持つ企業情報を辞書として返します。
銘柄によっては存在しないフィールドがあり、値が `None` の場合も
あります。

| フィールド | 説明 |
|-----------|------|
| `trailingPE` | 実績PER（株価収益率） |
| `priceToBook` | PBR（株価純資産倍率） |
| `dividendYield` | 配当利回り（小数、`0.03` は3%を意味する） |
| `marketCap` | 時価総額（円） |
| `longName` | 正式企業名 |
| `sector` | セクター（業種分類） |
| `currency` | 取引通貨 |

## 実ソースコード（Python / プロンプト例）

```python
import yfinance as yf


def fetch_price_history(ticker_symbol: str, period: str = "1mo"):
    """指定ティッカーの株価データ（OHLCV）を取得する。"""
    ticker = yf.Ticker(ticker_symbol)
    return ticker.history(period=period)


def fetch_fundamentals(ticker_symbol: str) -> dict:
    """財務指標を防御的に取得する。存在しない項目はNoneを返す。"""
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info
    return {
        "name": info.get("longName"),
        "trailing_pe": info.get("trailingPE"),
        "price_to_book": info.get("priceToBook"),
        "dividend_yield": info.get("dividendYield"),
        "market_cap": info.get("marketCap"),
    }


if __name__ == "__main__":
    symbol = "7203.T"  # トヨタ自動車（東証）

    history = fetch_price_history(symbol, period="1mo")
    print(history.tail(3)[["Open", "High", "Low", "Close", "Volume"]])

    fundamentals = fetch_fundamentals(symbol)
    for key, value in fundamentals.items():
        print(f"{key}: {value}")
```

### 悪い例

`.info` のキーに直接アクセスすると、銘柄によっては
`KeyError` が発生したり、値が `None` のまま演算に使われて
`TypeError` になります。

```python
# 悪い例: 存在確認なしにキーへ直接アクセスする
ticker = yf.Ticker("XXXX.T")
pe = ticker.info["trailingPE"]
if pe < 15:
    print("割安と判定")
```

### 良い例

`.get()` でデフォルト値を指定し、演算前に `None` チェックを
入れることで、欠損データによるクラッシュを防ぎます。

```python
# 良い例: .get()で取得し、使用前にNoneチェックする
ticker = yf.Ticker("XXXX.T")
pe = ticker.info.get("trailingPE")
if pe is not None and pe < 15:
    print("割安と判定")
else:
    print("PERが取得できないため判定不可")
```

### 実行結果例

```text
                                 Open        High         Low       Close    Volume
Date
2026-07-16 00:00:00+09:00  2895.0000  2921.0000  2884.5000  2910.0000  18234500
2026-07-17 00:00:00+09:00  2912.0000  2935.0000  2905.0000  2928.0000  15872300
2026-07-18 00:00:00+09:00  2930.0000  2948.0000  2918.0000  2941.0000  14209100
name: トヨタ自動車株式会社
trailing_pe: 10.82
price_to_book: 1.14
dividend_yield: 0.0289
market_cap: 41235000000000
```

## 演習課題

1. `fetch_price_history` に `interval` パラメータを追加し、
   週足（`1wk`）でも取得できるように拡張してください。
2. `.info` の `sector` と `currency` を含めた
   `fetch_fundamentals` の拡張版を書いてください。
3. `dividendYield` が `None` の場合に「配当情報なし」と
   表示するコードを追加してください。

## 理解度チェック

- [ ] 日本株のティッカーに `.T` サフィックスが必要な理由を説明できる
- [ ] `.info` の値が欠損する可能性がある理由を説明できる
- [ ] `.get()` と直接キーアクセスの違いを、例外の観点から説明できる

---

投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。

[← 前へ: 03-data-api](00-README.md) | [次へ: LLM APIのPython連携 →](02-llm-api-integration.md)
