"""日本株を対象としたAI投資リサーチアプリのエントリーポイント（Streamlit）。

ポートフォリオ管理・スクリーニング・バックテスト・一括バックテストランキング・
セクターローテーション分析の各機能をタブ形式のUIとしてまとめ、
株価/ファンダメンタルズ/ニュース取得とLLM（Claude）によるコメント生成を組み合わせて提供する。
各タブの描画処理は app_tabs 配下のモジュールに分割している。
"""

import streamlit as st

from common.disclaimer import DISCLAIMER_NOTICE
from data_api.llm_client import check_claude_cli_available

from app_tabs.backtest_tab import render_backtest_tab
from app_tabs.portfolio_tab import render_portfolio_tab
from app_tabs.ranking_tab import render_ranking_tab
from app_tabs.screening_tab import render_screening_tab
from app_tabs.sector import render_sector_tab

st.set_page_config(page_title="株投資リサーチアプリ", layout="wide")

# Claude CLIが利用できない環境ではLLM機能が動作しないため、起動時点でチェックしてアプリを止める
try:
    check_claude_cli_available()
except Exception as exc:
    st.error(str(exc))
    st.stop()

st.sidebar.markdown(DISCLAIMER_NOTICE)

# 5つの主要機能をタブとして構成する
tab_portfolio, tab_screening, tab_backtest, tab_ranking, tab_sector = st.tabs(
    ["ポートフォリオ", "スクリーニング", "バックテスト", "一括バックテスト", "セクターローテーション"]
)

with tab_portfolio:
    render_portfolio_tab()

with tab_screening:
    render_screening_tab()

with tab_backtest:
    render_backtest_tab()

with tab_ranking:
    render_ranking_tab()

with tab_sector:
    render_sector_tab()
