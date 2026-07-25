# セクターローテーション 表示順序・サイズ・ズーム調整機能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** セクターローテーションタブの5セクション（ヒートマップ／リード・ラグ上位ペア表／AIコメント／ネットワーク図／ウェーブレット分析）について、表示順序の変更・チャート高さの調整・パン/ズーム操作を可能にし、あわせて上部コントロールを1行にまとめて画面のチャート表示領域を広げる。

**Architecture:** `sector_analysis/display_settings.py`の設定スキーマを`{visible, order, height}`の3辞書構成へ拡張し、`app.py`側は既存の即時自動保存パターンを踏襲する。5セクションの描画コードを関数化し、`order`設定でソートした順に呼び出す構成へリファクタリングする。Altairチャートは`.interactive()`でズーム/パンを有効化し、Mermaidネットワーク図はCDN追加の`svg-pan-zoom.js`でズーム/パンを有効化する。

**Tech Stack:** Python, Streamlit 1.59, Altair, pandas, pytest, uv（既存プロジェクトの構成をそのまま使用。新規pip依存追加なし。CDN経由のJSライブラリ`svg-pan-zoom@3`を追加）

## Global Constraints

- 新規pip依存を追加しない（`svg-pan-zoom.js`はCDN経由でHTML埋め込みするのみ）
- 既存の「分析を実行」フロー（データ取得・全セクション分の計算ロジック）は変更しない。表示側の変更のみ行う
- 表示設定のセクションキーは`heatmap` / `pairs_table` / `ai_comments` / `network_diagram` / `wavelet_analysis`の5つ固定。`height`キーを持つのは`heatmap` / `network_diagram` / `wavelet_analysis`の3つのみ（[design doc](../specs/2026-07-25-sector-rotation-layout-controls-design.md)参照）
- デフォルトは全セクション表示ON・順序は既存の表示順（ヒートマップ=1〜ウェーブレット分析=5）・高さは現状の固定値（heatmap=500, network_diagram=400, wavelet_analysis=400）を踏襲。既存ユーザーの見た目は変更前と同じになる
- 旧フラットbool形式の`sector_display_settings.json`を読み込んだ場合は後方互換で`visible`として扱う
- 設定ファイルが存在しない・壊れている・型不正の場合はエラーにせずデフォルト値にフォールバックする
- 表・スライダーの変更時に即座にファイル保存する（保存ボタンなし、既存パターン踏襲）
- UI（Streamlit）の自動テストは書かない。既存プロジェクト方針どおり`uv run python -m streamlit run app.py`での手動確認とする
- テスト実行コマンド: `uv run pytest -v`（作業ディレクトリは`ai-stock-investing-tutorial/app`）

---

## File Structure

- Modify: `sector_analysis/display_settings.py` — 設定スキーマを`{visible, order, height}`の3辞書構成に拡張、旧フラットbool形式の後方互換読み込みを追加
- Modify: `tests/test_sector_display_settings.py` — 新スキーマ・後方互換に合わせて全面改訂
- Modify: `app.py:97-104` — `_render_mermaid`に`svg-pan-zoom.js`を追加
- Modify: `app.py:743-778` — 「表示設定」expanderを、表示ON/OFF＋順序を編集する`st.data_editor`テーブルと、チャート系3セクションの高さスライダーに置き換え
- Modify: `app.py:780-805` — 取得期間・キャッシュ無視・分析実行ボタンを`st.columns(3)`で1行化
- Modify: `app.py:867-1203` — 5セクションの描画を関数化し、`order`設定でソートした順に呼び出す構成へリファクタリング。Altairチャート3つに`.interactive()`を追加

---

### Task 1: `sector_analysis/display_settings.py` — 設定スキーマの拡張

**Files:**
- Modify: `sector_analysis/display_settings.py`
- Modify: `tests/test_sector_display_settings.py`

**Interfaces:**
- Consumes: なし（`pathlib.Path`, `json`のみ、標準ライブラリ）
- Produces:
  - `DEFAULT_SECTOR_DISPLAY_SETTINGS: dict[str, dict]` — `{"visible": {...5 keys, bool}, "order": {...5 keys, int}, "height": {...3 keys (heatmap/network_diagram/wavelet_analysis), int}}`
  - `load_sector_display_settings(path: Path) -> dict[str, dict]`
  - `save_sector_display_settings(path: Path, settings: dict[str, dict]) -> None`
  - Task 2/4はこの新しい戻り値の形（`display_settings["visible"][key]` / `display_settings["order"][key]` / `display_settings["height"][key]`）を前提にコードを書く

- [ ] **Step 1: 既存テストを新スキーマに合わせて全面改訂する（失敗する状態を作る）**

`tests/test_sector_display_settings.py`を以下の内容で置き換える:

