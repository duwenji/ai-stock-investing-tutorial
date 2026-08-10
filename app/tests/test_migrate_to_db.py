import json

import pytest
from sqlalchemy.orm import sessionmaker

from db.engine import create_db_engine, init_db
from db.models import Holding, SectorDisplaySetting, Strategy, User
from scripts.migrate_to_db import (
    create_admin_user,
    migrate_holdings,
    migrate_sector_display_settings,
    migrate_strategies,
)


@pytest.fixture
def session_factory(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    return sessionmaker(bind=engine)


def test_create_admin_user_hashes_password(session_factory):
    with session_factory() as session:
        user = create_admin_user(session, "taro", "s3cret", "taro@example.com")
        assert user.id is not None
        assert user.username == "taro"
        assert user.email == "taro@example.com"
        assert user.hashed_password != "s3cret"

        stored = session.query(User).filter_by(username="taro").one()
        assert stored.hashed_password == user.hashed_password


def test_migrate_holdings_inserts_rows_and_renames_file(tmp_path, session_factory):
    path = tmp_path / "holdings.json"
    path.write_text(
        json.dumps([{"ticker": "7203.T", "shares": 100, "cost": 2500.0}]),
        encoding="utf-8",
    )
    with session_factory() as session:
        user = create_admin_user(session, "taro", "s3cret", None)
        count = migrate_holdings(session, user.id, path=path)

        assert count == 1
        assert session.query(Holding).filter_by(user_id=user.id).count() == 1
    assert not path.exists()
    assert (tmp_path / "holdings.json.migrated").exists()


def test_migrate_holdings_missing_file_does_nothing(tmp_path, session_factory):
    path = tmp_path / "holdings.json"
    with session_factory() as session:
        user = create_admin_user(session, "taro", "s3cret", None)
        count = migrate_holdings(session, user.id, path=path)
        assert count == 0
        assert session.query(Holding).count() == 0
    assert not path.exists()


def test_migrate_strategies_inserts_rows_and_renames_file(tmp_path, session_factory):
    path = tmp_path / "strategies.json"
    path.write_text(
        json.dumps([{"strategy_name": "割安成長株", "conditions": []}]),
        encoding="utf-8",
    )
    with session_factory() as session:
        user = create_admin_user(session, "taro", "s3cret", None)
        count = migrate_strategies(session, user.id, path=path)

        assert count == 1
        row = session.query(Strategy).filter_by(user_id=user.id).one()
        assert json.loads(row.strategy_json) == {
            "strategy_name": "割安成長株",
            "conditions": [],
        }
    assert (tmp_path / "strategies.json.migrated").exists()


def test_migrate_sector_display_settings_normalizes_legacy_format(tmp_path, session_factory):
    path = tmp_path / "sector_display_settings.json"
    path.write_text(json.dumps({"heatmap": False, "pairs_table": True}), encoding="utf-8")
    with session_factory() as session:
        user = create_admin_user(session, "taro", "s3cret", None)
        migrated = migrate_sector_display_settings(session, user.id, path=path)

        assert migrated is True
        row = session.query(SectorDisplaySetting).filter_by(user_id=user.id).one()
        assert json.loads(row.visible_json)["heatmap"] is False
    assert (tmp_path / "sector_display_settings.json.migrated").exists()


def test_migrate_sector_display_settings_missing_file_returns_false(tmp_path, session_factory):
    path = tmp_path / "sector_display_settings.json"
    with session_factory() as session:
        user = create_admin_user(session, "taro", "s3cret", None)
        migrated = migrate_sector_display_settings(session, user.id, path=path)
        assert migrated is False
        assert session.query(SectorDisplaySetting).count() == 0
