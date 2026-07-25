import json

from sector_analysis.display_settings import (
    DEFAULT_SECTOR_DISPLAY_SETTINGS,
    load_sector_display_settings,
    save_sector_display_settings,
)


def test_load_missing_file_returns_defaults(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    assert load_sector_display_settings(path) == DEFAULT_SECTOR_DISPLAY_SETTINGS


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "sector_display_settings.json"
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
    save_sector_display_settings(path, settings)
    assert load_sector_display_settings(path) == settings


def test_load_corrupted_file_returns_defaults(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert load_sector_display_settings(path) == DEFAULT_SECTOR_DISPLAY_SETTINGS


def test_load_non_dict_json_returns_defaults(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_sector_display_settings(path) == DEFAULT_SECTOR_DISPLAY_SETTINGS


def test_load_legacy_flat_format_becomes_visible(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text(
        json.dumps(
            {
                "heatmap": False,
                "pairs_table": False,
                "ai_comments": False,
                "network_diagram": True,
                "wavelet_analysis": False,
            }
        ),
        encoding="utf-8",
    )
    result = load_sector_display_settings(path)
    assert result["visible"] == {
        "heatmap": False,
        "pairs_table": False,
        "ai_comments": False,
        "network_diagram": True,
        "wavelet_analysis": False,
    }
    assert result["order"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]
    assert result["height"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["height"]


def test_load_missing_keys_filled_with_defaults(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text(
        json.dumps({"visible": {"heatmap": False}, "order": {}, "height": {}}),
        encoding="utf-8",
    )
    result = load_sector_display_settings(path)
    assert result["visible"]["heatmap"] is False
    assert result["visible"]["pairs_table"] is True
    assert result["order"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]
    assert result["height"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["height"]


def test_load_unknown_keys_are_dropped(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text(
        json.dumps(
            {
                "visible": {"heatmap": False, "some_future_key": True},
                "order": {},
                "height": {},
            }
        ),
        encoding="utf-8",
    )
    result = load_sector_display_settings(path)
    assert "some_future_key" not in result["visible"]
    assert result["visible"]["heatmap"] is False


def test_load_non_bool_visible_value_falls_back_to_default(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text(
        json.dumps({"visible": {"heatmap": "yes"}, "order": {}, "height": {}}),
        encoding="utf-8",
    )
    result = load_sector_display_settings(path)
    assert result["visible"]["heatmap"] is True


def test_load_non_int_order_value_falls_back_to_default(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text(
        json.dumps({"visible": {}, "order": {"heatmap": "first"}, "height": {}}),
        encoding="utf-8",
    )
    result = load_sector_display_settings(path)
    assert result["order"]["heatmap"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]["heatmap"]


def test_load_bool_order_value_falls_back_to_default(tmp_path):
    # bool は Python では int のサブクラスなので、明示的に弾かれることを確認する
    path = tmp_path / "sector_display_settings.json"
    path.write_text(
        json.dumps({"visible": {}, "order": {"heatmap": True}, "height": {}}),
        encoding="utf-8",
    )
    result = load_sector_display_settings(path)
    assert result["order"]["heatmap"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]["heatmap"]


def test_load_non_numeric_height_value_falls_back_to_default(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text(
        json.dumps({"visible": {}, "order": {}, "height": {"heatmap": "big"}}),
        encoding="utf-8",
    )
    result = load_sector_display_settings(path)
    assert result["height"]["heatmap"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["height"]["heatmap"]


def test_load_unknown_height_key_is_dropped(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text(
        json.dumps({"visible": {}, "order": {}, "height": {"pairs_table": 999}}),
        encoding="utf-8",
    )
    result = load_sector_display_settings(path)
    assert "pairs_table" not in result["height"]