```python
import json

from sector_analysis.display_settings import (
    DEFAULT_SECTOR_DISPLAY_SETTINGS,
    load_sector_display_settings,
    save_sector_display_settings,
)


def test_load_missing_file_returns_defaults(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    assert load_sector_display_settings(path) == DEFAULT_SECTOR_DISPLAY_SETTINGS


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    settings = {
        "visible": {
            "heatmap": False,
            "pairs_table": True,
            "ai_comments": False,
            "network_diagram": True,
            "wavelet_analysis": False,
        },
        "order": {
            "heatmap": 3,
            "pairs_table": 1,
            "ai_comments": 2,
            "network_diagram": 5,
            "wavelet_analysis": 4,
        },
        "height": {"heatmap": 600, "network_diagram": 350, "wavelet_analysis": 450},
    }
    save_sector_display_settings(path, settings)
    assert load_sector_display_settings(path) == settings


def test_load_corrupted_file_returns_defaults(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert load_sector_display_settings(path) == DEFAULT_SECTOR_DISPLAY_SETTINGS


def test_load_non_dict_json_returns_defaults(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_sector_display_settings(path) == DEFAULT_SECTOR_DISPLAY_SETTINGS


def test_load_legacy_flat_format_becomes_visible(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text(
        json.dumps(
            {
                "heatmap": False,
                "pairs_table": False,
                "ai_comments": False,
                "network_diagram": True,
                "wavelet_analysis": False,
            }
        ),
        encoding="utf-8",
    )
    result = load_sector_display_settings(path)
    assert result["visible"] == {
        "heatmap": False,
        "pairs_table": False,
        "ai_comments": False,
        "network_diagram": True,
        "wavelet_analysis": False,
    }
    assert result["order"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]
    assert result["height"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["height"]


def test_load_missing_keys_filled_with_defaults(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text(
        json.dumps({"visible": {"heatmap": False}, "order": {}, "height": {}}),
        encoding="utf-8",
    )
    result = load_sector_display_settings(path)
    assert result["visible"]["heatmap"] is False
    assert result["visible"]["pairs_table"] is True
    assert result["order"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]
    assert result["height"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["height"]


def test_load_unknown_keys_are_dropped(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text(
        json.dumps(
            {
                "visible": {"heatmap": False, "some_future_key": True},
                "order": {},
                "height": {},
            }
        ),
        encoding="utf-8",
    )
    result = load_sector_display_settings(path)
    assert "some_future_key" not in result["visible"]
    assert result["visible"]["heatmap"] is False


def test_load_non_bool_visible_value_falls_back_to_default(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text(
        json.dumps({"visible": {"heatmap": "yes"}, "order": {}, "height": {}}),
        encoding="utf-8",
    )
    result = load_sector_display_settings(path)
    assert result["visible"]["heatmap"] is True


def test_load_non_int_order_value_falls_back_to_default(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text(
        json.dumps({"visible": {}, "order": {"heatmap": "first"}, "height": {}}),
        encoding="utf-8",
    )
    result = load_sector_display_settings(path)
    assert result["order"]["heatmap"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]["heatmap"]


def test_load_bool_order_value_falls_back_to_default(tmp_path):
    # bool は Python では int のサブクラスなので、明示的に弾かれることを確認する
    path = tmp_path / "sector_display_settings.json"
    path.write_text(
        json.dumps({"visible": {}, "order": {"heatmap": True}, "height": {}}),
        encoding="utf-8",
    )
    result = load_sector_display_settings(path)
    assert result["order"]["heatmap"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]["heatmap"]


def test_load_non_numeric_height_value_falls_back_to_default(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text(
        json.dumps({"visible": {}, "order": {}, "height": {"heatmap": "big"}}),
        encoding="utf-8",
    )
    result = load_sector_display_settings(path)
    assert result["height"]["heatmap"] == DEFAULT_SECTOR_DISPLAY_SETTINGS["height"]["heatmap"]


def test_load_unknown_height_key_is_dropped(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text(
        json.dumps({"visible": {}, "order": {}, "height": {"pairs_table": 999}}),
        encoding="utf-8",
    )
    result = load_sector_display_settings(path)
    assert "pairs_table" not in result["height"]
```

- [ ] **Step 2: テストを実行し失敗することを確認する**

Run (from `ai-stock-investing-tutorial/app`): `uv run pytest tests/test_sector_display_settings.py -v`
Expected: 複数件FAIL（既存モジュールはまだフラットbool形式のままのため、`DEFAULT_SECTOR_DISPLAY_SETTINGS`の形が新テストの期待値と一致しない）

- [ ] **Step 3: `sector_analysis/display_settings.py`を新スキーマで書き直す**

