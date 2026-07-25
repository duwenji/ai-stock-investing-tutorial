# チュートリアル教材: リード・ラグ分析＋ウェーブレット発展編 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `docs/05-portfolio-management`に新規2教材（シフト相関によるリード・ラグ分析の基礎、ウェーブレットによる周期分解の発展編）を追加し、既存4ファイルへの波及修正を行って、`app/`にしか無かった分析手法をチュートリアル自体で教えられるようにする。

**Architecture:** Markdown教材のみの追加・編集。`app/`のコードは変更しない。新規2教材は既存レッスンの共通テンプレート（学習目標→概要→位置づけ→主要概念→実ソースコード→良い例/悪い例→演習課題→理解度チェック→免責事項フッター→前後ナビ）を踏襲し、スタンドアロンで完結するPythonサンプルコードを含む。

**Tech Stack:** Markdown。サンプルコードはpandas/numpy/yfinance（教材04）、追加でpywavelets（教材05、新規依存として明記）。

## Global Constraints

- 既存レッスンの見出し構成・順序（`## この教材で身につくこと` → `## 概要` → `## 位置づけ` → `## 主要概念・パラメータ解説` → `## 実ソースコード` → `## 良い例と悪い例` → `## 演習課題` → `## 理解度チェック` → `---` → 免責事項 → 前後ナビ）を厳守する。
- `app/`配下のコードは一切変更しない。本作業は`docs/`配下のMarkdownのみを対象とする。
- 新規Pythonサンプルコードは`app/`からimportせず、教材単体で完結させる（既存教材と同じ方針）。
- すべてのLLMプロンプト例は「事実の説明にとどめ、売買を促す指示的表現を避けること」「個人向け投資助言ではないこと」を明示する既存パターンを踏襲する。
- 教材05は「発展・オプション」であることを教材冒頭で明記し、スキップしても06-real-world-examplesに進める設計にする。
- 免責事項フッターの文言（`投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。`）とリンク相対パスは既存教材と完全に一致させる。

---

### Task 1: `docs/05-portfolio-management/04-lead-lag-correlation.md`（新設）

**Files:**
- Create: `ai-stock-investing-tutorial/docs/05-portfolio-management/04-lead-lag-correlation.md`

**Interfaces:**
- Consumes: なし（新規スタンドアロン教材）
- Produces: Task 3（README更新）・Task 4（03の次へリンク）・Task 2（05の前へリンク）から参照されるファイルパス `04-lead-lag-correlation.md`

- [ ] **Step 1: ファイルを作成する**

以下の内容で新規作成する。

```markdown
# 相関とリード・ラグ分析の基礎

## この教材で身につくこと

- シフト相関（時差相関）で2つの系列のどちらが先行するかをpandasで検出する方法
- 複数系列（業種など）に総当たりでリード・ラグを計算し、相関の強い順にペアを抽出する方法
- シフト相関がラグ0日（同時相関＝市場全体の地合い）に偏りやすい理由と、その限界

## 概要

02-risk-assessment.mdで学んだ相関係数（`DataFrame.corr()`）は「同じ日の値動きがどれだけ似ているか」を1つの数値で表します。しかし実際の市場では、ある銘柄・業種の値動きが別の銘柄・業種に数日〜数週間遅れて波及することがあります。本教材では、一方の系列を日数分だけずらして相関を取り直す「シフト相関」を使い、「どちらが先に動く傾向があるか（リード・ラグ）」を検出する方法を学びます。

## 位置づけ

この教材は05-portfolio-managementカテゴリの4番目の教材です。02-risk-assessment.mdの相関係数を「時間差」の視点に拡張します。03-backtest-automation.mdの直後に位置し、次の05-wavelet-cycle-analysis.md（発展編）では、本教材の手法の限界（期間全体で1つのラグ値しか出せない）を解決するより高度な手法を扱います。

## 主要概念・パラメータ解説

| 概念 | 説明 |
| --- | --- |
| シフト相関 | `series_b.shift(lag)`と`series_a`の相関係数。`lag`を`-N`〜`N`まで振り、`\|相関\|`が最大になる`lag`を採用する |
| `lag > 0` | `series_a`が`series_b`に対して`lag`日先行（`series_a`の過去の値が`series_b`の現在値と相関） |
| `lag < 0` | `series_b`が`series_a`に対して`abs(lag)`日先行 |
| `max_lag_days` | 探索するラグの最大日数。長すぎると計算コストが増え、短すぎると長い周期の関係を見逃す |

### シフト相関の限界（次教材への橋渡し）

相関の強いペアを抽出すると、多くの場合ラグ0日（同時相関）に偏ります。これは業種固有の先行・追随関係というより、市場全体の地合い（同じ日に多くの銘柄・業種が一緒に動く傾向）を反映している可能性が高いです。この限界は、期間全体を通じて「1つのラグ値」しか計算していないことに起因します。次教材（05-wavelet-cycle-analysis.md、発展編）では、周期の長さごとに分解することでこの限界に対処する手法を扱います。

## 実ソースコード（Python / プロンプト例）

### シフト相関の計算

```python
import numpy as np
import pandas as pd
import yfinance as yf


