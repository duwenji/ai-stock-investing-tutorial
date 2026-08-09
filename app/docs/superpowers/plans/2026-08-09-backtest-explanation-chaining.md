# バックテスト解説の2段階化（Prompt Chaining） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 既存の「バックテスト解説」（1回のLLM呼び出し）を、「結果解説→改善提案」の固定順2ステップ（Prompt Chaining）に分解する。[2026-08-09-agentic-workflow-patterns-design.md](../specs/2026-08-09-agentic-workflow-patterns-design.md)のフェーズ2を実装する。

**Architecture:** `prompt_patterns/backtest_explanation.py`に新規`build_improvement_prompt`を追加し、Step1（既存の`build_backtest_prompt`）の解説結果を入力として改善提案プロンプトを組み立てる。`portfolio_management/backtest.py`の`generate_backtest_explanation`が2回`call_llm`を呼ぶよう変更する（Step1が空文字ならgateでStep2をスキップ）。関数シグネチャ・戻り値の型（`str`のMarkdown）は変更しないため、既存の呼び出し元`app_tabs/backtest_tab.py`とキャッシュ機構（文字列キャッシュ）は無改修で恩恵を受ける。

**Tech Stack:** Python 3.14 / pandas / pytest（`call_llm`をモック化してテスト、`uv run pytest`で実行）。新規外部依存は追加しない。

## Global Constraints

- `generate_backtest_explanation`の関数シグネチャ（引数・戻り値の型）を変更しない。
- gate: Step1（`explanation`）が空文字/空白のみの場合はStep2を呼ばず、「解説の生成に失敗しました。」を返す。
- Step2（`improvement`）が空文字/空白のみの場合は改善提案セクションを省略し、Step1の結果のみを返す。
- 各プロンプトは断定的な売買判断表現を禁止する指示を含める（既存の`build_backtest_prompt`と同じ規約）。
- 出力のMarkdown先頭・末尾に`DISCLAIMER_NOTICE`を付与する既存の挙動は変更しない。

---

### Task 1: `prompt_patterns/backtest_explanation.py` — `build_improvement_prompt`

**Files:**
- Modify: `ai-stock-investing-tutorial/app/prompt_patterns/backtest_explanation.py`
- Test: `ai-stock-investing-tutorial/app/tests/test_backtest_explanation.py`

**Interfaces:**
- Consumes: 既存の`comparison: dict[str, dict]`（`run_backtest_comparison`の戻り値と同じ形）
- Produces: `build_improvement_prompt(ticker: str, comparison: dict[str, dict], explanation: str, strategy_name: str = "移動平均クロスオーバー") -> str`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_backtest_explanation.py`の末尾に以下を追加する（importも更新する）。

```python
from common.disclaimer import DISCLAIMER_NOTICE
from prompt_patterns.backtest_explanation import (
    build_backtest_prompt,
    build_improvement_prompt,
    build_ranking_comment_prompt,
    generate_ranking_comments,
)
```

```python
def test_build_improvement_prompt_includes_ticker_facts_and_prior_explanation():
    comparison = {"標準(25/75)": {"total_return_pct": 18.4, "trade_days": 312}}

    prompt = build_improvement_prompt(
        "7203.T", comparison, "これまでの解説文です。", "移動平均クロスオーバー"
    )

    assert "7203.T" in prompt
    assert "18.4" in prompt
    assert "これまでの解説文です。" in prompt
    assert DISCLAIMER_NOTICE in prompt


def test_build_improvement_prompt_instructs_overfitting_and_no_directive_language():
    comparison = {"標準(25/75)": {"total_return_pct": 18.4}}

    prompt = build_improvement_prompt("7203.T", comparison, "解説文", "移動平均クロスオーバー")

    assert "過学習" in prompt
    assert "取引コスト" in prompt
    assert "売買" in prompt


def test_build_improvement_prompt_uses_default_strategy_name_when_omitted():
    comparison = {"標準(25/75)": {"total_return_pct": 18.4}}

    prompt = build_improvement_prompt("7203.T", comparison, "解説文")

    assert "移動平均クロスオーバー戦略" in prompt
