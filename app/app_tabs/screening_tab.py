"""スクリーニングタブ: 自然言語条件によるユニバース銘柄の絞り込み。"""

import json
import logging

import streamlit as st

from common.json_parsing import strip_code_fence
from common.logging_config import log_duration
from data_api.llm_client import call_llm
from data_api.stock_price_api import fetch_universe_fundamentals, load_all_company_profiles
from prompt_patterns.screening import (
    apply_filters,
    build_screening_prompt,
    generate_screening_comments,
)

from app_tabs.shared import handle_table_selection

logger = logging.getLogger(__name__)


def render_screening_tab() -> None:
    logger.info("スクリーニングタブを表示")
    st.header("銘柄スクリーニング")

    company_profiles = load_all_company_profiles()
    tickers = [p["ticker"] for p in company_profiles]
    names_by_ticker = {p["ticker"]: p["name"] for p in company_profiles if p["name"]}
    sector_jp_by_ticker = {
        p["ticker"]: p["sector_jp"] for p in company_profiles if p["sector_jp"]
    }

    condition_text = st.text_input(
        "スクリーニング条件を自然言語で入力してください",
        placeholder="PERが15倍以下で配当利回りが3%以上",
    )

    if condition_text:
        # 入力条件が前回から変わった場合のみLLMを呼び出し、自然言語条件を
        # 構造化フィルタ（JSON）に変換する。変わっていなければ結果をセッションから再利用する
        if st.session_state.get("screening_condition_text") != condition_text:
            prompt = build_screening_prompt(
                condition_text, sectors=sorted(set(sector_jp_by_ticker.values()))
            )
            raw_filters = call_llm(prompt)
            st.session_state["screening_condition_text"] = condition_text
            try:
                st.session_state["screening_filters"] = json.loads(strip_code_fence(raw_filters))
                st.session_state["screening_filters_error"] = False
            except json.JSONDecodeError:
                # LLMの出力が不正なJSONだった場合はエラーとして扱い、フィルタなしにする
                logger.warning("スクリーニング条件のJSON解析に失敗しました")
                st.session_state["screening_filters"] = None
                st.session_state["screening_filters_error"] = True

        filters = st.session_state.get("screening_filters")
        if st.session_state.get("screening_filters_error"):
            st.error("条件の解釈に失敗しました。条件を言い換えて再度お試しください。")

        if filters is not None:
            # 実際に適用する前にAIが解釈した条件をユーザーに確認させる
            st.subheader("AIが解釈した条件（適用前に確認してください）")
            st.json(filters)

            # 対象銘柄のファンダメンタルズを取得し、条件でフィルタしてAIコメントを付与する
            if st.button("この条件で絞り込む"):
                with log_duration(logger, "スクリーニング絞り込み実行"):
                    universe_df = fetch_universe_fundamentals(tickers)
                    universe_df["name"] = universe_df["ticker"].map(names_by_ticker).fillna(
                        universe_df["name"]
                    )
                    universe_df["sector"] = universe_df["ticker"].map(sector_jp_by_ticker)
                    result_df = apply_filters(universe_df, filters)
                    comments = generate_screening_comments(result_df, call_llm=call_llm)
                    # 時価総額は円単位だと桁が大きく読みにくいため、表示用に億円単位へ変換する
                    result_df = result_df.assign(market_cap=result_df["market_cap"] / 1e8)

                    st.session_state["screening_result_df"] = result_df
                    st.session_state["screening_comments"] = comments
                    st.session_state["screening_selected_row"] = None
                    st.session_state["screening_result_table"] = {
                        "selection": {"rows": [], "columns": []}
                    }

    # 絞り込み結果があれば、選択可能な一覧表と銘柄ごとのAIコメントを表示する
    if st.session_state.get("screening_result_df") is not None:
        result_df = st.session_state["screening_result_df"]
        comments = st.session_state["screening_comments"]

        st.subheader(f"絞り込み結果（{len(result_df)}件）")
        st.caption("行をクリックすると銘柄詳細を表示します。")
        event = st.dataframe(
            result_df,
            column_config={
                "ticker": st.column_config.TextColumn("銘柄コード"),
                "name": st.column_config.TextColumn("銘柄名"),
                "sector": st.column_config.TextColumn("業種"),
                "per": st.column_config.NumberColumn("PER"),
                "pbr": st.column_config.NumberColumn("PBR"),
                "dividend_yield_pct": st.column_config.NumberColumn("配当利回り(%)"),
                "market_cap": st.column_config.NumberColumn("時価総額(億円)", format="%.0f"),
            },
            on_select="rerun",
            selection_mode="single-row",
            key="screening_result_table",
        )
        handle_table_selection("screening_selected_row", event, result_df)

        st.subheader("銘柄ごとのAIコメント")
        for row in result_df.itertuples():
            st.write(
                f"**{row.ticker} {row.name}**: "
                f"{comments.get(row.ticker, 'コメント生成失敗')}"
            )