def fetch_daily_returns(tickers: list[str], period: str = "1y") -> pd.DataFrame:
    """複数銘柄の日次リターンをまとめたDataFrameを返す。"""
    prices = yf.download(tickers, period=period)["Close"]
    return prices.pct_change().dropna()


def compute_shifted_correlation(
    series_a: pd.Series, series_b: pd.Series, max_lag_days: int = 20
) -> tuple[int, float]:
    """series_aとseries_bのシフト相関から、|相関|が最大になるラグ日数と
    そのときの相関係数を返す。

    lag > 0はseries_aが先行、lag < 0はseries_bが先行することを示す。
    """
    combined = pd.concat([series_a.rename("a"), series_b.rename("b")], axis=1).dropna()
    best_lag, best_corr = 0, 0.0
    for lag in range(-max_lag_days, max_lag_days + 1):
        shifted = combined["b"].shift(lag)
        corr = combined["a"].corr(shifted)
        if pd.notna(corr) and abs(corr) > abs(best_corr):
            best_lag, best_corr = lag, corr
    return best_lag, round(best_corr, 3)


def compute_lead_lag_pairs(
    returns: dict[str, pd.Series], max_lag_days: int = 20
) -> list[dict]:
    """複数系列の全ペアについてシフト相関を計算し、|相関|の降順で返す。"""
    names = list(returns.keys())
    pairs = []
    for i, name_a in enumerate(names):
        for name_b in names[i + 1 :]:
            lag, corr = compute_shifted_correlation(
                returns[name_a], returns[name_b], max_lag_days
            )
            leading = name_a if lag >= 0 else name_b
            lagging = name_b if lag >= 0 else name_a
            pairs.append(
                {
                    "leading": leading,
                    "lagging": lagging,
                    "lag_days": abs(lag),
                    "correlation": corr,
                }
            )
    return sorted(pairs, key=lambda p: abs(p["correlation"]), reverse=True)
```

### LLMへの解説依頼

```python
def explain_lead_lag_pairs(pairs: list[dict], call_llm) -> str:
    """上位のリード・ラグペアをLLMに解説させる。"""
    top_pairs = pairs[:3]
    pairs_text = "\n".join(
        f"- {p['leading']}が{p['lagging']}に{p['lag_days']}日先行"
        f"（相関係数{p['correlation']}）"
        for p in top_pairs
    )
    prompt = f"""\
以下は複数銘柄間の値動きの時差相関（リード・ラグ）を、過去の株価データから
計算した結果です（Python側で計算済みのため再計算は不要です）。

{pairs_text}

各ペアについて、この関係が何を意味するかを投資初心者にも分かる言葉で
説明してください。ラグが0日に近いペアについては、銘柄固有の関係というより
市場全体の地合いを反映している可能性がある点にも触れてください。

出力は事実の説明と教育的な考察にとどめ、「買うべき」「今すぐ売買すべき」
のような指示的な表現は使わないでください。これは個人向けの投資助言では
ないことも明記してください。
"""
    return call_llm(prompt)
```

### 実行結果例

```text
- 6758.Tが7203.Tに2日先行（相関係数0.61）
- 7974.Tが6758.Tに0日先行（相関係数0.88）
```

```text
6758.Tと7203.Tの間には、6758.Tの値動きが7203.Tに2日遅れて
波及する傾向が見られます（相関係数0.61）。

一方、7974.Tと6758.Tはラグ0日で相関係数0.88と非常に高く、
両銘柄がほぼ同じ日に同じ方向へ動く傾向があります。これは銘柄固有の
先行・追随関係というより、市場全体の地合い（同じ日に多くの銘柄が
一緒に動く傾向）を反映している可能性があります。

