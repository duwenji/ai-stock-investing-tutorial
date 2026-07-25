"""セクターローテーションタブの表示セクション設定（表示ON/OFF・表示順序・
チャート高さ）をJSONファイルとして永続化・読み込みするモジュール。"""

import json
from pathlib import Path

_SECTION_KEYS = (
    "heatmap",
    "pairs_table",
    "ai_comments",
    "network_diagram",
    "wavelet_analysis",
)
_HEIGHT_KEYS = ("heatmap", "network_diagram", "wavelet_analysis")

DEFAULT_SECTOR_DISPLAY_SETTINGS: dict[str, dict] = {
    "visible": {key: True for key in _SECTION_KEYS},
    "order": {key: index + 1 for index, key in enumerate(_SECTION_KEYS)},
    "height": {"heatmap": 500, "network_diagram": 400, "wavelet_analysis": 400},
}


def _is_new_format(data: dict) -> bool:
    """新形式（トップレベルに"visible"辞書キーを持つ）かどうかを判定する。
    旧フラットbool形式（{"heatmap": true, ...}）にはこのキーが無い。"""
    return isinstance(data.get("visible"), dict)


def load_sector_display_settings(path: Path) -> dict[str, dict]:
    """表示設定をJSONファイルから読み込む。ファイルが存在しない、JSONとして
    壊れている、あるいは想定外の形式（辞書でない）の場合はデフォルト設定を
    返す。旧フラットbool形式のファイルは"visible"として読み込み、"order"・
    "height"はデフォルト値で補う。新形式でも、各サブ辞書内の欠落キー・
    型不正な値・未知のキーはデフォルト値で補う/無視する。"""
    settings = {
        "visible": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["visible"]),
        "order": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]),
        "height": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["height"]),
    }
    if not path.exists():
        return settings
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return settings
    if not isinstance(data, dict):
        return settings

    if not _is_new_format(data):
        for key in _SECTION_KEYS:
            if key in data and isinstance(data[key], bool):
                settings["visible"][key] = data[key]
        return settings

    visible_data = data.get("visible")
    if isinstance(visible_data, dict):
        for key in _SECTION_KEYS:
            value = visible_data.get(key)
            if isinstance(value, bool):
                settings["visible"][key] = value

    order_data = data.get("order")
    if isinstance(order_data, dict):
        for key in _SECTION_KEYS:
            value = order_data.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                settings["order"][key] = value

    height_data = data.get("height")
    if isinstance(height_data, dict):
        for key in _HEIGHT_KEYS:
            value = height_data.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                settings["height"][key] = value

    return settings


def save_sector_display_settings(path: Path, settings: dict[str, dict]) -> None:
    """表示設定をJSONファイルとして保存する。保存先ディレクトリが存在しない
    場合は作成する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
