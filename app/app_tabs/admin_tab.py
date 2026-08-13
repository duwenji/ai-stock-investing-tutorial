"""管理者タブ: is_admin権限を持つユーザーのみに表示される管理機能。
フェーズAでは全ユーザーの保存済み戦略の一覧・編集・削除のみを提供する
（ユーザー管理・市場データ管理は後続フェーズで追加）。
"""

import json
import logging

import pandas as pd
import streamlit as st

from admin import delete_user, list_ai_generations, list_users, set_admin_status
from data_api.stock_price_api import (
    load_company_profile,
    load_fundamentals_snapshots_for_ticker,
    load_price_history_for_ticker,
    save_company_profile_fields,
    save_fundamentals_snapshots_for_ticker,
    save_price_history_for_ticker,
)
from strategy_builder.storage import (
    delete_strategy_by_id,
    load_all_strategies,
    update_strategy_json_by_id,
)

from app_tabs.shared import get_current_user_id

logger = logging.getLogger(__name__)


def render_admin_tab() -> None:
    logger.info("管理者タブを表示")
    st.header("管理者")
    _render_strategy_management()
    st.divider()
    _render_user_management()
    st.divider()
    _render_market_data_management()
    st.divider()
    _render_ai_generation_log()


def _render_strategy_management() -> None:
    st.subheader("全ユーザー戦略管理")
    strategies = load_all_strategies()
    if not strategies:
        st.caption("保存済み戦略はまだありません。")
        return

    display_df = pd.DataFrame(
        [
            {
                "ユーザー": s["username"],
                "戦略名": s["strategy_name"],
                "作成日時": s["created_at"],
            }
            for s in strategies
        ]
    )
    st.caption("行をクリックすると内容を編集できます。")
    # on_select="rerun"を指定すると、行クリック時にStreamlitがスクリプトを再実行(rerun)し、
    # 戻り値のevent.selection.rowsに選択中の行インデックスが入る（複数選択がありうるため
    # リスト形式で返る点に注意）。key=はこのウィジェットの状態をst.session_state内で
    # 一意に識別するための名前で、同一画面に同種の部品が複数ある場合は必須。
    event = st.dataframe(
        display_df,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="admin_strategy_table",
    )
    selected_idx = event.selection.rows[0] if event.selection.rows else None
    # 削除操作直後のrerunでは、テーブルのウィジェット選択状態が古いインデックスを
    # 保持したままのことがあり、削除後に一覧が短くなっていると範囲外になり得るため
    # 明示的にチェックする
    if selected_idx is None or selected_idx >= len(strategies):
        return

    selected = strategies[selected_idx]
    st.caption(f"選択中: {selected['username']} / {selected['strategy_name']}")
    # key=f"...{selected['id']}" のように選択中の行IDをkeyに含めることで、選択行が
    # 変わるたびに別ウィジェット扱いになり、前の行で入力途中だった値が新しい行に
    # 引き継がれてしまう事故を防いでいる。
    json_text = st.text_area(
        "strategy_json",
        value=json.dumps(selected["strategy_json"], ensure_ascii=False, indent=2),
        height=300,
        key=f"admin_strategy_json_{selected['id']}",
    )
    save_col, delete_col = st.columns(2)
    with save_col:
        # st.buttonはクリックされた直後の1回のrerunでのみTrueを返す（その次のrerunでは
        # また自動的にFalseに戻る）。そのためボタン押下時の処理はifブロックの中に書く。
        if st.button("保存", key=f"admin_strategy_save_{selected['id']}"):
            try:
                update_strategy_json_by_id(selected["id"], json_text)
                st.success("更新しました。")
                # st.rerunはその場でスクリプトを再実行させるStreamlit専用命令。
                # 保存後すぐに呼ぶことで、DBの最新状態を反映した一覧に即座に更新できる
                # （呼ばなければ次にユーザーが何か操作するまで画面は更新されない）。
                st.rerun()
            except json.JSONDecodeError as exc:
                st.error(f"JSONの形式が不正です: {exc}")
    with delete_col:
        if st.button("削除", key=f"admin_strategy_delete_{selected['id']}"):
            delete_strategy_by_id(selected["id"])
            st.success("削除しました。")
            st.rerun()


def _render_user_management() -> None:
    st.subheader("ユーザーアカウント管理")
    current_user_id = get_current_user_id()
    users = list_users()

    display_df = pd.DataFrame(
        [
            {
                "ユーザー名": u["username"],
                "メール": u["email"] or "―",
                "登録日": u["created_at"],
                "管理者": u["is_admin"],
            }
            for u in users
        ]
    )
    st.caption("行をクリックすると操作できます。")
    event = st.dataframe(
        display_df,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="admin_user_table",
    )
    selected_idx = event.selection.rows[0] if event.selection.rows else None
    # 削除操作直後のrerunでは、テーブルのウィジェット選択状態が古いインデックスを
    # 保持したままのことがあり、削除後に一覧が短くなっていると範囲外になり得るため
    # 明示的にチェックする
    if selected_idx is None or selected_idx >= len(users):
        return

    selected = users[selected_idx]
    is_self = selected["id"] == current_user_id
    st.caption(f"選択中: {selected['username']}" + ("（自分自身）" if is_self else ""))

    admin_col, delete_col = st.columns(2)
    with admin_col:
        if selected["is_admin"]:
            if st.button(
                "管理者権限を剥奪",
                key=f"admin_user_revoke_{selected['id']}",
                disabled=is_self,
            ):
                set_admin_status(selected["id"], False)
                st.success("管理者権限を剥奪しました。")
                st.rerun()
        else:
            if st.button("管理者権限を付与", key=f"admin_user_grant_{selected['id']}"):
                set_admin_status(selected["id"], True)
                st.success("管理者権限を付与しました。")
                st.rerun()
    with delete_col:
        if st.button(
            "アカウント削除", key=f"admin_user_delete_{selected['id']}", disabled=is_self
        ):
            delete_user(selected["id"])
            st.success("アカウントを削除しました。")
            st.rerun()

    if is_self:
        st.caption("自分自身の管理者権限剥奪・アカウント削除はできません。")


