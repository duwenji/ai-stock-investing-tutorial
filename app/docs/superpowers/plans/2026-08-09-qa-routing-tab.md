# AI投資質問箱（Routingパターン） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 自由記述の投資質問を「fundamental/technical/news/portfolio/general」の5カテゴリにLLMで分類し、既存の分析エージェント（ファンダメンタルズ・テクニカル・ニュース・ポートフォリオ構成/リスク）へ振り分けて回答する新規タブ「AI質問箱」を追加する。[2026-08-09-agentic-workflow-patterns-design.md](../specs/2026-08-09-agentic-workflow-patterns-design.md)のフェーズ1（Routingパターン）を実装する。

**Architecture:** 新規`prompt_patterns/qa_routing.py`が分類プロンプトとカテゴリ別回答プロンプトの組み立てのみを担う純粋関数群を提供する（既存の`prompt_patterns/screening.py`等と同じ役割分担）。新規`app_tabs/qa_tab.py`がUIとデータ取得（既存の`cached_analyze_fundamentals`等の再利用）・分類結果に応じた分岐・LLM呼び出しのオーケストレーションを担う（既存の`backtest_tab.py`と同じ「単発ボタン押下で完結」パターンに従い、`st.session_state`への永続化は行わない）。`app.py`に7番目のタブとして登録する。

**Tech Stack:** Python 3.14 / Streamlit / pytest（`call_llm`をモック化してテスト、`uv run pytest`で実行）。新規外部依存は追加しない。

## Global Constraints

- `classify_question`が未知のラベル・空応答を返した場合は安全側の`"general"`にフォールバックする（05-02章Routingパターンの規約）。
- `fundamental`/`technical`/`news`に分類されたが銘柄コードが未入力の場合は`"general"`に読み替え、その旨をユーザーに案内する（実データを誤って伴わない安全側フォールバック）。
- 各カテゴリの回答プロンプトは、LLMに渡す事実データをPython側で取得・整形済みのものに限り、断定的な売買判断表現を禁止する指示を含める（事実/考察分離の既存規約）。
- 回答表示の末尾に`common.disclaimer.DISCLAIMER_NOTICE`を表示する。
- 表示専用の低リスク機能のため、確認ステップ（Verificationパターン）は設けない（既存のコメント生成系機能と同じ判断基準）。

---

### Task 1: `prompt_patterns/qa_routing.py` — 分類・回答プロンプト生成

**Files:**
- Create: `ai-stock-investing-tutorial/app/prompt_patterns/qa_routing.py`
- Test: `ai-stock-investing-tutorial/app/tests/test_qa_routing.py`

**Interfaces:**
- Consumes: `data_api.llm_client.call_llm(prompt: str) -> str`（既存関数、デフォルト引数として使用）
- Produces:
  - `classify_question(question: str, call_llm=default_call_llm) -> str`（戻り値は`"fundamental"`/`"technical"`/`"news"`/`"portfolio"`/`"general"`のいずれか）
  - `build_fundamental_answer_prompt(question: str, fundamentals: dict) -> str`
  - `build_technical_answer_prompt(question: str, technical: dict) -> str`
  - `build_news_answer_prompt(question: str, news: list[dict]) -> str`
  - `build_portfolio_answer_prompt(question: str, composition: dict, risk: dict) -> str`
  - `build_general_answer_prompt(question: str) -> str`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_qa_routing.py`を新規作成する。

```python
from prompt_patterns.qa_routing import (
    build_fundamental_answer_prompt,
    build_general_answer_prompt,
    build_news_answer_prompt,
    build_portfolio_answer_prompt,
    build_technical_answer_prompt,
    classify_question,
)


def test_classify_question_returns_llm_label_when_known():
    fake_call_llm = lambda prompt: "technical"
    result = classify_question("移動平均はどうなってる？", call_llm=fake_call_llm)
    assert result == "technical"


def test_classify_question_falls_back_to_general_on_unknown_label():
    fake_call_llm = lambda prompt: "unknown_category"
    result = classify_question("よく分からない質問", call_llm=fake_call_llm)
    assert result == "general"


def test_classify_question_falls_back_to_general_on_empty_response():
    fake_call_llm = lambda prompt: "  "
    result = classify_question("質問", call_llm=fake_call_llm)
    assert result == "general"