```

- [ ] **Step 2: テストを実行し、失敗することを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/test_backtest_explanation.py -v`
Expected: `ImportError: cannot import name 'build_improvement_prompt'` で失敗する。

- [ ] **Step 3: 最小限の実装を書く**

`prompt_patterns/backtest_explanation.py`の`build_backtest_prompt`関数の直後（`build_ranking_comment_prompt`の前）に以下を追加する。

```python
def build_improvement_prompt(
    ticker: str,
    comparison: dict[str, dict],
    explanation: str,
    strategy_name: str = "移動平均クロスオーバー",
) -> str:
    # Step1（結果解説）の出力を入力として受け取り、追加で検討すべき観点を
    # 生成させる2段階目のプロンプト（Prompt Chaining）。
    comparison_json = json.dumps(comparison, ensure_ascii=False, indent=2, default=str)
    return (
        f"以下は{strategy_name}戦略のバックテスト結果（Python側で計算済み）と、"
        "その結果について別のAIが作成した解説文です。\n\n"
        f"【対象銘柄】{ticker}\n"
        f"【パラメータ組ごとの結果（JSON）】\n{comparison_json}\n\n"
        f"【既存の解説】\n{explanation}\n\n"
        "この解説を踏まえ、投資家が追加で検討する価値がある観点を"
        "日本語で2〜3個、簡潔に提案してください。\n"
        "以下を必ず考慮してください。\n"
        "1. パラメータ組同士の結果が大きく異なる場合、過学習を避けるために"
        "確認すべき追加のデータ期間やパラメータ幅\n"
        "2. 取引コストやスリッページなど、本バックテストが考慮していない要因\n\n"
        "出力は教育的な提案にとどめ、「買うべき」「このルールで今すぐ売買すべき」"
        "のような指示的な表現は使わないでください。\n\n"
        f"{DISCLAIMER_NOTICE}"
    )
```

- [ ] **Step 4: テストを実行し、成功することを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/test_backtest_explanation.py -v`
Expected: 全テストPASS。

- [ ] **Step 5: コミット**

```bash
cd ai-stock-investing-tutorial
git add app/prompt_patterns/backtest_explanation.py app/tests/test_backtest_explanation.py
git commit -m "$(cat <<'EOF'
Add build_improvement_prompt for backtest explanation chaining

Second-stage prompt that takes Step1's explanation text and asks for
additional considerations (overfitting risk, transaction costs),
laying the groundwork for turning generate_backtest_explanation into
a two-step Prompt Chaining flow.
EOF
)"
```

---

### Task 2: `portfolio_management/backtest.py` — `generate_backtest_explanation`の2段階化

**Files:**
- Modify: `ai-stock-investing-tutorial/app/portfolio_management/backtest.py`
- Test: `ai-stock-investing-tutorial/app/tests/test_backtest.py`

**Interfaces:**
- Consumes: Task 1の`build_improvement_prompt(ticker, comparison, explanation, strategy_name) -> str`
- Produces: `generate_backtest_explanation(ticker, prices, backtest_func, strategy_name, presets, transaction_cost_pct, call_llm) -> str`（シグネチャ・戻り値の型は変更なし。呼び出し元`app_tabs/backtest_tab.py`は無改修）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_backtest.py`の`test_generate_backtest_explanation_uses_default_ma_strategy_when_presets_omitted`の直後に以下を追加する。

