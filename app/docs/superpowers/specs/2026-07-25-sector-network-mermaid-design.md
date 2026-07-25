# セクター間ネットワーク（全ペア俯瞰・Mermaid表示）設計書

## 概要・目的

[セクターローテーション ウェーブレット分析](2026-07-21-sector-rotation-wavelet-design.md)は、v1では選択した2業種のみをオンデマンドでウェーブレット計算し、時間×周期のヒートマップで詳細を可視化する設計だった。同設計書では「136業種ペア全体を一括でウェーブレット計算する機能」を将来課題として明示的にスコープ外としていた。

本機能では、その将来課題を実装する。17業種・全136ペアについてウェーブレット分析（クロスウェーブレット・コヒーレンスと符号付きラグ）を一括計算し、周期帯（短期・中期・長期）ごとに「今どの業種が誰をリードしているか」の全体構造をMermaidの有向グラフとして俯瞰できるようにする。

既存の2業種選択式ドリルダウン（時間×周期の詳細ヒートマップ）は変更せず、そのまま残す。役割分担は次の通り: **全体構造の俯瞰はMermaidネットワーク図、特定ペアの時間変化の詳細は既存のヒートマップ**。

既存タブと同じ設計方針を踏襲する: 事実データの計算はPython側で行い、AIコメントは新設しない。売買の推奨・指示は行わない（[DISCLAIMER.md](../../../../DISCLAIMER.md)準拠）。

## スコープ

- v1で実装する:
  - `sector_analysis/wavelet.py`に`compute_all_pairs_dominant_lag`を追加: 全業種ペアのウェーブレット計算を一括実行し、周期帯ごとに直近期間のコヒーレンス加重平均ラグに集約する
  - `sector_analysis/network.py`（新設）: 集約結果からMermaidの有向グラフ定義文字列を生成する`build_mermaid_lead_lag_graph`
  - `app.py`: セクターローテーションタブの「分析を実行」フローに全ペア一括計算を統合し、「業種間ネットワーク（全ペア俯瞰）」セクションを追加（周期帯選択・コヒーレンス閾値スライダー・Mermaidグラフ表示）
  - 既存の`sector-rotation-*`キャッシュpayloadに`network_pairs`を追加
  - 新規依存追加なし: Mermaidの描画は`st.components.v1.html`でmermaid.js（CDN読み込み）を埋め込む自前ヘルパー関数で行う（`streamlit-mermaid`パッケージは`altair<5`を要求し、既存の全Altairチャート機能に影響するため不採用。詳細は「UI設計」節を参照）
- v1で実装しない（将来課題）:
  - Mermaidグラフのエッジクリックによる、既存2業種ドリルダウンへの選択自動反映
  - 個別ペアの統計的有意性検定（既存ウェーブレット機能の将来課題を踏襲）
  - 周期帯をまたいだ集約表示（3帯を1つの図に統合する等）

## コアロジック — `sector_analysis/wavelet.py`への追加

### `compute_all_pairs_dominant_lag`

```python
def compute_all_pairs_dominant_lag(
    sector_returns: dict[str, pd.Series],
    window_days: int = 20,
) -> pd.DataFrame:
    """全業種ペアについてウェーブレット分析を一括実行し、周期帯ごとに
    直近window_days営業日のコヒーレンス加重平均ラグに集約する。

    個別ペアの計算で例外が発生した場合、またはデータ不足で
    compute_cross_wavelet_lead_lagが空のDataFrameを返した場合は、
    そのペアを結果から除外し処理を継続する。
    """
```

