# AIによるポートフォリオ分析

## この教材で身につくこと

- 保有銘柄をPythonのデータ構造（辞書のリスト/DataFrame）で表現する方法
- 評価額・損益・セクター別構成比をpandasで集計する方法
- 集計済みの数値をLLMに渡し、自然言語で要約・傾向指摘させる設計

## 概要

ポートフォリオ管理では、複数銘柄の保有状況を一度に把握する必要があります。
銘柄数が増えるほど、構成比や損益の全体像を人手で読み取るのは大変になります。

LLMは大量の数値を一覧しながら「特徴を言語化する」作業が得意です。
ただし、割合や損益の計算自体は苦手です。本教材では、集計はPythonで行い、
LLMには集計結果の解釈だけを任せる設計を扱います。

## 位置づけ

この教材は05-portfolio-managementカテゴリの最初の教材です。
03-data-apiで学んだ `yfinance` によるデータ取得と、04-analysis-agentsで
確立した「Pythonが計算し、LLMが説明する」原則を、単一銘柄からポートフォリオ
全体へと拡張します。

次の02-risk-assessment.mdでは、同じポートフォリオを対象に
ボラティリティ・相関係数などのリスク指標を扱います。

## 主要概念・パラメータ解説

### ポートフォリオの表現

保有銘柄は、次のような辞書のリストで表現します。

| キー | 内容 | 例 |
|------|------|-----|
| `ticker` | ティッカーシンボル | `"7203.T"` |
| `shares` | 保有株数 | `100` |
| `avg_cost` | 平均取得単価（円） | `2100.0` |

### Pythonで集計する指標

| 指標 | 計算方法 | 用途 |
|------|----------|------|
| 現在評価額 | `現在株価 × 保有株数` | 銘柄ごとの時価を把握する |
| 構成比 | `銘柄評価額 ÷ ポートフォリオ合計評価額` | 資産配分の偏りを把握する |
| 損益 | `(現在株価 - 平均取得単価) × 保有株数` | 含み損益を把握する |
| セクター別構成比 | セクターごとに評価額を合計し全体で割る | 業種の集中度を把握する |

セクター情報は `yfinance` の `Ticker.info["sector"]` から取得できます。
値が取得できない銘柄は `"Unknown"` として扱い、処理を止めないようにします。

### LLMに渡す情報とプロンプト設計

LLMには「計算済みの表」だけを渡し、計算そのものは依頼しません。
依頼するのは、次のような自然言語での要約・傾向指摘に限定します。

- 構成比の偏りがないかのコメント
- 損益が大きい銘柄・セクターへの言及
- 一般的な分散投資の観点からの気付き（個別助言ではない）

## 実ソースコード（Python / プロンプト例）

### 悪い例

構成比の計算をLLMに任せています。銘柄数が増えると誤った暗算をする
リスクがあり、パーセンテージの合計が100%にならないこともあります。

```text
以下は保有銘柄と評価額です。それぞれの構成比(%)を計算し、
偏りがあればコメントしてください。

- トヨタ自動車: 450,000円
- ソニーグループ: 320,000円
- 任天堂: 230,000円
```

### 良い例

構成比はPythonで計算済みの数値としてプロンプトに埋め込み、
LLMには解釈・コメントだけを依頼しています。

```text
以下は保有ポートフォリオの構成比（Python側で計算済み）です。
数値の再計算は不要です。構成比の偏りやセクター集中について、
一般的な観点から3行以内でコメントしてください。
個別の売買判断や具体的な推奨は行わないでください。

【構成比データ】
- トヨタ自動車 (7203.T): 45.0%（自動車セクター）
- ソニーグループ (6758.T): 32.0%（テクノロジーセクター）
- 任天堂 (7974.T): 23.0%（テクノロジーセクター）

【セクター別構成比】
- 自動車: 45.0%
- テクノロジー: 55.0%
```

### ポートフォリオ集計とLLM要約の実装

```python
import pandas as pd
import yfinance as yf


def build_portfolio_df(holdings: list[dict]) -> pd.DataFrame:
    """保有銘柄リストから評価額・損益・構成比のDataFrameを作る。"""
    rows = []
    for h in holdings:
        ticker = yf.Ticker(h["ticker"])
        price = ticker.history(period="1d")["Close"].iloc[-1]
        sector = ticker.info.get("sector", "Unknown")
        market_value = price * h["shares"]
        cost_basis = h["avg_cost"] * h["shares"]
        rows.append({
            "ticker": h["ticker"],
            "sector": sector,
            "shares": h["shares"],
            "price": round(price, 2),
            "market_value": round(market_value, 2),
            "pnl": round(market_value - cost_basis, 2),
        })
    df = pd.DataFrame(rows)
    total = df["market_value"].sum()
    df["weight_pct"] = (df["market_value"] / total * 100).round(1)
    return df


def summarize_portfolio(holdings: list[dict]) -> str:
    """構成比・損益をPythonで集計し、LLMに自然言語で要約させる。"""
    df = build_portfolio_df(holdings)
    sector_weight = (
        df.groupby("sector")["weight_pct"].sum().round(1).to_dict()
    )

    holdings_lines = "\n".join(
        f"- {row.ticker} ({row.sector}): 評価額{row.market_value:,.0f}円 "
        f"構成比{row.weight_pct}% 損益{row.pnl:+,.0f}円"
        for row in df.itertuples()
    )
    sector_lines = "\n".join(
        f"- {sector}: {pct}%" for sector, pct in sector_weight.items()
    )

    prompt = f"""\
以下は保有ポートフォリオの集計データ（Python側で計算済み）です。
数値の再計算は不要です。構成比の偏りやセクター集中について、
一般的な観点から3行以内でコメントしてください。
個別の売買判断や具体的な推奨は行わないでください。

【銘柄別データ】
{holdings_lines}

【セクター別構成比】
{sector_lines}
"""
    return call_llm(prompt)


def call_llm(prompt: str) -> str:
    # 実装は 03-data-api/02-llm-api-integration.md 参照
    raise NotImplementedError


if __name__ == "__main__":
    holdings = [
        {"ticker": "7203.T", "shares": 200, "avg_cost": 2100.0},
        {"ticker": "6758.T", "shares": 100, "avg_cost": 2800.0},
        {"ticker": "7974.T", "shares": 30, "avg_cost": 7200.0},
    ]
    print(summarize_portfolio(holdings))
```

### 実行結果例

```text
このポートフォリオはテクノロジーセクター（ソニーグループ・任天堂）に
55.0%が集中しており、自動車セクター（トヨタ自動車）の45.0%と
あわせて2セクターで全体を構成しています。

セクター数が少なく、業種分散の観点では偏りがある構成といえます。
特定業種の市況変化がポートフォリオ全体に影響しやすい点に留意してください。
```

## 演習課題

1. `build_portfolio_df` に、損益率（%）の列を追加してみてください。
2. 保有銘柄が5銘柄以上になった場合を想定し、構成比が20%を超える
   銘柄だけを抽出してLLMへの入力を作るコードを書いてください。
3. 「悪い例」のプロンプトをLLMに投げた場合に起こりうる問題を
   2つ挙げてください。

## 理解度チェック

- [ ] 構成比や損益の計算をPythonとLLMのどちらが担うべきか説明できる
- [ ] セクター情報を `yfinance` から取得する方法を説明できる
- [ ] LLMへのプロンプトに「再計算は不要」と明示する理由を説明できる

---

投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。

[← 前へ: 05-portfolio-management](00-README.md) | [次へ: リスク評価・分散 →](02-risk-assessment.md)
