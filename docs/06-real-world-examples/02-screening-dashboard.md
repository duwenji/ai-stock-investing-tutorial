# スクリーニングダッシュボード

## この教材で身につくこと

- Streamlit（Pythonだけで動く簡易Webダッシュボードを作れるライブラリ）
  の基本的な使い方
- 自然言語条件 → 構造化フィルタ → pandas絞り込みという流れをUI化する方法
- AIが解釈した条件を、適用前にユーザーへ確認させる設計の重要性

## 概要

01-daily-market-report-tool.mdはCLIで完結するツールでした。
このツールは、ユーザーがブラウザ上で条件を入力し、その場で
絞り込み結果を確認できるダッシュボードです。

処理の流れは次の3ステップです。

1. ユーザーが自然言語でスクリーニング条件を入力する
2. LLMが条件を構造化フィルタ（JSON）に変換する
3. 変換結果を**ユーザーに見せたうえで**、実データのDataFrameに適用する

Streamlitは、HTML/CSS/JavaScriptを書かずにPythonのコードだけで
Webアプリの見た目を組み立てられるライブラリです。`st.text_input`や
`st.dataframe`のような関数を呼ぶだけでUI部品が生成されます。

## 位置づけ

条件のJSON変換と`apply_filters`の実装そのものは、
[02-prompt-patterns/03-stock-screening-prompts.md](../02-prompt-patterns/03-stock-screening-prompts.md)
で学んだ内容をそのまま再利用します。

このツールで新しく学ぶのは、次の2点です。

- Streamlitによる入力UI・出力UIの組み立て方
- LLMが翻訳した条件を**人間の確認工程を挟んでから**適用する設計

01-daily-market-report-tool.mdが「決まった銘柄群を毎朝処理する」自動化
だったのに対し、このツールは「ユーザーの都度の入力を起点にする」対話型の
ツールです。03-portfolio-advisor-agent.mdでは再び自動化寄りの設計に戻ります。

## 主要概念・パラメータ解説

| 要素 | 目的 | 対応するコード |
|------|------|-----------------|
| `st.text_input` | 自然言語条件をユーザーから受け取る | `condition_text` |
| `build_screening_prompt` / `call_llm` | 条件をJSONフィルタへ変換する | 02-prompt-patterns/03 |
| `st.json` によるフィルタ表示 | 適用前にユーザーへ解釈結果を見せる | 確認ステップ |
| `apply_filters` | 確認済みフィルタを実データに適用する | 02-prompt-patterns/03 |
| `st.dataframe` | 絞り込み結果を表形式で表示する | `result_df` |
| 銘柄ごとの一言要約プロンプト | 表の各行にAIコメントを添える | `ONE_LINE_SUMMARY_PROMPT` |

## 実ソースコード（Python / プロンプト例）

### 一言要約プロンプト

```text
以下の銘柄データを見て、投資家向けの一言コメントを日本語で
1文だけ出力してください。断定的な売買判断は含めないでください。

銘柄コード: {code}
PER: {per}
配当利回り: {dividend_yield}%
```

### Streamlitアプリ本体

```python
import json

import pandas as pd
import streamlit as st

from data_api.llm_client import call_llm                      # 03-data-api/02
from data_api.stock_price_api import fetch_universe_fundamentals  # 03-data-api/01
from prompt_patterns.screening import build_screening_prompt, apply_filters  # 02-prompt-patterns/03

TICKER_UNIVERSE = ["7203.T", "6758.T", "9432.T", "8306.T", "9984.T"]

ONE_LINE_SUMMARY_PROMPT = """\
以下の銘柄データを見て、投資家向けの一言コメントを日本語で
1文だけ出力してください。断定的な売買判断は含めないでください。

銘柄コード: {code}
PER: {per}
配当利回り: {dividend_yield}%
"""

st.title("銘柄スクリーニングダッシュボード")

condition_text = st.text_input(
    "スクリーニング条件を自然言語で入力してください",
    placeholder="PERが15倍以下で配当利回りが3%以上",
)

if condition_text:
    prompt = build_screening_prompt(condition_text)
    filters = json.loads(call_llm(prompt))

    # 悪い例と良い例の分岐点: ここで必ずユーザーに解釈結果を見せる
    st.subheader("AIが解釈した条件（適用前に確認してください）")
    st.json(filters)

    if st.button("この条件で絞り込む"):
        universe_df = fetch_universe_fundamentals(TICKER_UNIVERSE)
        result_df = apply_filters(universe_df, filters)

        st.subheader(f"絞り込み結果（{len(result_df)}件）")
        st.dataframe(result_df)

        st.subheader("銘柄ごとのAIコメント")
        for _, row in result_df.iterrows():
            summary_prompt = ONE_LINE_SUMMARY_PROMPT.format(
                code=row["code"],
                per=row["per"],
                dividend_yield=row["dividend_yield"],
            )
            comment = call_llm(summary_prompt)
            st.write(f"**{row['code']}**: {comment}")
```

起動コマンドです。

```bash
streamlit run app.py
```

### 悪い例

LLMが変換したフィルタを、ユーザーに見せずそのまま適用しています。
条件の解釈を誤っても気づく手段がなく、意図しない銘柄群が
「絞り込み結果」として提示されてしまいます。

```python
# 悪い例: フィルタを確認させずに即座に適用する
filters = json.loads(call_llm(build_screening_prompt(condition_text)))
result_df = apply_filters(universe_df, filters)  # 確認ステップなし
st.dataframe(result_df)
```

### 良い例

`st.json(filters)`でAIの解釈結果を必ず表示し、ユーザーが
ボタンを押すまで実データへの適用を行いません。誤解釈があれば
この時点で気づけます。

```python
filters = json.loads(call_llm(build_screening_prompt(condition_text)))
st.json(filters)  # 確認ステップ

if st.button("この条件で絞り込む"):
    result_df = apply_filters(universe_df, filters)
    st.dataframe(result_df)
```

### 実行結果例

スクリーンショットの代わりに、画面の表示内容をテキストで説明します。

`condition_text`に「PERが15倍以下で配当利回りが3%以上」と入力すると、
「AIが解釈した条件」の下に次のJSONがそのまま表示されます。

```json
[
  {"field": "per", "operator": "<=", "value": 15},
  {"field": "dividend_yield", "operator": ">=", "value": 3}
]
```

「この条件で絞り込む」ボタンを押すと、表には`code`, `per`,
`dividend_yield`などの列を持つ2〜3行程度の候補銘柄が表示されます。
各行の下に「**7203**: PERが業界平均を下回り、割安感が意識されやすい
水準です。」のような一言コメントが1行ずつ並びます。

## 演習課題

1. `TICKER_UNIVERSE`を業種別に分割し、`st.selectbox`で
   ユーザーが対象ユニバースを選べるようにしてください。
2. フィルタのfieldに存在しない値が含まれていた場合、
   `st.error`でエラーメッセージを表示するようにしてください。
3. 「悪い例」のコードを実際に動かした場合、どのような誤操作が
   起こり得るか具体例を1つ考えてください。

## 理解度チェック

- [ ] Streamlitの基本的なUI部品（text_input, dataframe, button）を説明できる
- [ ] LLMが変換したフィルタをユーザーに確認させる理由を説明できる
- [ ] 自然言語条件からダッシュボード表示までの全ステップを説明できる

---

投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。

[← 前へ: 日次マーケットレポート自動生成ツール](01-daily-market-report-tool.md) | [次へ: 統合ポートフォリオアドバイザーエージェント →](03-portfolio-advisor-agent.md)
