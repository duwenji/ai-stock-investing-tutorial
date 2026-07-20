# セクターローテーション分析 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** UNIVERSE（228銘柄）を17業種に分類し、業種間の値動きの時差相関（リード・ラグ）を株価データのみから計算して可視化する新タブ「セクターローテーション」を追加する。

**Architecture:** `screening/sectors.py`に静的な`SECTOR_MAP`（ティッカー→17業種名）を追加。新規パッケージ`sector_analysis/`の`correlation.py`で業種別リターン算出とリード・ラグ計算を行う純粋関数を実装。`prompt_patterns/sector_rotation.py`で相関上位ペアのAI考察コメントを既存の`generate_ranking_comments`と同一パターン（1回のプロンプトでバッチJSON生成）で実装。`app.py`に新タブを追加し、既存の一括バックテストタブと同じ並列取得・キャッシュ・UIパターンを踏襲する。

**Tech Stack:** Python 3.14, pandas, numpy, altair, pytest, uv

## Global Constraints

- 新規の実行時依存追加なし（チャートは既存依存のAltairを使用）
- 外部マクロ経済指標は取得しない。景気サイクルの解釈は株価データから計算したリード・ラグをもとにAIコメントとして生成する
- 事実データの計算はPython側で行い、AIには考察のみ生成させる。売買の推奨・指示はしない（`DISCLAIMER_NOTICE`を必ず表示）
- `SECTOR_MAP`のキー集合は`UNIVERSE`（`screening/universe.py`）と完全一致すること
- キャッシュキー構造・ファイル形式は既存`common/cache.py`のパターン（`data/cache/YYYY-MM-DD-<key>.txt`）を踏襲する

---

### Task 1: SECTOR_MAPを追加する

**Files:**
- Create: `screening/sectors.py`
- Test: `tests/test_sectors.py`

**Interfaces:**
- Consumes: `screening.universe.UNIVERSE`（既存）
- Produces: `SECTOR_MAP: dict[str, str]`（228件、キーは`UNIVERSE`と同一のティッカー、値は17業種区分名の日本語文字列）。後続タスクはこのシンボルを`sector_analysis.correlation.compute_sector_returns`の第2引数として利用する。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_sectors.py` を新規作成する:

```python
from screening.sectors import SECTOR_MAP
from screening.universe import UNIVERSE


def test_sector_map_keys_match_universe():
    assert set(SECTOR_MAP.keys()) == set(UNIVERSE)


def test_sector_map_values_are_non_empty_strings():
    assert all(isinstance(sector, str) and sector for sector in SECTOR_MAP.values())


def test_sector_map_covers_all_seventeen_sectors():
    expected_sectors = {
        "食品", "エネルギー資源", "建設・資材", "素材・化学", "医薬品",
        "自動車・輸送機", "鉄鋼・非鉄", "機械", "電機・精密", "運輸・物流",
        "商社・卸売", "小売", "銀行", "金融（除く銀行）", "不動産",
        "情報通信・サービスその他", "電力・ガス",
    }
    assert set(SECTOR_MAP.values()) == expected_sectors
