"""複数のテクニカル戦略（MA・RSI・MACD・ボリンジャーバンド）を対象に、
過去の株価系列でベクトル化バックテストを実行し、成績指標やLLMによる
解説文を生成するモジュール。"""

import logging
import statistics
from concurrent.futures import ThreadPoolExecutor
from itertools import product

import pandas as pd

from common.disclaimer import DISCLAIMER_NOTICE
from common.logging_config import log_duration
from data_api.llm_client import call_llm as default_call_llm
from prompt_patterns.backtest_explanation import build_backtest_prompt, build_improvement_prompt

logger = logging.getLogger(__name__)


def _finalize_backtest(prices: pd.Series, position: pd.Series, transaction_cost_pct: float) -> dict:
    """ポジション系列（0/1）から損益・勝率・最大ドローダウン等の
    共通の成績指標を算出する。各戦略関数から共通利用される集計処理。"""
    daily_return = prices.pct_change().fillna(0)
    strategy_return = position * daily_return

    if transaction_cost_pct:
        # ポジションが変化した日（売買が発生した日）にのみ取引コストを差し引く。
        position_changed = position.diff().fillna(0) != 0
        cost = transaction_cost_pct / 100
        strategy_return = strategy_return - position_changed.astype(int) * cost

    benchmark_return = daily_return  # Buy & Hold

    # 日次リターンを複利で累積し、戦略とベンチマークの累積収益率を求める。
    cum_strategy = (1 + strategy_return).cumprod() - 1
    cum_benchmark = (1 + benchmark_return).cumprod() - 1

    # ポジションを保有していた日のみを対象に勝率を計算する。
    trade_days = position[position != 0].index
    win_rate = (strategy_return.loc[trade_days] > 0).mean() if len(trade_days) else 0.0

    # 累積収益の直近ピークからの下落率（ドローダウン）の最大値を求める。
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


def _risk_adjusted_return(result: dict) -> float:
    """収益率をリスク（最大ドローダウン）で調整した値を返す。
    ドローダウンが0の場合はゼロ除算を避け、収益率をそのまま返す。"""
    drawdown = abs(result["max_drawdown_pct"])
    risk_adjusted = result["total_return_pct"] / drawdown if drawdown else result["total_return_pct"]
    return round(risk_adjusted, 2)


def _run_grid_combinations(
    prices: pd.Series,
    backtest_func,
    keys: list[str],
    combos: list[tuple],
    fixed_params: dict,
    transaction_cost_pct: float,
) -> list[dict]:
    """param_gridの組み合わせ（あらかじめ計算済みのデカルト積）ごとにバックテストを
    実行する内部処理。ログ出力は呼び出し元（run_grid_search / run_universe_backtest_ranking）
    の責務とし、この関数自体はログを出さない（一括バックテストで銘柄数だけ呼ばれても
    ログが大量出力されないようにするため）。"""
    grid_results = []
    for combo in combos:
        params = dict(zip(keys, combo))
        result = backtest_func(
            prices, transaction_cost_pct=transaction_cost_pct, **params, **fixed_params
        )
        grid_results.append(
            {
                "params": params,
                **result,
                "risk_adjusted_return": _risk_adjusted_return(result),
            }
        )
    return grid_results


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


