# バックテスト パラメータ最適化（グリッドサーチ・近傍安定性チェック） 設計書

## 概要・目的

[2026-07-20-backtest-strategies-and-ranking-design.md](2026-07-20-backtest-strategies-and-ranking-design.md) で
「v2で実装しない（将来課題）」としていた「パラメータ最適化（グリッドサーチ等によるプリセット自動選定）」を実装する。

単一の「最良パラメータ」だけを採用すると過去データへの過学習（オーバーフィッティング）の危険がある。
そこで、候補パラメータの近傍範囲を格子状（グリッド）に総当たりでバックテストし、
その結果が連続的・滑らかに安定しているか（＝近傍全体で似た成績が出るか）を確認する。
一点だけ突出した成績（鋭いピーク）は過去データのノイズへの過学習を疑い、
近傍全体で安定した成績が出るパラメータ帯はより頑健（ロバスト）と判断できる、という考え方に基づく。

本機能は教育目的の参考実装であり、投資助言を行うものではない。
過学習リスクの啓発そのものが目的の一つであるため、LLM解説内で必ず明示する
（[DISCLAIMER.md](../../../DISCLAIMER.md) 準拠）。

## スコープ

- 実装する:
  - `portfolio_management/backtest.py` にグリッドサーチ・安定性判定の計算ロジックを追加
  - 既存の固定2プリセット比較（`STRATEGIES[...]["presets"]`、`run_backtest_comparison`）を廃止し、グリッドサーチに置き換える
  - 「バックテスト」タブ（単一銘柄）: ヒートマップ＋安定性サマリー表示
  - 「一括バックテスト」タブ（ユニバース）: 銘柄ごとに近傍グリッドで最良パラメータを探索してランキング
  - LLM解説（`generate_backtest_explanation`）に安定性情報（変動係数・安定判定）を渡し、過学習リスクの説明を強化
- 実装しない（将来課題）:
  - グリッド探索範囲のUI上での動的な調整（範囲は`STRATEGIES`にコードで固定）
  - 3本以上の移動平均を使った単一シグナルの合成戦略
  - 複数戦略のシグナルを組み合わせたポートフォリオ的バックテスト

## モジュール構成

既存パターンを踏襲し、新規ファイルは作らず既存ファイルを拡張する。

```
app/
  portfolio_management/
    backtest.py
      _finalize_backtest(...)                # 既存、変更なし
      _risk_adjusted_return(result) -> float  # 新規（内部共通処理、run_universe_backtest_rankingから抽出）
      run_ma_crossover_backtest(...)          # 既存、変更なし
      run_rsi_reversal_backtest(...)          # 既存、変更なし
      run_macd_crossover_backtest(...)        # 既存、変更なし
      run_bollinger_reversal_backtest(...)    # 既存、変更なし
      STRATEGIES                              # 変更：presets → param_grid + fixed_params
      run_backtest_comparison(...)            # 削除（グリッドサーチに置き換え）
      run_grid_search(...)                    # 新規
      summarize_grid_stability(...)           # 新規
      generate_backtest_explanation(...)      # シグネチャ変更：grid_resultsを受け取る形に
      run_universe_backtest_ranking(...)      # シグネチャ変更：param_grid/fixed_paramsを受け取る形に
  prompt_patterns/
    backtest_explanation.py
      build_backtest_prompt(ticker, comparison, strategy_name, stability)      # stability引数追加
      build_improvement_prompt(ticker, comparison, explanation, strategy_name, stability)  # stability引数追加
  app_tabs/
    backtest_tab.py       # ヒートマップ＋安定性サマリー表示に変更
    ranking_tab.py        # 銘柄ごとの採用パラメータ列追加、キャプション更新
  tests/
    test_backtest.py               # 新規関数・シグネチャ変更に合わせて更新
    test_backtest_explanation.py   # stability引数を考慮したプロンプト検証を追加
  docs/
    app-design.md    # 機能一覧表・4.3/4.4のシーケンス図・ステップ説明を実装に合わせて更新（詳細は後述）
  README.md           # 機能説明を更新
```

## 計算ロジック — `portfolio_management/backtest.py`

### `STRATEGIES`レジストリの変更

