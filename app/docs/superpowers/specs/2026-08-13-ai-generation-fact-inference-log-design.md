# 事実情報とAI推論情報の記録・区別（AI生成ログ基盤） 設計書

## 背景・目的

現在アプリ内のLLM生成箇所（`generate_stock_detail`の総合コメント、AI戦略ビルダーの対話・
評価改善ループなど）は、PER/PBR・テクニカルシグナル・ニュース要約・戦略JSONといった
**事実情報**をプロンプトに埋め込み、LLMに一括で文章やJSONを生成させている。生成結果は
その場で画面表示されるか（ディスクキャッシュに保存されることはあっても）、DBには
残らない。そのため、

- 後から「このAIコメントはどの事実データに基づいていたか」を追跡できない（監査・
  信頼性の可視化ができない）
- AIの見解（例: 総合コメントの含み、戦略ビルダーの評価フィードバック）が後日の実績と
  照らしてどの程度的中していたかを検証する手段がない
- 同じ事実に対する過去のAI見解を再利用する仕組みがない

という課題がある。本設計では、LLM呼び出しのたびに「入力した事実情報」と「LLMが返した
見解・推論」を明確に分離してDBへ記録する基盤を整備し、将来の監査・検証・再利用の
土台とする。

## スコープ（Phase 1）

- 対象:
  - `stock_detail/detail.py::generate_stock_detail`（総合コメント・事業内容コメントの
    2種類のLLM呼び出し）
  - AI戦略ビルダー（`app_tabs/strategy_builder_tab.py`の対話ターン、
    `strategy_builder/evaluation.py`のEvaluator-Optimizerループ）
- 管理画面（`admin.py`/`app_tabs/admin_tab.py`）への最小限の一覧表示を含む
- 対象外（Phase 1では見送り。将来フェーズで検討）:
  - ニュースタイトル・要約の日本語訳呼び出し（翻訳であり、事実/推論の区別が本質的に
    無いため）
  - Q&Aタブ（`qa_routing.py`）、ニュースセンチメント（`news_research_agent.py`）、
    セクターローテーション・スクリーニングレポート等、その他のLLM生成箇所
  - AIの見解の的中率を実際に算出する検証バッチ・ジョブ（本設計はそのためのデータ基盤
    のみを用意する）
  - 事実スナップショットのハッシュ照合による「同一事実なら再生成をスキップする」
    仕組み（既存のディスクキャッシュ`common/cache.py`と役割が重複するため、必要になれば
    別途設計する）
  - 管理画面での行クリックによる詳細展開（Phase 1は読み取り専用の一覧表示のみ）

## データモデル

新規テーブルを2つ追加する（既存テーブルへの列追加ではないため、`db/engine.py`の
`_add_column_if_missing`方式は使わず、`Base.metadata.create_all`による自動作成のみで
足りる）。

### `ai_sessions`（セッション単位のメタデータ）

| カラム | 型 | Nullable | 内容 |
|---|---|---|---|
| `id` | str (uuid4 hex) PK | No | セッションID。呼び出し元（アプリコード）が生成する |
| `feature` | str | No | セッション種別（例: `stock_detail`, `strategy_dialogue`） |
| `ticker` | str | Yes | 銘柄に紐づく場合のみ設定 |
| `user_id` | int, FK→`users.id` | Yes | セッションを開始したユーザー |
| `started_at` | datetime | No | 既定値: 作成時のUTC時刻 |

単発生成（総合コメント等）では1呼び出しごとに新規セッションを発行する。対話や
評価改善ループのような複数回のLLM呼び出しは、同一セッションIDを使い回すことで
一連の流れとして後から追跡できる。

### `ai_generations`（個々のLLM呼び出し。事実とAI推論を分離して保持）

| カラム | 型 | Nullable | 内容 |
|---|---|---|---|
| `id` | int PK (autoincrement) | No | |
| `session_id` | str, FK→`ai_sessions.id`, index | No | |
| `turn_index` | int | No | セッション内の呼び出し順（0始まり） |
| `feature` | str | No | 呼び出し単位の細かい種別（例: `strategy_evaluate`） |
| `facts` | Text (JSON文字列) | No | プロンプトに与えた**事実情報のスナップショット** |
| `prompt` | Text | No | LLMへ実際に送信したプロンプト全文 |
| `ai_output` | Text | No | LLMの生応答（**AIの見解・推論**） |
| `created_at` | datetime | No | 既定値: 作成時のUTC時刻 |

`ticker`/`user_id`は`ai_sessions`側にのみ持たせ、セッション内の各行での重複を避ける。

## 組み込み方式

### 共通ロガー: `common/ai_generation_log.py`（新規）

```python
def log_ai_generation(
    session_id: str,
    feature: str,
    facts: dict,
    prompt: str,
    ai_output: str,
    *,
    turn_index: int = 0,
    ticker: str | None = None,
    user_id: int | None = None,
    session_feature: str | None = None,
    session_factory=SessionLocal,
) -> None:
    ...
```

