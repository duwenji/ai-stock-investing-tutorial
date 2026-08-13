"""管理者操作用のDB連携モジュール。ユーザーアカウント自体の管理
（一覧・admin権限付与剥奪・削除）を担う。auth.pyは認証フロー連携を担当し、
本モジュールは管理者タブからの操作に特化する。
本モジュール自体はst.*を直接呼ばず、app_tabs/admin_tab.pyのUI（st.dataframeの行選択や
st.buttonのクリック）から結果を受けてDBを更新する側を担当する。
"""

from db.engine import SessionLocal
from db.models import AiGeneration, AiSession, Holding, SectorDisplaySetting, Strategy, User


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


# admin_tab.pyのAI生成ログ一覧表示から呼ばれる。件数が際限なく増えるテーブルのため、
# 常にlimitで上限を設けて新しい順に返す。
def list_ai_generations(limit: int = 200, session_factory=SessionLocal) -> list[dict]:
    """AI生成ログ（事実・プロンプト・AI応答）を新しい順に返す。ai_outputは
    表示用に長すぎる場合は先頭200文字に切り詰める。"""
    with session_factory() as session:
        rows = (
            session.query(AiGeneration, AiSession, User)
            .join(AiSession, AiGeneration.session_id == AiSession.id)
            .outerjoin(User, AiSession.user_id == User.id)
            .order_by(AiGeneration.created_at.desc(), AiGeneration.id.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "session_id": generation.session_id,
                "feature": generation.feature,
                "ticker": session_row.ticker,
                "username": user.username if user else None,
                "turn_index": generation.turn_index,
                "created_at": generation.created_at,
                "ai_output": (
                    generation.ai_output[:200]
                    if len(generation.ai_output) > 200
                    else generation.ai_output
                ),
            }
            for generation, session_row, user in rows
        ]
