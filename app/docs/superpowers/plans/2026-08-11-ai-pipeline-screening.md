# AI戦略ビルダー: 関数チェーン方式スクリーニングパイプライン Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AIとの対話で、既存のバックテストランキング・直近シグナル判定・ファンダメンタルズフィルタ等の関数を任意の順番・組み合わせで呼び出す「スクリーニングパイプライン」を組み立て、実行できるようにする。

**Architecture:** 候補銘柄テーブル（`ticker`列を含む`pd.DataFrame`）を共通データ形式とし、`(candidates_df, params, cache_dir) -> pd.DataFrame`という統一シグネチャの関数群をレジストリ（`PIPELINE_FUNCTIONS`）に登録する。AIが自然言語の要望から生成する`steps`（関数名とparamsの配列）を、汎用の実行エンジン（`run_pipeline`）がそのまま順に適用する。既存の`conditions`ベース戦略・UIは非破壊のまま維持し、新形式`steps`と共存させる。

**Tech Stack:** Python 3, pandas, Streamlit, SQLAlchemy, pytest（既存規約: monkeypatchでネットワーク/DB外部依存を排除、`tmp_path`で一時DB/キャッシュ）。

## Global Constraints

- 設計書: `docs/superpowers/specs/2026-08-11-ai-pipeline-screening-design.md`（このapp配下）に準拠する。
- 既存の`conditions`ベース戦略・UIコードパスは変更しない（後方互換）。
- `within_days`（クロス判定期間）は固定5営業日、パラメータ化しない。
- ネイティブLLM Function Calling API（tool_use）は使わない。LLMにJSONを出力させ、Python側でホワイトリスト方式に実行する既存パターンを踏襲する。
- 作業ディレクトリは `c:\Dev\tutorials\ai-stock-investing-tutorial\app`。テストは `.venv/Scripts/python.exe -m pytest <path> -v` で実行する。
- 既存の`*_tab.py`（Streamlit UI）にはpytestテストが一切無い（プロジェクトの既定方針）。UIタスクは`run`スキルでのブラウザ手動確認で仕上げる。

---

## File Structure

- **Modify** `portfolio_management/backtest.py`: 4戦略の指標系列計算を`compute_*`関数として切り出し、`run_*_backtest`から再利用。ユニバースバックテストのキャッシュキー生成を共有関数化。
- **Modify** `app_tabs/ranking_tab.py`: 上記キャッシュキー共有関数を使うよう最小修正（キャッシュキーの実値は不変）。
- **Create** `strategy_builder/pipeline_functions.py`: `PIPELINE_FUNCTIONS`レジストリと6関数（`BACKTEST_RANK`/`MULTI_STRATEGY_RANK`/`FILTER_CURRENT_SIGNAL`/`FILTER_BY_FUNDAMENTALS`/`SORT_BY`/`TOP_N`）の実体。
- **Create** `strategy_builder/pipeline.py`: `run_pipeline`実行エンジン。
- **Modify** `prompt_patterns/strategy_dialogue.py`: `PIPELINE_FUNCTIONS`を元にしたペルソナ指示、`steps`スキーマの解析、改善プロンプトの`steps`対応。
- **Modify** `strategy_builder/evaluation.py`: 改善案の受理判定を`conditions`/`steps`どちらのスキーマかで分岐するよう修正（既存バグ修正）。
- **Modify** `app_tabs/strategy_builder_tab.py`: `steps`の有無でUIを分岐し、新セクション「③ パイプラインを実行」を追加。
- **Test**: `tests/test_backtest.py`（既存、追記）、`tests/test_strategy_builder_pipeline_functions.py`（新規）、`tests/test_strategy_builder_pipeline.py`（新規）、`tests/test_strategy_dialogue_prompt.py`（既存、追記）、`tests/test_strategy_builder_evaluation.py`（既存、追記）。

---

## Task 1: backtest.pyの指標系列計算を関数として切り出す

**Files:**
- Modify: `portfolio_management/backtest.py:99-201`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Produces: `compute_ma_crossover_series(prices, short_window, long_window) -> tuple[pd.Series, pd.Series]`（short_ma, long_ma）、`compute_rsi_series(prices, period) -> pd.Series`、`compute_macd_series(prices, fast, slow, signal) -> tuple[pd.Series, pd.Series]`（macd_line, signal_line）、`compute_bollinger_bands(prices, window, num_std) -> tuple[pd.Series, pd.Series]`（middle_band, lower_band）

- [ ] **Step 1: 失敗するテストを追加する**

`tests/test_backtest.py`の先頭import文に以下を追加:

```python
from portfolio_management.backtest import (
    STRATEGIES,
    compute_bollinger_bands,
    compute_ma_crossover_series,
    compute_macd_series,
    compute_rsi_series,
    generate_backtest_explanation,
    run_bollinger_reversal_backtest,
    run_grid_search,
    run_ma_crossover_backtest,
    run_macd_crossover_backtest,
    run_rsi_reversal_backtest,
    run_universe_backtest_ranking,
    summarize_grid_stability,
)
```

ファイル末尾に追記:

```python
def test_compute_ma_crossover_series_returns_rolling_means():
    dates = pd.date_range("2026-01-01", periods=6, freq="D")
    prices = pd.Series([100, 100, 102, 102, 105, 108], index=dates, dtype=float)

    short_ma, long_ma = compute_ma_crossover_series(prices, short_window=2, long_window=4)

    pd.testing.assert_series_equal(short_ma, prices.rolling(2).mean())
    pd.testing.assert_series_equal(long_ma, prices.rolling(4).mean())


def test_compute_rsi_series_matches_manual_formula():
    dates = pd.date_range("2026-01-01", periods=9, freq="D")
    prices = pd.Series([100, 90, 80, 70, 90, 110, 130, 130, 130], index=dates, dtype=float)

    rsi = compute_rsi_series(prices, period=3)

    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(3).mean()
    avg_loss = loss.rolling(3).mean()
    expected = 100 - (100 / (1 + avg_gain / avg_loss))
    pd.testing.assert_series_equal(rsi, expected)


def test_compute_macd_series_matches_manual_ema_formula():
    dates = pd.date_range("2026-01-01", periods=6, freq="D")
    prices = pd.Series([100, 100, 102, 102, 105, 108], index=dates, dtype=float)

    macd_line, signal_line = compute_macd_series(prices, fast=2, slow=3, signal=2)

    fast_ema = prices.ewm(span=2, adjust=False).mean()
    slow_ema = prices.ewm(span=3, adjust=False).mean()
    expected_macd = fast_ema - slow_ema
    expected_signal = expected_macd.ewm(span=2, adjust=False).mean()
    pd.testing.assert_series_equal(macd_line, expected_macd)
    pd.testing.assert_series_equal(signal_line, expected_signal)


def test_compute_bollinger_bands_matches_manual_formula():
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    prices = pd.Series([100, 100, 70, 100, 100], index=dates, dtype=float)

    middle_band, lower_band = compute_bollinger_bands(prices, window=3, num_std=1.0)

    expected_middle = prices.rolling(3).mean()
    expected_lower = expected_middle - 1.0 * prices.rolling(3).std()
    pd.testing.assert_series_equal(middle_band, expected_middle)
    pd.testing.assert_series_equal(lower_band, expected_lower)
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backtest.py -k compute_ -v`
Expected: FAIL（`ImportError: cannot import name 'compute_ma_crossover_series'`）

- [ ] **Step 3: 関数を切り出し、4つのrun_*_backtestから利用する**

`portfolio_management/backtest.py`の`run_ma_crossover_backtest`（99-114行目）の直前に4つの関数を追加:

```python
def compute_ma_crossover_series(
    prices: pd.Series, short_window: int, long_window: int
) -> tuple[pd.Series, pd.Series]:
    """移動平均クロスオーバー戦略の短期/長期移動平均系列を計算する。"""
    short_ma = prices.rolling(short_window).mean()
    long_ma = prices.rolling(long_window).mean()
    return short_ma, long_ma


def compute_rsi_series(prices: pd.Series, period: int) -> pd.Series:
    """RSI逆張り戦略のRSI系列を計算する。"""
    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_macd_series(
    prices: pd.Series, fast: int, slow: int, signal: int
) -> tuple[pd.Series, pd.Series]:
    """MACDクロスオーバー戦略のMACD線/シグナル線系列を計算する。"""
    fast_ema = prices.ewm(span=fast, adjust=False).mean()
    slow_ema = prices.ewm(span=slow, adjust=False).mean()
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def compute_bollinger_bands(
    prices: pd.Series, window: int, num_std: float
) -> tuple[pd.Series, pd.Series]:
    """ボリンジャーバンド逆張り戦略の中心線/下バンド系列を計算する。"""
    middle_band = prices.rolling(window).mean()
    band_std = prices.rolling(window).std()
    lower_band = middle_band - num_std * band_std
    return middle_band, lower_band
```

`run_ma_crossover_backtest`本体（106-107行目）を置き換え:

```python
    short_ma, long_ma = compute_ma_crossover_series(prices, short_window, long_window)
```

`run_rsi_reversal_backtest`本体（125-132行目）を置き換え:

```python
    rsi = compute_rsi_series(prices, period)
```

`run_macd_crossover_backtest`本体（161-164行目）を置き換え:

```python
    macd_line, signal_line = compute_macd_series(prices, fast, slow, signal)
```

`run_bollinger_reversal_backtest`本体（181-183行目）を置き換え:

```python
    middle_band, lower_band = compute_bollinger_bands(prices, window, num_std)
```

（各関数のそれ以外の行、コメント、`_finalize_backtest`呼び出しは変更しない）

- [ ] **Step 4: 全テストが通ることを確認**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backtest.py -v`
Expected: PASS（既存の全run_*_backtestテストが厳密な期待値のまま通り、リファクタが計算結果を変えていないことを保証する）

- [ ] **Step 5: コミット**

```bash
git add portfolio_management/backtest.py tests/test_backtest.py
git commit -m "$(cat <<'EOF'
refactor: 4戦略の指標系列計算をcompute_*関数として切り出す

FILTER_CURRENT_SIGNAL（直近シグナル判定）が同じ指標計算ロジックを
再利用できるよう、run_*_backtest内部に埋め込まれていたMA/RSI/MACD/
ボリンジャーバンドの計算を独立関数に分離した。数値結果は変更なし
（既存テストの厳密な期待値がそのまま通ることで確認済み）。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: ユニバースバックテストのキャッシュキー生成を共有関数化する

**Files:**
- Modify: `portfolio_management/backtest.py`（Task 1の続き、末尾に追加）
- Modify: `app_tabs/ranking_tab.py:3, 16, 64-69`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: なし
- Produces: `build_universe_backtest_cache_key(strategy_names: list[str], period: str, transaction_cost_pct: float, tickers: list[str], aggregation: str | None = None) -> str`