`session_id`に対応する`ai_sessions`行が無ければ新規作成し（`session_feature`未指定時は
`feature`を流用）、`ai_generations`行を1件追加する。呼び出し元は「事実」「プロンプト」
「AI応答」をそのまま渡すだけでよい。他のDBアクセス関数と同様に`session_factory`を
差し替え可能にし、テストではインメモリSQLite等に差し替える。

### `stock_detail/detail.py::generate_stock_detail`

- 新規オプション引数`user_id: int | None = None`を追加する（本モジュールはst.*に
  依存しない方針を維持するため、値は呼び出し元から受け取るのみ）。
- ディスクキャッシュがヒットした場合はLLMを呼ばないため、ログも記録しない
  （記録対象は「実際にLLMを呼んだ生成」のみ）。
- LLM呼び出しの直前に`session_id = uuid.uuid4().hex`を発行する。
- `comment = call_llm(prompt)`の後: `log_ai_generation(session_id, "stock_detail_comment", facts={"fundamentals": fundamentals, "technical": technical, "news": news}, prompt=prompt, ai_output=comment, turn_index=0, ticker=ticker, user_id=user_id, session_feature="stock_detail")`
- `profile_comment = call_llm(profile_prompt)`の後（`business_summary`がある場合のみ）:
  `turn_index=1, feature="stock_detail_profile", facts={"sector":..., "industry":..., "business_summary": business_summary}`

呼び出し元`app_tabs/shared.py`（`show_stock_detail_dialog`）は既存の`get_current_user_id()`
の戻り値を`generate_stock_detail(..., user_id=...)`にそのまま渡す。

### AI戦略ビルダー

- `app_tabs/strategy_builder_tab.py`: 「対話を始める」ボタン押下時に
  `st.session_state["strategy_ai_session_id"] = uuid.uuid4().hex`と
  `st.session_state["strategy_ai_turn"] = 0`を初期化する（対話リセット時も同様に
  再発行する）。
- 対話ターン（`build_dialogue_prompt`の呼び出し）: `log_ai_generation(session_id, "strategy_dialogue_turn", facts={"history": history, "sectors": sectors}, prompt=prompt, ai_output=raw, turn_index=turn, ticker=None, user_id=get_current_user_id(), session_feature="strategy_dialogue")`。呼び出しごとに`turn`をインクリメントする。
- `strategy_builder/evaluation.py`の`evaluate_strategy`/`run_evaluation_loop`は、
  `stock_detail/detail.py`と同様にst.*非依存の方針を維持するため、
  `session_id`・`turn_index`の開始値・`user_id`をオプション引数として受け取る形に拡張する。
  - `evaluate_strategy`呼び出し: `feature="strategy_evaluate"`, `facts={"strategy": strategy}`
  - `build_refinement_prompt`呼び出し: `feature="strategy_refine"`, `facts={"strategy": current, "feedback": last_feedback}`
  - いずれも対話ターンと同じ`session_id`を共有し、`turn_index`を連番で継続する。これにより
    「事実（戦略JSON）→AIの評価・フィードバック→改善」という反省サイクル全体が
    1セッションとして後から追える。

## 管理画面への最小限の一覧表示

- `admin.py`に`list_ai_generations(limit=200, session_factory=SessionLocal) -> list[dict]`
  を追加する。`ai_sessions`と`ai_generations`を`session_id`でJOINし、`users`ともJOINして
  ユーザー名を解決する。`created_at`の新しい順に最大`limit`件を返す
  （無制限に増え続けるテーブルのため、一覧取得は常に上限を設ける）。返す各辞書は
  `session_id` / `feature` / `ticker` / `username` / `turn_index` / `created_at` /
  `ai_output`（表示用に長い場合は先頭N文字に切り詰め）を含む。
- `app_tabs/admin_tab.py`の`render_admin_tab()`に`_render_ai_generation_log()`を追加し、
  既存の「全ユーザー戦略管理」等と同様に`st.dataframe`で読み取り専用表示する。

## テスト方針

既存の慣習（`call_llm`/`session_factory`等をDIで差し替え可能にし、コアロジックは
pytestで単体テスト、UI描画部分の`app_tabs/*.py`は自動テスト対象外）に従う。

- `common/ai_generation_log.py`: `log_ai_generation`が新規セッションを作成すること、
  既存セッションには`ai_generations`行のみ追加すること、を検証する単体テスト
- `stock_detail/detail.py::generate_stock_detail`: `session_factory`をインメモリDBに
  差し替え、`comment`生成時に1件、`profile_comment`生成時にさらに1件（同一
  `session_id`、`turn_index`が0/1）が記録されることを検証。`business_summary`が無い
  ケースでは2件目が記録されないことも確認する
- `strategy_builder/evaluation.py`: `evaluate_strategy`/`run_evaluation_loop`が
  渡された`session_id`・`turn_index`でログを記録すること、イテレーションごとに
  `turn_index`が連番で増えることを検証
- `admin.py::list_ai_generations`: セッション・ユーザーのJOIN結果が期待通りの辞書に
  なることを検証する単体テスト
