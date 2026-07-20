# バックテスト機能拡張（複数戦略・複数銘柄ランキング） 設計書

## 概要・目的

[2026-07-20-backtest-automation-design.md](2026-07-20-backtest-automation-design.md) で「v1スコープ外（将来課題）」としていた以下2点を実装する。

- 移動平均クロスオーバー以外の戦略（RSI、MACD等）
- 複数銘柄の一括バックテスト・ランキング

本機能は教育目的の参考実装であり、投資助言を行うものではない。バックテスト結果は過去データに対する検証結果に過ぎず将来の成績を保証しないことを、LLM解説内で必ず明示する（[DISCLAIMER.md](../../../DISCLAIMER.md) 準拠）。既存の「単一銘柄・移動平均クロスオーバーのみ」の設計・実装を土台として拡張する。

## スコープ

- v2で実装する:
  - RSI逆張り、MACDクロスオーバー、ボリンジャーバンド逆張りの3戦略を追加
  - 既存「バックテスト」タブに戦略選択を追加し、4戦略すべてを単一銘柄に対して実行できるようにする
  - 「一括バックテスト」タブを新設し、UNIVERSE（[screening/universe.py](../../../screening/universe.py)）＋保有銘柄を対象に、選択した1戦略の標準プリセットで全銘柄をバックテストし、リスク調整済みリターンでランキング表示する
  - ランキング上位5銘柄に対するAIの一言コメント生成
- v2で実装しない（将来課題）:
  - 3本以上の移動平均を使った単一シグナルの合成戦略
  - 複数戦略のシグナルを組み合わせたポートフォリオ的バックテスト
  - パラメータ最適化（グリッドサーチ等によるプリセット自動選定）

## モジュール構成

既存パターンを踏襲し、新規ファイルは作らず既存ファイルを拡張する。

```
app/
  portfolio_management/
    backtest.py
      _finalize_backtest(prices, position, transaction_cost_pct) -> dict   # 新規（内部共通処理）
      run_ma_crossover_backtest(...)       # 既存、内部実装を _finalize_backtest 呼び出しに変更（返り値は不変）
      run_rsi_reversal_backtest(...)       # 新規
      run_macd_crossover_backtest(...)     # 新規
      run_bollinger_reversal_backtest(...) # 新規
      STRATEGIES                           # 新規：戦略レジストリ
      run_backtest_comparison(prices, backtest_func, presets, transaction_cost_pct=0.0)  # シグネチャ変更
      generate_backtest_explanation(...)   # strategy_name / backtest_func 引数を追加
      run_universe_backtest_ranking(prices_by_ticker, backtest_func, preset_params, transaction_cost_pct=0.0) -> list[dict]  # 新規
  prompt_patterns/
    backtest_explanation.py
      build_backtest_prompt(ticker, comparison, strategy_name="移動平均クロスオーバー")  # strategy_name 引数追加
      build_ranking_comment_prompt(ranking_rows: list[dict]) -> str                     # 新規
      generate_ranking_comments(ranking_rows, call_llm=default_call_llm) -> dict[str, str]  # 新規
  app.py                          # 「バックテスト」タブ拡張＋「一括バックテスト」タブ新設
  tests/
    test_backtest.py              # 既存テスト更新＋新規戦略・ランキングのテスト追加
    test_backtest_explanation.py  # 既存テスト更新＋ランキングコメント用テスト追加
```

## 計算ロジック — `portfolio_management/backtest.py`

### `_finalize_backtest(prices, position, transaction_cost_pct) -> dict`（新規・内部関数）

既存 `run_ma_crossover_backtest` の「シグナルをshift(1)した後」の処理をそのまま抽出する。引数 `position` は **shift済み**（ルックアヘッドバイアス回避済み）の0/1系列を受け取る。

- 日次リターン・戦略リターン・Buy&Holdベンチマークリターンを計算
- `transaction_cost_pct > 0` の場合、ポジション変化日に取引コストを差し引く（既存ロジックのまま）
- 累積リターン、勝率、最大ドローダウンを算出
- 返り値は既存と同じ形:

```python
{
    "total_return_pct": float,
    "benchmark_return_pct": float,
    "win_rate_pct": float,
    "max_drawdown_pct": float,
    "trade_days": int,
}
```

### `run_ma_crossover_backtest(prices, short_window=25, long_window=75, transaction_cost_pct=0.0) -> dict`

