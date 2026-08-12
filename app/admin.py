"""管理者操作用のDB連携モジュール。ユーザーアカウント自体の管理
（一覧・admin権限付与剥奪・削除）を担う。auth.pyは認証フロー連携を担当し、
本モジュールは管理者タブからの操作に特化する。
本モジュール自体はst.*を直接呼ばず、app_tabs/admin_tab.pyのUI（st.dataframeの行選択や
st.buttonのクリック）から結果を受けてDBを更新する側を担当する。
"""

from db.engine import SessionLocal
from db.models import Holding, SectorDisplaySetting, Strategy, User


# admin_tab.pyがst.dataframe()に渡す表の元データとして呼ぶ。rerunのたびに
# 呼ばれるため、ここでキャッシュはせず常に最新のDB内容を返す
# （管理者一覧は件数が少なく、キャッシュするほど重い処理ではないため）。
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


# admin_tab.pyの「管理者権限を付与/剥奪」ボタンのon_click相当の処理から呼ばれる
# （このプロジェクトではon_click引数ではなく、if st.button(...): の直下で呼ぶ書き方を
# 採用しているため、ボタンが押されてスクリプトが再実行された回だけここが実行される）。
def set_admin_status(user_id: int, is_admin: bool, session_factory=SessionLocal) -> None:
    """指定ユーザーの管理者権限を設定する。"""
    with session_factory() as session:
        user = session.query(User).filter_by(id=user_id).first()
        user.is_admin = is_admin
        session.commit()


# admin_tab.pyの「アカウント削除」ボタンから呼ばれる。呼び出し側は削除後に
# st.rerun()を呼び、一覧を最新状態で再描画する（削除だけでは画面は自動更新されない）。
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
