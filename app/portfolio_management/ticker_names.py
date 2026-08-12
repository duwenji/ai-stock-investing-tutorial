"""銘柄コードから日本語の銘柄名を解決し、画面表示等に使う
「銘柄コード→銘柄名」の対応表を組み立てるモジュール。
portfolio_tab.py・ranking_tab.pyから呼ばれる。"""

from data_api.stock_price_api import fetch_japanese_name as default_resolve_name
from data_api.stock_price_api import load_all_company_profiles


def build_candidate_names(
    holdings: list[dict],
    known_names: dict[str, str] | None = None,
    resolve_name=default_resolve_name,
) -> dict[str, str]:
    """既知の銘柄名一覧（company_profiles、未指定時は都度DBから読み込む）を
    ベースに、そこに含まれない保有銘柄についてはAPI経由で名称を解決し追加する。
    既知の銘柄は再解決せず、無駄なAPI呼び出しを避ける。

    resolve_nameを引数で差し替え可能にしているのは、テストで外部APIを
    呼ばずにダミー関数を渡せるようにするため（本番ではfetch_japanese_nameを使う）。"""
    if known_names is None:
        known_names = {
            p["ticker"]: p["name"] for p in load_all_company_profiles() if p["name"]
        }
    candidates = dict(known_names)
    for holding in holdings:
        ticker = holding.get("ticker")
        if not ticker or ticker in candidates:
            continue
        name = resolve_name(ticker)
        if name:
            candidates[ticker] = name
    return candidates
