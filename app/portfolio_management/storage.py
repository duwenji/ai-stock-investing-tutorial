"""保有銘柄一覧（holdings）をJSONファイルとして永続化・読み込みするモジュール。"""

import json
from pathlib import Path


def load_holdings(path: Path) -> list[dict]:
    """保有銘柄一覧をJSONファイルから読み込む。ファイルが存在しない、
    JSONとして壊れている、あるいは想定外の形式（リストでない）の場合は、
    エラーにせず空リストを返す。"""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return data


def save_holdings(path: Path, holdings: list[dict]) -> None:
    """保有銘柄一覧をJSONファイルとして保存する。保存先ディレクトリが
    存在しない場合は作成し、日本語をそのまま読める形式（ensure_ascii=False）
    で整形して書き出す。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(holdings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