これは一般的な教育目的の解説であり、個人向けの投資助言ではありません。
```

### 良い例と悪い例

```text
❌ 悪い例:
「7974.Tと6758.Tの相関が0.88と非常に強いので、7974.Tが動いたら
すぐに6758.Tを買うべきです。」
```

```text
✅ 良い例:
「ラグ0日・相関係数0.88というこの結果は、銘柄固有の先行・追随関係
というより、市場全体の地合いを反映している可能性があります。
過去の統計的傾向であり、将来の値動きを保証するものではありません。」
```

## 演習課題

1. `compute_lead_lag_pairs`を使い、3銘柄以上の日次リターンから
   リード・ラグペアの一覧を出力するスクリプトを書いてください。
2. `|correlation|`が0.5未満のペアを結果から除外するフィルタを
   `compute_lead_lag_pairs`に追加してください。
3. 実データで試したとき、上位ペアの多くがラグ0日に偏る理由を、
   本教材の「シフト相関の限界」の説明を踏まえて自分の言葉で説明してください。

## 理解度チェック

- [ ] シフト相関における`lag`の符号が何を意味するか説明できる
- [ ] リード・ラグ上位ペアがラグ0日に偏りやすい理由を説明できる
- [ ] シフト相関が「期間全体で1つのラグ値」しか出せないという限界を説明できる

---

投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。

[← 前へ: バックテスト自動化](03-backtest-automation.md) | [次へ: 周期分解によるリード・ラグ分析（発展） →](05-wavelet-cycle-analysis.md)
```

- [ ] **Step 2: Pythonコード例が構文的に妥当か確認する**

```bash
cd ai-stock-investing-tutorial/app
uv run python - <<'PYEOF'
import re, pathlib
path = pathlib.Path("../docs/05-portfolio-management/04-lead-lag-correlation.md")
text = path.read_text(encoding="utf-8")
blocks = re.findall(r"```python\n(.*?)```", text, re.DOTALL)
assert len(blocks) == 2, f"expected 2 python blocks, found {len(blocks)}"
for i, block in enumerate(blocks):
    compile(block, f"block-{i}", "exec")
print(f"{len(blocks)} python blocks compiled OK")
PYEOF
```

Expected: `2 python blocks compiled OK`

- [ ] **Step 3: リンク先ファイルの存在を確認する**

```bash
cd ai-stock-investing-tutorial/docs/05-portfolio-management
test -f 03-backtest-automation.md && echo "03 OK"
test -f 05-wavelet-cycle-analysis.md && echo "05 OK (Task 2完了後のみ成功する)"
```

Expected（Task 2完了前は`05 OK`は出ない。Task 2完了後に再実行して確認する）: `03 OK`

- [ ] **Step 4: コミット**

```bash
cd ai-stock-investing-tutorial
git add docs/05-portfolio-management/04-lead-lag-correlation.md
git commit -m "$(cat <<'EOF'
Add tutorial lesson 04: shifted-correlation lead-lag analysis

Extends the correlation concept from 02-risk-assessment into a
time-shifted version that detects which of two series leads the
other, and names its main limitation (lag-0 bias from market-wide
sentiment) that lesson 05 goes on to address.
EOF
)"
```

---

### Task 2: `docs/05-portfolio-management/05-wavelet-cycle-analysis.md`（新設）

**Files:**
- Create: `ai-stock-investing-tutorial/docs/05-portfolio-management/05-wavelet-cycle-analysis.md`

**Interfaces:**
- Consumes: Task 1で作成した `04-lead-lag-correlation.md`（前へリンク先として参照するのみ、コード上の依存はなし）
- Produces: Task 3（README更新）・Task 1（04の次へリンク）から参照されるファイルパス `05-wavelet-cycle-analysis.md`

- [ ] **Step 1: ファイルを作成する**

以下の内容で新規作成する。

