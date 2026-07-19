# ポートフォリオ管理・スクリーニング統合アプリ 設計書

## 概要・目的

`ai-stock-investing-tutorial/docs/` で学んだ内容（株価API連携・プロンプト設計・分析エージェント・ポートフォリオ管理）を統合し、個人が実際に使える1つのStreamlit Webアプリを `app/` に構築する。

対象ユースケースは2つ:

1. 保有銘柄（ポートフォリオ）の状態監視 — 構成比・損益・リスク・銘柄別スナップショットを統合したレビューレポートを生成する
2. 自然言語条件による新規銘柄のスクリーニング — 主要銘柄の中から条件に合うものを探す

この2つを1つのWebアプリの中でタブ切替により提供する。

本アプリは教育目的の参考実装であり、投資助言を行うものではない。生成される全てのレポート・レビューには免責事項を明示する（[DISCLAIMER.md](../../../DISCLAIMER.md) 準拠）。

## スコープ

- 対象: 個人（開発者本人）が1人で使うローカル実行のWebアプリ
- 対象市場: 日本株（`.T` サフィックス）を主とする
- v1で実装する: ポートフォリオレビュー、自然言語スクリーニング、両者に必要な共通データ取得・LLM連携基盤
- v1で実装しない（将来課題）: MCPサーバー化、メール/Slack通知、複数ユーザー対応・認証、日経225全銘柄対応、バックテスト機能

## アーキテクチャ

Streamlit単一アプリ + タブ切替方式を採用する（`st.tabs` で「ポートフォリオ」「スクリーニング」を切り替え）。

検討した代替案:

- **マルチページアプリ（pages/ ディレクトリ）**: 機能が2つしかない現時点では分割の恩恵が薄く、保有銘柄データなど共有状態の受け渡しが煩雑になるため見送り。
- **FastAPIバックエンド + フロントエンド分離**: 個人が1人で使うツールに対して明らかに過剰。プロセスが2つになり起動・デプロイの手間が増える。

単一アプリ方式を選んだ理由: 個人用途として過不足ない規模であり、バックエンドロジックを素のPython関数として実装するため、将来CLIツール等を追加したくなった場合もimportするだけで再利用できる。

## モジュール構成

`docs/` 内のコード例が参照しているパッケージ名（`data_api`, `analysis_agents`, `prompt_patterns`, `portfolio_management`）をそのまま踏襲する。教材を読み返しながら実装を追いやすくするため。

```
app/
  app.py                      # Streamlitエントリーポイント（タブ切替のみ、ロジックは持たない）
  data_api/
    stock_price_api.py        # fetch_price_history, fetch_fundamentals, fetch_news
    llm_client.py             # call_llm（Claude Code CLIサブプロセス呼び出し）
  prompt_patterns/
    screening.py              # build_screening_prompt, apply_filters
    report_generation.py      # build_report_prompt（事実/考察分離・免責事項組み込み）
  analysis_agents/
    fundamental_agent.py      # analyze_fundamentals（PER/PBR等）
    technical_agent.py        # analyze_technical（移動平均ベースの簡易シグナル）
    news_research_agent.py    # research_news（yfinanceニュース見出し→LLMセンチメント、バッチ対応）
  portfolio_management/
    composition.py            # analyze_portfolio_composition（構成比・損益）
    risk.py                    # assess_risk（ボラティリティ・相関）
    storage.py                 # load_holdings / save_holdings（JSON永続化）
  screening/
    universe.py                # 固定ユニバース定数（主要40〜50銘柄）
  common/
    disclaimer.py               # DISCLAIMER_NOTICE 定数
    cache.py                    # 日付キー付きファイルキャッシュのヘルパー関数
  data/                         # 実行時生成データ（gitignore対象）: holdings.json, cache/
  tests/                        # pytest（yfinance・call_llmはモック化）
  pyproject.toml                # uvで管理
  .env.example
```

## データフロー — ポートフォリオタブ

1. **起動時**: `portfolio_management/storage.py` の `load_holdings()` が `data/holdings.json` を読み込む（未作成なら空リストから開始し、破損していれば空リストにフォールバックして警告表示）。
2. **保有銘柄の編集**: `st.data_editor` で一覧をテーブル表示・編集可能にする（ティッカー・株数・取得単価）。「保存」ボタンで `save_holdings()` が即座にJSONへ書き込む。
3. **レビュー生成**（ボタン押下）:
   - `analyze_portfolio_composition(holdings)` — 現在値ベースの構成比・損益を計算（事実データ）
   - `assess_risk(holdings)` — 過去株価からボラティリティ・銘柄間相関を計算（事実データ）
   - 保有銘柄すべての fundamental（PER/PBR）・technical（移動平均シグナル）を個別に計算し、news センチメントは**保有銘柄すべてをまとめた1回のLLM呼び出し**でバッチ取得する（サブプロセス起動オーバーヘッド対策）
   - 上記すべての事実を `build_report_prompt(facts)` に渡し、`call_llm()` でAIの考察文を生成する。プロンプトには「観察事項として記述し、売買の推奨・指示・目標株価の提示は行わない」ことを明示する
   - `DISCLAIMER_NOTICE` をレポート冒頭・末尾に付与し、`st.markdown` で表示する
