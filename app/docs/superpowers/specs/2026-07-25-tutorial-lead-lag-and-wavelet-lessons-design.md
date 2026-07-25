# チュートリアル教材: リード・ラグ分析＋ウェーブレット発展編 設計書

## 概要・目的

[セクターローテーション ウェーブレット分析](2026-07-21-sector-rotation-wavelet-design.md)と[ウェーブレット分析 直近シグナル要約＋AI解説コメント](2026-07-25-wavelet-analysis-summary-and-ai-comment-design.md)により、`app/`には業種間の時差相関・周期分解（連続ウェーブレット変換によるリード・ラグ検出）という高度な分析手法が実装済みである。

一方、`docs/`（教材本体）はこの分析手法そのものを教えておらず、[06-real-world-examples/00-README.md](../../../../docs/06-real-world-examples/00-README.md)が「本カテゴリを一通り終えたあとの参考実装」として`app/`を指し示すのみで、セクターローテーション・ウェーブレット分析は教材読者にとって「見るだけで仕組みが分からないブラックボックス」になっている。

本機能は、この分析手法（周期分解・リード/ラグ検出）そのものを教材化する。`05-portfolio-management`に新規2教材を追加し、既存の02（リスク評価・相関）で学んだ`.corr()`を「どちらが先に動くか」という時間差の視点に拡張したうえで、より高度な周期分解（ウェーブレット）による発展的分析へとつなげる。

`app/`のコードそのものは変更しない。本機能は`docs/`配下のMarkdown教材の追加・修正のみを対象とする。

## スコープ

- v1で実装する:
  - `docs/05-portfolio-management/04-lead-lag-correlation.md`（新設）: シフト相関によるリード・ラグ検出の基礎
  - `docs/05-portfolio-management/05-wavelet-cycle-analysis.md`（新設）: ウェーブレット（CWT）による周期分解の発展編
  - `docs/05-portfolio-management/00-README.md`の更新（教材一覧・学習目標）
  - `docs/05-portfolio-management/03-backtest-automation.md`の更新（「カテゴリ最後の教材」記述の削除、末尾ナビの修正）
  - `docs/00-COVER.md`の更新（STEP 5の教材数・概要説明）
  - `docs/06-real-world-examples/00-README.md`の更新（「さらに発展させた実装例」の説明を、基礎が05-04/05で学べることを踏まえて調整）
- v1で実装しない（将来課題）:
  - `app/`側のコード変更（本機能は`docs/`のみ対象）
  - モンテカルロ法による統計的有意性検定など、[2026-07-21-sector-rotation-wavelet-design.md](2026-07-21-sector-rotation-wavelet-design.md)のv1スコープ外事項の教材化
  - 演習課題の模範解答集（既存教材も演習に模範解答を用意していないため、本機能でも踏襲しない）

## 既存教材の構成・慣例（前提整理）

`05-portfolio-management`配下の既存3教材（`01-portfolio-analysis-with-ai.md` / `02-risk-assessment.md` / `03-backtest-automation.md`）は、以下の共通テンプレートに従う。新規2教材もこれを踏襲する。

1. `# タイトル`
2. `## この教材で身につくこと`（箇条書き3点程度）
3. `## 概要`（何を学ぶか、なぜ必要かの短い説明）
4. `## 位置づけ`（前後の教材との関係、カテゴリ内の順序）
5. `## 主要概念・パラメータ解説`（表形式での用語・数式の整理）
6. `## 実ソースコード`（Python計算コード → LLM解説プロンプトの順。スタンドアロンで完結し、`app/`の本番コードをそのまま貼らず教材向けに簡略化する）
7. `## 良い例と悪い例`（❌/✅の対比）
8. `## 演習課題`（2〜3問）
9. `## 理解度チェック`（チェックボックス3点程度）
10. 免責事項フッター＋前後ナビゲーションリンク

既存コードは「Pythonが数値を計算し、LLMはその数値を解釈・要約する」という原則（[05-portfolio-management/00-README.md](../../../../docs/05-portfolio-management/00-README.md)に明記）を一貫して守っており、LLMプロンプトは常に「事実の説明にとどめ、売買を促す指示的表現を避けること」を明示する。新規2教材もこの原則・文言パターンをそのまま踏襲する。

