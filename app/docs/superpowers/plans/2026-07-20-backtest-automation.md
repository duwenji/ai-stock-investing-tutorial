# バックテスト機能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `docs/05-portfolio-management/03-backtest-automation.md` の移動平均クロスオーバー戦略バックテスト＋LLM解説を `app/` に統合し、取引コスト考慮と2パラメータ組（短期(5/25)・標準(25/75)）比較を備えた「バックテスト」タブとして提供する。

**Architecture:** 既存の `portfolio_management`（純粋計算）/ `prompt_patterns`（LLMプロンプト生成）/ `app.py`（Streamlit UI）の3層分離パターンを踏襲する。計算は `portfolio_management/backtest.py` に、プロンプト生成は `prompt_patterns/backtest_explanation.py` に置き、`app.py` は両者を呼び出すだけの薄い層にする。

**Tech Stack:** Python 3.14 / pandas / Streamlit / pytest（`uv run pytest`）。設計書: [docs/superpowers/specs/2026-07-20-backtest-automation-design.md](../specs/2026-07-20-backtest-automation-design.md)。

## Global Constraints

- 返り値の指標キーは既存の `_pct` 命名規則に合わせる: `total_return_pct`, `benchmark_return_pct`, `win_rate_pct`, `max_drawdown_pct`, `trade_days`
- `transaction_cost_pct` はパーセントポイント単位（例: `0.1` は0.1%）で渡す
- LLM解説文の冒頭・末尾には必ず `common.disclaimer.DISCLAIMER_NOTICE` を含める（`portfolio_management/review.py` の `generate_portfolio_review` と同じ形）
- プロンプトには「買うべき」「このルールで今すぐ売買すべき」等の指示的表現を使わないよう明示する
- yfinance呼び出しはテストでモックせず、`pd.Series` / `pd.DataFrame` をテストコードから直接関数に渡す（既存 `test_risk.py` / `test_technical_agent.py` と同じ方針）
- すべてのコマンドは `app/` ディレクトリで実行する

---

### Task 1: 移動平均クロスオーバーのバックテスト計算（取引コスト対応）

**Files:**
- Create: `portfolio_management/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Produces: `run_ma_crossover_backtest(prices: pd.Series, short_window: int = 25, long_window: int = 75, transaction_cost_pct: float = 0.0) -> dict` — 返り値は `{"total_return_pct": float, "benchmark_return_pct": float, "win_rate_pct": float, "max_drawdown_pct": float, "trade_days": int}`

- [ ] **Step 1: Write the failing tests**

`tests/test_backtest.py` を作成する:

```python
import pandas as pd

from portfolio_management.backtest import run_ma_crossover_backtest