```

- [ ] **Step 2: テストを実行し、失敗することを確認する**

Run: `cd app && uv run pytest tests/test_sectors.py -v`
Expected: `ModuleNotFoundError: No module named 'screening.sectors'` でFAIL

- [ ] **Step 3: `screening/sectors.py`を作成する**

```python
# SECTOR_MAPはUNIVERSE（screening/universe.py）の全銘柄を17業種区分（東証）に
# 分類したもの。app/docs/data_j.xls（JPX公式全銘柄一覧）の「17業種区分」列から
# 抽出。543A（ARCHION、2026年4月上場）のみdata_j.xlsに未収録のため、日野自動車と
# 三菱ふそうの経営統合会社であることから手動で「自動車・輸送機」を割り当てた。
# UNIVERSE更新時はこのファイルも合わせて更新すること。
SECTOR_MAP: dict[str, str] = {
    "1332.T": "食品",
    "1605.T": "エネルギー資源",
    "1721.T": "建設・資材",
    "1801.T": "建設・資材",
    "1802.T": "建設・資材",
    "1803.T": "建設・資材",
    "1808.T": "建設・資材",
    "1812.T": "建設・資材",
    "1925.T": "建設・資材",
    "1928.T": "建設・資材",
    "1963.T": "建設・資材",
    "2002.T": "食品",
    "2269.T": "食品",
    "2282.T": "食品",
    "2413.T": "情報通信・サービスその他",
    "2432.T": "情報通信・サービスその他",
    "2501.T": "食品",
    "2502.T": "食品",
    "2503.T": "食品",
    "2768.T": "商社・卸売",
    "2801.T": "食品",
    "2802.T": "食品",
    "285A.T": "電機・精密",
    "2871.T": "食品",
    "2914.T": "食品",
    "3086.T": "小売",
    "3092.T": "小売",
    "3099.T": "小売",
    "3289.T": "不動産",
    "3382.T": "小売",
    "3401.T": "素材・化学",
    "3402.T": "素材・化学",
    "3405.T": "素材・化学",
    "3407.T": "素材・化学",
    "3436.T": "建設・資材",
    "3659.T": "情報通信・サービスその他",
    "3697.T": "情報通信・サービスその他",
    "3861.T": "素材・化学",
    "4004.T": "素材・化学",
    "4005.T": "素材・化学",
    "4021.T": "素材・化学",
    "4042.T": "素材・化学",
    "4043.T": "素材・化学",
    "4061.T": "素材・化学",
    "4062.T": "電機・精密",
    "4063.T": "素材・化学",
    "4151.T": "医薬品",
    "4183.T": "素材・化学",
    "4188.T": "素材・化学",
    "4208.T": "素材・化学",
    "4307.T": "情報通信・サービスその他",
    "4324.T": "情報通信・サービスその他",
    "4385.T": "情報通信・サービスその他",
    "4452.T": "素材・化学",
    "4502.T": "医薬品",
    "4503.T": "医薬品",
    "4506.T": "医薬品",
    "4507.T": "医薬品",
    "4519.T": "医薬品",
    "4523.T": "医薬品",
    "4543.T": "電機・精密",
    "4568.T": "医薬品",
    "4578.T": "医薬品",
    "4661.T": "情報通信・サービスその他",
    "4689.T": "情報通信・サービスその他",
    "4704.T": "情報通信・サービスその他",
    "4751.T": "情報通信・サービスその他",
    "4755.T": "情報通信・サービスその他",
    "4901.T": "素材・化学",
    "4902.T": "電機・精密",
    "4911.T": "素材・化学",
    "5019.T": "エネルギー資源",
    "5020.T": "エネルギー資源",
    "5101.T": "自動車・輸送機",
    "5108.T": "自動車・輸送機",
    "5201.T": "建設・資材",
    "5214.T": "建設・資材",
    "5233.T": "建設・資材",
    "5301.T": "建設・資材",
    "5332.T": "建設・資材",
    "5333.T": "建設・資材",
    "5401.T": "鉄鋼・非鉄",
    "5406.T": "鉄鋼・非鉄",
    "5411.T": "鉄鋼・非鉄",
    "543A.T": "自動車・輸送機",
    "5631.T": "機械",
    "5706.T": "鉄鋼・非鉄",
    "5711.T": "鉄鋼・非鉄",
    "5713.T": "鉄鋼・非鉄",
    "5714.T": "鉄鋼・非鉄",
    "5801.T": "鉄鋼・非鉄",
    "5802.T": "鉄鋼・非鉄",
    "5803.T": "鉄鋼・非鉄",
    "5831.T": "銀行",
    "6098.T": "情報通信・サービスその他",
    "6103.T": "機械",
    "6113.T": "機械",
    "6146.T": "機械",
    "6178.T": "情報通信・サービスその他",
    "6273.T": "機械",
    "6301.T": "機械",
    "6302.T": "機械",
    "6305.T": "機械",
    "6326.T": "機械",
    "6361.T": "機械",
    "6367.T": "機械",
    "6471.T": "機械",
    "6472.T": "機械",
    "6473.T": "機械",
    "6479.T": "電機・精密",
    "6501.T": "電機・精密",
    "6503.T": "電機・精密",
    "6504.T": "電機・精密",
    "6506.T": "電機・精密",
    "6526.T": "電機・精密",
    "6532.T": "情報通信・サービスその他",
    "6594.T": "電機・精密",
    "6645.T": "電機・精密",
    "6701.T": "電機・精密",
    "6702.T": "電機・精密",
    "6723.T": "電機・精密",
    "6724.T": "電機・精密",
    "6752.T": "電機・精密",
    "6753.T": "電機・精密",
    "6758.T": "電機・精密",
    "6762.T": "電機・精密",
    "6770.T": "電機・精密",
    "6841.T": "電機・精密",
    "6857.T": "電機・精密",
    "6861.T": "電機・精密",
    "6890.T": "電機・精密",
    "6902.T": "自動車・輸送機",
    "6920.T": "電機・精密",
    "6954.T": "電機・精密",
    "6963.T": "電機・精密",
    "6971.T": "電機・精密",
    "6976.T": "電機・精密",
    "6981.T": "電機・精密",
    "6988.T": "素材・化学",
    "7004.T": "機械",
    "7011.T": "機械",
    "7012.T": "自動車・輸送機",
    "7013.T": "機械",
    "7186.T": "銀行",
    "7201.T": "自動車・輸送機",
    "7202.T": "自動車・輸送機",
    "7203.T": "自動車・輸送機",
    "7211.T": "自動車・輸送機",
    "7261.T": "自動車・輸送機",
    "7267.T": "自動車・輸送機",
    "7269.T": "自動車・輸送機",
    "7270.T": "自動車・輸送機",
    "7272.T": "自動車・輸送機",
    "7453.T": "小売",
    "7532.T": "小売",
    "7729.T": "電機・精密",
    "7731.T": "電機・精密",
    "7733.T": "電機・精密",
    "7735.T": "電機・精密",
    "7741.T": "電機・精密",
    "7751.T": "電機・精密",
    "7752.T": "電機・精密",
    "7832.T": "情報通信・サービスその他",
    "7911.T": "情報通信・サービスその他",
    "7912.T": "情報通信・サービスその他",
    "7951.T": "情報通信・サービスその他",
    "7974.T": "情報通信・サービスその他",
    "8001.T": "商社・卸売",
    "8002.T": "商社・卸売",
    "8015.T": "商社・卸売",
    "8031.T": "商社・卸売",
    "8035.T": "電機・精密",
    "8053.T": "商社・卸売",
    "8058.T": "商社・卸売",
    "8233.T": "小売",
    "8252.T": "小売",
    "8253.T": "金融（除く銀行）",
    "8267.T": "小売",
    "8304.T": "銀行",
    "8306.T": "銀行",
    "8308.T": "銀行",
    "8309.T": "銀行",
    "8316.T": "銀行",
    "8331.T": "銀行",
    "8354.T": "銀行",
    "8411.T": "銀行",
    "8591.T": "金融（除く銀行）",
    "8601.T": "金融（除く銀行）",
    "8604.T": "金融（除く銀行）",
    "8630.T": "金融（除く銀行）",
    "8697.T": "金融（除く銀行）",
    "8725.T": "金融（除く銀行）",
    "8750.T": "金融（除く銀行）",
    "8766.T": "金融（除く銀行）",
    "8795.T": "金融（除く銀行）",
    "8801.T": "不動産",
    "8802.T": "不動産",
    "8804.T": "不動産",
    "8830.T": "不動産",
    "9001.T": "運輸・物流",
    "9005.T": "運輸・物流",
    "9007.T": "運輸・物流",
    "9008.T": "運輸・物流",
    "9009.T": "運輸・物流",
    "9020.T": "運輸・物流",
    "9021.T": "運輸・物流",
    "9022.T": "運輸・物流",
    "9064.T": "運輸・物流",
    "9101.T": "運輸・物流",
    "9104.T": "運輸・物流",
    "9107.T": "運輸・物流",
    "9147.T": "運輸・物流",
    "9201.T": "運輸・物流",
    "9202.T": "運輸・物流",
    "9432.T": "情報通信・サービスその他",
    "9433.T": "情報通信・サービスその他",
    "9434.T": "情報通信・サービスその他",
    "9501.T": "電力・ガス",
    "9502.T": "電力・ガス",
    "9503.T": "電力・ガス",
    "9531.T": "電力・ガス",
    "9532.T": "電力・ガス",
    "9602.T": "情報通信・サービスその他",
    "9735.T": "情報通信・サービスその他",
    "9766.T": "情報通信・サービスその他",
    "9843.T": "小売",
    "9983.T": "小売",
    "9984.T": "情報通信・サービスその他",
}
```

- [ ] **Step 4: テストを実行し、パスすることを確認する**

Run: `cd app && uv run pytest tests/test_sectors.py -v`
Expected: 3件PASS

- [ ] **Step 5: コミット**

```bash
cd app
git add screening/sectors.py tests/test_sectors.py
git commit -m "feat: UNIVERSE銘柄を17業種区分に分類するSECTOR_MAPを追加"
```

---

### Task 2: 業種別リターン・リード/ラグ計算ロジックを実装する

**Files:**
- Create: `sector_analysis/__init__.py`（空ファイル、既存パッケージ規約踏襲）
- Create: `sector_analysis/correlation.py`
- Test: `tests/test_sector_correlation.py`

**Interfaces:**
- Consumes: `prices_by_ticker: dict[str, pd.Series]`（終値系列、既存の一括バックテストと同じ形）、`sector_map: dict[str, str]`（Task 1の`SECTOR_MAP`と同じ形）
- Produces:
  - `compute_sector_returns(prices_by_ticker, sector_map) -> dict[str, pd.Series]`
  - `compute_lead_lag_pairs(sector_returns, max_lag_days=20) -> list[dict]`（各要素は`{"leading_sector": str, "lagging_sector": str, "lag_days": int, "correlation": float}`、相関係数の絶対値降順にソート済み）
  - 後続タスク（`app.py`のUI、`prompt_patterns/sector_rotation.py`）はこの2関数と戻り値の形をそのまま利用する。

- [ ] **Step 1: `sector_analysis/__init__.py`を作成する**

空ファイルとして作成する（内容なし）。

- [ ] **Step 2: 失敗するテストを書く**

`tests/test_sector_correlation.py` を新規作成する:

```python
import numpy as np
import pandas as pd

