# AI戦略ビルダーの条件品質レビュー（Evaluator-Optimizer） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AI戦略ビルダーの対話で確定候補となった戦略JSONを、ユーザーに提示する前に自動評価し、不合格ならフィードバックをもとに改善案を再生成するループ（Evaluator-Optimizer）を最大3回まで回してから、既存の確認ステップ（`st.json` + 確定ボタン）に渡す。[2026-08-09-agentic-workflow-patterns-design.md](../specs/2026-08-09-agentic-workflow-patterns-design.md)のフェーズ3を実装する。

**Architecture:** 新規`strategy_builder/evaluation.py`が評価プロンプト・評価実行・ループ制御（`run_evaluation_loop`）というUIから独立した純粋関数群を提供する。新規`build_refinement_prompt`（`prompt_patterns/strategy_dialogue.py`）は既存の対話ペルソナ指示を使わず、確定候補JSON＋評価フィードバックから修正案JSONを1回で生成する軽量プロンプト。`app_tabs/strategy_builder_tab.py`は、AIが対話中に戦略候補を生成した直後（既存の`parsed["kind"] == "strategy"`判定の直後）に`run_evaluation_loop`を1回呼び出し、その結果を`st.session_state["strategy_pending_strategy"]`に格納する。既存の確認ステップ（`st.json`表示＋「この条件で確定する」ボタン）はそのまま残り、ユーザーは評価・改善済みの最終案を確認してから確定する。

**Tech Stack:** Python 3.14 / Streamlit / pytest（`call_llm`をモック化してテスト、`uv run pytest`で実行）。新規外部依存は追加しない。

## Global Constraints

- 評価基準は3つ: (1) 条件が具体的か、(2) 対象銘柄が0件になりそうな過度な絞り込みでないか、(3) 断定的な投資助言表現を含んでいないか。3つすべてを満たす場合のみ`pass: true`。
- `evaluate_strategy`がJSONパースに失敗、または`pass`キーを含まない場合は安全側に倒し`{"pass": False, "feedback": "評価結果のパースに失敗しました。"}`を返す。
- `run_evaluation_loop`の改善案応答がJSONとして無効、または`conditions`キーを含まない場合は、そのイテレーションをスキップし直前の戦略のままループを継続する。
- `run_evaluation_loop`は最後の評価イテレーションの後には改善案を生成しない（無駄な`call_llm`呼び出しを避ける）。
- 既存の確認ステップ（`st.json(pending)` + 「この条件で確定する」ボタンでの`save_strategy`実行）は維持する。評価・改善ループは確定ボタン押下前、戦略候補が生成された直後に1回だけ実行する。

---

### Task 1: `prompt_patterns/strategy_dialogue.py` — `build_refinement_prompt`

**Files:**
- Modify: `ai-stock-investing-tutorial/app/prompt_patterns/strategy_dialogue.py`
- Test: `ai-stock-investing-tutorial/app/tests/test_strategy_dialogue_prompt.py`

**Interfaces:**
- Produces: `build_refinement_prompt(pending_strategy: dict, feedback: str) -> str`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_strategy_dialogue_prompt.py`の先頭に`import json`を追加し、末尾に以下を追加する。

```python
import json

from prompt_patterns.strategy_dialogue import (
    build_dialogue_prompt,
    build_refinement_prompt,
    parse_dialogue_response,
)
```

```python
def test_build_refinement_prompt_includes_strategy_and_feedback():
    pending = {
        "strategy_name": "割安株",
        "conditions": [{"indicator": "PER", "operator": "LESS_THAN", "value": 15}],
    }
    prompt = build_refinement_prompt(pending, "条件が厳しすぎます")
    assert "割安株" in prompt
    assert "条件が厳しすぎます" in prompt
    assert "json" in prompt


