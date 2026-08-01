"""確定済み投資戦略（AI戦略ビルダー機能）をJSONファイルとして永続化・読み込みするモジュール。"""

import json
from pathlib import Path


def load_strategies(path: Path) -> list[dict]:
    """保存済み戦略の一覧をJSONファイルから読み込む。ファイルが存在しない、
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


def save_strategy(path: Path, strategy: dict) -> None:
    """戦略を1件、保存済み一覧に追記する。同名（strategy_name）の戦略が
    既にあれば上書きする。保存先ディレクトリが存在しない場合は作成し、
    日本語をそのまま読める形式（ensure_ascii=False）で整形して書き出す。"""
    strategies = load_strategies(path)
    name = strategy.get("strategy_name")
    strategies = [s for s in strategies if s.get("strategy_name") != name]
    strategies.append(strategy)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(strategies, ensure_ascii=False, indent=2), encoding="utf-8"
    )
