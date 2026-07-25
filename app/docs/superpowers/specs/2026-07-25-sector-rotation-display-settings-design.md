# セクターローテーション 表示コンテンツのユーザ設定機能 設計書

## 概要・目的

セクターローテーションタブ（`app.py`の`tab_sector`）は、ヒートマップ・リード/ラグ表・AIコメント・ネットワーク図・ウェーブレット分析と、機能追加を重ねた結果セクション数が多く縦に長くなっている。すべてのセクションを常に必要とするとは限らないため、ユーザーがセクション単位で表示/非表示を選べるようにする。

設定はファイルに永続化し、ブラウザを閉じて再度アプリを起動しても前回の表示設定が引き継がれるようにする。

既存の「分析を実行」ロジック（データ取得・全セクション分の計算）は変更しない。今回はあくまで**表示側の絞り込み**のみを対象とし、非表示にしたセクションの計算をスキップする最適化は将来課題とする（既存ロジックがシンプルなまま保たれ、セクション間の依存関係（例: ウェーブレット分析のデフォルト業種選択が`pairs`に依存する等）を壊さないため）。

## スコープ

- v1で実装する:
  - `sector_analysis/display_settings.py`（新設）: 表示設定のデフォルト値定義・JSON読み込み・保存
  - `data/sector_display_settings.json`（新規データファイル、`holdings.json`と同じ`DATA_DIR`配下）
  - `app.py`の`tab_sector`先頭に「表示設定」expanderを追加し、5つのチェックボックスでセクションの表示/非表示を切り替え。変更時に即座にファイルへ自動保存する
  - 既存の5セクション（ヒートマップ／リード・ラグ上位ペア表／AIコメント／ネットワーク図／ウェーブレット分析）をそれぞれ設定値で`if`分岐して表示制御する
- v1で実装しない（将来課題）:
  - 非表示セクションの計算スキップ（高速化）
  - セクションの表示順序のカスタマイズ
  - 他タブ（ポートフォリオ・スクリーニング等）への同様の設定機能の展開

## データ設計 — `sector_analysis/display_settings.py`

`portfolio_management/storage.py`の`load_holdings`/`save_holdings`と同じ設計パターンを踏襲する。

```python
"""セクターローテーションタブの表示セクション設定をJSONファイルとして
永続化・読み込みするモジュール。"""

import json
from pathlib import Path

DEFAULT_SECTOR_DISPLAY_SETTINGS: dict[str, bool] = {
    "heatmap": True,
    "pairs_table": True,
    "ai_comments": True,
    "network_diagram": True,
    "wavelet_analysis": True,
}


def load_sector_display_settings(path: Path) -> dict[str, bool]:
    """表示設定をJSONファイルから読み込む。ファイルが存在しない、JSONとして
    壊れている、あるいは想定外の形式（辞書でない）の場合はデフォルト設定を
    返す。デフォルトにないキーは無視し、デフォルトにあるが保存データにない
    キーはデフォルト値で補う（将来セクションが増えても既存ファイルで壊れない）。"""
    settings = dict(DEFAULT_SECTOR_DISPLAY_SETTINGS)
    if not path.exists():
        return settings
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return settings
    if not isinstance(data, dict):
        return settings
    for key in settings:
        if key in data and isinstance(data[key], bool):
            settings[key] = data[key]
    return settings


def save_sector_display_settings(path: Path, settings: dict[str, bool]) -> None:
    """表示設定をJSONファイルとして保存する。保存先ディレクトリが存在しない
    場合は作成する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
```

## UI設計 — `app.py`

### パス定義

既存の`HOLDINGS_PATH`定義の並びに追加する:

```python
SECTOR_DISPLAY_SETTINGS_PATH = DATA_DIR / "sector_display_settings.json"
```

### 「表示設定」expander

`tab_sector`冒頭、既存の説明キャプションの直後・期間選択（`sector_period`）の前に配置する。チェックボックスの値が読み込み時の設定と異なれば、その場でファイルへ保存する（保存ボタンなし、他のチェックボックス操作と同じ即時反映の感覚に揃える）。

