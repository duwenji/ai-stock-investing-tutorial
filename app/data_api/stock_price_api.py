"""yfinanceおよびYahoo!ファイナンス（日本版）から株価・ファンダメンタルズ・
ニュース等の市場データを取得するAPIラッパー群。取得結果のキャッシュ・
複数銘柄の並行取得もあわせて提供する。"""

import datetime
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
from db.engine import SessionLocal
from db.models import PriceHistory

logger = logging.getLogger(__name__)

# Yahoo!ファイナンス（日本版）のページタイトルからHTMLをパースせず銘柄名を
# 抜き出すための簡易正規表現（フルHTMLパーサーを使うほどではないため）
_YAHOO_JP_TITLE_RE = re.compile(r"<title>([^<]*)</title>")


# アプリ内で使われる最大期間（1mo/6mo/1y/2y/3y/5y）。鮮度切れ時は常にこの期間で
# yfinanceから取得してDBへ蓄積することで、以後どの期間で要求されてもDBだけで
# 足りるようにする（呼び出しごとに異なる期間を要求されても再フェッチが不要になる）。
_MAX_FETCH_PERIOD = "5y"
_PERIOD_TO_DAYS = {
    "1mo": 31,
    "6mo": 186,
    "1y": 366,
    "2y": 731,
    "3y": 1096,
    "5y": 1827,
}


def _period_to_start_date(period: str) -> datetime.date:
    days = _PERIOD_TO_DAYS.get(period, 366)
    return datetime.date.today() - datetime.timedelta(days=days)


def _fetch_price_history_from_yfinance(ticker_symbol: str, period: str) -> pd.DataFrame:
    """yfinanceから直接株価時系列を取得する（DBを経由しない生の取得処理）。"""
    logger.info("株価履歴リクエスト: ticker=%s period=%s", ticker_symbol, period)
    ticker = yf.Ticker(ticker_symbol)
    history = ticker.history(period=period)
    logger.info(
        "株価履歴レスポンス: ticker=%s data=%s",
        ticker_symbol,
        history.to_json(orient="records", date_format="iso"),
    )
    return history


def _upsert_price_history(session, ticker_symbol: str, history: pd.DataFrame) -> None:
    """historyの各日付をPriceHistoryへ追記する。既にDBにある日付は上書きしない
    （時系列を蓄積する方針のため）。"""
    if history.empty:
        return
    existing_dates = {
        row.date
        for row in session.query(PriceHistory.date).filter_by(ticker=ticker_symbol).all()
    }
    for index, row in history.iterrows():
        date_str = index.date().isoformat() if hasattr(index, "date") else str(index)
        if date_str in existing_dates:
            continue
        session.add(
            PriceHistory(
                ticker=ticker_symbol,
                date=date_str,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row["Volume"]),
            )
        )
        existing_dates.add(date_str)


def _load_price_history_from_db(session, ticker_symbol: str, period: str) -> pd.DataFrame:
    start_date = _period_to_start_date(period).isoformat()
    rows = (
        session.query(PriceHistory)
        .filter(PriceHistory.ticker == ticker_symbol, PriceHistory.date >= start_date)
        .order_by(PriceHistory.date)
        .all()
    )
    if not rows:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    return pd.DataFrame(
        {
            "Open": [r.open for r in rows],
            "High": [r.high for r in rows],
            "Low": [r.low for r in rows],
            "Close": [r.close for r in rows],
            "Volume": [r.volume for r in rows],
        },
        index=pd.to_datetime([r.date for r in rows]),
    )


