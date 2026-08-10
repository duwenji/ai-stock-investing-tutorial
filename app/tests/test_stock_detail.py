import json
import logging

import pandas as pd

from common.cache import write_cache
from stock_detail.detail import generate_stock_detail


def _fake_history():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    return pd.DataFrame(
        {
            "Open": [99.0, 100.5, 101.5],
            "High": [101.0, 102.0, 103.0],
            "Low": [98.5, 100.0, 101.0],
            "Close": [100.0, 101.0, 102.0],
            "Volume": [1000, 1200, 900],
        },
        index=dates,
    )


def test_generate_stock_detail_builds_payload_from_dependencies(tmp_path):
    def fake_call_llm(prompt):
        if "市場での立ち位置" in prompt:
            return "テスト用のプロフィール要約です。"
        return "テスト用の総合コメントです。"

    result = generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=fake_call_llm,
        fetch_price_history=lambda ticker, period: _fake_history(),
        fetch_news=lambda ticker: [
            {"title": "ニュース1", "publisher": "社", "link": "http://example.com"}
        ],
        analyze_fundamentals=lambda ticker: {"per": 12.0, "pbr": 1.1, "dividend_yield": 2.5},
        analyze_technical=lambda history: {"ma_short": 101.0, "ma_long": 100.0, "signal": "強気"},
        fetch_company_profile=lambda ticker: {
            "ticker": ticker,
            "sector": "Consumer Cyclical",
            "industry": "Auto Manufacturers",
            "business_summary": "Test business summary.",
        },
    )

    assert result == {
        "ticker": "AAA.T",
        "name": "エーエー株式会社",
        "price_history": {
            "dates": ["2026-01-01T00:00:00", "2026-01-02T00:00:00", "2026-01-03T00:00:00"],
            "open": [99.0, 100.5, 101.5],
            "high": [101.0, 102.0, 103.0],
            "low": [98.5, 100.0, 101.0],
            "close": [100.0, 101.0, 102.0],
            "volume": [1000, 1200, 900],
        },
        "fundamentals": {"per": 12.0, "pbr": 1.1, "dividend_yield": 2.5},
        "technical": {"ma_short": 101.0, "ma_long": 100.0, "signal": "強気"},
        "news": [{"title": "ニュース1", "publisher": "社", "link": "http://example.com"}],
        "comment": "テスト用の総合コメントです。",
        "profile": {
            "sector": "Consumer Cyclical",
            "industry": "Auto Manufacturers",
            "profile_comment": "テスト用のプロフィール要約です。",
        },
    }


def test_generate_stock_detail_handles_empty_price_history(tmp_path):
    result = generate_stock_detail(
        "AAA.T",
        None,
        tmp_path,
        call_llm=lambda prompt: "コメント",
        fetch_price_history=lambda ticker, period: pd.DataFrame(
            {"Open": [], "High": [], "Low": [], "Close": [], "Volume": []}
        ),
        fetch_news=lambda ticker: [],
        analyze_fundamentals=lambda ticker: {"per": None, "pbr": None, "dividend_yield": None},
        analyze_technical=lambda history: {"ma_short": None, "ma_long": None, "signal": "データ不足"},
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": None, "industry": None, "business_summary": None
        },
    )

    assert result["price_history"] == {
        "dates": [],
        "open": [],
        "high": [],
        "low": [],
        "close": [],
        "volume": [],
    }
    assert result["news"] == []
    assert result["name"] is None
    assert result["profile"]["profile_comment"] == "事業内容の情報が取得できませんでした。"


def test_generate_stock_detail_uses_cache_and_skips_dependency_calls(tmp_path):
    call_count = {"n": 0}

    def counting_fetch_price_history(ticker, period):
        call_count["n"] += 1
        return _fake_history()

    generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=lambda prompt: "初回コメント",
        fetch_price_history=counting_fetch_price_history,
        fetch_news=lambda ticker: [],
        analyze_fundamentals=lambda ticker: {"per": 1, "pbr": 1, "dividend_yield": 1},
        analyze_technical=lambda history: {
            "ma_short": 1, "ma_long": 1, "signal": "強気", "rsi_series": [1.0]
        },
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
        },
    )
    assert call_count["n"] == 1

    def fail(*args, **kwargs):
        raise AssertionError("キャッシュヒット時は依存関数が呼ばれてはいけない")

    result = generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=fail,
        fetch_price_history=fail,
        fetch_news=fail,
        analyze_fundamentals=fail,
        analyze_technical=fail,
        fetch_company_profile=fail,
    )
    assert result["comment"] == "初回コメント"