def test_classify_question_strips_whitespace_from_label():
    fake_call_llm = lambda prompt: "  fundamental  \n"
    result = classify_question("PERは高い？", call_llm=fake_call_llm)
    assert result == "fundamental"


def test_build_fundamental_answer_prompt_includes_facts_and_question():
    prompt = build_fundamental_answer_prompt(
        "この銘柄は割安？", {"per": 12.0, "pbr": 1.1, "dividend_yield": 3.2}
    )
    assert "12.0" in prompt
    assert "1.1" in prompt
    assert "この銘柄は割安？" in prompt
    assert "断定的な売買判断" in prompt


def test_build_technical_answer_prompt_includes_facts_and_question():
    prompt = build_technical_answer_prompt(
        "上昇トレンド？", {"ma_short": 2500.0, "ma_long": 2400.0, "signal": "強気"}
    )
    assert "強気" in prompt
    assert "上昇トレンド？" in prompt
    assert "断定的な売買判断" in prompt


def test_build_news_answer_prompt_includes_headlines():
    prompt = build_news_answer_prompt(
        "最近のニュースは？", [{"title": "好決算を発表", "publisher": "X"}]
    )
    assert "好決算を発表" in prompt
    assert "最近のニュースは？" in prompt


def test_build_news_answer_prompt_handles_empty_news():
    prompt = build_news_answer_prompt("最近のニュースは？", [])
    assert "ニュースなし" in prompt


def test_build_portfolio_answer_prompt_includes_composition_and_risk():
    composition = {"holdings": [{"ticker": "AAA", "weight_pct": 40.0}], "total_value": 100000.0}
    risk = {"portfolio_volatility_pct": 18.5}
    prompt = build_portfolio_answer_prompt("リスクは高い？", composition, risk)
    assert "40.0" in prompt
    assert "18.5" in prompt
    assert "リスクは高い？" in prompt


def test_build_general_answer_prompt_includes_question():
    prompt = build_general_answer_prompt("PERとは何ですか？")
    assert "PERとは何ですか？" in prompt
    assert "断定的な" in prompt
```

- [ ] **Step 2: テストを実行し、失敗することを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/test_qa_routing.py -v`
Expected: `ModuleNotFoundError: No module named 'prompt_patterns.qa_routing'` で失敗する。

- [ ] **Step 3: 最小限の実装を書く**

`prompt_patterns/qa_routing.py`を新規作成する。

```python
# 自由記述の投資質問をカテゴリに分類し（Routingパターン）、カテゴリ別の
# 事実データを埋め込んだ回答プロンプトを組み立てるモジュール。
# 実際のデータ取得・カテゴリ分岐の実行はapp_tabs/qa_tab.pyが担う。
import json

from data_api.llm_client import call_llm as default_call_llm

_CATEGORIES = ["fundamental", "technical", "news", "portfolio", "general"]


def build_classify_prompt(question: str) -> str:
    return (
        "次の株式投資に関する質問を、fundamental, technical, news, portfolio, "
        "general のいずれか1つに分類し、分類名のみを出力してください"
        "（説明文やコードブロック記法は不要です）。\n\n"
        "- fundamental: PER・PBR・配当利回りなど個別銘柄の財務指標に関する質問\n"
        "- technical: 移動平均線など個別銘柄の値動き・チャートに関する質問\n"
        "- news: 個別銘柄の直近ニュース・センチメントに関する質問\n"
        "- portfolio: 保有銘柄全体の構成比・リスク・分散に関する質問\n"
        "- general: 上記のいずれにも当てはまらない一般的な投資知識の質問\n\n"
        f"質問: {question}"
    )


def classify_question(question: str, call_llm=default_call_llm) -> str:
    # 未知のラベルや空応答は安全側の "general" にフォールバックする。
    label = call_llm(build_classify_prompt(question)).strip()
    return label if label in _CATEGORIES else "general"


def build_fundamental_answer_prompt(question: str, fundamentals: dict) -> str:
    facts_json = json.dumps(fundamentals, ensure_ascii=False)
    return (
        "以下は対象銘柄のファンダメンタルズ指標です"
        "（Python側で取得済みのため再計算は不要です）。\n\n"
        f"{facts_json}\n\n"
        "この情報をもとに、次の質問に日本語で答えてください。"
        "断定的な売買判断は含めないでください。\n\n"
        f"質問: {question}"
    )


def build_technical_answer_prompt(question: str, technical: dict) -> str:
    facts_json = json.dumps(technical, ensure_ascii=False)
    return (
        "以下は対象銘柄のテクニカル分析結果（移動平均クロスオーバー）です"
        "（Python側で計算済みのため再計算は不要です）。\n\n"
        f"{facts_json}\n\n"
        "この情報をもとに、次の質問に日本語で答えてください。"
        "断定的な売買判断は含めないでください。\n\n"
        f"質問: {question}"
    )


def build_news_answer_prompt(question: str, news: list[dict]) -> str:
    lines = "\n".join(f"- {item['title']}" for item in news) or "- (ニュースなし)"
    return (
        "以下は対象銘柄の直近ニュース見出しです"
        "（Python側で取得済みのため再取得は不要です）。\n\n"
        f"{lines}\n\n"
        "この情報をもとに、次の質問に日本語で答えてください。"
        "断定的な売買判断は含めないでください。\n\n"
        f"質問: {question}"
    )


def build_portfolio_answer_prompt(question: str, composition: dict, risk: dict) -> str:
    facts_json = json.dumps(
        {"composition": composition, "risk": risk}, ensure_ascii=False, default=str
    )
    return (
        "以下は保有ポートフォリオ全体の構成比・リスク指標です"
        "（Python側で計算済みのため再計算は不要です）。\n\n"
        f"{facts_json}\n\n"
        "この情報をもとに、次の質問に日本語で答えてください。"
        "断定的な売買判断は含めないでください。\n\n"
        f"質問: {question}"
    )


def build_general_answer_prompt(question: str) -> str:
    return (
        "次の株式投資に関する一般的な質問に、日本語で分かりやすく答えてください。"
        "個別銘柄への断定的な売買判断は含めないでください。\n\n"
        f"質問: {question}"
    )
```

