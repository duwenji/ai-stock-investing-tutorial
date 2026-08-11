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

`BACKTEST_RANK`はSTRATEGIESの4戦略（移動平均クロスオーバー/RSI逆張り/MACDクロスオーバー/
ボリンジャーバンド逆張り）のどれでも指定できる。`FILTER_CURRENT_SIGNAL`（直近シグナル
フィルタ）もこの4戦略すべてに対応させ、どの戦略を選んでも「①バックテストで上位を選ぶ→
②その戦略の直近シグナルで絞り込む→③再ランキング」という同じ3ステップパイプラインが
組み立てられるようにする。

## スコープ

- 対象: `app_tabs/strategy_builder_tab.py`（AI戦略ビルダータブ）の拡張
- v1関数レジストリ: `BACKTEST_RANK` / `FILTER_CURRENT_SIGNAL` / `FILTER_BY_FUNDAMENTALS` /
  `SORT_BY` / `TOP_N` の5関数。`BACKTEST_RANK`と`FILTER_CURRENT_SIGNAL`はSTRATEGIESの
  4戦略すべてに対応する
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
  → FILTER_CURRENT_SIGNAL（ENTRY）                         … 100件→23件
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
            "各銘柄について、直前のBACKTEST_RANKで使った戦略（_source_strategy列）"
            "そのものが直近5営業日以内に「エントリー」または「エグジット」シグナルを"
            "出したかどうかで絞り込む。戦略ごとの意味は次のとおり:\n"
            "・移動平均クロスオーバー: ENTRY＝短期MAが長期MAを下から上に抜けた"
            "（ゴールデンクロス）、EXIT＝その逆（デッドクロス）\n"
            "・MACDクロスオーバー: ENTRY＝MACD線がシグナル線を下から上に抜けた、"
            "EXIT＝その逆\n"
            "・RSI逆張り: ENTRY＝RSIが売られすぎ水準を下から上に抜けた（売られすぎから"
            "回復）、EXIT＝RSIが買われすぎ水準を上抜けた\n"
            "・ボリンジャーバンド逆張り: ENTRY＝終値が下バンドを下抜けた、EXIT＝終値が"
            "中心線（移動平均）を上抜けた\n"
            "各戦略のパラメータ（窓・閾値）は銘柄ごとのbest_params列（直前のBACKTEST_RANK"
            "が付与）を使う。best_paramsが無い、またはstrategy未指定の場合はparamsで"
            "明示されたstrategyとSTRATEGIESの既定パラメータを使う。"
        ),
        "params_schema": {
            "signal": "ENTRY または EXIT",
            "strategy": (
                "省略可。STRATEGIESのキー文字列。省略時は候補の_source_strategy列を使う"
            ),
        },
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

`BACKTEST_RANK`の出力には、既存の`total_return_pct`等に加えて`_source_strategy`列
（使用したSTRATEGIESキーをそのまま全行に設定）を追加する。`FILTER_CURRENT_SIGNAL`が
どの戦略の指標を計算すべきかを判断するために使う。

#### `FILTER_CURRENT_SIGNAL`（4戦略対応）

4戦略の「直近シグナル」はすべて次の2パターンのいずれかに帰着する。

- **2系列の交差**: 移動平均クロスオーバー（短期MA/長期MA）、MACDクロスオーバー
  （MACD線/シグナル線）、ボリンジャーバンド逆張り（終値/下バンド・終値/中心線）
- **1系列と閾値の交差**: RSI逆張り（RSI/売られすぎ・買われすぎ水準）

これを2つの汎用ヘルパーに集約する（新規、`pipeline_functions.py`）。

```python
def _detect_recent_cross(
    fast: pd.Series, slow: pd.Series, direction: str = "up", within_days: int = 5,
) -> bool:
    """2系列が直近within_days営業日以内に交差したかを判定する。
    データ不足（NaN混在含む）時はクロス無し（False）として扱う。"""
    if len(fast) < within_days + 1:
        return False
    recent_fast, recent_slow = fast.iloc[-(within_days + 1):], slow.iloc[-(within_days + 1):]
    if recent_fast.isna().any() or recent_slow.isna().any():
        return False
    is_above = fast > slow
    crossed_up = is_above & ~is_above.shift(1).fillna(False)
    crossed_down = ~is_above & is_above.shift(1).fillna(False)
    recent = crossed_up if direction == "up" else crossed_down
    return bool(recent.iloc[-within_days:].any())


def _detect_recent_threshold_cross(
    series: pd.Series, threshold: float, direction: str = "up", within_days: int = 5,
) -> bool:
    """1系列が直近within_days営業日以内に閾値を上抜け/下抜けしたかを判定する。"""
    is_above = series >= threshold if direction == "up" else series <= threshold
    crossed = is_above & ~is_above.shift(1).fillna(False)
    return bool(crossed.iloc[-within_days:].any())
```

