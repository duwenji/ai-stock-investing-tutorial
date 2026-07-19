# バックテスト機能 設計書

## 概要・目的

`docs/05-portfolio-management/03-backtest-automation.md` で扱う「移動平均クロスオーバー戦略のベクトル化バックテスト＋LLMによる結果解説」を `app/` に統合する。

[2026-07-19-portfolio-screening-app-design.md](2026-07-19-portfolio-screening-app-design.md) では「v1スコープ外」としていたバックテスト機能を、今回新たに追加する。

本機能は教育目的の参考実装であり、投資助言を行うものではない。バックテスト結果は過去データに対する検証結果に過ぎず将来の成績を保証しないことを、LLM解説内で必ず明示する（[DISCLAIMER.md](../../../DISCLAIMER.md) 準拠）。

## スコープ

- 対象: 日本株1銘柄に対する移動平均クロスオーバー戦略のバックテスト
- v1で実装する:
  - 単一パラメータ組（短期/長期移動平均）でのベクトル化バックテスト計算
  - 取引コスト（1回あたり0.1%、教材の演習課題1相当）を考慮したバックテスト計算
  - 「短期(5/25)」「標準(25/75)」の2パラメータ組を並べて比較する機能（教材の演習課題2相当）
  - LLMによる結果解説（本文のプロンプト要件＋パラメータ間の結果差への言及）
  - Streamlit「バックテスト」タブでのUI提供
- v1で実装しない（将来課題）:
  - 3本以上の移動平均を使った単一シグナルの合成戦略
  - 移動平均クロスオーバー以外の戦略（RSI、MACD等）
  - 複数銘柄の一括バックテスト

## モジュール構成

既存の `portfolio_management` / `prompt_patterns` の構成パターンを踏襲する。

```
app/
  portfolio_management/
    backtest.py                 # run_ma_crossover_backtest, BACKTEST_PRESETS,
                                 # run_backtest_comparison, generate_backtest_explanation
  prompt_patterns/
    backtest_explanation.py     # build_backtest_prompt
  app.py                        # 「バックテスト」タブを追加
  tests/
    test_backtest.py
    test_backtest_explanation.py
```

## 計算ロジック — `portfolio_management/backtest.py`

### `run_ma_crossover_backtest(prices, short_window=25, long_window=75, transaction_cost_pct=0.0) -> dict`

教材本文のロジックをそのまま移植する:

- 短期MA・長期MAを算出し、`短期MA > 長期MA` の日をロングポジション（1）とする
- ルックアヘッドバイアスを避けるため、シグナルを1日ずらす（`shift(1)`）
- 日次リターン・戦略リターン・Buy&Holdベンチマークリターンを計算
- 累積リターン、勝率（シグナルに従った日のうちプラスリターンの割合）、最大ドローダウンを算出

`transaction_cost_pct > 0` の場合の追加処理（演習課題1）:

- ポジションが前日から変化した日（`position.diff() != 0` かつ最初の非ゼロ変化を除く）を「取引が発生した日」とみなす
- 該当日の戦略リターンから `transaction_cost_pct` を差し引く
- エントリー・エグジットそれぞれが1回の取引としてコストが発生する（買い直後の反対売買を含め、ポジション変化のたびにコストを計上する単純化モデルとする。スリッページは考慮しない）

返り値（既存コードの `_pct` 命名規則に合わせる）:

```python
{
    "total_return_pct": float,
    "benchmark_return_pct": float,
    "win_rate_pct": float,
    "max_drawdown_pct": float,
    "trade_days": int,
}
```

### `BACKTEST_PRESETS`

```python
BACKTEST_PRESETS = [
    ("短期(5/25)", 5, 25),
    ("標準(25/75)", 25, 75),
]
```

### `run_backtest_comparison(prices, presets=BACKTEST_PRESETS, transaction_cost_pct=0.0) -> dict[str, dict]`

各プリセットについて `run_ma_crossover_backtest` を呼び出し、ラベルをキーとした結果の辞書を返す。

```python
{
    "短期(5/25)": {"total_return_pct": ..., ...},
    "標準(25/75)": {"total_return_pct": ..., ...},
}
```

### `generate_backtest_explanation(ticker, prices, presets=BACKTEST_PRESETS, transaction_cost_pct=0.0, call_llm=default_call_llm) -> str`

