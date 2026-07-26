"""個別銘柄の詳細画面向けに、株価・ファンダメンタルズ・テクニカル分析・
ニュース・LLMによる講評コメントを1つにまとめて生成するモジュール。"""

import json
import logging
from pathlib import Path

from analysis_agents.fundamental_agent import (
    analyze_fundamentals as default_analyze_fundamentals,
)
from analysis_agents.technical_agent import analyze_technical as default_analyze_technical
from common.cache import read_cache, write_cache
from common.logging_config import log_duration
from data_api.llm_client import call_llm as default_call_llm
from data_api.stock_price_api import fetch_news as default_fetch_news
from data_api.stock_price_api import fetch_price_history as default_fetch_price_history
from prompt_patterns.stock_detail import build_stock_detail_prompt

logger = logging.getLogger(__name__)


def generate_stock_detail(
    ticker: str,
    name: str | None,
    cache_dir: Path,
    call_llm=default_call_llm,
    fetch_price_history=default_fetch_price_history,
    fetch_news=default_fetch_news,
    analyze_fundamentals=default_analyze_fundamentals,
    analyze_technical=default_analyze_technical,
) -> dict:
    """指定銘柄の詳細情報一式を組み立てる。

    依存する各取得・分析処理は引数でデフォルト実装を上書きできるようにし、
    テスト時にモック差し替えしやすくしている。
    """
    # 生成にはLLM呼び出しを含みコストが高いため、キャッシュがあれば再利用する。
    # 旧バージョンのキャッシュ（price_historyにopenキーが無いもの）は無効として扱う。
    cache_key = f"stock-detail-{ticker}"
    cached = read_cache(cache_dir, cache_key)
    if cached is not None:
        payload = json.loads(cached)
        if "open" in payload["price_history"]:
            return payload

    with log_duration(logger, f"銘柄詳細生成（{ticker}）"):
        # 移動平均線（特に75日線）の計算バッファとして、表示に必要な6ヶ月分より
        # 長めの2年分を取得する。
        history = fetch_price_history(ticker, period="2y")
        fundamentals = analyze_fundamentals(ticker)
        technical = analyze_technical(history)
        news = fetch_news(ticker)

        # チャート描画用に、pandasのDataFrameをJSONシリアライズ可能な
        # プレーンな辞書（日付文字列＋各系列のリスト）に変換する
        if history.empty:
            price_history = {
                "dates": [], "open": [], "high": [], "low": [], "close": [], "volume": []
            }
        else:
            price_history = {
                "dates": [d.isoformat() for d in history.index],
                "open": history["Open"].tolist(),
                "high": history["High"].tolist(),
                "low": history["Low"].tolist(),
                "close": history["Close"].tolist(),
                "volume": history["Volume"].tolist(),
            }

        # ここまでに集めたファンダメンタルズ・テクニカル・ニュースをプロンプトに
        # まとめ、LLMに銘柄の講評コメントを生成させる
        prompt = build_stock_detail_prompt(ticker, name, fundamentals, technical, news)
        comment = call_llm(prompt)

        payload = {
            "ticker": ticker,
            "name": name,
            "price_history": price_history,
            "fundamentals": fundamentals,
            "technical": technical,
            "news": news,
            "comment": comment,
        }
        write_cache(cache_dir, cache_key, json.dumps(payload, ensure_ascii=False))
        return payload