既存のまま。内部で `position = (short_ma > long_ma).astype(int).shift(1).fillna(0)` を計算した後、`_finalize_backtest(prices, position, transaction_cost_pct)` を呼ぶ形にリファクタする。**返り値・既存テストの期待値は変更しない。**

### `run_rsi_reversal_backtest(prices, period=14, oversold=30, overbought=70, transaction_cost_pct=0.0) -> dict`

- RSIを算出（`pandas` の `diff()` → 上昇/下降平均の比率、Wilderの平滑化ではなく単純移動平均で計算する簡易版とする。教材の技術指標計算との整合は不要、ベクトル化バックテスト用途に限定するため）
- ロングエントリー: RSIが `oversold` を下から上に回復した日（`RSI.shift(1) < oversold` かつ `RSI >= oversold`）
- ロング手仕舞い: RSIが `overbought` 以上になった日
- 上記のエントリー/手仕舞いシグナルから `ffill().fillna(0)` でポジション系列を構築し、shift(1)してから `_finalize_backtest` へ渡す

### `run_macd_crossover_backtest(prices, fast=12, slow=26, signal=9, transaction_cost_pct=0.0) -> dict`

- `MACD = EMA(fast) - EMA(slow)`、`signal_line = EMA(MACD, signal)`
- `position = (MACD > signal_line).astype(int)` をshift(1)して `_finalize_backtest` へ渡す（MAクロスオーバーと同じ形のロジック）

### `run_bollinger_reversal_backtest(prices, window=20, num_std=2.0, transaction_cost_pct=0.0) -> dict`

- 中心線 = `prices.rolling(window).mean()`、下バンド = `中心線 - num_std * prices.rolling(window).std()`
- ロングエントリー: 終値が下バンドを下回った日
- ロング手仕舞い: 終値が中心線（移動平均）以上に回帰した日
- RSI逆張りと同様に `ffill().fillna(0)` でポジション構築 → shift(1) → `_finalize_backtest`

### `STRATEGIES` レジストリ

```python
STRATEGIES: dict[str, dict] = {
    "移動平均クロスオーバー": {
        "func": run_ma_crossover_backtest,
        "presets": [
            ("標準(25/75)", {"short_window": 25, "long_window": 75}),
            ("短期(5/25)", {"short_window": 5, "long_window": 25}),
        ],
        "min_days": 75,
    },
    "RSI逆張り": {
        "func": run_rsi_reversal_backtest,
        "presets": [
            ("標準(14, 30/70)", {"period": 14, "oversold": 30, "overbought": 70}),
            ("厳格(14, 20/80)", {"period": 14, "oversold": 20, "overbought": 80}),
        ],
        "min_days": 14,
    },
    "MACDクロスオーバー": {
        "func": run_macd_crossover_backtest,
        "presets": [
            ("標準(12/26/9)", {"fast": 12, "slow": 26, "signal": 9}),
            ("短期(5/13/5)", {"fast": 5, "slow": 13, "signal": 5}),
        ],
        "min_days": 26,
    },
    "ボリンジャーバンド逆張り": {
        "func": run_bollinger_reversal_backtest,
        "presets": [
            ("標準(20, 2.0σ)", {"window": 20, "num_std": 2.0}),
            ("タイト(20, 1.5σ)", {"window": 20, "num_std": 1.5}),
        ],
        "min_days": 20,
    },
}
```

各戦略の1つ目のプリセット（`presets[0]`）を「標準プリセット」とし、一括バックテスト・ランキングではこれを使う。

### `run_backtest_comparison(prices, backtest_func, presets, transaction_cost_pct=0.0) -> dict[str, dict]`（シグネチャ変更）

```python
def run_backtest_comparison(prices, backtest_func, presets, transaction_cost_pct=0.0):
    return {
        label: backtest_func(prices, transaction_cost_pct=transaction_cost_pct, **params)
        for label, params in presets
    }
```

`presets` は `list[tuple[str, dict]]`（レジストリの `presets` と同形式）。旧シグネチャ（`presets: list[tuple[str, int, int]]`、`BACKTEST_PRESETS` 定数）は廃止し、呼び出し側・既存テストを新形式に更新する。

### `generate_backtest_explanation(ticker, prices, backtest_func=run_ma_crossover_backtest, strategy_name="移動平均クロスオーバー", presets=None, transaction_cost_pct=0.0, call_llm=default_call_llm) -> str`

