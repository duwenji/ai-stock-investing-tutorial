"""確定済み投資戦略（AI戦略ビルダー機能）をDBで永続化・読み込みするモジュール。"""

import json

from db.engine import SessionLocal
from db.models import Strategy


def load_strategies(user_id: int, session_factory=SessionLocal) -> list[dict]:
    """指定ユーザーの保存済み戦略一覧をDBから読み込む。1件も無ければ空リストを返す。"""
    with session_factory() as session:
        rows = (
            session.query(Strategy)
            .filter_by(user_id=user_id)
            .order_by(Strategy.id)
            .all()
        )
        return [json.loads(row.strategy_json) for row in rows]


def save_strategy(user_id: int, strategy: dict, session_factory=SessionLocal) -> None:
    """戦略を1件、保存済み一覧に追記する。同名（strategy_name）の戦略が既にあれば
    上書きする。"""
    name = strategy.get("strategy_name")
    with session_factory() as session:
        session.query(Strategy).filter_by(user_id=user_id, strategy_name=name).delete()
        session.add(
            Strategy(
                user_id=user_id,
                strategy_name=name,
                strategy_json=json.dumps(strategy, ensure_ascii=False),
            )
        )
        session.commit()