- [ ] **Step 1: 失敗するテストを追加する**

`tests/test_backtest.py`のimportに`build_universe_backtest_cache_key`を追加し、末尾に追記:

```python
import hashlib


def test_build_universe_backtest_cache_key_matches_legacy_single_strategy_format():
    # ranking_tab.pyの旧実装と同じハッシュ値になることを確認し、
    # 既存キャッシュを無効化しないことを保証する。
    key = build_universe_backtest_cache_key(
        ["移動平均クロスオーバー"], "3y", 0.1, ["AAA.T", "BBB.T"]
    )
    legacy_source = "移動平均クロスオーバー-3y-0.1-AAA.T-BBB.T"
    expected = "universe-backtest-" + hashlib.sha256(
        legacy_source.encode("utf-8")
    ).hexdigest()[:12]
    assert key == expected


def test_build_universe_backtest_cache_key_is_order_independent_for_tickers():
    key_a = build_universe_backtest_cache_key(["RSI逆張り"], "1y", 0.0, ["BBB.T", "AAA.T"])
    key_b = build_universe_backtest_cache_key(["RSI逆張り"], "1y", 0.0, ["AAA.T", "BBB.T"])
    assert key_a == key_b


def test_build_universe_backtest_cache_key_differs_by_aggregation():
    key_mean = build_universe_backtest_cache_key(
        ["A", "B"], "1y", 0.0, ["AAA.T"], aggregation="MEAN"
    )
    key_best = build_universe_backtest_cache_key(
        ["A", "B"], "1y", 0.0, ["AAA.T"], aggregation="BEST"
    )
    assert key_mean != key_best
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backtest.py -k cache_key -v`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 関数を実装する**

`portfolio_management/backtest.py`先頭のimportに`import hashlib`を追加（`import logging`の前）。

ファイル末尾に追記:

```python
def build_universe_backtest_cache_key(
    strategy_names: list[str],
    period: str,
    transaction_cost_pct: float,
    tickers: list[str],
    aggregation: str | None = None,
) -> str:
    """ユニバース一括バックテスト結果のキャッシュキーを生成する。strategy_names・
    period・transaction_cost_pct・対象ticker集合（順不同を吸収するためソートして
    結合）からハッシュ化する。単一戦略の場合はstrategy_namesを要素数1のリストで
    渡す。ranking_tab.py（単一戦略）とpipeline_functions.py（単一/4戦略）の
    両方から共有される。"""
    strategy_part = "+".join(strategy_names)
    key_source = f"{strategy_part}-{period}-{transaction_cost_pct}-{'-'.join(sorted(tickers))}"
    if aggregation is not None:
        key_source += f"-{aggregation}"
    return "universe-backtest-" + hashlib.sha256(key_source.encode("utf-8")).hexdigest()[:12]
```

- [ ] **Step 4: テストが通ることを確認**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backtest.py -v`
Expected: PASS

- [ ] **Step 5: ranking_tab.pyを新関数を使うよう修正する**

`app_tabs/ranking_tab.py:3`の`import hashlib`を削除。

`app_tabs/ranking_tab.py:16`を置き換え:

```python
from portfolio_management.backtest import (
    STRATEGIES,
    build_universe_backtest_cache_key,
    run_universe_backtest_ranking,
)
```

`app_tabs/ranking_tab.py:64-67`を置き換え:

```python
        cache_key = build_universe_backtest_cache_key(
            [ranking_strategy], ranking_period, transaction_cost_pct, target_tickers
        )
```

- [ ] **Step 6: 全テストスイートを実行し回帰が無いことを確認**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS（`ranking_tab.py`には直接のpytestテストが無いため、他モジュールに影響が無いことを全体スイートで確認する）

- [ ] **Step 7: コミット**

```bash
git add portfolio_management/backtest.py app_tabs/ranking_tab.py tests/test_backtest.py
git commit -m "$(cat <<'EOF'
refactor: ユニバースバックテストのキャッシュキー生成を共有関数化

ranking_tab.pyにベタ書きされていたキャッシュキーのハッシュ生成ロジックを
build_universe_backtest_cache_key()として切り出し、既存キャッシュを
無効化しない（同一入力で同一ハッシュ値になる）ことをテストで保証した。
今後追加するMULTI_STRATEGY_RANKからも共有する。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: pipeline_functions.py — BACKTEST_RANK

**Files:**
- Create: `strategy_builder/pipeline_functions.py`
- Test: `tests/test_strategy_builder_pipeline_functions.py`

**Interfaces:**
- Consumes: `STRATEGIES`, `run_universe_backtest_ranking`, `build_universe_backtest_cache_key`（Task 1-2, `portfolio_management.backtest`）、`fetch_universe_price_histories`（`data_api.stock_price_api`）、`read_cache`/`write_cache`（`common.cache`）
- Produces: `_run_backtest_rank(candidates_df: pd.DataFrame, params: dict, cache_dir) -> pd.DataFrame`。出力列: `ticker, total_return_pct, benchmark_return_pct, win_rate_pct, max_drawdown_pct, risk_adjusted_return, best_params, trade_days, stability_cv, is_stable, _source_strategy`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_strategy_builder_pipeline_functions.py`を新規作成:

```python
import pandas as pd

import strategy_builder.pipeline_functions as pipeline_functions


def test_run_backtest_rank_adds_source_strategy_and_sorts_by_risk_adjusted_return(
    monkeypatch, tmp_path
):
    dates = pd.date_range("2026-01-01", periods=90, freq="D")

    def fake_fetch(tickers, period):
        return {
            "AAA.T": pd.Series(range(100, 190), index=dates, dtype=float),
            "BBB.T": pd.Series([100.0] * 90, index=dates, dtype=float),
        }

    monkeypatch.setattr(pipeline_functions, "fetch_universe_price_histories", fake_fetch)

    candidates_df = pd.DataFrame({"ticker": ["AAA.T", "BBB.T"]})
    result_df = pipeline_functions._run_backtest_rank(
        candidates_df, {"strategy": "移動平均クロスオーバー", "period": "1y"}, tmp_path
    )

    assert set(result_df["_source_strategy"]) == {"移動平均クロスオーバー"}
    assert result_df["risk_adjusted_return"].is_monotonic_decreasing


def test_run_backtest_rank_applies_top_n():
    pass  # 下のStep3実装後にStep1bで追加する
```

（2つ目は仮置き。実装確認後、以下の`test_run_backtest_rank_applies_top_n`に差し替える）

- [ ] **Step 2: テストが失敗することを確認**

Run: `.venv/Scripts/python.exe -m pytest tests/test_strategy_builder_pipeline_functions.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'strategy_builder.pipeline_functions'`）

- [ ] **Step 3: `_run_backtest_rank`を実装する**

`strategy_builder/pipeline_functions.py`を新規作成:

```python
"""AI戦略ビルダーのAI対話が生成するstepsから呼び出される、再利用可能な
スクリーニング/ランキング関数のレジストリ。各関数は
(candidates_df: pd.DataFrame, params: dict, cache_dir) -> pd.DataFrame
という統一シグネチャを持つ。"""

import json

import pandas as pd

from common.cache import read_cache, write_cache
from data_api.stock_price_api import fetch_universe_fundamentals, fetch_universe_price_histories, load_all_company_profiles
from portfolio_management.backtest import (
    STRATEGIES,
    build_universe_backtest_cache_key,
    compute_bollinger_bands,
    compute_ma_crossover_series,
    compute_macd_series,
    compute_rsi_series,
    run_universe_backtest_ranking,
)
from strategy_builder.conditions import apply_strategy_conditions


def _run_backtest_rank(candidates_df: pd.DataFrame, params: dict, cache_dir) -> pd.DataFrame:
    """対象銘柄群を1戦略でバックテストし、リスク調整済みリターン降順にランキングして
    上位top_n件に絞る。"""
    strategy_name = params.get("strategy")
    if strategy_name not in STRATEGIES:
        raise ValueError(f"未知の戦略です: {strategy_name}")
    period = params.get("period", "1y")
    transaction_cost_pct = params.get("transaction_cost_pct", 0.0)
    top_n = params.get("top_n")
    tickers = candidates_df["ticker"].tolist()

    cache_key = build_universe_backtest_cache_key(
        [strategy_name], period, transaction_cost_pct, tickers
    )
    cached_payload = read_cache(cache_dir, cache_key)
    if cached_payload is not None:
        rows = json.loads(cached_payload)
    else:
        prices_by_ticker = fetch_universe_price_histories(tickers, period)
        definition = STRATEGIES[strategy_name]
        rows = run_universe_backtest_ranking(
            prices_by_ticker,
            definition["func"],
            definition["param_grid"],
            definition.get("fixed_params"),
            transaction_cost_pct=transaction_cost_pct,
            min_days=definition["min_days"],
        )
        write_cache(cache_dir, cache_key, json.dumps(rows, ensure_ascii=False))

    result_df = pd.DataFrame(rows)
    if result_df.empty:
        return result_df.assign(_source_strategy=pd.Series(dtype=str))
    result_df["_source_strategy"] = strategy_name
    if top_n is not None:
        result_df = result_df.head(top_n)
    return result_df
```

- [ ] **Step 4: テストコードを最終形にする**

`test_run_backtest_rank_applies_top_n`を実装し、`tests/test_strategy_builder_pipeline_functions.py`の仮置き関数を置き換える:

```python
def test_run_backtest_rank_applies_top_n(monkeypatch, tmp_path):
    dates = pd.date_range("2026-01-01", periods=20, freq="D")

    def fake_fetch(tickers, period):
        return {t: pd.Series(range(100, 120), index=dates, dtype=float) for t in tickers}

    monkeypatch.setattr(pipeline_functions, "fetch_universe_price_histories", fake_fetch)
    monkeypatch.setattr(
        pipeline_functions,
        "STRATEGIES",
        {
            "テスト戦略": {
                "func": lambda prices, transaction_cost_pct=0.0, **p: {
                    "total_return_pct": 1.0, "benchmark_return_pct": 0.0,
                    "win_rate_pct": 100.0, "max_drawdown_pct": -1.0, "trade_days": 1,
                },
                "param_grid": {"x": [1]},
                "min_days": 1,
            }
        },
    )

    candidates_df = pd.DataFrame({"ticker": ["AAA.T", "BBB.T", "CCC.T"]})
    result_df = pipeline_functions._run_backtest_rank(
        candidates_df, {"strategy": "テスト戦略", "top_n": 2}, tmp_path
    )

    assert len(result_df) == 2


def test_run_backtest_rank_raises_for_unknown_strategy(tmp_path):
    candidates_df = pd.DataFrame({"ticker": ["AAA.T"]})
    try:
        pipeline_functions._run_backtest_rank(candidates_df, {"strategy": "存在しない戦略"}, tmp_path)
        assert False, "ValueErrorが送出されるべき"
    except ValueError:
        pass