`portfolio_management/review.py` の `generate_portfolio_review` と同じ統合パターン:

1. `run_backtest_comparison` で事実データを計算
2. `build_backtest_prompt(ticker, comparison)` でプロンプトを生成
3. `call_llm(prompt)` で解説文を取得
4. `DISCLAIMER_NOTICE` を冒頭・末尾に付与して返す

## プロンプト設計 — `prompt_patterns/backtest_explanation.py`

### `build_backtest_prompt(ticker: str, comparison: dict[str, dict]) -> str`

`prompt_patterns/report_generation.py` と同様、事実データ（比較結果の辞書）をJSON化してプロンプトに埋め込む。LLMへの指示に以下を必須で含める（教材本文のプロンプト要件を踏襲）:

1. 各パラメータ組について、戦略のリターンとベンチマーク（Buy&Hold）の比較
2. 勝率・最大ドローダウンの意味の説明
3. 過去の結果が将来の成績を保証しないこと。特にパラメータを過去データに合わせすぎる過学習のリスク、取引コスト・スリッページを考慮しきれていない可能性への注意喚起
4. **パラメータ組（短期(5/25) と 標準(25/75)）の結果を比較し、大きく異なっている場合はパラメータ選択に対する過学習リスクを強調する**（演習課題2の意図を解説文に反映）
5. 追加で確認する価値がある指標・シナリオの提案（実行はしない）
6. 「買うべき」「このルールで今すぐ売買すべき」等の指示的な表現を使わない

末尾に `DISCLAIMER_NOTICE` を付与する。

## UI — `app.py`「バックテスト」タブ

既存の「ポートフォリオ」「スクリーニング」タブに並べて `st.tabs` に追加する。

1. 銘柄コード入力（テキスト入力、例: `7203.T`）
2. 取得期間の選択（`st.selectbox`、デフォルト `3y`、選択肢: `1y`/`3y`/`5y`）
3. 「取引コストを考慮する（1回あたり0.1%）」チェックボックス（デフォルトOFF。ONの場合 `transaction_cost_pct=0.1` を渡す）
4. 「バックテストを実行」ボタン
5. 実行後:
   - `data_api.stock_price_api.fetch_price_history(ticker, period=period)` で株価取得（既存関数を再利用、失敗時・データ不足時はエラー表示して中断）
   - `run_backtest_comparison` の結果を `st.dataframe` で比較テーブル表示（行=パラメータ組、列=各指標）
   - `generate_backtest_explanation` を呼び出し、`st.markdown` で解説文を表示
   - キャッシュ: ポートフォリオレビューと同様、`common/cache.py` を使い `"backtest-" + sha256(ticker + period + transaction_cost_pct + プリセット内容)` をキーに日次キャッシュする。「キャッシュを無視して再生成する」チェックボックスも同様に用意する

## エラーハンドリング

- 株価データが取得できない、または最長ウィンドウ（75日）に満たない場合: `analyze_technical` の「データ不足」パターンに倣い、バックテストを実行せず `st.error` でメッセージ表示する
- LLM呼び出し失敗: 該当箇所を「生成失敗」として表示し、比較テーブル（事実データ）の表示は継続する

## テスト方針

- `tests/test_backtest.py`:
  - `run_ma_crossover_backtest`: 既知の価格系列に対する計算結果の検証、`transaction_cost_pct` 指定時にリターンが減少することの検証
  - `run_backtest_comparison`: 2プリセット分の結果がラベルをキーに返ることの検証
  - `generate_backtest_explanation`: `call_llm` をモック化し、免責事項が含まれること・比較結果がプロンプトに渡っていることを検証（`test_review.py` と同様のパターン）
- `tests/test_backtest_explanation.py`:
  - `build_backtest_prompt`: 両パターンの数値、過学習・取引コストへの注意喚起、指示的表現禁止の指示が含まれることを検証（`test_report_generation.py` と同様のパターン）
- yfinance呼び出しは既存方針通りテストでは行わず、`fetch_price_history` の結果を模した `pd.Series`/`pd.DataFrame` を直接関数に渡す

## ドキュメント更新

- `README.md` の「機能」に「バックテスト」タブの説明を追加する

## v1スコープ外（将来課題）

- 3本以上の移動平均を使った単一シグナルの合成戦略
- 移動平均クロスオーバー以外の戦略
- 複数銘柄の一括バックテスト・ランキング