```python
"""セクターローテーションタブの表示セクション設定（表示ON/OFF・表示順序・
チャート高さ）をJSONファイルとして永続化・読み込みするモジュール。"""

import json
from pathlib import Path

_SECTION_KEYS = (
    "heatmap",
    "pairs_table",
    "ai_comments",
    "network_diagram",
    "wavelet_analysis",
)
_HEIGHT_KEYS = ("heatmap", "network_diagram", "wavelet_analysis")

DEFAULT_SECTOR_DISPLAY_SETTINGS: dict[str, dict] = {
    "visible": {key: True for key in _SECTION_KEYS},
    "order": {key: index + 1 for index, key in enumerate(_SECTION_KEYS)},
    "height": {"heatmap": 500, "network_diagram": 400, "wavelet_analysis": 400},
}


def _is_new_format(data: dict) -> bool:
    """新形式（トップレベルに"visible"辞書キーを持つ）かどうかを判定する。
    旧フラットbool形式（{"heatmap": true, ...}）にはこのキーが無い。"""
    return isinstance(data.get("visible"), dict)


def load_sector_display_settings(path: Path) -> dict[str, dict]:
    """表示設定をJSONファイルから読み込む。ファイルが存在しない、JSONとして
    壊れている、あるいは想定外の形式（辞書でない）の場合はデフォルト設定を
    返す。旧フラットbool形式のファイルは"visible"として読み込み、"order"・
    "height"はデフォルト値で補う。新形式でも、各サブ辞書内の欠落キー・
    型不正な値・未知のキーはデフォルト値で補う/無視する。"""
    settings = {
        "visible": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["visible"]),
        "order": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["order"]),
        "height": dict(DEFAULT_SECTOR_DISPLAY_SETTINGS["height"]),
    }
    if not path.exists():
        return settings
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return settings
    if not isinstance(data, dict):
        return settings

    if not _is_new_format(data):
        for key in _SECTION_KEYS:
            if key in data and isinstance(data[key], bool):
                settings["visible"][key] = data[key]
        return settings

    visible_data = data.get("visible")
    if isinstance(visible_data, dict):
        for key in _SECTION_KEYS:
            value = visible_data.get(key)
            if isinstance(value, bool):
                settings["visible"][key] = value

    order_data = data.get("order")
    if isinstance(order_data, dict):
        for key in _SECTION_KEYS:
            value = order_data.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                settings["order"][key] = value

    height_data = data.get("height")
    if isinstance(height_data, dict):
        for key in _HEIGHT_KEYS:
            value = height_data.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                settings["height"][key] = value

    return settings


def save_sector_display_settings(path: Path, settings: dict[str, dict]) -> None:
    """表示設定をJSONファイルとして保存する。保存先ディレクトリが存在しない
    場合は作成する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
```

- [ ] **Step 4: テストを実行し全てパスすることを確認する**

Run: `uv run pytest tests/test_sector_display_settings.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add sector_analysis/display_settings.py tests/test_sector_display_settings.py
git commit -m "$(cat <<'EOF'
Extend sector display settings with order and height

Adds visible/order/height sub-dicts to the persisted schema so the
sector rotation tab can support section reordering and per-chart
sizing, while still reading old flat-bool settings files.
EOF
)"
```

---

### Task 2: `app.py` — 「表示設定」expanderを順序・サイズ設定UIに置き換え

**Files:**
- Modify: `app.py:743-778`

**Interfaces:**
- Consumes: `sector_analysis.display_settings.load_sector_display_settings` / `save_sector_display_settings`（Task 1で拡張済み）
- Produces: `display_settings: dict[str, dict]`という名前のローカル変数（`tab_sector`ブロック内、`{"visible": ..., "order": ..., "height": ...}`の形）。Task 4はこの変数をそのまま使う

- [ ] **Step 1: 現在のコードを確認する**

`app.py:743-778`は現在以下の内容（5つのチェックボックスでフラットbool形式の`display_settings`を作る）:

```python
    display_settings = load_sector_display_settings(SECTOR_DISPLAY_SETTINGS_PATH)
    with st.expander("表示設定"):
        st.caption(
            "チェックを外すとそのセクションを非表示にできます"
            "（設定は次回起動時も保持されます）。"
        )
        new_display_settings = {
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
        if new_display_settings != display_settings:
            save_sector_display_settings(SECTOR_DISPLAY_SETTINGS_PATH, new_display_settings)
            display_settings = new_display_settings
```

- [ ] **Step 2: 上記ブロックを以下に置き換える**

```python
    display_settings = load_sector_display_settings(SECTOR_DISPLAY_SETTINGS_PATH)
    section_labels = {
        "heatmap": "業種間相関ヒートマップ",
        "pairs_table": "リード・ラグ上位ペア",
        "ai_comments": "相関上位5ペアのAIコメント",
        "network_diagram": "業種間ネットワーク（全ペア俯瞰）",
        "wavelet_analysis": "ウェーブレット分析",
    }
    with st.expander("表示設定"):
        st.caption(
            "表示のON/OFFと並び順を指定できます"
            "（設定は次回起動時も保持されます）。"
        )
        editor_df = pd.DataFrame(
            [
                {
                    "key": key,
                    "セクション": label,
                    "表示": display_settings["visible"][key],
                    "順序": display_settings["order"][key],
                }
                for key, label in section_labels.items()
            ]
        )
        edited_df = st.data_editor(
            editor_df,
            column_config={
                "key": None,
                "セクション": st.column_config.TextColumn(disabled=True),
                "表示": st.column_config.CheckboxColumn(),
                "順序": st.column_config.NumberColumn(min_value=1, max_value=5, step=1),
            },
            hide_index=True,
            key="sector_section_editor",
        )
        new_visible = {
            key: bool(value) for key, value in zip(edited_df["key"], edited_df["表示"])
        }
        new_order = {
            key: (
                int(value)
                if pd.notna(value)
                else display_settings["order"][key]
            )
            for key, value in zip(edited_df["key"], edited_df["順序"])
        }

        new_height = dict(display_settings["height"])
        height_specs = [
            ("heatmap", "業種間相関ヒートマップの高さ (px)"),
            ("network_diagram", "業種間ネットワークの高さ (px)"),
            ("wavelet_analysis", "ウェーブレット分析ヒートマップの高さ (px)"),
        ]
        for key, label in height_specs:
            if new_visible[key]:
                new_height[key] = st.slider(
                    label,
                    250,
                    900,
                    display_settings["height"][key],
                    50,
                    key=f"sector_height_{key}",
                )

        new_display_settings = {
            "visible": new_visible,
            "order": new_order,
            "height": new_height,
        }
        if new_display_settings != display_settings:
            save_sector_display_settings(SECTOR_DISPLAY_SETTINGS_PATH, new_display_settings)
            display_settings = new_display_settings
```

