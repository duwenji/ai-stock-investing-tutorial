# AI戦略ビルダー: 関数チェーン方式スクリーニングパイプライン 設計書

## 背景・目的

現在の「AI戦略ビルダー」タブは、ユーザーの投資アイデアをAIとの対話でPER/PBR/ROE等の
ファンダメンタルズ条件（`conditions`）に変換し、それをその場のスナップショットに
適用してスクリーニングする機能のみを持つ。

これに対し、以下のような複数ステップにまたがるスクリーニングは現状実現できない。

> 1. 「移動平均クロスオーバー」戦略で全銘柄を一括バックテストし、リスク調整済み
>    リターン（収益率÷|最大ドローダウン|）が高い順の上位100銘柄を選ぶ
> 2. その上位100銘柄から、直近でゴールデンクロスした銘柄だけを絞り込む
> 3. 絞り込んだ銘柄を再度リスク調整済みリターンでランキングする

この設計では、「バックテストランキング」「直近シグナルフィルタ」「ファンダメンタルズ
フィルタ」「並べ替え」「上位N件抽出」といった再利用可能な関数群（レジストリ）を整備し、
AIとの対話が自然言語の要望からこれらの関数をどの順番・組み合わせで呼ぶかを都度
JSONとして生成し、Python側が生成された`steps`をそのまま実行する。処理フローは
コード上に固定されず、AIが要望ごとに自由に組み立てる。

将来的に別の要望（例:「RSI逆張り戦略で上位50銘柄を選び、配当利回り3%以上で絞る」）
にも、レジストリに関数を追加するだけで対応できることを狙う。

## スコープ

- 対象: `app_tabs/strategy_builder_tab.py`（AI戦略ビルダータブ）の拡張
- v1関数レジストリ: `BACKTEST_RANK` / `FILTER_CURRENT_SIGNAL` / `FILTER_BY_FUNDAMENTALS` /
  `SORT_BY` / `TOP_N` の5関数
- 既存の`conditions`ベース戦略（保存済みDB上の既存データ、③④の既存UIロジック）は
  非破壊のまま維持する（後方互換）。新規に対話で作られる戦略は`steps`形式になる。
- ネイティブなLLM Function Calling API（tool_use）は使わない。既存の
  `screening.py`/`conditions.py`と同じ「LLMにJSONを出力させ、Python側で
  ホワイトリスト方式に安全に実行する」パターンを踏襲する。

## アーキテクチャ

候補銘柄テーブル（`ticker`列を含む`pd.DataFrame`）を共通データ形式とし、レジストリの
各関数は `(candidates_df: pd.DataFrame, params: dict) -> pd.DataFrame` という統一
シグネチャを持つ。実行エンジンはAIが生成した`steps`（`[{"function": ..., "params": {...}}, ...]`）
を先頭から順に適用するだけの薄い実装であり、どの関数をどの順で呼ぶかという
「フロー」自体はコードに存在しない。

```
全銘柄(company_profiles) の ticker 列のみの DataFrame
  → steps[0] 適用 → steps[1] 適用 → ... → 最終結果テーブル
```

例（ゴールデンクロス・低リスク高収益スクリーニングの場合）:

```
全銘柄
  → BACKTEST_RANK（移動平均クロスオーバー, top_n=100）  … 4444件→100件
  → FILTER_CURRENT_SIGNAL（GOLDEN_CROSS）                 … 100件→23件
  → SORT_BY（risk_adjusted_return, DESC）                 … 23件（並べ替えのみ）
```

別の要望（例: RSI逆張り→配当利回りフィルタ）が来れば、AIは
`BACKTEST_RANK(strategy=RSI逆張り) → FILTER_BY_FUNDAMENTALS(dividend_yield_pct>=3)`
のような別のstepsをそのまま生成でき、コード変更は不要。

## 新規モジュール

### `strategy_builder/pipeline_functions.py`

関数レジストリ本体。