def test_build_refinement_prompt_lists_allowed_indicators_and_operators():
    pending = {"strategy_name": "割安株", "conditions": []}
    prompt = build_refinement_prompt(pending, "改善してください")
    assert "DIVIDEND_YIELD" in prompt
    assert "GREATER_EQUAL" in prompt
```

（既存の`from prompt_patterns.strategy_dialogue import build_dialogue_prompt, parse_dialogue_response`の1行を、上記のimportブロックで置き換える。）

- [ ] **Step 2: テストを実行し、失敗することを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/test_strategy_dialogue_prompt.py -v`
Expected: `ImportError: cannot import name 'build_refinement_prompt'` で失敗する。

- [ ] **Step 3: 最小限の実装を書く**

`prompt_patterns/strategy_dialogue.py`の`parse_dialogue_response`関数の直後に以下を追加する。

```python
def build_refinement_prompt(pending_strategy: dict, feedback: str) -> str:
    """確定候補の戦略JSONと評価フィードバックから、修正版JSONを1回で
    生成させる軽量プロンプト（Evaluator-Optimizerパターンの改善ステップ）。
    既存の対話ペルソナ指示（_PERSONA_INSTRUCTIONS）は使わない。
    """
    strategy_json = json.dumps(pending_strategy, ensure_ascii=False, indent=2)
    return (
        "以下は投資戦略のスクリーニング条件（JSON）と、その評価フィードバックです。\n\n"
        f"【現在の条件】\n{strategy_json}\n\n"
        f"【評価フィードバック】\n{feedback}\n\n"
        "このフィードバックを踏まえて条件を修正し、それ以外の説明文を一切含めず、"
        "必ず次のJSON形式のみを```json コードブロックで返してください。\n"
        "```json\n"
        "{\n"
        '  "strategy_name": "修正後の戦略名",\n'
        '  "conditions": [\n'
        '    {"indicator": "PER", "operator": "LESS_THAN", "value": 15}\n'
        "  ],\n"
        '  "sort_by": "ROE",\n'
        '  "order": "DESC"\n'
        "}\n"
        "```\n"
        "indicatorはPER, PBR, ROE, DIVIDEND_YIELD, REVENUE_GROWTH, MARKET_CAP, SECTORの"
        "いずれか、operatorはLESS_THAN, LESS_EQUAL, GREATER_THAN, GREATER_EQUAL, EQUALSの"
        "いずれかを使ってください。"
    )
```

- [ ] **Step 4: テストを実行し、成功することを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/test_strategy_dialogue_prompt.py -v`
Expected: 全テストPASS。

- [ ] **Step 5: コミット**

```bash
cd ai-stock-investing-tutorial
git add app/prompt_patterns/strategy_dialogue.py app/tests/test_strategy_dialogue_prompt.py
git commit -m "$(cat <<'EOF'
Add build_refinement_prompt for strategy condition refinement

One-shot prompt (no persona instructions) that takes a confirmed
strategy JSON candidate and evaluator feedback and asks for a
corrected JSON, feeding the Evaluator-Optimizer improvement step.
EOF
)"
```

---

### Task 2: `strategy_builder/evaluation.py` — 評価・改善ループ

**Files:**
- Create: `ai-stock-investing-tutorial/app/strategy_builder/evaluation.py`
- Test: `ai-stock-investing-tutorial/app/tests/test_strategy_builder_evaluation.py`

**Interfaces:**
- Consumes: Task 1の`build_refinement_prompt(pending_strategy, feedback) -> str`。`data_api.llm_client.call_llm(prompt: str) -> str`（既存関数、デフォルト引数として使用）。
- Produces:
  - `build_evaluate_prompt(strategy: dict) -> str`
  - `evaluate_strategy(strategy: dict, call_llm=default_call_llm) -> dict`（戻り値: `{"pass": bool, "feedback": str}`）
  - `run_evaluation_loop(strategy: dict, call_llm=default_call_llm, max_iterations: int = 3) -> dict`（戻り値: `{"strategy": dict, "iterations": int, "last_feedback": str | None}`）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_strategy_builder_evaluation.py`を新規作成する。

```python
import json

