"""AI戦略ビルダーの簡易バックテスト: 現在の財務指標で選定した銘柄群を、
過去に遡って均等金額で購入・保有し続けた場合の資産推移をシミュレーションする。

過去の各時点で同条件を満たしていたかは考慮しないため、ルックアヘッド
バイアスを含む簡易シミュレーションである（詳細は設計書を参照）。
"""

import logging

import pandas as pd

from common.logging_config import log_duration

logger = logging.getLogger(__name__)


def run_strategy_backtest(prices_by_ticker: dict[str, pd.Series]) -> dict:
    """各銘柄の株価をその銘柄自身の開始日=100に正規化し、日次で銘柄平均を
    とった「等金額購入・保有」の資産推移から、累積リターン・最大ドローダウン・
    勝率を算出する。

    勝率は「期間トータルリターンがプラスだった銘柄数の割合」と定義する
    （買い持ち戦略にはポジション0/1の概念がないため、単一銘柄・テクニカル
    戦略向けの portfolio_management.backtest._finalize_backtest とは
    勝率の定義が異なる）。

    銘柄によって株価データの開始日が異なる場合（新規上場等）は、共通の
    日付インデックスのunion上でNaNを許容し、平均計算はskipnaで行う。

    prices_by_tickerが空、または全銘柄が2営業日未満のデータしか
    持たない場合は空の結果（equity_curveが空のSeries）を返す。
    """
    with log_duration(logger, f"戦略バックテスト計算（{len(prices_by_ticker)}銘柄）"):
        normalized_series = {}
        ticker_returns: dict[str, float] = {}
        for ticker, prices in prices_by_ticker.items():
            valid = prices.dropna()
            if len(valid) < 2:
                continue
            start = valid.iloc[0]
            if start == 0:
                continue
            normalized_series[ticker] = prices / start * 100
            ticker_returns[ticker] = round((valid.iloc[-1] / start - 1) * 100, 2)

        if not normalized_series:
            return {
                "total_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "win_rate_pct": 0.0,
                "equity_curve": pd.Series(dtype=float),
                "ticker_returns": {},
            }

        combined = pd.concat(normalized_series.values(), axis=1)
        equity_curve = combined.mean(axis=1, skipna=True).dropna()

        total_return_pct = round(
            (equity_curve.iloc[-1] / equity_curve.iloc[0] - 1) * 100, 2
        )
        running_max = equity_curve.cummax()
        drawdown = equity_curve / running_max - 1
        max_drawdown_pct = round(drawdown.min() * 100, 2)
        win_rate_pct = round(
            sum(1 for r in ticker_returns.values() if r > 0)
            / len(ticker_returns)
            * 100,
            2,
        )

        return {
            "total_return_pct": total_return_pct,
            "max_drawdown_pct": max_drawdown_pct,
            "win_rate_pct": win_rate_pct,
            "equity_curve": equity_curve,
            "ticker_returns": ticker_returns,
        }