def test_generate_stock_detail_ignores_stale_cache_missing_ohlcv(tmp_path):
    stale_payload = {
        "ticker": "AAA.T",
        "name": "エーエー株式会社",
        "price_history": {
            "dates": ["2026-01-01T00:00:00"],
            "close": [100.0],
        },
        "fundamentals": {"per": 1, "pbr": 1, "dividend_yield": 1},
        "technical": {"ma_short": 1, "ma_long": 1, "signal": "強気"},
        "news": [],
        "comment": "旧形式のキャッシュ",
    }
    write_cache(tmp_path, "stock-detail-AAA.T", json.dumps(stale_payload, ensure_ascii=False))

    result = generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=lambda prompt: "再生成後のコメント",
        fetch_price_history=lambda ticker, period: _fake_history(),
        fetch_news=lambda ticker: [],
        analyze_fundamentals=lambda ticker: {"per": 1, "pbr": 1, "dividend_yield": 1},
        analyze_technical=lambda history: {"ma_short": 1, "ma_long": 1, "signal": "強気"},
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
        },
    )

    assert result["comment"] == "再生成後のコメント"
    assert result["price_history"]["open"] == [99.0, 100.5, 101.5]


def test_generate_stock_detail_ignores_stale_cache_missing_profile(tmp_path):
    stale_payload = {
        "ticker": "AAA.T",
        "name": "エーエー株式会社",
        "price_history": {
            "dates": ["2026-01-01T00:00:00", "2026-01-02T00:00:00", "2026-01-03T00:00:00"],
            "open": [99.0, 100.5, 101.5],
            "high": [101.0, 102.0, 103.0],
            "low": [98.5, 100.0, 101.0],
            "close": [100.0, 101.0, 102.0],
            "volume": [1000, 1200, 900],
        },
        "fundamentals": {"per": 1, "pbr": 1, "dividend_yield": 1},
        "technical": {"ma_short": 1, "ma_long": 1, "signal": "強気"},
        "news": [],
        "comment": "profileキーが無い旧形式のキャッシュ",
    }
    write_cache(tmp_path, "stock-detail-AAA.T", json.dumps(stale_payload, ensure_ascii=False))

    result = generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=lambda prompt: "再生成後のコメント",
        fetch_price_history=lambda ticker, period: _fake_history(),
        fetch_news=lambda ticker: [],
        analyze_fundamentals=lambda ticker: {"per": 1, "pbr": 1, "dividend_yield": 1},
        analyze_technical=lambda history: {"ma_short": 1, "ma_long": 1, "signal": "強気"},
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
        },
    )

    assert result["comment"] == "再生成後のコメント"
    assert "profile" in result


def test_generate_stock_detail_ignores_stale_cache_missing_technical_series(tmp_path):
    stale_payload = {
        "ticker": "AAA.T",
        "name": "エーエー株式会社",
        "price_history": {
            "dates": ["2026-01-01T00:00:00", "2026-01-02T00:00:00", "2026-01-03T00:00:00"],
            "open": [99.0, 100.5, 101.5],
            "high": [101.0, 102.0, 103.0],
            "low": [98.5, 100.0, 101.0],
            "close": [100.0, 101.0, 102.0],
            "volume": [1000, 1200, 900],
        },
        "fundamentals": {"per": 1, "pbr": 1, "dividend_yield": 1},
        # RSI/ADX/ATRの時系列（rsi_series等）を追加する前の旧形式キャッシュ
        "technical": {"ma_short": 1, "ma_long": 1, "signal": "強気"},
        "news": [],
        "comment": "指標時系列が無い旧形式のキャッシュ",
        "profile": {"sector": "A", "industry": "B", "profile_comment": "C"},
    }
    write_cache(tmp_path, "stock-detail-AAA.T", json.dumps(stale_payload, ensure_ascii=False))

    result = generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=lambda prompt: "再生成後のコメント",
        fetch_price_history=lambda ticker, period: _fake_history(),
        fetch_news=lambda ticker: [],
        analyze_fundamentals=lambda ticker: {"per": 1, "pbr": 1, "dividend_yield": 1},
        analyze_technical=lambda history: {
            "ma_short": 1, "ma_long": 1, "signal": "強気", "rsi_series": [1.0]
        },
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
        },
    )

    assert result["comment"] == "再生成後のコメント"
    assert "rsi_series" in result["technical"]


