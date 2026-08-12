"""業種間のリード・ラグ関係をMermaidのフローチャート形式に変換するモジュール。

wavelet.pyが計算した「どの業種がどの業種を何日先行するか」というデータを、
セクタータブのネットワーク図（Mermaid diagram）としてそのまま描画できる
テキスト形式に組み立てる。実際の描画はapp_tabs/sector側でst.markdown等に渡して行う。
"""

import pandas as pd


def build_mermaid_lead_lag_graph(
    pairs_df: pd.DataFrame,
    band: str,
    coherence_threshold: float,
) -> str | None:
    """周期帯・コヒーレンス閾値でフィルタした業種間リード・ラグ関係を
    Mermaidの有向グラフ定義（flowchart LR）として返す。

    pairs_dfはcompute_all_pairs_dominant_lagの戻り値と同じ列構成を持つ
    （sector_x, sector_y, band, dominant_lag_days, mean_coherence,
    leading_sector, lagging_sector, lag_days_abs）。
    フィルタ後にエッジが0件の場合はNoneを返す。
    """
    if pairs_df.empty:
        return None

    # コヒーレンス（周期的な連動の強さ）が閾値未満のペアはノイズに近く
    # 信頼できないリード・ラグ関係とみなし、グラフに含めない
    filtered = pairs_df[
        (pairs_df["band"] == band) & (pairs_df["mean_coherence"] >= coherence_threshold)
    ]
    if filtered.empty:
        return None

    # 業種名は「・」等Mermaidのノードid規則に使えない文字を含みうるため、
    # S0, S1, ...の合成idを割り当て、業種名はラベルとしてのみ使う
    sectors = sorted(set(filtered["leading_sector"]) | set(filtered["lagging_sector"]))
    node_ids = {sector: f"S{i}" for i, sector in enumerate(sectors)}

    lines = ["flowchart LR"]
    for sector, node_id in node_ids.items():
        lines.append(f'    {node_id}["{sector}"]')
    for _, row in filtered.iterrows():
        leading_id = node_ids[row["leading_sector"]]
        lagging_id = node_ids[row["lagging_sector"]]
        # 矢印は「先行業種→遅行業種」の向きに描画し、ラベルには何営業日
        # 先行するか（lag_days_abs）とその関係の確からしさ（coherence）を添える
        label = f'{row["lag_days_abs"]:.1f}日 / coh {row["mean_coherence"]:.2f}'
        lines.append(f'    {leading_id} -->|"{label}"| {lagging_id}')

    return "\n".join(lines)
