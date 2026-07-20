# バックテスト機能拡張（複数戦略・複数銘柄ランキング） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移動平均クロスオーバーに加えてRSI逆張り・MACDクロスオーバー・ボリンジャーバンド逆張りの3戦略を追加し、UNIVERSE＋保有銘柄を対象にした複数銘柄一括バックテスト・ランキング（「一括バックテスト」タブ）を実装する。

**Architecture:** 4戦略共通の「ポジション系列→リターン・勝率・最大ドローダウン算出」処理を `_finalize_backtest` ヘルパーに集約し、`STRATEGIES` レジストリ（戦略名→計算関数・プリセット・最低必要日数）で戦略を一元管理する。既存の「バックテスト」タブは戦略選択に対応させ、新設の「一括バックテスト」タブはレジストリの標準プリセットで全銘柄を実行してリスク調整済みリターンでランキングする。

**Tech Stack:** Python 3.14 / pandas / Streamlit / pytest（`uv run pytest`）。設計書: [docs/superpowers/specs/2026-07-20-backtest-strategies-and-ranking-design.md](../specs/2026-07-20-backtest-strategies-and-ranking-design.md)。

## Global Constraints

- 返り値の指標キーは既存の `_pct` 命名規則に合わせる: `total_return_pct`, `benchmark_return_pct`, `win_rate_pct`, `max_drawdown_pct`, `trade_days`（新規追加する `risk_adjusted_return` を除く）
- `transaction_cost_pct` はパーセントポイント単位（例: `0.1` は0.1%）で渡す
- 全戦略の計算関数は「シグナル発生日の終値ではなく翌日約定とするため1日ずらす」ルックアヘッドバイアス回避を必ず行う（`shift(1)`）
- LLM解説文の冒頭・末尾には必ず `common.disclaimer.DISCLAIMER_NOTICE` を含める
- プロンプトには「買うべき」「このルールで今すぐ売買すべき」等の指示的表現を使わないよう明示する
- yfinance呼び出しはテストでモックせず、`pd.Series` の辞書やスタブ関数をテストコードから直接渡す（既存 `test_backtest.py` と同じ方針）
- すべてのコマンドは `app/` ディレクトリで実行する
- 本プランは `portfolio_management/backtest.py` の既存公開関数のシグネチャ（`run_backtest_comparison`, `generate_backtest_explanation`）を破壊的に変更する。`BACKTEST_PRESETS` 定数は廃止し `STRATEGIES` レジストリに置き換える

---

### Task 1: 共通末尾処理の抽出（`_finalize_backtest`）

既存の `run_ma_crossover_backtest` の「シグナルをshift(1)した後」の処理を独立関数に抽出する（リファクタのみ、返り値・既存テストの期待値は一切変更しない）。

**Files:**
- Modify: `portfolio_management/backtest.py`
- Test: `tests/test_backtest.py`（新規テストは追加しない。既存テストが回帰なく通ることを確認する）

**Interfaces:**
- Produces: `_finalize_backtest(prices: pd.Series, position: pd.Series, transaction_cost_pct: float) -> dict` — `position` はshift済み（ルックアヘッドバイアス回避済み）の0/1系列。返り値は `{"total_return_pct": float, "benchmark_return_pct": float, "win_rate_pct": float, "max_drawdown_pct": float, "trade_days": int}`

- [ ] **Step 1: 既存テストがリファクタ前に通ることを確認する**

Run: `uv run pytest tests/test_backtest.py -v`
Expected: PASS（既存6件全て成功、これがリファクタ後も壊れていないことを確認する基準になる）

- [ ] **Step 2: `_finalize_backtest` を抽出し `run_ma_crossover_backtest` を書き換える**

`portfolio_management/backtest.py` の `run_ma_crossover_backtest` を以下に置き換える（ファイル冒頭の `import pandas as pd` 以下、`BACKTEST_PRESETS` より前の部分）:

```python
import pandas as pd

from common.disclaimer import DISCLAIMER_NOTICE
from data_api.llm_client import call_llm as default_call_llm
from prompt_patterns.backtest_explanation import build_backtest_prompt


def _finalize_backtest(prices: pd.Series, position: pd.Series, transaction_cost_pct: float) -> dict:
    daily_return = prices.pct_change().fillna(0)
    strategy_return = position * daily_return

    if transaction_cost_pct:
        position_changed = position.diff().fillna(0) != 0
        cost = transaction_cost_pct / 100
        strategy_return = strategy_return - position_changed.astype(int) * cost

    benchmark_return = daily_return  # Buy & Hold

    cum_strategy = (1 + strategy_return).cumprod() - 1
    cum_benchmark = (1 + benchmark_return).cumprod() - 1

    trade_days = position[position != 0].index
    win_rate = (strategy_return.loc[trade_days] > 0).mean() if len(trade_days) else 0.0

    running_max = (1 + cum_strategy).cummax()
    drawdown = (1 + cum_strategy) / running_max - 1
    max_drawdown = drawdown.min()

    return {
        "total_return_pct": round(cum_strategy.iloc[-1] * 100, 2),
        "benchmark_return_pct": round(cum_benchmark.iloc[-1] * 100, 2),
        "win_rate_pct": round(win_rate * 100, 2),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "trade_days": int(len(trade_days)),
    }


def run_ma_crossover_backtest(
    prices: pd.Series,
    short_window: int = 25,
    long_window: int = 75,
    transaction_cost_pct: float = 0.0,
) -> dict:
    """移動平均クロスオーバー戦略をベクトル化してバックテストする。"""
    short_ma = prices.rolling(short_window).mean()
    long_ma = prices.rolling(long_window).mean()

    # 短期MAが長期MAを上回っている日をロングポジション(1)とする。
    # シグナル発生日の終値ではなく翌日約定とするため1日ずらす
    # （ルックアヘッドバイアス回避）。
    position = (short_ma > long_ma).astype(int).shift(1).fillna(0)

    return _finalize_backtest(prices, position, transaction_cost_pct)
```

ファイルの残り（`BACKTEST_PRESETS` 以降）はこの時点では変更しない。

- [ ] **Step 3: 既存テストが引き続き通ることを確認する**

Run: `uv run pytest tests/test_backtest.py -v`
Expected: PASS（Step 1と同じ6件が成功。数値が一切変わっていないことを確認する）

- [ ] **Step 4: Commit**

```bash
git add portfolio_management/backtest.py
git commit -m "refactor: extract shared backtest finalization logic"
```

---

### Task 2: RSI逆張り戦略

