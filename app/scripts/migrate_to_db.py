"""既存のJSON永続化データ（holdings.json・strategies.json・
sector_display_settings.json）をDBへ一回限り移行するスクリプト。

実行方法（ai-stock-investing-tutorial/app ディレクトリで）:
    uv run python -m scripts.migrate_to_db
"""

import getpass
import json
from pathlib import Path

import bcrypt
from sqlalchemy.orm import Session

from db.engine import DATA_DIR, SessionLocal, engine, init_db
from db.models import Holding, SectorDisplaySetting, Strategy, User
from sector_analysis.display_settings import _normalize

HOLDINGS_PATH = DATA_DIR / "holdings.json"
STRATEGIES_PATH = DATA_DIR / "strategies.json"
SECTOR_DISPLAY_SETTINGS_PATH = DATA_DIR / "sector_display_settings.json"


def _load_json(path: Path):
    """JSONファイルを読み込む。存在しない、または壊れている場合はNoneを返す。"""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _mark_migrated(path: Path) -> None:
    path.rename(path.with_suffix(".json.migrated"))


def create_admin_user(session: Session, username: str, password: str, email: str | None) -> User:
    """管理者（最初の）ユーザーを作成する。パスワードはbcryptでハッシュ化して保存する。"""
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    user = User(username=username, email=email or None, hashed_password=hashed)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def migrate_holdings(session: Session, user_id: int, path: Path = HOLDINGS_PATH) -> int:
    """holdings.jsonの内容を指定ユーザーの保有銘柄としてDBへ移行し、移行元ファイルを
    リネームする。移行した件数を返す。ファイルが無い/壊れている場合は0件のまま
    何もしない。"""
    data = _load_json(path)
    holdings = data if isinstance(data, list) else []
    for holding in holdings:
        ticker = holding.get("ticker")
        if not ticker:
            continue
        session.add(
            Holding(
                user_id=user_id,
                ticker=ticker,
                shares=holding.get("shares", 0),
                cost=holding.get("cost", 0.0),
            )
        )
    session.commit()
    if holdings:
        _mark_migrated(path)
    return len(holdings)


def migrate_strategies(session: Session, user_id: int, path: Path = STRATEGIES_PATH) -> int:
    """strategies.jsonの内容を指定ユーザーの保存済み戦略としてDBへ移行し、移行元
    ファイルをリネームする。移行した件数を返す。"""
    data = _load_json(path)
    strategies = data if isinstance(data, list) else []
    for strategy in strategies:
        name = strategy.get("strategy_name")
        if not name:
            continue
        session.add(
            Strategy(
                user_id=user_id,
                strategy_name=name,
                strategy_json=json.dumps(strategy, ensure_ascii=False),
            )
        )
    session.commit()
    if strategies:
        _mark_migrated(path)
    return len(strategies)


def migrate_sector_display_settings(
    session: Session, user_id: int, path: Path = SECTOR_DISPLAY_SETTINGS_PATH
) -> bool:
    """sector_display_settings.jsonの内容を、既存の読み込みロジックと同じ検証
    （_normalize）を通した上で指定ユーザーの表示設定としてDBへ移行し、移行元
    ファイルをリネームする。ファイルが無ければFalseを返し何もしない。"""
    data = _load_json(path)
    if data is None:
        return False
    normalized = _normalize(data)
    session.add(
        SectorDisplaySetting(
            user_id=user_id,
            visible_json=json.dumps(normalized["visible"], ensure_ascii=False),
            order_json=json.dumps(normalized["order"], ensure_ascii=False),
            height_json=json.dumps(normalized["height"], ensure_ascii=False),
        )
    )
    session.commit()
    _mark_migrated(path)
    return True


def main() -> None:
    init_db(engine)
    with SessionLocal() as session:
        username = input("管理者ユーザー名: ").strip()
        password = getpass.getpass("パスワード: ")
        email = input("メールアドレス（任意、Enterでスキップ）: ").strip()

        user = create_admin_user(session, username, password, email)
        print(f"ユーザー '{user.username}' (id={user.id}) を作成しました。")

        n_holdings = migrate_holdings(session, user.id)
        print(f"保有銘柄 {n_holdings} 件を移行しました。")

        n_strategies = migrate_strategies(session, user.id)
        print(f"保存済み戦略 {n_strategies} 件を移行しました。")

        migrated_settings = migrate_sector_display_settings(session, user.id)
        print(
            "セクター表示設定を移行しました。"
            if migrated_settings
            else "セクター表示設定は見つかりませんでした。"
        )


if __name__ == "__main__":
    main()