各戦略の`presets`（固定2種のパラメータ組）を廃止し、`param_grid`（探索する2軸パラメータ）と、
3パラメータ戦略で固定する値を持つ`fixed_params`（省略可）に置き換える。

近傍範囲は各戦略の従来「標準」プリセットを中心に、グリッド全体の組み合わせ数が
概ね15〜40通りに収まるよう定義する（多すぎると一括バックテストで452銘柄×グリッドの
計算コストが過大になるため）。

```python
STRATEGIES: dict[str, dict] = {
    "移動平均クロスオーバー": {
        "func": run_ma_crossover_backtest,
        "param_grid": {"short_window": range(20, 31), "long_window": range(65, 86, 5)},
        "min_days": 85,
    },
    "RSI逆張り": {
        "func": run_rsi_reversal_backtest,
        "param_grid": {"period": range(10, 19), "oversold": range(20, 36, 5)},
        "fixed_params": {"overbought": 70},
        "min_days": 18,
    },
    "MACDクロスオーバー": {
        "func": run_macd_crossover_backtest,
        "param_grid": {"fast": range(8, 15), "slow": range(20, 31, 2)},
        "fixed_params": {"signal": 9},
        "min_days": 30,
    },
    "ボリンジャーバンド逆張り": {
        "func": run_bollinger_reversal_backtest,
        "param_grid": {"window": range(15, 26, 2), "num_std": [1.5, 1.75, 2.0, 2.25, 2.5]},
        "min_days": 25,
    },
}
```

（`min_days`はグリッド中の最大ウィンドウ長を満たせるよう見直す。具体的な範囲・刻みは実装時に
グリッド件数と挙動を見ながら微調整してよい。）

### `_risk_adjusted_return(result: dict) -> float`（新規・内部関数）

現在`run_universe_backtest_ranking`内にベタ書きされているリスク調整済みリターン計算
（収益率÷|最大ドローダウン|、ドローダウンが0の場合は収益率をそのまま採用）を抽出し、
`run_grid_search`と`run_universe_backtest_ranking`の両方から共通利用する。

### `run_grid_search(prices, backtest_func, param_grid, fixed_params=None, transaction_cost_pct=0.0) -> list[dict]`（新規）

`param_grid`の全組み合わせ（デカルト積）でバックテストを実行する。各要素は
`{"params": {...}, **backtest結果, "risk_adjusted_return": float}`の形。
`fixed_params`が指定されていれば、全組み合わせに対して固定値として追加で渡す。

### `summarize_grid_stability(grid_results: list[dict]) -> dict`（新規）

グリッド全体の`risk_adjusted_return`から以下を算出する。

- `best`: `risk_adjusted_return`が最大の要素
- `worst`: `risk_adjusted_return`が最小の要素
- `cv`: 変動係数（標準偏差 ÷ |平均|）。近傍全体でのばらつきの大きさを表す
- `is_stable`: `cv < 0.5`を安定の目安とする。平均が0近傍（`abs(mean) < 1e-6`）で
  変動係数が定義できない場合は`is_stable=False`とし、判定不可である旨を別途フラグで示す

### `run_universe_backtest_ranking`の変更

`preset_params: dict`引数を`param_grid: dict, fixed_params: dict | None = None`に置き換える。
銘柄ごとに`run_grid_search`→`summarize_grid_stability`を実行し、その銘柄にとっての
最良パラメータ（`best`）の成績でランキングする。各行に`best_params`（採用したパラメータ）・
`stability_cv`・`is_stable`を追加する。

### `run_backtest_comparison`の削除

固定プリセット比較の廃止に伴い削除する。

## LLM解説 — `prompt_patterns/backtest_explanation.py` / `generate_backtest_explanation`

### `generate_backtest_explanation`のシグネチャ変更

```python
def generate_backtest_explanation(
    ticker: str,
    grid_results: list[dict],
    strategy_name: str = "移動平均クロスオーバー",
    call_llm=default_call_llm,
) -> str:
```

`prices`/`backtest_func`/`presets`/`transaction_cost_pct`引数を廃止し、呼び出し元
（`backtest_tab.py`）で計算済みの`grid_results`を受け取る形に変更する。これにより、
表示用ヒートマップと解説生成で同じグリッドサーチ結果を再利用でき、現状存在する
「表示用と解説用で同じバックテストを2回計算している」重複を解消する。

