"""セクターローテーションタブの表示セクション設定（表示ON/OFF・表示順序・
チャート高さ）をDBで永続化・読み込みするモジュール。"""

import json

from db.engine import SessionLocal
from db.models import SectorDisplaySetting

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


def _normalize(data: dict | None) -> dict[str, dict]:
    """設定dictを検証し、欠落キー・型不正な値・未知のキーをデフォルト値で
    補う/無視した正規形を返す。dataがdictでない場合はデフォルト設定を返す。
    移行スクリプト（scripts/migrate_to_db.py、旧JSONファイルの読み込み）と
    load_sector_display_settingsの両方から使う共通ロジック。"""
    settings = {
        "visible": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["visible"]),
        "order": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]),
        "height": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["height"]),
    }
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


def load_sector_display_settings(user_id: int, session_factory=SessionLocal) -> dict[str, dict]:
    """指定ユーザーの表示設定をDBから読み込む。保存済みの設定が無ければ
    デフォルト設定を返す。"""
    with session_factory() as session:
        row = session.get(SectorDisplaySetting, user_id)
        if row is None:
            return _normalize(None)
        data = {
            "visible": json.loads(row.visible_json),
            "order": json.loads(row.order_json),
            "height": json.loads(row.height_json),
        }
        return _normalize(data)


def save_sector_display_settings(
    user_id: int, settings: dict[str, dict], session_factory=SessionLocal
) -> None:
    """指定ユーザーの表示設定をDBに保存する。既存の設定があれば上書きする。"""
    with session_factory() as session:
        row = session.get(SectorDisplaySetting, user_id)
        if row is None:
            row = SectorDisplaySetting(user_id=user_id)
            session.add(row)
        row.visible_json = json.dumps(settings["visible"], ensure_ascii=False)
        row.order_json = json.dumps(settings["order"], ensure_ascii=False)
        row.height_json = json.dumps(settings["height"], ensure_ascii=False)
        session.commit()
