import json

import pytest
from sqlalchemy.orm import sessionmaker

from db.engine import create_db_engine, init_db
from sector_analysis.display_settings import (
    DEFAULT_SECTOR_DISPLAY_SETTINGS,
    _normalize,
    load_sector_display_settings,
    save_sector_display_settings,
)


def test_normalize_none_returns_defaults():
    assert _normalize(None) == DEFAULT_SECTOR_DISPLAY_SETTINGS


def test_normalize_non_dict_returns_defaults():
    assert _normalize([1, 2, 3]) == DEFAULT_SECTOR_DISPLAY_SETTINGS


def test_normalize_legacy_flat_format_becomes_visible():
    data = {
        "heatmap": False,
        "pairs_table": False,
        "ai_comments": False,
        "network_diagram": True,
        "wavelet_analysis": False,
    }
    result = _normalize(data)
    assert result["visible"] == data
    assert result["order"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]
    assert result["height"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["height"]


def test_normalize_missing_keys_filled_with_defaults():
    data = {"visible": {"heatmap": False}, "order": {}, "height": {}}
    result = _normalize(data)
    assert result["visible"]["heatmap"] is False
    assert result["visible"]["pairs_table"] is True
    assert result["order"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]
    assert result["height"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["height"]


def test_normalize_unknown_keys_are_dropped():
    data = {
        "visible": {"heatmap": False, "some_future_key": True},
        "order": {},
        "height": {},
    }
    result = _normalize(data)
    assert "some_future_key" not in result["visible"]
    assert result["visible"]["heatmap"] is False


def test_normalize_non_bool_visible_value_falls_back_to_default():
    data = {"visible": {"heatmap": "yes"}, "order": {}, "height": {}}
    result = _normalize(data)
    assert result["visible"]["heatmap"] is True


def test_normalize_non_int_order_value_falls_back_to_default():
    data = {"visible": {}, "order": {"heatmap": "first"}, "height": {}}
    result = _normalize(data)
    assert result["order"]["heatmap"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]["heatmap"]


def test_normalize_bool_order_value_falls_back_to_default():
    # boolはPythonではintのサブクラスなので、明示的に弾かれることを確認する
    data = {"visible": {}, "order": {"heatmap": True}, "height": {}}
    result = _normalize(data)
    assert result["order"]["heatmap"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]["heatmap"]


def test_normalize_non_numeric_height_value_falls_back_to_default():
    data = {"visible": {}, "order": {}, "height": {"heatmap": "big"}}
    result = _normalize(data)
    assert result["height"]["heatmap"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["height"]["heatmap"]


def test_normalize_unknown_height_key_is_dropped():
    data = {"visible": {}, "order": {}, "height": {"pairs_table": 999}}
    result = _normalize(data)
    assert "pairs_table" not in result["height"]


@pytest.fixture
def session_factory(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    return sessionmaker(bind=engine)


def test_load_returns_defaults_when_no_row(session_factory):
    assert load_sector_display_settings(1, session_factory=session_factory) == (
        DEFAULT_SECTOR_DISPLAY_SETTINGS
    )


def test_save_then_load_roundtrip(session_factory):
    settings = {
        "visible": {
            "heatmap": False,
            "pairs_table": True,
            "ai_comments": False,
            "network_diagram": True,
            "wavelet_analysis": False,
        },
        "order": {
            "heatmap": 3,
            "pairs_table": 1,
            "ai_comments": 2,
            "network_diagram": 5,
            "wavelet_analysis": 4,
        },
        "height": {"heatmap": 600, "network_diagram": 350, "wavelet_analysis": 450},
    }
    save_sector_display_settings(1, settings, session_factory=session_factory)
    assert load_sector_display_settings(1, session_factory=session_factory) == settings


def test_save_overwrites_existing_settings(session_factory):
    settings_a = {
        "visible": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["visible"]),
        "order": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]),
        "height": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["height"]),
    }
    settings_b = json.loads(json.dumps(settings_a))
    settings_b["visible"]["heatmap"] = False

    save_sector_display_settings(1, settings_a, session_factory=session_factory)
    save_sector_display_settings(1, settings_b, session_factory=session_factory)
    assert load_sector_display_settings(1, session_factory=session_factory)["visible"]["heatmap"] is (
        False
    )


def test_settings_are_scoped_per_user(session_factory):
    settings_1 = {
        "visible": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["visible"]),
        "order": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]),
        "height": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["height"]),
    }
    save_sector_display_settings(1, settings_1, session_factory=session_factory)
    assert load_sector_display_settings(2, session_factory=session_factory) == (
        DEFAULT_SECTOR_DISPLAY_SETTINGS
    )