def run_rsi_reversal_backtest(
    prices: pd.Series,
    period: int = 14,
    oversold: int = 30,
    overbought: int = 70,
    transaction_cost_pct: float = 0.0,
) -> dict:
    """RSI逆張り戦略をベクトル化してバックテストする。"""
    # 値上がり幅と値下がり幅を分離し、それぞれの移動平均比からRSIを算出する。
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

    # エントリー/エグジットのシグナルが立った日以降、次のシグナルが
    # 出るまでポジションを保持し続けるために前方補完（ffill）する。
    raw_position = pd.Series(index=prices.index, dtype=float)
    raw_position[entry] = 1.0
    raw_position[exit_signal] = 0.0
    held_position = raw_position.ffill().fillna(0)

    # シグナル発生日の終値ではなく翌日約定とするため1日ずらす
    # （ルックアヘッドバイアス回避）。
    position = held_position.shift(1).fillna(0)

    return _finalize_backtest(prices, position, transaction_cost_pct)


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

    # エントリー/エグジットのシグナルが立った日以降、次のシグナルが
    # 出るまでポジションを保持し続けるために前方補完（ffill）する。
    raw_position = pd.Series(index=prices.index, dtype=float)
    raw_position[entry] = 1.0
    raw_position[exit_signal] = 0.0
    held_position = raw_position.ffill().fillna(0)

    # シグナル発生日の終値ではなく翌日約定とするため1日ずらす
    # （ルックアヘッドバイアス回避）。
    position = held_position.shift(1).fillna(0)

    return _finalize_backtest(prices, position, transaction_cost_pct)


def run_grid_search(
    prices: pd.Series,
    backtest_func,
    param_grid: dict,
    fixed_params: dict | None = None,
    transaction_cost_pct: float = 0.0,
) -> list[dict]:
    """param_gridの全組み合わせ（デカルト積）でバックテストを実行し、
    組み合わせごとのパラメータ・成績・リスク調整済みリターンをまとめて返す。"""
    fixed_params = fixed_params or {}
    keys = list(param_grid.keys())
    combos = list(product(*(list(param_grid[key]) for key in keys)))
    with log_duration(logger, f"グリッドサーチ計算（{len(combos)}通り）"):
        return _run_grid_combinations(
            prices, backtest_func, keys, combos, fixed_params, transaction_cost_pct
        )


def summarize_grid_stability(grid_results: list[dict]) -> dict:
    """グリッド全体のリスク調整済みリターンから、最良・最悪の組み合わせと
    近傍全体の安定性（変動係数）を求める。"""
    returns = [row["risk_adjusted_return"] for row in grid_results]
    best = max(grid_results, key=lambda row: row["risk_adjusted_return"])
    worst = min(grid_results, key=lambda row: row["risk_adjusted_return"])

    mean = statistics.mean(returns)
    # 母集団（グリッド全体）のばらつきを見るため、標本標準偏差ではなく母標準偏差を使う。
    stdev = statistics.pstdev(returns)
    if abs(mean) < 1e-6:
        cv = None
        is_stable = False
    else:
        cv = round(abs(stdev / mean), 4)
        is_stable = cv < 0.5

    return {
        "best": best,
        "worst": worst,
        "cv": cv,
        "is_stable": is_stable,
        "grid_size": len(grid_results),
    }


# 画面（UI）に表示する戦略の一覧。各戦略の実行関数・グリッドサーチの探索範囲・
# バックテストに最低限必要な日数（min_days）を紐付けて管理する。
# param_gridは近傍グリッドサーチで探索する2軸パラメータ。fixed_paramsは
# 3パラメータ戦略（RSI・MACD）で探索対象外として固定する値。
STRATEGIES: dict[str, dict] = {
    "移動平均クロスオーバー": {
        "func": run_ma_crossover_backtest,
        "param_grid": {"short_window": range(20, 31, 2), "long_window": range(65, 86, 5)},
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
        "param_grid": {"fast": range(8, 15, 2), "slow": range(20, 31, 2)},
        "fixed_params": {"signal": 9},
        "min_days": 30,
    },
    "ボリンジャーバンド逆張り": {
        "func": run_bollinger_reversal_backtest,
        "param_grid": {"window": range(15, 26, 2), "num_std": [1.5, 1.75, 2.0, 2.25, 2.5]},
        "min_days": 25,
    },
}


def _format_params(params: dict) -> str:
    return ", ".join(f"{key}={value}" for key, value in params.items())


