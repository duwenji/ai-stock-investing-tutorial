"""個別銘柄の詳細画面向けに、株価・ファンダメンタルズ・テクニカル分析・
ニュース・LLMによる講評コメント・基本情報（業種・市場ポジション）を
1つにまとめて生成するモジュール。

本モジュール自体はst.*を直接呼ばない。呼び出し元のapp_tabs/shared.py
（show_stock_detail_dialog）がst.spinner()の中でgenerate_stock_detail()を呼び、
処理中であることをユーザーに示す。
"""

import json
import logging
import uuid
from pathlib import Path

from analysis_agents.fundamental_agent import (
    analyze_fundamentals as default_analyze_fundamentals,
)
from analysis_agents.technical_agent import analyze_technical as default_analyze_technical
from common.ai_generation_log import log_ai_generation
from common.cache import read_cache, write_cache
from common.logging_config import log_duration
from data_api.llm_client import call_llm as default_call_llm
from data_api.stock_price_api import fetch_company_profile as default_fetch_company_profile
from data_api.stock_price_api import fetch_news as default_fetch_news
from data_api.stock_price_api import fetch_price_history as default_fetch_price_history
from db.engine import SessionLocal
from prompt_patterns.stock_detail import (
    build_company_profile_prompt,
    build_news_summary_translation_prompt,
    build_news_title_translation_prompt,
    build_stock_detail_prompt,
)

logger = logging.getLogger(__name__)

_NO_PROFILE_MESSAGE = "事業内容の情報が取得できませんでした。"


def generate_stock_detail(
    ticker: str,
    name: str | None,
    cache_dir: Path,
    call_llm=default_call_llm,
    fetch_price_history=default_fetch_price_history,
    fetch_news=default_fetch_news,
    analyze_fundamentals=default_analyze_fundamentals,
    analyze_technical=default_analyze_technical,
    fetch_company_profile=default_fetch_company_profile,
    user_id: int | None = None,
    session_factory=SessionLocal,
) -> dict:
    """指定銘柄の詳細情報一式を組み立てる。

    依存する各取得・分析処理は引数でデフォルト実装を上書きできるようにし、
    テスト時にモック差し替えしやすくしている。
    """
    # 生成にはLLM呼び出しを含みコストが高いため、キャッシュがあれば再利用する。
    # ここではst.cache_data（実行プロセスのメモリ上、rerun間だけ有効）ではなく
    # common.cacheによる自前のディスクキャッシュを使っている。アプリ再起動後も
    # 有効にしたい／全ユーザーで共有したい、という理由から@st.cache_dataではなく
    # この方式を選んでいる。
    # 旧バージョンのキャッシュ（price_historyにopenキーが無い、profileキーが
    # 無い、またはtechnicalにRSI/ADX/ATRの時系列が無いもの）は無効として扱う。
    cache_key = f"stock-detail-{ticker}"
    cached = read_cache(cache_dir, cache_key)
    if cached is not None:
        payload = json.loads(cached)
        if (
            "open" in payload["price_history"]
            and "profile" in payload
            and "rsi_series" in payload["technical"]
        ):
            return payload

    with log_duration(logger, f"銘柄詳細生成（{ticker}）"):
        # 移動平均線（特に75日線）の計算バッファとして、表示に必要な6ヶ月分より
        # 長めの2年分を取得する。
        history = fetch_price_history(ticker, period="2y")
        fundamentals = analyze_fundamentals(ticker)
        technical = analyze_technical(history)
        news = fetch_news(ticker)

        # 画面表示専用に、タイトルと要約をまとめて1回ずつLLM呼び出しで日本語訳する。
        # これにより、英語のタイトル/要約がそのまま表示されることを防ぐ。
        # 件数がズレた場合（LLMが指示通りの件数を返さなかった場合）は
        # 誤った記事に翻訳を割り当てるリスクを避け、翻訳結果を付けずに諦める。
        title_indices = [i for i, item in enumerate(news) if item.get("title")]
        if title_indices:
            title_prompt = build_news_title_translation_prompt(
                [news[i]["title"] for i in title_indices]
            )
            translated_titles = [part.strip() for part in call_llm(title_prompt).split("@@@")]
            if len(translated_titles) == len(title_indices):
                for index, translated in zip(title_indices, translated_titles):
                    news[index]["title_ja"] = translated
            else:
                logger.warning(
                    "ニュースタイトルの翻訳件数が入力件数と一致しませんでした"
                    "（入力%d件、応答%d件）: ticker=%s",
                    len(title_indices),
                    len(translated_titles),
                    ticker,
                )

        indices_with_summary = [i for i, item in enumerate(news) if item.get("summary")]
        if indices_with_summary:
            translation_prompt = build_news_summary_translation_prompt(
                [news[i]["summary"] for i in indices_with_summary]
            )
            translated_text = call_llm(translation_prompt)
            translated_summaries = [part.strip() for part in translated_text.split("@@@")]
            if len(translated_summaries) == len(indices_with_summary):
                for index, translated in zip(indices_with_summary, translated_summaries):
                    news[index]["summary_ja"] = translated
            else:
                logger.warning(
                    "ニュース要約の翻訳件数が入力件数と一致しませんでした"
                    "（入力%d件、応答%d件）: ticker=%s",
                    len(indices_with_summary),
                    len(translated_summaries),
                    ticker,
                )

        company_profile = fetch_company_profile(ticker)

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
        detail_session_id = uuid.uuid4().hex
        log_ai_generation(
            detail_session_id,
            "stock_detail_comment",
            facts={"fundamentals": fundamentals, "technical": technical, "news": news},
            prompt=prompt,
            ai_output=comment,
            turn_index=0,
            ticker=ticker,
            user_id=user_id,
            session_feature="stock_detail",
            session_factory=session_factory,
        )

        # 事業内容の説明が無ければLLMを呼ばず、固定メッセージにする
        business_summary = company_profile.get("business_summary")
        if business_summary:
            profile_prompt = build_company_profile_prompt(
                ticker,
                name,
                company_profile.get("sector"),
                company_profile.get("industry"),
                business_summary,
            )
            profile_comment = call_llm(profile_prompt)
            log_ai_generation(
                detail_session_id,
                "stock_detail_profile",
                facts={
                    "sector": company_profile.get("sector"),
                    "industry": company_profile.get("industry"),
                    "business_summary": business_summary,
                },
                prompt=profile_prompt,
                ai_output=profile_comment,
                turn_index=1,
                ticker=ticker,
                user_id=user_id,
                session_factory=session_factory,
            )
        else:
            profile_comment = _NO_PROFILE_MESSAGE

        payload = {
            "ticker": ticker,
            "name": name,
            "price_history": price_history,
            "fundamentals": fundamentals,
            "technical": technical,
            "news": news,
            "comment": comment,
            "profile": {
                "sector": company_profile.get("sector"),
                "industry": company_profile.get("industry"),
                "profile_comment": profile_comment,
            },
        }
        write_cache(cache_dir, cache_key, json.dumps(payload, ensure_ascii=False))
        return payload