**Files:**
- Modify: `portfolio_management/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: Task 1の `_finalize_backtest(prices, position, transaction_cost_pct) -> dict`
- Produces: `run_rsi_reversal_backtest(prices: pd.Series, period: int = 14, oversold: int = 30, overbought: int = 70, transaction_cost_pct: float = 0.0) -> dict`

- [ ] **Step 1: Write the failing tests**

`tests/test_backtest.py` の先頭importに追加する:

```python
from portfolio_management.backtest import (
    BACKTEST_PRESETS,
    generate_backtest_explanation,
    run_backtest_comparison,
    run_ma_crossover_backtest,
    run_rsi_reversal_backtest,
)
```

（`BACKTEST_PRESETS` は Task 5 で削除されるまではまだ残っているのでこの時点ではimportしたままでよい）

ファイル末尾に追加する:

```python
def test_run_rsi_reversal_backtest_enters_on_oversold_recovery_and_exits_on_overbought():
    dates = pd.date_range("2026-01-01", periods=9, freq="D")
    prices = pd.Series([100, 90, 80, 70, 90, 110, 130, 130, 130], index=dates)

    result = run_rsi_reversal_backtest(prices, period=3, oversold=30, overbought=70)

    assert result == {
        "total_return_pct": 22.22,
        "benchmark_return_pct": 30.0,
        "win_rate_pct": 100.0,
        "max_drawdown_pct": 0.0,
        "trade_days": 1,
    }