- [ ] **Step 4: テストを実行し、成功することを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/test_qa_routing.py -v`
Expected: 全テストPASS。

- [ ] **Step 5: コミット**

```bash
cd ai-stock-investing-tutorial
git add app/prompt_patterns/qa_routing.py app/tests/test_qa_routing.py
git commit -m "$(cat <<'EOF'
Add prompt_patterns/qa_routing for question classification and answers

Classifies a free-text investing question into fundamental/technical/
news/portfolio/general (Routing pattern) and builds a category-specific
answer prompt from facts computed elsewhere, following the existing
facts-in-python / LLM-interprets-only convention.
EOF
)"
```

---

### Task 2: `app_tabs/qa_tab.py` — AI質問箱タブとapp.pyへの登録

**Files:**
- Create: `ai-stock-investing-tutorial/app/app_tabs/qa_tab.py`
- Modify: `ai-stock-investing-tutorial/app/app.py`

**Interfaces:**
- Consumes:
  - Task 1: `prompt_patterns.qa_routing.classify_question(question, call_llm) -> str`、`build_fundamental_answer_prompt(question, fundamentals) -> str`、`build_technical_answer_prompt(question, technical) -> str`、`build_news_answer_prompt(question, news) -> str`、`build_portfolio_answer_prompt(question, composition, risk) -> str`、`build_general_answer_prompt(question) -> str`
  - 既存: `app_tabs.shared.cached_analyze_fundamentals(ticker) -> dict`、`cached_fetch_price_history(ticker, period) -> pd.DataFrame`、`cached_fetch_news(ticker) -> list[dict]`、`HOLDINGS_PATH`
  - 既存: `analysis_agents.technical_agent.analyze_technical(price_history) -> dict`
  - 既存: `portfolio_management.storage.load_holdings(path) -> list[dict]`
  - 既存: `portfolio_management.composition.analyze_portfolio_composition(holdings, current_prices) -> dict`
  - 既存: `portfolio_management.risk.assess_risk(price_histories) -> dict`
  - 既存: `data_api.llm_client.call_llm(prompt) -> str`、`common.disclaimer.DISCLAIMER_NOTICE`
- Produces: `render_qa_tab() -> None`（`app.py`から呼ばれる。他タスクから消費されるインターフェースなし）

- [ ] **Step 1: `app_tabs/qa_tab.py`を新規作成する**

```python
"""AI質問箱タブ: 自由記述の投資質問をカテゴリに応じて既存の分析エージェント
へ振り分けて回答する（Routingパターン）。"""

