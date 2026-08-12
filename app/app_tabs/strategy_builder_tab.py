"""AI戦略ビルダータブ: 投資アイデアの入力からAIとの対話によるロジック構築、
確定後のパイプライン実行（PIPELINE_FUNCTIONSベースのsteps）までを一気通貫で行う。
"""

import logging

import pandas as pd
import streamlit as st

from common.disclaimer import DISCLAIMER_NOTICE
from data_api.llm_client import call_llm
from data_api.stock_price_api import load_all_company_profiles
from prompt_patterns.strategy_dialogue import build_dialogue_prompt, parse_dialogue_response
from strategy_builder.evaluation import run_evaluation_loop
from strategy_builder.sector_insight import build_watchlist_from_rotation
from strategy_builder.storage import load_strategies, save_strategy

from app_tabs.shared import (
    CACHE_DIR,
    get_current_user_id,
    handle_table_selection,
    run_or_load_sector_rotation,
)
from strategy_builder.pipeline import run_pipeline

logger = logging.getLogger(__name__)

_TEMPLATES = {
    "バリュー株": "PERが低く、PBRも割安な銘柄に投資したい。",
    "グロース株": "売上高の伸び率が高く、将来性のある成長株に投資したい。",
    "配当株": "配当利回りが高く、安定した配当が期待できる銘柄に投資したい。",
}


def _render_sector_rotation_suggestion() -> None:
    with st.expander("業種ローテーションから本日の注目銘柄を提案"):
        sector_period = st.selectbox(
            "分析期間", ["1y", "2y"], key="strategy_sector_period"
        )
        sector_force_regenerate = st.checkbox(
            "キャッシュを無視して再生成する", key="strategy_sector_force_regenerate"
        )
        if st.button("今すぐ分析を実行", key="strategy_run_sector_rotation"):
            with st.spinner("業種ローテーション分析を実行中..."):
                payload = run_or_load_sector_rotation(sector_period, sector_force_regenerate)
            if payload is None:
                st.error("分析可能な銘柄がありませんでした。")

        payload = st.session_state.get("sector_payload")
        if payload is None:
            st.info(
                "上のボタンで分析を実行すると、本日の値上がり銘柄から"
                "注目業種・銘柄を提案します。"
            )
            return

        band_choice = st.selectbox(
            "周期帯",
            ["すべて（自動選択）", "短期", "中期", "長期"],
            key="strategy_watchlist_band",
        )
        band = None if band_choice == "すべて（自動選択）" else band_choice

        company_profiles = load_all_company_profiles()
        sector_jp_by_ticker = {
            p["ticker"]: p["sector_jp"] for p in company_profiles if p["sector_jp"]
        }
        names_by_ticker = {p["ticker"]: p["name"] for p in company_profiles if p["name"]}
        watchlist = build_watchlist_from_rotation(
            payload.get("ticker_latest_return_pct", {}),
            payload.get("network_pairs", []),
            sector_jp_by_ticker,
            names_by_ticker,
            band=band,
        )
        if watchlist["idea_text"] is None:
            st.info("十分な確信度を持つ業種間の関係が見つかりませんでした。")
            return

        st.write(watchlist["idea_text"])
        st.dataframe(
            pd.DataFrame(watchlist["candidates"]),
            column_config={
                "ticker": st.column_config.TextColumn("銘柄コード"),
                "name": st.column_config.TextColumn("銘柄名"),
                "sector": st.column_config.TextColumn("業種"),
                "leading_sector": st.column_config.TextColumn("先行業種"),
                "lag_days": st.column_config.NumberColumn("遅行日数"),
                "band": st.column_config.TextColumn("周期帯"),
            },
            hide_index=True,
        )
        if st.button("この案をアイデア欄に反映", key="strategy_apply_watchlist_idea"):
            st.session_state["strategy_idea_text"] = watchlist["idea_text"]
            st.rerun()


