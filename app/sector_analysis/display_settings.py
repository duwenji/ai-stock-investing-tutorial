"""セクターローテーションタブの表示セクション設定をJSONファイルとして
永続化・読み込みするモジュール。"""

import json
from pathlib import Path

DEFAULT_SECTOR_DISPLAY_SETTINGS: dict[str, bool] = {
    "heatmap": True,
    "pairs_table": True,
    "ai_comments": True,
    "network_diagram": True,
    "wavelet_analysis": True,
}


def load_sector_display_settings(path: Path) -> dict[str, bool]:
    """表示設定をJSONファイルから読み込む。ファイルが存在しない、JSONとして
    壊れている、あるいは想定外の形式（辞書でない）の場合はデフォルト設定を
    返す。デフォルトにないキーは無視し、デフォルトにあるが保存データにない
    キー、または値がbool以外のキーはデフォルト値で補う（将来セクションが
    増えても既存ファイルで壊れない）。"""
    settings = dict(DEFAULT_SECTOR_DISPLAY_SETTINGS)
    if not path.exists():
        return settings
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return settings
    if not isinstance(data, dict):
        return settings
    for key in settings:
        if key in data and isinstance(data[key], bool):
            settings[key] = data[key]
    return settings


def save_sector_display_settings(path: Path, settings: dict[str, bool]) -> None:
    """表示設定をJSONファイルとして保存する。保存先ディレクトリが存在しない
    場合は作成する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
