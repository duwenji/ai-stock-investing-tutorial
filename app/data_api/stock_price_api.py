"""yfinanceおよびYahoo!ファイナンス（日本版）から株価・ファンダメンタルズ・
ニュース等の市場データを取得するAPIラッパー群。取得結果のキャッシュ・
複数銘柄の並行取得もあわせて提供する。"""

import hashlib
import json
import logging
import re
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

from common.cache import read_cache, write_cache
from common.concurrency import map_concurrently
from common.logging_config import log_duration

logger = logging.getLogger(__name__)

# Yahoo!ファイナンス（日本版）のページタイトルからHTMLをパースせず銘柄名を
# 抜き出すための簡易正規表現（フルHTMLパーサーを使うほどではないため）
_YAHOO_JP_TITLE_RE = re.compile(r"<title>([^<]*)</title>")


def fetch_price_history(ticker_symbol: str, period: str = "1mo"):
    """指定銘柄の株価時系列（OHLCV）をyfinance経由で取得する。"""
    logger.info("株価履歴リクエスト: ticker=%s period=%s", ticker_symbol, period)
    ticker = yf.Ticker(ticker_symbol)
    history = ticker.history(period=period)
    logger.info(
        "株価履歴レスポンス: ticker=%s data=%s",
        ticker_symbol,
        history.to_json(orient="records", date_format="iso"),
    )
    return history


def fetch_fundamentals(ticker_symbol: str) -> dict:
    """指定銘柄のファンダメンタルズ指標（PER・PBR・配当利回り等）を取得する。"""
    logger.info("fundamentalsリクエスト: ticker=%s", ticker_symbol)
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info
    result = {
        "ticker": ticker_symbol,
        "name": info.get("longName"),
        "trailing_pe": info.get("trailingPE"),
        "price_to_book": info.get("priceToBook"),
        "dividend_yield": info.get("dividendYield"),
        "market_cap": info.get("marketCap"),
    }
    logger.info("fundamentalsレスポンス: ticker=%s data=%s", ticker_symbol, result)
    return result


def fetch_news(ticker_symbol: str, limit: int = 5) -> list[dict]:
    """指定銘柄に関連する最新ニュースを取得し、表示に必要な項目だけに整形する。"""
    logger.info("newsリクエスト: ticker=%s limit=%s", ticker_symbol, limit)
    ticker = yf.Ticker(ticker_symbol)
    news_items = ticker.news or []
    result = []
    for item in news_items[:limit]:
        # yfinanceのニュースレスポンスはネストしたcontent/provider構造のため、
        # 欠損があっても落ちないよう各階層でNone安全に取り出す
        content = item.get("content") or {}
        provider = content.get("provider") or {}
        link_info = content.get("clickThroughUrl") or content.get("canonicalUrl") or {}
        result.append(
            {
                "title": content.get("title"),
                "publisher": provider.get("displayName"),
                "link": link_info.get("url"),
            }
        )
    logger.info("newsレスポンス: ticker=%s data=%s", ticker_symbol, result)
    return result


def fetch_japanese_name(ticker_symbol: str) -> str | None:
    """Yahoo!ファイナンス（日本版）のページタイトルから日本語の銘柄名を取得する。

    yfinance（Yahoo Financeのグローバルデータ）は日本株の名前を英語でしか
    返さないため、日本語名専用にこの関数を使う。
    """
    url = f"https://finance.yahoo.co.jp/quote/{ticker_symbol}"
    logger.info("日本語銘柄名リクエスト: url=%s", url)
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        response.raise_for_status()
    except requests.RequestException:
        logger.warning("日本語銘柄名取得失敗: url=%s", url)
        return None
    logger.info("日本語銘柄名レスポンス: url=%s body=%s", url, response.text)

    match = _YAHOO_JP_TITLE_RE.search(response.text)
    if not match:
        return None

    title = match.group(1)
    if "【" not in title:
        return None

    name = title.split("【", 1)[0].strip()
    return name or None


def fetch_universe_fundamentals(
    tickers: list[str],
    cache_dir: Path,
    fetch_fundamentals=fetch_fundamentals,
) -> pd.DataFrame:
    """複数銘柄のファンダメンタルズをまとめて取得し、DataFrameとして返す。

    セクター分析などスクリーニング用途で銘柄集合全体を扱うため、
    キャッシュと並行取得によって繰り返し呼び出しのコストを抑える。
    """
    # 銘柄集合ごとに一意なキャッシュキーを作る（順序に依らないようソートしてハッシュ化）
    cache_key = "universe-" + hashlib.sha256(
        "-".join(sorted(tickers)).encode("utf-8")
    ).hexdigest()[:12]
    cached = read_cache(cache_dir, cache_key)
    if cached is not None:
        return pd.DataFrame(json.loads(cached))

    with log_duration(logger, f"ユニバースfundamentals一括取得（{len(tickers)}銘柄）"):
        # 銘柄数が多いと逐次取得は遅いため、複数銘柄を並行してAPI取得する
        results = map_concurrently(tickers, fetch_fundamentals)
        rows = []
        for ticker_symbol in tickers:
            data = results[ticker_symbol]
            # 個別銘柄の取得失敗（例外）は全体を止めず、その銘柄だけスキップする
            if isinstance(data, Exception):
                continue
            rows.append(
                {
                    "ticker": data.get("ticker", ticker_symbol),
                    "name": data.get("name"),
                    "per": data.get("trailing_pe"),
                    "pbr": data.get("price_to_book"),
                    # yfinance's dividendYield is already a percentage number
                    # (e.g. 3.45 means 3.45%), not a fraction to scale up.
                    "dividend_yield_pct": data.get("dividend_yield"),
                    "market_cap": data.get("market_cap"),
                }
            )
        df = pd.DataFrame(rows)
        write_cache(cache_dir, cache_key, df.to_json(orient="records", force_ascii=False))
    return df
