# セクターローテーション 表示コンテンツのユーザ設定機能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** セクターローテーションタブの5セクション（ヒートマップ／リード・ラグ上位ペア表／AIコメント／ネットワーク図／ウェーブレット分析）を、ユーザーがチェックボックスで表示/非表示を切り替えられるようにし、その設定をファイルに永続化する。

**Architecture:** `portfolio_management/storage.py`（holdings.jsonのload/saveパターン）を踏襲した新規モジュール`sector_analysis/display_settings.py`でJSON永続化を行う。`app.py`の`tab_sector`先頭に「表示設定」expanderを追加し、チェックボックスの値をファイルへ即時自動保存する。既存の5セクションはそれぞれ`if display_settings[...]:`で囲むだけで、計算ロジックは一切変更しない。

**Tech Stack:** Python, Streamlit, pytest, uv（既存プロジェクトの構成をそのまま使用。新規pip依存追加なし）

## Global Constraints

- 新規pip依存を追加しない
- 既存の「分析を実行」フロー（データ取得・全セクション分の計算）は変更しない。非表示セクションの計算スキップは実装しない（v1スコープ外）
- 表示設定のキーは`heatmap` / `pairs_table` / `ai_comments` / `network_diagram` / `wavelet_analysis`の5つ固定（[design doc](../specs/2026-07-25-sector-rotation-display-settings-design.md)参照）
- デフォルトは全セクション`True`（表示）。既存ユーザーの見た目は変更前と同じになる
- 設定ファイルが存在しない・壊れている・型不正の場合はエラーにせずデフォルト値にフォールバックする
- チェックボックス変更時に即座にファイル保存する（保存ボタンなし）
- UI（Streamlit）の自動テストは書かない。既存プロジェクト方針どおり`uv run python -m streamlit run app.py`での手動確認とする
- テスト実行コマンド: `uv run pytest -v`（作業ディレクトリは`ai-stock-investing-tutorial/app`）

---

## File Structure

- Create: `sector_analysis/display_settings.py` — 表示設定のデフォルト値・JSON読み込み・保存
- Create: `tests/test_sector_display_settings.py` — 上記モジュールの単体テスト
- Modify: `app.py` — パス定数追加、import追加、「表示設定」expander追加、5セクションを`display_settings`で分岐

---

### Task 1: `sector_analysis/display_settings.py` — 表示設定の永続化モジュール

**Files:**
- Create: `sector_analysis/display_settings.py`
- Test: `tests/test_sector_display_settings.py`

**Interfaces:**
- Consumes: なし（`pathlib.Path`, `json`のみ、標準ライブラリ）
- Produces:
  - `DEFAULT_SECTOR_DISPLAY_SETTINGS: dict[str, bool]` — キーは`heatmap`, `pairs_table`, `ai_comments`, `network_diagram`, `wavelet_analysis`、値はすべて`True`
  - `load_sector_display_settings(path: Path) -> dict[str, bool]`
  - `save_sector_display_settings(path: Path, settings: dict[str, bool]) -> None`
  - Task 2/3はこれら3つのシンボルを`sector_analysis.display_settings`からimportして使う

- [ ] **Step 1: Write the failing tests**

`tests/test_sector_display_settings.py`を新規作成する:

```python
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
        "heatmap": False,
        "pairs_table": True,
        "ai_comments": False,
        "network_diagram": True,
        "wavelet_analysis": False,
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


def test_load_missing_keys_filled_with_defaults(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text('{"heatmap": false}', encoding="utf-8")
    result = load_sector_display_settings(path)
    assert result["heatmap"] is False
    assert result["pairs_table"] is True
    assert result["ai_comments"] is True
    assert result["network_diagram"] is True
    assert result["wavelet_analysis"] is True


def test_load_unknown_keys_are_dropped(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text('{"heatmap": false, "some_future_key": true}', encoding="utf-8")
    result = load_sector_display_settings(path)
    assert "some_future_key" not in result
    assert result["heatmap"] is False


def test_load_non_bool_value_falls_back_to_default(tmp_path):
    path = tmp_path / "sector_display_settings.json"
    path.write_text('{"heatmap": "yes"}', encoding="utf-8")
    result = load_sector_display_settings(path)
    assert result["heatmap"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `ai-stock-investing-tutorial/app`): `uv run pytest tests/test_sector_display_settings.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'sector_analysis.display_settings'`

- [ ] **Step 3: Write the implementation**

`sector_analysis/display_settings.py`を新規作成する:

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
    キー、または値がbool以外のキーはデフォルト値で補う（将来セクションが
    増えても既存ファイルで壊れない）。"""
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sector_display_settings.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add sector_analysis/display_settings.py tests/test_sector_display_settings.py
git commit -m "$(cat <<'EOF'
Add sector rotation display settings persistence module

Loads/saves which sector-rotation-tab sections a user wants shown,
following the same JSON storage pattern as portfolio holdings.
EOF
)"
```

