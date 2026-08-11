"""AI戦略ビルダーのAI対話が生成するstepsから呼び出される、再利用可能な
スクリーニング/ランキング関数のレジストリ。各関数は
(candidates_df: pd.DataFrame, params: dict, cache_dir) -> pd.DataFrame
という統一シグネチャを持つ。"""

import json

import pandas as pd

from common.cache import read_cache, write_cache
from data_api.stock_price_api import (
    fetch_universe_fundamentals,
    fetch_universe_price_histories,
    load_all_company_profiles,
)
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