```markdown
# 周期分解によるリード・ラグ分析（発展）

## この教材で身につくこと

- 04のシフト相関が「期間全体で1つのラグ値」しか出せず、短期の地合いと長期の業種固有の動きを区別できない理由
- 連続ウェーブレット変換（CWT）で、周期の長さ（短期/中期/長期）ごとにリード・ラグを分解する考え方
- コヒーレンス（関係の確からしさ）が低い区間を参考程度として扱うことの重要性

## 概要

04で学んだシフト相関は、期間全体を通じて「最も強い1つのラグ」しか教えてくれません。しかし実際の値動きには、数日〜2週間程度の短い周期の動き（市場全体の地合いに近い）と、1〜6か月程度の長い周期の動き（業種固有のサイクルに近い）が混ざっています。

本教材（発展編）では、連続ウェーブレット変換（CWT）を使い、値動きを「周期の長さ」ごとに分解したうえで、周期ごとに「どちらが先行しているか」「その関係はどれくらい確からしいか（コヒーレンス）」を計算する考え方を学びます。数式の詳細には立ち入らず、直感的な理解と最小限の実行可能なサンプルコードを目的とします。

> 本教材は**発展・オプション**です。スキップしても06-real-world-examplesに進めます。

## 位置づけ

この教材は05-portfolio-managementカテゴリの5番目（最後）の教材です。04-lead-lag-correlation.mdの限界（期間全体で1つのラグ値）を解決する発展的な手法として位置づけます。

次の06-real-world-examplesでは、ここまでの内容を統合した実践的なツール構築演習に取り組みます。

## 主要概念・パラメータ解説

| 概念 | 説明 |
| --- | --- |
| 連続ウェーブレット変換（CWT） | 時系列を「時間×周期の長さ」の2次元に分解する変換。周期ごとに値動きの強さと位相（タイミングのズレ）を計算できる |
| コヒーレンス（`coherence`） | 2系列の関係の確からしさを`0`〜`1`で表す指標。低いほど「その周期・その時点での関係は参考程度」であることを示す |
| 周期帯（`PERIOD_BANDS`） | 短期（4〜10営業日）・中期（10〜40営業日）・長期（40〜120営業日）の3区分。単位は営業日 |
| ラグの符号 | 04と同じ規約: 正なら系列Aが先行、負なら系列Bが先行 |

## 実ソースコード（最小限のサンプル）

新規依存として`pywavelets`が必要です（`uv add pywavelets`、インポート名は`pywt`）。

```python
import numpy as np
import pandas as pd
import pywt

WAVELET = "cmor1.5-1.0"  # 複素モルレーウェーブレット


def compute_wavelet_lag_snapshot(
    series_a: pd.Series, series_b: pd.Series, period_days: float
) -> dict:
    """指定した周期（営業日）における、直近時点のラグとコヒーレンスを
    最小限の実装で計算する（時間軸方向の平滑化は省略した簡易版）。
    """
    combined = pd.concat([series_a.rename("a"), series_b.rename("b")], axis=1).dropna()
    center_freq = pywt.central_frequency(WAVELET)
    scale = center_freq * period_days

    coeffs_a, _ = pywt.cwt(combined["a"].to_numpy(), [scale], WAVELET, sampling_period=1.0)
    coeffs_b, _ = pywt.cwt(combined["b"].to_numpy(), [scale], WAVELET, sampling_period=1.0)
    wa, wb = coeffs_a[0], coeffs_b[0]

    cross = wa * np.conj(wb)
    coherence = float(np.abs(cross[-1]) ** 2 / (np.abs(wa[-1]) ** 2 * np.abs(wb[-1]) ** 2))
    lag_days = float(np.angle(cross[-1]) / (2 * np.pi) * period_days)

    return {"lag_days": round(lag_days, 1), "coherence": round(min(coherence, 1.0), 2)}
```

> このサンプルは概念理解のための最小実装であり、時間軸方向の平滑化・複数周期の一括計算・複数業種対応は行っていません（平滑化を省略しているため、コヒーレンスは常に1に近い値になる点に注意してください。実運用では平滑化が必須です）。完全な実装（平滑化・複数周期帯・Streamlit UIでの可視化・直近シグナル要約・AI解説コメント）は[`app/sector_analysis/wavelet.py`](../../../app/sector_analysis/wavelet.py)と[`app/prompt_patterns/wavelet_explanation.py`](../../../app/prompt_patterns/wavelet_explanation.py)を参照してください。

### LLMへの解説依頼

```python
def explain_wavelet_snapshot(
    sector_a: str, sector_b: str, band_label: str, snapshot: dict, call_llm
) -> str:
    """ウェーブレット分析のスナップショットをLLMに解説させる。"""
    lag = snapshot["lag_days"]
    leading = sector_a if lag >= 0 else sector_b
    lagging = sector_b if lag >= 0 else sector_a
    prompt = f"""\
以下は「{sector_a}」と「{sector_b}」について、周期帯「{band_label}」における
ウェーブレット分析の直近時点の計算結果です（Python側で計算済みです）。

- 支配的ラグ: 約{abs(lag):.1f}営業日（{leading}が{lagging}に先行）
- コヒーレンス（関係の確からしさ、0〜1）: {snapshot['coherence']:.2f}

この結果が何を意味するかを、コヒーレンスの水準（高い/低い）にも触れながら
投資初心者向けに説明してください。過去の統計的傾向であり将来を保証しない
ことを明記し、指示的な売買表現は使わないでください。
"""
    return call_llm(prompt)