## 教材04 — `05-portfolio-management/04-lead-lag-correlation.md`（新設）

### この教材で身につくこと

- シフト相関（時差相関）で2つの系列のどちらが先行するかをpandasで検出する方法
- 複数系列（業種など）に総当たりでリード・ラグを計算し、相関の強い順にペアを抽出する方法
- シフト相関がラグ0日（同時相関＝市場全体の地合い）に偏りやすい理由と、その限界

### 概要

02-risk-assessment.mdで学んだ相関係数（`DataFrame.corr()`）は「同じ日の値動きがどれだけ似ているか」を1つの数値で表す。しかし実際の市場では、ある銘柄・業種の値動きが別の銘柄・業種に数日〜数週間遅れて波及することがある。本教材では、一方の系列を日数分だけずらして相関を取り直す「シフト相関」を使い、「どちらが先に動く傾向があるか（リード・ラグ）」を検出する方法を学ぶ。

### 位置づけ

この教材は05-portfolio-managementカテゴリの4番目の教材である。02-risk-assessment.mdの相関係数を「時間差」の視点に拡張する。03-backtest-automation.mdの直後に位置し、次の05-wavelet-cycle-analysis.md（発展編）では、本教材の手法の限界（期間全体で1つのラグ値しか出せない）を解決するより高度な手法を扱う。

### 主要概念・パラメータ解説

| 概念 | 説明 |
| --- | --- |
| シフト相関 | `series_b.shift(lag)`と`series_a`の相関係数。`lag`を`-N`〜`N`まで振り、`|相関|`が最大になる`lag`を採用する |
| `lag > 0` | `series_a`が`series_b`に対して`lag`日先行（`series_a`の過去の値が`series_b`の現在値と相関） |
| `lag < 0` | `series_b`が`series_a`に対して`abs(lag)`日先行 |
| `max_lag_days` | 探索するラグの最大日数。長すぎると計算コストが増え、短すぎると長い周期の関係を見逃す |

### シフト相関の限界（次教材への橋渡し）

相関の強いペアを抽出すると、多くの場合ラグ0日（同時相関）に偏る。これは業種固有の先行・追随関係というより、市場全体の地合い（同じ日に多くの銘柄・業種が一緒に動く傾向）を反映している可能性が高い。この限界は、期間全体を通じて「1つのラグ値」しか計算していないことに起因する。次教材（05-wavelet-cycle-analysis.md、発展編）では、周期の長さごとに分解することでこの限界に対処する手法を扱う。

### 実ソースコード

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

### 演習課題

1. `compute_lead_lag_pairs`を使い、3銘柄以上の日次リターンから
   リード・ラグペアの一覧を出力するスクリプトを書いてください。
2. `|correlation|`が0.5未満のペアを結果から除外するフィルタを
   `compute_lead_lag_pairs`に追加してください。
3. 実データで試したとき、上位ペアの多くがラグ0日に偏る理由を、
   本教材の「シフト相関の限界」の説明を踏まえて自分の言葉で説明してください。

### 理解度チェック

- [ ] シフト相関における`lag`の符号が何を意味するか説明できる
- [ ] リード・ラグ上位ペアがラグ0日に偏りやすい理由を説明できる
- [ ] シフト相関が「期間全体で1つのラグ値」しか出せないという限界を説明できる

---

投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。

[← 前へ: バックテスト自動化](03-backtest-automation.md) | [次へ: 周期分解によるリード・ラグ分析（発展） →](05-wavelet-cycle-analysis.md)

（以上が`04-lead-lag-correlation.md`の内容。）

## 教材05 — `05-portfolio-management/05-wavelet-cycle-analysis.md`（新設）

### この教材で身につくこと

- 04のシフト相関が「期間全体で1つのラグ値」しか出せず、短期の地合いと長期の業種固有の動きを区別できない理由
- 連続ウェーブレット変換（CWT）で、周期の長さ（短期/中期/長期）ごとにリード・ラグを分解する考え方
- コヒーレンス（関係の確からしさ）が低い区間を参考程度として扱うことの重要性

### 概要

