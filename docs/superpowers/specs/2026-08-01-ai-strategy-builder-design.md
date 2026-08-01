# AI戦略ビルダー（投資アイデア構築〜実践 一気通貫機能）設計

## 背景・課題

現在のアプリには、自然言語の1文をLLMで構造化フィルタ（JSON）に変換してユニバースを
絞り込む「スクリーニング」タブ（`app/app_tabs/screening_tab.py`）と、単一銘柄・単一
テクニカル戦略のバックテストを行う「バックテスト」タブがある。

しかし、次の一気通貫フローは存在しない。

1. ユーザーが曖昧な投資アイデアを自由記述で入力する
2. AIとの**対話**を通じて、具体的な財務指標・閾値を持つスクリーニング条件に詰める
3. 確定した条件を過去の値動きで**検証**する
4. 検証済みの条件を最新の市場データに適用して**今買うべき銘柄を特定**する

このドキュメントは、この一気通貫フローを新規タブ「AI戦略ビルダー」として追加する設計を定める。

## データ制約と方針転換

`app/data_api/stock_price_api.py` の `fetch_fundamentals` は yfinance の `Ticker.info` から
**現在時点の**PER・PBR・配当利回りのスナップショットのみを取得しており、過去の各時点で
その銘柄がどの財務指標だったか（ポイントインタイム・ファンダメンタルズ）は保持していない。
yfinanceの四半期財務データは日本株では欠損が多く、数年分程度しか遡れないため、
「過去の各時点で条件を満たしていた銘柄群」を厳密に再現するバックテストは、
このアプリのデータ層では実現しない。

このため③のバックテストは、**現在の財務指標で選定した銘柄群を、過去に遡って
均等金額で購入・保有し続けた場合の株価推移**を示す簡易シミュレーションとする。
これは「過去の各時点で同条件を満たしていたか」を考慮しないルックアヘッドバイアスを
含むため、画面上に明示的な注記を出す。

## 全体構成

既存5タブ（ポートフォリオ／スクリーニング／バックテスト／一括バックテスト／
セクターローテーション）は一切変更せず、新規タブ「AI戦略ビルダー」を追加する。

```
app/strategy_builder/
  __init__.py
  storage.py      # 戦略JSONの保存・読込（portfolio_management/storage.py と同パターン）
  conditions.py   # 戦略JSON条件の適用・並び替え・判定理由の生成
  backtest.py     # 簡易バックテスト（等金額購入シミュレーション）
app/prompt_patterns/strategy_dialogue.py  # 対話用ペルソナ・プロンプト構築・応答解析
app/app_tabs/strategy_builder_tab.py      # タブUI本体
app/data/strategies.json                  # 確定済み戦略の保存先（新規、holdings.json同様に未コミット運用）
```

`app/app.py` には6番目のタブとして1行追加するのみ。

### LLM呼び出し方式

既存の `data_api/llm_client.call_llm` は毎回固定のシステムプロンプト
（「指示に厳密に従うアシスタント」）を送るサブプロセス呼び出しであり、
ターン単位のセッション状態を持たない。これを変更せず、依頼書にある
「クオンツ・アナリスト」ペルソナとステップ指示は、既存の
`prompt_patterns/screening.py::build_screening_prompt` と同様に
**ユーザープロンプト本文に埋め込む**。対話の各ターンでは、会話全履歴を
毎回プロンプトに含めて送信する（ステートレスなCLI呼び出しのため）。

### 指標の拡張

依頼書のペルソナ例にあるROE・売上高伸び率は現行の `fetch_fundamentals` が
取得していない。yfinanceの `info` に `returnOnEquity` / `revenueGrowth` があるため、
`fetch_fundamentals` / `fetch_universe_fundamentals` に `roe_pct` / `revenue_growth_pct`
を追加する。既存フィールドは変更しないため、既存スクリーニングタブの動作に影響しない。

## 機能① アイデア入力

- `st.text_area`（キー: `strategy_idea_text`）で自由記述の投資アイデアを入力
- テンプレートボタン3つ（「バリュー株」「グロース株」「配当株」）: クリックで
  `session_state["strategy_idea_text"]` に定型文を設定し `st.rerun()` して反映
- 「対話を始める」ボタンで、この文言を対話の最初のユーザー発言として機能②を開始

## 機能② AI協調型ロジック構築エンジン

