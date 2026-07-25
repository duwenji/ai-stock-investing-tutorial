# セクターローテーション 表示順序・サイズ・ズーム調整機能 設計書

## 概要・目的

[表示コンテンツのユーザ設定機能](2026-07-25-sector-rotation-display-settings-design.md)により、セクターローテーションタブの5セクション（ヒートマップ／リード・ラグ上位ペア表／AIコメント／ネットワーク図／ウェーブレット分析）は表示/非表示を切り替えられるようになった。しかし依然として画面が縦に長く、チャートの表示領域を広く使いたい・見たい順序に並べ替えたい・チャートを拡大縮小して細部を確認したい、というニーズが残っている。

本機能では、既存の表示設定の仕組みを拡張し、次の3点を可能にする:

1. **表示順序**: 5セクションの並び順をユーザーが指定できるようにする
2. **サイズ**: チャートを含む3セクション（ヒートマップ・ネットワーク図・ウェーブレット分析）の表示の高さを調整できるようにする
3. **ズーム**: Altairチャート・Mermaidネットワーク図をマウスホイール／ドラッグで拡大縮小・パンできるようにする

あわせて、「表示設定」expander・取得期間・キャッシュ無視・分析実行ボタンといった上部コントロール群を縦方向によりコンパクトにまとめ、チャート表示領域を最大化する。

既存の「分析を実行」ロジック（データ取得・全セクション分の計算）は変更しない。今回もあくまで**表示側**の変更にとどめる。

## スコープ

- v1で実装する:
  - `sector_analysis/display_settings.py`: 設定スキーマを`visible`/`order`/`height`の3辞書構成に拡張し、旧フラットbool形式のファイルを後方互換で読み込めるようにする
  - `app.py`: 上部コントロール（取得期間・キャッシュ無視・分析実行ボタン）を`st.columns`で1行にまとめる
  - `app.py`: 「表示設定」expander内のチェックボックス群を、表示ON/OFF・表示順序を編集できる`st.data_editor`テーブルに置き換える
  - `app.py`: チャート系3セクション（ヒートマップ・ネットワーク図・ウェーブレット分析）が表示中の場合のみ、その高さを調整するスライダーを表示する
  - `app.py`: Altairチャート3つ（相関ヒートマップ・ウェーブレットヒートマップ・支配的ラグ折れ線）に`.interactive()`を付与し、ホイールズーム・ドラッグパンを有効化する
  - `app.py`: `_render_mermaid`に`svg-pan-zoom.js`（CDN）を追加し、ネットワーク図をドラッグパン・ホイールズームできるようにする
  - 5セクションの描画ロジックを関数化し、`order`設定でソートした順に呼び出す構成へリファクタリングする
- v1で実装しない（将来課題）:
  - 非表示セクションの計算スキップ（高速化、既存設計書から引き続き将来課題）
  - 他タブ（ポートフォリオ・スクリーニング等）への同様の表示制御機能の展開
  - セクション単位のドラッグ&ドロップによる並び替えUI（今回は数値入力による順序指定）
  - ネットワーク図・チャートの幅（横方向サイズ）調整（今回は高さのみ。幅は既存通り`width="stretch"`で画面幅に追従）

## データ設計 — `sector_analysis/display_settings.py`

### 新スキーマ

```python
DEFAULT_SECTOR_DISPLAY_SETTINGS: dict[str, dict] = {
    "visible": {
        "heatmap": True,
        "pairs_table": True,
        "ai_comments": True,
        "network_diagram": True,
        "wavelet_analysis": True,
    },
    "order": {
        "heatmap": 1,
        "pairs_table": 2,
        "ai_comments": 3,
        "network_diagram": 4,
        "wavelet_analysis": 5,
    },
    "height": {
        "heatmap": 500,
        "network_diagram": 400,
        "wavelet_analysis": 400,
    },
}
```

- `visible`/`order`は5セクション全キーを持つ。`height`はチャートを持つ3セクションのみキーを持つ（`pairs_table`・`ai_comments`は高さ調整の対象外のため含めない）
- `order`は1〜5の整数（UI側で`st.column_config.NumberColumn(min_value=1, max_value=5, step=1)`により範囲を強制する）。重複や欠番があってもエラーにはせず、表示順の決定（後述）で安定ソートにより解決する
- `height`はピクセル値（スライダーで250〜900、50刻みを想定）

