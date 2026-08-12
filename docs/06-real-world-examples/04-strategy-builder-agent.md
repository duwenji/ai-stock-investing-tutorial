# AI戦略ビルダーエージェント

## この教材で身につくこと

- 曖昧な投資アイデアを、AIとの複数ターンの対話を通じて「関数チェーン型
  パイプライン」に詰めていく設計パターン
- ステートレスなLLM呼び出し（`call_llm`）で対話UIを実現する方法
  （会話全履歴を毎ターン送信する）
- 再利用可能な処理単位（関数レジストリ）を定義し、その一覧をそのまま
  プロンプトに埋め込んでAIに「どの関数をどの順番で組み合わせるか」を
  組み立てさせる設計パターン
- 「確定前にユーザーへ見せる」設計を、単発のJSON確認だけでなく
  自動評価・改善ループ（Evaluator-Optimizer）にまで広げる考え方

## 概要

02-screening-dashboard.mdは「自然言語1文→JSON→絞り込み」という単発の
変換フローでした。このツールは、その前段に「AIとの対話でアイデアを
関数チェーンに詰める」ステップを加え、アイデアの入力から実践（銘柄選定・
ランキング）までを1つの画面で完結させます。

処理の流れは次の3ステップです。

1. ユーザーが自由記述で投資アイデアを入力する（テンプレートボタンや、
   業種間のリード・ラグ分析から本日の注目銘柄を提案する機能も使える）
2. AIとの対話で、「どの関数（バックテストランキング・ファンダメンタルズ
   フィルタ等）をどの順番で使うか」という関数チェーン（`steps`）に詰める。
   確定候補は人間の目に触れる前に自動評価・改善ループを1往復通す
3. 確定した`steps`を最新の市場データに適用してパイプラインを実行し、
   該当銘柄・ランキングを一覧表示する

## 位置づけ

パイプラインを対話で組み立てる考え方は
[02-screening-dashboard.md](02-screening-dashboard.md)の延長線上にありますが、
このツールでは条件の生成を**単発の変換ではなく複数ターンの対話**にし、
「フィルタ条件」だけでなく「バックテストランキング」「シグナル絞り込み」
「並べ替え」まで含めた**関数チェーン**を組み立てます。

パイプラインのステップの1つ`FILTER_BY_FUNDAMENTALS`は、02と同様に
PER/PBR等のファンダメンタルズ条件を扱いますが、フィールド名は独自の
`indicator`/`operator`表記（`strategy_builder/conditions.py`）を使います。

`BACKTEST_RANK`ステップは、
[05-portfolio-management/03-backtest-automation.md](../05-portfolio-management/03-backtest-automation.md)
で学ぶ移動平均クロスオーバー等の指標計算・バックテストロジック
（`app/portfolio_management/backtest.py`）をそのまま再利用し、銘柄ごとに
近傍グリッドサーチで最適パラメータを探索してリスク調整済みリターン順に
ランキングします。単一銘柄の戦略検証ではなく、複数銘柄を一括でランキング
する点が特徴です。

業種間のリード・ラグ分析は
[05-portfolio-management/04-lead-lag-correlation.md](../05-portfolio-management/04-lead-lag-correlation.md)
で学んだ考え方をそのまま再利用し、「本日値上がりした業種の銘柄→過去の
分析で追随が見込まれる業種の銘柄」を洗い出す入力補助として使います。