- `st.session_state["strategy_chat_history"]`: `[{"role": "user"|"assistant", "content": str}]`
- `prompt_patterns/strategy_dialogue.py::build_dialogue_prompt(history)` が、
  ペルソナ指示＋会話全履歴＋出力形式指示（「合意できるまでは1〜2個の質問・提案のみを
  短く返す。合意できたら説明文なしで指定JSON形式のみを```json コードブロックで返す」）
  を組み立て、`call_llm` に渡す
- `parse_dialogue_response(raw)` が応答を判定する:
  - JSONコードブロック（`common/json_parsing.strip_code_fence` 使用）として解析でき、
    かつ `strategy_name` / `conditions` を含む → 「確定候補」として `st.json` で表示し、
    「この条件で確定する」／「さらに対話を続ける」ボタンを表示
  - それ以外 → AIの質問・提案テキストとして `st.chat_message("assistant")` で表示
- `st.chat_input` でユーザーの返信を受け付け、履歴に追加して再度LLM呼び出し（`st.rerun`）
- 「確定する」を押すと `strategy_builder.storage.save_strategy()` で
  `app/data/strategies.json` に追記保存し、機能③④のセクションを表示可能にする
- タブ上部に「保存済み戦略を開く」セレクトボックスを設置。過去の戦略を選ぶと
  対話をスキップし、直接その戦略で機能③④に進める

### 戦略JSONスキーマ（依頼書のシステムプロンプト準拠）

```json
{
  "strategy_name": "確定した戦略名",
  "conditions": [
    {"indicator": "PER", "operator": "LESS_THAN", "value": 15},
    {"indicator": "ROE", "operator": "GREATER_THAN", "value": 10}
  ],
  "sort_by": "ROE",
  "order": "DESC"
}
```

既存スクリーニングタブが使う `apply_filters` のスキーマ（`field`/記号演算子）とは
別スキーマとして扱う。`strategy_builder/conditions.py` に、
`indicator`（PER/PBR/ROE/DIVIDEND_YIELD/REVENUE_GROWTH等）→ DataFrame列名、
`operator`（LESS_THAN/LESS_EQUAL/GREATER_THAN/GREATER_EQUAL/EQUALS）→比較関数の
ホワイトリスト辞書を持つ次の関数を実装する。

- `apply_strategy_conditions(df, strategy) -> pd.DataFrame`: 条件を順に適用
- `sort_by_strategy(df, strategy) -> pd.DataFrame`: `sort_by`/`order`で並び替え
- `build_match_reason(row, conditions) -> str`: 各条件について実際の値と閾値を
  機械的に整形した判定理由文字列を生成する（例:「PER 12.3倍（条件: 15未満）／
  ROE 15.2%（条件: 10より大）」）。LLMを呼ばず決定的に生成することで、
  スクリーニング結果の「判定理由」列を高速かつ正確にする

## 機能③ バックテスト検証モジュール（簡易版）

1. 期間セレクトボックス（**1y/2y**）
2. 確定戦略の条件で現在のユニバースfundamentalsを絞り込み
   （`fetch_universe_fundamentals` + `apply_strategy_conditions`）→ 該当銘柄を確定
3. 該当銘柄の株価履歴を並行取得。`data_api/stock_price_api.py` に
   `fetch_universe_price_histories(tickers, period, cache_dir) -> dict[str, pd.Series]`
   を新設する（`fetch_universe_fundamentals` と同じ並行取得＋キャッシュのパターン）
4. `strategy_builder/backtest.py::run_strategy_backtest(prices_by_ticker) -> dict`:
   各銘柄の株価をその銘柄の開始日=100に正規化し、日次で銘柄平均（`skipna=True`）を
   とった「等金額購入・保有」の資産推移曲線を作成する。
   - **累積リターン**・**最大ドローダウン**はこの資産推移曲線から算出
   - **勝率**は「期間トータルリターン（終値/始値-1）がプラスだった銘柄数の割合」と
     定義する（買い持ち戦略にはポジション0/1の概念がないため、既存の
     `portfolio_management/backtest.py::_finalize_backtest` の勝率定義とは異なる）
   - 銘柄によって株価データの開始日が異なる場合（新規上場等）は、共通日付インデックスの
     union上でNaNを許容し、平均計算時にskipnaで対応する
5. `st.metric` で3指標、Altairで資産推移の折れ線グラフ、銘柄別トータルリターンの
   内訳テーブルを表示
6. 「本バックテストは現在の財務指標で選んだ銘柄群を過去に遡って保有した想定であり、
   過去時点で同条件を満たしていたかは考慮していません（先読みバイアスあり）」という
   注記と、既存 `common/disclaimer.DISCLAIMER_NOTICE` を明示する

## 機能④ 銘柄選定（スクリーニング）実行画面

- 「最新データで銘柄選定を実行」ボタン → `fetch_universe_fundamentals` に
  `apply_strategy_conditions` を適用し、`sort_by_strategy` で並び替え
- `st.dataframe` で銘柄コード・銘柄名・現在の株価・判定理由（`build_match_reason`）を
  一覧表示。行クリックで既存の `handle_table_selection`（銘柄詳細ダイアログ）を再利用
- 選定結果テーブルの下に「選定銘柄の業種ネットワーク」セクションを追加（後述）

### 業種間ネットワーク図の再利用

既存のセクターローテーションタブは、UNIVERSE全228銘柄の株価取得＋136業種ペアの
ウェーブレット分析という重い処理（初回30秒程度）の結果を `st.session_state["sector_payload"]`
に保持し、`sector_analysis/network.py::build_mermaid_lead_lag_graph` でMermaid図として描画する。

この重い処理を両タブから呼べるよう、現在 `app_tabs/sector/tab.py` の
`render_sector_tab()` 内（`if run_clicked:` ブロック）にUI処理と一体化して埋め込まれている
「キャッシュ確認→並列株価取得→`compute_sector_returns`/`compute_lead_lag_pairs`/
`compute_all_pairs_dominant_lag`→AIコメント生成→キャッシュ書き込み→
`session_state["sector_payload"]`更新」の一連処理を、
`app_tabs/shared.py::run_or_load_sector_rotation(period, force_regenerate) -> dict`
として切り出す。`sector/tab.py` はこの関数を呼ぶだけに簡素化し、動作は変わらない。

`app_tabs/sector/network_diagram.py` の private関数 `_render_mermaid` は
`app_tabs/shared.py::render_mermaid(code, height)` として公開し、両タブから共用する。

機能④側の業種ネットワークセクションの挙動:

- `st.session_state.get("sector_payload")` が既にあれば、機能④の選定銘柄群の業種集合で
  `network_pairs` を絞り込み（`leading_sector`/`lagging_sector`のいずれかが選定銘柄の
  業種に含まれる行のみ）、セクタータブと同じ周期帯・コヒーレンス閾値の選択UIで
  Mermaid図を描画する
- なければ「今すぐ分析を実行」ボタンを表示し、押すと `run_or_load_sector_rotation` を
  呼んで同じ処理を実行する（機能③のバックテスト期間セレクトボックスと同じ1y/2yを
  分析期間として使う）。同一期間・同一UNIVERSEであれば、セクタータブ側のキャッシュと
  共有され二重計算を避ける

## テスト

既存踏襲（UIタブ自体は単体テストせず、ロジックモジュールを単体テストする）。

- `tests/test_strategy_builder_storage.py`: 保存・読込の往復、壊れたJSON/不正形式の
  フォールバック（`portfolio_management/storage.py`のテストと同パターン）
- `tests/test_strategy_dialogue_prompt.py`: `build_dialogue_prompt`が履歴とペルソナ指示を
  含むこと、`parse_dialogue_response`がJSON確定候補と質問テキストを正しく判別すること
  （コードフェンス付き/不正JSON/キー欠落を含む）
- `tests/test_strategy_builder_conditions.py`: `apply_strategy_conditions`の
  indicator/operatorの組み合わせ、`sort_by_strategy`、`build_match_reason`の文字列生成
- `tests/test_strategy_builder_backtest.py`: 合成した複数銘柄の株価Seriesで累積リターン・
  最大ドローダウン・勝率を既知の値で検証し、銘柄ごとに開始日が異なる場合の整合性を確認する
- 既存 `tests/test_stock_price_api.py` に `fetch_universe_price_histories` のテストと、
  `fetch_fundamentals`のROE/売上高伸び率追加分のテストケースを追加する

## ドキュメント

- `docs/06-real-world-examples/04-strategy-builder-agent.md` を新規追加し、既存の
  `02-screening-dashboard.md` を踏まえて「対話でロジックを詰める→検証→実行」という
  一気通貫の流れを解説する。`00-README.md`・`MASTER-INDEX.md`・前後リンクも更新する
- 各画面に既存 `DISCLAIMER.md` への言及を配置する（既存パターン踏襲）

## 影響を受けないもの

- 既存5タブ（ポートフォリオ／スクリーニング／バックテスト／一括バックテスト／
  セクターローテーション）のUI・動作
- `apply_filters`（既存スクリーニングタブが使うフィルタスキーマ）
- `holdings.json` / `sector_display_settings.json` のデータ構造
- `data_api/llm_client.py`（`call_llm`のシグネチャ・システムプロンプト）
