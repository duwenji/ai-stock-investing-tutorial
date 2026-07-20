import pandas as pd

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
    result = generate_stock_detail(
        "AAA.T",
        "エーエー株式会社",
        tmp_path,
        call_llm=lambda prompt: "テスト用の総合コメントです。",
        fetch_price_history=lambda ticker, period: _fake_history(),
        fetch_news=lambda ticker: [
            {"title": "ニュース1", "publisher": "社", "link": "http://example.com"}
        ],
        analyze_fundamentals=lambda ticker: {"per": 12.0, "pbr": 1.1, "dividend_yield": 2.5},
        analyze_technical=lambda history: {"ma_short": 101.0, "ma_long": 100.0, "signal": "強気"},
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
        analyze_technical=lambda history: {"ma_short": 1, "ma_long": 1, "signal": "強気"},
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
    )
    assert result["comment"] == "初回コメント"