`edited_df`の「表示」「順序」列はStreamlitの`data_editor`から返る際にnumpyのbool_/int64になっていることがあり、そのままだと`json.dumps`（`save_sector_display_settings`内）が`Object of type bool_/int64 is not JSON serializable`で失敗する。`bool(value)`/`int(value)`で必ずPythonネイティブ型に変換すること。「順序」セルをユーザーが空にした場合（`pd.notna(value)`がFalse）は直前の設定値にフォールバックする。

- [ ] **Step 3: アプリを起動して動作確認する**

Run: `uv run python -m streamlit run app.py`

確認項目:
1. 「セクターローテーション」タブの「表示設定」expanderを開くと、セクション名・表示ON/OFF・順序の3列を持つ編集可能な表が表示される
2. いずれかの「表示」チェックを外す・「順序」の数値を変える →`data/sector_display_settings.json`が新形式（`visible`/`order`/`height`キーを持つ）で保存されることを確認する（`cat data/sector_display_settings.json`、Windows PowerShellなら`Get-Content data/sector_display_settings.json`）
3. 「表示」がONのチャート系3セクション（ヒートマップ・ネットワーク図・ウェーブレット分析）にのみ高さスライダーが表示される。OFFにすると対応スライダーが消える
4. ブラウザをリロードしても表・スライダーの値が保持されている
5. 既存の`data/sector_display_settings.json`（旧フラット形式が残っている場合）を読み込んでもエラーにならず、表のチェック状態に反映される
6. この時点ではまだ表の順序変更・高さスライダーはタブの表示内容に反映されない（Task 4で対応）

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "$(cat <<'EOF'
Replace sector display checkboxes with order/height editor

The display-settings expander now uses a data_editor table for
per-section visibility and order, plus height sliders for the three
chart-bearing sections.
EOF
)"
```

---

### Task 3: `app.py` — 上部コントロールを1行化

**Files:**
- Modify: `app.py:780-805`

**Interfaces:**
- Consumes: なし
- Produces: `sector_period` / `sector_force_regenerate` / `run_clicked`（ローカル変数、以降`if run_clicked:`ブロックの条件として使う。`app.py:806`以降の既存コードは変更しない）

- [ ] **Step 1: 現在のコードを確認する**

`app.py:780-805`は現在以下の内容（取得期間・キャッシュ無視チェックボックス・分析実行ボタンが縦に3つ並んでいる）:

```python
    sector_period = st.selectbox(
        "取得期間",
        ["6mo", "1y", "2y"],
        index=1,
        key="sector_period",
        help=(
            "株価データを取得する期間です。長いほど長期の周期（サイクル）分析の"
            "精度が上がりますが、取得に時間がかかります。"
        ),
    )
    sector_force_regenerate = st.checkbox(
        "キャッシュを無視して再生成する",
        key="sector_force_regenerate",
        help=(
            "前回と同じ期間で分析済みの場合、通常は保存済みの結果を再利用します。"
            "最新データで計算し直したいときにチェックしてください。"
        ),
    )

    if st.button(
        "分析を実行",
        help=(
            "初回実行時は228銘柄のデータ取得のため30秒程度かかります"
            "（2回目以降はキャッシュにより高速です）。"
        ),
    ):
```

（この直後、`app.py:806`から`# 取得期間と対象ユニバースが同一なら分析結果をキャッシュから再利用する`のコメントとキャッシュ処理が続く。この部分は変更しない）

- [ ] **Step 2: 上記ブロックを以下に置き換える**

```python
    col_period, col_regen, col_run = st.columns(3)
    with col_period:
        sector_period = st.selectbox(
            "取得期間",
            ["6mo", "1y", "2y"],
            index=1,
            key="sector_period",
            help=(
                "株価データを取得する期間です。長いほど長期の周期（サイクル）分析の"
                "精度が上がりますが、取得に時間がかかります。"
            ),
        )
    with col_regen:
        sector_force_regenerate = st.checkbox(
            "キャッシュを無視して再生成する",
            key="sector_force_regenerate",
            help=(
                "前回と同じ期間で分析済みの場合、通常は保存済みの結果を再利用します。"
                "最新データで計算し直したいときにチェックしてください。"
            ),
        )
    with col_run:
        run_clicked = st.button(
            "分析を実行",
            help=(
                "初回実行時は228銘柄のデータ取得のため30秒程度かかります"
                "（2回目以降はキャッシュにより高速です）。"
            ),
        )

    if run_clicked:
```

`app.py:806`以降（キャッシュキー計算〜`st.session_state["sector_payload"] = payload`まで）はインデント・内容ともに一切変更しない。

- [ ] **Step 3: アプリを起動して動作確認する**

Run: `uv run python -m streamlit run app.py`

確認項目:
1. 「取得期間」「キャッシュを無視して再生成する」「分析を実行」ボタンが横1行に並んで表示される
2. 「分析を実行」ボタンを押すと、これまで通り分析が実行され結果が表示される
3. 「キャッシュを無視して再生成する」にチェックを入れて実行すると、これまで通りキャッシュが無視されて再計算される

- [ ] **Step 4: 既存の自動テストが壊れていないことを確認する**

