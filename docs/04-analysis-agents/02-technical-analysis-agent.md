# テクニカル分析エージェント

## この教材で身につくこと

- pandasで移動平均線・RSIなどのテクニカル指標を計算する方法
- 計算済みの数値をLLMに渡し、解釈・説明させる設計パターン
- LLMに直接数値計算をさせてはいけない理由

## 概要

テクニカル分析エージェントは、価格データから指標を計算し、
その結果をLLMに解釈させるプログラムです。
指標の計算は必ずPython側（pandas）で行い、LLMには計算済みの
数値の意味を説明させる役割だけを与えます。

## 位置づけ

[03-data-api/01-stock-price-api.md](../03-data-api/01-stock-price-api.md) で
学んだyfinanceの価格取得を土台にします。
LLMへの説明生成には [03-data-api/02-llm-api-integration.md](../03-data-api/02-llm-api-integration.md)
の `call_llm` を使用します。

## 主要概念・パラメータ解説

### なぜLLMに計算させないのか

LLMはトークン単位でテキストを生成するモデルであり、
桁数の多い数値の四則演算や統計計算を苦手とします。
移動平均やRSIのような指標は、Python側で正確に計算し、
LLMには「計算結果の解釈」のみを担当させます。

### ゴールデンクロス/デッドクロス判定

| 用語 | 意味 |
|------|------|
| 短期移動平均線 | 直近N日の終値の単純移動平均（例: 25日） |
| 長期移動平均線 | 直近M日の終値の単純移動平均（例: 75日） |
| ゴールデンクロス | 短期線が長期線を下から上に抜けること |
| デッドクロス | 短期線が長期線を上から下に抜けること |

### compute_ma_crossover関数の入出力

| 項目 | 型 | 内容 |
|------|-----|------|
| 引数 `ticker` | `str` | 対象銘柄のティッカーシンボル |
| 引数 `short_window` | `int` | 短期移動平均の日数（既定25） |
| 引数 `long_window` | `int` | 長期移動平均の日数（既定75） |
| 戻り値 `ma_short` / `ma_long` | `float` | 直近の移動平均値 |
| 戻り値 `golden_cross` / `dead_cross` | `bool` | クロス発生の有無 |

## 実ソースコード

### 指標の計算（Python/pandas）

```python
import pandas as pd
import yfinance as yf


def compute_ma_crossover(
    ticker: str, short_window: int = 25, long_window: int = 75
) -> dict:
    hist = yf.Ticker(ticker).history(period="6mo")
    hist["ma_short"] = hist["Close"].rolling(short_window).mean()
    hist["ma_long"] = hist["Close"].rolling(long_window).mean()

    latest, prev = hist.iloc[-1], hist.iloc[-2]
    golden_cross = (
        prev["ma_short"] <= prev["ma_long"]
        and latest["ma_short"] > latest["ma_long"]
    )
    dead_cross = (
        prev["ma_short"] >= prev["ma_long"]
        and latest["ma_short"] < latest["ma_long"]
    )

    return {
        "ticker": ticker,
        "ma_short": round(float(latest["ma_short"]), 2),
        "ma_long": round(float(latest["ma_long"]), 2),
        "golden_cross": bool(golden_cross),
        "dead_cross": bool(dead_cross),
    }
```

### 計算結果をLLMに解釈させる

```python
from llm_client import call_llm  # 03-llm-api-integrationで定義


def explain_technical_signal(signal: dict) -> str:
    prompt = f"""
以下は既にPythonで正確に計算済みの移動平均線データです。
数値の再計算は不要です。この結果が示す意味を、
投資初心者にも分かるよう平易な言葉で説明してください。
断定的な売買判断は避け、あくまで指標の解釈として説明してください。

{signal}
"""
    return call_llm(prompt)
```

### 実行結果例

```python
signal = compute_ma_crossover("7203.T")
explanation = explain_technical_signal(signal)
```

```json
{
  "ticker": "7203.T",
  "ma_short": 2951.4,
  "ma_long": 2887.1,
  "golden_cross": true,
  "dead_cross": false
}
```

```text
25日移動平均線（2951.4円）が75日移動平均線（2887.1円）を
上抜けし、ゴールデンクロスが発生しています。
一般的に短期的な上昇トレンドへの転換を示すサインとされますが、
出来高や他の指標と合わせて確認することが望まれます。
```

### 良い例 / 悪い例

```text
悪い例:
「直近25日の終値[2940, 2955, ...]からRSIを計算し、
買われすぎか判定してください」
→ LLMが生の数値列から統計計算を行うため、
  誤差や計算ミスが発生しやすい
```

```text
良い例:
「pandasで計算したRSI値は58.3です。この数値が
何を意味するか説明してください」
→ 計算はPython側で正確に行い、LLMは解釈のみを担当する
```

## 演習課題

1. `compute_ma_crossover` を参考に、RSI（相対力指数）を
   `pandas` で計算する関数 `compute_rsi(ticker, period=14)` を書け
2. `explain_technical_signal` のプロンプトに、RSIの計算結果も
   渡して複合的な説明を生成させよ
3. ゴールデンクロス・デッドクロスのどちらでもない場合の
   説明文が不自然にならないよう、プロンプトを調整せよ

## 理解度チェック

- [ ] LLMに直接テクニカル指標を計算させてはいけない理由を
      説明できる
- [ ] ゴールデンクロス・デッドクロスの判定条件を説明できる
- [ ] 計算結果とLLMの解釈を分離する設計のメリットを説明できる

---

投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。

[← 前へ: ファンダメンタル分析エージェント](01-fundamental-analysis-agent.md) | [次へ: ニュースリサーチエージェント →](03-news-research-agent.md)