### `load_sector_display_settings(path: Path) -> dict[str, dict]`

読み込み時のフォールバック規則（既存方針を踏襲し拡張）:

| 事象 | 挙動 |
| --- | --- |
| ファイルが存在しない | デフォルト設定（`DEFAULT_SECTOR_DISPLAY_SETTINGS`のコピー）を返す |
| JSONとして壊れている | デフォルト設定を返す |
| 内容が辞書でない | デフォルト設定を返す |
| **後方互換**: 読み込んだ辞書のトップレベルキーが`visible`/`order`/`height`のいずれも含まず、既知の5セクションキー（`heatmap`等）の値がすべてbool（旧フラット形式） | そのままの値を`visible`として採用し、`order`・`height`はデフォルト値を使う |
| `visible`/`order`/`height`の各サブ辞書内で、既知キーの値が欠落・型不正（`visible`はbool以外、`order`は整数以外、`height`は数値以外） | 該当キーのみデフォルト値で補う |
| `order`/`height`の値が想定範囲外（例: `order`が0や6、`height`が極端な値） | そのまま採用する（UI側の`NumberColumn`/`slider`で通常は範囲内に収まるため、読み込み時点では範囲チェックしない。壊れたファイルを手編集された場合の表示崩れは許容する） |
| 将来削除されたセクションのキーが残っている | 無視する |

新形式の判定は「トップレベルが`{"visible": ..., "order": ..., "height": ...}`の形かどうか」で行う。具体的には、トップレベル辞書に`visible`キーが存在し、かつその値が辞書であれば新形式として扱い、そうでなければ（トップレベルの値がbool中心なら）旧形式として扱う。

### `save_sector_display_settings(path: Path, settings: dict) -> None`

新スキーマのまま`json.dumps`して保存する（既存の保存パターンを踏襲、ディレクトリ自動作成も踏襲）。保存後は常に新形式になるため、一度保存が走れば以後は新形式として読み込まれる。

## UI設計 — `app.py`

### 上部コントロールの1行化

`tab_sector`の構成を次の順序に変更する:

```python
with tab_sector:
    st.header("セクターローテーション")
    st.caption(...)  # 既存のまま

    display_settings = load_sector_display_settings(SECTOR_DISPLAY_SETTINGS_PATH)
    with st.expander("表示設定"):
        ...  # 後述の表示順序テーブル・高さスライダー

    col_period, col_regen, col_run = st.columns(3)
    with col_period:
        sector_period = st.selectbox("取得期間", ["6mo", "1y", "2y"], index=1, key="sector_period", help=...)
    with col_regen:
        sector_force_regenerate = st.checkbox("キャッシュを無視して再生成する", key="sector_force_regenerate", help=...)
    with col_run:
        run_clicked = st.button("分析を実行", help=...)

    if run_clicked:
        ...  # 既存のまま
```

「表示設定」expanderは折りたたみ時は1行だけなので、単独行のままとする（狭い列に入れて中の表を圧迫させないため）。取得期間・キャッシュ無視・分析実行ボタンの3つを`st.columns(3)`で1行にまとめることで、既存の縦3行分の余白を1行に圧縮する。

### 表示順序・サイズ設定（「表示設定」expander内）

