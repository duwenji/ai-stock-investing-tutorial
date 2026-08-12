"""streamlit-authenticatorとDB（Userテーブル）を仲介するモジュール。
credentials辞書の構築、新規登録・パスワード変更結果の永続化を担う。
本モジュール自体はst.*を直接呼ばず、app.pyの認証フロー（ログインフォーム・
新規登録フォーム・パスワード変更フォーム）から結果を受け取ってDBに反映する側を担当する。
"""

from db.engine import SessionLocal
from db.models import User


# app.pyがstauth.Authenticate()を生成する際にcredentials引数として渡す関数。
# streamlit-authenticatorはこの辞書の形（{"usernames": {ユーザー名: {...}}}）を
# 厳密に要求するため、DBの行そのものではなくこの専用の辞書に変換する。
def build_credentials(session_factory=SessionLocal) -> dict:
    """DBのUserテーブル全件からstreamlit-authenticatorが要求するcredentials辞書を
    組み立てる。first_name/last_nameが未設定のユーザー（フェーズ1の移行スクリプトで
    作成した管理者アカウント等）はusernameを表示名としてフォールバックする
    （AuthenticationModel._get_user_nameがfirst_name/last_name不在時に"name"キーを
    参照する挙動に合わせる）。"""
    with session_factory() as session:
        users = session.query(User).all()
        usernames = {}
        for user in users:
            entry = {"email": user.email, "password": user.hashed_password}
            if user.first_name or user.last_name:
                entry["first_name"] = user.first_name or ""
                entry["last_name"] = user.last_name or ""
            else:
                entry["name"] = user.username
            usernames[user.username] = entry
        return {"usernames": usernames}


# ログイン成功直後にapp.pyがst.session_state["user_id"]へ書き込むために呼ぶ。
# ここで一度DBから引いてsession_stateに保存しておけば、以降のrerunのたびに
# 同じ問い合わせをやり直さずに済む。
def get_user_id(username: str, session_factory=SessionLocal) -> int | None:
    """ユーザー名からユーザーIDを引き当てる。存在しなければNoneを返す。"""
    with session_factory() as session:
        user = session.query(User).filter_by(username=username).first()
        return user.id if user else None


# get_user_idと同様、app.pyがログイン成功直後にst.session_state["is_admin"]へ
# 書き込むために呼ぶ。管理者タブの表示要否をrerunのたびに判定する際に使われる。
def get_is_admin(username: str, session_factory=SessionLocal) -> bool:
    """ユーザー名から管理者権限の有無を引き当てる。ユーザーが存在しなければ
    Falseを返す。"""
    with session_factory() as session:
        user = session.query(User).filter_by(username=username).first()
        return bool(user.is_admin) if user else False


# app.pyのauthenticator.register_user()（新規登録フォーム）が成功した直後に呼ばれる。
# フォーム自体はstreamlit-authenticator側のメモリ上のcredentialsしか更新しないため、
# ここでDBに保存しないと次回のbuild_credentials()呼び出し（アプリ再起動時）で消えてしまう。
def persist_new_user(
    username: str,
    email: str | None,
    hashed_password: str,
    first_name: str | None = None,
    last_name: str | None = None,
    session_factory=SessionLocal,
) -> User:
    """streamlit-authenticatorのregister_user()ウィジェットが成功した後、その結果
    （既にbcryptハッシュ済みのパスワードを含む）をUserテーブルへ永続化する。"""
    with session_factory() as session:
        user = User(
            username=username,
            email=email,
            hashed_password=hashed_password,
            first_name=first_name,
            last_name=last_name,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


# app.pyのauthenticator.reset_password()（サイドバーのパスワード変更フォーム）が
# 成功した直後に呼ばれる。register_user同様、DBへの反映を忘れるとアプリ再起動後に
# 変更前のパスワードに戻ってしまう。
def persist_password_update(
    username: str, hashed_password: str, session_factory=SessionLocal
) -> None:
    """streamlit-authenticatorのreset_password()ウィジェットが成功した後、その結果
    （既にbcryptハッシュ済みのパスワードを含む）をUserテーブルへ反映する。"""
    with session_factory() as session:
        user = session.query(User).filter_by(username=username).first()
        user.hashed_password = hashed_password
        session.commit()