戦略ごとの指標系列（短期/長期MA、MACD線/シグナル線、RSI、ボリンジャーバンド）は、
`portfolio_management/backtest.py`の`run_ma_crossover_backtest`等が内部で計算している
ロジックを**共有ヘルパーとして切り出し**（例: `compute_ma_crossover_series`,
`compute_macd_series`, `compute_rsi_series`, `compute_bollinger_bands`）、既存の
`run_*_backtest`関数とこの`FILTER_CURRENT_SIGNAL`の両方から呼び出す（指標計算ロジックの
重複を避ける）。

`FILTER_CURRENT_SIGNAL`の実行手順:

1. `strategy = params.get("strategy") or candidates_df["_source_strategy"].iloc[0]`
   （どちらも無ければそのステップをスキップしトレースにエラーを記録）
2. 候補銘柄の価格系列を`fetch_universe_price_histories(tickers, period="1y")`で取得
   （この時点で候補は数十〜100件程度のため軽量）
3. 銘柄ごとに`best_params`列（無ければSTRATEGIESの既定パラメータにフォールバックし、
   トレースに1回だけwarningを記録）を使って対応する指標系列を計算し、`strategy`と
   `signal`（ENTRY/EXIT）に応じた判定関数（`_detect_recent_cross`または
   `_detect_recent_threshold_cross`）を呼ぶ
4. Trueの行だけを残す

| strategy | signal=ENTRY | signal=EXIT |
|---|---|---|
| 移動平均クロスオーバー | `_detect_recent_cross(short_ma, long_ma, "up")` | 同, `"down"` |
| MACDクロスオーバー | `_detect_recent_cross(macd_line, signal_line, "up")` | 同, `"down"` |
| ボリンジャーバンド逆張り | `_detect_recent_cross(close, lower_band, "down")` | `_detect_recent_cross(close, middle_band, "up")` |
| RSI逆張り | `_detect_recent_threshold_cross(rsi, oversold, "up")` | `_detect_recent_threshold_cross(rsi, overbought, "up")` |

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
    {"function": "FILTER_CURRENT_SIGNAL", "params": {"signal": "ENTRY"}},
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

## 既存コードの小さな整理

**キャッシュ共有**: `BACKTEST_RANK`はユニバース全体のグリッドサーチを伴う最も重い処理であり、
`app_tabs/ranking_tab.py`が既に持つキャッシュ機構（戦略名・期間・コスト・対象銘柄集合の
ハッシュをキーに`common/cache.py`のread_cache/write_cacheを使う）と同じ考え方が必要になる。
このキャッシュキー生成・読み書きロジックを`ranking_tab.py`から
`portfolio_management/backtest.py`に小関数として切り出し、`ranking_tab.py`と新規
`pipeline_functions.py`の両方から共有する。

**指標計算ロジックの共有**: `portfolio_management/backtest.py`の`run_ma_crossover_backtest`/
`run_rsi_reversal_backtest`/`run_macd_crossover_backtest`/`run_bollinger_reversal_backtest`は
現状、各戦略の指標系列（短期/長期MA、RSI、MACD線/シグナル線、ボリンジャーバンド）を
`position`計算のためだけに内部で計算しており、系列自体を外に返さない。これを
`compute_ma_crossover_series`/`compute_rsi_series`/`compute_macd_series`/
`compute_bollinger_bands`として切り出し、各`run_*_backtest`関数と新規
`FILTER_CURRENT_SIGNAL`の両方から呼び出す。指標計算ロジックの二重実装を避けるための
整理であり、既存バックテストの計算結果（`total_return_pct`等）は変更されない。

## テスト方針

既存規約（pytest、monkeypatchでネットワーク呼び出しを排除、`create_db_engine`で
一時DBを使う）に従う。

- `pipeline_functions.py`: 各関数の正常系・空データ・不正params（登録外の値等）
- `_detect_recent_cross`/`_detect_recent_threshold_cross`: 窓内クロス→True、窓外→False、
  データ不足（NaN混在含む）→False、クロス無し→False、下方向（EXIT）
- `FILTER_CURRENT_SIGNAL`: 4戦略それぞれでENTRY/EXITが正しい指標・判定関数に
  ディスパッチされること、`_source_strategy`列からのstrategy自動解決、
  best_params欠如時のSTRATEGIES既定値へのフォールバック
- `backtest.py`から切り出す指標計算ヘルパー（`compute_ma_crossover_series`等）:
  既存`run_*_backtest`のポジション計算結果が切り出し前後で変わらないことの回帰確認
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