import logging

import streamlit as st

from analysis_agents.technical_agent import analyze_technical
from common.disclaimer import DISCLAIMER_NOTICE
from data_api.llm_client import call_llm
from portfolio_management.composition import analyze_portfolio_composition
from portfolio_management.risk import assess_risk
from portfolio_management.storage import load_holdings
from prompt_patterns.qa_routing import (
    build_fundamental_answer_prompt,
    build_general_answer_prompt,
    build_news_answer_prompt,
    build_portfolio_answer_prompt,
    build_technical_answer_prompt,
    classify_question,
)

from app_tabs.shared import (
    HOLDINGS_PATH,
    cached_analyze_fundamentals,
    cached_fetch_news,
    cached_fetch_price_history,
)

logger = logging.getLogger(__name__)

_CATEGORY_LABELS = {
    "fundamental": "ファンダメンタルズ",
    "technical": "テクニカル",
    "news": "ニュース",
    "portfolio": "ポートフォリオ全体",
    "general": "一般的な質問",
}


def _build_portfolio_facts() -> tuple[dict, dict] | None:
    """保有銘柄一覧から構成比・リスク指標を計算する。保有銘柄が無ければNoneを返す。"""
    holdings = load_holdings(HOLDINGS_PATH)
    if not holdings:
        return None

    current_prices: dict[str, float] = {}
    price_histories: dict = {}
    for holding in holdings:
        history = cached_fetch_price_history(holding["ticker"], "6mo")
        if not history.empty:
            current_prices[holding["ticker"]] = float(history["Close"].iloc[-1])
            price_histories[holding["ticker"]] = history["Close"]

    composition = analyze_portfolio_composition(holdings, current_prices)
    risk = assess_risk(price_histories)
    return composition, risk


def render_qa_tab() -> None:
    logger.info("AI質問箱タブを表示")
    st.header("AI投資質問箱")
    st.caption(
        "自由な言葉で投資に関する質問を入力してください。個別銘柄について"
        "聞く場合は銘柄コードも入力してください。"
    )

    ticker = st.text_input("銘柄コード（任意）", placeholder="7203.T", key="qa_ticker")
    question = st.text_area(
        "質問", placeholder="この銘柄は割安ですか？", key="qa_question"
    )

    if not st.button("質問する", disabled=not question):
        return

    with st.spinner("質問を分類しています..."):
        category = classify_question(question, call_llm=call_llm)

    note = None
    if category in ("fundamental", "technical", "news") and not ticker:
        note = "個別銘柄について聞く場合は銘柄コードを入力してください。一般的な回答を表示します。"
        category = "general"

    with st.spinner("回答を生成しています..."):
        if category == "fundamental":
            fundamentals = cached_analyze_fundamentals(ticker)
            prompt = build_fundamental_answer_prompt(question, fundamentals)
        elif category == "technical":
            history = cached_fetch_price_history(ticker, "6mo")
            technical = analyze_technical(history)
            prompt = build_technical_answer_prompt(question, technical)
        elif category == "news":
            news = cached_fetch_news(ticker)
            prompt = build_news_answer_prompt(question, news)
        elif category == "portfolio":
            facts = _build_portfolio_facts()
            if facts is None:
                st.info("保有銘柄が未登録です。ポートフォリオタブで銘柄を追加してください。")
                return
            composition, risk = facts
            prompt = build_portfolio_answer_prompt(question, composition, risk)
        else:
            prompt = build_general_answer_prompt(question)

        answer = call_llm(prompt)

    st.subheader(f"分類: {_CATEGORY_LABELS.get(category, category)}")
    if note:
        st.caption(note)
    st.write(answer)
    st.markdown(DISCLAIMER_NOTICE)
```

- [ ] **Step 2: `app.py`にタブを登録する**

`app.py`のインポートブロック（`from app_tabs.portfolio_tab import render_portfolio_tab`の直後）に1行追加する。

```python
from app_tabs.portfolio_tab import render_portfolio_tab
from app_tabs.qa_tab import render_qa_tab
from app_tabs.ranking_tab import render_ranking_tab
```

`app.py`のタブ定義部分を以下に置き換える（既存の6タブに「AI質問箱」を追加）。

```python
# 7つの主要機能をタブとして構成する
(
    tab_portfolio,
    tab_screening,
    tab_backtest,
    tab_ranking,
    tab_sector,
    tab_strategy_builder,
    tab_qa,
) = st.tabs(
    [
        "ポートフォリオ",
        "スクリーニング",
        "バックテスト",
        "一括バックテスト",
        "セクターローテーション",
        "AI戦略ビルダー",
        "AI質問箱",
    ]
)

