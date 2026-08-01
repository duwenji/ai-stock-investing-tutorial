# AI戦略ビルダーエージェント

## この教材で身につくこと

- 曖昧な投資アイデアを、AIとの複数ターンの対話を通じて構造化条件に
  詰めていく設計パターン
- ステートレスなLLM呼び出し（`call_llm`）で対話UIを実現する方法
  （会話全履歴を毎ターン送信する）
- 「確定前にユーザーへ見せる」設計を、単発のJSON確認だけでなく
  対話プロセス全体に広げる考え方
- 財務指標ベースのスクリーニング戦略を、簡易的に過去の値動きで
  検証してから実運用（銘柄選定）に進める一気通貫のUI構成

## 概要

02-screening-dashboard.mdは「自然言語1文→JSON→絞り込み」という単発の
変換フローでした。このツールは、その前段に「AIとの対話でアイデアを
条件に詰める」ステップと、後段に「簡易バックテストで検証する」ステップを
加え、アイデアの入力から実践（銘柄選定）までを1つの画面で完結させます。

処理の流れは次の4ステップです。

1. ユーザーが自由記述で投資アイデアを入力する（テンプレートボタンや、
   業種間のリード・ラグ分析から本日の注目銘柄を提案する機能も使える）
2. AIとの対話で、財務指標と閾値を持つ構造化条件（JSON）に詰める
3. 現在の財務指標で選んだ銘柄群を過去に遡って保有した場合の
   資産推移を簡易シミュレーションする
4. 確定した条件を最新の市場データに適用し、該当銘柄と判定理由を一覧表示する

## 位置づけ

条件のJSON変換・絞り込みの考え方は
[02-screening-dashboard.md](02-screening-dashboard.md)の延長線上にありますが、
このツールでは条件の生成を**単発の変換ではなく複数ターンの対話**にし、
独自のJSONスキーマ（`indicator`/`operator`表記）を使います。

バックテストの考え方は
[05-portfolio-management/03-backtest-automation.md](../05-portfolio-management/03-backtest-automation.md)
と共通ですが、このツールでは単一銘柄のテクニカル戦略ではなく、
**複数銘柄を均等金額で購入・保有した場合の資産推移**を扱います。

業種間のリード・ラグ分析は
[05-portfolio-management/04-lead-lag-correlation.md](../05-portfolio-management/04-lead-lag-correlation.md)
で学んだ考え方をそのまま再利用し、「本日値上がりした業種の銘柄→過去の
分析で追随が見込まれる業種の銘柄」を洗い出す入力補助として使います。

## 主要概念・パラメータ解説

| 要素 | 目的 | 対応するコード |
|------|------|-----------------|
| 会話全履歴を毎ターン送信 | ステートレスな`call_llm`で対話を実現する | `build_dialogue_prompt` |
| JSON確定候補 vs 質問テキストの判別 | AIの応答が「まだ質問中」か「条件が確定した」かを見分ける | `parse_dialogue_response` |
| indicator/operatorスキーマ | 既存のfield/記号演算子スキーマとは独立した戦略JSON形式 | `strategy_builder/conditions.py` |
| 判定理由の決定的生成 | AIを呼ばず、実際の値と閾値から機械的に判定理由を組み立てる | `build_match_reason` |
| 均等金額購入・保有シミュレーション | 過去の各時点で条件を満たしていたかは考慮しない簡易バックテスト | `run_strategy_backtest` |
| 業種間リード・ラグからの銘柄提案 | 本日の値上がり銘柄→追随業種の候補銘柄を洗い出す | `sector_insight.py` |

## 実ソースコード（Python / プロンプト例）

### 対話プロンプトのペルソナ指示（抜粋）