from sector_analysis.correlation import compute_lead_lag_pairs, compute_sector_returns


def test_compute_sector_returns_averages_tickers_in_same_sector():
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    prices_by_ticker = {
        "A.T": pd.Series([100.0, 102.0, 104.0, 103.0, 105.0], index=dates),
        "B.T": pd.Series([200.0, 204.0, 208.0, 206.0, 210.0], index=dates),
    }
    sector_map = {"A.T": "業種X", "B.T": "業種X"}

    result = compute_sector_returns(prices_by_ticker, sector_map)

    assert list(result.keys()) == ["業種X"]
    expected = prices_by_ticker["A.T"].pct_change()
    pd.testing.assert_series_equal(result["業種X"], expected, check_names=False)


def test_compute_sector_returns_skips_missing_ticker_and_keeps_sector():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    prices_by_ticker = {"A.T": pd.Series([100.0, 101.0, 102.0], index=dates)}
    sector_map = {"A.T": "業種X", "B.T": "業種X"}

    result = compute_sector_returns(prices_by_ticker, sector_map)

    assert list(result.keys()) == ["業種X"]


def test_compute_sector_returns_excludes_sector_with_no_available_tickers():
    sector_map = {"A.T": "業種X"}

    result = compute_sector_returns({}, sector_map)

    assert result == {}


