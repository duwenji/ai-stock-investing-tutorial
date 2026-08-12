"""日本株を対象としたAI投資リサーチアプリのエントリーポイント（Streamlit）。

ポートフォリオ管理・スクリーニング・バックテスト・一括バックテストランキング・
セクターローテーション分析の各機能をタブ形式のUIとしてまとめ、
株価/ファンダメンタルズ/ニュース取得とLLM（Claude）によるコメント生成を組み合わせて提供する。
各タブの描画処理は app_tabs 配下のモジュールに分割している。
"""

import logging

import streamlit as st
import streamlit_authenticator as stauth

from auth import build_credentials, get_is_admin, get_user_id, persist_new_user, persist_password_update
from common.disclaimer import DISCLAIMER_NOTICE
from common.logging_config import setup_logging
from data_api.llm_client import check_llm_available
from db.engine import engine, init_db

from app_tabs.admin_tab import render_admin_tab
from app_tabs.backtest_tab import render_backtest_tab
from app_tabs.portfolio_tab import render_portfolio_tab
from app_tabs.qa_tab import render_qa_tab
from app_tabs.ranking_tab import render_ranking_tab
from app_tabs.screening_tab import render_screening_tab
from app_tabs.sector import render_sector_tab
from app_tabs.strategy_builder_tab import render_strategy_builder_tab

setup_logging()
logger = logging.getLogger(__name__)
# StreamlitはユーザーがUI操作するたびにapp.pyを再実行するため、このログは
# 起動時だけでなく再実行のたびに出る。以降のログとの時系列対応付けに使う。
logger.info("app.pyを実行しました")

# st.set_page_config()はブラウザタブのタイトルやレイアウト幅を設定するStreamlit専用の関数。
# スクリプトの中で一番最初に呼ぶ必要があり（他のst.*コマンドより前）、1回のスクリプト実行で1度しか呼べない。
st.set_page_config(page_title="株投資リサーチアプリ", layout="wide")

init_db(engine)

# 設定されたLLMプロバイダが利用できない環境ではLLM機能が動作しないため、起動時点でチェックしてアプリを止める
# st.stop()はここでスクリプトの実行を打ち切るStreamlit専用の命令。これより下のコードは一切実行されない
# （Pythonのreturnと似ているが、関数の外・スクリプトのどこからでも呼べる点が特徴）。
try:
    check_llm_available()
except Exception as exc:
    st.error(str(exc))
    st.stop()

# --- 認証ゲート ---
# Cookie署名キーは.streamlit/secrets.tomlに保存する（README.mdのセットアップ手順を参照）。
# リポジトリには含めない機密情報のため、未設定ならここでアプリを止める。
# st.secretsはsecrets.tomlの内容を辞書のように読み込むStreamlit専用の機能（環境変数管理に相当）。
try:
    auth_cookie_key = st.secrets["auth_cookie_key"]
except Exception:
    st.error(
        "認証用のCookie署名キーが設定されていません。"
        "`.streamlit/secrets.toml` に `auth_cookie_key = \"...\"` を設定してください"
        "（README.mdのセットアップ手順を参照）。"
    )
    st.stop()

authenticator = stauth.Authenticate(
    build_credentials(),
    cookie_name="stock_advisor_auth",
    cookie_key=auth_cookie_key,
    cookie_expiry_days=30,
)

# authenticator.login()はログインフォーム（ユーザー名・パスワード入力欄とボタン）を画面に描画する。
# ログイン結果は戻り値ではなくst.session_state（後述）に書き込まれる点に注意。
try:
    authenticator.login()
except stauth.LoginError as exc:
    st.error(str(exc))

# st.session_stateはユーザーごとに保持される辞書のようなオブジェクト。
# Streamlitは操作のたびにapp.pyの中身を毎回上から実行し直す（これを「再実行(rerun)」と呼ぶ）ため、
# 通常の変数はrerunのたびに初期化されてしまうが、st.session_stateに入れた値だけは前回の状態が残る。
auth_status = st.session_state.get("authentication_status")

if auth_status is False:
    st.error("ユーザー名またはパスワードが正しくありません。")

if auth_status is not True:
    # ログイン成功（auth_status is True）以外は、この下の新規登録フォームを表示してst.stop()で処理を止める。
    # つまりログイン済みユーザーだけが、この関数より下にあるタブ描画コードまでたどり着ける。
    st.divider()
    st.subheader("新規登録")
    try:
        new_email, new_username, new_name = authenticator.register_user(captcha=False)
        if new_email:
            entry = authenticator.authentication_controller.authentication_model.credentials[
                "usernames"
            ][new_username]
            persist_new_user(
                new_username,
                entry.get("email"),
                entry["password"],
                entry.get("first_name"),
                entry.get("last_name"),
            )
            st.success("登録が完了しました。上のフォームからログインしてください。")
    except stauth.RegisterError as exc:
        st.error(str(exc))
    st.stop()

# ここでもst.session_stateに書き込むことで、rerunのたびにDB問い合わせをやり直さなくても
# app_tabs配下の各モジュールがst.session_state["user_id"]のようにこの値を参照できるようになる。
st.session_state["user_id"] = get_user_id(st.session_state["username"])
st.session_state["is_admin"] = get_is_admin(st.session_state["username"])

# st.sidebar.xxx() は st.xxx() と同じ部品を「左側のサイドバー」に配置するためのAPI。
# メイン画面用のst.xxx()とサイドバー用のst.sidebar.xxx()を使い分けることでレイアウトを制御する。
authenticator.logout(location="sidebar")
st.sidebar.caption(
    f"ログイン中: {st.session_state.get('name') or st.session_state['username']}"
)
st.sidebar.divider()
st.sidebar.subheader("パスワード変更")
try:
    if authenticator.reset_password(st.session_state["username"], location="sidebar"):
        entry = authenticator.authentication_controller.authentication_model.credentials[
            "usernames"
        ][st.session_state["username"]]
        persist_password_update(st.session_state["username"], entry["password"])
        st.sidebar.success("パスワードを変更しました。")
except (stauth.CredentialsError, stauth.ResetError) as exc:
    st.sidebar.error(str(exc))

st.sidebar.markdown(DISCLAIMER_NOTICE)

# 7つの主要機能に加え、管理者には8つ目の「管理者」タブを表示する
tab_labels = [
    "ポートフォリオ",
    "スクリーニング",
    "バックテスト",
    "一括バックテスト",
    "セクターローテーション",
    "AI戦略ビルダー",
    "AI質問箱",
]
if st.session_state["is_admin"]:
    tab_labels.append("管理者")

# st.tabs(labels)はタブ切り替えUIを作り、各タブに対応する「コンテナ」のリストを返す。
# 返ってくる順番はlabelsで渡した順番と一致するので、tabs[0]が「ポートフォリオ」タブに対応する。
tabs = st.tabs(tab_labels)
(
    tab_portfolio,
    tab_screening,
    tab_backtest,
    tab_ranking,
    tab_sector,
    tab_strategy_builder,
    tab_qa,
) = tabs[:7]

# 「with タブ:」のブロックに書いた部品は、そのタブが選択されているときだけ画面に表示される。
# ただし表示/非表示に関わらずrender_xxx_tab()の中身はrerunのたびに全タブ分が実行される
# （非表示のタブの処理も裏では走っている）ので、重い処理は各タブ側で@st.cache_dataなどを使って抑える。
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

with tab_strategy_builder:
    render_strategy_builder_tab()

with tab_qa:
    render_qa_tab()

if st.session_state["is_admin"]:
    with tabs[7]:
        render_admin_tab()