```

### 実行結果例

```text
支配的ラグ: 約3.2営業日（電機・精密が機械に先行）
コヒーレンス: 0.62
```

```text
中期の周期帯（10〜40営業日）では、電機・精密の値動きが機械に約3.2営業日
先行する傾向が見られます。コヒーレンス0.62は中程度の確からしさを示して
おり、この関係は一定の裏付けがあるものの絶対的なものではありません。

これは過去の統計的傾向の説明であり、将来の値動きを保証するものでは
ありません。
```

### 良い例と悪い例

```text
❌ 悪い例:
「支配的ラグが3.2日なので、電機・精密が動いたら3営業日後に機械を
買えば確実に利益が出ます。」
```

```text
✅ 良い例:
「コヒーレンス0.62は中程度の確からしさであり、この関係は絶対的な
ものではありません。過去の統計的傾向であり、将来を保証しません。」
```

## 演習課題

1. `compute_wavelet_lag_snapshot`の`period_days`引数を変えて、
   短期（例: 8営業日）と長期（例: 60営業日）でラグ・コヒーレンスが
   どう変わるか比較してください。
2. 04で計算したシフト相関の結果と、本教材のウェーブレット分析の結果を
   同じ2銘柄で比較し、両者が一致する場合・しない場合それぞれについて
   考えられる理由を説明してください。
3. `app/sector_analysis/wavelet.py`の`summarize_band_snapshot`関数を読み、
   本教材のサンプルコードと何が違うか（特に平滑化の有無）を説明してください。

## 理解度チェック

- [ ] シフト相関とウェーブレット分析の違い（1つのラグ値 vs 周期ごとの分解）を説明できる
- [ ] コヒーレンスが低い区間を「参考程度」として扱うべき理由を説明できる
- [ ] 本教材のサンプルコードと`app/`の完全な実装との違いを説明できる

## さらに学ぶには

`app/`には、本教材で学んだ考え方をもとにした完成版のStreamlitアプリがあります。

- 複数業種を選択できるUI、周期帯（短期/中期/長期）ごとの支配的ラグの時系列グラフ
- 直近シグナルの要約パネル（`summarize_band_snapshot`、機械的な数値表示）
- ボタン起動・日次キャッシュ付きのAI解説コメント（`generate_wavelet_explanation`）

これらは、01-portfolio-management以降で一貫して使ってきた「Pythonが事実を計算し、LLMがそれを解釈する」という設計パターンを、より高度な分析（周期分解）にそのまま適用した例です。詳細は[`app/README.md`](../../../app/README.md)と[`docs/superpowers/specs/`](../../../app/docs/superpowers/specs/)配下の設計書を参照してください。

---

投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。

[← 前へ: 相関とリード・ラグ分析の基礎](04-lead-lag-correlation.md) | [次へ: 06-real-world-examples →](../06-real-world-examples/00-README.md)
```

- [ ] **Step 2: Pythonコード例が構文的に妥当か確認する**

```bash
cd ai-stock-investing-tutorial/app
uv run python - <<'PYEOF'
import re, pathlib
path = pathlib.Path("../docs/05-portfolio-management/05-wavelet-cycle-analysis.md")
text = path.read_text(encoding="utf-8")
blocks = re.findall(r"```python\n(.*?)```", text, re.DOTALL)
assert len(blocks) == 2, f"expected 2 python blocks, found {len(blocks)}"
for i, block in enumerate(blocks):
    compile(block, f"block-{i}", "exec")
print(f"{len(blocks)} python blocks compiled OK")
PYEOF
```

Expected: `2 python blocks compiled OK`（`pywavelets`が未インストールでも`compile()`は構文チェックのみのため成功する）

- [ ] **Step 3: リンク先ファイルの存在を確認する**

