# エージェント型ワークフローパターン導入（Routing / Prompt Chaining / Evaluator-Optimizer）設計書

## 概要・目的

`app/`の生成AI活用箇所は現在10箇所すべてが「1回のAugmented LLM呼び出し」（単発またはバッチ）であり、複数のLLM呼び出しを動的に組み合わせるワークフロー/エージェント型パターンは未使用である。これは[genai-app-integration-tutorial](https://github.com/duwenji/genai-app-integration-tutorial)の05章（エージェント型ワークフローパターン）・06章（既存アプリの統合パターン横断マッピング）が明示的に指摘しているギャップであり、両教材とも「単純な用途に留まるため複雑さが不要」と位置づけつつ、演習課題として「このパターンを`app/`に追加するならどこに使えそうか」を検討させている。

本設計書は、この演習課題に対する実際の回答として、05章が扱う4パターンのうち3つ（Routing / Prompt Chaining / Evaluator-Optimizer）を`app/`に実装する。既存の10箇所の生成AI活用は変更しない（Orchestrator-WorkersとAutonomous Agentsは、既存機能の複雑さに見合わないため本設計のスコープ外とする）。

3フェーズはそれぞれ独立した機能単位であり、優先順位（フェーズ1→2→3）の順に個別のプラン作成・実装・テストサイクルを回すことを想定する。

## 背景（既存の`app/`との整合）

- **呼び出し方式**: 全機能が`data_api.llm_client.call_llm`（Claude Code CLIサブプロセス方式）を経由する。本設計の全プロンプトもこれを踏襲する。
- **入出力契約**: JSON構造化出力を求める場合は`common.json_parsing.strip_code_fence`でコードフェンスを除去してから`json.loads`する。パース失敗時は例外を伝播させず、安全側のフォールバック値を返す（`prompt_patterns/screening.py`の`generate_screening_comments`等が先例）。
- **事実と考察の分離**: LLMに渡す事実データはPython側で計算済みのものに限り、LLMには解釈・説明のみを担わせる。生成物には`common.disclaimer.DISCLAIMER_NOTICE`を付与する。
- **確認ステップ**: 誤った解釈が実データへの操作に直結する場合（スクリーニング条件・戦略条件）は、`st.json(...)`での表示＋確定ボタンによる確認ステップを設ける。

## スコープ

- v1で実装する:
  - フェーズ1: `prompt_patterns/qa_routing.py`（新設）、`app_tabs/qa_tab.py`（新設）、`app.py`へのタブ追加
  - フェーズ2: `prompt_patterns/backtest_explanation.py`への`build_improvement_prompt`追加、`portfolio_management/backtest.py`の`generate_backtest_explanation`の2段階化
  - フェーズ3: `strategy_builder/evaluation.py`（新設）、`prompt_patterns/strategy_dialogue.py`への`build_refinement_prompt`追加、`app_tabs/strategy_builder_tab.py`の確定フロー変更
- v1で実装しない（将来課題）:
  - Orchestrator-Workers・Autonomous Agentsパターンの導入
  - フェーズ1「AI投資質問箱」でのマルチターン対話化（v1は質問1件・回答1件の単発フロー）
  - フェーズ3の評価基準へのユーザーカスタマイズ機能
  - `genai-app-integration-tutorial`側ドキュメント（case-study-map.md等）の更新 — 別セッションで対応

---

## フェーズ1: Routing — 「AI投資質問箱」タブ

### 目的

自由記述の投資に関する質問を「fundamental」「technical」「news」「portfolio」「general」の5カテゴリに分類し、既存の分析エージェント（`analysis_agents.fundamental_agent` / `technical_agent` / `news_research_agent`、`portfolio_management.composition` / `risk`）へ振り分けて回答する。既存エージェントをほぼそのまま再利用し、新規ドメインロジックを増やさない。

### プロンプト層 — `prompt_patterns/qa_routing.py`（新設）

```python
def classify_question(question: str, call_llm=default_call_llm) -> str:
    """質問文を fundamental/technical/news/portfolio/general のいずれかに分類する。
    未知のラベルが返った場合は安全側の "general" にフォールバックする。
    """

def build_fundamental_answer_prompt(question: str, fundamentals: dict) -> str: ...
def build_technical_answer_prompt(question: str, technical: dict) -> str: ...
def build_news_answer_prompt(question: str, news: list[dict]) -> str: ...
def build_portfolio_answer_prompt(question: str, composition: dict, risk: dict) -> str: ...
def build_general_answer_prompt(question: str) -> str: ...
```

- 各`build_*_answer_prompt`は、既存の`build_backtest_prompt`等と同様、事実データをJSONとしてプロンプトに埋め込み、断定的な売買判断表現を禁止する指示を含める。
- `classify_question`の分類プロンプトは、`_ROUTES`相当の許可ラベル一覧をプロンプト内で明示し、ラベル名のみを出力させる（05-02章のサンプルに準拠）。

### タブ層 — `app_tabs/qa_tab.py`（新設）

- UI: 銘柄コード入力欄（任意）＋質問入力欄（`st.text_area`）＋実行ボタン
- 分類結果に応じた分岐:
  - `fundamental`/`technical`/`news`かつ銘柄コード未入力 → `general`に読み替え、「個別銘柄について聞く場合は銘柄コードを入力してください」と案内（安全側フォールバック）
  - `fundamental`/`technical`/`news`かつ銘柄コード入力あり → 既存の`cached_analyze_fundamentals`/`analyze_technical`/`cached_fetch_news`（`app_tabs/shared.py`）で事実データ取得
  - `portfolio` → `portfolio_management.storage.load_holdings(HOLDINGS_PATH)`。保有銘柄が空なら「保有銘柄が未登録です」で終了。あれば現在値・価格履歴を取得し`analyze_portfolio_composition`/`assess_risk`で事実データ算出
  - `general` → 事実データ取得なし
- 分類カテゴリ・回答・`DISCLAIMER_NOTICE`を表示
- `app.py`に7番目のタブ「AI質問箱」として追加

### エラー処理

- `classify_question`の未知ラベル・空応答 → `general`にフォールバック（表示専用の低リスク機能のため確認ステップは設けない）
- 事実データ取得失敗（既存`cached_fetch_*`が空/例外） → 「データを取得できませんでした」を明記したままプロンプトに渡し、LLMに正直に伝えさせる

### テスト

- `tests/test_qa_routing.py`: `classify_question`の未知ラベルフォールバック、各`build_*_answer_prompt`の出力内容を`call_llm`モックで検証

---

## フェーズ2: Prompt Chaining — バックテスト解説の2段階化

### 目的

既存の「バックテスト解説」（単発呼び出し）を、「結果解説→改善提案」の固定順2ステップに分解する。genai-app-integration-tutorial 05-01章の演習課題が候補として明示している改修。

### プロンプト層 — `prompt_patterns/backtest_explanation.py`

```python
def build_improvement_prompt(
    ticker: str, comparison: dict[str, dict], explanation: str, strategy_name: str
) -> str:
    """Step1の解説文と比較データを踏まえ、追加で検証すべき指標・過学習を
    避けるための改善提案を生成させるプロンプトを組み立てる。
    断定的な売買指示は既存の build_backtest_prompt と同様に禁止する。
    """
```

### データ層 — `portfolio_management/backtest.py`の`generate_backtest_explanation`変更

```
comparison(dict) → build_backtest_prompt → call_llm → explanation
                                              ↓ gate（空文字チェック）
        build_improvement_prompt(explanation, comparison) → call_llm → improvement
                                              ↓
    最終Markdown = 解説セクション + 改善提案セクション + 免責事項
```

- 関数シグネチャは変更しない（呼び出し元`app_tabs/backtest_tab.py`は無改修で恩恵を受ける）
- **gate**: Step1（`explanation`）が空文字の場合はStep2をスキップし、「解説の生成に失敗しました」を返す
- Step2（`improvement`）が空文字の場合は改善提案セクションを省略し、Step1の結果のみ返す（Step2の失敗でStep1の価値ある結果まで失わない）

### キャッシュ

既存の`backtest_tab.py`のキャッシュキー方式（戦略・銘柄・期間・コストのハッシュ）をそのまま流用する。2段階分の結果を含む最終Markdown文字列を1つのキャッシュ値として保存する（既存の文字列キャッシュ形式を維持し、後方互換性を保つ）。

### テスト

- `tests/test_backtest_explanation.py`に`build_improvement_prompt`のテストを追加
- `tests/test_backtest.py`の`generate_backtest_explanation`テストに、2回目の`call_llm`呼び出し・gate分岐（Step1が空文字のケース）・Step2失敗時のフォールバックのテストを追加

---

## フェーズ3: Evaluator-Optimizer — AI戦略ビルダーの条件品質レビュー

### 目的

AI戦略ビルダーの対話で確定候補となった戦略JSON（`parse_dialogue_response`が`kind: "strategy"`と判定したもの）を、確定ボタン押下時に自動評価し、問題があれば改善ループを回してから最終確認画面を出す。既存の確認ステップ（`st.json(pending)` + 確定ボタン）と組み合わせる。

### 評価基準（04章ガードレールとの接続）

1. 条件が具体的か（indicator/valueが曖昧でないか）
2. 条件数が極端に少なく／多くなく、対象銘柄が0件になりそうな過度な絞り込みでないか
3. 断定的な投資助言表現を含んでいないか

### 評価層 — `strategy_builder/evaluation.py`（新設）

```python
def build_evaluate_prompt(strategy: dict) -> str:
    """上記3基準で {"pass": bool, "feedback": str} 形式のJSON出力を要求する。"""

def evaluate_strategy(strategy: dict, call_llm=default_call_llm) -> dict:
    """評価を実行する。JSONパース失敗時は安全側に倒し
    {"pass": False, "feedback": "評価結果のパースに失敗しました。"} を返す。
    """

def run_evaluation_loop(
    strategy: dict, call_llm=default_call_llm, max_iterations: int = 3
) -> dict:
    """evaluate_strategy が pass=True を返すか max_iterations に達するまで、
    build_refinement_prompt による再生成を繰り返す。
    途中でrefinementの応答がJSONとして無効な場合は、そのイテレーションを
    スキップし直前の strategy のままループを継続する。
    戻り値: {"strategy": dict, "iterations": int, "last_feedback": str | None}
    """
```

`run_evaluation_loop`をタブ層から独立した純粋関数として切り出すことで、ループ制御自体をUIなしでユニットテストできるようにする。

### プロンプト層 — `prompt_patterns/strategy_dialogue.py`への追加

```python
def build_refinement_prompt(pending_strategy: dict, feedback: str) -> str:
    """確定済みJSON＋評価フィードバックを渡し、同じJSON形式（strategy_name/
    conditions/sort_by/order）での修正案を1回で生成させる軽量プロンプト。
    既存の対話ペルソナ指示（_PERSONA_INSTRUCTIONS）は使わない。
    """
```

### タブ層 — `app_tabs/strategy_builder_tab.py`の確定フロー変更

```
pending → run_evaluation_loop(pending)
            └─ 結果の strategy を st.json で再表示
               （iterations > 0 の場合は「AIによる自動改善を行いました」を
                 st.caption で補足し、last_feedback を表示）
            └─ 改めて「この条件で確定する」ボタンで人間の最終確認を求める
               （save_strategy はこのボタン押下時のみ実行 — 既存の確認ステップ規約を維持）
```

評価・改善ループはボタン押下時に同期的に実行する（既存のマルチターン対話とは別に、確定直前の1回限りの内部ループ）。UI表示中は`st.spinner("戦略条件を評価・改善中...")`。

### テスト

- `tests/test_strategy_builder_evaluation.py`: `build_evaluate_prompt`の内容、`evaluate_strategy`のパース失敗フォールバック、`run_evaluation_loop`の合格時即終了・max_iterations到達時の打ち切り・refinement応答が無効な場合のスキップ動作
- `tests/test_strategy_dialogue_prompt.py`に`build_refinement_prompt`のテストを追加

---

## 実装順序と各フェーズの独立性

3フェーズは互いに独立しており、フェーズ1→2→3の順に「プラン作成→実装→テスト→レビュー」のサイクルを個別に回す。後続フェーズの設計が先行フェーズの実装結果に依存する箇所はない。

## テスト方針（共通）

既存の`tests/`の慣例（`call_llm`を差し替え可能な引数として受け取り、モックで応答を固定してテストする）に従う。Streamlit UI層（タブファイル自体）は既存タブと同様にユニットテスト対象外とし、手動確認で担保する。ループ制御（フェーズ3の`run_evaluation_loop`）のように、UIから独立させられるロジックは積極的に純粋関数として切り出しテスト可能にする。

## スコープ外（将来課題）

- genai-app-integration-tutorial側のcase-study-map.md更新（AI戦略ビルダーの確認ステップ記載の実態との乖離を含む）、および両教材間の相互参照リンク整備は、別セッション（サブプロジェクトB）で扱う。
- Orchestrator-WorkersパターンとAutonomous Agentsパターンの`app/`への導入は、既存機能の複雑さに見合わないため現時点では見送る。

---

投資判断に関わる内容です。必ず[DISCLAIMER.md](../../../DISCLAIMER.md)をご確認ください。