def test_generate_stock_detail_translates_news_summaries_and_merges_summary_ja(tmp_path):
    def fake_call_llm(prompt):
        if "日本語に翻訳してください" in prompt:
            return "翻訳文1@@@翻訳文2"
        if "市場での立ち位置" in prompt:
            return "プロフィール要約"
        return "総合コメント"

    result = generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=fake_call_llm,
        fetch_price_history=lambda ticker, period: _fake_history(),
        fetch_news=lambda ticker: [
            {
                "title": "ニュース1",
                "publisher": "社1",
                "link": "http://example.com/1",
                "summary": "Summary 1",
            },
            {
                "title": "ニュース2",
                "publisher": "社2",
                "link": "http://example.com/2",
                "summary": "Summary 2",
            },
        ],
        analyze_fundamentals=lambda ticker: {"per": 12.0, "pbr": 1.1, "dividend_yield": 2.5},
        analyze_technical=lambda history: {"ma_short": 101.0, "ma_long": 100.0, "signal": "強気"},
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
        },
    )

    assert result["news"][0]["summary_ja"] == "翻訳文1"
    assert result["news"][1]["summary_ja"] == "翻訳文2"


def test_generate_stock_detail_skips_translation_call_when_no_news_have_summary(tmp_path):
    def fake_call_llm(prompt):
        assert "日本語に翻訳してください" not in prompt
        if "市場での立ち位置" in prompt:
            return "プロフィール要約"
        return "総合コメント"

    result = generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=fake_call_llm,
        fetch_price_history=lambda ticker, period: _fake_history(),
        fetch_news=lambda ticker: [
            {"title": "ニュース1", "publisher": "社", "link": "http://example.com"}
        ],
        analyze_fundamentals=lambda ticker: {"per": 12.0, "pbr": 1.1, "dividend_yield": 2.5},
        analyze_technical=lambda history: {"ma_short": 101.0, "ma_long": 100.0, "signal": "強気"},
        fetch_company_profile=lambda ticker: {
            "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
        },
    )

    assert "summary_ja" not in result["news"][0]


def test_generate_stock_detail_leaves_summary_ja_unset_when_translation_count_mismatches(
    tmp_path, caplog
):
    def fake_call_llm(prompt):
        if "日本語に翻訳してください" in prompt:
            return "翻訳文1"  # 2件を渡したのに1件しか返さない異常応答を模す
        if "市場での立ち位置" in prompt:
            return "プロフィール要約"
        return "総合コメント"

    with caplog.at_level(logging.WARNING, logger="stock_detail.detail"):
        result = generate_stock_detail(
            "AAA.T",
            "エーエー株式会社",
            tmp_path,
            call_llm=fake_call_llm,
            fetch_price_history=lambda ticker, period: _fake_history(),
            fetch_news=lambda ticker: [
                {
                    "title": "ニュース1",
                    "publisher": "社1",
                    "link": "http://example.com/1",
                    "summary": "Summary 1",
                },
                {
                    "title": "ニュース2",
                    "publisher": "社2",
                    "link": "http://example.com/2",
                    "summary": "Summary 2",
                },
            ],
            analyze_fundamentals=lambda ticker: {"per": 12.0, "pbr": 1.1, "dividend_yield": 2.5},
            analyze_technical=lambda history: {
                "ma_short": 101.0, "ma_long": 100.0, "signal": "強気"
            },
            fetch_company_profile=lambda ticker: {
                "ticker": ticker, "sector": "A", "industry": "B", "business_summary": "C"
            },
        )

    assert "summary_ja" not in result["news"][0]
    assert "summary_ja" not in result["news"][1]
    assert "一致しませんでした" in caplog.text


def test_generate_stock_detail_logs_duration_on_cache_miss(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger="stock_detail.detail"):
        generate_stock_detail(
            "AAA.T",
            "エーエー株式会社",
            tmp_path,
            call_llm=lambda prompt: "コメント",
            fetch_price_history=lambda ticker, period: _fake_history(),
            fetch_news=lambda ticker: [],
            analyze_fundamentals=lambda ticker: {},
            analyze_technical=lambda history: {},
            fetch_company_profile=lambda ticker: {
                "ticker": ticker, "sector": None, "industry": None, "business_summary": None
            },
        )

    assert "銘柄詳細生成（AAA.T）" in caplog.text
    assert "を開始" in caplog.text
    assert "が完了しました" in caplog.text