```python
def test_generate_backtest_explanation_calls_llm_twice_and_includes_improvement_section():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.Series([100, 100, 102, 102], index=dates)
    responses = iter(["結果の解説です。", "追加提案です。"])
    call_count = {"n": 0}

    def fake_call_llm(prompt):
        call_count["n"] += 1
        return next(responses)

    result = generate_backtest_explanation(
        "AAA.T",
        prices,
        presets=[("A", {"short_window": 1, "long_window": 2})],
        call_llm=fake_call_llm,
    )

    assert call_count["n"] == 2
    assert "結果の解説です。" in result
    assert "追加提案です。" in result
    assert "## 追加で検討したい観点" in result


def test_generate_backtest_explanation_second_prompt_includes_first_explanation():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.Series([100, 100, 102, 102], index=dates)
    captured_prompts = []
    responses = iter(["最初の解説文です。", "改善提案文です。"])

    def fake_call_llm(prompt):
        captured_prompts.append(prompt)
        return next(responses)

    generate_backtest_explanation(
        "AAA.T",
        prices,
        presets=[("A", {"short_window": 1, "long_window": 2})],
        call_llm=fake_call_llm,
    )

    assert "最初の解説文です。" in captured_prompts[1]
    assert "AAA.T" in captured_prompts[1]


def test_generate_backtest_explanation_gate_skips_second_call_when_explanation_empty():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.Series([100, 100, 102, 102], index=dates)
    call_count = {"n": 0}

    def fake_call_llm(prompt):
        call_count["n"] += 1
        return "   "

    result = generate_backtest_explanation(
        "AAA.T",
        prices,
        presets=[("A", {"short_window": 1, "long_window": 2})],
        call_llm=fake_call_llm,
    )

    assert call_count["n"] == 1
    assert result == "解説の生成に失敗しました。"


def test_generate_backtest_explanation_omits_improvement_section_when_step2_empty():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.Series([100, 100, 102, 102], index=dates)
    responses = iter(["結果の解説です。", "  "])

    def fake_call_llm(prompt):
        return next(responses)

    result = generate_backtest_explanation(
        "AAA.T",
        prices,
        presets=[("A", {"short_window": 1, "long_window": 2})],
        call_llm=fake_call_llm,
    )

    assert "結果の解説です。" in result
    assert "## 追加で検討したい観点" not in result
```

- [ ] **Step 2: テストを実行し、失敗することを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/test_backtest.py -v -k generate_backtest_explanation`
Expected: 新規4件が失敗する（`call_count["n"] == 2`が`1`のため、または`StopIteration`など、2段階化未実装のため）。既存4件（`test_generate_backtest_explanation_includes_disclaimer_and_commentary`等）はこの時点でもPASSのままである（変更前の実装のため）。

- [ ] **Step 3: 最小限の実装を書く**

`portfolio_management/backtest.py`の`generate_backtest_explanation`関数を以下に置き換える。

```python
def generate_backtest_explanation(
    ticker: str,
    prices: pd.Series,
    backtest_func=run_ma_crossover_backtest,
    strategy_name: str = "移動平均クロスオーバー",
    presets: list[tuple[str, dict]] | None = None,
    transaction_cost_pct: float = 0.0,
    call_llm=default_call_llm,
) -> str:
    """バックテスト結果をLLMに渡し、投資家向けの解説レポート（Markdown）を
    生成する。免責事項を先頭と末尾に必ず付与する。

    Prompt Chaining: Step1で結果解説を生成し、その出力をgate（空文字チェック）
    で検証したうえで、Step2でStep1の解説を踏まえた改善提案を生成する。
    Step1が空文字の場合はStep2に進まずエラーメッセージを返す。Step2が
    空文字の場合は改善提案セクションを省略し、Step1の結果のみ返す。
    """
    if presets is None:
        presets = STRATEGIES[strategy_name]["presets"]

    comparison = run_backtest_comparison(prices, backtest_func, presets, transaction_cost_pct)

    # Step1: 結果解説
    explanation = call_llm(build_backtest_prompt(ticker, comparison, strategy_name)).strip()
    if not explanation:
        return "解説の生成に失敗しました。"

    sections = [
        DISCLAIMER_NOTICE,
        "",
        f"# バックテスト結果解説（{ticker}）",
        "",
        explanation,
    ]

    # Step2: 改善提案（Step1の解説を入力として渡す）
    improvement_prompt = build_improvement_prompt(ticker, comparison, explanation, strategy_name)
    improvement = call_llm(improvement_prompt).strip()
    if improvement:
        sections += [
            "",
            "## 追加で検討したい観点",
            "",
            improvement,
        ]

    sections += [
        "",
        "---",
        "",
        DISCLAIMER_NOTICE,
    ]
    return "\n".join(sections)