```python
with tab_sector:
    st.header("セクターローテーション")
    st.caption(...)  # 既存のまま

    display_settings = load_sector_display_settings(SECTOR_DISPLAY_SETTINGS_PATH)
    with st.expander("表示設定"):
        st.caption("チェックを外すとそのセクションを非表示にできます（設定は次回起動時も保持されます）。")
        new_settings = {
            "heatmap": st.checkbox(
                "業種間相関ヒートマップ",
                value=display_settings["heatmap"],
                key="sector_show_heatmap",
            ),
            "pairs_table": st.checkbox(
                "リード・ラグ上位ペア",
                value=display_settings["pairs_table"],
                key="sector_show_pairs_table",
            ),
            "ai_comments": st.checkbox(
                "相関上位5ペアのAIコメント",
                value=display_settings["ai_comments"],
                key="sector_show_ai_comments",
            ),
            "network_diagram": st.checkbox(
                "業種間ネットワーク（全ペア俯瞰）",
                value=display_settings["network_diagram"],
                key="sector_show_network",
            ),
            "wavelet_analysis": st.checkbox(
                "ウェーブレット分析",
                value=display_settings["wavelet_analysis"],
                key="sector_show_wavelet",
            ),
        }
        if new_settings != display_settings:
            save_sector_display_settings(SECTOR_DISPLAY_SETTINGS_PATH, new_settings)
            display_settings = new_settings

    sector_period = st.selectbox(...)  # 既存のまま
    ...
```

expanderは初期状態では閉じておく（`expanded`引数を指定しないデフォルト＝折りたたみ）。普段は邪魔にならず、必要なときだけ開く。

### 各セクションの表示制御

既存の表示ロジック（`if payload is not None`ブロック内）を、`display_settings`で分岐するよう変更する。計算自体（`pairs`, `network_pairs`, `sector_returns`等の算出）は変更しない。

```python
if pairs:
    if display_settings["heatmap"]:
        # 既存の「業種間相関ヒートマップ」st.subheader〜st.altair_chartをそのまま
        ...
    if display_settings["pairs_table"]:
        # 既存の「リード・ラグ上位ペア」st.subheader〜pairs_dfのst.dataframe、
        # および「リード・ラグの読み方」expanderをそのまま
        ...
    if display_settings["ai_comments"]:
        # 既存の「相関上位5ペアのAIコメント」st.subheader〜forループをそのまま
        ...
else:
    st.info("有効な業種ペアがありませんでした。")  # 既存のまま、設定に関わらず表示

if display_settings["network_diagram"]:
    # 既存の「業種間ネットワーク（全ペア俯瞰）」セクション全体
    # （周期帯セレクトボックス・閾値スライダー・Mermaid描画）をそのまま
    ...

if display_settings["wavelet_analysis"]:
    # 既存の「ウェーブレット分析」セクション全体
    # （業種選択・実行ボタン・ヒートマップ・支配的ラグ折れ線・
    # 直近シグナルサマリー・AI解説ボタン）をそのまま
    ...
```

- `pairs`が空の場合の`st.info`は表示設定に関わらず常に表示する（エラー状態の告知であり、ユーザーが選ぶ「コンテンツ」ではないため）
- ネットワーク図・ウェーブレット分析セクション内の`st.selectbox`/`st.slider`/`st.button`等のインタラクティブ要素は、セクションごと非表示になった場合はレンダリングされない（Streamlitの通常の挙動どおり、非表示中はセッション状態のキーも更新されない）
- 全セクションを非表示にした場合、分析結果はキャッシュ・セッションには保持されたまま何も表示されない状態になる。これは意図的な挙動（ユーザーが選択した結果）としてエラー扱いしない

## エラーハンドリング

| 事象 | 挙動 |
| --- | --- |
| `sector_display_settings.json`が存在しない | 全セクションを表示するデフォルト設定を使用 |
| JSONとして壊れている | デフォルト設定を使用（例外にしない） |
| 内容が辞書でない、または既知キーの値がbool以外 | 該当キーはデフォルト値で補完 |
| 将来削除されたセクションのキーが残っている | 無視する（`DEFAULT_SECTOR_DISPLAY_SETTINGS`にないキーは読み込み時に捨てる） |

## テスト方針

- `tests/test_sector_display_settings.py`（新設、`tests/test_storage.py`と同じ形式）:
  - ファイルが存在しない場合、`load_sector_display_settings`が`DEFAULT_SECTOR_DISPLAY_SETTINGS`と等しい値を返すことを検証
  - 保存→読み込みのラウンドトリップで同じ内容が復元されることを検証
  - 壊れたJSONファイルの場合、デフォルト設定を返すことを検証
  - 保存データの一部キーが欠落している場合、欠落分がデフォルト値で補われることを検証
  - 保存データに未知のキーが含まれる場合、読み込み結果に含まれないことを検証
  - 保存データのある値がbool以外（例: 文字列）の場合、そのキーはデフォルト値で補われることを検証
- UI（expanderの開閉・チェックボックスによる表示切り替え）は既存方針通り自動テスト対象外。`uv run python -m streamlit run app.py`でチェックボックスの切り替え・再起動後の設定引き継ぎを手動確認する

## v1スコープ外（将来課題）

- 非表示セクションの計算スキップによる高速化
- セクション表示順序のカスタマイズ
- 他タブへの同様の表示設定機能の展開