def test_run_rsi_reversal_backtest_applies_transaction_cost_on_position_change():
    dates = pd.date_range("2026-01-01", periods=9, freq="D")
    prices = pd.Series([100, 90, 80, 70, 90, 110, 130, 130, 130], index=dates)

    result = run_rsi_reversal_backtest(
        prices, period=3, oversold=30, overbought=70, transaction_cost_pct=0.1
    )

    assert result == {
        "total_return_pct": 22.0,
        "benchmark_return_pct": 30.0,
        "win_rate_pct": 100.0,
        "max_drawdown_pct": -0.1,
        "trade_days": 1,
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_backtest.py -v`
Expected: FAIL（`ImportError`: `run_rsi_reversal_backtest` が存在しない）

- [ ] **Step 3: Write minimal implementation**

`portfolio_management/backtest.py` の `run_ma_crossover_backtest` の直後に追加する:

```python
def run_rsi_reversal_backtest(
    prices: pd.Series,
    period: int = 14,
    oversold: int = 30,
    overbought: int = 70,
    transaction_cost_pct: float = 0.0,
) -> dict:
    """RSI逆張り戦略をベクトル化してバックテストする。"""
    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    # RSIが売られすぎ水準を下から上に回復した日にロングエントリー、
    # 買われすぎ水準に達した日に手仕舞いする。
    entry = (rsi.shift(1) < oversold) & (rsi >= oversold)
    exit_signal = rsi >= overbought

    raw_position = pd.Series(index=prices.index, dtype=float)
    raw_position[entry] = 1.0
    raw_position[exit_signal] = 0.0
    held_position = raw_position.ffill().fillna(0)

    # シグナル発生日の終値ではなく翌日約定とするため1日ずらす
    # （ルックアヘッドバイアス回避）。
    position = held_position.shift(1).fillna(0)

    return _finalize_backtest(prices, position, transaction_cost_pct)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_backtest.py -v`
Expected: PASS（既存6件＋新規2件の計8件が成功）

- [ ] **Step 5: Commit**

```bash
git add portfolio_management/backtest.py tests/test_backtest.py
git commit -m "feat: add RSI reversal backtest strategy"
```

---

### Task 3: MACDクロスオーバー戦略

**Files:**
- Modify: `portfolio_management/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: Task 1の `_finalize_backtest(prices, position, transaction_cost_pct) -> dict`
- Produces: `run_macd_crossover_backtest(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9, transaction_cost_pct: float = 0.0) -> dict`

- [ ] **Step 1: Write the failing tests**

`tests/test_backtest.py` の先頭importに `run_macd_crossover_backtest` を追加する（`run_rsi_reversal_backtest` の並びに追加）。

ファイル末尾に追加する:

```python
def test_run_macd_crossover_backtest_shifts_signal_to_avoid_lookahead_bias():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.Series([100, 100, 102, 102], index=dates)

    result = run_macd_crossover_backtest(prices, fast=1, slow=2, signal=2)

    assert result == {
        "total_return_pct": 0.0,
        "benchmark_return_pct": 2.0,
        "win_rate_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "trade_days": 1,
    }


def test_run_macd_crossover_backtest_applies_transaction_cost_on_position_change():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.Series([100, 100, 102, 102], index=dates)

    result = run_macd_crossover_backtest(
        prices, fast=1, slow=2, signal=2, transaction_cost_pct=0.1
    )

    assert result["total_return_pct"] == -0.1
    assert result["max_drawdown_pct"] == -0.1
    assert result["benchmark_return_pct"] == 2.0
    assert result["trade_days"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_backtest.py -v`
Expected: FAIL（`ImportError`: `run_macd_crossover_backtest` が存在しない）

- [ ] **Step 3: Write minimal implementation**

`portfolio_management/backtest.py` の `run_rsi_reversal_backtest` の直後に追加する:

```python
def run_macd_crossover_backtest(
    prices: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    transaction_cost_pct: float = 0.0,
) -> dict:
    """MACDクロスオーバー戦略をベクトル化してバックテストする。"""
    fast_ema = prices.ewm(span=fast, adjust=False).mean()
    slow_ema = prices.ewm(span=slow, adjust=False).mean()
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()

    # MACD線がシグナル線を上回っている日をロングポジション(1)とする。
    # シグナル発生日の終値ではなく翌日約定とするため1日ずらす
    # （ルックアヘッドバイアス回避）。
    position = (macd_line > signal_line).astype(int).shift(1).fillna(0)

    return _finalize_backtest(prices, position, transaction_cost_pct)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_backtest.py -v`
Expected: PASS（既存8件＋新規2件の計10件が成功）

- [ ] **Step 5: Commit**

```bash
git add portfolio_management/backtest.py tests/test_backtest.py
git commit -m "feat: add MACD crossover backtest strategy"
```

---

### Task 4: ボリンジャーバンド逆張り戦略

**Files:**
- Modify: `portfolio_management/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: Task 1の `_finalize_backtest(prices, position, transaction_cost_pct) -> dict`
- Produces: `run_bollinger_reversal_backtest(prices: pd.Series, window: int = 20, num_std: float = 2.0, transaction_cost_pct: float = 0.0) -> dict`

- [ ] **Step 1: Write the failing tests**

`tests/test_backtest.py` の先頭importに `run_bollinger_reversal_backtest` を追加する。

ファイル末尾に追加する:

```python
def test_run_bollinger_reversal_backtest_enters_below_lower_band_and_exits_at_middle_band():
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    prices = pd.Series([100, 100, 70, 100, 100], index=dates)

    result = run_bollinger_reversal_backtest(prices, window=3, num_std=1.0)

    assert result == {
        "total_return_pct": 42.86,
        "benchmark_return_pct": 0.0,
        "win_rate_pct": 100.0,
        "max_drawdown_pct": 0.0,
        "trade_days": 1,
    }


def test_run_bollinger_reversal_backtest_applies_transaction_cost_on_position_change():
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    prices = pd.Series([100, 100, 70, 100, 100], index=dates)

    result = run_bollinger_reversal_backtest(
        prices, window=3, num_std=1.0, transaction_cost_pct=0.1
    )

    assert result == {
        "total_return_pct": 42.61,
        "benchmark_return_pct": 0.0,
        "win_rate_pct": 100.0,
        "max_drawdown_pct": -0.1,
        "trade_days": 1,
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_backtest.py -v`
Expected: FAIL（`ImportError`: `run_bollinger_reversal_backtest` が存在しない）

- [ ] **Step 3: Write minimal implementation**

`portfolio_management/backtest.py` の `run_macd_crossover_backtest` の直後に追加する:

```python
def run_bollinger_reversal_backtest(
    prices: pd.Series,
    window: int = 20,
    num_std: float = 2.0,
    transaction_cost_pct: float = 0.0,
) -> dict:
    """ボリンジャーバンド逆張り戦略をベクトル化してバックテストする。"""
    middle_band = prices.rolling(window).mean()
    band_std = prices.rolling(window).std()
    lower_band = middle_band - num_std * band_std

    # 終値が下バンドを下回った日にロングエントリー、
    # 中心線（移動平均）以上に回帰した日に手仕舞いする。
    entry = prices < lower_band
    exit_signal = prices >= middle_band

    raw_position = pd.Series(index=prices.index, dtype=float)
    raw_position[entry] = 1.0
    raw_position[exit_signal] = 0.0
    held_position = raw_position.ffill().fillna(0)

    # シグナル発生日の終値ではなく翌日約定とするため1日ずらす
    # （ルックアヘッドバイアス回避）。
    position = held_position.shift(1).fillna(0)

    return _finalize_backtest(prices, position, transaction_cost_pct)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_backtest.py -v`
Expected: PASS（既存10件＋新規2件の計12件が成功）

- [ ] **Step 5: Commit**

```bash
git add portfolio_management/backtest.py tests/test_backtest.py
git commit -m "feat: add Bollinger band reversal backtest strategy"
```

---

### Task 5: `STRATEGIES` レジストリと `run_backtest_comparison` / `generate_backtest_explanation` / `build_backtest_prompt` の汎用化

`BACKTEST_PRESETS` を廃止し `STRATEGIES` レジストリに置き換える。`run_backtest_comparison` のシグネチャを汎用化し、`generate_backtest_explanation` と `build_backtest_prompt` が戦略名・戦略関数を受け取れるようにする。この3つは相互依存しているため1タスクにまとめる（分割すると中間状態でimportエラーになる）。

**Files:**
- Modify: `portfolio_management/backtest.py`
- Modify: `prompt_patterns/backtest_explanation.py`
- Test: `tests/test_backtest.py`
- Test: `tests/test_backtest_explanation.py`

**Interfaces:**
- Consumes: Task 1〜4の4つの `run_*_backtest` 関数
- Produces:
  - `STRATEGIES: dict[str, dict]`（キー: 戦略名、値: `{"func": callable, "presets": list[tuple[str, dict]], "min_days": int}`。各戦略の `presets[0]` が「標準プリセット」）
  - `run_backtest_comparison(prices: pd.Series, backtest_func, presets: list[tuple[str, dict]], transaction_cost_pct: float = 0.0) -> dict[str, dict]`
  - `build_backtest_prompt(ticker: str, comparison: dict[str, dict], strategy_name: str = "移動平均クロスオーバー") -> str`
  - `generate_backtest_explanation(ticker: str, prices: pd.Series, backtest_func=run_ma_crossover_backtest, strategy_name: str = "移動平均クロスオーバー", presets: list[tuple[str, dict]] | None = None, transaction_cost_pct: float = 0.0, call_llm=default_call_llm) -> str`

- [ ] **Step 1: Write the failing tests**

`tests/test_backtest_explanation.py` を以下に置き換える:

```python
from common.disclaimer import DISCLAIMER_NOTICE
from prompt_patterns.backtest_explanation import build_backtest_prompt


def test_build_backtest_prompt_includes_ticker_and_facts():
    comparison = {"標準(25/75)": {"total_return_pct": 18.4, "trade_days": 312}}

    prompt = build_backtest_prompt("7203.T", comparison)

    assert "7203.T" in prompt
    assert "18.4" in prompt
    assert "312" in prompt
    assert DISCLAIMER_NOTICE in prompt


def test_build_backtest_prompt_instructs_overfitting_and_no_directive_language():
    comparison = {"標準(25/75)": {"total_return_pct": 18.4}}

    prompt = build_backtest_prompt("7203.T", comparison)

    assert "過学習" in prompt
    assert "取引コスト" in prompt
    assert "売買" in prompt
    assert "パラメータ" in prompt


def test_build_backtest_prompt_uses_default_strategy_name_when_omitted():
    comparison = {"標準(25/75)": {"total_return_pct": 18.4}}

    prompt = build_backtest_prompt("7203.T", comparison)

    assert "移動平均クロスオーバー戦略" in prompt


def test_build_backtest_prompt_uses_given_strategy_name():
    comparison = {"標準(14, 30/70)": {"total_return_pct": 5.0}}

    prompt = build_backtest_prompt("7203.T", comparison, strategy_name="RSI逆張り")

    assert "RSI逆張り戦略" in prompt
    assert "移動平均クロスオーバー戦略" not in prompt
```

`tests/test_backtest.py` を以下に置き換える（RSI/MACD/ボリンジャーバンドのテストはTask 2〜4で追加済みの部分を保持しつつ、importと `BACKTEST_PRESETS`/`run_backtest_comparison`/`generate_backtest_explanation` 関連テストを更新する）:

```python
import pandas as pd

from common.disclaimer import DISCLAIMER_NOTICE
from portfolio_management.backtest import (
    STRATEGIES,
    generate_backtest_explanation,
    run_backtest_comparison,
    run_bollinger_reversal_backtest,
    run_ma_crossover_backtest,
    run_macd_crossover_backtest,
    run_rsi_reversal_backtest,
)


def test_run_ma_crossover_backtest_shifts_signal_to_avoid_lookahead_bias():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.Series([100, 100, 102, 102], index=dates)

    result = run_ma_crossover_backtest(prices, short_window=1, long_window=2)

    assert result == {
        "total_return_pct": 0.0,
        "benchmark_return_pct": 2.0,
        "win_rate_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "trade_days": 1,
    }


def test_run_ma_crossover_backtest_applies_transaction_cost_on_position_change():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.Series([100, 100, 102, 102], index=dates)

    result = run_ma_crossover_backtest(
        prices, short_window=1, long_window=2, transaction_cost_pct=0.1
    )

    assert result["total_return_pct"] == -0.1
    assert result["max_drawdown_pct"] == -0.1
    assert result["benchmark_return_pct"] == 2.0
    assert result["trade_days"] == 1


def test_run_rsi_reversal_backtest_enters_on_oversold_recovery_and_exits_on_overbought():
    dates = pd.date_range("2026-01-01", periods=9, freq="D")
    prices = pd.Series([100, 90, 80, 70, 90, 110, 130, 130, 130], index=dates)

    result = run_rsi_reversal_backtest(prices, period=3, oversold=30, overbought=70)

    assert result == {
        "total_return_pct": 22.22,
        "benchmark_return_pct": 30.0,
        "win_rate_pct": 100.0,
        "max_drawdown_pct": 0.0,
        "trade_days": 1,
    }


def test_run_rsi_reversal_backtest_applies_transaction_cost_on_position_change():
    dates = pd.date_range("2026-01-01", periods=9, freq="D")
    prices = pd.Series([100, 90, 80, 70, 90, 110, 130, 130, 130], index=dates)

    result = run_rsi_reversal_backtest(
        prices, period=3, oversold=30, overbought=70, transaction_cost_pct=0.1
    )

    assert result == {
        "total_return_pct": 22.0,
        "benchmark_return_pct": 30.0,
        "win_rate_pct": 100.0,
        "max_drawdown_pct": -0.1,
        "trade_days": 1,
    }


def test_run_macd_crossover_backtest_shifts_signal_to_avoid_lookahead_bias():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.Series([100, 100, 102, 102], index=dates)

    result = run_macd_crossover_backtest(prices, fast=1, slow=2, signal=2)

    assert result == {
        "total_return_pct": 0.0,
        "benchmark_return_pct": 2.0,
        "win_rate_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "trade_days": 1,
    }


def test_run_macd_crossover_backtest_applies_transaction_cost_on_position_change():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.Series([100, 100, 102, 102], index=dates)

    result = run_macd_crossover_backtest(
        prices, fast=1, slow=2, signal=2, transaction_cost_pct=0.1
    )

    assert result["total_return_pct"] == -0.1
    assert result["max_drawdown_pct"] == -0.1
    assert result["benchmark_return_pct"] == 2.0
    assert result["trade_days"] == 1


def test_run_bollinger_reversal_backtest_enters_below_lower_band_and_exits_at_middle_band():
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    prices = pd.Series([100, 100, 70, 100, 100], index=dates)

    result = run_bollinger_reversal_backtest(prices, window=3, num_std=1.0)

    assert result == {
        "total_return_pct": 42.86,
        "benchmark_return_pct": 0.0,
        "win_rate_pct": 100.0,
        "max_drawdown_pct": 0.0,
        "trade_days": 1,
    }


def test_run_bollinger_reversal_backtest_applies_transaction_cost_on_position_change():
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    prices = pd.Series([100, 100, 70, 100, 100], index=dates)

    result = run_bollinger_reversal_backtest(
        prices, window=3, num_std=1.0, transaction_cost_pct=0.1
    )

    assert result == {
        "total_return_pct": 42.61,
        "benchmark_return_pct": 0.0,
        "win_rate_pct": 100.0,
        "max_drawdown_pct": -0.1,
        "trade_days": 1,
    }


def test_strategies_registry_contains_all_four_strategies():
    assert set(STRATEGIES.keys()) == {
        "移動平均クロスオーバー",
        "RSI逆張り",
        "MACDクロスオーバー",
        "ボリンジャーバンド逆張り",
    }


def test_strategies_registry_entries_have_func_two_presets_and_min_days():
    for definition in STRATEGIES.values():
        assert callable(definition["func"])
        assert isinstance(definition["presets"], list)
        assert len(definition["presets"]) == 2
        assert isinstance(definition["min_days"], int)


def test_run_backtest_comparison_returns_result_per_preset_label():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.Series([100, 100, 102, 102], index=dates)

    result = run_backtest_comparison(
        prices,
        run_ma_crossover_backtest,
        presets=[
            ("A", {"short_window": 1, "long_window": 2}),
            ("B", {"short_window": 1, "long_window": 2}),
        ],
    )

    expected_single = {
        "total_return_pct": 0.0,
        "benchmark_return_pct": 2.0,
        "win_rate_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "trade_days": 1,
    }
    assert result == {"A": expected_single, "B": expected_single}


def test_generate_backtest_explanation_includes_disclaimer_and_commentary():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.Series([100, 100, 102, 102], index=dates)
    fake_call_llm = lambda prompt: "テスト用のバックテスト解説です。"

    result = generate_backtest_explanation(
        "AAA.T",
        prices,
        presets=[("A", {"short_window": 1, "long_window": 2})],
        call_llm=fake_call_llm,
    )

    assert result.count(DISCLAIMER_NOTICE) == 2
    assert "テスト用のバックテスト解説です。" in result


def test_generate_backtest_explanation_passes_ticker_and_comparison_to_prompt():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.Series([100, 100, 102, 102], index=dates)
    captured_prompts = []

    def fake_call_llm(prompt):
        captured_prompts.append(prompt)
        return "解説"

    generate_backtest_explanation(
        "AAA.T",
        prices,
        presets=[("A", {"short_window": 1, "long_window": 2})],
        call_llm=fake_call_llm,
    )

    assert "AAA.T" in captured_prompts[0]
    assert '"A"' in captured_prompts[0]


def test_generate_backtest_explanation_passes_strategy_name_and_func_to_prompt():
    dates = pd.date_range("2026-01-01", periods=9, freq="D")
    prices = pd.Series([100, 90, 80, 70, 90, 110, 130, 130, 130], index=dates)
    captured_prompts = []

    def fake_call_llm(prompt):
        captured_prompts.append(prompt)
        return "解説"

    generate_backtest_explanation(
        "AAA.T",
        prices,
        backtest_func=run_rsi_reversal_backtest,
        strategy_name="RSI逆張り",
        presets=[("A", {"period": 3, "oversold": 30, "overbought": 70})],
        call_llm=fake_call_llm,
    )

    assert "RSI逆張り戦略" in captured_prompts[0]


def test_generate_backtest_explanation_uses_default_ma_strategy_when_presets_omitted():
    dates = pd.date_range("2026-01-01", periods=80, freq="D")
    prices = pd.Series([100.0] * 80, index=dates)
    fake_call_llm = lambda prompt: "解説"

    result = generate_backtest_explanation("AAA.T", prices, call_llm=fake_call_llm)

    assert "解説" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_backtest.py tests/test_backtest_explanation.py -v`
Expected: FAIL（`ImportError`: `STRATEGIES` が存在しない、`run_backtest_comparison`/`generate_backtest_explanation` のシグネチャ不一致によるエラー、`build_backtest_prompt` が `strategy_name` を受け付けない）

- [ ] **Step 3: Write minimal implementation**

`prompt_patterns/backtest_explanation.py` を以下に置き換える:

```python
import json

from common.disclaimer import DISCLAIMER_NOTICE


def build_backtest_prompt(
    ticker: str, comparison: dict[str, dict], strategy_name: str = "移動平均クロスオーバー"
) -> str:
    comparison_json = json.dumps(comparison, ensure_ascii=False, indent=2, default=str)
    return (
        f"以下は{strategy_name}戦略のバックテスト結果です"
        "（Python側でパラメータ組ごとに計算済みのため再計算は不要です）。\n\n"
        f"【対象銘柄】{ticker}\n"
        f"【パラメータ組ごとの結果（JSON）】\n{comparison_json}\n\n"
        "この結果を投資初心者にも分かる言葉で説明してください。\n"
        "以下を必ず含めてください。\n"
        "1. 各パラメータ組について、戦略のリターンとベンチマーク（Buy&Hold）の比較\n"
        "2. 勝率・最大ドローダウンの意味\n"
        "3. 過去の結果が将来の成績を保証しないこと、"
        "および過学習・取引コストやスリッページを考慮しきれていない可能性への注意喚起\n"
        "4. パラメータ組同士の結果を比較し、大きく異なっている場合は"
        "パラメータ選択に対する過学習リスクを強調すること\n"
        "5. 追加で確認する価値がある指標やシナリオの提案（実行はしない）\n\n"
        "出力は事実の説明と教育的な提案にとどめ、「買うべき」「このルールで"
        "今すぐ売買すべき」のような指示的な表現は使わないでください。\n\n"
        f"{DISCLAIMER_NOTICE}"
    )
```

`portfolio_management/backtest.py` の `BACKTEST_PRESETS` 以降（旧 `run_backtest_comparison`・`generate_backtest_explanation`）を以下に置き換える:

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


def run_backtest_comparison(
    prices: pd.Series,
    backtest_func,
    presets: list[tuple[str, dict]],
    transaction_cost_pct: float = 0.0,
) -> dict[str, dict]:
    return {
        label: backtest_func(prices, transaction_cost_pct=transaction_cost_pct, **params)
        for label, params in presets
    }


def generate_backtest_explanation(
    ticker: str,
    prices: pd.Series,
    backtest_func=run_ma_crossover_backtest,
    strategy_name: str = "移動平均クロスオーバー",
    presets: list[tuple[str, dict]] | None = None,
    transaction_cost_pct: float = 0.0,
    call_llm=default_call_llm,
) -> str:
    if presets is None:
        presets = STRATEGIES[strategy_name]["presets"]

    comparison = run_backtest_comparison(prices, backtest_func, presets, transaction_cost_pct)
    prompt = build_backtest_prompt(ticker, comparison, strategy_name)
    commentary = call_llm(prompt)

    sections = [
        DISCLAIMER_NOTICE,
        "",
        f"# バックテスト結果解説（{ticker}）",
        "",
        commentary,
        "",
        "---",
        "",
        DISCLAIMER_NOTICE,
    ]
    return "\n".join(sections)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_backtest.py tests/test_backtest_explanation.py -v`
Expected: PASS（全件成功）

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -v`
Expected: PASS（`app.py` はこの時点でまだ古い `BACKTEST_PRESETS` importを参照しており、pytest収集時にimportエラーになる場合はTask 8まで待たずに `app.py` のバックテスト関連import行を一時的に `STRATEGIES` に変更してビルドを通す。ただしUIロジック本体の書き換えはTask 8で行う）

- [ ] **Step 6: Commit**

```bash
git add portfolio_management/backtest.py prompt_patterns/backtest_explanation.py tests/test_backtest.py tests/test_backtest_explanation.py
git commit -m "feat: add strategy registry and generalize backtest comparison/explanation"
```

---

### Task 6: 複数銘柄一括バックテスト・ランキング関数

**Files:**
- Modify: `portfolio_management/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Produces: `run_universe_backtest_ranking(prices_by_ticker: dict[str, pd.Series], backtest_func, preset_params: dict, transaction_cost_pct: float = 0.0, min_days: int = 0) -> list[dict]` — 各行は `{"ticker": str, **backtest_func の返り値, "risk_adjusted_return": float}`。`risk_adjusted_return` の降順でソート済み

- [ ] **Step 1: Write the failing tests**

`tests/test_backtest.py` の先頭importに `run_universe_backtest_ranking` を追加する。

ファイル末尾に追加する:

```python
def test_run_universe_backtest_ranking_sorts_by_risk_adjusted_return_and_skips_short_history():
    dates3 = pd.date_range("2026-01-01", periods=3, freq="D")
    dates1 = pd.date_range("2026-01-01", periods=1, freq="D")
    prices_by_ticker = {
        "AAA.T": pd.Series([20.0, 20.0, 20.0], index=dates3),
        "BBB.T": pd.Series([60.0, 60.0, 60.0], index=dates3),
        "CCC.T": pd.Series([999.0], index=dates1),
    }

    def fake_backtest_func(prices, transaction_cost_pct=0.0, **params):
        marker = float(prices.iloc[0])
        return {
            "total_return_pct": marker,
            "benchmark_return_pct": 0.0,
            "win_rate_pct": 100.0,
            "max_drawdown_pct": -10.0,
            "trade_days": 1,
        }

    result = run_universe_backtest_ranking(
        prices_by_ticker, fake_backtest_func, preset_params={}, min_days=2
    )

    assert [row["ticker"] for row in result] == ["BBB.T", "AAA.T"]
    assert result[0]["risk_adjusted_return"] == 6.0
    assert result[1]["risk_adjusted_return"] == 2.0


def test_run_universe_backtest_ranking_falls_back_to_total_return_when_drawdown_is_zero():
    dates = pd.date_range("2026-01-01", periods=2, freq="D")
    prices_by_ticker = {"AAA.T": pd.Series([10.0, 10.0], index=dates)}

    def fake_backtest_func(prices, transaction_cost_pct=0.0, **params):
        return {
            "total_return_pct": 15.0,
            "benchmark_return_pct": 0.0,
            "win_rate_pct": 100.0,
            "max_drawdown_pct": 0.0,
            "trade_days": 1,
        }

    result = run_universe_backtest_ranking(
        prices_by_ticker, fake_backtest_func, preset_params={}, min_days=1
    )

    assert result[0]["risk_adjusted_return"] == 15.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_backtest.py -v`
Expected: FAIL（`ImportError`: `run_universe_backtest_ranking` が存在しない）

- [ ] **Step 3: Write minimal implementation**

`portfolio_management/backtest.py` の末尾に追加する:

```python
def run_universe_backtest_ranking(
    prices_by_ticker: dict[str, pd.Series],
    backtest_func,
    preset_params: dict,
    transaction_cost_pct: float = 0.0,
    min_days: int = 0,
) -> list[dict]:
    rows = []
    for ticker, prices in prices_by_ticker.items():
        if len(prices) < min_days:
            continue
        result = backtest_func(prices, transaction_cost_pct=transaction_cost_pct, **preset_params)
        drawdown = abs(result["max_drawdown_pct"])
        risk_adjusted_return = (
            result["total_return_pct"] / drawdown if drawdown else result["total_return_pct"]
        )
        rows.append(
            {"ticker": ticker, **result, "risk_adjusted_return": round(risk_adjusted_return, 2)}
        )
    return sorted(rows, key=lambda row: row["risk_adjusted_return"], reverse=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_backtest.py -v`
Expected: PASS（全件成功）

- [ ] **Step 5: Commit**

```bash
git add portfolio_management/backtest.py tests/test_backtest.py
git commit -m "feat: add universe backtest ranking"
```

---

### Task 7: ランキング上位銘柄のAIコメント生成

**Files:**
- Modify: `prompt_patterns/backtest_explanation.py`
- Test: `tests/test_backtest_explanation.py`

**Interfaces:**
- Produces:
  - `build_ranking_comment_prompt(ranking_rows: list[dict]) -> str`
  - `generate_ranking_comments(ranking_rows: list[dict], call_llm=default_call_llm) -> dict[str, str]`

- [ ] **Step 1: Write the failing tests**

`tests/test_backtest_explanation.py` の末尾に追加する（先頭importに `build_ranking_comment_prompt, generate_ranking_comments` を追加する）:

```python
def test_build_ranking_comment_prompt_includes_ticker_data_and_json_output_instruction():
    ranking_rows = [{"ticker": "AAA.T", "total_return_pct": 20.0, "risk_adjusted_return": 6.0}]

    prompt = build_ranking_comment_prompt(ranking_rows)

    assert "AAA.T" in prompt
    assert "20.0" in prompt
    assert "6.0" in prompt


def test_generate_ranking_comments_returns_empty_dict_for_empty_ranking():
    assert generate_ranking_comments([]) == {}


def test_generate_ranking_comments_parses_llm_json_response():
    ranking_rows = [
        {"ticker": "AAA.T", "total_return_pct": 20.0, "risk_adjusted_return": 6.0},
        {"ticker": "BBB.T", "total_return_pct": 10.0, "risk_adjusted_return": 2.0},
    ]
    fake_call_llm = lambda prompt: '{"AAA.T": "好調でした。", "BBB.T": "堅調でした。"}'

    result = generate_ranking_comments(ranking_rows, call_llm=fake_call_llm)

    assert result == {"AAA.T": "好調でした。", "BBB.T": "堅調でした。"}


def test_generate_ranking_comments_falls_back_on_invalid_json():
    ranking_rows = [{"ticker": "AAA.T", "total_return_pct": 20.0, "risk_adjusted_return": 6.0}]
    fake_call_llm = lambda prompt: "not json"

    result = generate_ranking_comments(ranking_rows, call_llm=fake_call_llm)

    assert result == {"AAA.T": "コメント生成失敗"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_backtest_explanation.py -v`
Expected: FAIL（`ImportError`: `build_ranking_comment_prompt`/`generate_ranking_comments` が存在しない）

- [ ] **Step 3: Write minimal implementation**

`prompt_patterns/backtest_explanation.py` の先頭importを以下に変更する:

```python
import json

from common.disclaimer import DISCLAIMER_NOTICE
from common.json_parsing import strip_code_fence
from data_api.llm_client import call_llm as default_call_llm
```

ファイル末尾に追加する:

```python
def build_ranking_comment_prompt(ranking_rows: list[dict]) -> str:
    rows = [
        {
            "ticker": row["ticker"],
            "total_return_pct": row["total_return_pct"],
            "risk_adjusted_return": row["risk_adjusted_return"],
        }
        for row in ranking_rows
    ]
    rows_json = json.dumps(rows, ensure_ascii=False)
    return (
        "以下は複数銘柄のバックテスト結果ランキング（リスク調整済みリターン降順）です。"
        "銘柄ごとに投資家向けの一言コメントを日本語で1文ずつ作成してください。"
        "断定的な売買判断は含めないでください。\n"
        '出力形式: {"<ticker>": "<コメント>"} というJSONのみを出力してください。\n\n'
        f"{rows_json}"
    )


def generate_ranking_comments(
    ranking_rows: list[dict], call_llm=default_call_llm
) -> dict[str, str]:
    if not ranking_rows:
        return {}

    prompt = build_ranking_comment_prompt(ranking_rows)
    raw = call_llm(prompt)
    try:
        return json.loads(strip_code_fence(raw))
    except json.JSONDecodeError:
        return {row["ticker"]: "コメント生成失敗" for row in ranking_rows}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_backtest_explanation.py -v`
Expected: PASS（全件成功）

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -v`
Expected: PASS（`app.py` のimportエラーが残っている場合はTask 5 Step 5の暫定対応を維持。Task 8で解消する）

- [ ] **Step 6: Commit**

```bash
git add prompt_patterns/backtest_explanation.py tests/test_backtest_explanation.py
git commit -m "feat: add ranking comment prompt and generation"
```

---

### Task 8: 既存「バックテスト」タブの戦略選択対応

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: Task 5の `STRATEGIES`, `run_backtest_comparison(prices, backtest_func, presets, transaction_cost_pct)`, `generate_backtest_explanation(ticker, prices, backtest_func, strategy_name, presets, transaction_cost_pct, call_llm)`

- [ ] **Step 1: importを更新する**

`app.py` の以下の行:

```python
from portfolio_management.backtest import (
    BACKTEST_PRESETS,
    generate_backtest_explanation,
    run_backtest_comparison,
)
```

を以下に置き換える:

```python
from portfolio_management.backtest import (
    STRATEGIES,
    generate_backtest_explanation,
    run_backtest_comparison,
)
```

- [ ] **Step 2: 「バックテスト」タブの中身を戦略選択対応に書き換える**

`app.py` の `with tab_backtest:` ブロック全体を以下に置き換える:

```python
with tab_backtest:
    st.header("バックテスト")

    backtest_strategy = st.selectbox(
        "戦略", list(STRATEGIES.keys()), key="backtest_strategy"
    )
    backtest_ticker = st.text_input(
        "銘柄コード", placeholder="7203.T", key="backtest_ticker"
    )
    backtest_period = st.selectbox(
        "取得期間", ["1y", "3y", "5y"], index=1, key="backtest_period"
    )
    apply_transaction_cost = st.checkbox(
        "取引コストを考慮する（1回あたり0.1%）", key="backtest_cost_checkbox"
    )
    backtest_force_regenerate = st.checkbox(
        "キャッシュを無視して再生成する", key="backtest_force_regenerate"
    )

    if backtest_ticker and st.button("バックテストを実行"):
        strategy = STRATEGIES[backtest_strategy]
        transaction_cost_pct = 0.1 if apply_transaction_cost else 0.0
        history = fetch_price_history(backtest_ticker, period=backtest_period)

        if history.empty or len(history) < strategy["min_days"]:
            st.error(
                "株価データが取得できないか、バックテストに必要な日数"
                f"（{strategy['min_days']}日）に満たないため実行できません。"
            )
        else:
            prices = history["Close"]

            comparison = run_backtest_comparison(
                prices, strategy["func"], strategy["presets"], transaction_cost_pct
            )
            comparison_df = pd.DataFrame(comparison).T
            comparison_df.index.name = "パラメータ組"

            st.subheader("パラメータ組ごとの比較")
            st.dataframe(
                comparison_df,
                column_config={
                    "total_return_pct": st.column_config.NumberColumn("累積リターン(%)"),
                    "benchmark_return_pct": st.column_config.NumberColumn("ベンチマーク(%)"),
                    "win_rate_pct": st.column_config.NumberColumn("勝率(%)"),
                    "max_drawdown_pct": st.column_config.NumberColumn("最大DD(%)"),
                    "trade_days": st.column_config.NumberColumn("取引日数"),
                },
            )

            cache_key = "backtest-" + hashlib.sha256(
                f"{backtest_strategy}-{backtest_ticker}-{backtest_period}-{transaction_cost_pct}".encode(
                    "utf-8"
                )
            ).hexdigest()[:12]
            cached_explanation = (
                None if backtest_force_regenerate else read_cache(CACHE_DIR, cache_key)
            )

            if cached_explanation is not None:
                explanation = cached_explanation
            else:
                explanation = generate_backtest_explanation(
                    backtest_ticker,
                    prices,
                    backtest_func=strategy["func"],
                    strategy_name=backtest_strategy,
                    presets=strategy["presets"],
                    transaction_cost_pct=transaction_cost_pct,
                )
                write_cache(CACHE_DIR, cache_key, explanation)

            st.markdown(explanation)
```

- [ ] **Step 3: 全テストを実行して既存機能に影響がないことを確認する**

Run: `uv run pytest -v`
Expected: PASS（全件成功。`app.py` はimport可能なpythonファイルとしての構文チェックのみ対象）

- [ ] **Step 4: Streamlitアプリを起動して手動確認する**

Run: `uv run streamlit run app.py`

確認項目:
- 「バックテスト」タブに「戦略」ドロップダウンが表示され、4戦略すべてが選択できる
- 実在する銘柄コード（例: `7203.T`）を入力し、各戦略で「バックテストを実行」を押すと、比較テーブル（プリセット2行）が表示される
- 戦略を切り替えて実行すると、比較テーブルの指標が戦略に応じて変化する
- LLM解説文に選択した戦略名が反映されている
- 確認後、動作結果を一言メモしておく（後続のレビューで参照するため）

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "feat: add strategy selector to the backtest tab"
```

---

### Task 9: 「一括バックテスト」タブの新設

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes:
  - Task 5の `STRATEGIES`
  - Task 6の `run_universe_backtest_ranking(prices_by_ticker, backtest_func, preset_params, transaction_cost_pct, min_days) -> list[dict]`
  - Task 7の `generate_ranking_comments(ranking_rows, call_llm) -> dict[str, str]`
  - 既存の `UNIVERSE`, `UNIVERSE_NAMES`（`screening.universe`）
  - 既存の `load_holdings(HOLDINGS_PATH) -> list[dict]`, `build_candidate_names(holdings, resolve_name) -> dict[str, str]`
  - 既存の `fetch_price_history(ticker, period) -> pd.DataFrame`, `read_cache`/`write_cache`, `CACHE_DIR`, `_cached_fetch_japanese_name`

- [ ] **Step 1: importを追加する**

`app.py` の以下の行:

```python
from portfolio_management.backtest import (
    STRATEGIES,
    generate_backtest_explanation,
    run_backtest_comparison,
)
```

を以下に置き換える:

```python
from portfolio_management.backtest import (
    STRATEGIES,
    generate_backtest_explanation,
    run_backtest_comparison,
    run_universe_backtest_ranking,
)
```

`from prompt_patterns.screening import (` の直前に以下を追加する:

```python
from prompt_patterns.backtest_explanation import generate_ranking_comments
```

- [ ] **Step 2: タブ構成を4つに変更する**

`app.py` の以下の行:

```python
tab_portfolio, tab_screening, tab_backtest = st.tabs(
    ["ポートフォリオ", "スクリーニング", "バックテスト"]
)
```

を以下に置き換える:

```python
tab_portfolio, tab_screening, tab_backtest, tab_ranking = st.tabs(
    ["ポートフォリオ", "スクリーニング", "バックテスト", "一括バックテスト"]
)
```

- [ ] **Step 3: 「一括バックテスト」タブの中身を追加する**

`app.py` の `with tab_backtest:` ブロックの末尾（ファイル末尾）に追加する:

```python
with tab_ranking:
    st.header("複数銘柄一括バックテスト・ランキング")
    st.caption(
        "主要銘柄（UNIVERSE）と保有銘柄を対象に、選択した戦略の標準プリセットで"
        "バックテストし、リスク調整済みリターン（累積リターン÷|最大ドローダウン|）の高い順に並べます。"
    )

    ranking_strategy = st.selectbox(
        "戦略", list(STRATEGIES.keys()), key="ranking_strategy"
    )
    ranking_period = st.selectbox(
        "取得期間", ["1y", "3y", "5y"], index=1, key="ranking_period"
    )
    ranking_apply_cost = st.checkbox(
        "取引コストを考慮する（1回あたり0.1%）", key="ranking_cost_checkbox"
    )
    ranking_force_regenerate = st.checkbox(
        "キャッシュを無視して再生成する", key="ranking_force_regenerate"
    )

    if st.button("一括バックテストを実行"):
        strategy = STRATEGIES[ranking_strategy]
        transaction_cost_pct = 0.1 if ranking_apply_cost else 0.0

        holdings = load_holdings(HOLDINGS_PATH)
        holdings_tickers = [h["ticker"] for h in holdings if h.get("ticker")]
        target_tickers = sorted(set(UNIVERSE) | set(holdings_tickers))

        cache_key = "universe-backtest-" + hashlib.sha256(
            f"{ranking_strategy}-{ranking_period}-{transaction_cost_pct}-"
            f"{'-'.join(target_tickers)}".encode("utf-8")
        ).hexdigest()[:12]
        cached_payload = None if ranking_force_regenerate else read_cache(CACHE_DIR, cache_key)

        payload = json.loads(cached_payload) if cached_payload is not None else None

        if payload is None:
            prices_by_ticker = {}
            skipped_tickers = []
            progress = st.progress(0.0, text="株価データを取得中...")
            for i, ticker in enumerate(target_tickers):
                try:
                    history = fetch_price_history(ticker, period=ranking_period)
                except Exception:
                    skipped_tickers.append(ticker)
                    history = None
                if history is not None and not history.empty:
                    prices_by_ticker[ticker] = history["Close"]
                else:
                    if ticker not in skipped_tickers:
                        skipped_tickers.append(ticker)
                progress.progress(
                    (i + 1) / len(target_tickers),
                    text=f"株価データを取得中... ({i + 1}/{len(target_tickers)})",
                )
            progress.empty()

            if not prices_by_ticker:
                st.error("バックテスト可能な銘柄がありませんでした。")
                payload = None
            else:
                standard_label, standard_params = strategy["presets"][0]
                ranking_rows = run_universe_backtest_ranking(
                    prices_by_ticker,
                    strategy["func"],
                    standard_params,
                    transaction_cost_pct=transaction_cost_pct,
                    min_days=strategy["min_days"],
                )
                comments = generate_ranking_comments(ranking_rows[:5], call_llm=call_llm)
                payload = {
                    "ranking_rows": ranking_rows,
                    "skipped_tickers": skipped_tickers,
                    "comments": comments,
                    "preset_label": standard_label,
                }
                write_cache(CACHE_DIR, cache_key, json.dumps(payload, ensure_ascii=False))

        if payload is not None:
            candidate_names = build_candidate_names(
                load_holdings(HOLDINGS_PATH), resolve_name=_cached_fetch_japanese_name
            )
            ranking_df = pd.DataFrame(payload["ranking_rows"])
            ranking_df["name"] = ranking_df["ticker"].map(candidate_names).fillna("")
            ranking_df.insert(0, "順位", range(1, len(ranking_df) + 1))
            ranking_df = ranking_df[
                [
                    "順位",
                    "ticker",
                    "name",
                    "total_return_pct",
                    "benchmark_return_pct",
                    "win_rate_pct",
                    "max_drawdown_pct",
                    "risk_adjusted_return",
                ]
            ]

            st.subheader(f"{ranking_strategy}（{payload['preset_label']}）ランキング")
            st.dataframe(
                ranking_df,
                column_config={
                    "ticker": st.column_config.TextColumn("銘柄コード"),
                    "name": st.column_config.TextColumn("銘柄名"),
                    "total_return_pct": st.column_config.NumberColumn("累積リターン(%)"),
                    "benchmark_return_pct": st.column_config.NumberColumn("ベンチマーク(%)"),
                    "win_rate_pct": st.column_config.NumberColumn("勝率(%)"),
                    "max_drawdown_pct": st.column_config.NumberColumn("最大DD(%)"),
                    "risk_adjusted_return": st.column_config.NumberColumn("リスク調整済みリターン"),
                },
                hide_index=True,
            )

            if payload["skipped_tickers"]:
                st.info(
                    "データ取得・データ不足によりスキップした銘柄: "
                    + ", ".join(payload["skipped_tickers"])
                )

            st.subheader("上位5銘柄のAIコメント")
            for row in payload["ranking_rows"][:5]:
                ticker = row["ticker"]
                st.write(f"**{ticker}**: {payload['comments'].get(ticker, 'コメント生成失敗')}")

            st.markdown(DISCLAIMER_NOTICE)
```

- [ ] **Step 4: 全テストを実行して既存機能に影響がないことを確認する**

Run: `uv run pytest -v`
Expected: PASS（全件成功）

- [ ] **Step 5: Streamlitアプリを起動して手動確認する**

Run: `uv run streamlit run app.py`

確認項目:
- 「一括バックテスト」タブが表示される
- 戦略を選び「一括バックテストを実行」を押すと、進捗バーが表示された後、ランキング表が表示される（UNIVERSE 58銘柄が対象になるため数十秒かかる場合がある点に留意する）
- ランキング表がリスク調整済みリターンの降順で並んでいる
- 上位5銘柄にAIコメントが表示され、末尾に免責事項が表示される
- 存在しない銘柄が保有銘柄に含まれていてもクラッシュせず、「スキップ銘柄」として表示される（保有銘柄に架空のティッカーを追加して確認する）
- 「キャッシュを無視して再生成する」チェックボックスをONにすると再実行されることを確認する
- 確認後、動作結果を一言メモしておく（後続のレビューで参照するため）

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "feat: add universe backtest ranking tab"
```

---

### Task 10: README更新

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 「バックテスト」タブの説明を戦略選択対応に更新し、「一括バックテスト」タブの説明を追加する**

`README.md` の以下の行:

```markdown
- **バックテスト**タブ: 銘柄コードを入力すると、移動平均クロスオーバー戦略を「短期(5/25)」「標準(25/75)」の2パラメータ組でベクトル化バックテストし、累積リターン・ベンチマーク（Buy&Hold）・勝率・最大ドローダウンを比較表示します。取引コスト（1回あたり0.1%）を考慮した計算にも対応し、AIによる結果解説（過学習・取引コスト未考慮などバックテストの限界への注意喚起を含む）を表示します。
```

を以下に置き換える:

```markdown
- **バックテスト**タブ: 銘柄コードを入力すると、選択した戦略（移動平均クロスオーバー、RSI逆張り、MACDクロスオーバー、ボリンジャーバンド逆張りの4種類）を2パラメータ組でベクトル化バックテストし、累積リターン・ベンチマーク（Buy&Hold）・勝率・最大ドローダウンを比較表示します。取引コスト（1回あたり0.1%）を考慮した計算にも対応し、AIによる結果解説（過学習・取引コスト未考慮などバックテストの限界への注意喚起を含む）を表示します。
- **一括バックテスト**タブ: 主要銘柄（UNIVERSE、58銘柄）と保有銘柄を対象に、選択した戦略の標準プリセットで一括バックテストし、リスク調整済みリターン（累積リターン÷\|最大ドローダウン\|）の高い順にランキング表示します。上位5銘柄にはAIによる一言コメントを表示します。
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: update README for new backtest strategies and ranking tab"
```

---

## Self-Review Notes

- **Spec coverage:** 設計書の全項目（4戦略、`STRATEGIES` レジストリ、`run_backtest_comparison`/`generate_backtest_explanation`/`build_backtest_prompt` の汎用化、`run_universe_backtest_ranking`、ランキングAIコメント、両タブのUI、README）をTask 1〜10で網羅している。
- **Type consistency:** `run_*_backtest` の返り値キー（`total_return_pct` 等）はTask 1〜9で一貫。`presets: list[tuple[str, dict]]` の形もTask 5以降で統一。`STRATEGIES[key]["presets"][0]` を「標準プリセット」とする規約は設計書・Task 5・Task 9で一致させた（移動平均クロスオーバーの `presets` 順序を「標準」→「短期」に変更し、他3戦略と揃えた）。
- **Placeholder scan:** 各Stepに実行可能なコード・具体的なアサーション・実コマンドを記載済み。「TBD」「後で実装」等の記述なし。
- **Numeric verification:** RSI逆張り・MACDクロスオーバー・ボリンジャーバンド逆張りの期待値は全て手計算で検証済み（設計時にpandasのローリング計算・EMA計算を分数で追跡し、四捨五入後の値を確定させた）。