from strategy_builder.evaluation import (
    build_evaluate_prompt,
    evaluate_strategy,
    run_evaluation_loop,
)


def test_build_evaluate_prompt_includes_strategy_and_criteria():
    strategy = {
        "strategy_name": "割安株",
        "conditions": [{"indicator": "PER", "operator": "LESS_THAN", "value": 15}],
    }
    prompt = build_evaluate_prompt(strategy)
    assert "割安株" in prompt
    assert "PER" in prompt
    assert "pass" in prompt
    assert "断定的な投資助言" in prompt


def test_evaluate_strategy_parses_pass_response():
    strategy = {"strategy_name": "割安株", "conditions": []}
    result = evaluate_strategy(strategy, call_llm=lambda prompt: '{"pass": true, "feedback": ""}')
    assert result == {"pass": True, "feedback": ""}


def test_evaluate_strategy_falls_back_to_fail_on_invalid_json():
    strategy = {"strategy_name": "割安株", "conditions": []}
    result = evaluate_strategy(strategy, call_llm=lambda prompt: "not json")
    assert result == {"pass": False, "feedback": "評価結果のパースに失敗しました。"}


def test_evaluate_strategy_falls_back_to_fail_when_pass_key_missing():
    strategy = {"strategy_name": "割安株", "conditions": []}
    result = evaluate_strategy(strategy, call_llm=lambda prompt: '{"feedback": "何か"}')
    assert result == {"pass": False, "feedback": "評価結果のパースに失敗しました。"}


def test_run_evaluation_loop_returns_immediately_when_first_evaluation_passes():
    strategy = {
        "strategy_name": "割安株",
        "conditions": [{"indicator": "PER", "operator": "LESS_THAN", "value": 15}],
    }
    call_count = {"n": 0}

    def fake_call_llm(prompt):
        call_count["n"] += 1
        return '{"pass": true, "feedback": ""}'

    result = run_evaluation_loop(strategy, call_llm=fake_call_llm)

    assert call_count["n"] == 1
    assert result == {"strategy": strategy, "iterations": 0, "last_feedback": None}


def test_run_evaluation_loop_refines_and_returns_on_second_pass():
    strategy = {
        "strategy_name": "割安株",
        "conditions": [{"indicator": "PER", "operator": "LESS_THAN", "value": 15}],
    }
    refined_strategy = {
        "strategy_name": "割安株（改善）",
        "conditions": [{"indicator": "PER", "operator": "LESS_THAN", "value": 20}],
    }
    responses = iter(
        [
            '{"pass": false, "feedback": "条件が厳しすぎます"}',
            json.dumps(refined_strategy, ensure_ascii=False),
            '{"pass": true, "feedback": ""}',
        ]
    )

    def fake_call_llm(prompt):
        return next(responses)

    result = run_evaluation_loop(strategy, call_llm=fake_call_llm)

    assert result["strategy"] == refined_strategy
    assert result["iterations"] == 1
    assert result["last_feedback"] == "条件が厳しすぎます"


def test_run_evaluation_loop_stops_at_max_iterations_when_never_passes():
    strategy = {"strategy_name": "割安株", "conditions": []}
    refined_once = {
        "strategy_name": "割安株2",
        "conditions": [{"indicator": "PER", "operator": "LESS_THAN", "value": 10}],
    }
    responses = iter(
        [
            '{"pass": false, "feedback": "改善してください"}',
            json.dumps(refined_once, ensure_ascii=False),
            '{"pass": false, "feedback": "まだ不十分です"}',
        ]
    )

    def fake_call_llm(prompt):
        return next(responses)

    result = run_evaluation_loop(strategy, call_llm=fake_call_llm, max_iterations=2)

    assert result["strategy"] == refined_once
    assert result["iterations"] == 2
    assert result["last_feedback"] == "まだ不十分です"