```bash
cd ai-stock-investing-tutorial
test -f docs/05-portfolio-management/04-lead-lag-correlation.md && echo "04 OK"
test -f docs/06-real-world-examples/00-README.md && echo "06-README OK"
test -f app/sector_analysis/wavelet.py && echo "wavelet.py OK"
test -f app/prompt_patterns/wavelet_explanation.py && echo "wavelet_explanation.py OK"
```

Expected: 4行すべて `OK` で出力される

- [ ] **Step 4: コミット**

```bash
cd ai-stock-investing-tutorial
git add docs/05-portfolio-management/05-wavelet-cycle-analysis.md
git commit -m "$(cat <<'EOF'
Add tutorial lesson 05: wavelet cycle decomposition (advanced)

Introduces continuous wavelet transform coherence/lag as the fix for
lesson 04's single-lag-per-period limitation, with a minimal runnable
example and a pointer to the full app/sector_analysis/wavelet.py
implementation for readers who want the production version.
EOF
)"
```

---

### Task 3: `docs/05-portfolio-management/00-README.md` の更新

**Files:**
- Modify: `ai-stock-investing-tutorial/docs/05-portfolio-management/00-README.md`

**Interfaces:**
- Consumes: Task 1・Task 2で作成したファイル名（`04-lead-lag-correlation.md`, `05-wavelet-cycle-analysis.md`）
- Produces: なし

- [ ] **Step 1: 学習目標に2行追加する**

`## 学習目標`の箇条書きの末尾（既存3行の後）に以下を追加する。

```markdown
- 複数銘柄・業種間の値動きの時間差（リード・ラグ）をシフト相関で検出する
- （発展）周期分解（ウェーブレット）により、周期の長さごとのリード・ラグとその確からしさを分析する
```

- [ ] **Step 2: 教材一覧の表に2行追加する**

既存の表の最終行（03の行）の直後に以下の2行を追加する。

```markdown
| 04 | [相関とリード・ラグ分析の基礎](04-lead-lag-correlation.md) | シフト相関による2系列の先行・追随関係の検出 |
| 05 | [周期分解によるリード・ラグ分析（発展）](05-wavelet-cycle-analysis.md) | ウェーブレット変換による周期ごとのリード・ラグ分析（オプション） |
```

- [ ] **Step 3: 「学習の進め方」の推奨順序を更新する**

`01 → 03 の順に進めることを推奨します。`を以下に置き換える。

```markdown
01 → 05 の順に進めることを推奨します（05は発展・オプションのため、時間が限られる場合は04までで次のカテゴリに進んでも構いません）。
```

- [ ] **Step 4: 「共通パターン」の教材数を修正する**

`このカテゴリの3教材はすべて、次の順序で処理を行う共通パターンに従います。`を以下に置き換える。

```markdown
このカテゴリの5教材はすべて、次の順序で処理を行う共通パターンに従います。
```

- [ ] **Step 5: 変更後のファイル全体を確認する**

Run: `cat ai-stock-investing-tutorial/docs/05-portfolio-management/00-README.md`（PowerShellの場合は`Get-Content`）
Expected: 表に04・05の行があり、学習目標に2行追加され、「01 → 05」「5教材」の記述になっていることを目視確認する。

- [ ] **Step 6: コミット**

```bash
cd ai-stock-investing-tutorial
git add docs/05-portfolio-management/00-README.md
git commit -m "$(cat <<'EOF'
Add lessons 04-05 to the 05-portfolio-management category index

Lists the new lead-lag correlation and wavelet cycle-decomposition
lessons in the category README and updates the recommended reading
order and lesson count.
EOF
)"
```

---

### Task 4: `docs/05-portfolio-management/03-backtest-automation.md` の更新

**Files:**
- Modify: `ai-stock-investing-tutorial/docs/05-portfolio-management/03-backtest-automation.md`

**Interfaces:**
- Consumes: Task 1で作成した `04-lead-lag-correlation.md`
- Produces: なし

- [ ] **Step 1: 「位置づけ」セクションを更新する**

以下の既存テキストを:

```markdown
## 位置づけ

この教材は05-portfolio-managementカテゴリの最後の教材です。
01・02で学んだ「構成比の要約」「リスク指標の解説」に続き、
本教材では「戦略の過去成績の解説」を扱います。

次の06-real-world-examplesでは、ここまでの内容を統合した
実践的なツール構築演習に取り組みます。
```

以下に置き換える。