Run: `uv run pytest -v`
Expected: 既存の全テストがPASS

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "$(cat <<'EOF'
Combine sector rotation top controls into one row

Period selector, cache-ignore checkbox, and run button now share a
single st.columns row instead of stacking vertically, freeing space
for the chart sections below.
EOF
)"
```

---

### Task 4: `app.py` — セクション描画の関数化・順序対応・ズーム有効化

**Files:**
- Modify: `app.py:867-1203`

**Interfaces:**
- Consumes: `display_settings: dict[str, dict]`（Task 2で定義済みのローカル変数）、`pairs` / `payload`（既存のまま）
- Produces: なし（このタスクの後は`app.py:1205`以降の`skipped_tickers`/`excluded_sectors`/`DISCLAIMER_NOTICE`表示にそのまま続く。ここは変更しない）

- [ ] **Step 1: `if pairs:`ブロックの開始から`st.markdown(cached_state["text"])`までを、以下のブロック全体で置き換える**

Task 2・Task 3の編集により行番号がずれているため、行番号ではなく内容で置き換え範囲を特定すること:
- 開始位置: `pairs = payload["pairs"]`の次の行にある`if pairs:`（Task 1・2実施前の`app.py:867`相当）
- 終了位置: `wavelet_comment_key`と一致する場合に`st.markdown(cached_state["text"])`を呼ぶ行（Task 1・2実施前の`app.py:1203`相当）。その直後の行（空行を挟んで`if payload["skipped_tickers"]:`）はこの置き換え範囲に含めない

```python
        if not pairs:
            st.info("有効な業種ペアがありませんでした。")

        def _render_heatmap():
            # 相関ペアの一覧から対称な相関行列（ヒートマップ用）を組み立てる
            sectors = sorted(
                {pair["leading_sector"] for pair in pairs}
                | {pair["lagging_sector"] for pair in pairs}
            )
            corr_matrix = pd.DataFrame(1.0, index=sectors, columns=sectors)
            for pair in pairs:
                a, b = pair["leading_sector"], pair["lagging_sector"]
                value = abs(pair["correlation"])
                corr_matrix.loc[a, b] = value
                corr_matrix.loc[b, a] = value

            # Altairのheatmapはlong形式を要求するため、行列をmeltして変換する
            heatmap_df = (
                corr_matrix.reset_index()
                .melt(id_vars="index", var_name="sector_b", value_name="correlation")
                .rename(columns={"index": "sector_a"})
            )

            st.subheader(
                "業種間相関ヒートマップ",
                help=(
                    "17業種の組み合わせについて、最も強く連動するタイミング"
                    "（リード・ラグ）における相関の強さを、色の濃さで示します。"
                ),
            )
            heatmap = (
                alt.Chart(heatmap_df)
                .mark_rect()
                .encode(
                    x=alt.X("sector_a:N", title=None),
                    y=alt.Y("sector_b:N", title=None),
                    color=alt.Color(
                        "correlation:Q", scale=alt.Scale(scheme="reds", domain=[0, 1])
                    ),
                    tooltip=["sector_a", "sector_b", "correlation"],
                )
                .properties(height=display_settings["height"]["heatmap"])
                .interactive()
            )
            st.altair_chart(heatmap, width="stretch")

        def _render_pairs_table():
            st.subheader(
                "リード・ラグ上位ペア",
                help=(
                    "相関が強い順に、どちらの業種が何営業日先行して動く傾向が"
                    "あったかを一覧表示します。"
                ),
            )
            pairs_df = pd.DataFrame(pairs)[
                ["leading_sector", "lagging_sector", "lag_days", "correlation"]
            ]
            st.dataframe(
                pairs_df,
                column_config={
                    "leading_sector": st.column_config.TextColumn("先行業種"),
                    "lagging_sector": st.column_config.TextColumn("追随業種"),
                    "lag_days": st.column_config.NumberColumn("ラグ（営業日）"),
                    "correlation": st.column_config.NumberColumn("相関係数"),
                },
                hide_index=True,
            )

            with st.expander("リード・ラグの読み方"):
                st.markdown(
                    "「先行業種」の値動きに、「追随業種」が「ラグ（営業日）」で"
                    "示した日数だけ遅れて追随する傾向が、指定した期間の株価データ"
                    "から確認されたことを示します。\n\n"
                    "例えば「先行業種: 建設・資材、追随業種: 機械、ラグ: 0日、"
                    "相関係数: 0.87」であれば、建設・資材セクターの値動きと"
                    "機械セクターの値動きが、同じ営業日にほぼ同じ方向へ動く傾向が"
                    "強かったことを意味します。\n\n"
                    "**注意:** 上位ペアの多くはラグ0日（同時相関）になりやすい"
                    "傾向があります。これは業種固有の先行・追随関係というより、"
                    "市場全体の地合い（同じ日に多くの業種が一緒に動く傾向）を"
                    "反映している可能性があります。特定の周期の長さ"
                    "（短期・中期・長期）ごとに、より業種固有の先行・追随関係を"
                    "確認したい場合は、下部の「ウェーブレット分析」もあわせて"
                    "ご覧ください。"
                )

        def _render_ai_comments():
            st.subheader(
                "相関上位5ペアのAIコメント",
                help=(
                    "上記の上位5ペアについて、過去データ上の傾向をAIが解説した"
                    "ものです。売買の推奨ではありません。"
                ),
            )
            for pair in pairs[:5]:
                key = f"{pair['leading_sector']}->{pair['lagging_sector']}"
                st.write(
                    f"**{pair['leading_sector']} → {pair['lagging_sector']}**: "
                    f"{payload['comments'].get(key, 'コメント生成失敗')}"
                )

        def _render_network_diagram():
            st.subheader(
                "業種間ネットワーク（全ペア俯瞰）",
                help=(
                    "全業種ペアについて、直近20営業日のウェーブレット分析結果を集約し、"
                    "周期の長さごとにどの業種が誰をリードしているかを俯瞰します。"
                ),
            )
            st.caption(
                "コヒーレンス（関係の確からしさ）が閾値以上のペアのみを矢印で表示します。"
                "矢印の元が先行業種、矢印の先が追随業種です。"
            )

            network_df = pd.DataFrame(payload["network_pairs"])
            col_band, col_threshold = st.columns(2)
            with col_band:
                network_band = st.selectbox(
                    "周期帯", ["短期", "中期", "長期"], index=1, key="network_band"
                )
            with col_threshold:
                network_threshold = st.slider(
                    "コヒーレンス閾値（これ以上のペアのみ表示）",
                    0.0,
                    1.0,
                    0.5,
                    0.05,
                    key="network_threshold",
                )

            mermaid_code = build_mermaid_lead_lag_graph(
                network_df, network_band, network_threshold
            )
            if mermaid_code is None:
                st.info(
                    "十分な確信度を持つ関係が見つかりませんでした。閾値を下げてみてください。"
                )
            else:
                _render_mermaid(
                    mermaid_code, height=display_settings["height"]["network_diagram"]
                )

        def _render_wavelet_analysis():
            st.subheader(
                "ウェーブレット分析（時間変化するリード・ラグ）",
                help="時間の経過とともに変化する、業種間の先行・追随関係を可視化します。",
            )
            st.caption(
                "選択した2つの業種について、値動きの周期の長さ（短期・中期・長期）ごとに、"
                "どちらの業種がどれくらい先行しているかの時間変化を可視化します。"
                "色が薄い部分は関係の確からしさ（コヒーレンス）が低いことを示します。"
            )
            with st.expander("ウェーブレット分析とは？"):
                st.markdown(
                    "通常の相関分析は「期間全体で1つの数値」を計算しますが、実際の"
                    "値動きには短い周期（数日〜2週間程度）の動きと、長い周期"
                    "（1〜6か月程度）の動きが混ざっています。ウェーブレット分析は、"
                    "この値動きを周期の長さ（短期・中期・長期）ごとに分解し、周期ごとに"
                    "「どちらの業種が先に動いたか」「どれくらい確からしい関係か"
                    "（コヒーレンス）」を計算する手法です。\n\n"
                    "**周期帯の目安**\n"
                    "- 短期: 4〜10営業日程度（1〜2週間の値動き）\n"
                    "- 中期: 10〜40営業日程度（2週間〜2か月の値動き）\n"
                    "- 長期: 40〜120営業日程度（2〜6か月の値動き）\n\n"
                    "**下のヒートマップの読み方**\n"
                    "- 横軸: 日付\n"
                    "- 縦軸: 周期の長さ（営業日）\n"
                    "- 色: 正（青系）なら業種Aが先行、負（赤系）なら業種Bが先行\n"
                    "- 色の濃さ: 関係の確からしさ（コヒーレンス）。薄いほど確からしさが"
                    "低く、参考程度に留めてください\n\n"
                    "下部の「支配的ラグ」の折れ線グラフは、選んだ周期帯の中で"
                    "コヒーレンスの高い部分を重視した、平均的な先行・遅行日数の推移を"
                    "示します。0より上なら業種Aが先行、0より下なら業種Bが先行して"
                    "いたことを意味します。"
                )

            sector_options = sorted(payload["sector_returns"].keys())
            if len(sector_options) < 2:
                st.info("ウェーブレット分析には2業種以上のデータが必要です。")
            else:
                default_x = pairs[0]["leading_sector"] if pairs else sector_options[0]
                default_y = pairs[0]["lagging_sector"] if pairs else sector_options[1]
                if default_x not in sector_options:
                    default_x = sector_options[0]
                if default_y not in sector_options or default_y == default_x:
                    default_y = next(s for s in sector_options if s != default_x)

                col_a, col_b = st.columns(2)
                sector_select_help = (
                    "比較したい2つの業種を選びます"
                    "（デフォルトは相関上位ペアの先行・追随業種）。"
                )
                with col_a:
                    sector_x = st.selectbox(
                        "業種A",
                        sector_options,
                        index=sector_options.index(default_x),
                        key="wavelet_sector_x",
                        help=sector_select_help,
                    )
                with col_b:
                    sector_y = st.selectbox(
                        "業種B",
                        sector_options,
                        index=sector_options.index(default_y),
                        key="wavelet_sector_y",
                        help=sector_select_help,
                    )

                if st.button("ウェーブレット分析を実行"):
                    all_series = deserialize_sector_returns(payload["sector_returns"])
                    try:
                        wavelet_df = compute_cross_wavelet_lead_lag(
                            all_series[sector_x], all_series[sector_y], sector_x, sector_y
                        )
                    except Exception:
                        st.error("ウェーブレット分析の計算に失敗しました。")
                        wavelet_df = pd.DataFrame()

                    if wavelet_df.empty:
                        st.warning(
                            "選択した2業種の共通データが不足しているため、分析できませんでした。"
                        )
                        st.session_state["wavelet_result"] = None
                    else:
                        st.session_state["wavelet_result"] = {
                            "df": wavelet_df,
                            "x": sector_x,
                            "y": sector_y,
                        }

                wavelet_result = st.session_state.get("wavelet_result")
                if wavelet_result is not None:
                    wavelet_df = wavelet_result["df"]

                    heatmap = (
                        alt.Chart(wavelet_df)
                        .mark_rect()
                        .encode(
                            x=alt.X("date:T", title=None),
                            y=alt.Y(
                                "period_days:O", title="周期（営業日）", sort="descending"
                            ),
                            color=alt.Color(
                                "lag_days:Q",
                                title=f"ラグ（正={wavelet_result['x']}が先行）",
                                scale=alt.Scale(scheme="redblue", domainMid=0),
                            ),
                            opacity=alt.Opacity(
                                "coherence:Q", scale=alt.Scale(domain=[0, 1], range=[0.05, 1])
                            ),
                            tooltip=[
                                "date:T",
                                "period_days:Q",
                                "band:N",
                                "coherence:Q",
                                "lag_days:Q",
                                "leading_sector:N",
                            ],
                        )
                        .properties(height=display_settings["height"]["wavelet_analysis"])
                        .interactive()
                    )
                    st.altair_chart(heatmap, width="stretch")

                    band = st.selectbox(
                        "周期帯",
                        ["短期", "中期", "長期"],
                        index=1,
                        key="wavelet_band",
                        help=(
                            "短期(4〜10営業日) / 中期(10〜40営業日) / 長期(40〜120営業日) "
                            "のいずれかを選び、その周期帯における支配的ラグの推移を"
                            "表示します。"
                        ),
                    )
                    band_df = wavelet_df[wavelet_df["band"] == band]
                    if band_df.empty:
                        st.info("この周期帯には有効なデータがありませんでした。")
                    else:
                        dominant = compute_dominant_lag_series(band_df)
                        line = (
                            alt.Chart(dominant)
                            .mark_line()
                            .encode(
                                x=alt.X("date:T", title=None),
                                y=alt.Y("dominant_lag_days:Q", title="支配的ラグ（日）"),
                            )
                            .properties(height=250)
                            .interactive()
                        )
                        st.altair_chart(line, width="stretch")

                        # 直近シグナルの要約パネル（機械的な数値表示、AI不使用）。
                        # 周期帯セレクトボックスの変更ごとに自動的に追従する。
                        snapshot = summarize_band_snapshot(band_df)
                        if snapshot is not None:
                            snap_lag = snapshot["dominant_lag_days"]
                            snap_leading = sector_x if snap_lag >= 0 else sector_y
                            snap_lagging = sector_y if snap_lag >= 0 else sector_x

                            col_lag, col_coherence = st.columns(2)
                            col_lag.metric("支配的ラグ（日）", f"{snap_lag:+.1f}")
                            col_coherence.metric(
                                "コヒーレンス", f"{snapshot['avg_coherence']:.2f}"
                            )
                            st.caption(
                                f"直近（{snapshot['date'].strftime('%Y-%m-%d')}）時点: "
                                f"{snap_leading} が {snap_lagging} に約{abs(snap_lag):.1f}営業日先行"
                                f"（コヒーレンス {snapshot['avg_coherence']:.2f}）"
                            )

                            # AI解説コメント（明示的ボタン起動、日次ファイルキャッシュ）。
                            # 表示中のペア・周期帯と異なる古いコメントを残さないよう、
                            # session_stateには生成時のキーも一緒に保持し、一致時のみ表示する。
                            wavelet_comment_key = (sector_x, sector_y, sector_period, band)
                            wavelet_comment_force_regenerate = st.checkbox(
                                "AI解説のキャッシュを無視して再生成する",
                                key="wavelet_comment_force_regenerate",
                            )
                            if st.button("AI解説を生成", key="wavelet_comment_button"):
                                comment_cache_key = "wavelet-comment-" + hashlib.sha256(
                                    "-".join(
                                        str(part) for part in wavelet_comment_key
                                    ).encode("utf-8")
                                ).hexdigest()[:12]
                                cached_comment = (
                                    None
                                    if wavelet_comment_force_regenerate
                                    else read_cache(CACHE_DIR, comment_cache_key)
                                )
                                if cached_comment is not None:
                                    wavelet_comment_text = cached_comment
                                else:
                                    wavelet_comment_text = generate_wavelet_explanation(
                                        sector_x, sector_y, band, snapshot, call_llm=call_llm
                                    )
                                    write_cache(
                                        CACHE_DIR, comment_cache_key, wavelet_comment_text
                                    )
                                st.session_state["wavelet_comment"] = {
                                    "key": wavelet_comment_key,
                                    "text": wavelet_comment_text,
                                }

                            cached_state = st.session_state.get("wavelet_comment")
                            if (
                                cached_state is not None
                                and cached_state["key"] == wavelet_comment_key
                            ):
                                st.markdown(cached_state["text"])

        section_renderers = {
            "heatmap": _render_heatmap,
            "pairs_table": _render_pairs_table,
            "ai_comments": _render_ai_comments,
            "network_diagram": _render_network_diagram,
            "wavelet_analysis": _render_wavelet_analysis,
        }
        ordered_keys = sorted(
            section_renderers, key=lambda k: display_settings["order"][k]
        )
        for key in ordered_keys:
            if key in ("heatmap", "pairs_table", "ai_comments") and not pairs:
                continue
            if display_settings["visible"][key]:
                section_renderers[key]()
