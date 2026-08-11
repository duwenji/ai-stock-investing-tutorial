# ファンダメンタル分析エージェント

## この教材で身につくこと

- yfinanceで取得した財務指標をもとにプロンプトを組み立てる方法
- 構造化出力パターンで割安/妥当/割高の判定結果を得る方法
- LLMの記憶ではなく取得データのみで推論させる設計の重要性

## 概要

ファンダメンタル分析エージェントは、企業の財務指標を取得し、
その数値のみを根拠にLLMへ判定させるプログラムです。
PERやPBRは絶対値だけでなく、セクター平均との比較が重要です。
本教材では、この比較をプロンプトに組み込む方法を学びます。

## 位置づけ

[03-data-api/01-stock-price-api.md](../03-data-api/01-stock-price-api.md) の
yfinance連携と、[03-data-api/03-structured-output.md](../03-data-api/03-structured-output.md) の
構造化出力パターンを組み合わせて実装します。
LLM出力の検証方法は [01-fundamentals/02-hallucination-and-verification.md](../01-fundamentals/02-hallucination-and-verification.md)
を参照してください。

## 主要概念・パラメータ解説

### エージェントが守るべき原則

| 原則 | 内容 |
|------|------|
| データ根拠の明示 | プロンプトに含めたデータのみを判定根拠とする |
| 記憶からの補完禁止 | LLMが学習時点で知っている企業情報を使わせない |
| 比較基準の明示 | セクター平均等、判定の物差しを必ず数値で渡す |
| 構造化出力の強制 | 自由文ではなくtool_useで判定結果を固定フォーマット化する |

### analyze_fundamentals関数の入出力

| 項目 | 型 | 内容 |
|------|-----|------|
| 引数 `ticker` | `str` | 対象銘柄のティッカーシンボル |
| 引数 `sector_avg_per` | `float` | セクター平均PER（呼び出し側が用意） |
| 引数 `sector_avg_pbr` | `float` | セクター平均PBR（呼び出し側が用意） |
| 戻り値 `verdict` | `str` | `"割安"` / `"妥当"` / `"割高"` のいずれか |
| 戻り値 `rationale` | `str` | 判定理由（データに基づく説明文） |
| 戻り値 `key_metrics_used` | `list[str]` | 判定に使用した指標名の一覧 |

## 実ソースコード

### データ取得と判定関数

```python
import yfinance as yf
from llm_client import call_llm_structured  # 03-structured-outputで定義

FUNDAMENTAL_TOOL_SCHEMA = {
    "name": "fundamental_verdict",
    "description": "ファンダメンタル分析の結果を構造化して返す",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["割安", "妥当", "割高"],
            },
            "rationale": {"type": "string"},
            "key_metrics_used": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["verdict", "rationale", "key_metrics_used"],
    },
}


def fetch_fundamentals(ticker: str) -> dict:
    """yfinanceから財務指標のみを取得する（推測を含まない）"""
    info = yf.Ticker(ticker).info
    return {
        "ticker": ticker,
        "trailing_pe": info.get("trailingPE"),
        "price_to_book": info.get("priceToBook"),
        "sector": info.get("sector"),
        "market_cap": info.get("marketCap"),
    }


def analyze_fundamentals(
    ticker: str, sector_avg_per: float, sector_avg_pbr: float
) -> dict:
    data = fetch_fundamentals(ticker)

    prompt = f"""
あなたは株式のファンダメンタル分析を行うアシスタントです。
以下は取得済みの実データです。この情報のみに基づいて判定してください。
記憶にある企業情報や一般知識で数値を補完しないでください。
不足しているデータがある場合は、その旨をrationaleに明記してください。

# 対象銘柄データ
{data}

# セクター平均（参考値）
PER平均: {sector_avg_per}
PBR平均: {sector_avg_pbr}

上記データのみを根拠に、割安・妥当・割高のいずれかを判定してください。
"""
    return call_llm_structured(prompt, tool_schema=FUNDAMENTAL_TOOL_SCHEMA)
```

### 実行結果例

```python
result = analyze_fundamentals("7203.T", sector_avg_per=14.2, sector_avg_pbr=1.1)
```

```json
{
  "verdict": "割安",
  "rationale": "PER 9.8倍はセクター平均14.2倍を大きく下回る。PBR 0.9倍もセクター平均1.1倍を下回り、株価は純資産に対して割安な水準にある。",
  "key_metrics_used": ["trailing_pe", "price_to_book"]
}
```

### 良い例 / 悪い例

```text
良い例:
「以下のデータ（PER 9.8, PBR 0.9, セクター平均PER 14.2,
セクター平均PBR 1.1）のみに基づいて割安/妥当/割高を判定してください」
→ 判定根拠が検証可能で、ハルシネーションのリスクが低い
```

```text
悪い例:
「この銘柄（7203.T）は買いですか、売りですか？」
→ データを渡していないため、LLMは学習時点の記憶や
  一般論で回答してしまう。最新の財務状況を反映できない
```

## 演習課題

1. `fetch_fundamentals` に配当利回り（`dividendYield`）を追加し、
   判定プロンプトに組み込め
2. セクター平均を固定値ではなく、複数銘柄の平均から動的に計算する
   関数を書け
3. `analyze_fundamentals` の戻り値のうち、`key_metrics_used` が
   実際に渡したデータに含まれるか検証するチェック処理を追加せよ

## 理解度チェック

- [ ] LLMに判定させる際、なぜ記憶ではなく取得データのみを
      根拠にすべきか説明できる
- [ ] `analyze_fundamentals` の戻り値がどのように構造化されるか
      説明できる
- [ ] セクター平均のような比較基準をプロンプトに含める理由を
      説明できる

---

投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。

[← 前へ: 04-analysis-agents](00-README.md) | [次へ: テクニカル分析エージェント →](02-technical-analysis-agent.md)