def test_run_backtest_rank_reuses_cache_on_second_call(monkeypatch, tmp_path):
    dates = pd.date_range("2026-01-01", periods=20, freq="D")
    call_count = {"n": 0}

    def fake_fetch(tickers, period):
        call_count["n"] += 1
        return {t: pd.Series(range(100, 120), index=dates, dtype=float) for t in tickers}

    monkeypatch.setattr(pipeline_functions, "fetch_universe_price_histories", fake_fetch)
    monkeypatch.setattr(
        pipeline_functions,
        "STRATEGIES",
        {
            "テスト戦略": {
                "func": lambda prices, transaction_cost_pct=0.0, **p: {
                    "total_return_pct": 1.0, "benchmark_return_pct": 0.0,
                    "win_rate_pct": 100.0, "max_drawdown_pct": -1.0, "trade_days": 1,
                },
                "param_grid": {"x": [1]},
                "min_days": 1,
            }
        },
    )

    candidates_df = pd.DataFrame({"ticker": ["AAA.T"]})
    params = {"strategy": "テスト戦略"}
    pipeline_functions._run_backtest_rank(candidates_df, params, tmp_path)
    pipeline_functions._run_backtest_rank(candidates_df, params, tmp_path)

    assert call_count["n"] == 1
```

- [ ] **Step 5: テストが通ることを確認**

Run: `.venv/Scripts/python.exe -m pytest tests/test_strategy_builder_pipeline_functions.py -v`
Expected: PASS

- [ ] **Step 6: コミット**

```bash
git add strategy_builder/pipeline_functions.py tests/test_strategy_builder_pipeline_functions.py
git commit -m "$(cat <<'EOF'
feat: パイプライン関数BACKTEST_RANKを追加

1戦略を指定してユニバース全体をバックテストランキングし、_source_strategy
列を付与して上位top_n件に絞るBACKTEST_RANKを実装。ranking_tab.pyと同じ
キャッシュキー共有関数を使い、結果をファイルキャッシュする。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: pipeline_functions.py — MULTI_STRATEGY_RANK

**Files:**
- Modify: `strategy_builder/pipeline_functions.py`
- Test: `tests/test_strategy_builder_pipeline_functions.py`

**Interfaces:**
- Produces: `_merge_strategy_results(rows_by_strategy: dict[str, list[dict]]) -> list[dict]`、`_run_multi_strategy_rank(candidates_df, params, cache_dir) -> pd.DataFrame`。出力列はBACKTEST_RANKと同じ + `avg_risk_adjusted_return`, `profitable_strategy_count`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_strategy_builder_pipeline_functions.py`に追記:

```python
def test_merge_strategy_results_selects_best_strategy_and_computes_aggregates():
    rows_by_strategy = {
        "戦略A": [
            {"ticker": "AAA.T", "total_return_pct": 10.0, "benchmark_return_pct": 4.0,
             "win_rate_pct": 100.0, "max_drawdown_pct": -5.0, "risk_adjusted_return": 2.0,
             "best_params": {"x": 1}},
        ],
        "戦略B": [
            {"ticker": "AAA.T", "total_return_pct": -3.0, "benchmark_return_pct": 4.0,
             "win_rate_pct": 0.0, "max_drawdown_pct": -6.0, "risk_adjusted_return": -0.5,
             "best_params": {"y": 2}},
        ],
    }

    merged = pipeline_functions._merge_strategy_results(rows_by_strategy)

    assert merged == [
        {
            "ticker": "AAA.T",
            "total_return_pct": 10.0,
            "benchmark_return_pct": 4.0,
            "win_rate_pct": 100.0,
            "max_drawdown_pct": -5.0,
            "risk_adjusted_return": 2.0,
            "best_params": {"x": 1},
            "_source_strategy": "戦略A",
            "avg_risk_adjusted_return": 0.75,
            "profitable_strategy_count": 1,
        }
    ]


def test_merge_strategy_results_handles_ticker_missing_from_some_strategies():
    rows_by_strategy = {
        "戦略A": [{"ticker": "AAA.T", "total_return_pct": 5.0, "benchmark_return_pct": 0.0,
                   "win_rate_pct": 100.0, "max_drawdown_pct": -1.0, "risk_adjusted_return": 5.0,
                   "best_params": {}}],
        "戦略B": [],
    }

    merged = pipeline_functions._merge_strategy_results(rows_by_strategy)

    assert len(merged) == 1
    assert merged[0]["avg_risk_adjusted_return"] == 5.0
    assert merged[0]["profitable_strategy_count"] == 1


def test_run_multi_strategy_rank_picks_best_strategy_per_ticker(monkeypatch, tmp_path):
    dates = pd.date_range("2026-01-01", periods=5, freq="D")

    def fake_fetch(tickers, period):
        return {t: pd.Series([100.0, 101.0, 102.0, 103.0, 104.0], index=dates) for t in tickers}

    monkeypatch.setattr(pipeline_functions, "fetch_universe_price_histories", fake_fetch)

    def strategy_a(prices, transaction_cost_pct=0.0, **params):
        return {"total_return_pct": 10.0, "benchmark_return_pct": 4.0, "win_rate_pct": 100.0,
                "max_drawdown_pct": -5.0, "trade_days": 1}

    def strategy_b(prices, transaction_cost_pct=0.0, **params):
        return {"total_return_pct": 20.0, "benchmark_return_pct": 4.0, "win_rate_pct": 100.0,
                "max_drawdown_pct": -5.0, "trade_days": 1}

    monkeypatch.setattr(
        pipeline_functions,
        "STRATEGIES",
        {
            "戦略A": {"func": strategy_a, "param_grid": {"x": [1]}, "min_days": 1},
            "戦略B": {"func": strategy_b, "param_grid": {"x": [1]}, "min_days": 1},
        },
    )

    candidates_df = pd.DataFrame({"ticker": ["AAA.T"]})
    result_df = pipeline_functions._run_multi_strategy_rank(
        candidates_df, {"period": "1y", "top_n": 10}, tmp_path
    )

    row = result_df.iloc[0]
    assert row["_source_strategy"] == "戦略B"
    assert row["risk_adjusted_return"] == 4.0
    assert row["avg_risk_adjusted_return"] == 3.0
    assert row["profitable_strategy_count"] == 2
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `.venv/Scripts/python.exe -m pytest tests/test_strategy_builder_pipeline_functions.py -k "merge_strategy or multi_strategy" -v`
Expected: FAIL（`AttributeError: module has no attribute '_merge_strategy_results'`）

- [ ] **Step 3: 実装する**

`strategy_builder/pipeline_functions.py`の`_run_backtest_rank`の直後に追記:

```python
def _merge_strategy_results(rows_by_strategy: dict[str, list[dict]]) -> list[dict]:
    """戦略名→run_universe_backtest_rankingの結果行リスト、というdictから、
    銘柄ごとにrisk_adjusted_return最大の戦略を採用し、avg_risk_adjusted_return・
    profitable_strategy_countを付与した行リストにまとめる。ある銘柄が一部の戦略で
    グリッドサーチに失敗しスキップされていた場合、その銘柄は残りの戦略の結果のみで
    集計する。"""
    rows_by_ticker: dict[str, list[dict]] = {}
    for strategy_name, rows in rows_by_strategy.items():
        for row in rows:
            rows_by_ticker.setdefault(row["ticker"], []).append({**row, "_strategy": strategy_name})

    merged = []
    for ticker, entries in rows_by_ticker.items():
        best = max(entries, key=lambda entry: entry["risk_adjusted_return"])
        avg_risk_adjusted_return = round(
            sum(entry["risk_adjusted_return"] for entry in entries) / len(entries), 2
        )
        profitable_strategy_count = sum(1 for entry in entries if entry["total_return_pct"] > 0)
        merged.append(
            {
                "ticker": ticker,
                "total_return_pct": best["total_return_pct"],
                "benchmark_return_pct": best["benchmark_return_pct"],
                "win_rate_pct": best["win_rate_pct"],
                "max_drawdown_pct": best["max_drawdown_pct"],
                "risk_adjusted_return": best["risk_adjusted_return"],
                "best_params": best["best_params"],
                "_source_strategy": best["_strategy"],
                "avg_risk_adjusted_return": avg_risk_adjusted_return,
                "profitable_strategy_count": profitable_strategy_count,
            }
        )
    return merged


def _run_multi_strategy_rank(candidates_df: pd.DataFrame, params: dict, cache_dir) -> pd.DataFrame:
    """1戦略に決め打たず、STRATEGIESの全戦略で対象銘柄群をバックテストし、銘柄ごとに
    最良戦略を採用して総合的にランキングする。"""
    period = params.get("period", "1y")
    transaction_cost_pct = params.get("transaction_cost_pct", 0.0)
    top_n = params.get("top_n")
    aggregation = params.get("aggregation", "MEAN")
    tickers = candidates_df["ticker"].tolist()
    strategy_names = list(STRATEGIES.keys())

    cache_key = build_universe_backtest_cache_key(
        strategy_names, period, transaction_cost_pct, tickers, aggregation=aggregation
    )
    cached_payload = read_cache(cache_dir, cache_key)
    if cached_payload is not None:
        merged_rows = json.loads(cached_payload)
    else:
        prices_by_ticker = fetch_universe_price_histories(tickers, period)
        rows_by_strategy = {}
        for strategy_name, definition in STRATEGIES.items():
            rows_by_strategy[strategy_name] = run_universe_backtest_ranking(
                prices_by_ticker,
                definition["func"],
                definition["param_grid"],
                definition.get("fixed_params"),
                transaction_cost_pct=transaction_cost_pct,
                min_days=definition["min_days"],
            )
        merged_rows = _merge_strategy_results(rows_by_strategy)
        write_cache(cache_dir, cache_key, json.dumps(merged_rows, ensure_ascii=False))

    result_df = pd.DataFrame(merged_rows)
    if result_df.empty:
        return result_df

    sort_column = {
        "MEAN": "avg_risk_adjusted_return",
        "CONSENSUS": "profitable_strategy_count",
        "BEST": "risk_adjusted_return",
    }.get(aggregation, "avg_risk_adjusted_return")
    result_df = result_df.sort_values(sort_column, ascending=False)
    if top_n is not None:
        result_df = result_df.head(top_n)
    return result_df
```

- [ ] **Step 4: テストが通ることを確認**