with tab_portfolio:
    render_portfolio_tab()

with tab_screening:
    render_screening_tab()

with tab_backtest:
    render_backtest_tab()

with tab_ranking:
    render_ranking_tab()

with tab_sector:
    render_sector_tab()

with tab_strategy_builder:
    render_strategy_builder_tab()

with tab_qa:
    render_qa_tab()
```

- [ ] **Step 3: 既存テストスイートを実行し、回帰がないことを確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/ -v`
Expected: 全テストPASS（`app.py`自体はテスト対象外だが、import解決に問題がないことは次のステップの手動起動で確認する）。

- [ ] **Step 4: アプリを起動して手動確認する**

Run: `cd ai-stock-investing-tutorial/app && uv run python -m streamlit run app.py`

ブラウザで以下を確認する:
1. 「AI質問箱」タブが表示されることを確認する
2. 銘柄コードを空欄のまま「この銘柄のPERは高いですか？」のような個別銘柄向け質問を入力し「質問する」を押す → 「個別銘柄について聞く場合は銘柄コードを入力してください」という案内とともに一般的な回答が表示されることを確認する
3. 銘柄コード（例: `7203.T`）を入力し「この銘柄は割安ですか？」で質問する → 分類が「ファンダメンタルズ」となり、PER/PBR等の実データに基づく回答が表示されることを確認する
4. 同じ銘柄コードで「最近のニュースは？」を質問する → 分類が「ニュース」となることを確認する
5. ポートフォリオタブで銘柄を1件も追加していない状態で「ポートフォリオ全体のリスクは？」を質問する → 「保有銘柄が未登録です」と表示されることを確認する
6. ポートフォリオタブで銘柄を1件追加してから同じ質問をする → 分類が「ポートフォリオ全体」となり、構成比・リスク指標に基づく回答が表示されることを確認する
7. 「PERとは何ですか？」のような一般的な質問をする → 分類が「一般的な質問」となることを確認する
8. すべての回答表示の末尾に免責事項が表示されることを確認する

問題があれば実装を修正し、再度確認する。

- [ ] **Step 5: 全体テストスイートを再実行する**

Run: `cd ai-stock-investing-tutorial/app && uv run pytest tests/ -v`
Expected: 全テストPASS（回帰なし）。

- [ ] **Step 6: コミット**

```bash
cd ai-stock-investing-tutorial
git add app/app_tabs/qa_tab.py app/app.py
git commit -m "$(cat <<'EOF'
Add AI question box tab that routes questions to existing agents

New "AI質問箱" tab classifies a free-text question (fundamental/
technical/news/portfolio/general) and answers it using the matching
existing analysis agent, giving app/ its first agentic Routing
pattern (05-02 of genai-app-integration-tutorial).
EOF
)"
```

---

## Self-Review Notes

- **Spec coverage:** 設計書フェーズ1のプロンプト層（`prompt_patterns/qa_routing.py`の全6関数）→ Task 1。タブ層（銘柄コード有無による安全側フォールバック、portfolioカテゴリの保有銘柄空チェック、`app.py`への7番目のタブ登録）→ Task 2。テスト方針（`tests/test_qa_routing.py`）→ Task 1。手動確認手順（UI層はユニットテスト対象外の既存慣例に従う）→ Task 2 Step 4。
- **プレースホルダー確認:** 各ステップに実コード・実プロンプト文言を記載済み。「後で実装」「適切なエラーハンドリングを追加」等の曖昧な指示なし。
- **型・シグネチャの一貫性:** `classify_question`の戻り値ラベル集合（`fundamental`/`technical`/`news`/`portfolio`/`general`）はTask 1のプロンプト内カテゴリ説明・`_CATEGORIES`リストとTask 2の`_CATEGORY_LABELS`・分岐条件で一致。`build_*_answer_prompt`の引数名・型（`fundamentals: dict`, `technical: dict`, `news: list[dict]`, `composition: dict`, `risk: dict`）はTask 1・2で一致。
