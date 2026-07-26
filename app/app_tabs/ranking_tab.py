"""一括バックテストタブ: ユニバース銘柄+保有銘柄を対象にした戦略ランキング。"""

import hashlib
import json
import logging

import pandas as pd
import streamlit as st

from common.cache import read_cache, write_cache
from common.concurrency import map_concurrently
from common.disclaimer import DISCLAIMER_NOTICE
from common.logging_config import log_duration
from data_api.llm_client import call_llm
from portfolio_management.backtest import STRATEGIES, run_universe_backtest_ranking
from portfolio_management.storage import load_holdings
from portfolio_management.ticker_names import build_candidate_names
from prompt_patterns.backtest_explanation import generate_ranking_comments
from screening.universe import UNIVERSE

from app_tabs.shared import (
    CACHE_DIR,
    HOLDINGS_PATH,
    cached_fetch_japanese_name,
    cached_fetch_price_history,
    handle_table_selection,
)

logger = logging.getLogger(__name__)


def render_ranking_tab() -> None:
    logger.info("一括バックテストタブを表示")
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

        # 分析対象はユニバース銘柄と保有銘柄の和集合とする
        holdings = load_holdings(HOLDINGS_PATH)
        holdings_tickers = [h["ticker"] for h in holdings if h.get("ticker")]
        target_tickers = sorted(set(UNIVERSE) | set(holdings_tickers))

        # 戦略・期間・コスト・対象銘柄集合が同一なら結果をキャッシュから再利用する
        cache_key = "universe-backtest-" + hashlib.sha256(
            f"{ranking_strategy}-{ranking_period}-{transaction_cost_pct}-"
            f"{'-'.join(target_tickers)}".encode("utf-8")
        ).hexdigest()[:12]
        cached_payload = None if ranking_force_regenerate else read_cache(CACHE_DIR, cache_key)

        payload = json.loads(cached_payload) if cached_payload is not None else None

        if payload is None:
            with log_duration(
                logger, f"一括バックテスト実行（{ranking_strategy}, {len(target_tickers)}銘柄）"
            ):
                prices_by_ticker = {}
                skipped_tickers = []
                # 多数の銘柄の株価取得を並列化して待ち時間を短縮する
                with st.spinner(f"株価データを取得中...（{len(target_tickers)}銘柄）"):
                    price_results = map_concurrently(
                        target_tickers,
                        lambda ticker: cached_fetch_price_history(ticker, ranking_period),
                    )
                # データ取得に失敗・不足した銘柄はランキング対象から除外し、後で案内する
                for ticker in target_tickers:
                    history = price_results[ticker]
                    if isinstance(history, Exception) or history is None or history.empty:
                        skipped_tickers.append(ticker)
                    else:
                        prices_by_ticker[ticker] = history["Close"]

                if not prices_by_ticker:
                    logger.warning("一括バックテスト実行不可（対象銘柄が0件）")
                    st.error("バックテスト可能な銘柄がありませんでした。")
                    payload = None
                else:
                    # 標準プリセット（先頭のパラメータ組）で全銘柄を横並び比較しランキング化する
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
            # 再実行後もランキング結果を表示し続けられるようセッションに保持する
            st.session_state["ranking_payload"] = payload
            st.session_state["ranking_strategy_label"] = ranking_strategy
            st.session_state["ranking_selected_row"] = None
            st.session_state["ranking_table"] = {"selection": {"rows": [], "columns": []}}

    if st.session_state.get("ranking_payload") is not None:
        payload = st.session_state["ranking_payload"]
        ranking_strategy_label = st.session_state["ranking_strategy_label"]

        candidate_names = build_candidate_names(
            load_holdings(HOLDINGS_PATH), resolve_name=cached_fetch_japanese_name
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

        st.subheader(f"{ranking_strategy_label}（{payload['preset_label']}）ランキング")
        st.caption("行をクリックすると銘柄詳細を表示します。")
        event = st.dataframe(
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
            on_select="rerun",
            selection_mode="single-row",
            key="ranking_table",
        )
        handle_table_selection("ranking_selected_row", event, ranking_df)

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
