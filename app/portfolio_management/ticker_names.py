"""銘柄コードから日本語の銘柄名を解決し、画面表示等に使う
「銘柄コード→銘柄名」の対応表を組み立てるモジュール。"""

from data_api.stock_price_api import fetch_japanese_name as default_resolve_name
from screening.universe import UNIVERSE_NAMES


def build_candidate_names(
    holdings: list[dict],
    universe_names: dict[str, str] = UNIVERSE_NAMES,
    resolve_name=default_resolve_name,
) -> dict[str, str]:
    """既知の銘柄名一覧（UNIVERSE_NAMES）をベースに、そこに含まれない
    保有銘柄についてはAPI経由で名称を解決し追加する。ユニバースに
    存在する銘柄は再解決せず、無駄なAPI呼び出しを避ける。"""
    candidates = dict(universe_names)
    for holding in holdings:
        ticker = holding.get("ticker")
        if not ticker or ticker in candidates:
            continue
        name = resolve_name(ticker)
        if name:
            candidates[ticker] = name
    return candidates
