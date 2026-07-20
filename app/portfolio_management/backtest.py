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
