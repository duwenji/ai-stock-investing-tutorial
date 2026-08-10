"""保有銘柄一覧（holdings）をDBで永続化・読み込みするモジュール。"""

from data_api.stock_price_api import ensure_company_profile_stub
from db.engine import SessionLocal
from db.models import Holding


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
        session.query(Holding).filter_by(user_id=user_id).delete()
        for holding in holdings:
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
