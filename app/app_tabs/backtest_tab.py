"""バックテストタブ: 単一銘柄・単一戦略のバックテスト実行。"""

import hashlib
import logging

import altair as alt
import pandas as pd
import streamlit as st

from common.cache import read_cache, write_cache
from common.logging_config import log_duration
from portfolio_management.backtest import (
    STRATEGIES,
    generate_backtest_explanation,
    run_grid_search,
    summarize_grid_stability,
)

from app_tabs.shared import CACHE_DIR, cached_fetch_price_history

logger = logging.getLogger(__name__)


def _render_grid_heatmap(grid_results: list[dict], param_grid: dict) -> None:
    x_key, y_key = list(param_grid.keys())
    grid_df = pd.DataFrame(
        [
            {
                x_key: row["params"][x_key],
                y_key: row["params"][y_key],
                "risk_adjusted_return": row["risk_adjusted_return"],
                "total_return_pct": row["total_return_pct"],
                "win_rate_pct": row["win_rate_pct"],
                "max_drawdown_pct": row["max_drawdown_pct"],
            }
            for row in grid_results
        ]
    )
    # altairのChartオブジェクトを組み立てるだけではまだ画面に表示されない。
    # 呼び出し元でst.altair_chart()に渡して初めてStreamlit上に描画される。
    heatmap = (
        alt.Chart(grid_df)
        .mark_rect()
        .encode(
            x=alt.X(f"{x_key}:O", title=x_key),
            y=alt.Y(f"{y_key}:O", title=y_key),
            color=alt.Color("risk_adjusted_return:Q", title="リスク調整済みリターン"),
            tooltip=[
                x_key,
                y_key,
                "risk_adjusted_return",
                "total_return_pct",
                "win_rate_pct",
                "max_drawdown_pct",
            ],
        )
    )
    st.altair_chart(heatmap, width="stretch")


def _render_stability_summary(summary: dict) -> None:
    best = summary["best"]
    st.subheader("近傍グリッドサーチ・安定性チェック")
    # st.columns(3)で3分割したコンテナのリストを受け取り、各要素に.metric()を
    # 呼ぶことで数値を横並びのカードのように強調表示する。
    metric_cols = st.columns(3)
    metric_cols[0].metric("最良パラメータの累積リターン(%)", best["total_return_pct"])
    metric_cols[1].metric("最良パラメータの最大DD(%)", best["max_drawdown_pct"])
    metric_cols[2].metric("グリッド件数", summary["grid_size"])

    best_params_text = "、".join(f"{key}={value}" for key, value in best["params"].items())
    st.caption(f"最良パラメータ: {best_params_text}")

    if summary["cv"] is None:
        st.info("グリッド全体の平均成績が0近傍のため、安定性を判定できませんでした。")
    elif summary["is_stable"]:
        st.success(f"近傍グリッド内で結果は安定しています（変動係数={summary['cv']}）。")
    else:
        st.warning(
            "近傍グリッド内で結果のばらつきが大きく、過学習の可能性があります"
            f"（変動係数={summary['cv']}）。"
        )


def render_backtest_tab() -> None:
    logger.info("バックテストタブを表示")
    st.header("バックテスト")

    # 単一銘柄・単一戦略に対するバックテスト条件の入力
    # 各ウィジェットにkey=を指定するとst.session_state[key]に値が自動保存される。
    # そのため他のウィジェット操作でrerunが起きても、ユーザーが選んだ値はここで
    # 再取得され画面に維持される（keyを省略すると内部的に自動生成されたキーが使われる）。
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

    # st.buttonはクリックされて発生したrerunでのみTrueになる。ここではand式の右側に
    # 置くことで「銘柄コードが入力済み、かつ今このrerunでボタンが押された」場合だけ
    # 下のバックテスト処理を実行する。
    if backtest_ticker and st.button("バックテストを実行"):
        strategy = STRATEGIES[backtest_strategy]
        transaction_cost_pct = 0.1 if apply_transaction_cost else 0.0
        # cached_fetch_price_history（shared.py）は@st.cache_data付きなので、同じ銘柄・
        # 期間の組み合わせであれば実際のデータ取得は行わずキャッシュ済みの結果を返す。
        history = cached_fetch_price_history(backtest_ticker, backtest_period)

        # 戦略が要求する最低データ日数を満たさない場合は実行できない旨を伝える
        if history.empty or len(history) < strategy["min_days"]:
            logger.warning(
                "バックテスト実行不可（%s, データ日数不足または取得失敗）", backtest_ticker
            )
            st.error(
                "株価データが取得できないか、バックテストに必要な日数"
                f"（{strategy['min_days']}日）に満たないため実行できません。"
            )
        else:
            with log_duration(
                logger, f"バックテスト実行（{backtest_ticker}, {backtest_strategy}）"
            ):
                prices = history["Close"]

                grid_results = run_grid_search(
                    prices,
                    strategy["func"],
                    strategy["param_grid"],
                    strategy.get("fixed_params"),
                    transaction_cost_pct,
                )
                summary = summarize_grid_stability(grid_results)

                if "fixed_params" in strategy:
                    fixed_text = "、".join(
                        f"{key}={value}" for key, value in strategy["fixed_params"].items()
                    )
                    st.caption(f"以下のパラメータは近傍探索の対象外とし固定しています: {fixed_text}")

                st.subheader("パラメータ組み合わせのヒートマップ")
                _render_grid_heatmap(grid_results, strategy["param_grid"])
                _render_stability_summary(summary)

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
                        grid_results,
                        strategy_name=backtest_strategy,
                    )
                    write_cache(CACHE_DIR, cache_key, explanation)

                st.markdown(explanation)