def test_compute_lead_lag_pairs_detects_known_lag():
    rng = np.random.default_rng(42)
    n = 60
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    base = pd.Series(rng.normal(size=n), index=dates)

    lag_n = 5
    # shifted[t] = base[t - lag_n] -> shiftedは base に lag_n 日遅れて追随する
    shifted = base.shift(lag_n)
    sector_returns = {"X業種": base, "Y業種": shifted}

    pairs = compute_lead_lag_pairs(sector_returns, max_lag_days=10)

    assert len(pairs) == 1
    pair = pairs[0]
    assert pair["leading_sector"] == "X業種"
    assert pair["lagging_sector"] == "Y業種"
    assert pair["lag_days"] == lag_n
    assert abs(pair["correlation"] - 1.0) < 1e-9


def test_compute_lead_lag_pairs_excludes_pairs_with_insufficient_overlap():
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    sector_returns = {
        "X業種": pd.Series([0.01, 0.02, -0.01, 0.03, 0.0], index=dates),
        "Y業種": pd.Series([0.02, 0.01, -0.02, 0.01, 0.0], index=dates),
    }

    pairs = compute_lead_lag_pairs(sector_returns, max_lag_days=20)

    assert pairs == []


def test_compute_lead_lag_pairs_sorts_by_absolute_correlation_descending():
    rng = np.random.default_rng(7)
    n = 60
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    a = pd.Series(rng.normal(size=n), index=dates)
    b = a.shift(3)  # aと強く相関
    c = pd.Series(rng.normal(size=n), index=dates)  # aと無関係

    sector_returns = {"A業種": a, "B業種": b, "C業種": c}

    pairs = compute_lead_lag_pairs(sector_returns, max_lag_days=10)

    assert len(pairs) == 3
    strongest = pairs[0]
    assert {strongest["leading_sector"], strongest["lagging_sector"]} == {"A業種", "B業種"}
    for earlier, later in zip(pairs, pairs[1:]):
        assert abs(earlier["correlation"]) >= abs(later["correlation"])