def _render_idea_input_section() -> None:
    st.subheader("① 投資アイデアを入力")
    st.caption(
        "自由な言葉で投資アイデアを入力してください。テンプレートボタンや、"
        "本日の値上がり銘柄からの提案も利用できます。"
    )

    template_cols = st.columns(len(_TEMPLATES))
    for col, (label, template_text) in zip(template_cols, _TEMPLATES.items()):
        with col:
            if st.button(label, key=f"strategy_template_{label}"):
                st.session_state["strategy_idea_text"] = template_text
                st.rerun()

    _render_sector_rotation_suggestion()

    st.text_area(
        "投資アイデア",
        key="strategy_idea_text",
        placeholder="例: PERが低く、ROEが高い成長株に投資したい",
        height=100,
    )

    if st.button("対話を始める", disabled=not st.session_state.get("strategy_idea_text")):
        st.session_state["strategy_chat_history"] = [
            {"role": "user", "content": st.session_state["strategy_idea_text"]}
        ]
        st.session_state["strategy_pending_strategy"] = None
        st.rerun()


def _clear_strategy_execution_state() -> None:
    """確定戦略が切り替わる（新規確定・別戦略の読み込み）タイミングで、前の戦略に
    対する実行結果（パイプライン/バックテスト/銘柄選定）をセッションから消す。
    消さないと、新しい戦略名のキャプションのまま前の戦略の結果テーブルが
    表示され続けてしまう。"""
    for key in (
        "strategy_pipeline_result_df",
        "strategy_pipeline_trace",
        "strategy_pipeline_selected_row",
        "strategy_pipeline_result_table",
        "strategy_backtest_result",
        "strategy_screening_result_df",
        "strategy_screening_selected_row",
        "strategy_screening_result_table",
    ):
        st.session_state.pop(key, None)


def _render_dialogue_section() -> None:
    st.subheader("② AIとの対話でロジックを構築")

    saved_strategies = load_strategies(get_current_user_id())
    if saved_strategies:
        options = ["(新規に対話する)"] + [s["strategy_name"] for s in saved_strategies]
        picked = st.selectbox("保存済み戦略を開く", options, key="strategy_load_picker")
        if picked != "(新規に対話する)":
            picked_strategy = next(
                s for s in saved_strategies if s["strategy_name"] == picked
            )
            if st.button("この戦略を読み込む", key="strategy_load_picked"):
                st.session_state["strategy_confirmed"] = picked_strategy
                st.session_state["strategy_chat_history"] = []
                st.session_state["strategy_pending_strategy"] = None
                _clear_strategy_execution_state()
                st.rerun()

    history = st.session_state.get("strategy_chat_history")
    if not history:
        st.caption("①でアイデアを入力し「対話を始める」を押すと、ここで対話が始まります。")
        return

    for turn in history:
        with st.chat_message(turn["role"]):
            st.write(turn["content"])

    pending = st.session_state.get("strategy_pending_strategy")

    # 最後のターンがユーザー発言で、まだ確定候補が無い場合のみLLMを呼ぶ。
    # （直前にAIの質問を表示済み、あるいは確定候補を表示中の再実行で
    # 重複してLLMを呼ばないようにするための判定）
    if history[-1]["role"] == "user" and pending is None:
        sector_jp_values = {
            p["sector_jp"] for p in load_all_company_profiles() if p["sector_jp"]
        }
        prompt = build_dialogue_prompt(history, sectors=sorted(sector_jp_values))
        with st.spinner("AIが回答を考えています..."):
            raw = call_llm(prompt)
        parsed = parse_dialogue_response(raw)
        if parsed["kind"] == "strategy":
            # 確定候補が生成された直後に自動評価・改善ループを1回だけ実行する
            # （Evaluator-Optimizerパターン）。結果を人間の最終確認に回す。
            with st.spinner("戦略条件を評価・改善中..."):
                evaluation_result = run_evaluation_loop(parsed["strategy"], call_llm=call_llm)
            st.session_state["strategy_pending_strategy"] = evaluation_result["strategy"]
            st.session_state["strategy_pending_evaluation"] = evaluation_result
        else:
            history.append({"role": "assistant", "content": parsed["text"]})
            st.session_state["strategy_chat_history"] = history
        st.rerun()

    if pending is not None:
        st.subheader("確定候補の戦略")
        evaluation_result = st.session_state.get("strategy_pending_evaluation")
        if evaluation_result and evaluation_result["iterations"] > 0:
            st.caption("AIによる自動改善を行いました。")
            if evaluation_result["last_feedback"]:
                st.caption(f"評価フィードバック: {evaluation_result['last_feedback']}")
        st.json(pending)
        confirm_col, continue_col = st.columns(2)
        with confirm_col:
            if st.button("この条件で確定する", key="strategy_confirm_pending"):
                save_strategy(get_current_user_id(), pending)
                st.session_state["strategy_confirmed"] = pending
                st.session_state["strategy_pending_strategy"] = None
                st.session_state["strategy_pending_evaluation"] = None
                _clear_strategy_execution_state()
                st.success(f"戦略「{pending['strategy_name']}」を保存しました。")
                st.rerun()
        with continue_col:
            if st.button("さらに対話を続ける", key="strategy_reject_pending"):
                history.append(
                    {
                        "role": "user",
                        "content": (
                            "まだ確定しません。もう少し条件について質問や"
                            "別の提案をしてください。"
                        ),
                    }
                )
                st.session_state["strategy_chat_history"] = history
                st.session_state["strategy_pending_strategy"] = None
                st.session_state["strategy_pending_evaluation"] = None
                st.rerun()
        return

    user_reply = st.chat_input("AIへの返信を入力", key="strategy_chat_input")
    if user_reply:
        history.append({"role": "user", "content": user_reply})
        st.session_state["strategy_chat_history"] = history
        st.rerun()