Run: `.venv/Scripts/python.exe -m pytest tests/test_strategy_builder_pipeline_functions.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add strategy_builder/pipeline_functions.py tests/test_strategy_builder_pipeline_functions.py
git commit -m "$(cat <<'EOF'
feat: パイプライン関数MULTI_STRATEGY_RANKを追加

4戦略すべてでバックテストし、銘柄ごとに最良戦略を採用して総合ランキング
するMULTI_STRATEGY_RANKを実装。出力列をBACKTEST_RANKと互換にすることで
後続のFILTER_CURRENT_SIGNAL等をそのまま繋げられるようにした。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: pipeline_functions.py — 直近クロス判定の汎用ヘルパー

**Files:**
- Modify: `strategy_builder/pipeline_functions.py`
- Test: `tests/test_strategy_builder_pipeline_functions.py`

**Interfaces:**
- Produces: `_detect_recent_cross(fast, slow, direction="up", within_days=5) -> bool`、`_detect_recent_threshold_cross(series, threshold, direction="up", within_days=5) -> bool`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_strategy_builder_pipeline_functions.py`に追記:

```python
def test_detect_recent_cross_true_when_cross_within_window():
    dates = pd.date_range("2026-01-01", periods=6, freq="D")
    fast = pd.Series([1, 1, 1, 5, 5, 5], index=dates, dtype=float)
    slow = pd.Series([2, 2, 2, 2, 2, 2], index=dates, dtype=float)

    assert pipeline_functions._detect_recent_cross(fast, slow, "up", within_days=5) is True


def test_detect_recent_cross_false_when_cross_outside_window():
    dates = pd.date_range("2026-01-01", periods=8, freq="D")
    fast = pd.Series([1, 1, 5, 5, 5, 5, 5, 5], index=dates, dtype=float)
    slow = pd.Series([2, 2, 2, 2, 2, 2, 2, 2], index=dates, dtype=float)
    # クロス（下→上）は3日目（index=2）で発生。直近2日以内には無い。

    assert pipeline_functions._detect_recent_cross(fast, slow, "up", within_days=2) is False


def test_detect_recent_cross_false_when_insufficient_data():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    fast = pd.Series([1, 2, 3], index=dates, dtype=float)
    slow = pd.Series([2, 2, 2], index=dates, dtype=float)

    assert pipeline_functions._detect_recent_cross(fast, slow, "up", within_days=5) is False


def test_detect_recent_cross_detects_downward_direction():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    fast = pd.Series([5, 5, 1, 1], index=dates, dtype=float)
    slow = pd.Series([2, 2, 2, 2], index=dates, dtype=float)

    assert pipeline_functions._detect_recent_cross(fast, slow, "down", within_days=3) is True


def test_detect_recent_threshold_cross_true_when_crossed_up_recently():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    series = pd.Series([20.0, 25.0, 35.0, 35.0], index=dates)

    assert pipeline_functions._detect_recent_threshold_cross(
        series, threshold=30.0, direction="up", within_days=2
    ) is True


def test_detect_recent_threshold_cross_false_when_never_crossed():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    series = pd.Series([20.0, 21.0, 22.0, 23.0], index=dates)

    assert pipeline_functions._detect_recent_threshold_cross(
        series, threshold=30.0, direction="up", within_days=3
    ) is False
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `.venv/Scripts/python.exe -m pytest tests/test_strategy_builder_pipeline_functions.py -k detect_recent -v`
Expected: FAIL

- [ ] **Step 3: 実装する**

`strategy_builder/pipeline_functions.py`の`_run_multi_strategy_rank`の直後に追記:

```python
def _detect_recent_cross(
    fast: pd.Series, slow: pd.Series, direction: str = "up", within_days: int = 5,
) -> bool:
    """2系列が直近within_days営業日以内に交差したかを判定する。
    データ不足（NaN混在含む）時はクロス無し（False）として扱う。"""
    if len(fast) < within_days + 1:
        return False
    recent_fast, recent_slow = fast.iloc[-(within_days + 1):], slow.iloc[-(within_days + 1):]
    if recent_fast.isna().any() or recent_slow.isna().any():
        return False
    is_above = fast > slow
    crossed_up = is_above & ~is_above.shift(1).fillna(False)
    crossed_down = ~is_above & is_above.shift(1).fillna(False)
    recent = crossed_up if direction == "up" else crossed_down
    return bool(recent.iloc[-within_days:].any())


def _detect_recent_threshold_cross(
    series: pd.Series, threshold: float, direction: str = "up", within_days: int = 5,
) -> bool:
    """1系列が直近within_days営業日以内に閾値を上抜け/下抜けしたかを判定する。"""
    is_above = series >= threshold if direction == "up" else series <= threshold
    crossed = is_above & ~is_above.shift(1).fillna(False)
    return bool(crossed.iloc[-within_days:].any())
```

- [ ] **Step 4: テストが通ることを確認**

Run: `.venv/Scripts/python.exe -m pytest tests/test_strategy_builder_pipeline_functions.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add strategy_builder/pipeline_functions.py tests/test_strategy_builder_pipeline_functions.py
git commit -m "$(cat <<'EOF'
feat: 直近クロス判定の汎用ヘルパーを追加

2系列交差（MA/MACD/ボリンジャー）と1系列閾値交差（RSI）を共通の
ロジックで判定する_detect_recent_cross/_detect_recent_threshold_crossを
実装。FILTER_CURRENT_SIGNALの基盤となる。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: pipeline_functions.py — FILTER_CURRENT_SIGNAL

**Files:**
- Modify: `strategy_builder/pipeline_functions.py`
- Test: `tests/test_strategy_builder_pipeline_functions.py`

**Interfaces:**
- Consumes: `compute_ma_crossover_series`/`compute_rsi_series`/`compute_macd_series`/`compute_bollinger_bands`（Task 1）、`_detect_recent_cross`/`_detect_recent_threshold_cross`（Task 5）
- Produces: `_resolve_strategy_params(strategy, best_params) -> dict`、`_detect_signal_for_row(close, strategy, best_params, signal) -> bool`、`_run_filter_current_signal(candidates_df, params, cache_dir) -> pd.DataFrame`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_strategy_builder_pipeline_functions.py`に追記:

```python
def test_resolve_strategy_params_uses_best_params_when_keys_match():
    params = pipeline_functions._resolve_strategy_params(
        "移動平均クロスオーバー", {"short_window": 10, "long_window": 40}
    )
    assert params == {"short_window": 10, "long_window": 40}


def test_resolve_strategy_params_falls_back_to_defaults_when_keys_mismatch():
    params = pipeline_functions._resolve_strategy_params("移動平均クロスオーバー", {"period": 14})
    assert params == {"short_window": 25, "long_window": 75}


def test_resolve_strategy_params_falls_back_to_defaults_when_none():
    params = pipeline_functions._resolve_strategy_params("RSI逆張り", None)
    assert params == {"period": 14, "oversold": 30, "overbought": 70}


def test_detect_signal_for_row_dispatches_ma_crossover():
    dates = pd.date_range("2026-01-01", periods=10, freq="D")
    close = pd.Series([10, 10, 10, 10, 10, 20, 20, 20, 20, 20], index=dates, dtype=float)

    result = pipeline_functions._detect_signal_for_row(
        close, "移動平均クロスオーバー", {"short_window": 1, "long_window": 3}, "ENTRY"
    )
    assert result is True


def test_detect_signal_for_row_dispatches_rsi_entry_uses_oversold(monkeypatch):
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    close = pd.Series(range(4), index=dates, dtype=float)
    captured = {}

    def fake_compute_rsi(prices, period):
        captured["period"] = period
        return pd.Series([20.0, 20.0, 35.0, 35.0], index=dates)

    monkeypatch.setattr(pipeline_functions, "compute_rsi_series", fake_compute_rsi)

    entry_result = pipeline_functions._detect_signal_for_row(
        close, "RSI逆張り", {"period": 7, "oversold": 30, "overbought": 70}, "ENTRY"
    )
    exit_result = pipeline_functions._detect_signal_for_row(
        close, "RSI逆張り", {"period": 7, "oversold": 30, "overbought": 70}, "EXIT"
    )

    assert captured["period"] == 7
    assert entry_result is True
    assert exit_result is False


def test_detect_signal_for_row_dispatches_macd_crossover(monkeypatch):
    dates = pd.date_range("2026-01-01", periods=6, freq="D")
    close = pd.Series(range(6), index=dates, dtype=float)

    def fake_compute_macd(prices, fast, slow, signal):
        macd_line = pd.Series([-1.0, -1.0, -1.0, 1.0, 1.0, 1.0], index=dates)
        signal_line = pd.Series([0.0] * 6, index=dates)
        return macd_line, signal_line

    monkeypatch.setattr(pipeline_functions, "compute_macd_series", fake_compute_macd)

    result = pipeline_functions._detect_signal_for_row(
        close, "MACDクロスオーバー", {"fast": 12, "slow": 26, "signal": 9}, "ENTRY"
    )
    assert result is True


def test_detect_signal_for_row_dispatches_bollinger_entry_uses_lower_band(monkeypatch):
    dates = pd.date_range("2026-01-01", periods=6, freq="D")
    close = pd.Series([100.0, 100.0, 100.0, 70.0, 70.0, 70.0], index=dates)

    def fake_compute_bands(prices, window, num_std):
        return pd.Series([100.0] * 6, index=dates), pd.Series([90.0] * 6, index=dates)

    monkeypatch.setattr(pipeline_functions, "compute_bollinger_bands", fake_compute_bands)

    entry_result = pipeline_functions._detect_signal_for_row(
        close, "ボリンジャーバンド逆張り", {"window": 20, "num_std": 2.0}, "ENTRY"
    )
    assert entry_result is True


def test_detect_signal_for_row_dispatches_bollinger_exit_uses_middle_band(monkeypatch):
    dates = pd.date_range("2026-01-01", periods=6, freq="D")
    close = pd.Series([70.0, 70.0, 70.0, 100.0, 100.0, 100.0], index=dates)

    def fake_compute_bands(prices, window, num_std):
        return pd.Series([90.0] * 6, index=dates), pd.Series([60.0] * 6, index=dates)

    monkeypatch.setattr(pipeline_functions, "compute_bollinger_bands", fake_compute_bands)

    exit_result = pipeline_functions._detect_signal_for_row(
        close, "ボリンジャーバンド逆張り", {"window": 20, "num_std": 2.0}, "EXIT"
    )
    assert exit_result is True


def test_detect_signal_for_row_returns_false_for_unknown_strategy():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    close = pd.Series([1.0, 2.0, 3.0], index=dates)

    assert pipeline_functions._detect_signal_for_row(close, "未知戦略", None, "ENTRY") is False


