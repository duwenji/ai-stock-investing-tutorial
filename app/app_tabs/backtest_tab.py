"""バックテストタブ: 単一銘柄・単一戦略のバックテスト実行。"""

import hashlib

import pandas as pd
import streamlit as st

from common.cache import read_cache, write_cache
from portfolio_management.backtest import (
    STRATEGIES,
    generate_backtest_explanation,
    run_backtest_comparison,
)

from app_tabs.shared import CACHE_DIR, cached_fetch_price_history


def render_backtest_tab() -> None:
    st.header("バックテスト")

    # 単一銘柄・単一戦略に対するバックテスト条件の入力
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
        history = cached_fetch_price_history(backtest_ticker, backtest_period)

        # 戦略が要求する最低データ日数を満たさない場合は実行できない旨を伝える
        if history.empty or len(history) < strategy["min_days"]:
            st.error(
                "株価データが取得できないか、バックテストに必要な日数"
                f"（{strategy['min_days']}日）に満たないため実行できません。"
            )
        else:
            prices = history["Close"]

            # 戦略のプリセットパラメータごとに成績を比較する
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

            # バックテスト条件（戦略・銘柄・期間・コスト）が同一ならAI解説をキャッシュ再利用する
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