```

- [ ] **Step 3: テストを実行し、失敗することを確認する**

Run: `cd app && uv run pytest tests/test_sector_correlation.py -v`
Expected: `ModuleNotFoundError: No module named 'sector_analysis'` でFAIL

- [ ] **Step 4: `sector_analysis/correlation.py`を実装する**

```python
import pandas as pd


def compute_sector_returns(
    prices_by_ticker: dict[str, pd.Series],
    sector_map: dict[str, str],
) -> dict[str, pd.Series]:
    """業種ごとに構成銘柄の日次リターンを等ウエイト平均した系列を返す。

    prices_by_tickerに存在しない銘柄はスキップする。構成銘柄が0件になった
    業種はキーごと結果から除外する。
    """
    returns_by_sector: dict[str, list[pd.Series]] = {}
    for ticker, sector in sector_map.items():
        prices = prices_by_ticker.get(ticker)
        if prices is None or prices.empty:
            continue
        returns_by_sector.setdefault(sector, []).append(prices.pct_change())

    sector_returns: dict[str, pd.Series] = {}
    for sector, series_list in returns_by_sector.items():
        combined = pd.concat(series_list, axis=1)
        sector_returns[sector] = combined.mean(axis=1, skipna=True)
    return sector_returns


def compute_lead_lag_pairs(
    sector_returns: dict[str, pd.Series],
    max_lag_days: int = 20,
) -> list[dict]:
    """業種の全ペア（重複なし）について、時差相関が最大となるラグを求める。

    lag > 0 で corr(sector_x, sector_y.shift(lag)) が最大になる場合、
    sector_yの過去（lag日前）の値がsector_xの現在の値と相関している
    ことになるため、sector_yが先行しsector_xが追随すると解釈する。
    共通の非欠損日数がmax_lag_days未満のペアは結果から除外する。
    """
    sectors = sorted(sector_returns.keys())
    pairs: list[dict] = []

    for i in range(len(sectors)):
        for j in range(i + 1, len(sectors)):
            sector_x, sector_y = sectors[i], sectors[j]
            x, y = sector_returns[sector_x], sector_returns[sector_y]

            best_lag = None
            best_corr = None
            for lag in range(-max_lag_days, max_lag_days + 1):
                aligned = pd.concat([x, y.shift(lag)], axis=1).dropna()
                if len(aligned) < max_lag_days:
                    continue
                corr = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
                if corr is None or pd.isna(corr):
                    continue
                if best_corr is None or abs(corr) > abs(best_corr):
                    best_corr = corr
                    best_lag = lag

            if best_lag is None:
                continue

            if best_lag > 0:
                leading, lagging, lag_days = sector_y, sector_x, best_lag
            elif best_lag < 0:
                leading, lagging, lag_days = sector_x, sector_y, -best_lag
            else:
                leading, lagging, lag_days = min(sector_x, sector_y), max(sector_x, sector_y), 0

            pairs.append(
                {
                    "leading_sector": leading,
                    "lagging_sector": lagging,
                    "lag_days": lag_days,
                    "correlation": float(best_corr),
                }
            )

    pairs.sort(key=lambda pair: abs(pair["correlation"]), reverse=True)
    return pairs
```

- [ ] **Step 5: テストを実行し、パスすることを確認する**

Run: `cd app && uv run pytest tests/test_sector_correlation.py -v`
Expected: 6件PASS

- [ ] **Step 6: コミット**

```bash
cd app
git add sector_analysis/__init__.py sector_analysis/correlation.py tests/test_sector_correlation.py
git commit -m "feat: 業種別リターン算出とリード・ラグ相関計算のロジックを追加"
```

---

### Task 3: AIコメント生成プロンプトを実装する

**Files:**
- Create: `prompt_patterns/sector_rotation.py`
- Test: `tests/test_sector_rotation_prompt.py`

**Interfaces:**
- Consumes: `top_pairs: list[dict]`（Task 2の`compute_lead_lag_pairs`の戻り値と同じ形の要素を持つリスト）、`call_llm`（既存`data_api.llm_client.call_llm`と同じシグネチャ: `(prompt: str) -> str`）
- Produces:
  - `build_sector_rotation_prompt(top_pairs: list[dict]) -> str`
  - `generate_sector_rotation_comments(top_pairs: list[dict], call_llm=default_call_llm) -> dict[str, str]`（キーは`f"{leading_sector}->{lagging_sector}"`形式の文字列）。後続タスク（`app.py`）はこの関数をそのまま利用する。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_sector_rotation_prompt.py` を新規作成する:

```python
from prompt_patterns.sector_rotation import (
    build_sector_rotation_prompt,
    generate_sector_rotation_comments,
)


def test_build_sector_rotation_prompt_includes_pair_data_and_no_directive_language():
    top_pairs = [
        {
            "leading_sector": "電機・精密",
            "lagging_sector": "機械",
            "lag_days": 5,
            "correlation": 0.82,
        }
    ]

    prompt = build_sector_rotation_prompt(top_pairs)

    assert "電機・精密" in prompt
    assert "機械" in prompt
    assert "過去" in prompt
    assert "将来" in prompt
    assert "売買" in prompt


def test_generate_sector_rotation_comments_returns_empty_dict_for_empty_pairs():
    assert generate_sector_rotation_comments([]) == {}


def test_generate_sector_rotation_comments_parses_llm_json_response():
    top_pairs = [
        {
            "leading_sector": "電機・精密",
            "lagging_sector": "機械",
            "lag_days": 5,
            "correlation": 0.82,
        }
    ]
    fake_call_llm = lambda prompt: '{"電機・精密->機械": "先行して動く傾向があります。"}'

    result = generate_sector_rotation_comments(top_pairs, call_llm=fake_call_llm)

    assert result == {"電機・精密->機械": "先行して動く傾向があります。"}


def test_generate_sector_rotation_comments_falls_back_on_invalid_json():
    top_pairs = [
        {
            "leading_sector": "電機・精密",
            "lagging_sector": "機械",
            "lag_days": 5,
            "correlation": 0.82,
        }
    ]
    fake_call_llm = lambda prompt: "not json"

    result = generate_sector_rotation_comments(top_pairs, call_llm=fake_call_llm)

    assert result == {"電機・精密->機械": "コメント生成失敗"}
```

- [ ] **Step 2: テストを実行し、失敗することを確認する**

Run: `cd app && uv run pytest tests/test_sector_rotation_prompt.py -v`
Expected: `ModuleNotFoundError: No module named 'prompt_patterns.sector_rotation'` でFAIL

- [ ] **Step 3: `prompt_patterns/sector_rotation.py`を実装する**

```python
import json

from common.json_parsing import strip_code_fence
from data_api.llm_client import call_llm as default_call_llm


def build_sector_rotation_prompt(top_pairs: list[dict]) -> str:
    pairs_json = json.dumps(top_pairs, ensure_ascii=False, indent=2)
    return (
        "以下は業種（セクター）間の値動きの時差相関（リード・ラグ）を、"
        "過去の株価データから計算した結果です"
        "（Python側で計算済みのため再計算は不要です）。\n\n"
        f"【相関上位ペア（JSON）】\n{pairs_json}\n\n"
        "各ペアについて、投資家向けの解説コメントを日本語で1文ずつ作成してください。\n"
        "以下を必ず含めてください。\n"
        "1. leading_sector（先行業種）の値動きに、lagging_sector（追随業種）が"
        "lag_days営業日遅れて追随する傾向がある、という過去データ上の傾向の説明\n"
        "2. これはあくまで過去の統計的傾向であり、将来の値動きを保証するものではないこと\n\n"
        "出力は事実の説明と教育的な考察にとどめ、「買うべき」「今すぐこの業種を"
        "売買すべき」のような指示的な表現は使わないでください。\n"
        '出力形式: {"<leading_sector>-><lagging_sector>": "<コメント>"} という'
        "JSONのみを出力してください。コードブロックは不要です。"
    )


def generate_sector_rotation_comments(
    top_pairs: list[dict],
    call_llm=default_call_llm,
) -> dict[str, str]:
    if not top_pairs:
        return {}

    prompt = build_sector_rotation_prompt(top_pairs)
    raw = call_llm(prompt)
    try:
        return json.loads(strip_code_fence(raw))
    except json.JSONDecodeError:
        return {
            f"{pair['leading_sector']}->{pair['lagging_sector']}": "コメント生成失敗"
            for pair in top_pairs
        }
```

- [ ] **Step 4: テストを実行し、パスすることを確認する**

Run: `cd app && uv run pytest tests/test_sector_rotation_prompt.py -v`
Expected: 4件PASS

- [ ] **Step 5: コミット**