---

### Task 2: 「表示設定」expanderをタブに追加

**Files:**
- Modify: `app.py:38` (import追加), `app.py:64` (パス定数追加), `app.py:730-737` (expander挿入)

**Interfaces:**
- Consumes: `sector_analysis.display_settings.load_sector_display_settings`, `save_sector_display_settings`, `DEFAULT_SECTOR_DISPLAY_SETTINGS`（Task 1で実装済み）
- Produces: `display_settings: dict[str, bool]`という名前のローカル変数を`tab_sector`ブロック内で定義する。Task 3はこの変数をそのまま使って各セクションを分岐する

- [ ] **Step 1: importを追加**

既存のimport群はアルファベット順に並んでいる。`app.py:50`（`from sector_analysis.correlation import ...`）と`app.py:51`（`from sector_analysis.network import ...`）の間に追加する:

```python
from sector_analysis.display_settings import (
    load_sector_display_settings,
    save_sector_display_settings,
)
```

- [ ] **Step 2: パス定数を追加**

`app.py:64`（`HOLDINGS_PATH = DATA_DIR / "holdings.json"`の次の行）に追加する:

```python
SECTOR_DISPLAY_SETTINGS_PATH = DATA_DIR / "sector_display_settings.json"
```

- [ ] **Step 3: 「表示設定」expanderを追加**

`app.py:730-737`（`with tab_sector:`から`sector_period = st.selectbox(`の直前まで）を以下に置き換える:

```python
with tab_sector:
    st.header("セクターローテーション")
    st.caption(
        "UNIVERSE銘柄を17業種に分類し、業種間の値動きの時差相関（リード・ラグ）を"
        "過去の株価データから計算します。あくまで過去の統計的傾向であり、"
        "将来の値動きを保証するものではありません。"
    )

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

（この後に元のまま`sector_period = st.selectbox(`以降が続く。この時点ではまだTask 3を行わないため、`display_settings`変数はまだどこからも参照されないが、それで構わない）

- [ ] **Step 4: アプリを起動して動作確認**

Run: `uv run python -m streamlit run app.py`

確認項目:
1. 「セクターローテーション」タブを開き、説明キャプションの直後に「表示設定」expanderが（折りたたまれた状態で）表示される
2. expanderを開くと5つのチェックボックスが表示され、初期状態はすべてチェック済み
3. いずれかのチェックを外す →`ai-stock-investing-tutorial/app/data/sector_display_settings.json`が作成され、該当キーが`false`になっていることを確認する（`cat data/sector_display_settings.json`）
4. ブラウザをリロード（Streamlitの再実行）してもチェック状態が保持されている
5. この時点ではまだチェックを外してもタブの表示内容は変わらない（Task 3で対応）

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "$(cat <<'EOF'
Add display-settings expander to sector rotation tab

Wires up the persisted section-visibility settings as checkboxes at
the top of the tab; sections don't yet respect the settings.
EOF
)"
```

---

### Task 3: 5セクションを`display_settings`で表示制御

**Files:**
- Modify: `app.py:825-920` (ヒートマップ／リード・ラグ上位ペア表／AIコメントの3セクション), `app.py:922-958` (ネットワーク図), `app.py:960-1156` (ウェーブレット分析)

**Interfaces:**
- Consumes: `display_settings: dict[str, bool]`（Task 2で定義済みのローカル変数）
- Produces: なし（このタスクが最終タスク）

- [ ] **Step 1: ヒートマップ／リード・ラグ上位ペア表／AIコメントの3セクションを分岐**

`app.py:825`の`if pairs:`ブロック内（`app.py:826`〜`app.py:918`）を、既存コードの中身は一切変更せず、3箇所に`if display_settings[...]:`を追加してインデントを4スペース深くする。

現在の構造（`app.py:825-920`）:

```python
        if pairs:
            # 相関ペアの一覧から対称な相関行列（ヒートマップ用）を組み立てる
            sectors = sorted(
                ...
            )
            ...
            st.subheader(
                "業種間相関ヒートマップ",
                ...
            )
            heatmap = (
                ...
            )
            st.altair_chart(heatmap, width="stretch")

            st.subheader(
                "リード・ラグ上位ペア",
                ...
            )
            pairs_df = pd.DataFrame(pairs)[...]
            st.dataframe(...)

            with st.expander("リード・ラグの読み方"):
                st.markdown(...)

            st.subheader(
                "相関上位5ペアのAIコメント",
                ...
            )
            for pair in pairs[:5]:
                ...
        else:
            st.info("有効な業種ペアがありませんでした。")
```

変更後の構造（中身は完全に同一、`if display_settings[...]:`で3グループに分割してインデントするだけ）:

```python
        if pairs:
            if display_settings["heatmap"]:
                # 相関ペアの一覧から対称な相関行列（ヒートマップ用）を組み立てる
                sectors = sorted(
                    ...
                )
                ...
                st.subheader(
                    "業種間相関ヒートマップ",
                    ...
                )
                heatmap = (
                    ...
                )
                st.altair_chart(heatmap, width="stretch")

            if display_settings["pairs_table"]:
                st.subheader(
                    "リード・ラグ上位ペア",
                    ...
                )
                pairs_df = pd.DataFrame(pairs)[...]
                st.dataframe(...)

                with st.expander("リード・ラグの読み方"):
                    st.markdown(...)

            if display_settings["ai_comments"]:
                st.subheader(
                    "相関上位5ペアのAIコメント",
                    ...
                )
                for pair in pairs[:5]:
                    ...
        else:
            st.info("有効な業種ペアがありませんでした。")
```

`...`部分は元のコードをそのまま（1文字も変えず）、インデントだけ4スペース追加して移す。3グループの境界は次の行:
- グループ1「heatmap」: `app.py:826`（`sectors = sorted(`のコメント行）〜`app.py:865`（`st.altair_chart(heatmap, width="stretch")`）
- グループ2「pairs_table」: `app.py:867`（`st.subheader(`／「リード・ラグ上位ペア」）〜`app.py:904`（`with st.expander("リード・ラグの読み方"):`ブロックの終わり）
- グループ3「ai_comments」: `app.py:906`（`st.subheader(`／「相関上位5ペアのAIコメント」）〜`app.py:918`（forループの終わり）
- `else: st.info(...)`（`app.py:919-920`）はそのまま変更しない

- [ ] **Step 2: ネットワーク図セクションを分岐**

`app.py:922-958`（`st.subheader("業種間ネットワーク（全ペア俯瞰）"...)`から`_render_mermaid(mermaid_code)`まで）全体を`if display_settings["network_diagram"]:`で囲み、インデントを4スペース深くする。中身は変更しない。

```python
        if display_settings["network_diagram"]:
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
                _render_mermaid(mermaid_code)
```

- [ ] **Step 3: ウェーブレット分析セクションを分岐**

`app.py:960-1156`（`st.subheader("ウェーブレット分析（時間変化するリード・ラグ）"...)`から、AI解説の`st.markdown(cached_state["text"])`まで）全体を`if display_settings["wavelet_analysis"]:`で囲み、インデントを4スペース深くする。中身（`with st.expander("ウェーブレット分析とは？"):`、業種A/B選択、実行ボタン、ヒートマップ、支配的ラグ折れ線、直近シグナルサマリー、AI解説ボタンをすべて含む）は一切変更しない。

このブロックは分量が多いため、境界だけを正確に確認する:
- 開始: `app.py:960`の`st.subheader(`（第一引数`"ウェーブレット分析（時間変化するリード・ラグ）"`）
- 終了: `app.py:1156`の`st.markdown(cached_state["text"])`（その直後、`app.py:1157`は空行、`app.py:1158`から`if payload["skipped_tickers"]:`が続くが、これはウェーブレット分析セクションの外にある既存コードなので変更しない）

- [ ] **Step 4: アプリを起動して動作確認**

Run: `uv run python -m streamlit run app.py`

確認項目（`data/sector_display_settings.json`を都度編集するか、UIのチェックボックスで操作する）:
1. 全チェックON（デフォルト）の状態で「分析を実行」→ 5セクションすべてが今まで通り表示される
2. 「業種間相関ヒートマップ」のチェックを外して再実行 → ヒートマップだけが消え、リード・ラグ上位ペア表・AIコメント・ネットワーク図・ウェーブレット分析は表示されたまま
3. 「ウェーブレット分析」のチェックを外す → ウェーブレット分析セクション全体（業種選択・実行ボタン含む）が非表示になり、その下の「スキップした銘柄」情報や免責事項（`DISCLAIMER_NOTICE`）は引き続き表示される
4. 全チェックをOFFにする → 5セクションがすべて非表示になり、エラーは発生しない（`skipped_tickers`/`excluded_sectors`/免責事項は表示されたまま）
5. 有効な業種ペアが無い場合（`pairs`が空）の`st.info("有効な業種ペアがありませんでした。")`は、`heatmap`/`pairs_table`/`ai_comments`のチェック状態に関わらず常に表示される

- [ ] **Step 5: 既存の自動テストが壊れていないことを確認**

Run: `uv run pytest -v`
Expected: 既存の全テストがPASS（`app.py`はUI自動テスト対象外だが、他モジュールへの影響がないことを確認する）

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "$(cat <<'EOF'
Gate sector rotation sections behind display settings

Each of the five sections (heatmap, pairs table, AI comments, network
diagram, wavelet analysis) now renders only when its checkbox in the
display-settings expander is checked.
EOF
)"
```