```

（この直後、`app.py:1205`の`if payload["skipped_tickers"]:`以降は変更しない）

各関数の中身は既存コードと完全に同一（`.properties(height=500)`→`.properties(height=display_settings["height"]["heatmap"]).interactive()`、`.properties(height=400)`→`.properties(height=display_settings["height"]["wavelet_analysis"]).interactive()`、支配的ラグ折れ線の`.properties(height=250)`→`.properties(height=250).interactive()`、`_render_mermaid(mermaid_code)`→`_render_mermaid(mermaid_code, height=display_settings["height"]["network_diagram"])`の4箇所の差分のみ）。

- [ ] **Step 2: アプリを起動して動作確認する**

Run: `uv run python -m streamlit run app.py`

確認項目（`data/sector_display_settings.json`を編集するか、UIの表・スライダーで操作する）:
1. 全セクション表示ON・デフォルト順序（1〜5）の状態で「分析を実行」→ 5セクションが元通りの順序（ヒートマップ→ペア表→AIコメント→ネットワーク図→ウェーブレット分析）で表示される
2. 表示設定expanderで「ウェーブレット分析」の順序を`1`に変更 → タブ内でウェーブレット分析セクションが一番上に表示される
3. 「業種間相関ヒートマップ」のチェックを外す → ヒートマップだけが消え、他のセクションは表示されたまま
4. 全チェックをOFFにする → 5セクションがすべて非表示になり、エラーは発生しない（`skipped_tickers`/`excluded_sectors`/免責事項は表示されたまま）
5. 有効な業種ペアが無い場合（`pairs`が空）の`st.info("有効な業種ペアがありませんでした。")`は、表示設定・順序に関わらず常に表示される
6. 相関ヒートマップ・ウェーブレットヒートマップ・支配的ラグ折れ線をマウスホイールでズーム、ドラッグでパンできる
7. ヒートマップ・ネットワーク図・ウェーブレット分析の高さスライダーを動かすと、該当チャートの高さが変わる

- [ ] **Step 3: 既存の自動テストが壊れていないことを確認する**

Run: `uv run pytest -v`
Expected: 既存の全テストがPASS

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "$(cat <<'EOF'
Render sector rotation sections in configurable order

Each section is now a function looked up and called in the order
from display_settings["order"], with per-chart height wired from
display_settings["height"] and .interactive() added to the Altair
charts for pan/zoom.
EOF
)"
```

