"""複数のテクニカル戦略（MA・RSI・MACD・ボリンジャーバンド）を対象に、
過去の株価系列でベクトル化バックテストを実行し、成績指標やLLMによる
解説文を生成するモジュール。"""

import logging

import pandas as pd

from common.disclaimer import DISCLAIMER_NOTICE
from common.logging_config import log_duration
from data_api.llm_client import call_llm as default_call_llm
from prompt_patterns.backtest_explanation import build_backtest_prompt

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


# 画面（UI）に表示する戦略の一覧。各戦略の実行関数・プリセットパラメータ・
# バックテストに最低限必要な日数（min_days）を紐付けて管理する。
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
    """同一戦略の複数プリセット（パラメータ設定）でバックテストを実行し、
    プリセット名ごとの成績を比較できる形でまとめる。"""
    with log_duration(logger, f"バックテスト比較計算（プリセット{len(presets)}件）"):
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
    """バックテスト結果をLLMに渡し、投資家向けの解説レポート（Markdown）を
    生成する。免責事項を先頭と末尾に必ず付与する。"""
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


def run_universe_backtest_ranking(
    prices_by_ticker: dict[str, pd.Series],
    backtest_func,
    preset_params: dict,
    transaction_cost_pct: float = 0.0,
    min_days: int = 0,
) -> list[dict]:
    """銘柄ユニバース全体に同一戦略・同一パラメータでバックテストを行い、
    リスク調整後リターン（収益率÷最大ドローダウン）でランキングする。"""
    with log_duration(logger, f"ユニバース一括バックテスト（{len(prices_by_ticker)}銘柄）"):
        rows = []
        for ticker, prices in prices_by_ticker.items():
            # データ期間が短すぎる銘柄は戦略が機能しないため除外する。
            if len(prices) < min_days:
                continue
            result = backtest_func(
                prices, transaction_cost_pct=transaction_cost_pct, **preset_params
            )
            drawdown = abs(result["max_drawdown_pct"])
            # ドローダウンが0の場合はゼロ除算を避け、収益率をそのまま指標とする。
            risk_adjusted_return = (
                result["total_return_pct"] / drawdown if drawdown else result["total_return_pct"]
            )
            rows.append(
                {
                    "ticker": ticker,
                    **result,
                    "risk_adjusted_return": round(risk_adjusted_return, 2),
                }
            )
        return sorted(rows, key=lambda row: row["risk_adjusted_return"], reverse=True)
