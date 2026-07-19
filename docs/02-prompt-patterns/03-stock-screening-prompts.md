# 銘柄スクリーニング条件言語化プロンプト

## この教材で身につくこと

- 自然言語のスクリーニング条件を構造化フィルタに変換するプロンプト設計
- 「銘柄選定」と「条件翻訳」をLLMの役割から明確に切り分ける考え方
- 構造化フィルタをpandasのDataFrameに適用する実装方法

## 概要

「PERが15倍以下で配当利回りが3%以上の銘柄」のような条件は、
人間には自然でも、そのままではプログラムで処理できません。

LLMにこの条件を直接「銘柄を選んで」と丸投げすると、実在しない
銘柄コードや古い財務数値を生成してしまう危険があります。
LLMには条件の**翻訳**だけをさせ、実際の絞り込みはPython側の
実データに対して行うことが重要です。

## 位置づけ

前の2教材では「一次情報を渡してLLMに解釈させる」パターンを
扱いました。この教材では逆に、「LLMには判断させず、条件の
構造化だけをさせる」という異なる役割分担を学びます。

この考え方は、03-data-api/01-stock-price-api.mdで取得する
実データとLLMの出力を組み合わせる際の基本パターンになります。

## 主要概念・パラメータ解説

| 要素 | 目的 | 具体例 |
|------|------|--------|
| 役割の限定 | 銘柄選定をLLMにさせない | 「条件をJSONに変換するだけでよい」 |
| フィルタのスキーマ指定 | 後続コードで機械的に処理可能にする | `field` / `operator` / `value` の3要素 |
| 使用可能フィールドの列挙 | 存在しない指標名の生成を防ぐ | `per`, `pbr`, `dividend_yield` 等を明示 |
| 演算子の限定 | 曖昧な条件表現を防ぐ | `<=`, `>=`, `==` のみ許可 |
| 実データへの適用は別工程 | ハルシネーション銘柄を防ぐ | フィルタ適用はPythonのpandas側で行う |

## 実ソースコード（Python / プロンプト例）

### 悪い例

条件の翻訳ではなく、LLMに直接「良い銘柄」を選ばせています。
実データを見ていないため、存在しない銘柄コードや古い数値を
生成するリスクが高い指示です。

```text
PERが15倍以下で配当利回りが3%以上の、日本の優良銘柄を
5つ教えてください。
```

### 良い例

LLMの役割を「自然言語条件のJSON変換」のみに限定しています。
実際の銘柄選定は、この後Python側で実データに対して行います。

```text
あなたは株式スクリーニング条件の翻訳アシスタントです。
以下の【条件】を、次のJSONスキーマに従って構造化してください。
実際に銘柄を選ぶ必要はありません。条件の翻訳のみを行ってください。

使用可能なfield: "per", "pbr", "dividend_yield", "market_cap"
使用可能なoperator: "<=", ">=", "=="

出力形式（複数条件はAND条件として配列にする）:
[
  {{"field": "フィールド名", "operator": "演算子", "value": 数値}}
]

【条件】
{condition_text}
```

### プロンプトテンプレートの適用とフィルタ適用

```python
import json
import pandas as pd

SCREENING_PROMPT = """\
あなたは株式スクリーニング条件の翻訳アシスタントです。
以下の【条件】を、次のJSONスキーマに従って構造化してください。
実際に銘柄を選ぶ必要はありません。条件の翻訳のみを行ってください。

使用可能なfield: "per", "pbr", "dividend_yield", "market_cap"
使用可能なoperator: "<=", ">=", "=="

出力形式（複数条件はAND条件として配列にする）:
[
  {{"field": "フィールド名", "operator": "演算子", "value": 数値}}
]

【条件】
{condition_text}
"""


def build_screening_prompt(condition_text: str) -> str:
    """自然言語の条件を埋め込み、フィルタ翻訳プロンプトを組み立てる。"""
    return SCREENING_PROMPT.format(condition_text=condition_text)


def call_llm(prompt: str) -> str:
    # 実装は 03-data-api/02-llm-api-integration.md 参照
    raise NotImplementedError


def apply_filters(df: pd.DataFrame, filters: list[dict]) -> pd.DataFrame:
    """LLMが翻訳したフィルタ条件を、実データのDataFrameに適用する。"""
    mask = pd.Series(True, index=df.index)
    ops = {
        "<=": lambda s, v: s <= v,
        ">=": lambda s, v: s >= v,
        "==": lambda s, v: s == v,
    }
    for f in filters:
        column, operator, value = f["field"], f["operator"], f["value"]
        mask &= ops[operator](df[column], value)
    return df[mask]


if __name__ == "__main__":
    condition = "PERが15倍以下で配当利回りが3%以上"
    prompt = build_screening_prompt(condition)
    filters = json.loads(call_llm(prompt))

    # 実データは 03-data-api/01-stock-price-api.md で取得する想定
    stocks = pd.DataFrame(
        {
            "code": ["1301", "1332", "1333"],
            "per": [12.5, 18.2, 9.8],
            "dividend_yield": [3.5, 2.1, 4.0],
        }
    )
    result = apply_filters(stocks, filters)
    print(result)
```

### 実行結果例

LLMが返すフィルタ条件のJSON:

```json
[
  {"field": "per", "operator": "<=", "value": 15},
  {"field": "dividend_yield", "operator": ">=", "value": 3}
]
```

`apply_filters` の実行結果（pandasのDataFrame）:

```text
   code   per  dividend_yield
0  1301  12.5             3.5
2  1333   9.8             4.0
```

## 演習課題

1. 「時価総額1000億円以上」という条件を追加した場合の
   フィルタJSONを、自分で書いてみてください。
2. `apply_filters` に、使用可能なfield以外が渡された場合の
   エラー処理を追加してください。
3. 「悪い例」のプロンプトで得られる銘柄名を、なぜそのまま
   投資判断に使ってはいけないか説明してください。

## 理解度チェック

- [ ] LLMに「条件翻訳」と「銘柄選定」を分離させる理由を説明できる
- [ ] フィルタのfield/operatorを限定する意義を説明できる
- [ ] 構造化フィルタをpandasでどう適用するか説明できる

---

投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。

[← 前へ: ニュース・センチメント分析プロンプト](02-news-sentiment-prompts.md) | [次へ: レポート自動生成プロンプト →](04-report-generation-prompts.md)