```python
with st.expander("表示設定"):
    st.caption(
        "表示のON/OFFと並び順を指定できます"
        "（設定は次回起動時も保持されます）。"
    )
    section_labels = {
        "heatmap": "業種間相関ヒートマップ",
        "pairs_table": "リード・ラグ上位ペア",
        "ai_comments": "相関上位5ペアのAIコメント",
        "network_diagram": "業種間ネットワーク（全ペア俯瞰）",
        "wavelet_analysis": "ウェーブレット分析",
    }
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
            "key": None,  # 非表示列（内部キー保持用）
            "セクション": st.column_config.TextColumn(disabled=True),
            "表示": st.column_config.CheckboxColumn(),
            "順序": st.column_config.NumberColumn(min_value=1, max_value=5, step=1),
        },
        hide_index=True,
        key="sector_section_editor",
    )
    new_visible = dict(zip(edited_df["key"], edited_df["表示"]))
    new_order = dict(zip(edited_df["key"], edited_df["順序"]))

    new_height = dict(display_settings["height"])
    height_specs = [
        ("heatmap", "業種間相関ヒートマップの高さ"),
        ("network_diagram", "業種間ネットワークの高さ"),
        ("wavelet_analysis", "ウェーブレット分析ヒートマップの高さ"),
    ]
    for key, label in height_specs:
        if new_visible[key]:
            new_height[key] = st.slider(
                label, 250, 900, display_settings["height"][key], 50,
                key=f"sector_height_{key}",
            )

    new_display_settings = {"visible": new_visible, "order": new_order, "height": new_height}
    if new_display_settings != display_settings:
        save_sector_display_settings(SECTOR_DISPLAY_SETTINGS_PATH, new_display_settings)
        display_settings = new_display_settings
```

- 高さスライダーは、対応するセクションが「表示」ONの場合のみ表示する（非表示セクションのスライダーを出しても操作対象が見えず混乱するため）。非表示中も設定値自体は`display_settings["height"]`に保持されたままなので、再度表示ONにすれば直前の値が復元される
- `st.data_editor`のcolumn_configで`順序`をNumberColumn（1〜5固定範囲）にすることでUI上は範囲外入力を防ぐが、内部的に重複が発生しても後述の安定ソートで表示は破綻しない

### 表示順序に基づく描画（関数化リファクタリング）

現状、5セクションの描画は`if pairs: ... else: st.info(...)` → `if display_settings["network_diagram"]: ...` → `if display_settings["wavelet_analysis"]: ...` という直列コードになっている。順序変更に対応するため、各セクションの描画を関数化し、`order`でソートした順に呼び出す形に再構成する。

```python
if st.session_state.get("sector_payload") is not None:
    payload = st.session_state["sector_payload"]
    pairs = payload["pairs"]

    if not pairs:
        st.info("有効な業種ペアがありませんでした。")

    def _render_heatmap():
        ...  # 既存の「業種間相関ヒートマップ」の中身。.properties(height=display_settings["height"]["heatmap"]).interactive() を追加

    def _render_pairs_table():
        ...  # 既存の「リード・ラグ上位ペア」の中身（変更なし）

    def _render_ai_comments():
        ...  # 既存の「相関上位5ペアのAIコメント」の中身（変更なし）

    def _render_network_diagram():
        ...  # 既存の「業種間ネットワーク」の中身。_render_mermaid(mermaid_code, height=display_settings["height"]["network_diagram"])

    def _render_wavelet_analysis():
        ...  # 既存の「ウェーブレット分析」の中身。メインヒートマップに
             # .properties(height=display_settings["height"]["wavelet_analysis"]).interactive() を追加
             # （支配的ラグ折れ線は既存どおり height=250 固定、こちらも .interactive() のみ追加）

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
            continue  # pairsが空の場合はこの3セクションを描画しない（st.infoは既に表示済み）
        if display_settings["visible"][key]:
            section_renderers[key]()
```

- `pairs`が空の場合の`st.info(...)`は、順序設定に関わらず常に一番先に表示する（エラー状態の告知であり、並び替え対象の「コンテンツ」ではないため。既存方針を踏襲）
- 各関数はクロージャとして`payload`・`pairs`・`display_settings`・`sector_x`/`sector_y`選択用の`st.session_state`キー等、既存コードが参照していた変数をそのまま参照する。中身のロジック自体は変更しない（`.interactive()`呼び出し追加と、`height=`の参照先を固定値から`display_settings["height"][...]`に変える点を除く）

### ズーム対応

**Altairチャート（相関ヒートマップ・ウェーブレットヒートマップ・支配的ラグ折れ線）**

`.properties(height=...)`の後に`.interactive()`を追加するだけ。Vega-Liteの標準機能で、マウスホイールでズーム、ドラッグでパンができるようになる。新規依存なし。