def _render_pipeline_section() -> None:
    strategy = st.session_state.get("strategy_confirmed")
    st.subheader("③ パイプラインを実行")
    if strategy is None:
        st.caption("②で戦略を確定するか、保存済み戦略を読み込むと利用できます。")
        return

    st.write(f"対象戦略: **{strategy['strategy_name']}**")

    if st.button("パイプラインを実行", key="strategy_run_pipeline"):
        with st.spinner("パイプラインを実行中..."):
            company_profiles = load_all_company_profiles()
            all_tickers = [p["ticker"] for p in company_profiles]
            names_by_ticker = {
                p["ticker"]: p["name"] for p in company_profiles if p["name"]
            }

            result_df, trace = run_pipeline(strategy["steps"], all_tickers, CACHE_DIR)
            result_df = result_df.copy()
            result_df["name"] = result_df["ticker"].map(names_by_ticker).fillna("")

            st.session_state["strategy_pipeline_result_df"] = result_df
            st.session_state["strategy_pipeline_trace"] = trace
            st.session_state["strategy_pipeline_selected_row"] = None
            st.session_state["strategy_pipeline_result_table"] = {
                "selection": {"rows": [], "columns": []}
            }

    trace = st.session_state.get("strategy_pipeline_trace")
    if trace:
        st.caption(" → ".join(trace))

    result_df = st.session_state.get("strategy_pipeline_result_df")
    if result_df is not None:
        st.caption(f"該当銘柄（{len(result_df)}件）。行をクリックすると銘柄詳細を表示します。")
        event = st.dataframe(
            result_df,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="strategy_pipeline_result_table",
        )
        handle_table_selection("strategy_pipeline_selected_row", event, result_df)


def render_strategy_builder_tab() -> None:
    logger.info("AI戦略ビルダータブを表示")
    st.header("AI戦略ビルダー")
    st.caption(
        "投資アイデアの入力からAIとの対話によるロジック構築、確定後のパイプライン"
        "実行までを一気通貫で行います。"
    )

    if "strategy_idea_text" not in st.session_state:
        st.session_state["strategy_idea_text"] = ""
    if "strategy_chat_history" not in st.session_state:
        st.session_state["strategy_chat_history"] = []
    if "strategy_pending_strategy" not in st.session_state:
        st.session_state["strategy_pending_strategy"] = None
    if "strategy_pending_evaluation" not in st.session_state:
        st.session_state["strategy_pending_evaluation"] = None
    if "strategy_confirmed" not in st.session_state:
        st.session_state["strategy_confirmed"] = None

    _render_idea_input_section()
    st.divider()
    _render_dialogue_section()
    st.divider()
    _render_pipeline_section()
    st.markdown(DISCLAIMER_NOTICE)
