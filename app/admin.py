"""管理者操作用のDB連携モジュール。ユーザーアカウント自体の管理
（一覧・admin権限付与剥奪・削除）を担う。auth.pyは認証フロー連携を担当し、
本モジュールは管理者タブからの操作に特化する。
"""

from db.engine import SessionLocal
from db.models import Holding, SectorDisplaySetting, Strategy, User


def list_users(session_factory=SessionLocal) -> list[dict]:
    """全ユーザーの一覧をDBから読み込む。"""
    with session_factory() as session:
        users = session.query(User).order_by(User.id).all()
        return [
            {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "created_at": user.created_at,
                "is_admin": user.is_admin,
            }
            for user in users
        ]


def set_admin_status(user_id: int, is_admin: bool, session_factory=SessionLocal) -> None:
    """指定ユーザーの管理者権限を設定する。"""
    with session_factory() as session:
        user = session.query(User).filter_by(id=user_id).first()
        user.is_admin = is_admin
        session.commit()


def delete_user(user_id: int, session_factory=SessionLocal) -> None:
    """指定ユーザーのアカウントを削除する。SQLiteの外部キーCASCADEを
    有効化していないため、紐づくHolding/Strategy/SectorDisplaySettingも
    アプリ側で明示的に削除する。"""
    with session_factory() as session:
        session.query(Holding).filter_by(user_id=user_id).delete()
        session.query(Strategy).filter_by(user_id=user_id).delete()
        session.query(SectorDisplaySetting).filter_by(user_id=user_id).delete()
        session.query(User).filter_by(id=user_id).delete()
        session.commit()