```markdown
## 位置づけ

この教材は05-portfolio-managementカテゴリの3番目の教材です。
01・02で学んだ「構成比の要約」「リスク指標の解説」に続き、
本教材では「戦略の過去成績の解説」を扱います。

次の04-lead-lag-correlation.mdでは、02で学んだ相関係数を
時間差の視点に拡張します。
```

- [ ] **Step 2: 末尾ナビゲーションを更新する**

以下の既存行を:

```markdown
[← 前へ: リスク評価・分散](02-risk-assessment.md) | [次へ: 06-real-world-examples →](../06-real-world-examples/00-README.md)
```

以下に置き換える。

```markdown
[← 前へ: リスク評価・分散](02-risk-assessment.md) | [次へ: 相関とリード・ラグ分析の基礎 →](04-lead-lag-correlation.md)
```

- [ ] **Step 3: リンク先ファイルの存在を確認する**

```bash
test -f ai-stock-investing-tutorial/docs/05-portfolio-management/04-lead-lag-correlation.md && echo "OK"
```

Expected: `OK`

- [ ] **Step 4: コミット**

```bash
cd ai-stock-investing-tutorial
git add docs/05-portfolio-management/03-backtest-automation.md
git commit -m "$(cat <<'EOF'
Point 03-backtest-automation onward to the new lead-lag lesson

03 is no longer the last lesson in the category now that 04-05 exist,
so its position note and footer nav link move from 06-real-world-examples
to 04-lead-lag-correlation.md.
EOF
)"
```

---

### Task 5: `docs/00-COVER.md` の更新

**Files:**
- Modify: `ai-stock-investing-tutorial/docs/00-COVER.md`

**Interfaces:**
- Consumes: なし
- Produces: なし

- [ ] **Step 1: STEP 5のブロックを更新する**

以下の既存テキストを:

```markdown
STEP 5 ──→ Portfolio Management（3教材）
             AIポートフォリオ分析・リスク評価・バックテスト自動化
```

以下に置き換える。

```markdown
STEP 5 ──→ Portfolio Management（5教材）
             AIポートフォリオ分析・リスク評価・バックテスト自動化・
             リード/ラグ分析・周期分解（ウェーブレット、発展）
```

- [ ] **Step 2: 変更を確認する**

Run: `cat ai-stock-investing-tutorial/docs/00-COVER.md`（PowerShellの場合は`Get-Content`）
Expected: STEP 5が「5教材」と表示され、リード/ラグ分析・周期分解が説明文に含まれる。

- [ ] **Step 3: コミット**

```bash
cd ai-stock-investing-tutorial
git add docs/00-COVER.md
git commit -m "$(cat <<'EOF'
Update STEP 5 lesson count in the tutorial cover page

Reflects the two new 05-portfolio-management lessons (lead-lag
correlation, wavelet cycle decomposition) added to the curriculum.
EOF
)"
```

---

### Task 6: `docs/06-real-world-examples/00-README.md` の更新

**Files:**
- Modify: `ai-stock-investing-tutorial/docs/06-real-world-examples/00-README.md`

**Interfaces:**
- Consumes: Task 1・Task 2で作成したレッスン（`05-portfolio-management/04-lead-lag-correlation.md`, `05-wavelet-cycle-analysis.md`）へのカテゴリ参照
- Produces: なし

- [ ] **Step 1: 「さらに発展させた実装例」の段落を更新する**

以下の既存テキストを:

```markdown
本カテゴリ、特に03「統合ポートフォリオアドバイザーエージェント」の考え方をさらに発展させ、
複数戦略（移動平均クロスオーバー／RSI逆張り／MACDクロスオーバー／ボリンジャーバンド逆張り）
のバックテスト、ユニバース一括ランキング、セクターローテーション分析、
銘柄詳細（ローソク足＋移動平均線チャート）などを追加した完成版のStreamlitアプリが
[`app/`](../../app/README.md) にあります。本カテゴリを一通り終えたあとの参考実装として
ご覧ください（教材のコード例とは別に発展させた実装のため、必ずしも一致しません）。
```

以下に置き換える。