```bash
cd app
git add prompt_patterns/sector_rotation.py tests/test_sector_rotation_prompt.py
git commit -m "feat: セクターローテーションのAIコメント生成プロンプトを追加"
```

---

### Task 4: app.pyに「セクターローテーション」タブを追加する

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: `screening.sectors.SECTOR_MAP`（Task 1）、`sector_analysis.correlation.compute_sector_returns` / `compute_lead_lag_pairs`（Task 2）、`prompt_patterns.sector_rotation.generate_sector_rotation_comments`（Task 3）、既存の`UNIVERSE`・`map_concurrently`・`_cached_fetch_price_history`・`read_cache`/`write_cache`・`call_llm`・`DISCLAIMER_NOTICE`
- Produces: なし（UIタブの追加のみ、他タスクから参照されるインターフェースはない）

このタスクはUI配線のみのため、既存方針（`app.py`はロジックを持たせず薄い呼び出しに留め、自動テスト対象外・手動確認）に従いTDDステップは適用しない。Task 5で手動確認する。

- [ ] **Step 1: importを追加する**

`app.py`冒頭のimport群に以下を追加する（アルファベット順、既存の並びに合わせる）:

```python
from prompt_patterns.sector_rotation import generate_sector_rotation_comments
```

```python
from screening.sectors import SECTOR_MAP
```

```python
from sector_analysis.correlation import compute_lead_lag_pairs, compute_sector_returns
```

既存のモジュール名アルファベット順を維持し、以下の位置に挿入する:
- `from prompt_patterns.screening import (...)` の直後に `from prompt_patterns.sector_rotation import generate_sector_rotation_comments`
- `from screening.universe import UNIVERSE, UNIVERSE_NAMES` の直前に `from screening.sectors import SECTOR_MAP`
- `from screening.universe import ...` の直後・`from stock_detail.detail import generate_stock_detail` の直前に `from sector_analysis.correlation import compute_lead_lag_pairs, compute_sector_returns`（`sector_analysis` は `screening` の後、`stock_detail` の前）

- [ ] **Step 2: タブ定義に新タブを追加する**

現状:
```python
tab_portfolio, tab_screening, tab_backtest, tab_ranking = st.tabs(
    ["ポートフォリオ", "スクリーニング", "バックテスト", "一括バックテスト"]
)
```

変更後:
```python
tab_portfolio, tab_screening, tab_backtest, tab_ranking, tab_sector = st.tabs(
    ["ポートフォリオ", "スクリーニング", "バックテスト", "一括バックテスト", "セクターローテーション"]
)
```

- [ ] **Step 3: ファイル末尾に新タブの中身を追加する**

現状のファイル末尾（一括バックテストタブの終わり、`st.markdown(DISCLAIMER_NOTICE)`まで）の直後に、以下を追加する:

```python

with tab_sector:
    st.header("セクターローテーション")
    st.caption(
        "UNIVERSE銘柄を17業種に分類し、業種間の値動きの時差相関（リード・ラグ）を"
        "過去の株価データから計算します。あくまで過去の統計的傾向であり、"
        "将来の値動きを保証するものではありません。"
    )

    sector_period = st.selectbox(
        "取得期間", ["6mo", "1y", "2y"], index=1, key="sector_period"
    )
    sector_force_regenerate = st.checkbox(
        "キャッシュを無視して再生成する", key="sector_force_regenerate"
    )

    if st.button("分析を実行"):
        cache_key = "sector-rotation-" + hashlib.sha256(
            f"{sector_period}-{'-'.join(sorted(UNIVERSE))}".encode("utf-8")
        ).hexdigest()[:12]
        cached_payload = (
            None if sector_force_regenerate else read_cache(CACHE_DIR, cache_key)
        )
        payload = json.loads(cached_payload) if cached_payload is not None else None

        if payload is None:
            skipped_tickers = []
            prices_by_ticker = {}
            with st.spinner(f"株価データを取得中...（{len(UNIVERSE)}銘柄）"):
                price_results = map_concurrently(
                    UNIVERSE,
                    lambda ticker: _cached_fetch_price_history(ticker, sector_period),
                )
            for ticker in UNIVERSE:
                history = price_results[ticker]
                if isinstance(history, Exception) or history is None or history.empty:
                    skipped_tickers.append(ticker)
                else:
                    prices_by_ticker[ticker] = history["Close"]

            if not prices_by_ticker:
                st.error("分析可能な銘柄がありませんでした。")
                payload = None
            else:
                sector_returns = compute_sector_returns(prices_by_ticker, SECTOR_MAP)
                excluded_sectors = sorted(
                    set(SECTOR_MAP.values()) - set(sector_returns.keys())
                )
                pairs = compute_lead_lag_pairs(sector_returns, max_lag_days=20)
                comments = generate_sector_rotation_comments(pairs[:5], call_llm=call_llm)
                payload = {
                    "pairs": pairs,
                    "skipped_tickers": skipped_tickers,
                    "excluded_sectors": excluded_sectors,
                    "comments": comments,
                }
                write_cache(CACHE_DIR, cache_key, json.dumps(payload, ensure_ascii=False))

        if payload is not None:
            st.session_state["sector_payload"] = payload

    if st.session_state.get("sector_payload") is not None:
        payload = st.session_state["sector_payload"]
        pairs = payload["pairs"]

        if pairs:
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

            heatmap_df = (
                corr_matrix.reset_index()
                .melt(id_vars="index", var_name="sector_b", value_name="correlation")
                .rename(columns={"index": "sector_a"})
            )

            st.subheader("業種間相関ヒートマップ")
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
                .properties(height=500)
            )
            st.altair_chart(heatmap, width="stretch")

            st.subheader("リード・ラグ上位ペア")
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

            st.subheader("相関上位5ペアのAIコメント")
            for pair in pairs[:5]:
                key = f"{pair['leading_sector']}->{pair['lagging_sector']}"
                st.write(
                    f"**{pair['leading_sector']} → {pair['lagging_sector']}**: "
                    f"{payload['comments'].get(key, 'コメント生成失敗')}"
                )
        else:
            st.info("有効な業種ペアがありませんでした。")

        if payload["skipped_tickers"]:
            st.info(
                "データ取得・データ不足によりスキップした銘柄: "
                + ", ".join(payload["skipped_tickers"])
            )
        if payload["excluded_sectors"]:
            st.info(
                "構成銘柄が取得できず分析から除外した業種: "
                + ", ".join(payload["excluded_sectors"])
            )

        st.markdown(DISCLAIMER_NOTICE)
```

- [ ] **Step 4: 既存テストスイートを実行し、副作用がないことを確認する**

Run: `cd app && uv run pytest -v`
Expected: 全件PASS（`app.py`はテスト対象外のため件数に変化はない）

- [ ] **Step 5: コミット**

```bash
cd app
git add app.py
git commit -m "feat: セクターローテーションタブをapp.pyに追加"
```

---

### Task 5: UI動作の手動確認

**Files:** なし（コード変更なし、動作確認のみ）

**Interfaces:**
- Consumes: Task 1〜4で実装した一式
- Produces: なし（確認結果をこのタスクの完了条件とする）

- [ ] **Step 1: アプリを起動する**

Run: `cd app && uv run python -m streamlit run app.py`
Expected: エラーなく起動し、5つ目のタブ「セクターローテーション」が表示される

- [ ] **Step 2: セクターローテーションタブを実行する**

タブを開き、期間を選択して「分析を実行」をクリックする。
Expected:
- 「株価データを取得中...（228銘柄）」の表示後、エラーなく完了する
- 業種間相関ヒートマップが描画される
- リード・ラグ上位ペアの表が相関係数降順で表示される
- 相関上位5ペアのAIコメントが表示される
- 免責事項がタブ末尾に表示される

- [ ] **Step 3: キャッシュ動作を確認する**

同じ期間で再度「分析を実行」をクリックし、即座に結果が表示される（キャッシュヒット）ことを確認する。「キャッシュを無視して再生成する」をオンにして再実行し、再計算されることを確認する。

- [ ] **Step 4: 他タブに影響がないことを確認する**

ポートフォリオ・スクリーニング・バックテスト・一括バックテストの各タブを開き、これまで通り動作することを確認する（`console --errors`相当のブラウザエラー監視でも確認）。

このタスクにチェックボックスの完了以外の成果物はない。すべて期待通りであればTask 5完了とする。

---

## Global Constraintsの確認（実装完了時のチェックリスト）

- [ ] 新規の実行時依存が`pyproject.toml`に追加されていないこと
- [ ] `SECTOR_MAP`のキー集合が`UNIVERSE`と完全一致すること（`tests/test_sectors.py`でPASS）
- [ ] AIプロンプト・UI表示に売買の推奨・指示表現が含まれていないこと
- [ ] `DISCLAIMER_NOTICE`がタブ末尾に表示されること
- [ ] `common/cache.py`のキャッシュキー生成ロジック・ファイル形式に変更がないこと