---

### Task 5: `app.py` — `_render_mermaid`にパン/ズームを追加

**Files:**
- Modify: `app.py:97-104`

**Interfaces:**
- Consumes: なし
- Produces: `_render_mermaid(code: str, height: int = 400) -> None`（シグネチャは変更なし。Task 4の`_render_network_diagram`は既にこの関数を`height=`キーワード引数付きで呼び出している）

- [ ] **Step 1: 現在のコードを確認する**

`app.py:97-104`は現在以下の内容:

```python
def _render_mermaid(code: str, height: int = 400) -> None:
    """Mermaidコード文字列を、CDN経由のmermaid.jsを使ってHTML埋め込みで描画する。"""
    html = f"""
    <div class="mermaid">{code}</div>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <script>mermaid.initialize({{ startOnLoad: true }});</script>
    """
    components.html(html, height=height, scrolling=True)
```

- [ ] **Step 2: 上記を以下に置き換える**

```python
def _render_mermaid(code: str, height: int = 400) -> None:
    """Mermaidコード文字列を、CDN経由のmermaid.js + svg-pan-zoom.jsを使って
    ドラッグパン・ホイールズーム可能なHTML埋め込みとして描画する。"""
    html = f"""
    <div class="mermaid">{code}</div>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/svg-pan-zoom@3/dist/svg-pan-zoom.min.js"></script>
    <script>
      mermaid.initialize({{ startOnLoad: false }});
      mermaid.run({{ querySelector: ".mermaid" }}).then(function () {{
        var svgEl = document.querySelector(".mermaid svg");
        if (svgEl) {{
          svgPanZoom(svgEl, {{
            zoomEnabled: true,
            controlIconsEnabled: true,
            fit: true,
            center: true,
          }});
        }}
      }});
    </script>
    """
    components.html(html, height=height, scrolling=True)
```

- [ ] **Step 3: アプリを起動して動作確認する**

Run: `uv run python -m streamlit run app.py`

確認項目:
1. 「セクターローテーション」タブでネットワーク図が表示されること（`mermaid.run()`への変更後も従来通り描画される）
2. ネットワーク図をマウスドラッグでパンできること
3. マウスホイールでズームイン/アウトできること
4. SVG右下にズームイン/アウト/リセットのアイコンが表示され、クリックで機能すること

- [ ] **Step 4: 既存の自動テストが壊れていないことを確認する**

Run: `uv run pytest -v`
Expected: 既存の全テストがPASS

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "$(cat <<'EOF'
Add pan/zoom to the sector network Mermaid diagram

Loads svg-pan-zoom.js from CDN and wires it up after mermaid.run()
completes, giving the network diagram drag-to-pan and wheel-zoom
controls.
EOF
)"
```