内部で`summarize_grid_stability(grid_results)`を呼び、`best`/`worst`の2点を
`{"最良（short_window=27, long_window=75）": {...}, "近傍最悪（...）": {...}}`の形に整形して
`build_backtest_prompt`/`build_improvement_prompt`に渡す。

### `build_backtest_prompt`/`build_improvement_prompt`への`stability`引数追加

```python
def build_backtest_prompt(
    ticker: str,
    comparison: dict[str, dict],
    strategy_name: str,
    stability: dict,  # {"cv": float, "is_stable": bool, "grid_size": int}
) -> str:
```

プロンプトの指示文を、単純な「パラメータ組同士の比較」から「近傍グリッド内での安定性」の
観点に更新する。`is_stable=False`の場合は過学習リスクをより強調するよう明示的に指示する。
LLMに変動係数を再計算させず、Python側で計算済みの値をそのまま説明させる（既存の
「数値計算はPython側で完結させる」方針を踏襲）。

## UI変更

### `app_tabs/backtest_tab.py`（単一銘柄タブ）

「パラメータ組ごとの比較」表を廃止し、以下に置き換える。

1. `run_grid_search`を1回実行し、結果をAltairの`mark_rect`によるヒートマップで表示する
   （x軸/y軸=`param_grid`の2パラメータ、色=`risk_adjusted_return`、ツールチップで各指標を表示）
2. `summarize_grid_stability`の結果から安定性サマリーを表示する
   （最良パラメータとその成績を`st.metric`等で表示、`is_stable`に応じて`st.success`/`st.warning`のバッジ、
   `cv`の値も表示）
3. `fixed_params`を持つ戦略（RSI・MACD）は、固定した値を`st.caption`で明示する
4. 同じ`grid_results`を`generate_backtest_explanation`にそのまま渡す

### `app_tabs/ranking_tab.py`（一括バックテストタブ）

- キャプションを「標準プリセットで」から「銘柄ごとに近傍グリッドで探索した最良パラメータで」に更新する
- ランキング表に「採用パラメータ」列（`best_params`）を追加し、銘柄ごとに何が選ばれたか透明性を持たせる
- 株価取得と同様、銘柄ごとのグリッドサーチも`map_concurrently`で並列化し、`st.spinner`で進捗を示す
  （452銘柄×グリッドのため計算コストが増えることへの対応）
- キャッシュキーは現状どおり戦略名・期間・コスト・対象銘柄集合ベースのままとする
  （`param_grid`はコード側で固定のため、キャッシュキーに含める必要はない）

## エラーハンドリング

- グリッド全体で`risk_adjusted_return`の平均が0近傍になるケース（全組み合わせが未取引またはリターン0）は、
  `summarize_grid_stability`で判定不可として扱い、UI側では「安定性を判定できませんでした」と表示する
- 個別銘柄のグリッドサーチが例外を投げた場合、一括バックテストの`map_concurrently`が
  既存の挙動どおり例外を結果として捕捉し、その銘柄はスキップ扱いとする（既存の`skipped_tickers`と同様の
  ハンドリングを踏襲）

## テスト方針

`tests/test_backtest.py`に以下を追加・更新する。

- `run_grid_search`: 組み合わせ数が`param_grid`の直積と一致すること、各結果に`params`と
  `risk_adjusted_return`が含まれること、`fixed_params`が全組み合わせに適用されること
- `summarize_grid_stability`: `best`/`worst`の選定が正しいこと、`cv`の計算が正しいこと、
  `is_stable`の閾値判定、平均0近傍でのフォールバック挙動
- `run_universe_backtest_ranking`: 新シグネチャでの動作、`best_params`/`stability_cv`/`is_stable`が
  結果に含まれること、データ日数不足銘柄のスキップは既存挙動を維持すること
- `generate_backtest_explanation`: `grid_results`を渡す新シグネチャでの動作、プロンプトに
  安定性情報（`cv`・`is_stable`）が含まれること
- `STRATEGIES`レジストリのテストを`param_grid`（2キー）・`min_days`の検証に更新
  （`presets`関連のテストは削除）

`tests/test_backtest_explanation.py`に、`stability`引数がプロンプトに正しく反映されることの検証を追加する。

## ドキュメント更新