def generate_backtest_explanation(
    ticker: str,
    grid_results: list[dict],
    strategy_name: str = "移動平均クロスオーバー",
    call_llm=default_call_llm,
) -> str:
    """グリッドサーチ結果をLLMに渡し、投資家向けの解説レポート（Markdown）を
    生成する。免責事項を先頭と末尾に必ず付与する。

    Prompt Chaining: Step1で結果解説を生成し、その出力をgate（空文字チェック）
    で検証したうえで、Step2でStep1の解説を踏まえた改善提案を生成する。
    Step1が空文字の場合はStep2に進まずエラーメッセージを返す。Step2が
    空文字の場合は改善提案セクションを省略し、Step1の結果のみ返す。
    """
    summary = summarize_grid_stability(grid_results)
    best, worst = summary["best"], summary["worst"]
    comparison = {
        f"最良（{_format_params(best['params'])}）": {
            key: value for key, value in best.items() if key != "params"
        },
        f"近傍最悪（{_format_params(worst['params'])}）": {
            key: value for key, value in worst.items() if key != "params"
        },
    }
    stability = {
        "cv": summary["cv"],
        "is_stable": summary["is_stable"],
        "grid_size": summary["grid_size"],
    }

    # Step1: 結果解説
    explanation = call_llm(
        build_backtest_prompt(ticker, comparison, stability, strategy_name)
    ).strip()
    if not explanation:
        return "解説の生成に失敗しました。"

    sections = [
        DISCLAIMER_NOTICE,
        "",
        f"# バックテスト結果解説（{ticker}）",
        "",
        explanation,
    ]

    # Step2: 改善提案（Step1の解説を入力として渡す）
    improvement_prompt = build_improvement_prompt(
        ticker, comparison, explanation, stability, strategy_name
    )
    improvement = call_llm(improvement_prompt).strip()
    if improvement:
        sections += [
            "",
            "## 追加で検討したい観点",
            "",
            improvement,
        ]

    sections += [
        "",
        "---",
        "",
        DISCLAIMER_NOTICE,
    ]
    return "\n".join(sections)


def run_universe_backtest_ranking(
    prices_by_ticker: dict[str, pd.Series],
    backtest_func,
    param_grid: dict,
    fixed_params: dict | None = None,
    transaction_cost_pct: float = 0.0,
    min_days: int = 0,
    max_workers: int = 8,
) -> list[dict]:
    """銘柄ユニバース全体に対し、銘柄ごとに近傍グリッドサーチで最良パラメータを
    探索し、そのリスク調整後リターン（収益率÷最大ドローダウン）でランキングする。
    銘柄ごとの計算はCPUバウンドなベクトル化演算（pandas/numpy）のため、
    スレッド並列でも一定の高速化が見込める。"""
    fixed_params = fixed_params or {}
    keys = list(param_grid.keys())
    combos = list(product(*(list(param_grid[key]) for key in keys)))

    def _rank_one(item: tuple[str, pd.Series]) -> dict | None:
        ticker, prices = item
        if len(prices) < min_days:
            return None
        try:
            grid_results = _run_grid_combinations(
                prices, backtest_func, keys, combos, fixed_params, transaction_cost_pct
            )
        except Exception:
            logger.exception("銘柄 %s のグリッドサーチに失敗したためスキップします", ticker)
            return None
        summary = summarize_grid_stability(grid_results)
        best = summary["best"]
        return {
            "ticker": ticker,
            "total_return_pct": best["total_return_pct"],
            "benchmark_return_pct": best["benchmark_return_pct"],
            "win_rate_pct": best["win_rate_pct"],
            "max_drawdown_pct": best["max_drawdown_pct"],
            "trade_days": best["trade_days"],
            "risk_adjusted_return": best["risk_adjusted_return"],
            "best_params": best["params"],
            "stability_cv": summary["cv"],
            "is_stable": summary["is_stable"],
        }

    with log_duration(logger, f"ユニバース一括バックテスト（{len(prices_by_ticker)}銘柄）"):
        rows = []
        worker_count = min(max_workers, len(prices_by_ticker) or 1)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            for row in executor.map(_rank_one, prices_by_ticker.items()):
                if row is not None:
                    rows.append(row)
        return sorted(rows, key=lambda row: row["risk_adjusted_return"], reverse=True)