def test_run_evaluation_loop_skips_refinement_when_response_is_invalid_json():
    strategy = {
        "strategy_name": "割安株",
        "conditions": [{"indicator": "PER", "operator": "LESS_THAN", "value": 15}],
    }
    responses = iter(
        [
            '{"pass": false, "feedback": "改善してください"}',
            "not valid json",
            '{"pass": true, "feedback": ""}',
        ]
    )

    def fake_call_llm(prompt):
        return next(responses)

    result = run_evaluation_loop(strategy, call_llm=fake_call_llm, max_iterations=3)

    assert result["strategy"] == strategy
    assert result["iterations"] == 1
```

- [ ] **Step 2: テストを実行し、失敗することを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/test_strategy_builder_evaluation.py -v`
Expected: `ModuleNotFoundError: No module named 'strategy_builder.evaluation'` で失敗する。

- [ ] **Step 3: 最小限の実装を書く**

`strategy_builder/evaluation.py`を新規作成する。

```python
# AI戦略ビルダーが確定候補とした戦略JSONを、確定前に自動評価・改善する
# モジュール（Evaluator-Optimizerパターン）。
import json

from common.json_parsing import strip_code_fence
from data_api.llm_client import call_llm as default_call_llm
from prompt_patterns.strategy_dialogue import build_refinement_prompt


def build_evaluate_prompt(strategy: dict) -> str:
    strategy_json = json.dumps(strategy, ensure_ascii=False, indent=2)
    return (
        "以下は投資戦略のスクリーニング条件（JSON）です。\n\n"
        f"{strategy_json}\n\n"
        '次の3つの基準で評価し、{"pass": true/false, "feedback": "..."} '
        "形式のJSONのみを出力してください（説明文やコードブロック記法は不要です）。\n"
        "1. 条件が具体的か（indicator/valueが曖昧でないか）\n"
        "2. 条件数が極端に少なく／多くなく、対象銘柄が0件になりそうな過度な"
        "絞り込みでないか\n"
        "3. 断定的な投資助言表現（例: 「必ず上がる」「今すぐ買うべき」）を"
        "含んでいないか\n\n"
        "3つすべてを満たす場合のみpassをtrueにしてください。"
        "falseの場合、feedbackに具体的な改善点を日本語で1〜2文で書いてください。"
    )


def evaluate_strategy(strategy: dict, call_llm=default_call_llm) -> dict:
    raw = call_llm(build_evaluate_prompt(strategy))
    try:
        result = json.loads(strip_code_fence(raw))
    except json.JSONDecodeError:
        result = None

    # 評価自体が失敗した場合（パース不可・pass欠落）は安全側に倒し、不合格として扱う。
    if not isinstance(result, dict) or "pass" not in result:
        return {"pass": False, "feedback": "評価結果のパースに失敗しました。"}
    return {"pass": bool(result.get("pass")), "feedback": result.get("feedback", "")}


def run_evaluation_loop(
    strategy: dict, call_llm=default_call_llm, max_iterations: int = 3
) -> dict:
    """evaluate_strategyがpass=Trueを返すかmax_iterationsに達するまで、
    build_refinement_promptによる再生成を繰り返す。

    改善案の応答がJSONとして無効、またはconditionsキーを含まない場合は、
    そのイテレーションをスキップし直前のstrategyのままループを継続する。
    最後の評価イテレーションの後には改善案を生成しない。
    """
    current = strategy
    last_feedback = None
    for i in range(max_iterations):
        evaluation = evaluate_strategy(current, call_llm=call_llm)
        if evaluation["pass"]:
            return {"strategy": current, "iterations": i, "last_feedback": last_feedback}
        last_feedback = evaluation["feedback"]

        if i < max_iterations - 1:
            raw = call_llm(build_refinement_prompt(current, last_feedback))
            try:
                refined = json.loads(strip_code_fence(raw))
            except json.JSONDecodeError:
                refined = None
            if isinstance(refined, dict) and "conditions" in refined:
                current = refined

    return {"strategy": current, "iterations": max_iterations, "last_feedback": last_feedback}
```