```markdown
本カテゴリ、特に03「統合ポートフォリオアドバイザーエージェント」の考え方をさらに発展させ、
複数戦略（移動平均クロスオーバー／RSI逆張り／MACDクロスオーバー／ボリンジャーバンド逆張り）
のバックテスト、ユニバース一括ランキング、銘柄詳細（ローソク足＋移動平均線チャート）などを
追加した完成版のStreamlitアプリが[`app/`](../../app/README.md)にあります。
本カテゴリを一通り終えたあとの参考実装としてご覧ください（教材のコード例とは別に発展させた
実装のため、必ずしも一致しません）。

セクター間のリード・ラグ分析・周期分解（ウェーブレット分析）の基礎は
[05-portfolio-management](../05-portfolio-management/00-README.md)の04・05で学べます。
app/の完成版UIでは、これらの考え方を17業種・複数の周期帯に対応させ、直近シグナルの
要約パネルやAI解説コメント（キャッシュ付き）まで拡張しています。
```

- [ ] **Step 2: 変更を確認する**

Run: `cat ai-stock-investing-tutorial/docs/06-real-world-examples/00-README.md`（PowerShellの場合は`Get-Content`）
Expected: 「セクターローテーション分析」という単独の記述が消え、代わりに05-04/05への参照を含む新しい段落が末尾に追加されている。

- [ ] **Step 3: コミット**

```bash
cd ai-stock-investing-tutorial
git add docs/06-real-world-examples/00-README.md
git commit -m "$(cat <<'EOF'
Point sector-rotation mention to the new 05-04/05 tutorial lessons

The "further extended app/" note previously treated sector rotation
as app/-only content; now that its underlying technique is taught in
05-portfolio-management/04-05, the README credits those lessons and
describes app/ as the fuller production UI built on the same ideas.
EOF
)"
```

---

### Task 7: 全体整合性の最終確認

**Files:**
- なし（確認のみ、変更は加えない）

**Interfaces:**
- Consumes: Task 1〜6のすべての変更結果
- Produces: なし

- [ ] **Step 1: 教材一覧の教材数とファイル数が一致することを確認する**

```bash
ls ai-stock-investing-tutorial/docs/05-portfolio-management/*.md | grep -v 00-README | wc -l
```

Expected: `5`（01〜05の5ファイル）

- [ ] **Step 2: 03→04→05→06の前後ナビゲーションが循環していることを確認する**

```bash
cd ai-stock-investing-tutorial/docs/05-portfolio-management
grep -o '\[次へ:[^]]*\](.*)$' 03-backtest-automation.md
grep -o '\[次へ:[^]]*\](.*)$' 04-lead-lag-correlation.md
grep -o '\[次へ:[^]]*\](.*)$' 05-wavelet-cycle-analysis.md
```

Expected: それぞれ`04-lead-lag-correlation.md`、`05-wavelet-cycle-analysis.md`、`../06-real-world-examples/00-README.md`を指している。

- [ ] **Step 3: 00-COVER.mdとREADME.mdの教材数表記が一致することを確認する**

```bash
grep "Portfolio Management" ai-stock-investing-tutorial/docs/00-COVER.md
grep "01 → 05" ai-stock-investing-tutorial/docs/05-portfolio-management/00-README.md
```

Expected: 両方とも「5教材」「01 → 05」の記述で一致している。

- [ ] **Step 4: 完了報告**

すべてのStepがPASSしたら、Task 1〜6のコミットが揃っていることを`git log --oneline -8`で確認し、作業完了として報告する。追加のコミットは不要（Task 7は確認のみ）。

---

## Self-Review Notes

- **Spec coverage:** 教材04（データ層に相当する概念・実ソースコード・良い例悪い例・演習・理解度チェック）→ Task 1。教材05（発展編、同構成＋「さらに学ぶには」）→ Task 2。既存4ファイルへの波及修正（00-README/03/00-COVER/06-README）→ Task 3〜6。整合性確認 → Task 7。設計書の「エラーハンドリング・留意点」「テスト方針」もTask 1・2のStep 2（構文チェック）とTask 7（リンク・教材数整合性）でカバー。
- **プレースホルダー確認:** 各Stepに実際のMarkdown/コード内容を記載済み。「後で追記」等の曖昧な指示なし。
- **型・シグネチャの一貫性:** 教材04の`compute_lead_lag_pairs`が返す辞書のキー（`leading`/`lagging`/`lag_days`/`correlation`）は教材04内のLLMプロンプト生成コードと一致。教材05の`compute_wavelet_lag_snapshot`が返す辞書のキー（`lag_days`/`coherence`）も教材05内のLLMプロンプト生成コードと一致。ファイル名参照（`04-lead-lag-correlation.md`, `05-wavelet-cycle-analysis.md`）はTask 1・2・3・4・6ですべて一致。