4. **キャッシュ**: 同日・同一保有構成であれば `common/cache.py` の日付+保有内容ハッシュキーで生成済みレポートを再利用し、無駄なLLM呼び出しを避ける。「再生成」ボタンで強制更新可能にする。

## データフロー — スクリーニングタブ

1. 固定ユニバース（`screening/universe.py` に定義する主要40〜50銘柄）を使用する。日経225全銘柄を毎回取得すると起動のたびに大量のネットワーク呼び出しが発生し動作が重くなるため、v1では流動性の高い主要銘柄のサブセットに限定する。選定基準は「日経225構成銘柄のうち時価総額上位40〜50社」とし、業種の偏りを避けるため主要セクターから概ね均等に含める。将来的に定数を拡張すれば増やせる。
2. ユーザーが自然言語で条件を入力する（例:「PERが15倍以下で配当利回りが3%以上」）。
3. `build_screening_prompt(condition_text)` → `call_llm()` でJSON形式のフィルタ条件に変換する。
4. **確認ステップ**: `st.json(filters)` で変換結果を必ず表示し、「この条件で絞り込む」ボタンを押すまで実データには適用しない。誤解釈があればこの時点で気づける。
5. ボタン押下で `fetch_universe_fundamentals(universe)`（キャッシュ付きでyfinance一括取得）→ `apply_filters(df, filters)` で絞り込みを実行する。
6. 絞り込み結果を `st.dataframe` で一覧表示する。各銘柄への一言AIコメントは、行ごとに呼び出すのではなく**該当銘柄すべてをまとめた1回のプロンプト**でJSON配列として一括生成する。

## LLM連携（Claude Code CLI）

Anthropic/OpenAIのAPIキーを別途契約せず、既存のClaude Codeサブスクリプションを利用する。

- `data_api/llm_client.py` の `call_llm(prompt: str, timeout: int = 120) -> str` は `subprocess.run(["claude", "-p", prompt], capture_output=True, text=True, timeout=timeout)` の形でリスト引数として実行する（`shell=True` を使わないことで、ユーザー入力を含むプロンプトでもコマンドインジェクションの懸念がない）。
- JSON形式の応答が必要な箇所（スクリーニング条件のフィルタ変換、銘柄コメントの一括生成）は、プロンプト内で「JSONのみを出力してください」と明示し、応答をパースする。パース失敗時はエラーを表示し再試行を促す。
- サブプロセス起動はAPI直接呼び出しより遅いため、複数銘柄に対するコメント生成・センチメント分析は個別呼び出しではなく**1回のプロンプトにまとめてバッチ処理**する（ポートフォリオタブのニューススナップショット、スクリーニングタブの一言コメント双方に適用）。
- **起動時チェック**: アプリ起動時に `shutil.which("claude")` でCLIの存在を確認し、無ければ分かりやすいエラーメッセージを表示して停止する。
- **失敗時**: `subprocess.run` の returncode が非0、またはタイムアウトの場合は `st.error` で表示する。バッチ処理が失敗した場合は該当箇所全体を「生成失敗」として表示し、他の処理（事実データの表示等）は継続する。

## データ永続化

- 保有銘柄: `data/holdings.json`（`[{"ticker": str, "shares": int, "cost": float}, ...]`）
- キャッシュ: `data/cache/` 配下に日付キー付きファイル（ポートフォリオレビュー、ユニバースfundamentals双方で共通の `common/cache.py` ヘルパーを使う）
- `data/` ディレクトリ全体を `.gitignore` に追加する

## エラーハンドリング

- **個別銘柄のデータ取得失敗**: `.get()` + Noneチェックによる防御的実装（docsの「良い例」を踏襲）。取得できない銘柄は「データ取得不可」と表示し、処理全体は継続する。
- **LLM呼び出し失敗**: 該当箇所のみ「生成失敗」とし、他の事実データの表示は継続する。
- **`claude` CLI未検出**: アプリ起動時に停止し、インストール・ログイン手順を促すメッセージを表示する。
- **`holdings.json` 破損/読み込み失敗**: 空リストにフォールバックし、警告を表示する。

## 免責事項の扱い

- `common/disclaimer.py` の `DISCLAIMER_NOTICE` を、ポートフォリオレビュー・スクリーニング結果のレポート本文冒頭・末尾の両方に必ず挿入する。
- サイドバーにも免責事項を常時表示する。
- AIによる考察・コメントは、Python側で計算した「事実」と明確に分離して表示する（見出しレベルで区別する）。
- プロンプト内で「売買の推奨・指示・目標株価の提示は行わない」ことを明示し、観察事項としての言い回しに限定する。

## テスト方針

- `data_api` / `analysis_agents` / `portfolio_management` の純粋関数を pytest でユニットテストする。yfinance呼び出し・`call_llm`（サブプロセス）はモック化する。
- Streamlit UI部分（`app.py`）はロジックを持たせず、テスト可能な関数への薄い呼び出しのみとする。UI自体は `streamlit run app.py` で実際に操作して手動確認する。

## v1スコープ外（将来課題）

- MCPサーバー経由でのデータ取得への置き換え
- レポートのメール/Slack自動送信
- 複数ユーザー対応・認証
- 日経225全銘柄への対応拡大
- バックテスト機能（`05-portfolio-management` で扱うが、今回の統合対象には含めない）