- `app/docs/app-design.md`（機能一覧表・シーケンス図・ステップ説明による体系的な設計ドキュメント）を
  実装と合わせて更新する。以下は必須（本設計のスコープに含む）:
  - 4章冒頭の機能一覧表（3行目「バックテスト」・4行目「一括バックテスト」）: 「4戦略×2パラメータ組」
    「標準プリセットで一括バックテスト」の記述をグリッドサーチ・近傍安定性チェックの内容に更新する
  - 「4.3 バックテスト（単一銘柄）」のシーケンス図: `run_backtest_comparison(prices, strategy_func, presets, cost)`を
    `run_grid_search`→`summarize_grid_stability`の呼び出しに置き換え、「パラメータ組ごとの比較結果」を
    「グリッドサーチ結果＋安定性サマリー」に、UIの表示ステップをヒートマップ・安定性バッジ表示に更新する
  - 「4.3」のステップ説明1（`STRATEGIES`の`presets`→`param_grid`/`fixed_params`）・6（プロンプトの必須項目に
    安定性の観点を追加）を更新する
  - 「4.4 一括バックテスト（ランキング）」のシーケンス図: `run_universe_backtest_ranking(prices_by_ticker, func, 標準preset, cost, min_days)`を
    `param_grid`/`fixed_params`を渡す形に更新し、銘柄ごとのループ内にグリッドサーチ・安定性判定のステップを追加する
  - 「4.4」のステップ説明4「標準プリセットのみ使用」を「銘柄ごとに近傍グリッドで最良パラメータを探索」に更新する
  - なお同ドキュメントの機能一覧表・4.4節に見られる「UNIVERSE 226銘柄」という記載は現在の実際の銘柄数（452銘柄）と
    既に乖離しているが、これは本設計と無関係な既存の記載漏れであり、本設計のスコープ外として別途対応する
- `docs/05-portfolio-management/03-backtest-automation.md`（トップレベルのチュートリアル本体＝銘柄取引のknow-how教材）を
  以下2点で拡充する。同ファイルは現状MAクロスオーバーのみを教材コードとして扱っており、RSI/MACD/ボリンジャーバンドの
  3戦略は2026-07-20のv2拡張時に`app/`へは追加されたが教材本体には未反映という既存ギャップがある
  （当時の設計書も`README.md`更新のみで`docs/`更新を含んでいなかった）。今回のグリッドサーチ機能の教材化を機に、
  この既存ギャップも合わせて解消する。

  1. **新設「戦略のバリエーション」節**（「主要概念・パラメータ解説」内、既存の指標・注意点の表の前に配置）:
     4戦略（MA/RSI/MACD/BB）のエントリー・エグジット条件と主パラメータを1つの表にまとめる。
     RSI・ADXなどの指標そのものの計算方法は
     [04-analysis-agents/02-technical-analysis-agent.md](../04-analysis-agents/02-technical-analysis-agent.md)
     を参照させ重複を避け、本節では「指標をどう売買ルールに変換するか」（エントリー/エグジット条件）に絞る。
     MACD・ボリンジャーバンドはこの教材シリーズで初出のため、指標の定義も簡潔に含める。
  2. **新設「パラメータの安定性チェック（近傍グリッドサーチ）」節**（「実ソースコード」節の末尾、
     「良い例と悪い例」の前に配置）: 本設計の中核技術（近傍グリッドサーチ＋変動係数による安定性判定）を、
     既存の`run_ma_crossover_backtest`のコード例を拡張する形のコード例とともに教材化する。
     既存の「注意すべき点」表の「過学習」の行から本節へ参照を追加し、定性的な注意喚起に留まっていた
     過学習リスクに対する具体的な検証手法を示す。
  3. 演習課題2（「短期/長期の移動平均期間を変えて複数パターンでバックテストし、結果が大きく変動するかどうかを
     確認してください」）は、上記2の内容を手動で体験する導入として位置づけを明確化する文言に更新する
     （「新設節で自動化する近傍グリッドサーチを、まず手動で体験してみましょう」等）
  4. 「理解度チェック」に、近傍グリッドサーチによる安定性チェックが何を検出するための手法かを説明できる、
     という項目を追加する
- `app/README.md`の機能説明を、固定プリセット比較からグリッドサーチ・安定性チェックへの変更に合わせて更新する