04で学んだシフト相関は、期間全体を通じて「最も強い1つのラグ」しか教えてくれない。しかし実際の値動きには、数日〜2週間程度の短い周期の動き（市場全体の地合いに近い）と、1〜6か月程度の長い周期の動き（業種固有のサイクルに近い）が混ざっている。

本教材（発展編）では、連続ウェーブレット変換（CWT）を使い、値動きを「周期の長さ」ごとに分解したうえで、周期ごとに「どちらが先行しているか」「その関係はどれくらい確からしいか（コヒーレンス）」を計算する考え方を学ぶ。数式の詳細には立ち入らず、直感的な理解と最小限の実行可能なサンプルコードを目的とする。

> 本教材は**発展・オプション**である。スキップしても06-real-world-examplesに進める。

### 位置づけ

この教材は05-portfolio-managementカテゴリの5番目（最後）の教材である。04-lead-lag-correlation.mdの限界（期間全体で1つのラグ値）を解決する発展的な手法として位置づける。

次の06-real-world-examplesでは、ここまでの内容を統合した実践的なツール構築演習に取り組む。

### 主要概念・パラメータ解説

| 概念 | 説明 |
| --- | --- |
| 連続ウェーブレット変換（CWT） | 時系列を「時間×周期の長さ」の2次元に分解する変換。周期ごとに値動きの強さと位相（タイミングのズレ）を計算できる |
| コヒーレンス（`coherence`） | 2系列の関係の確からしさを`0`〜`1`で表す指標。低いほど「その周期・その時点での関係は参考程度」であることを示す |
| 周期帯（`PERIOD_BANDS`） | 短期（4〜10営業日）・中期（10〜40営業日）・長期（40〜120営業日）の3区分。単位は営業日 |
| ラグの符号 | 04と同じ規約: 正なら系列Aが先行、負なら系列Bが先行 |

### 実ソースコード（最小限のサンプル）

新規依存として`pywavelets`が必要（`uv add pywavelets`、インポート名は`pywt`）。

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

> このサンプルは概念理解のための最小実装であり、時間軸方向の平滑化・複数周期の一括計算・複数業種対応は行っていない（平滑化を省略しているため、コヒーレンスは常に1に近い値になる点に注意。実運用では平滑化が必須）。完全な実装（平滑化・複数周期帯・Streamlit UIでの可視化・直近シグナル要約・AI解説コメント）は[`app/sector_analysis/wavelet.py`](../../../app/sector_analysis/wavelet.py)と[`app/prompt_patterns/wavelet_explanation.py`](../../../app/prompt_patterns/wavelet_explanation.py)を参照してほしい。

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

### 演習課題

1. `compute_wavelet_lag_snapshot`の`period_days`引数を変えて、
   短期（例: 8営業日）と長期（例: 60営業日）でラグ・コヒーレンスが
   どう変わるか比較してください。
2. 04で計算したシフト相関の結果と、本教材のウェーブレット分析の結果を
   同じ2銘柄で比較し、両者が一致する場合・しない場合それぞれについて
   考えられる理由を説明してください。
3. `app/sector_analysis/wavelet.py`の`summarize_band_snapshot`関数を読み、
   本教材のサンプルコードと何が違うか（特に平滑化の有無）を説明してください。

### 理解度チェック

- [ ] シフト相関とウェーブレット分析の違い（1つのラグ値 vs 周期ごとの分解）を説明できる
- [ ] コヒーレンスが低い区間を「参考程度」として扱うべき理由を説明できる
- [ ] 本教材のサンプルコードと`app/`の完全な実装との違いを説明できる

### さらに学ぶには

`app/`には、本教材で学んだ考え方をもとにした完成版のStreamlitアプリがある。

- 複数業種を選択できるUI、周期帯（短期/中期/長期）ごとの支配的ラグの時系列グラフ
- 直近シグナルの要約パネル（`summarize_band_snapshot`、機械的な数値表示）
- ボタン起動・日次キャッシュ付きのAI解説コメント（`generate_wavelet_explanation`）

これらは、01-portfolio-management以降で一貫して使ってきた「Pythonが事実を計算し、LLMがそれを解釈する」という設計パターンを、より高度な分析（周期分解）にそのまま適用した例である。詳細は[`app/README.md`](../../../app/README.md)と[`docs/superpowers/specs/`](../../../app/docs/superpowers/specs/)配下の設計書を参照してほしい。