```

`portfolio_management/backtest.py`冒頭のimportを以下に置き換える（`build_improvement_prompt`を追加）。

```python
from prompt_patterns.backtest_explanation import build_backtest_prompt, build_improvement_prompt
```

- [ ] **Step 4: テストを実行し、成功することを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/test_backtest.py -v`
Expected: 全テストPASS（新規4件・既存4件を含む`generate_backtest_explanation`関連の全テスト）。

- [ ] **Step 5: 全体テストスイートを実行し、回帰がないことを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/ -v`
Expected: 全テストPASS（回帰なし）。

- [ ] **Step 6: アプリを起動して手動確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run python -m streamlit run app.py`

ブラウザで以下を確認する:
1. 「バックテスト」タブを開き、戦略・銘柄コード（例: `7203.T`）・取得期間を選んで「バックテストを実行」を押す
2. パラメータ組ごとの比較表の下にAI解説が表示されることを確認する
3. 解説の下に「## 追加で検討したい観点」の見出しと改善提案の本文が表示されることを確認する
4. 「キャッシュを無視して再生成する」チェックを入れずに同条件で再度実行すると、（同日中は）キャッシュから即座に同じ解説・改善提案が返ることを確認する（既存のキャッシュ機構が引き続き機能する）
5. 「キャッシュを無視して再生成する」にチェックを入れて再実行すると、LLMが再度呼び出されることを確認する

問題があれば実装を修正し、再度確認する。

- [ ] **Step 7: コミット**

```bash
cd ai-stock-investing-tutorial
git add app/portfolio_management/backtest.py app/tests/test_backtest.py
git commit -m "$(cat <<'EOF'
Chain backtest explanation into result + improvement steps

generate_backtest_explanation now runs a two-step Prompt Chaining
flow: Step1 explains the backtest comparison (existing behavior,
gated on non-empty output), Step2 asks a follow-up LLM call for
additional considerations (overfitting risk, costs) based on Step1's
explanation. Signature and return type are unchanged, so
app_tabs/backtest_tab.py and its string-based cache need no changes.
EOF
)"
```

---

## Self-Review Notes

- **Spec coverage:** 設計書フェーズ2のプロンプト層（`build_improvement_prompt`）→ Task 1。データ層（Step1/Step2の連結、gate、Step2失敗時のフォールバック）→ Task 2。キャッシュ方針（シグネチャ不変・既存の文字列キャッシュそのまま流用）→ Task 2は関数シグネチャ・戻り値の型を変更しないため、`app_tabs/backtest_tab.py`のキャッシュコードは無改修で成立することを確認済み（Global Constraintsに明記）。手動確認手順（キャッシュ再利用の確認を含む）→ Task 2 Step 6。
- **プレースホルダー確認:** 各ステップに実コード・実プロンプト文言を記載済み。「後で実装」「適切なエラーハンドリングを追加」等の曖昧な指示なし。
- **型・シグネチャの一貫性:** `build_improvement_prompt(ticker, comparison, explanation, strategy_name)`の引数順・型はTask 1・2で一致。`generate_backtest_explanation`の既存シグネチャ（引数・戻り値`str`）はTask 2で変更していないことを確認済み。gateの閾値（空文字/空白のみ）・改善提案セクションの見出し文字列（`## 追加で検討したい観点`）はTask 2のテストと実装で一致。
- **既存テストへの影響確認:** `test_generate_backtest_explanation_includes_disclaimer_and_commentary`・`test_generate_backtest_explanation_passes_ticker_and_comparison_to_prompt`・`test_generate_backtest_explanation_passes_strategy_name_and_func_to_prompt`・`test_generate_backtest_explanation_uses_default_ma_strategy_when_presets_omitted`は、いずれもcall_llmが常に非空文字列を返すfakeを使い、`captured_prompts[0]`（Step1のプロンプト）またはStep1由来のテキストの`in`検査のみを行っているため、2段階化後も変更なしでPASSし続ける（Task 2 Step 1のテスト追加のみで対応し、既存テストの書き換えは不要）。