処理内容:
1. `itertools.combinations(sorted(sector_returns.keys()), 2)`で全ペアを列挙する（業種数nに対しC(n,2)ペア、n=17なら136ペア）
2. 各ペアに対し`compute_cross_wavelet_lead_lag(series_x, series_y, sector_x, sector_y)`を実行する。例外発生時はそのペアをスキップする
3. 結果が空でなければ、各`band`（短期/中期/長期）ごとに、`date`列のユニーク値を昇順ソートし末尾`window_days`件を求め、該当する日付に属する全ての行（1日付につき複数周期のスケールを含む）に絞り込む
4. 絞り込んだ行に対し、`lag_days`をコヒーレンスで加重平均した`dominant_lag_days`と、単純平均の`mean_coherence`を計算する（コヒーレンス合計が0の場合はそのband・ペアの組を除外する）
5. `leading_sector`/`lagging_sector`/`lag_days_abs`を`dominant_lag_days`の符号から算出する（`dominant_lag_days >= 0`なら`sector_x`が先行）
6. tidy long-form DataFrameとして返す。列: `sector_x`, `sector_y`, `band`, `dominant_lag_days`, `mean_coherence`, `leading_sector`, `lagging_sector`, `lag_days_abs`

### 依存関係

- 既存の`compute_cross_wavelet_lead_lag`をそのまま呼び出す。新規の計算ロジック依存追加はなし

## コアロジック — `sector_analysis/network.py`（新設）

### `build_mermaid_lead_lag_graph`

```python
def build_mermaid_lead_lag_graph(
    pairs_df: pd.DataFrame,
    band: str,
    coherence_threshold: float,
) -> str | None:
    """周期帯・コヒーレンス閾値でフィルタした業種間リード・ラグ関係を
    Mermaidの有向グラフ定義（flowchart LR）として返す。

    フィルタ後にエッジが0件の場合はNoneを返す。
    """
```

処理内容:
1. `pairs_df`を`band`列で絞り込み、さらに`mean_coherence >= coherence_threshold`で絞り込む
2. フィルタ後が空なら`None`を返す
3. 登場する業種名（`leading_sector`/`lagging_sector`の和集合）を昇順ソートし、`S0`, `S1`, ...の合成ノードIDを割り当てる（業種名に含まれる`・`等の文字はMermaidのノードIDとして使えないため、`S0["電機・精密"]`の形でラベルとして表示する）
4. 各行を`{leading_id} -->|"{lag_days_abs:.1f}日 / coh {mean_coherence:.2f}"| {lagging_id}`の形式でエッジとして出力する
5. `flowchart LR`ヘッダ、ノード定義、エッジ定義を結合した文字列を返す

## UI設計 — `app.py`

### Mermaid描画方法

StreamlitはMermaidをネイティブ描画できず、`streamlit-mermaid`パッケージは`altair<5`を要求するため（既存の全Altairチャート機能が`altair>=6`に依存しており、導入すると既存チャートに影響するリスクがあるため）採用しない。新規pip依存を追加せず、`st.components.v1.html`でmermaid.js（CDN読み込み）を埋め込む自前のヘルパー関数`_render_mermaid`を実装する:

```python
import streamlit.components.v1 as components


def _render_mermaid(code: str, height: int = 400) -> None:
    """Mermaidコード文字列を、CDN経由のmermaid.jsを使ってHTML埋め込みで描画する。"""
    html = f"""
    <div class="mermaid">{code}</div>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <script>mermaid.initialize({{ startOnLoad: true }});</script>
    """
    components.html(html, height=height, scrolling=True)
```

- 業種名（`network_df`由来）にHTML特殊文字（`<`, `>`, `&`）は含まれない前提とする（`SECTOR_MAP`は固定の17業種区分のみ）。ユーザー入力に由来する文字列ではないためエスケープ処理は行わない
- mermaid.jsの読み込みにはインターネット接続が必要（既存の株価データ取得（yfinance）・LLM呼び出しですでにインターネット接続前提のため、新たな制約ではない）

### 「分析を実行」フローへの統合

既存の`compute_lead_lag_pairs`呼び出しの直後に、全ペア一括計算を追加する:

```python
pairs = compute_lead_lag_pairs(sector_returns, max_lag_days=20)
with st.spinner("ネットワーク図データを計算中（136ペア）..."):
    network_pairs = compute_all_pairs_dominant_lag(sector_returns)
comments = generate_sector_rotation_comments(pairs[:5], call_llm=call_llm)
payload = {
    "pairs": pairs,
    "skipped_tickers": skipped_tickers,
    "excluded_sectors": excluded_sectors,
    "comments": comments,
    "sector_returns": serialize_sector_returns(sector_returns),
    "network_pairs": network_pairs.to_dict("records"),
}
```

