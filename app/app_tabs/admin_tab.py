"""管理者タブ: is_admin権限を持つユーザーのみに表示される管理機能。
フェーズAでは全ユーザーの保存済み戦略の一覧・編集・削除のみを提供する
（ユーザー管理・市場データ管理は後続フェーズで追加）。
"""

import json
import logging

import pandas as pd
import streamlit as st

from strategy_builder.storage import (
    delete_strategy_by_id,
    load_all_strategies,
    update_strategy_json_by_id,
)

logger = logging.getLogger(__name__)


def render_admin_tab() -> None:
    logger.info("管理者タブを表示")
    st.header("管理者")
    _render_strategy_management()


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