- [ ] **Step 4: テストを実行し、成功することを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/test_strategy_builder_evaluation.py -v`
Expected: 全テストPASS。

- [ ] **Step 5: コミット**

```bash
cd ai-stock-investing-tutorial
git add app/strategy_builder/evaluation.py app/tests/test_strategy_builder_evaluation.py
git commit -m "$(cat <<'EOF'
Add strategy_builder/evaluation for confirmed-strategy quality review

evaluate_strategy checks a confirmed strategy JSON against three
criteria (specificity, over-narrowing, no directive language),
falling back to a fail verdict on unparseable responses.
run_evaluation_loop wraps it in an Evaluator-Optimizer loop (evaluate
-> refine on failure -> re-evaluate, up to max_iterations), kept as a
UI-independent pure function so the loop control is unit-testable.
EOF
)"
```

---

### Task 3: `app_tabs/strategy_builder_tab.py` — 評価ループを確定フローに接続

**Files:**
- Modify: `ai-stock-investing-tutorial/app/app_tabs/strategy_builder_tab.py`

**Interfaces:**
- Consumes: Task 2の`strategy_builder.evaluation.run_evaluation_loop(strategy, call_llm) -> dict`（戻り値`{"strategy": dict, "iterations": int, "last_feedback": str | None}`）
- Produces: UI変更のみ（他タスクから消費されるインターフェースなし）

- [ ] **Step 1: importを追加する**

`app_tabs/strategy_builder_tab.py`の`from prompt_patterns.strategy_dialogue import ...`の直後に1行追加する。

```python
from prompt_patterns.strategy_dialogue import build_dialogue_prompt, parse_dialogue_response
from screening.sectors import SECTOR_MAP
from screening.universe import UNIVERSE, UNIVERSE_NAMES
from sector_analysis.network import build_mermaid_lead_lag_graph
from strategy_builder.backtest import run_strategy_backtest
from strategy_builder.conditions import (
    apply_strategy_conditions,
    build_match_reason,
    sort_by_strategy,
)
from strategy_builder.evaluation import run_evaluation_loop
from strategy_builder.sector_insight import build_watchlist_from_rotation
from strategy_builder.storage import load_strategies, save_strategy
```

- [ ] **Step 2: 戦略候補が生成された直後に評価ループを実行するよう変更する**

`app_tabs/strategy_builder_tab.py`の`_render_dialogue_section`関数内、以下の既存コードを探す。

```python
    if history[-1]["role"] == "user" and pending is None:
        prompt = build_dialogue_prompt(history, sectors=sorted(set(SECTOR_MAP.values())))
        with st.spinner("AIが回答を考えています..."):
            raw = call_llm(prompt)
        parsed = parse_dialogue_response(raw)
        if parsed["kind"] == "strategy":
            st.session_state["strategy_pending_strategy"] = parsed["strategy"]
        else:
            history.append({"role": "assistant", "content": parsed["text"]})
            st.session_state["strategy_chat_history"] = history
        st.rerun()
```

これを以下に置き換える。

```python
    if history[-1]["role"] == "user" and pending is None:
        prompt = build_dialogue_prompt(history, sectors=sorted(set(SECTOR_MAP.values())))
        with st.spinner("AIが回答を考えています..."):
            raw = call_llm(prompt)
        parsed = parse_dialogue_response(raw)
        if parsed["kind"] == "strategy":
            # 確定候補が生成された直後に自動評価・改善ループを1回だけ実行する
            # （Evaluator-Optimizerパターン）。結果を人間の最終確認に回す。
            with st.spinner("戦略条件を評価・改善中..."):
                evaluation_result = run_evaluation_loop(parsed["strategy"], call_llm=call_llm)
            st.session_state["strategy_pending_strategy"] = evaluation_result["strategy"]
            st.session_state["strategy_pending_evaluation"] = evaluation_result
        else:
            history.append({"role": "assistant", "content": parsed["text"]})
            st.session_state["strategy_chat_history"] = history
        st.rerun()