def test_run_ma_crossover_backtest_shifts_signal_to_avoid_lookahead_bias():
    # short_window=1, long_window=2 のとき、
    # day2にクロスオーバーが発生するが、シグナルは1日ずらされるため
    # 実際にポジションを持つのはday3のみ（このday3のリターンは0）。
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

    # 唯一のポジション変化日（day3のエントリー）に0.1%のコストが乗る。
    assert result["total_return_pct"] == -0.1
    assert result["max_drawdown_pct"] == -0.1
    assert result["benchmark_return_pct"] == 2.0
    assert result["trade_days"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_backtest.py -v`
Expected: FAIL（`ModuleNotFoundError` または `ImportError`: `portfolio_management.backtest` が存在しない）

- [ ] **Step 3: Write minimal implementation**

`portfolio_management/backtest.py` を作成する:

```python
import pandas as pd


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_backtest.py -v`
Expected: PASS（2件とも成功）

- [ ] **Step 5: Commit**

```bash
git add portfolio_management/backtest.py tests/test_backtest.py
git commit -m "feat: add MA crossover backtest calculation with transaction cost support"
```

---

### Task 2: 2パラメータ組の比較（`BACKTEST_PRESETS` / `run_backtest_comparison`）

**Files:**
- Modify: `portfolio_management/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: Task 1の `run_ma_crossover_backtest(prices, short_window, long_window, transaction_cost_pct) -> dict`
- Produces:
  - `BACKTEST_PRESETS: list[tuple[str, int, int]]` = `[("短期(5/25)", 5, 25), ("標準(25/75)", 25, 75)]`
  - `run_backtest_comparison(prices: pd.Series, presets: list[tuple[str, int, int]] = BACKTEST_PRESETS, transaction_cost_pct: float = 0.0) -> dict[str, dict]`

- [ ] **Step 1: Write the failing tests**

`tests/test_backtest.py` の末尾に追加する:

```python
from portfolio_management.backtest import BACKTEST_PRESETS, run_backtest_comparison


def test_backtest_presets_are_short_and_standard():
    assert BACKTEST_PRESETS == [
        ("短期(5/25)", 5, 25),
        ("標準(25/75)", 25, 75),
    ]


def test_run_backtest_comparison_returns_result_per_preset_label():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.Series([100, 100, 102, 102], index=dates)

    result = run_backtest_comparison(prices, presets=[("A", 1, 2), ("B", 1, 2)])

    expected_single = {
        "total_return_pct": 0.0,
        "benchmark_return_pct": 2.0,
        "win_rate_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "trade_days": 1,
    }
    assert result == {"A": expected_single, "B": expected_single}
```

（`from portfolio_management.backtest import run_ma_crossover_backtest` の行はそのまま残し、上記のインポートを追加する形にする）

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_backtest.py -v`
Expected: FAIL（`ImportError`: `BACKTEST_PRESETS` / `run_backtest_comparison` が存在しない）

- [ ] **Step 3: Write minimal implementation**

`portfolio_management/backtest.py` の末尾に追加する:

```python
BACKTEST_PRESETS: list[tuple[str, int, int]] = [
    ("短期(5/25)", 5, 25),
    ("標準(25/75)", 25, 75),
]


def run_backtest_comparison(
    prices: pd.Series,
    presets: list[tuple[str, int, int]] = BACKTEST_PRESETS,
    transaction_cost_pct: float = 0.0,
) -> dict[str, dict]:
    return {
        label: run_ma_crossover_backtest(
            prices,
            short_window=short_window,
            long_window=long_window,
            transaction_cost_pct=transaction_cost_pct,
        )
        for label, short_window, long_window in presets
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_backtest.py -v`
Expected: PASS（4件とも成功）

- [ ] **Step 5: Commit**

```bash
git add portfolio_management/backtest.py tests/test_backtest.py
git commit -m "feat: add short/standard MA parameter-set comparison"
```

---

### Task 3: LLM解説プロンプトの生成

**Files:**
- Create: `prompt_patterns/backtest_explanation.py`
- Test: `tests/test_backtest_explanation.py`

**Interfaces:**
- Produces: `build_backtest_prompt(ticker: str, comparison: dict[str, dict]) -> str`

- [ ] **Step 1: Write the failing tests**

`tests/test_backtest_explanation.py` を作成する:

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_backtest_explanation.py -v`
Expected: FAIL（`ModuleNotFoundError`: `prompt_patterns.backtest_explanation` が存在しない）

- [ ] **Step 3: Write minimal implementation**

`prompt_patterns/backtest_explanation.py` を作成する:

```python
import json

from common.disclaimer import DISCLAIMER_NOTICE


def build_backtest_prompt(ticker: str, comparison: dict[str, dict]) -> str:
    comparison_json = json.dumps(comparison, ensure_ascii=False, indent=2, default=str)
    return (
        "以下は移動平均クロスオーバー戦略のバックテスト結果です"
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_backtest_explanation.py -v`
Expected: PASS（2件とも成功）

- [ ] **Step 5: Commit**

```bash
git add prompt_patterns/backtest_explanation.py tests/test_backtest_explanation.py
git commit -m "feat: add backtest explanation prompt builder"
```

---

### Task 4: 計算・プロンプト・LLM呼び出しの統合（`generate_backtest_explanation`）

**Files:**
- Modify: `portfolio_management/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes:
  - Task 2の `run_backtest_comparison(prices, presets, transaction_cost_pct) -> dict[str, dict]` と `BACKTEST_PRESETS`
  - Task 3の `build_backtest_prompt(ticker, comparison) -> str`
  - `data_api.llm_client.call_llm(prompt: str, timeout: int = 120) -> str`（デフォルト実装）
  - `common.disclaimer.DISCLAIMER_NOTICE`
- Produces: `generate_backtest_explanation(ticker: str, prices: pd.Series, presets: list[tuple[str, int, int]] = BACKTEST_PRESETS, transaction_cost_pct: float = 0.0, call_llm=default_call_llm) -> str`

- [ ] **Step 1: Write the failing tests**

`tests/test_backtest.py` の末尾に追加する（`from portfolio_management.backtest import generate_backtest_explanation` と `from common.disclaimer import DISCLAIMER_NOTICE` を先頭のimportに追加する）:

```python
def test_generate_backtest_explanation_includes_disclaimer_and_commentary():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.Series([100, 100, 102, 102], index=dates)
    fake_call_llm = lambda prompt: "テスト用のバックテスト解説です。"

    result = generate_backtest_explanation(
        "AAA.T", prices, presets=[("A", 1, 2)], call_llm=fake_call_llm
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
        "AAA.T", prices, presets=[("A", 1, 2)], call_llm=fake_call_llm
    )

    assert "AAA.T" in captured_prompts[0]
    assert '"A"' in captured_prompts[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_backtest.py -v`
Expected: FAIL（`ImportError`: `generate_backtest_explanation` が存在しない）

- [ ] **Step 3: Write minimal implementation**

`portfolio_management/backtest.py` の先頭のimportに以下を追加する:

```python
from common.disclaimer import DISCLAIMER_NOTICE
from data_api.llm_client import call_llm as default_call_llm
from prompt_patterns.backtest_explanation import build_backtest_prompt
```

ファイル末尾に追加する:

```python
def generate_backtest_explanation(
    ticker: str,
    prices: pd.Series,
    presets: list[tuple[str, int, int]] = BACKTEST_PRESETS,
    transaction_cost_pct: float = 0.0,
    call_llm=default_call_llm,
) -> str:
    comparison = run_backtest_comparison(prices, presets, transaction_cost_pct)
    prompt = build_backtest_prompt(ticker, comparison)
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

Run: `uv run pytest tests/test_backtest.py -v`
Expected: PASS（6件とも成功）

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -v`
Expected: PASS（既存テストを含め全件成功。他モジュールに影響がないことを確認する）

- [ ] **Step 6: Commit**

```bash
git add portfolio_management/backtest.py tests/test_backtest.py
git commit -m "feat: integrate backtest calculation with LLM explanation"
```

---

### Task 5: Streamlit「バックテスト」タブの追加とREADME更新

**Files:**
- Modify: `app.py`
- Modify: `README.md`

**Interfaces:**
- Consumes:
  - Task 2の `BACKTEST_PRESETS`, `run_backtest_comparison`
  - Task 4の `generate_backtest_explanation`
  - 既存の `data_api.stock_price_api.fetch_price_history(ticker_symbol, period) -> pd.DataFrame`
  - 既存の `common.cache.read_cache(cache_dir, key) -> str | None` / `write_cache(cache_dir, key, content) -> None`
  - 既存のモジュールレベル定数 `CACHE_DIR`（`app.py` 内で定義済み）

- [ ] **Step 1: `app.py` のimportにバックテスト関連を追加する**

`app.py` の既存importブロック（`from portfolio_management.review import generate_portfolio_review` の下）に追加する:

```python
from portfolio_management.backtest import (
    BACKTEST_PRESETS,
    generate_backtest_explanation,
    run_backtest_comparison,
)
```

- [ ] **Step 2: タブ構成を3つに変更する**

`app.py` の以下の行を:

```python
tab_portfolio, tab_screening = st.tabs(["ポートフォリオ", "スクリーニング"])
```

以下に置き換える:

```python
tab_portfolio, tab_screening, tab_backtest = st.tabs(
    ["ポートフォリオ", "スクリーニング", "バックテスト"]
)
```

- [ ] **Step 3: 「バックテスト」タブの中身を追加する**

`with tab_screening:` ブロックの末尾（ファイル末尾）に追加する:

```python
with tab_backtest:
    st.header("移動平均クロスオーバー戦略のバックテスト")

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
        transaction_cost_pct = 0.1 if apply_transaction_cost else 0.0
        history = fetch_price_history(backtest_ticker, period=backtest_period)
        min_required_days = max(long_window for _, _, long_window in BACKTEST_PRESETS)

        if history.empty or len(history) < min_required_days:
            st.error(
                "株価データが取得できないか、バックテストに必要な日数"
                f"（{min_required_days}日）に満たないため実行できません。"
            )
        else:
            prices = history["Close"]

            comparison = run_backtest_comparison(
                prices, transaction_cost_pct=transaction_cost_pct
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
                f"{backtest_ticker}-{backtest_period}-{transaction_cost_pct}".encode("utf-8")
            ).hexdigest()[:12]
            cached_explanation = (
                None if backtest_force_regenerate else read_cache(CACHE_DIR, cache_key)
            )

            if cached_explanation is not None:
                explanation = cached_explanation
            else:
                explanation = generate_backtest_explanation(
                    backtest_ticker, prices, transaction_cost_pct=transaction_cost_pct
                )
                write_cache(CACHE_DIR, cache_key, explanation)

            st.markdown(explanation)
```

- [ ] **Step 4: 全テストを実行して既存機能に影響がないことを確認する**

Run: `uv run pytest -v`
Expected: PASS（全件成功。`app.py` はimport可能なpythonファイルとしての構文チェックのみ対象、UIロジック自体はpytest対象外）

- [ ] **Step 5: Streamlitアプリを起動して手動確認する**

Run: `uv run streamlit run app.py`

確認項目:
- 「バックテスト」タブが表示される
- 実在する銘柄コード（例: `7203.T`）を入力し「バックテストを実行」を押すと、比較テーブル（短期(5/25)・標準(25/75)の2行）が表示される
- 「取引コストを考慮する」チェックボックスのON/OFFで累積リターンの数値が変化する
- LLM解説文が表示され、免責事項が含まれる
- 未入力の銘柄コードや存在しない銘柄コードでエラーメッセージが表示される（クラッシュしない）
- 確認後、動作結果を一言メモしておく（後続のレビューで参照するため）

- [ ] **Step 6: README.mdの「機能」に説明を追加する**

`README.md` の以下の行:

```markdown
- **スクリーニング**タブ: 自然言語の条件（例:「PERが15倍以下で配当利回りが3%以上」）を入力すると、主要銘柄（[screening/universe.py](screening/universe.py)、44銘柄）の中から条件に合う銘柄を絞り込みます。AIが解釈した条件は適用前に必ず画面で確認できます。
```

の直後に追加する:

```markdown
- **バックテスト**タブ: 銘柄コードを入力すると、移動平均クロスオーバー戦略を「短期(5/25)」「標準(25/75)」の2パラメータ組でベクトル化バックテストし、累積リターン・ベンチマーク（Buy&Hold）・勝率・最大ドローダウンを比較表示します。取引コスト（1回あたり0.1%）を考慮した計算にも対応し、AIによる結果解説（過学習・取引コスト未考慮などバックテストの限界への注意喚起を含む）を表示します。
```

- [ ] **Step 7: Commit**

```bash
git add app.py README.md
git commit -m "feat: add backtest tab to the Streamlit app"
```

---

## Self-Review Notes

- **Spec coverage:** 取引コスト計算（Task 1）、2パラメータ組比較（Task 2）、プロンプト設計要件5点＋指示的表現禁止（Task 3）、統合関数＋免責事項ラップ（Task 4）、UI・キャッシュ・エラーハンドリング・README（Task 5）を全てカバーしている。
- **Type consistency:** `run_ma_crossover_backtest` の戻り値キー名（`total_return_pct` 等）を Task 2〜5 まで一貫して使用している。`presets: list[tuple[str, int, int]]` の型もTask 2で定義したものをTask 4・5で踏襲している。
- **Placeholder scan:** 各Stepに実行可能なコード・具体的なアサーション・実コマンドを記載済み。「TBD」「後で実装」等の記述なし。
