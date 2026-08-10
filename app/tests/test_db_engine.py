from sqlalchemy import inspect
from sqlalchemy.orm import sessionmaker

from db.engine import create_db_engine, init_db
from db.models import Holding, SectorDisplaySetting, Strategy, User


def test_init_db_creates_all_tables(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    table_names = set(inspect(engine).get_table_names())
    assert {"users", "holdings", "strategies", "sector_display_settings"} <= table_names


def test_init_db_allows_basic_crud(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        user = User(username="taro", hashed_password="hashed")
        session.add(user)
        session.commit()
        session.refresh(user)

        session.add(Holding(user_id=user.id, ticker="7203.T", shares=100.0, cost=2500.0))
        session.add(Strategy(user_id=user.id, strategy_name="A", strategy_json="{}"))
        session.add(
            SectorDisplaySetting(
                user_id=user.id, visible_json="{}", order_json="{}", height_json="{}"
            )
        )
        session.commit()

    with session_factory() as session:
        assert session.query(Holding).count() == 1
        assert session.query(Strategy).count() == 1
        assert session.query(SectorDisplaySetting).count() == 1


def test_strategy_unique_constraint_on_user_and_name(tmp_path):
    from sqlalchemy.exc import IntegrityError

    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        user = User(username="taro", hashed_password="hashed")
        session.add(user)
        session.commit()
        session.refresh(user)

        session.add(Strategy(user_id=user.id, strategy_name="A", strategy_json="{}"))
        session.commit()

        session.add(Strategy(user_id=user.id, strategy_name="A", strategy_json="{}"))
        try:
            session.commit()
            assert False, "IntegrityErrorが発生するはず"
        except IntegrityError:
            session.rollback()