- `presets`省略時は `STRATEGIES["移動平均クロスオーバー"]["presets"]` を使う（既存デフォルト動作を維持）
- `run_backtest_comparison(prices, backtest_func, presets, transaction_cost_pct)` で比較結果を計算
- `build_backtest_prompt(ticker, comparison, strategy_name)` でプロンプト生成
- 以降は既存ロジック（`call_llm` → `DISCLAIMER_NOTICE` で前後を挟む）のまま

### `run_universe_backtest_ranking(prices_by_ticker: dict[str, pd.Series], backtest_func, preset_params: dict, transaction_cost_pct=0.0, min_days: int = 0) -> list[dict]`（新規）

```python
def run_universe_backtest_ranking(prices_by_ticker, backtest_func, preset_params, transaction_cost_pct=0.0, min_days=0):
    rows = []
    for ticker, prices in prices_by_ticker.items():
        if len(prices) < min_days:
            continue
        result = backtest_func(prices, transaction_cost_pct=transaction_cost_pct, **preset_params)
        drawdown = abs(result["max_drawdown_pct"])
        result["risk_adjusted_return"] = (
            result["total_return_pct"] / drawdown if drawdown else result["total_return_pct"]
        )
        rows.append({"ticker": ticker, **result})
    return sorted(rows, key=lambda row: row["risk_adjusted_return"], reverse=True)
```

- 銘柄コードごとの株価取得（yfinance呼び出し）は `app.py` 側の責務とし、この関数自体はテスト容易性のため `pd.Series` の辞書を直接受け取る（既存方針の踏襲）
- データ不足銘柄は `min_days` でスキップ（呼び出し不能な銘柄は `app.py` 側で事前に除外し、この関数には渡さない）

## プロンプト設計 — `prompt_patterns/backtest_explanation.py`

### `build_backtest_prompt(ticker, comparison, strategy_name="移動平均クロスオーバー") -> str`（引数追加）

既存の「以下は移動平均クロスオーバー戦略の...」という固定文言を `f"以下は{strategy_name}戦略の..."` に変更する以外は既存ロジックのまま。デフォルト値により省略時は既存の文言・既存テストの期待値と一致する。

### `build_ranking_comment_prompt(ranking_rows: list[dict]) -> str`（新規）

上位5銘柄（`ticker`, `total_return_pct`, `risk_adjusted_return` 等）をJSON化してプロンプトに埋め込み、`prompt_patterns/screening.py` の `build_comment_prompt` と同様のパターンで、銘柄ごとに投資家向け一言コメント（断定的な売買判断を含めない）を求める。出力形式は `{"<ticker>": "<コメント>"}` のJSON。

### `generate_ranking_comments(ranking_rows, call_llm=default_call_llm) -> dict[str, str]`（新規）

`generate_screening_comments` と同じパターン: 空リストなら `{}` を返す。JSONパース失敗時は全銘柄に対して `"コメント生成失敗"` を返す。

## UI — `app.py`

### 既存「バックテスト」タブの変更

1. 戦略選択 `st.selectbox("戦略", list(STRATEGIES.keys()), key="backtest_strategy")` を追加（デフォルト = リストの先頭 = 「移動平均クロスオーバー」）
2. 選択された戦略の `min_days` でデータ不足チェック（`max(long_window ...)` の決め打ちを廃止）
3. `run_backtest_comparison(prices, strategy["func"], strategy["presets"], transaction_cost_pct)` を呼ぶ
4. キャッシュキーに戦略名を含める: `f"backtest-{strategy_key}-{ticker}-{period}-{cost}"`
5. `generate_backtest_explanation(ticker, prices, backtest_func=strategy["func"], strategy_name=strategy_key, presets=strategy["presets"], transaction_cost_pct=...)` を呼ぶ

### 新規「一括バックテスト」タブ

タブ構成を4つに変更: `["ポートフォリオ", "スクリーニング", "バックテスト", "一括バックテスト"]`