```python
PIPELINE_FUNCTIONS: dict[str, dict] = {
    "BACKTEST_RANK": {
        "description": (
            "対象銘柄群をSTRATEGIES（移動平均クロスオーバー/RSI逆張り/MACDクロスオーバー/"
            "ボリンジャーバンド逆張り）のいずれかでバックテストし、銘柄ごとに近傍グリッド"
            "サーチで最適パラメータを探索してリスク調整済みリターン（収益率÷|最大ドロー"
            "ダウン|）降順にランキングし、上位top_n件に絞る。出力列: total_return_pct, "
            "benchmark_return_pct, win_rate_pct, max_drawdown_pct, risk_adjusted_return, "
            "best_params。"
        ),
        "params_schema": {
            "strategy": "STRATEGIESのキー文字列（例: 移動平均クロスオーバー）",
            "period": "1y/3y/5y",
            "transaction_cost_pct": "数値（省略時0）",
            "top_n": "整数（省略時は絞り込みなし）",
        },
    },
    "FILTER_CURRENT_SIGNAL": {
        "description": (
            "各銘柄の直近5営業日以内に発生した移動平均クロスで絞り込む。GOLDEN_CROSS＝"
            "短期MAが長期MAを直近5営業日以内に下から上に抜けた銘柄、DEAD_CROSSはその逆。"
            "直前にBACKTEST_RANK（移動平均クロスオーバー）があれば銘柄ごとのbest_params"
            "（short_window/long_window）を使う。無ければ既定25/75を使う。"
        ),
        "params_schema": {"signal": "GOLDEN_CROSS または DEAD_CROSS"},
    },
    "FILTER_BY_FUNDAMENTALS": {
        "description": (
            "PER/PBR/ROE/配当利回り/売上高伸び率/時価総額/業種でフィルタする"
            "（既存apply_strategy_conditionsと同じindicator/operatorスキーマ）。"
        ),
        "params_schema": {"conditions": "既存のconditions配列と同じ形式"},
    },
    "SORT_BY": {
        "description": (
            "その時点で存在する列で並べ替える。fieldが存在しない列の場合は"
            "既存apply_filters/apply_strategy_conditionsと同じ方針で並べ替えをスキップし"
            "元の順序のまま返す（トレースにその旨を記録）。"
        ),
        "params_schema": {"field": "列名", "order": "ASC または DESC"},
    },
    "TOP_N": {
        "description": (
            "指定件数に絞る。byが指定されていればその列で降順ソートしてから先頭n件を、"
            "byが省略されていれば直前の並び順のまま先頭n件を取る。"
        ),
        "params_schema": {"n": "整数", "by": "列名（省略可）"},
    },
}
```

各関数の実体（`_run_backtest_rank`等）は同ファイル内のプライベート関数として実装し、
`BACKTEST_RANK`は既存`run_universe_backtest_ranking`（`portfolio_management/backtest.py`）を、
`FILTER_BY_FUNDAMENTALS`は既存`apply_strategy_conditions`（`strategy_builder/conditions.py`）を、
`SORT_BY`は既存`sort_by_strategy`を汎用化したロジックをそれぞれラップ・再利用する。

`FILTER_CURRENT_SIGNAL`のクロス判定は新規関数として実装する。

```python
def _detect_recent_ma_cross(
    close: pd.Series,
    short_window: int,
    long_window: int,
    direction: str = "up",
    within_days: int = 5,
) -> bool:
    """直近within_days営業日以内に移動平均のクロスが発生したかを判定する。
    データ不足時はクロス無し（False）として扱う（既存の「データ不足」方針と同じ）。"""
    if len(close) < long_window + within_days:
        return False
    short_ma = close.rolling(short_window).mean()
    long_ma = close.rolling(long_window).mean()
    is_above = short_ma > long_ma
    crossed_up = is_above & ~is_above.shift(1).fillna(False)
    crossed_down = ~is_above & is_above.shift(1).fillna(False)
    recent = crossed_up if direction == "up" else crossed_down
    return bool(recent.iloc[-within_days:].any())
```

`FILTER_CURRENT_SIGNAL`は候補銘柄の価格系列を`fetch_universe_price_histories(tickers, period="1y")`
で取得し（この時点で候補は数十〜100件程度のため軽量）、銘柄ごとに`best_params`列
（無ければ既定25/75）を使って`_detect_recent_ma_cross`を呼び、Trueの行だけを残す。
`best_params`に`short_window`/`long_window`キーが無い場合（別戦略のbest_paramsが
渡された等）は既定値25/75にフォールバックし、トレースログに1回だけwarningを出す。

### `strategy_builder/pipeline.py`

実行エンジン。

```python
def run_pipeline(steps: list[dict], all_tickers: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """全銘柄のticker列のみのDataFrameを初期値とし、stepsを先頭から順に適用する。
    戻り値は (最終結果DataFrame, 各ステップの実行トレース文字列のリスト)。
    未知のfunction名や例外を送出したステップはスキップし、トレースに理由を記録して
    処理を継続する（既存apply_filtersと同じ「壊れたLLM出力で全体を落とさない」方針）。
    """
```

