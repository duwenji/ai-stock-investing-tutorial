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


def _detect_recent_cross(
    fast: pd.Series, slow: pd.Series, direction: str = "up", within_days: int = 5,
) -> bool:
    """2系列が直近within_days営業日以内に交差したかを判定する。系列長が
    within_days+1に満たない場合はFalseを返す。ローリング窓の未成熟期間
    （fast/slowの先頭側のNaN）はfast > slow等の比較が自然にFalseになるため
    誤ったクロス検出にはならず、別途NaNチェックは不要。"""
    if len(fast) < within_days + 1:
        return False
    is_above = fast > slow
    # shift(1)はbool Seriesの先頭にNaNを挿入するためdtypeがobjectに昇格し、
    # そのまま~を適用するとPythonのbool（int扱い）へのビット反転（~True=-2等、
    # どちらも真値扱いになる）になってしまい論理否定にならない。astype(bool)で
    # 明示的にbool dtypeへ戻してから~を適用する。
    prev_above = is_above.shift(1).fillna(False).astype(bool)
    crossed_up = is_above & ~prev_above
    crossed_down = ~is_above & prev_above
    recent = crossed_up if direction == "up" else crossed_down
    return bool(recent.iloc[-within_days:].any())


def _detect_recent_threshold_cross(
    series: pd.Series, threshold: float, direction: str = "up", within_days: int = 5,
) -> bool:
    """1系列が直近within_days営業日以内に閾値を上抜け/下抜けしたかを判定する。"""
    is_above = series >= threshold if direction == "up" else series <= threshold
    prev_above = is_above.shift(1).fillna(False).astype(bool)
    crossed = is_above & ~prev_above
    return bool(crossed.iloc[-within_days:].any())


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
