"""streamlit-authenticatorとDB（Userテーブル）を仲介するモジュール。
credentials辞書の構築、新規登録・パスワード変更結果の永続化を担う。
"""

from db.engine import SessionLocal
from db.models import User


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


def get_user_id(username: str, session_factory=SessionLocal) -> int | None:
    """ユーザー名からユーザーIDを引き当てる。存在しなければNoneを返す。"""
    with session_factory() as session:
        user = session.query(User).filter_by(username=username).first()
        return user.id if user else None


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


def persist_password_update(
    username: str, hashed_password: str, session_factory=SessionLocal
) -> None:
    """streamlit-authenticatorのreset_password()ウィジェットが成功した後、その結果
    （既にbcryptハッシュ済みのパスワードを含む）をUserテーブルへ反映する。"""
    with session_factory() as session:
        user = session.query(User).filter_by(username=username).first()
        user.hashed_password = hashed_password
        session.commit()