def test_run_filter_current_signal_keeps_only_rows_with_entry_signal(monkeypatch, tmp_path):
    dates = pd.date_range("2026-01-01", periods=6, freq="D")

    def fake_fetch(tickers, period):
        return {
            "AAA.T": pd.Series([10, 10, 10, 10, 10, 10], index=dates, dtype=float),
            "BBB.T": pd.Series([10, 10, 10, 20, 20, 20], index=dates, dtype=float),
        }

    monkeypatch.setattr(pipeline_functions, "fetch_universe_price_histories", fake_fetch)

    candidates_df = pd.DataFrame(
        [
            {"ticker": "AAA.T", "_source_strategy": "移動平均クロスオーバー",
             "best_params": {"short_window": 1, "long_window": 3}},
            {"ticker": "BBB.T", "_source_strategy": "移動平均クロスオーバー",
             "best_params": {"short_window": 1, "long_window": 3}},
        ]
    )

    result_df = pipeline_functions._run_filter_current_signal(
        candidates_df, {"signal": "ENTRY"}, tmp_path
    )

    assert result_df["ticker"].tolist() == ["BBB.T"]


def test_run_filter_current_signal_uses_explicit_strategy_override(monkeypatch, tmp_path):
    dates = pd.date_range("2026-01-01", periods=6, freq="D")

    def fake_fetch(tickers, period):
        return {"AAA.T": pd.Series([10, 10, 10, 20, 20, 20], index=dates, dtype=float)}

    monkeypatch.setattr(pipeline_functions, "fetch_universe_price_histories", fake_fetch)

    candidates_df = pd.DataFrame(
        [{"ticker": "AAA.T", "best_params": {"short_window": 1, "long_window": 3}}]
    )

    result_df = pipeline_functions._run_filter_current_signal(
        candidates_df, {"signal": "ENTRY", "strategy": "移動平均クロスオーバー"}, tmp_path
    )

    assert result_df["ticker"].tolist() == ["AAA.T"]


def test_run_filter_current_signal_skips_row_when_strategy_unresolvable(monkeypatch, tmp_path):
    dates = pd.date_range("2026-01-01", periods=6, freq="D")

    def fake_fetch(tickers, period):
        return {"AAA.T": pd.Series([10, 10, 10, 20, 20, 20], index=dates, dtype=float)}

    monkeypatch.setattr(pipeline_functions, "fetch_universe_price_histories", fake_fetch)

    candidates_df = pd.DataFrame([{"ticker": "AAA.T"}])
    result_df = pipeline_functions._run_filter_current_signal(
        candidates_df, {"signal": "ENTRY"}, tmp_path
    )

    assert result_df.empty
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `.venv/Scripts/python.exe -m pytest tests/test_strategy_builder_pipeline_functions.py -k "resolve_strategy or detect_signal or filter_current_signal" -v`
Expected: FAIL

- [ ] **Step 3: 実装する**

`strategy_builder/pipeline_functions.py`の`_detect_recent_threshold_cross`の直後に追記:

```python
_SIGNAL_DIRECTION = {"ENTRY": "up", "EXIT": "down"}

_STRATEGY_PARAM_DEFAULTS: dict[str, dict] = {
    "移動平均クロスオーバー": {"short_window": 25, "long_window": 75},
    "RSI逆張り": {"period": 14, "oversold": 30, "overbought": 70},
    "MACDクロスオーバー": {"fast": 12, "slow": 26, "signal": 9},
    "ボリンジャーバンド逆張り": {"window": 20, "num_std": 2.0},
}


def _resolve_strategy_params(strategy: str, best_params: dict | None) -> dict:
    """best_paramsがNone、または対象strategyの既定パラメータのキーと一致しない
    （別戦略のbest_paramsが紛れ込んだ等）場合は、STRATEGIESの既定パラメータに
    フォールバックする。"""
    defaults = _STRATEGY_PARAM_DEFAULTS[strategy]
    if not best_params or not set(defaults).issubset(best_params.keys()):
        return defaults
    return {key: best_params[key] for key in defaults}


def _detect_signal_for_row(
    close: pd.Series, strategy: str, best_params: dict | None, signal: str
) -> bool:
    """1銘柄の価格系列について、strategyとsignal（ENTRY/EXIT）に応じた
    直近5営業日以内のシグナル発生を判定する。未知のstrategyはFalseを返す。"""
    if strategy not in _STRATEGY_PARAM_DEFAULTS:
        return False
    direction = _SIGNAL_DIRECTION[signal]
    params = _resolve_strategy_params(strategy, best_params)

    if strategy == "移動平均クロスオーバー":
        short_ma, long_ma = compute_ma_crossover_series(
            close, params["short_window"], params["long_window"]
        )
        return _detect_recent_cross(short_ma, long_ma, direction)
    if strategy == "MACDクロスオーバー":
        macd_line, signal_line = compute_macd_series(
            close, params["fast"], params["slow"], params["signal"]
        )
        return _detect_recent_cross(macd_line, signal_line, direction)
    if strategy == "ボリンジャーバンド逆張り":
        middle_band, lower_band = compute_bollinger_bands(
            close, params["window"], params["num_std"]
        )
        if signal == "ENTRY":
            return _detect_recent_cross(close, lower_band, "down")
        return _detect_recent_cross(close, middle_band, "up")
    # RSI逆張り
    rsi = compute_rsi_series(close, params["period"])
    threshold = params["oversold"] if signal == "ENTRY" else params["overbought"]
    return _detect_recent_threshold_cross(rsi, threshold, "up")


def _run_filter_current_signal(candidates_df: pd.DataFrame, params: dict, cache_dir) -> pd.DataFrame:
    """各銘柄について、その銘柄自身のstrategy（override指定が無ければ
    _source_strategy列）が直近5営業日以内にENTRY/EXITシグナルを出したかで絞り込む。"""
    signal = params.get("signal")
    if signal not in _SIGNAL_DIRECTION:
        raise ValueError(f"未知のsignalです: {signal}")
    override_strategy = params.get("strategy")

    if candidates_df.empty:
        return candidates_df

    tickers = candidates_df["ticker"].tolist()
    prices_by_ticker = fetch_universe_price_histories(tickers, period="1y")

    keep_mask = []
    for _, row in candidates_df.iterrows():
        strategy = override_strategy or row.get("_source_strategy")
        close = prices_by_ticker.get(row["ticker"])
        if strategy is None or close is None or close.empty:
            keep_mask.append(False)
            continue
        keep_mask.append(_detect_signal_for_row(close, strategy, row.get("best_params"), signal))

    return candidates_df[keep_mask]
```

- [ ] **Step 4: テストが通ることを確認**

Run: `.venv/Scripts/python.exe -m pytest tests/test_strategy_builder_pipeline_functions.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add strategy_builder/pipeline_functions.py tests/test_strategy_builder_pipeline_functions.py
git commit -m "$(cat <<'EOF'
feat: パイプライン関数FILTER_CURRENT_SIGNALを追加（4戦略対応）

移動平均クロスオーバー・MACDクロスオーバー・ボリンジャーバンド逆張り・
RSI逆張りの4戦略それぞれについて、銘柄ごとの_source_strategy/best_params
から直近ENTRY/EXITシグナルを判定するFILTER_CURRENT_SIGNALを実装。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: pipeline_functions.py — FILTER_BY_FUNDAMENTALS / SORT_BY / TOP_N とレジストリ

**Files:**
- Modify: `strategy_builder/pipeline_functions.py`
- Test: `tests/test_strategy_builder_pipeline_functions.py`

**Interfaces:**
- Produces: `_run_filter_by_fundamentals`, `_run_sort_by`, `_run_top_n`（いずれも`(candidates_df, params, cache_dir) -> pd.DataFrame`）、`PIPELINE_FUNCTIONS: dict[str, dict]`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_strategy_builder_pipeline_functions.py`に追記:

```python
def test_run_filter_by_fundamentals_merges_and_filters(monkeypatch, tmp_path):
    def fake_fetch_universe_fundamentals(tickers):
        return pd.DataFrame(
            [
                {"ticker": "AAA.T", "name": "A社", "per": 10.0, "pbr": 1.0,
                 "dividend_yield_pct": 4.0, "market_cap": 100, "roe_pct": 12.0,
                 "revenue_growth_pct": 5.0},
                {"ticker": "BBB.T", "name": "B社", "per": 25.0, "pbr": 3.0,
                 "dividend_yield_pct": 1.0, "market_cap": 200, "roe_pct": 8.0,
                 "revenue_growth_pct": 2.0},
            ]
        )

    monkeypatch.setattr(
        pipeline_functions, "fetch_universe_fundamentals", fake_fetch_universe_fundamentals
    )
    monkeypatch.setattr(pipeline_functions, "load_all_company_profiles", lambda: [])

    candidates_df = pd.DataFrame(
        [{"ticker": "AAA.T", "risk_adjusted_return": 3.0},
         {"ticker": "BBB.T", "risk_adjusted_return": 5.0}]
    )

    result_df = pipeline_functions._run_filter_by_fundamentals(
        candidates_df,
        {"conditions": [{"indicator": "DIVIDEND_YIELD", "operator": "GREATER_EQUAL", "value": 3}]},
        tmp_path,
    )

    assert result_df["ticker"].tolist() == ["AAA.T"]
    assert result_df["risk_adjusted_return"].tolist() == [3.0]


def test_run_filter_by_fundamentals_returns_empty_unchanged():
    result_df = pipeline_functions._run_filter_by_fundamentals(
        pd.DataFrame(columns=["ticker"]), {"conditions": []}, None
    )
    assert result_df.empty


def test_run_sort_by_sorts_descending_by_field():
    df = pd.DataFrame([{"ticker": "AAA.T", "risk_adjusted_return": 1.0},
                        {"ticker": "BBB.T", "risk_adjusted_return": 5.0}])
    result_df = pipeline_functions._run_sort_by(
        df, {"field": "risk_adjusted_return", "order": "DESC"}, None
    )
    assert result_df["ticker"].tolist() == ["BBB.T", "AAA.T"]


def test_run_sort_by_returns_unchanged_when_field_missing():
    df = pd.DataFrame([{"ticker": "AAA.T"}])
    result_df = pipeline_functions._run_sort_by(df, {"field": "unknown_field", "order": "DESC"}, None)
    assert result_df["ticker"].tolist() == ["AAA.T"]


def test_run_top_n_truncates_to_n_rows():
    df = pd.DataFrame([{"ticker": f"T{i}.T"} for i in range(5)])
    result_df = pipeline_functions._run_top_n(df, {"n": 2}, None)
    assert len(result_df) == 2


def test_run_top_n_sorts_by_field_before_truncating():
    df = pd.DataFrame([{"ticker": "AAA.T", "score": 1.0}, {"ticker": "BBB.T", "score": 9.0}])
    result_df = pipeline_functions._run_top_n(df, {"n": 1, "by": "score"}, None)
    assert result_df["ticker"].tolist() == ["BBB.T"]


def test_pipeline_functions_registry_contains_all_six_functions():
    assert set(pipeline_functions.PIPELINE_FUNCTIONS.keys()) == {
        "BACKTEST_RANK", "MULTI_STRATEGY_RANK", "FILTER_CURRENT_SIGNAL",
        "FILTER_BY_FUNDAMENTALS", "SORT_BY", "TOP_N",
    }


def test_pipeline_functions_registry_entries_have_description_params_schema_and_run():
    for entry in pipeline_functions.PIPELINE_FUNCTIONS.values():
        assert isinstance(entry["description"], str) and entry["description"]
        assert isinstance(entry["params_schema"], dict)
        assert callable(entry["run"])
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `.venv/Scripts/python.exe -m pytest tests/test_strategy_builder_pipeline_functions.py -k "filter_by_fundamentals or sort_by or top_n or registry" -v`
Expected: FAIL

- [ ] **Step 3: 実装する**

`strategy_builder/pipeline_functions.py`の`_run_filter_current_signal`の直後に追記:

```python
def _run_filter_by_fundamentals(candidates_df: pd.DataFrame, params: dict, cache_dir) -> pd.DataFrame:
    """PER/PBR/ROE等のファンダメンタルズ条件で絞り込む。候補銘柄にまだ
    ファンダメンタルズ/業種列が無い前提で、フィルタ前に取得・結合する。"""
    if candidates_df.empty:
        return candidates_df
    tickers = candidates_df["ticker"].tolist()
    fundamentals_df = fetch_universe_fundamentals(tickers)
    profiles = load_all_company_profiles()
    sector_jp_by_ticker = {p["ticker"]: p["sector_jp"] for p in profiles if p["sector_jp"]}
    fundamentals_df = fundamentals_df.assign(
        sector=fundamentals_df["ticker"].map(sector_jp_by_ticker)
    )
    merged_df = candidates_df.merge(fundamentals_df.drop(columns=["name"]), on="ticker", how="left")
    return apply_strategy_conditions(merged_df, {"conditions": params.get("conditions", [])})


