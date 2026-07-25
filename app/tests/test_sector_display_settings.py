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
        "heatmap": False,
        "pairs_table": True,
        "ai_comments": False,
        "network_diagram": True,
        "wavelet_analysis": False,
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


def test_load_missing_keys_filled_with_defaults(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text('{"heatmap": false}', encoding="utf-8")
    result = load_sector_display_settings(path)
    assert result["heatmap"] is False
    assert result["pairs_table"] is True
    assert result["ai_comments"] is True
    assert result["network_diagram"] is True
    assert result["wavelet_analysis"] is True


def test_load_unknown_keys_are_dropped(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text('{"heatmap": false, "some_future_key": true}', encoding="utf-8")
    result = load_sector_display_settings(path)
    assert "some_future_key" not in result
    assert result["heatmap"] is False


def test_load_non_bool_value_falls_back_to_default(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text('{"heatmap": "yes"}', encoding="utf-8")
    result = load_sector_display_settings(path)
    assert result["heatmap"] is True