```text
あなた（AI）は、ユーザーの投資アイデアを厳密な「株式スクリーニング・
バックテスト条件」へと昇華させるプロのクオンツ・アナリストです。

【ステップ1: アイデアの定量化】
使用する財務指標と具体的な数値の閾値を具体化するための質問や提案を
1〜2個、短く行ってください。

【ステップ2: 構造化データの出力】
条件が合意できたら、次のJSON形式のみを```json コードブロックで
返してください。
{
  "strategy_name": "確定した戦略名",
  "conditions": [
    {"indicator": "PER", "operator": "LESS_THAN", "value": 15}
  ],
  "sort_by": "ROE",
  "order": "DESC"
}
```

### 判定理由の決定的生成

```python
def build_match_reason(row: pd.Series, conditions: list[dict]) -> str:
    """1銘柄の判定理由を、条件ごとの実際の値と閾値から機械的に組み立てる。
    LLMを呼ばず決定的に生成することで、判定理由の正確性と再現性を保証する。"""
    parts = []
    for condition in conditions:
        column = _INDICATOR_COLUMNS.get(condition.get("indicator"))
        op_func, op_label = _OPERATORS.get(condition.get("operator"), (None, None))
        if column is None or op_func is None or column not in row.index:
            continue
        actual = row[column]
        if pd.isna(actual):
            continue
        label = _INDICATOR_LABELS.get(condition["indicator"], condition["indicator"])
        parts.append(f"{label} {round(float(actual), 1)}（条件: {condition['value']}{op_label}）")
    return " / ".join(parts) if parts else "条件詳細なし"
```

完全な実装は[`app/strategy_builder/`](../../app/strategy_builder/)、
起動コマンドは`app/`ディレクトリで次の通りです。

```bash
streamlit run app.py
```

### 悪い例

対話の各ターンでAIの応答をそのまま信頼し、確定JSONかどうかを
判別せずに直接スクリーニングへ適用しています。

```python
# 悪い例: 応答が質問なのか確定JSONなのか判別せずそのまま使う
raw = call_llm(prompt)
strategy = json.loads(raw)  # 質問テキストの場合ここで例外になる、
                             # あるいは不完全な条件のまま実行されてしまう
result_df = apply_strategy_conditions(universe_df, strategy)
```

### 良い例

`parse_dialogue_response`で応答の種類を判別し、確定候補はユーザーに
`st.json`で見せたうえで、明示的な「確定する」操作を経てから保存・適用します。

```python
parsed = parse_dialogue_response(raw)
if parsed["kind"] == "strategy":
    st.session_state["strategy_pending_strategy"] = parsed["strategy"]
    st.json(parsed["strategy"])  # 確認ステップ
    if st.button("この条件で確定する"):
        save_strategy(STRATEGIES_PATH, parsed["strategy"])
else:
    st.chat_message("assistant").write(parsed["text"])  # まだ対話を続ける
```

### 実行結果例

投資アイデア欄に「PERが低く、ROEが高い成長株」と入力して対話を始めると、
AIから「PERとROEの具体的な閾値を教えてください（例: PER 15倍以下、
ROE 10%以上など）」といった質問が返ります。閾値を伝えて合意すると、
次のJSONが確定候補として表示されます。

```json
{
  "strategy_name": "割安成長株戦略",
  "conditions": [
    {"indicator": "PER", "operator": "LESS_THAN", "value": 15},
    {"indicator": "ROE", "operator": "GREATER_THAN", "value": 10}
  ],
  "sort_by": "ROE",
  "order": "DESC"
}
```

「確定する」を押すとバックテスト・銘柄選定セクションが利用可能になり、
銘柄選定結果には「PER 12.3（条件: 15未満）／ROE 15.2（条件: 10より大）」
のような判定理由が銘柄ごとに表示されます。

## 演習課題

1. `_INDICATOR_COLUMNS`に新しい指標（例: 自己資本比率）を1つ追加し、
   `fetch_fundamentals`にも対応するデータ取得を追加してください。
2. `find_dominant_lagging_sector`のコヒーレンス閾値をUIから調整できる
   ようにし、閾値を上げると候補銘柄が減ることを確認してください。
3. 「悪い例」のコードを実際に動かした場合、対話の途中（AIがまだ質問を
   返している段階）でどのようなエラーになるか具体例を1つ考えてください。

## 理解度チェック

- [ ] ステートレスなLLM呼び出しで複数ターンの対話を実現する方法を説明できる
- [ ] AIの応答を「確定JSON」か「対話継続」かで判別する必要性を説明できる
- [ ] この簡易バックテストが持つルックアヘッドバイアスの内容を説明できる
- [ ] 判定理由をAIではなく決定的ロジックで生成する利点を説明できる

---

投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。

[← 前へ: 統合ポートフォリオアドバイザーエージェント](03-portfolio-advisor-agent.md) | [トップに戻る →](../../README.md)
