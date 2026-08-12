"""確定済み投資戦略（AI戦略ビルダー機能）をDBで永続化・読み込みするモジュール。"""

import json

from db.engine import SessionLocal
from db.models import Strategy, User


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
        # updateではなく削除→追加で「上書き」を実現する（strategy_builder_tab.pyの
        # 保存ボタン押下時に呼ばれる）。
        session.query(Strategy).filter_by(user_id=user_id, strategy_name=name).delete()
        session.add(
            Strategy(
                user_id=user_id,
                strategy_name=name,
                strategy_json=json.dumps(strategy, ensure_ascii=False),
            )
        )
        session.commit()


def load_all_strategies(session_factory=SessionLocal) -> list[dict]:
    """全ユーザーの保存済み戦略一覧を、紐づくユーザー名付きでDBから読み込む
    （管理者向け）。strategy_jsonはパース済みdictとして含める。"""
    with session_factory() as session:
        rows = (
            session.query(Strategy, User.username)
            .join(User, Strategy.user_id == User.id)
            .order_by(Strategy.id)
            .all()
        )
        return [
            {
                "id": strategy.id,
                "user_id": strategy.user_id,
                "username": username,
                "strategy_name": strategy.strategy_name,
                "strategy_json": json.loads(strategy.strategy_json),
                "created_at": strategy.created_at,
            }
            for strategy, username in rows
        ]


def delete_strategy_by_id(strategy_id: int, session_factory=SessionLocal) -> None:
    """指定したIDの戦略を削除する（管理者向け、ユーザーを問わない）。"""
    with session_factory() as session:
        session.query(Strategy).filter_by(id=strategy_id).delete()
        session.commit()


def update_strategy_json_by_id(
    strategy_id: int, strategy_json_str: str, session_factory=SessionLocal
) -> None:
    """指定したIDの戦略のstrategy_jsonを更新する（管理者向け）。
    strategy_json_strが不正なJSONの場合はjson.JSONDecodeErrorをそのまま送出する。
    パース結果にstrategy_nameキーがあればstrategy_name列も同期する。"""
    parsed = json.loads(strategy_json_str)
    with session_factory() as session:
        strategy = session.query(Strategy).filter_by(id=strategy_id).first()
        strategy.strategy_json = strategy_json_str
        if "strategy_name" in parsed:
            strategy.strategy_name = parsed["strategy_name"]
        session.commit()
