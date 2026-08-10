"""管理者タブ: is_admin権限を持つユーザーのみに表示される管理機能。
フェーズAでは全ユーザーの保存済み戦略の一覧・編集・削除のみを提供する
（ユーザー管理・市場データ管理は後続フェーズで追加）。
"""

import json
import logging

import pandas as pd
import streamlit as st

from admin import delete_user, list_users, set_admin_status
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
    event = st.dataframe(
        display_df,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="admin_strategy_table",
    )
    selected_idx = event.selection.rows[0] if event.selection.rows else None
    if selected_idx is None:
        return

    selected = strategies[selected_idx]
    st.caption(f"選択中: {selected['username']} / {selected['strategy_name']}")
    json_text = st.text_area(
        "strategy_json",
        value=json.dumps(selected["strategy_json"], ensure_ascii=False, indent=2),
        height=300,
        key=f"admin_strategy_json_{selected['id']}",
    )
    save_col, delete_col = st.columns(2)
    with save_col:
        if st.button("保存", key=f"admin_strategy_save_{selected['id']}"):
            try:
                update_strategy_json_by_id(selected["id"], json_text)
                st.success("更新しました。")
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
    if selected_idx is None:
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