1. 戦略選択 `st.selectbox("戦略", list(STRATEGIES.keys()), key="ranking_strategy")`
2. 取得期間選択（`1y`/`3y`/`5y`、デフォルト`3y`）
3. 「取引コストを考慮する（1回あたり0.1%）」チェックボックス
4. 「キャッシュを無視して再生成する」チェックボックス
5. 「一括バックテストを実行」ボタン
6. 実行後:
   - 対象銘柄 = `UNIVERSE`（[screening/universe.py](../../../screening/universe.py)）と `load_holdings(HOLDINGS_PATH)` の銘柄コードを結合・重複除去したリスト（常時結合、UI選択なし）
   - キャッシュキー: `"universe-backtest-" + sha256(strategy_key + period + cost + sorted(tickers))`
   - キャッシュヒット時はキャッシュ済みのランキング結果・コメントをそのまま表示
   - キャッシュミス時:
     - `st.progress` で進捗を表示しながら各銘柄について `fetch_price_history(ticker, period=period)` を実行。取得失敗（例外）・空データの銘柄は「スキップ銘柄」リストに追加してスキップする
     - `run_universe_backtest_ranking(prices_by_ticker, strategy["func"], strategy["presets"][0][1], transaction_cost_pct, min_days=strategy["min_days"])` でランキングを計算
     - 銘柄名は `UNIVERSE_NAMES` と保有銘柄の `candidate_names`（ポートフォリオタブと同じ `build_candidate_names`）を合わせて解決する
     - `generate_ranking_comments(ranking_rows[:5], call_llm=call_llm)` で上位5銘柄のAIコメントを生成
     - 結果（ランキング行・コメント・スキップ銘柄一覧）をキャッシュに保存
   - `st.dataframe` でランキング表示（列: 順位・銘柄コード・銘柄名・累積リターン・ベンチマーク・勝率・最大DD・リスク調整済みリターン）
   - スキップ銘柄があれば `st.info` で一覧表示
   - 上位5銘柄について `st.write` でAIコメントを表示し、末尾に `DISCLAIMER_NOTICE` を表示

## エラーハンドリング

- 単一銘柄タブ: 既存通り（データ不足・取得失敗時は `st.error` で中断）
- 一括バックテストタブ:
  - 銘柄単位の取得失敗・データ不足はスキップして継続（全滅時のみ `st.error` で「バックテスト可能な銘柄がありませんでした」を表示）
  - AIコメント生成失敗時は該当銘柄に「コメント生成失敗」を表示し、ランキング表自体の表示は継続

## テスト方針

- `tests/test_backtest.py`:
  - `_finalize_backtest` を介した既存 `run_ma_crossover_backtest` のテストが変更なしで通ること（リファクタの回帰確認）
  - `run_rsi_reversal_backtest` / `run_macd_crossover_backtest` / `run_bollinger_reversal_backtest`: 既知の価格系列に対するエントリー・手仕舞いタイミングの検証（shift(1)によるルックアヘッドバイアス回避を含む）
  - `STRATEGIES`: 4戦略それぞれが `func`/`presets`/`min_days` キーを持つことの検証
  - `run_backtest_comparison`: 新シグネチャ（`backtest_func`, `presets: list[tuple[str, dict]]`）での動作検証（既存テストを更新）
  - `run_universe_backtest_ranking`: 複数銘柄の結果が `risk_adjusted_return` 降順でソートされること、`min_days` 未満の銘柄がスキップされること、`max_drawdown_pct == 0` の場合に0除算にならないことを検証
  - `generate_backtest_explanation`: `strategy_name` がプロンプトに反映されることの検証（既存テストを更新）
- `tests/test_backtest_explanation.py`:
  - `build_backtest_prompt`: `strategy_name` を指定した場合・省略した場合（デフォルト値で既存文言と一致）の両方を検証
  - `build_ranking_comment_prompt` / `generate_ranking_comments`: `prompt_patterns/screening.py` の対応するテストと同様のパターンで検証
- yfinance呼び出しは既存方針通りテストでは行わず、`pd.Series` の辞書を直接関数に渡す

## ドキュメント更新

- `README.md` の「機能」に「一括バックテスト」タブの説明を追加し、「バックテスト」タブの説明を戦略選択対応の文言に更新する
- 本ドキュメントの前身である [2026-07-20-backtest-automation-design.md](2026-07-20-backtest-automation-design.md) の「v1スコープ外」節は変更せず、履歴として残す

## v2スコープ外（将来課題）

- 3本以上の移動平均を使った単一シグナルの合成戦略
- 複数戦略のシグナルを組み合わせたポートフォリオ的バックテスト
- パラメータ最適化（グリッドサーチ等）