> 関連: マルチターン（対話型）プロンプトの設計の一般原則は
> [genai-app-integration-tutorial: マルチターン（対話型）プロンプトの設計](https://github.com/duwenji/genai-app-integration-tutorial/blob/master/docs/02-io-contract-design/04-multi-turn-dialogue-prompting.md)
> で学べます。確定候補が生成された直後の「評価→不合格なら改善→再評価」
> ループ（Evaluator-Optimizer、`strategy_builder/evaluation.py`）は、
> 本教材の実ソースコードでも直接扱いますが、一般原則としては
> [genai-app-integration-tutorial: Evaluator-Optimizer](https://github.com/duwenji/genai-app-integration-tutorial/blob/master/docs/05-agentic-workflow-patterns/04-evaluator-optimizer.md)
> を参照してください。

## 主要概念・パラメータ解説

| 要素 | 目的 | 対応するコード |
|------|------|-----------------|
| 会話全履歴を毎ターン送信 | ステートレスな`call_llm`で対話を実現する | `build_dialogue_prompt` |
| JSON確定候補 vs 質問テキストの判別 | AIの応答が「まだ質問中」か「条件が確定した」かを見分ける | `parse_dialogue_response` |
| 関数レジストリ（`PIPELINE_FUNCTIONS`） | 関数名→説明文・パラメータスキーマ・実処理のマッピング。この一覧をそのままプロンプトに埋め込みAIに使わせる | `strategy_builder/pipeline_functions.py` |
| stepsの実行エンジン | AIが生成した`steps`（関数名の並び）を先頭から順に適用する薄い実行機 | `strategy_builder/pipeline.py::run_pipeline` |
| indicator/operatorスキーマ | `FILTER_BY_FUNDAMENTALS`ステップが内部で使うファンダメンタルズ条件表記 | `strategy_builder/conditions.py` |
| 確定候補の自動評価・改善ループ | パラメータの具体性・絞り込みすぎ・断定的な投資助言表現をAIに自己チェックさせ、不合格なら自動修正する | `strategy_builder/evaluation.py` |
| 業種間リード・ラグからの銘柄提案 | 本日の値上がり銘柄→追随業種の候補銘柄を洗い出す | `strategy_builder/sector_insight.py` |

## 実ソースコード（Python / プロンプト例）

### 対話プロンプトのペルソナ指示（抜粋）

```text
あなた（AI）は、ユーザーの投資アイデアを厳密な「株式スクリーニング・
パイプライン」へと昇華させるプロのクオンツ・アナリストです。

【ステップ1: アイデアの定量化】
ユーザーから「考え方」が入力されたら、それを歓迎し、以下の要素を
具体化するための質問や提案を1〜2個、短く行ってください。
1. どの関数（複数可）をどの順番で使うか
2. 各関数のパラメータ（戦略名・期間・閾値等）

【使用できる関数一覧】
- BACKTEST_RANK: 対象銘柄群を1戦略でバックテストし、銘柄ごとに近傍
  グリッドサーチで最適パラメータを探索してリスク調整済みリターン
  降順にランキングし、上位top_n件に絞る。
- FILTER_BY_FUNDAMENTALS: PER/PBR/ROE/配当利回り/売上高伸び率/
  時価総額/業種でフィルタする。
（他にMULTI_STRATEGY_RANK, FILTER_CURRENT_SIGNAL, SORT_BY, TOP_Nも
使用可能）

【ステップ2: 構造化データの出力】
ユーザーと条件が合意できたら、それ以外の説明文を一切含めず、必ず
次のJSON形式のみを```json コードブロックで返してください。
```json
{
  "strategy_name": "確定した戦略名",
  "steps": [
    {"function": "関数名", "params": {...}}
  ]
}
```
```

### 関数レジストリ（抜粋）

```python
PIPELINE_FUNCTIONS: dict[str, dict] = {
    "BACKTEST_RANK": {
        "description": (
            "対象銘柄群をSTRATEGIES（移動平均クロスオーバー/RSI逆張り/"
            "MACDクロスオーバー/ボリンジャーバンド逆張り）のいずれかで"
            "バックテストし、銘柄ごとに近傍グリッドサーチで最適パラメータを"
            "探索してリスク調整済みリターン降順にランキングし、上位top_n件"
            "に絞る。"
        ),
        "params_schema": {
            "strategy": "STRATEGIESのキー文字列（例: 移動平均クロスオーバー）",
            "period": "1y/3y/5y",
            "top_n": "整数（省略時は絞り込みなし）",
        },
        "run": _run_backtest_rank,
    },
    "FILTER_BY_FUNDAMENTALS": {
        "description": "PER/PBR/ROE/配当利回り/売上高伸び率/時価総額/業種でフィルタする。",
        "params_schema": {
            "conditions": (
                "[{indicator, operator, value}, ...] の配列。indicatorは"
                "PER, PBR, ROE, DIVIDEND_YIELD, REVENUE_GROWTH, "
                "MARKET_CAP, SECTORのいずれか。"
            ),
        },
        "run": _run_filter_by_fundamentals,
    },
    # SORT_BY, TOP_N, FILTER_CURRENT_SIGNAL, MULTI_STRATEGY_RANKも同様に登録
}
```

このdictの`description`/`params_schema`は`prompt_patterns/strategy_dialogue.py`
がそのままプロンプトに埋め込むため、キー名や説明文を変えるとAIが生成する
`steps` JSONの挙動にも直接影響します。新しい処理単位を1つ追加するだけで、
AIが使える関数一覧が自動的に更新される設計です。

### stepsの実行エンジン

```python
def run_pipeline(
    steps: list[dict], all_tickers: list[str], cache_dir
) -> tuple[pd.DataFrame, list[str]]:
    """全銘柄のticker列のみのDataFrameを初期値とし、stepsを先頭から
    順に適用する。未知のfunction名や例外を送出したステップはスキップし、
    トレースに理由を記録して処理を継続する。"""
    candidates_df = pd.DataFrame({"ticker": all_tickers})
    trace = [f"開始: {len(candidates_df)}件"]
    for step in steps:
        entry = PIPELINE_FUNCTIONS.get(step.get("function"))
        if entry is None:
            trace.append(f"{step.get('function')}: 未知の関数のためスキップ")
            continue
        before_count = len(candidates_df)
        candidates_df = entry["run"](candidates_df, step.get("params", {}), cache_dir)
        trace.append(f"{step.get('function')}: {before_count}件→{len(candidates_df)}件")
    return candidates_df, trace
```

完全な実装は[`app/strategy_builder/`](../../app/strategy_builder/)、
起動コマンドは`app/`ディレクトリで次の通りです。

```bash
streamlit run app.py
```

### 悪い例

対話の各ターンでAIの応答をそのまま信頼し、確定JSONかどうかを
判別せずに直接パイプラインへ適用しています。

```python
# 悪い例: 応答が質問なのか確定JSONなのか判別せずそのまま使う
raw = call_llm(prompt)
strategy = json.loads(raw)  # 質問テキストの場合ここで例外になる、
                             # あるいは不完全なstepsのまま実行されてしまう
result_df, trace = run_pipeline(strategy["steps"], all_tickers, cache_dir)
```

### 良い例

`parse_dialogue_response`で応答の種類を判別し、確定候補は自動評価・
改善ループ（`run_evaluation_loop`）を通したうえで`st.json`でユーザーに
見せ、明示的な「確定する」操作を経てから保存・実行します。

```python
parsed = parse_dialogue_response(raw)
if parsed["kind"] == "strategy":
    evaluation_result = run_evaluation_loop(parsed["strategy"], call_llm=call_llm)
    st.session_state["strategy_pending_strategy"] = evaluation_result["strategy"]
    st.json(evaluation_result["strategy"])  # 確認ステップ
    if st.button("この条件で確定する"):
        save_strategy(user_id, evaluation_result["strategy"])
else:
    st.chat_message("assistant").write(parsed["text"])  # まだ対話を続ける
```

### 実行結果例

投資アイデア欄に「PERが低く、ROEが高い成長株を、直近上昇トレンドの
タイミングで買いたい」と入力して対話を始めると、AIから「どの戦略で
エントリーシグナルを判定しますか？（例: 移動平均クロスオーバー）」
といった質問が返ります。合意すると、次のJSONが確定候補として表示されます。

```json
{
  "strategy_name": "割安成長株の押し目買い戦略",
  "steps": [
    {
      "function": "FILTER_BY_FUNDAMENTALS",
      "params": {
        "conditions": [
          {"indicator": "PER", "operator": "LESS_THAN", "value": 15},
          {"indicator": "ROE", "operator": "GREATER_THAN", "value": 10}
        ]
      }
    },
    {
      "function": "BACKTEST_RANK",
      "params": {"strategy": "移動平均クロスオーバー", "period": "1y", "top_n": 20}
    },
    {
      "function": "FILTER_CURRENT_SIGNAL",
      "params": {"signal": "ENTRY"}
    }
  ]
}
```

「確定する」を押すと③パイプライン実行セクションが利用可能になり、
「FILTER_BY_FUNDAMENTALS: 3200件→48件 → BACKTEST_RANK: 48件→20件 →
FILTER_CURRENT_SIGNAL: 20件→6件」のようなトレースとともに該当銘柄が
表示されます。

## 演習課題

1. `_INDICATOR_COLUMNS`（`strategy_builder/conditions.py`）に新しい指標
   （例: 自己資本比率）を1つ追加し、`fetch_fundamentals`にも対応する
   データ取得を追加してください。
2. `find_dominant_lagging_sector`のコヒーレンス閾値をUIから調整できる
   ようにし、閾値を上げると候補銘柄が減ることを確認してください。
3. `PIPELINE_FUNCTIONS`に新しいステップ（例: 出来高で絞り込む
   `FILTER_BY_VOLUME`）を1つ追加し、`strategy_dialogue.py`が組み立てる
   プロンプトの関数一覧に自動的に反映されることを確認してください。
4. 「悪い例」のコードを実際に動かした場合、対話の途中（AIがまだ質問を
   返している段階）でどのようなエラーになるか具体例を1つ考えてください。

## 理解度チェック

- [ ] ステートレスなLLM呼び出しで複数ターンの対話を実現する方法を説明できる
- [ ] AIの応答を「確定JSON」か「対話継続」かで判別する必要性を説明できる
- [ ] 関数チェーン型パイプライン（`steps`）が単発の条件フィルタと比べて
      何を表現できるようになるか説明できる
- [ ] 確定候補を自動評価・改善するEvaluator-Optimizerループの役割を
      説明できる

---

投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。

[← 前へ: 統合ポートフォリオアドバイザーエージェント](03-portfolio-advisor-agent.md) | [トップに戻る →](../../README.md)
