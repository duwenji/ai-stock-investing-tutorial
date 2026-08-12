"""保有銘柄一覧（holdings）をDBで永続化・読み込みするモジュール。
portfolio_tab.py・qa_tab.py・ranking_tab.pyから呼ばれる。"""

from data_api.stock_price_api import ensure_company_profile_stub
from db.engine import SessionLocal
from db.models import Holding


# session_factoryをデフォルト引数（本番用のSessionLocal）ごと外から差し替えられるように
# しているのは、テストコードが実DBの代わりにインメモリDB用のセッションファクトリを
# 渡せるようにするため（Streamlit UI側は常にデフォルトのまま呼び出す）。
def load_holdings(user_id: int, session_factory=SessionLocal) -> list[dict]:
    """指定ユーザーの保有銘柄一覧をDBから読み込む。1件も無ければ空リストを返す。"""
    with session_factory() as session:
        rows = (
            session.query(Holding)
            .filter_by(user_id=user_id)
            .order_by(Holding.id)
            .all()
        )
        return [
            {"ticker": row.ticker, "shares": row.shares, "cost": row.cost} for row in rows
        ]


def save_holdings(user_id: int, holdings: list[dict], session_factory=SessionLocal) -> None:
    """指定ユーザーの保有銘柄一覧をDBに保存する。既存の保有銘柄は全て削除してから
    渡されたholdingsで置き換える（呼び出し元は常に全件を渡す想定）。"""
    with session_factory() as session:
        # 差分更新ではなく「全削除→全件追加」という単純な置き換え方式にすることで、
        # 追加・削除・銘柄数変更のケース分けを呼び出し側で考えなくてよいようにしている。
        session.query(Holding).filter_by(user_id=user_id).delete()
        for holding in holdings:
            # 銘柄マスタ（company_profiles）に未登録のtickerでも保存できるよう、
            # 保有銘柄として登録する前に最低限のプロフィール行を用意しておく。
            ensure_company_profile_stub(session, holding["ticker"])
            session.add(
                Holding(
                    user_id=user_id,
                    ticker=holding["ticker"],
                    shares=holding["shares"],
                    cost=holding["cost"],
                )
            )
        session.commit()