```python
heatmap = (
    alt.Chart(heatmap_df)
    .mark_rect()
    .encode(...)
    .properties(height=display_settings["height"]["heatmap"])
    .interactive()
)
```

**Mermaidネットワーク図**

`_render_mermaid`に`svg-pan-zoom.js`（CDN）を追加し、mermaid描画完了後にSVG要素へパン・ズームを有効化する。mermaid v10の`startOnLoad`は非同期処理のタイミング制御が難しいため、`startOnLoad: false`にして明示的に`mermaid.run()`を呼び、完了後に`svgPanZoom`を初期化する:

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
          svgPanZoom(svgEl, {{ zoomEnabled: true, controlIconsEnabled: true, fit: true, center: true }});
        }}
      }});
    </script>
    """
    components.html(html, height=height, scrolling=True)
```

- `height`引数は既存どおり呼び出し側（`_render_network_diagram`関数）から`display_settings["height"]["network_diagram"]`を渡す
- `controlIconsEnabled: true`により、ズームイン/アウト・リセットボタンがSVG右下に表示される
- mermaid.js・svg-pan-zoom.js共にCDN読み込みのため、インターネット接続が必要（既存のmermaid.js利用時点で既にこの制約は存在するため新たな制約ではない）

## エラーハンドリング

| 事象 | 挙動 |
| --- | --- |
| `sector_display_settings.json`が旧フラットbool形式 | `visible`として読み込み、`order`/`height`はデフォルト値を使う（後方互換） |
| JSONとして壊れている・辞書でない | 全項目デフォルト設定にフォールバック |
| `order`に重複・欠番がある | エラーにせず、安定ソートで一貫した順序を決定する |
| `pairs`が空 | 順序・表示設定に関わらず、ヒートマップ・ペア表・AIコメントの3セクションは描画せず`st.info`のみ表示する |
| CDN（mermaid.js/svg-pan-zoom.js）が読み込めない環境 | ネットワーク図が描画されない（既存のmermaid.js単体使用時と同じ制約、新規のエラーハンドリングは追加しない） |

## テスト方針

- `tests/test_sector_display_settings.py`（既存ファイルを新スキーマに合わせて全面改訂）:
  - ファイルが存在しない場合、`DEFAULT_SECTOR_DISPLAY_SETTINGS`と等しい値を返すことを検証
  - 新スキーマでの保存→読み込みラウンドトリップを検証
  - 旧フラットbool形式のファイルを読み込むと、`visible`にその内容が反映され、`order`/`height`がデフォルト値になることを検証（後方互換）
  - 壊れたJSON・非辞書JSONの場合、デフォルト設定を返すことを検証
  - `visible`/`order`/`height`の一部キーが欠落・型不正の場合、該当キーのみデフォルト値で補われることを検証
  - 未知のキーが読み込み結果に含まれないことを検証
- `app.py`のUI変更（1行化・表・スライダー・ズーム）は既存方針通り自動テスト対象外。`uv run python -m streamlit run app.py`で以下を手動確認する:
  1. 上部コントロールが1行にまとまっていること
  2. 表示設定expanderの表で表示ON/OFF・順序を変更すると、タブ内のセクション表示順が追従すること
  3. チャート系3セクションの高さスライダーを操作すると、該当チャートの高さが変わること（非表示にすると対応スライダーが消えること）
  4. 相関ヒートマップ・ウェーブレットヒートマップ・支配的ラグ折れ線をマウスホイールでズーム、ドラッグでパンできること
  5. ネットワーク図をドラッグ・ホイールでズーム/パンでき、右下のズームコントロールアイコンが機能すること
  6. 既存の`data/sector_display_settings.json`（旧フラット形式）が入った状態でアプリを起動しても、表示設定expanderが正しい初期状態（旧設定の表示ON/OFFが反映され、順序はデフォルト1〜5、高さはデフォルト500/400/400）で表示されること
- `uv run pytest -v`で既存の全テストが引き続きPASSすることを確認する

## v1スコープ外（将来課題）

- 非表示セクションの計算スキップによる高速化
- 他タブへの同様の表示制御機能の展開
- ドラッグ&ドロップによるセクション並び替えUI
- チャートの幅（横方向サイズ）調整