def _run_sort_by(candidates_df: pd.DataFrame, params: dict, cache_dir) -> pd.DataFrame:
    """その時点で存在する列で並べ替える。存在しない列の場合は元の順序のまま返す。"""
    field = params.get("field")
    if field not in candidates_df.columns:
        return candidates_df
    ascending = params.get("order") != "DESC"
    return candidates_df.sort_values(field, ascending=ascending)


def _run_top_n(candidates_df: pd.DataFrame, params: dict, cache_dir) -> pd.DataFrame:
    """指定件数に絞る。byが指定されていればその列で降順ソートしてから先頭n件を、
    省略時は直前の並び順のまま先頭n件を取る。"""
    n = params.get("n")
    if n is None:
        return candidates_df
    by = params.get("by")
    if by is not None and by in candidates_df.columns:
        candidates_df = candidates_df.sort_values(by, ascending=False)
    return candidates_df.head(n)


PIPELINE_FUNCTIONS: dict[str, dict] = {
    "BACKTEST_RANK": {
        "description": (
            "対象銘柄群をSTRATEGIES（移動平均クロスオーバー/RSI逆張り/MACDクロスオーバー/"
            "ボリンジャーバンド逆張り）のいずれかでバックテストし、銘柄ごとに近傍グリッド"
            "サーチで最適パラメータを探索してリスク調整済みリターン（収益率÷|最大ドロー"
            "ダウン|）降順にランキングし、上位top_n件に絞る。出力列: total_return_pct, "
            "benchmark_return_pct, win_rate_pct, max_drawdown_pct, risk_adjusted_return, "
            "best_params, _source_strategy。"
        ),
        "params_schema": {
            "strategy": "STRATEGIESのキー文字列（例: 移動平均クロスオーバー）",
            "period": "1y/3y/5y",
            "transaction_cost_pct": "数値（省略時0）",
            "top_n": "整数（省略時は絞り込みなし）",
        },
        "run": _run_backtest_rank,
    },
    "MULTI_STRATEGY_RANK": {
        "description": (
            "1戦略に決め打たず、STRATEGIESの4戦略すべてで対象銘柄群をバックテストし、"
            "銘柄ごとに「4戦略中もっともリスク調整済みリターンが高かった戦略」を採用して"
            "総合的にランキングする。「総合的に評価」「複数戦略で判断」のような要望で使う。"
            "出力列はBACKTEST_RANKと同じに加え、avg_risk_adjusted_return（4戦略平均）と"
            "profitable_strategy_count（4戦略中プラス収益だった戦略数、0〜4）を追加する。"
        ),
        "params_schema": {
            "period": "1y/3y/5y",
            "transaction_cost_pct": "数値（省略時0）",
            "top_n": "整数（省略時は絞り込みなし）",
            "aggregation": (
                "MEAN（デフォルト、avg_risk_adjusted_return降順）/ "
                "CONSENSUS（profitable_strategy_count降順）/ "
                "BEST（採用戦略自身のrisk_adjusted_return降順）"
            ),
        },
        "run": _run_multi_strategy_rank,
    },
    "FILTER_CURRENT_SIGNAL": {
        "description": (
            "各銘柄について、その銘柄自身の_source_strategy列の値（直前のBACKTEST_RANK"
            "またはMULTI_STRATEGY_RANKが付与）が直近5営業日以内にENTRY/EXITシグナルを"
            "出したかで絞り込む。移動平均クロスオーバー: ENTRY＝ゴールデンクロス、EXIT＝"
            "デッドクロス。MACDクロスオーバー: ENTRY＝MACD線がシグナル線を上抜け、EXIT＝"
            "その逆。RSI逆張り: ENTRY＝売られすぎ水準から回復、EXIT＝買われすぎ水準に到達。"
            "ボリンジャーバンド逆張り: ENTRY＝下バンド割れ、EXIT＝中心線を上抜け。"
        ),
        "params_schema": {
            "signal": "ENTRY または EXIT",
            "strategy": "省略可。STRATEGIESのキー文字列。省略時は銘柄ごとの_source_strategy列を使う",
        },
        "run": _run_filter_current_signal,
    },
    "FILTER_BY_FUNDAMENTALS": {
        "description": (
            "PER/PBR/ROE/配当利回り/売上高伸び率/時価総額/業種でフィルタする。"
        ),
        "params_schema": {
            "conditions": (
                "[{indicator, operator, value}, ...] の配列。indicatorはPER, PBR, ROE, "
                "DIVIDEND_YIELD, REVENUE_GROWTH, MARKET_CAP, SECTORのいずれか。operatorは"
                "LESS_THAN, LESS_EQUAL, GREATER_THAN, GREATER_EQUAL, EQUALSのいずれか"
                "（SECTORはEQUALSのみ）。"
            ),
        },
        "run": _run_filter_by_fundamentals,
    },
    "SORT_BY": {
        "description": "その時点で存在する列で並べ替える。存在しない列の場合は並べ替えをスキップする。",
        "params_schema": {"field": "列名", "order": "ASC または DESC"},
        "run": _run_sort_by,
    },
    "TOP_N": {
        "description": "指定件数に絞る。byが指定されていればその列で降順ソートしてから先頭n件を取る。",
        "params_schema": {"n": "整数", "by": "列名（省略可）"},
        "run": _run_top_n,
    },
}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `.venv/Scripts/python.exe -m pytest tests/test_strategy_builder_pipeline_functions.py -v`
Expected: PASS（全テスト）

- [ ] **Step 5: コミット**

```bash
git add strategy_builder/pipeline_functions.py tests/test_strategy_builder_pipeline_functions.py
git commit -m "$(cat <<'EOF'
feat: FILTER_BY_FUNDAMENTALS/SORT_BY/TOP_NとPIPELINE_FUNCTIONSレジストリを追加

v1関数レジストリ6関数が出揃った。FILTER_BY_FUNDAMENTALSは候補銘柄に
ファンダメンタルズ/業種列を都度結合してから既存apply_strategy_conditions
を適用する。SORT_BY/TOP_Nは列名を直接指定する汎用ソート/切り出し関数。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: pipeline.py — 実行エンジン

**Files:**
- Create: `strategy_builder/pipeline.py`
- Test: `tests/test_strategy_builder_pipeline.py`

**Interfaces:**
- Consumes: `PIPELINE_FUNCTIONS`（Task 7, `strategy_builder.pipeline_functions`）
- Produces: `run_pipeline(steps: list[dict], all_tickers: list[str], cache_dir) -> tuple[pd.DataFrame, list[str]]`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_strategy_builder_pipeline.py`を新規作成:

```python
import pandas as pd

import strategy_builder.pipeline as pipeline


def test_run_pipeline_applies_steps_in_order(monkeypatch):
    def fake_add_one(candidates_df, params, cache_dir):
        candidates_df = candidates_df.copy()
        candidates_df["value"] = candidates_df.get("value", 0) + params.get("amount", 1)
        return candidates_df

    monkeypatch.setattr(pipeline, "PIPELINE_FUNCTIONS", {"ADD": {"run": fake_add_one}})

    result_df, trace = pipeline.run_pipeline(
        [{"function": "ADD", "params": {"amount": 3}}, {"function": "ADD", "params": {"amount": 2}}],
        ["AAA.T"],
        cache_dir=None,
    )

    assert result_df["value"].iloc[0] == 5
    assert trace == ["開始: 1件", "ADD: 1件→1件", "ADD: 1件→1件"]


def test_run_pipeline_skips_unknown_function_and_continues():
    result_df, trace = pipeline.run_pipeline(
        [{"function": "UNKNOWN", "params": {}}], ["AAA.T"], cache_dir=None
    )

    assert result_df["ticker"].tolist() == ["AAA.T"]
    assert trace == ["開始: 1件", "UNKNOWN: 未知の関数のためスキップ"]


def test_run_pipeline_skips_step_that_raises_and_continues(monkeypatch):
    def failing_step(candidates_df, params, cache_dir):
        raise ValueError("boom")

    def passthrough_step(candidates_df, params, cache_dir):
        return candidates_df

    monkeypatch.setattr(
        pipeline,
        "PIPELINE_FUNCTIONS",
        {"FAIL": {"run": failing_step}, "PASS": {"run": passthrough_step}},
    )

    result_df, trace = pipeline.run_pipeline(
        [{"function": "FAIL", "params": {}}, {"function": "PASS", "params": {}}],
        ["AAA.T"],
        cache_dir=None,
    )

    assert result_df["ticker"].tolist() == ["AAA.T"]
    assert trace == ["開始: 1件", "FAIL: エラーのためスキップ", "PASS: 1件→1件"]


def test_run_pipeline_reduces_row_count_across_steps(monkeypatch):
    def keep_first_only(candidates_df, params, cache_dir):
        return candidates_df.head(1)

    monkeypatch.setattr(pipeline, "PIPELINE_FUNCTIONS", {"KEEP_FIRST": {"run": keep_first_only}})

    result_df, trace = pipeline.run_pipeline(
        [{"function": "KEEP_FIRST", "params": {}}], ["AAA.T", "BBB.T"], cache_dir=None
    )

    assert result_df["ticker"].tolist() == ["AAA.T"]
    assert trace == ["開始: 2件", "KEEP_FIRST: 2件→1件"]
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `.venv/Scripts/python.exe -m pytest tests/test_strategy_builder_pipeline.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 実装する**