def fetch_price_history(
    ticker_symbol: str, period: str = "1mo", session_factory=SessionLocal
) -> pd.DataFrame:
    """指定銘柄の株価時系列（OHLCV）を取得する。DB上の当該銘柄の最新日付が
    「本日から1日以内」ならDBから期間分を組み立てて返す。それより古い/データ無し
    ならyfinanceから_MAX_FETCH_PERIOD分を取得してPriceHistoryへ追記した上で、
    DBから期間分を組み立てて返す。"""
    with session_factory() as session:
        latest_date_str = (
            session.query(PriceHistory.date)
            .filter_by(ticker=ticker_symbol)
            .order_by(PriceHistory.date.desc())
            .limit(1)
            .scalar()
        )
        is_fresh = latest_date_str is not None and (
            datetime.date.today() - datetime.date.fromisoformat(latest_date_str)
        ).days <= 1

        if not is_fresh:
            history = _fetch_price_history_from_yfinance(ticker_symbol, _MAX_FETCH_PERIOD)
            _upsert_price_history(session, ticker_symbol, history)
            session.commit()

        return _load_price_history_from_db(session, ticker_symbol, period)


def fetch_fundamentals(ticker_symbol: str) -> dict:
    """指定銘柄のファンダメンタルズ指標（PER・PBR・配当利回り・ROE・売上高伸び率等）を取得する。"""
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
        "return_on_equity": info.get("returnOnEquity"),
        "revenue_growth": info.get("revenueGrowth"),
    }
    logger.info("fundamentalsレスポンス: ticker=%s data=%s", ticker_symbol, result)
    return result


def fetch_company_profile(ticker_symbol: str) -> dict:
    """指定銘柄の業種・事業内容をyfinance経由で取得する。"""
    logger.info("company profileリクエスト: ticker=%s", ticker_symbol)
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info
    result = {
        "ticker": ticker_symbol,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "business_summary": info.get("longBusinessSummary"),
    }
    logger.info("company profileレスポンス: ticker=%s data=%s", ticker_symbol, result)
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


def _to_pct(value: float | None) -> float | None:
    """yfinanceが小数（例: 0.155 = 15.5%）で返す指標を、パーセント表示用に100倍する。"""
    return None if value is None else value * 100


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
                    # returnOnEquity/revenueGrowthは小数（例: 0.155 = 15.5%）で
                    # 返るため、dividend_yieldと異なり100倍してパーセント表示用にする。
                    "roe_pct": _to_pct(data.get("return_on_equity")),
                    "revenue_growth_pct": _to_pct(data.get("revenue_growth")),
                }
            )
        df = pd.DataFrame(rows)
        write_cache(cache_dir, cache_key, df.to_json(orient="records", force_ascii=False))
    return df


def fetch_universe_price_histories(
    tickers: list[str],
    period: str,
    cache_dir: Path,
    fetch_price_history=fetch_price_history,
) -> dict[str, pd.Series]:
    """複数銘柄の終値時系列をまとめて取得し、{ticker: pd.Series} として返す。

    strategy_builderの簡易バックテスト・銘柄選定実行画面で、絞り込み後の
    銘柄群の株価をまとめて取得する用途に使う。取得失敗・空データの銘柄は
    結果から除外する。
    """
    cache_key = "universe-prices-" + hashlib.sha256(
        f"{period}-{'-'.join(sorted(tickers))}".encode("utf-8")
    ).hexdigest()[:12]
    cached = read_cache(cache_dir, cache_key)
    if cached is not None:
        payload = json.loads(cached)
        return {
            ticker: pd.Series(
                data["values"], index=pd.to_datetime(data["dates"]), name="Close"
            )
            for ticker, data in payload.items()
        }

    with log_duration(logger, f"ユニバース株価一括取得（{len(tickers)}銘柄, period={period}）"):
        results = map_concurrently(
            tickers, lambda ticker: fetch_price_history(ticker, period=period)
        )
        prices_by_ticker: dict[str, pd.Series] = {}
        for ticker in tickers:
            history = results[ticker]
            if isinstance(history, Exception) or history is None or history.empty:
                continue
            prices_by_ticker[ticker] = history["Close"]

        write_cache(
            cache_dir,
            cache_key,
            json.dumps(
                {
                    ticker: {
                        "dates": [d.isoformat() for d in series.index],
                        "values": [float(v) for v in series],
                    }
                    for ticker, series in prices_by_ticker.items()
                }
            ),
        )
    return prices_by_ticker
