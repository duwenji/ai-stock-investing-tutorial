"""業種間リード・ラグ関係（セクターローテーション分析）を使い、本日の
値上がり銘柄から「後日注意すべき業種・銘柄」を提案するモジュール。

セクターローテーションタブ・AI戦略ビルダータブが共有する分析結果
（app_tabs.shared.run_or_load_sector_rotation の戻り値）を入力とする。
このモジュール自体はStreamlit・データ取得に依存しない純粋ロジックとする。
"""


def find_top_gaining_tickers(
    ticker_latest_return_pct: dict[str, float], top_n: int = 5
) -> list[dict]:
    """直近日次リターンが高い順に上位top_n銘柄を返す。"""
    ranked = sorted(
        ticker_latest_return_pct.items(), key=lambda item: item[1], reverse=True
    )
    return [
        {"ticker": ticker, "return_pct": round(return_pct, 2)}
        for ticker, return_pct in ranked[:top_n]
    ]


def find_dominant_lagging_sector(
    network_pairs: list[dict],
    leading_sector: str,
    coherence_threshold: float = 0.5,
    band: str | None = None,
) -> dict | None:
    """指定業種が先行業種（leading_sector）となるペアの中から、
    コヒーレンス（mean_coherence）が閾値以上でもっとも高いものを返す。
    該当ペアが無ければNoneを返す。

    bandを指定すると、その周期帯（短期/中期/長期）のペアのみを対象にする。
    Noneの場合は全周期帯を横断してもっともコヒーレンスの高いペアを選ぶ。
    """
    candidates = [
        pair
        for pair in network_pairs
        if pair.get("leading_sector") == leading_sector
        and pair.get("mean_coherence", 0) >= coherence_threshold
        and (band is None or pair.get("band") == band)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda pair: pair["mean_coherence"])


def build_watchlist_from_rotation(
    ticker_latest_return_pct: dict[str, float],
    network_pairs: list[dict],
    sector_map: dict[str, str],
    universe_names: dict[str, str],
    top_n: int = 5,
    coherence_threshold: float = 0.5,
    band: str | None = None,
) -> dict:
    """本日の値上がり銘柄→先行業種→追随業種→候補銘柄、の順に洗い出し、
    投資アイデア文と候補銘柄一覧を返す。

    値上がり上位銘柄を順に試し、先行・追随関係が見つかった最初の1件を採用する。
    bandを指定すると、その周期帯（短期/中期/長期）のみを対象に先行・追随関係を
    探す（Noneの場合は全周期帯から自動選択する）。
    該当する関係が1件も見つからない場合は
    `{"idea_text": None, "candidates": []}` を返す。
    """
    top_gainers = find_top_gaining_tickers(ticker_latest_return_pct, top_n=top_n)

    for gainer in top_gainers:
        leading_sector = sector_map.get(gainer["ticker"])
        if leading_sector is None:
            continue
        pair = find_dominant_lagging_sector(
            network_pairs, leading_sector, coherence_threshold=coherence_threshold, band=band
        )
        if pair is None:
            continue

        lagging_sector = pair["lagging_sector"]
        candidates = [
            {
                "ticker": ticker,
                "name": universe_names.get(ticker, ticker),
                "sector": lagging_sector,
                "leading_sector": leading_sector,
                "lag_days": round(pair["lag_days_abs"], 1),
                "band": pair["band"],
            }
            for ticker, sector in sector_map.items()
            if sector == lagging_sector
        ]
        idea_text = (
            f"本日、業種「{leading_sector}」の銘柄（{gainer['ticker']}など）が"
            f"値上がりしました（直近日次リターン{gainer['return_pct']}%）。"
            f"過去の業種間分析では、{leading_sector}は業種「{lagging_sector}」に対し"
            f"平均{round(pair['lag_days_abs'], 1)}日先行する関係が見られます"
            f"（{pair['band']}、コヒーレンス{round(pair['mean_coherence'], 2)}）。"
            f"{lagging_sector}業種の中で財務健全性の高い銘柄に注目したい。"
        )
        return {"idea_text": idea_text, "candidates": candidates}

    return {"idea_text": None, "candidates": []}