## 戦略JSONスキーマの拡張

既存スキーマ（`strategy_name`, `conditions`, `sort_by`, `order`）はそのまま残し、
新たに`steps`キーを追加する。両方が同時に存在することはない（対話で生成される
戦略は常にどちらか一方）。

```json
{
  "strategy_name": "ゴールデンクロス・低リスク高収益スクリーニング",
  "steps": [
    {"function": "BACKTEST_RANK", "params": {"strategy": "移動平均クロスオーバー", "period": "3y", "top_n": 100}},
    {"function": "FILTER_CURRENT_SIGNAL", "params": {"signal": "GOLDEN_CROSS"}},
    {"function": "SORT_BY", "params": {"field": "risk_adjusted_return", "order": "DESC"}}
  ]
}
```

`prompt_patterns/strategy_dialogue.py`の`_PERSONA_INSTRUCTIONS`を書き換え、
`PIPELINE_FUNCTIONS`の関数名・説明・params_schemaをプロンプトに埋め込んだうえで、
「ユーザーの要望を分析し、上記関数を必要な順番・組み合わせで並べたstepsを出力する」
よう指示する。`parse_dialogue_response`は`"steps"`キーの有無で新旧スキーマを判定する
（`"steps"`があれば新形式、`"conditions"`のみなら旧形式として扱う）。

`build_refinement_prompt`（Evaluator-Optimizerの改善ステップ）も同様に`steps`形式に
対応させる。

## UI変更（`app_tabs/strategy_builder_tab.py`）

②対話で確定した戦略に`"steps"`キーがあるかどうかで分岐する。

- **`"conditions"`のみ（旧形式）**: 既存の③バックテスト検証／④最新データで銘柄選定の
  コードパスは無変更。
- **`"steps"`あり（新形式）**: ③④を統合した新セクション**「③ パイプラインを実行」**を表示する。
  - 実行ボタン押下で`load_all_company_profiles()`から全ticker一覧を取り`run_pipeline`を呼ぶ
  - 各ステップ後の件数・内容をトレースとして表示（例:
    `BACKTEST_RANK: 4444件→100件` → `FILTER_CURRENT_SIGNAL: 100件→23件` → `SORT_BY: 23件`）
  - 最終結果テーブルをその時点で存在する列（ticker/name/現在値/risk_adjusted_return等）で
    動的に表示し、既存の行クリック→銘柄詳細遷移（`handle_table_selection`）を流用する

## 既存コードの小さな整理（キャッシュ共有）

`BACKTEST_RANK`はユニバース全体のグリッドサーチを伴う最も重い処理であり、
`app_tabs/ranking_tab.py`が既に持つキャッシュ機構（戦略名・期間・コスト・対象銘柄集合の
ハッシュをキーに`common/cache.py`のread_cache/write_cacheを使う）と同じ考え方が必要になる。
このキャッシュキー生成・読み書きロジックを`ranking_tab.py`から
`portfolio_management/backtest.py`に小関数として切り出し、`ranking_tab.py`と新規
`pipeline_functions.py`の両方から共有する。

## テスト方針

既存規約（pytest、monkeypatchでネットワーク呼び出しを排除、`create_db_engine`で
一時DBを使う）に従う。

- `pipeline_functions.py`: 各関数の正常系・空データ・不正params（登録外の値等）
- `_detect_recent_ma_cross`: 窓内クロス→True、窓外→False、データ不足→False、
  クロス無し→False、下方クロス（DEAD_CROSS）
- `pipeline.py`の`run_pipeline`: 未知function名のスキップ、複数ステップの列引き継ぎ、
  トレースログの内容
- `strategy_dialogue.py`: `steps`形式の解析、新旧スキーマの判定分岐
- `strategy_builder_tab.py`: `steps`あり/なしでのUI分岐（既存の`conditions`のみの
  挙動が変わっていないことを含む）
- `backtest.py`のキャッシュ共有関数の切り出しによるranking_tab既存テストの非破壊確認

## 非スコープ（v1では対応しない）

- ネイティブLLM Function Calling API（tool_use）の導入
- `within_days`（クロス判定期間）のパラメータ化。固定5営業日
- セクターローテーション等、他の既存分析機能のレジストリへの統合
- 旧`conditions`形式で保存済みの戦略を`steps`形式へ自動移行するマイグレーション