---

投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。

[← 前へ: 相関とリード・ラグ分析の基礎](04-lead-lag-correlation.md) | [次へ: 06-real-world-examples →](../06-real-world-examples/00-README.md)

## 既存ファイルへの波及修正

### `docs/05-portfolio-management/00-README.md`

- 教材一覧の表に04・05を追加する
- 「学習の進め方」の「01 → 03の順に進めることを推奨します」を「01 → 05の順に進めることを推奨します（05は発展・オプション）」に変更する
- 「学習目標」に以下を追加する:
  - 複数銘柄・業種間の値動きの時間差（リード・ラグ）をシフト相関で検出する
  - （発展）周期分解（ウェーブレット）により、周期の長さごとのリード・ラグとその確からしさを分析する

### `docs/05-portfolio-management/03-backtest-automation.md`

- 「位置づけ」セクションの「次の06-real-world-examplesでは、ここまでの内容を統合した実践的なツール構築演習に取り組みます。」を「次の04-lead-lag-correlation.mdでは、02で学んだ相関係数を時間差の視点に拡張します。」に変更する
- 末尾ナビゲーションの`[次へ: 06-real-world-examples →]`を`[次へ: 相関とリード・ラグ分析の基礎 →](04-lead-lag-correlation.md)`に変更する

### `docs/00-COVER.md`

- 「学習の流れ」の`STEP 5`のブロックを以下に変更する:
  ```
  STEP 5 ──→ Portfolio Management（5教材）
               AIポートフォリオ分析・リスク評価・バックテスト自動化・
               リード/ラグ分析・周期分解（ウェーブレット、発展）
  ```

### `docs/06-real-world-examples/00-README.md`

「さらに発展させた実装例」セクションの以下の一文を修正する。

修正前:
> 本カテゴリ、特に03「統合ポートフォリオアドバイザーエージェント」の考え方をさらに発展させ、複数戦略（移動平均クロスオーバー／RSI逆張り／MACDクロスオーバー／ボリンジャーバンド逆張り）のバックテスト、ユニバース一括ランキング、セクターローテーション分析、銘柄詳細（ローソク足＋移動平均線チャート）などを追加した完成版のStreamlitアプリが[`app/`](../../app/README.md)にあります。

修正後（該当部分のみ差し替え、他の戦略・ランキング・チャートに関する記述は変更しない）:
> セクター間のリード・ラグ分析・周期分解（ウェーブレット分析）の基礎は[05-portfolio-management](../05-portfolio-management/00-README.md)の04・05で学べます。app/の完成版UIでは、これらの考え方を17業種・複数の周期帯に対応させ、直近シグナルの要約パネルやAI解説コメント（キャッシュ付き）まで拡張しています。

## エラーハンドリング・留意点

本機能はMarkdown教材のみの変更であり、実行時エラーハンドリングは対象外。ただし以下の一貫性に留意する。

| 事象 | 対応 |
| --- | --- |
| 教材05のサンプルコードが平滑化を省略しているため、コヒーレンスが常に高くなる（実運用と異なる挙動） | 教材05の実ソースコード直後に注記として明記済み（上記参照）。読者が実運用コードと誤解しないようにする |
| `pywavelets`という新規依存が既存教材（pandas/numpy/yfinanceのみ）と異なる | 教材05冒頭で明示し、インストール手順（`uv add pywavelets`）を案内する |
| 04・05を追加したことで03の「カテゴリ最後の教材」という既存記述と矛盾する | 「既存ファイルへの波及修正」に記載の通り03を更新する |

## テスト方針

Markdown教材のみの変更であり自動テスト対象はない。以下を確認する。

- 新規2教材のPythonコード例が単体で構文的に妥当であること（`python -m py_compile`等での簡易チェック。`pywavelets`がインストールされていない環境でも構文チェック自体は可能）
- 教材04・05・既存03の前後ナビゲーションリンクが循環せず、実在するファイルを指していること
- 00-COVER.md・05-README.md・06-README.mdの数値（教材数）が実際のファイル数と一致していること