### 新セクション「業種間ネットワーク（全ペア俯瞰）」

既存の「相関上位5ペアのAIコメント」セクションの直後、既存の2業種選択ウェーブレット・ドリルダウンの直前に配置する。

```python
st.subheader("業種間ネットワーク（全ペア俯瞰）")
st.caption(
    "全業種ペアについて、直近20営業日のウェーブレット分析結果を集約し、"
    "周期の長さ（短期・中期・長期）ごとに、どの業種が誰をリードしているかを俯瞰できます。"
)

network_df = pd.DataFrame(payload["network_pairs"])
col_a, col_b = st.columns(2)
with col_a:
    network_band = st.selectbox("周期帯", ["短期", "中期", "長期"], index=1, key="network_band")
with col_b:
    coherence_threshold = st.slider(
        "コヒーレンス閾値（これ以上のペアのみ表示）", 0.0, 1.0, 0.5, 0.05, key="network_threshold"
    )

mermaid_code = build_mermaid_lead_lag_graph(network_df, network_band, coherence_threshold)
if mermaid_code is None:
    st.info("十分な確信度を持つ関係が見つかりませんでした。閾値を下げてみてください。")
else:
    _render_mermaid(mermaid_code)
```

- 周期帯・閾値のデフォルトは中期・0.5
- `network_df`が空（`payload["network_pairs"]`が空リスト）の場合も`build_mermaid_lead_lag_graph`が`None`を返すため、上記の分岐でそのまま処理される

## データ変更 — キャッシュpayloadへの`network_pairs`追加

既存の`sector_returns`キー追加時と同じ移行パターンを踏襲する。キャッシュ読み込み時に`"network_pairs" not in payload`であればキャッシュミス扱いとして再計算する:

```python
payload = json.loads(cached_payload) if cached_payload is not None else None
if payload is not None and ("sector_returns" not in payload or "network_pairs" not in payload):
    payload = None  # 旧スキーマのキャッシュは再計算して移行する
```

## エラーハンドリング

| 事象 | 挙動 |
| --- | --- |
| 個別ペアのウェーブレット計算で例外発生 | そのペアを`network_pairs`から除外、他ペアの処理は継続 |
| 個別ペアの共通非欠損データ数が不足（`compute_cross_wavelet_lead_lag`が空を返す） | そのペアを`network_pairs`から除外 |
| 選択した周期帯・閾値でフィルタ後のエッジが0件 | 「十分な確信度を持つ関係が見つかりませんでした」と表示、グラフ描画をスキップ |
| 旧スキーマのキャッシュ（`network_pairs`または`sector_returns`なし） | キャッシュミス扱いとして再計算 |

## テスト方針

- `tests/test_sector_network.py`（新設）:
  - `compute_all_pairs_dominant_lag`: 人工的に既知のラグを仕込んだ3業種の系列で、C(3,2)=3ペア分の結果が返り、各ペアの`leading_sector`/`dominant_lag_days`の符号・大きさが期待通りであることを検証
  - `compute_all_pairs_dominant_lag`: 1ペアの系列を意図的にデータ不足にした場合、そのペアが結果から除外され、他ペアは正常に計算されることを検証（例外を握りつぶして継続することの確認）
  - `build_mermaid_lead_lag_graph`: 閾値以上のペアのみがエッジとして出力され、閾値未満のペアが含まれないことを検証
  - `build_mermaid_lead_lag_graph`: 業種名に`・`を含むケースでノードIDとラベルが分離されて出力され、Mermaid構文として業種名がそのままIDに使われないことを検証
  - `build_mermaid_lead_lag_graph`: フィルタ後にエッジが0件の場合`None`を返すことを検証
- UI（Mermaid描画・スライダー操作）は既存方針通り自動テスト対象外。`uv run python -m streamlit run app.py`で手動確認する

## v1スコープ外（将来課題）

- Mermaidグラフのエッジクリックによる既存2業種ドリルダウンへの選択自動反映
- 個別ペアの統計的有意性検定
- 周期帯をまたいだ統合表示