def _render_market_data_management() -> None:
    st.subheader("市場データ管理")
    # st.text_inputは1文字入力するたびにrerunを発生させ、その時点の入力値を返す
    # （st.form内と違い即時反映される）。空文字ならこの下の編集UIを描画せず早期returnする。
    ticker = st.text_input("銘柄コード（例: 7203.T）", key="admin_market_data_ticker")
    if not ticker:
        st.caption("銘柄コードを入力すると、株価履歴・fundamentals・企業プロファイルを編集できます。")
        return

    st.markdown("**株価履歴（PriceHistory）**")
    price_rows = load_price_history_for_ticker(ticker)
    price_df = pd.DataFrame(
        price_rows, columns=["date", "open", "high", "low", "close", "volume"]
    )
    # st.data_editorはセルを直接編集できるテーブルウィジェット。num_rows="dynamic"を
    # 指定すると行の追加・削除も可能になる。戻り値は編集後のDataFrameで、元のprice_dfは
    # 変更されない（保存するにはこの戻り値を明示的にDB書き込み関数へ渡す必要がある）。
    edited_price_df = st.data_editor(
        price_df,
        num_rows="dynamic",
        hide_index=True,
        key=f"admin_price_history_editor_{ticker}",
    )
    if st.button("株価履歴を保存", key=f"admin_price_history_save_{ticker}"):
        # 追加行のうちdate未入力の行（保存準備がまだ整っていない空行）は除外する
        records = [r for r in edited_price_df.to_dict("records") if r.get("date")]
        save_price_history_for_ticker(ticker, records)
        st.success("株価履歴を保存しました。")
        st.rerun()

    st.markdown("**Fundamentalsスナップショット（FundamentalsSnapshot）**")
    fundamentals_rows = load_fundamentals_snapshots_for_ticker(ticker)
    fundamentals_df = pd.DataFrame(
        fundamentals_rows,
        columns=[
            "snapshot_date",
            "name",
            "trailing_pe",
            "price_to_book",
            "dividend_yield",
            "market_cap",
            "return_on_equity",
            "revenue_growth",
        ],
    )
    edited_fundamentals_df = st.data_editor(
        fundamentals_df,
        num_rows="dynamic",
        hide_index=True,
        key=f"admin_fundamentals_editor_{ticker}",
    )
    if st.button("Fundamentalsスナップショットを保存", key=f"admin_fundamentals_save_{ticker}"):
        records = [r for r in edited_fundamentals_df.to_dict("records") if r.get("snapshot_date")]
        save_fundamentals_snapshots_for_ticker(ticker, records)
        st.success("Fundamentalsスナップショットを保存しました。")
        st.rerun()

    st.markdown("**企業プロファイル（CompanyProfile）**")
    profile = load_company_profile(ticker) or {}
    # st.formで囲んだ中の入力ウィジェットは、値を変更しただけではrerunが発生しない
    # （通常のst.text_input等は1文字入力するたびにrerunするが、フォーム内は違う）。
    # フォーム内のst.form_submit_button（「送信」専用ボタン）が押されたときに初めて
    # まとめてrerunし、その時点の各入力値を読み取れる。複数項目を一括入力させたい
    # ときに、入力途中の余計なrerunを避けられるのが利点。
    with st.form(key=f"admin_company_profile_form_{ticker}"):
        name = st.text_input("日本語銘柄名", value=profile.get("name") or "")
        sector = st.text_input("業種", value=profile.get("sector") or "")
        industry = st.text_input("詳細業種", value=profile.get("industry") or "")
        sector_jp = st.text_input("東証17業種区分", value=profile.get("sector_jp") or "")
        business_summary = st.text_area(
            "事業内容", value=profile.get("business_summary") or "", height=150
        )
        if st.form_submit_button("企業プロファイルを保存"):
            save_company_profile_fields(
                ticker,
                name or None,
                sector or None,
                industry or None,
                business_summary or None,
                sector_jp or None,
            )
            st.success("企業プロファイルを保存しました。")
            st.rerun()


def _render_ai_generation_log() -> None:
    st.subheader("AI生成ログ（事実・AI見解）")
    generations = list_ai_generations()
    if not generations:
        st.caption("記録されたAI生成はまだありません。")
        return

    display_df = pd.DataFrame(
        [
            {
                "セッションID": g["session_id"],
                "種別": g["feature"],
                "銘柄": g["ticker"] or "―",
                "ユーザー": g["username"] or "―",
                "順番": g["turn_index"],
                "作成日時": g["created_at"],
                "AI応答（先頭200文字）": g["ai_output"],
            }
            for g in generations
        ]
    )
    st.dataframe(display_df, hide_index=True)