`strategy_builder/pipeline.py`を新規作成:

```python
"""AIが対話で生成したsteps（関数名とparamsの並び）をそのまま実行するエンジン。
どの関数をどの順番で呼ぶかというフロー自体はここには存在せず、stepsに
従うだけの薄い実装にする。"""

import logging

import pandas as pd

from strategy_builder.pipeline_functions import PIPELINE_FUNCTIONS

logger = logging.getLogger(__name__)


def run_pipeline(steps: list[dict], all_tickers: list[str], cache_dir) -> tuple[pd.DataFrame, list[str]]:
    """全銘柄のticker列のみのDataFrameを初期値とし、stepsを先頭から順に適用する。
    未知のfunction名や例外を送出したステップはスキップし、トレースに理由を記録して
    処理を継続する（既存apply_filtersと同じ「壊れたLLM出力で全体を落とさない」方針）。"""
    candidates_df = pd.DataFrame({"ticker": all_tickers})
    trace = [f"開始: {len(candidates_df)}件"]

    for step in steps:
        function_name = step.get("function")
        params = step.get("params", {})
        entry = PIPELINE_FUNCTIONS.get(function_name)
        if entry is None:
            trace.append(f"{function_name}: 未知の関数のためスキップ")
            continue
        before_count = len(candidates_df)
        try:
            candidates_df = entry["run"](candidates_df, params, cache_dir)
        except Exception:
            logger.exception(
                "ステップ実行に失敗しました: function=%s params=%s", function_name, params
            )
            trace.append(f"{function_name}: エラーのためスキップ")
            continue
        trace.append(f"{function_name}: {before_count}件→{len(candidates_df)}件")

    return candidates_df, trace
```

- [ ] **Step 4: テストが通ることを確認**

Run: `.venv/Scripts/python.exe -m pytest tests/test_strategy_builder_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add strategy_builder/pipeline.py tests/test_strategy_builder_pipeline.py
git commit -m "$(cat <<'EOF'
feat: パイプライン実行エンジンrun_pipelineを追加

AIが生成したsteps（関数名+params配列）を先頭から順に適用する汎用
エンジンを実装。未知の関数名や例外を送出したステップはスキップし
トレースに記録して処理を継続する。処理フローはコードに存在せず、
steps自体がフローを表現する。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: strategy_dialogue.py — stepsスキーマへの対応

**Files:**
- Modify: `prompt_patterns/strategy_dialogue.py`
- Test: `tests/test_strategy_dialogue_prompt.py`

**Interfaces:**
- Consumes: `PIPELINE_FUNCTIONS`（Task 7, `strategy_builder.pipeline_functions`）
- Produces: `build_dialogue_prompt`（変更後も同シグネチャ）、`parse_dialogue_response`（`steps`キー検出を追加）、`build_refinement_prompt`（`steps`形式を出力するよう変更）

- [ ] **Step 1: 失敗する/変更が必要なテストを書く**

`tests/test_strategy_dialogue_prompt.py`の`test_build_dialogue_prompt_includes_persona_instructions`を置き換え:

```python
def test_build_dialogue_prompt_includes_persona_instructions():
    prompt = build_dialogue_prompt([{"role": "user", "content": "PERが低い銘柄"}])
    assert "クオンツ・アナリスト" in prompt
    assert "steps" in prompt
```

ファイル末尾に追記:

```python
def test_build_dialogue_prompt_lists_all_pipeline_functions():
    prompt = build_dialogue_prompt([{"role": "user", "content": "PERが低い銘柄"}])
    assert "BACKTEST_RANK" in prompt
    assert "MULTI_STRATEGY_RANK" in prompt
    assert "FILTER_CURRENT_SIGNAL" in prompt
    assert "FILTER_BY_FUNDAMENTALS" in prompt
    assert "SORT_BY" in prompt
    assert "TOP_N" in prompt


def test_parse_dialogue_response_detects_finalized_strategy_json_with_steps():
    raw = (
        '```json\n{"strategy_name": "ゴールデンクロス", "steps": '
        '[{"function": "BACKTEST_RANK", "params": {"strategy": "移動平均クロスオーバー"}}]}\n```'
    )
    result = parse_dialogue_response(raw)
    assert result["kind"] == "strategy"
    assert result["strategy"]["strategy_name"] == "ゴールデンクロス"
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `.venv/Scripts/python.exe -m pytest tests/test_strategy_dialogue_prompt.py -v`
Expected: FAIL（`test_build_dialogue_prompt_includes_persona_instructions`の`"steps" in prompt`と新規2テストがFAIL）

- [ ] **Step 3: 実装する**

`prompt_patterns/strategy_dialogue.py`を全面置き換え:

```python
"""AI協調型のスクリーニングロジック構築（AI戦略ビルダー機能②）向けの
対話プロンプト構築・応答解析を行うモジュール。

data_api.llm_client.call_llm はターン単位のセッション状態を持たない
ステートレスなサブプロセス呼び出しのため、対話の各ターンで会話全履歴を
毎回プロンプトに含めて送信する。
"""

import json

from common.json_parsing import strip_code_fence
from strategy_builder.pipeline_functions import PIPELINE_FUNCTIONS


def _format_pipeline_functions_for_prompt() -> str:
    lines = []
    for name, entry in PIPELINE_FUNCTIONS.items():
        params_lines = "\n".join(
            f"    - {param}: {description}"
            for param, description in entry["params_schema"].items()
        )
        lines.append(f"- {name}: {entry['description']}\n  params:\n{params_lines}")
    return "\n".join(lines)


_PERSONA_INSTRUCTIONS_TEMPLATE = """\
あなた（AI）は、ユーザーの投資アイデアを厳密な「株式スクリーニング・パイプライン」へと
昇華させるプロのクオンツ・アナリストです。以下のステップに従ってユーザーをナビゲートしてください。

【ステップ1: アイデアの定量化】
ユーザーから「考え方」が入力されたら、それを歓迎し、以下の要素を具体化するための質問や提案を
1〜2個、短く行ってください。
1. どの関数（複数可）をどの順番で使うか
2. 各関数のパラメータ（戦略名・期間・閾値等）
このステップでは、説明文以外は出力しないでください。JSON形式は使わないでください。

【使用できる関数一覧】
{functions}

【ステップ2: 構造化データの出力】
ユーザーと条件が合意できたら、それ以外の説明文を一切含めず、必ず次のJSON形式のみを
```json コードブロックで返してください。
```json
{{
  "strategy_name": "確定した戦略名",
  "steps": [
    {{"function": "関数名", "params": {{...}}}}
  ]
}}
```
stepsは上記の関数一覧にある関数名のみを使い、必要な順番・組み合わせで並べてください。
"""


def build_dialogue_prompt(history: list[dict], sectors: list[str] | None = None) -> str:
    """会話履歴（[{"role": "user"|"assistant", "content": str}, ...]）から、
    ペルソナ指示と会話全文を含む1回分のLLM呼び出し用プロンプトを組み立てる。

    sectorsを渡すと、SECTOR条件のvalueに使うべき正確な業種名の一覧を
    プロンプトに追加する（表記ゆれのない条件生成のため）。
    """
    sector_block = ""
    if sectors:
        sector_list = "、".join(sectors)
        sector_block = (
            "\n\nFILTER_BY_FUNDAMENTALSでSECTOR条件を使う場合、valueは次の業種名のいずれか"
            f"一つをそのまま正確に使ってください（表記ゆれを吸収し、最も近いものを選ぶこと）: {sector_list}"
        )
    persona = _PERSONA_INSTRUCTIONS_TEMPLATE.format(
        functions=_format_pipeline_functions_for_prompt()
    )
    transcript_lines = [
        f"{'ユーザー' if turn['role'] == 'user' else 'AI'}: {turn['content']}"
        for turn in history
    ]
    transcript = "\n".join(transcript_lines)
    return (
        f"{persona}{sector_block}"
        f"\n\n【これまでの会話】\n{transcript}\n\n【あなたの次の発言】"
    )


def parse_dialogue_response(raw: str) -> dict:
    """LLM応答を判定する。

    JSONコードブロックとして解析でき、かつ`strategy_name`と（`steps`または
    `conditions`）を含む場合は `{"kind": "strategy", "strategy": {...}}` を返す
    （`steps`は新形式、`conditions`は後方互換の旧形式）。それ以外は質問・提案
    テキストとして `{"kind": "question", "text": raw}` を返す。
    """
    try:
        parsed = json.loads(strip_code_fence(raw))
    except json.JSONDecodeError:
        return {"kind": "question", "text": raw.strip()}

    if isinstance(parsed, dict) and "strategy_name" in parsed:
        if "steps" in parsed or "conditions" in parsed:
            return {"kind": "strategy", "strategy": parsed}
    return {"kind": "question", "text": raw.strip()}


def build_refinement_prompt(pending_strategy: dict, feedback: str) -> str:
    """確定候補の戦略JSONと評価フィードバックから、修正版JSONを1回で
    生成させる軽量プロンプト（Evaluator-Optimizerパターンの改善ステップ）。
    既存の対話ペルソナ指示（_PERSONA_INSTRUCTIONS_TEMPLATE）は使わない。"""
    strategy_json = json.dumps(pending_strategy, ensure_ascii=False, indent=2)
    return (
        "以下は投資戦略のスクリーニングパイプライン（JSON）と、その評価フィードバックです。\n\n"
        f"【現在の条件】\n{strategy_json}\n\n"
        f"【評価フィードバック】\n{feedback}\n\n"
        "このフィードバックを踏まえて修正し、それ以外の説明文を一切含めず、"
        "必ず次のJSON形式のみを```json コードブロックで返してください。\n"
        "```json\n"
        "{\n"
        '  "strategy_name": "修正後の戦略名",\n'
        '  "steps": [\n'
        '    {"function": "関数名", "params": {}}\n'
        "  ]\n"
        "}\n"
        "```\n"
        f"{_format_pipeline_functions_for_prompt()}"
    )
```

- [ ] **Step 4: 全テストが通ることを確認**

Run: `.venv/Scripts/python.exe -m pytest tests/test_strategy_dialogue_prompt.py -v`
Expected: PASS（既存テストの`test_parse_dialogue_response_detects_finalized_strategy_json`・`test_build_refinement_prompt_lists_allowed_indicators_and_operators`等が無修正のまま通ることも確認する）

- [ ] **Step 5: コミット**

```bash
git add prompt_patterns/strategy_dialogue.py tests/test_strategy_dialogue_prompt.py
git commit -m "$(cat <<'EOF'
feat: AI対話のペルソナ指示をPIPELINE_FUNCTIONSベースのstepsスキーマに刷新

_PERSONA_INSTRUCTIONSをPIPELINE_FUNCTIONSレジストリから動的に生成する
方式に変更し、AIがユーザーの要望から任意の関数の組み合わせ・順番を
stepsとして出力できるようにした。parse_dialogue_responseはsteps/
conditionsどちらのスキーマも判定でき、既存の保存済みconditions形式
戦略との後方互換を保つ。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: evaluation.py — steps/conditionsスキーマ判定バグの修正

**Files:**
- Modify: `strategy_builder/evaluation.py:64`
- Test: `tests/test_strategy_builder_evaluation.py`

**Interfaces:**
- Consumes: `build_refinement_prompt`（Task 9）
- Produces: `run_evaluation_loop`（既存シグネチャ変更なし、内部の受理判定のみ修正）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_strategy_builder_evaluation.py`に追記:

```python
def test_run_evaluation_loop_refines_steps_based_strategy_and_returns_on_second_pass():
    strategy = {
        "strategy_name": "ゴールデンクロス",
        "steps": [{"function": "BACKTEST_RANK", "params": {"strategy": "移動平均クロスオーバー"}}],
    }
    refined_strategy = {
        "strategy_name": "ゴールデンクロス（改善）",
        "steps": [
            {"function": "BACKTEST_RANK", "params": {"strategy": "移動平均クロスオーバー", "top_n": 50}}
        ],
    }
    responses = iter(
        [
            '{"pass": false, "feedback": "対象銘柄数を絞ってください"}',
            json.dumps(refined_strategy, ensure_ascii=False),
            '{"pass": true, "feedback": ""}',
        ]
    )

    def fake_call_llm(prompt):
        return next(responses)

    result = run_evaluation_loop(strategy, call_llm=fake_call_llm)

    assert result["strategy"] == refined_strategy
    assert result["iterations"] == 1


def test_run_evaluation_loop_rejects_refinement_with_wrong_schema_for_steps_strategy():
    strategy = {
        "strategy_name": "ゴールデンクロス",
        "steps": [{"function": "BACKTEST_RANK", "params": {"strategy": "移動平均クロスオーバー"}}],
    }
    wrong_schema_refinement = {
        "strategy_name": "誤ったスキーマ",
        "conditions": [{"indicator": "PER", "operator": "LESS_THAN", "value": 15}],
    }
    responses = iter(
        [
            '{"pass": false, "feedback": "改善してください"}',
            json.dumps(wrong_schema_refinement, ensure_ascii=False),
            '{"pass": false, "feedback": "まだ不十分です"}',
        ]
    )

    def fake_call_llm(prompt):
        return next(responses)

    result = run_evaluation_loop(strategy, call_llm=fake_call_llm, max_iterations=2)

    assert result["strategy"] == strategy
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `.venv/Scripts/python.exe -m pytest tests/test_strategy_builder_evaluation.py -k steps_based -v`
Expected: FAIL（`test_run_evaluation_loop_refines_steps_based_strategy_and_returns_on_second_pass`が失敗する。現状は`"conditions" in refined`のみを見ているため、steps形式の改善案が常に拒否され、`result["strategy"]`が`refined_strategy`ではなく元の`strategy`のままになる）

- [ ] **Step 3: バグを修正する**

`strategy_builder/evaluation.py:58-65`（`run_evaluation_loop`内、`if i < max_iterations - 1:`ブロック）を置き換え:

```python
        if i < max_iterations - 1:
            raw = call_llm(build_refinement_prompt(current, last_feedback))
            try:
                refined = json.loads(strip_code_fence(raw))
            except json.JSONDecodeError:
                refined = None
            expected_key = "steps" if "steps" in current else "conditions"
            if isinstance(refined, dict) and expected_key in refined:
                current = refined
```

- [ ] **Step 4: 全テストが通ることを確認**

Run: `.venv/Scripts/python.exe -m pytest tests/test_strategy_builder_evaluation.py -v`
Expected: PASS（既存の`conditions`ベーステストも無修正のまま通ることを確認する）

- [ ] **Step 5: コミット**

```bash
git add strategy_builder/evaluation.py tests/test_strategy_builder_evaluation.py
git commit -m "$(cat <<'EOF'
fix: 評価ループの改善案受理判定をsteps/conditions両対応に修正

run_evaluation_loopが改善案JSONの受理判定に"conditions" in refinedを
決め打ちしていたため、steps形式の戦略に対する改善案が常に拒否され
Evaluator-Optimizerループが機能しないバグを修正。現在のstrategyが
steps/conditionsどちらのスキーマかで期待するキーを切り替える。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: strategy_builder_tab.py — UI分岐とパイプライン実行セクション

**Files:**
- Modify: `app_tabs/strategy_builder_tab.py:1-37, 344-435`（import追加、`_render_pipeline_section`新設、`render_strategy_builder_tab`の分岐）

**Interfaces:**
- Consumes: `run_pipeline`（Task 8, `strategy_builder.pipeline`）、`CACHE_DIR`（`app_tabs.shared`）

このタスクにはpytestテストが無い（このプロジェクトでは`app_tabs/*.py`のUI関数を直接pytestで検証する前例が無いため）。実装後、`run`スキルでStreamlitアプリを起動し、ブラウザで手動確認する。

- [ ] **Step 1: importを追加する**

`app_tabs/strategy_builder_tab.py:30-35`を置き換え:

```python
from app_tabs.shared import (
    CACHE_DIR,
    get_current_user_id,
    handle_table_selection,
    render_mermaid,
    run_or_load_sector_rotation,
)
from strategy_builder.pipeline import run_pipeline
```

- [ ] **Step 2: `_render_pipeline_section`を追加する**

`app_tabs/strategy_builder_tab.py`の`_render_screening_section`の直後（`render_strategy_builder_tab`定義の直前、404-407行目付近の空行部分）に追記:

```python
def _render_pipeline_section() -> None:
    strategy = st.session_state.get("strategy_confirmed")
    st.subheader("③ パイプラインを実行")
    if strategy is None:
        st.caption("②で戦略を確定するか、保存済み戦略を読み込むと利用できます。")
        return

    st.write(f"対象戦略: **{strategy['strategy_name']}**")

    if st.button("パイプラインを実行", key="strategy_run_pipeline"):
        with st.spinner("パイプラインを実行中..."):
            company_profiles = load_all_company_profiles()
            all_tickers = [p["ticker"] for p in company_profiles]
            names_by_ticker = {
                p["ticker"]: p["name"] for p in company_profiles if p["name"]
            }

            result_df, trace = run_pipeline(strategy["steps"], all_tickers, CACHE_DIR)
            result_df = result_df.copy()
            result_df["name"] = result_df["ticker"].map(names_by_ticker).fillna("")

            st.session_state["strategy_pipeline_result_df"] = result_df
            st.session_state["strategy_pipeline_trace"] = trace
            st.session_state["strategy_pipeline_selected_row"] = None
            st.session_state["strategy_pipeline_result_table"] = {
                "selection": {"rows": [], "columns": []}
            }

    trace = st.session_state.get("strategy_pipeline_trace")
    if trace:
        st.caption(" → ".join(trace))

    result_df = st.session_state.get("strategy_pipeline_result_df")
    if result_df is not None:
        st.caption(f"該当銘柄（{len(result_df)}件）。行をクリックすると銘柄詳細を表示します。")
        event = st.dataframe(
            result_df,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="strategy_pipeline_result_table",
        )
        handle_table_selection("strategy_pipeline_selected_row", event, result_df)
```

- [ ] **Step 3: `render_strategy_builder_tab`を分岐させる**

`app_tabs/strategy_builder_tab.py:427-434`を置き換え:

```python
    _render_idea_input_section()
    st.divider()
    _render_dialogue_section()
    st.divider()

    strategy = st.session_state.get("strategy_confirmed")
    if strategy is not None and "steps" in strategy:
        _render_pipeline_section()
    else:
        _render_backtest_section()
        st.divider()
        _render_screening_section()
    st.markdown(DISCLAIMER_NOTICE)
```

- [ ] **Step 4: 全テストスイートを実行し回帰が無いことを確認**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS（全件）

- [ ] **Step 5: `run`スキルでStreamlitアプリを起動し、ブラウザで手動確認する**

確認項目:
- 既存の`conditions`ベースのアイデア（例:「PERが低い銘柄」）を対話で確定すると、従来どおり③バックテスト検証④最新データで銘柄選定が表示され、動作が変わっていないこと
- 新しいアイデア（例:「移動平均クロスオーバー戦略で上位100銘柄を選び、直近ゴールデンクロスしている銘柄を、リスク調整済みリターンでランキングして」）を対話で確定すると、`steps`を含む戦略JSONが生成され、③パイプラインを実行セクションが表示されること
- 「パイプラインを実行」ボタン押下で、各ステップの件数トレースと最終結果テーブルが表示されること
- 結果テーブルの行をクリックすると銘柄詳細ダイアログが開くこと

- [ ] **Step 6: コミット**

```bash
git add app_tabs/strategy_builder_tab.py
git commit -m "$(cat <<'EOF'
feat: AI戦略ビルダータブにパイプライン実行セクションを追加

確定した戦略にstepsキーがあれば新設の「③ パイプラインを実行」セクション
（run_pipelineを呼び、各ステップの件数トレースと最終結果テーブルを表示）
に、conditionsキーのみの旧形式戦略なら既存の③バックテスト検証/④最新
データで銘柄選定にそのまま分岐する。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Notes

- **Spec coverage**: 6関数レジストリ（Task 3,4,6,7）・実行エンジン（Task 8）・戦略JSONスキーマ拡張とAI対話プロンプト（Task 9）・UI分岐（Task 11）・キャッシュ共有（Task 2）・指標計算ロジック共有（Task 1）・`_source_strategy`の銘柄単位解決バグ回避（Task 6の`_run_filter_current_signal`）・評価ループのスキーマ判定バグ修正（Task 10、設計書には無いが実装時に発見し対応）を全てタスク化済み。設計書の「非スコープ」項目（tool_use API、within_daysパラメータ化、セクターローテーション連携、旧形式の自動マイグレーション）はいずれのタスクにも含めていない。
- **Type consistency**: `(candidates_df, params, cache_dir) -> pd.DataFrame`の統一シグネチャを全関数・`run_pipeline`・テストのmonkeypatchで一貫させた。`PIPELINE_FUNCTIONS`のキー名（`BACKTEST_RANK`等）はTask 7のレジストリ定義とTask 9のプロンプト生成・テストで一致させた。