```

- [ ] **Step 3: 確定候補の表示に評価結果の補足を追加する**

同じ関数内、以下の既存コードを探す。

```python
    if pending is not None:
        st.subheader("確定候補の戦略")
        st.json(pending)
        confirm_col, continue_col = st.columns(2)
        with confirm_col:
            if st.button("この条件で確定する", key="strategy_confirm_pending"):
                save_strategy(STRATEGIES_PATH, pending)
                st.session_state["strategy_confirmed"] = pending
                st.session_state["strategy_pending_strategy"] = None
                st.success(f"戦略「{pending['strategy_name']}」を保存しました。")
                st.rerun()
        with continue_col:
            if st.button("さらに対話を続ける", key="strategy_reject_pending"):
                history.append(
                    {
                        "role": "user",
                        "content": (
                            "まだ確定しません。もう少し条件について質問や"
                            "別の提案をしてください。"
                        ),
                    }
                )
                st.session_state["strategy_chat_history"] = history
                st.session_state["strategy_pending_strategy"] = None
                st.rerun()
        return
```

これを以下に置き換える（評価結果の補足表示、および両ボタンでの`strategy_pending_evaluation`クリアを追加）。

```python
    if pending is not None:
        st.subheader("確定候補の戦略")
        evaluation_result = st.session_state.get("strategy_pending_evaluation")
        if evaluation_result and evaluation_result["iterations"] > 0:
            st.caption("AIによる自動改善を行いました。")
            if evaluation_result["last_feedback"]:
                st.caption(f"評価フィードバック: {evaluation_result['last_feedback']}")
        st.json(pending)
        confirm_col, continue_col = st.columns(2)
        with confirm_col:
            if st.button("この条件で確定する", key="strategy_confirm_pending"):
                save_strategy(STRATEGIES_PATH, pending)
                st.session_state["strategy_confirmed"] = pending
                st.session_state["strategy_pending_strategy"] = None
                st.session_state["strategy_pending_evaluation"] = None
                st.success(f"戦略「{pending['strategy_name']}」を保存しました。")
                st.rerun()
        with continue_col:
            if st.button("さらに対話を続ける", key="strategy_reject_pending"):
                history.append(
                    {
                        "role": "user",
                        "content": (
                            "まだ確定しません。もう少し条件について質問や"
                            "別の提案をしてください。"
                        ),
                    }
                )
                st.session_state["strategy_chat_history"] = history
                st.session_state["strategy_pending_strategy"] = None
                st.session_state["strategy_pending_evaluation"] = None
                st.rerun()
        return
```

- [ ] **Step 4: `strategy_pending_evaluation`の初期化を追加する**

`render_strategy_builder_tab`関数内の既存の`session_state`初期化ブロックを探す。

```python
    if "strategy_idea_text" not in st.session_state:
        st.session_state["strategy_idea_text"] = ""
    if "strategy_chat_history" not in st.session_state:
        st.session_state["strategy_chat_history"] = []
    if "strategy_pending_strategy" not in st.session_state:
        st.session_state["strategy_pending_strategy"] = None
    if "strategy_confirmed" not in st.session_state:
        st.session_state["strategy_confirmed"] = None
```

これを以下に置き換える。

```python
    if "strategy_idea_text" not in st.session_state:
        st.session_state["strategy_idea_text"] = ""
    if "strategy_chat_history" not in st.session_state:
        st.session_state["strategy_chat_history"] = []
    if "strategy_pending_strategy" not in st.session_state:
        st.session_state["strategy_pending_strategy"] = None
    if "strategy_pending_evaluation" not in st.session_state:
        st.session_state["strategy_pending_evaluation"] = None
    if "strategy_confirmed" not in st.session_state:
        st.session_state["strategy_confirmed"] = None
