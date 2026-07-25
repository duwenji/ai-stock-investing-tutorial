import pandas as pd

from sector_analysis.network import build_mermaid_lead_lag_graph


def _make_pairs_df(rows: list[dict]) -> pd.DataFrame:
    columns = [
        "sector_x",
        "sector_y",
        "band",
        "dominant_lag_days",
        "mean_coherence",
        "leading_sector",
        "lagging_sector",
        "lag_days_abs",
    ]
    return pd.DataFrame(rows, columns=columns)


def test_build_mermaid_lead_lag_graph_filters_by_coherence_threshold():
    pairs_df = _make_pairs_df(
        [
            {
                "sector_x": "A",
                "sector_y": "B",
                "band": "中期",
                "dominant_lag_days": 5.0,
                "mean_coherence": 0.8,
                "leading_sector": "A",
                "lagging_sector": "B",
                "lag_days_abs": 5.0,
            },
            {
                "sector_x": "C",
                "sector_y": "D",
                "band": "中期",
                "dominant_lag_days": 2.0,
                "mean_coherence": 0.3,
                "leading_sector": "C",
                "lagging_sector": "D",
                "lag_days_abs": 2.0,
            },
        ]
    )

    result = build_mermaid_lead_lag_graph(pairs_df, band="中期", coherence_threshold=0.5)

    assert result is not None
    assert "flowchart" in result
    assert '"A"' in result
    assert '"B"' in result
    assert '"C"' not in result
    assert '"D"' not in result


def test_build_mermaid_lead_lag_graph_filters_by_band():
    pairs_df = _make_pairs_df(
        [
            {
                "sector_x": "A",
                "sector_y": "B",
                "band": "短期",
                "dominant_lag_days": 5.0,
                "mean_coherence": 0.9,
                "leading_sector": "A",
                "lagging_sector": "B",
                "lag_days_abs": 5.0,
            }
        ]
    )

    result = build_mermaid_lead_lag_graph(pairs_df, band="中期", coherence_threshold=0.5)

    assert result is None


def test_build_mermaid_lead_lag_graph_returns_none_when_no_edges_meet_threshold():
    pairs_df = _make_pairs_df(
        [
            {
                "sector_x": "A",
                "sector_y": "B",
                "band": "中期",
                "dominant_lag_days": 2.0,
                "mean_coherence": 0.1,
                "leading_sector": "A",
                "lagging_sector": "B",
                "lag_days_abs": 2.0,
            }
        ]
    )

    result = build_mermaid_lead_lag_graph(pairs_df, band="中期", coherence_threshold=0.5)

    assert result is None


def test_build_mermaid_lead_lag_graph_returns_none_for_empty_dataframe():
    pairs_df = _make_pairs_df([])

    result = build_mermaid_lead_lag_graph(pairs_df, band="中期", coherence_threshold=0.5)

    assert result is None


def test_build_mermaid_lead_lag_graph_uses_synthetic_node_ids_for_special_characters():
    pairs_df = _make_pairs_df(
        [
            {
                "sector_x": "電機・精密",
                "sector_y": "情報通信・サービスその他",
                "band": "中期",
                "dominant_lag_days": 3.0,
                "mean_coherence": 0.9,
                "leading_sector": "電機・精密",
                "lagging_sector": "情報通信・サービスその他",
                "lag_days_abs": 3.0,
            }
        ]
    )

    result = build_mermaid_lead_lag_graph(pairs_df, band="中期", coherence_threshold=0.5)

    assert result is not None
    # ノード定義行にラベルとして業種名が入る
    assert '["電機・精密"]' in result
    assert '["情報通信・サービスその他"]' in result
    # エッジ行はS0 -->|...| S1のような合成IDを使い、業種名を直接IDに使わない
    edge_lines = [line for line in result.splitlines() if "-->" in line]
    assert len(edge_lines) == 1
    assert edge_lines[0].strip().startswith("S")
    assert "電機・精密 -->" not in result