```

- [ ] **Step 5: 既存テストスイートを実行し、回帰がないことを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/ -v`
Expected: 全テストPASS（`app_tabs/strategy_builder_tab.py`自体はテスト対象外だが、import解決に問題がないことは次のステップの手動起動で確認する）。

- [ ] **Step 6: アプリを起動して手動確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run python -m streamlit run app.py`

ブラウザで以下を確認する:
1. 「AI戦略ビルダー」タブを開き、テンプレートボタン（例:「バリュー株」）を押して「対話を始める」を押す
2. AIとの対話を進め、戦略条件が確定候補として提示されるまで続ける
3. 確定候補の表示前に「戦略条件を評価・改善中...」のスピナーが一瞬表示されることを確認する（評価ループが実行されている）
4. 確定候補のJSON表示の上に、AIが自動改善を行った場合は「AIによる自動改善を行いました。」というキャプションと評価フィードバックが表示されることを確認する（改善が発生しなかった場合はキャプションが表示されないことも許容）
5. 「この条件で確定する」を押すと、従来通り戦略が保存され「戦略「...」を保存しました。」と表示されることを確認する
6. 別の対話で「さらに対話を続ける」を押した場合、評価結果のキャプションが次の候補提示時に正しくクリア・更新されることを確認する

問題があれば実装を修正し、再度確認する。

- [ ] **Step 7: 全体テストスイートを再実行する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/ -v`
Expected: 全テストPASS（回帰なし）。

- [ ] **Step 8: コミット**

```bash
cd ai-stock-investing-tutorial
git add app/app_tabs/strategy_builder_tab.py
git commit -m "$(cat <<'EOF'
Run strategy condition through an evaluation loop before confirmation

When the AI dialogue produces a confirmed-strategy candidate, it now
runs through run_evaluation_loop (Evaluator-Optimizer) once before
being shown for human confirmation. The existing confirm-step UX
(st.json preview + confirm button) is unchanged — the loop just
improves what gets shown, and a caption surfaces when auto-refinement
happened.
EOF
)"
```

---

## Self-Review Notes

- **Spec coverage:** 評価基準（3項目）→ Task 2の`build_evaluate_prompt`。評価失敗時の安全側フォールバック→ Task 2の`evaluate_strategy`。改善プロンプト→ Task 1の`build_refinement_prompt`。ループ制御（合格時即終了・max_iterations到達時の打ち切り・無効応答時のスキップ）→ Task 2の`run_evaluation_loop`とそのテスト4件。既存確認ステップとの統合・UI表示（自動改善の補足キャプション）→ Task 3。手動確認手順→ Task 3 Step 6。
- **プレースホルダー確認:** 各ステップに実コード・実プロンプト文言を記載済み。「後で実装」「適切なエラーハンドリングを追加」等の曖昧な指示なし。
- **型・シグネチャの一貫性:** `build_refinement_prompt(pending_strategy, feedback)`の引数順はTask 1・2で一致。`run_evaluation_loop`の戻り値キー（`strategy`/`iterations`/`last_feedback`）はTask 2のテストとTask 3のUI参照（`evaluation_result["iterations"]`、`evaluation_result["last_feedback"]`）で一致。`evaluate_strategy`の戻り値キー（`pass`/`feedback`）はTask 2内で一貫。
- **既存機能への影響確認:** `_render_dialogue_section`の「さらに対話を続ける」パスと「保存済み戦略を読み込む」パス（`strategy_load_picked`）は`strategy_pending_strategy`を経由しないため評価ループの対象外のまま変わらない。既存の`test_strategy_dialogue_prompt.py`・`test_strategy_builder_conditions.py`等はTask 1で追加したimport以外に変更がなく、既存アサーションに影響しない。
