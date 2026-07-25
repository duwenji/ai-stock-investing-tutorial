# バックテスト自動化

## この教材で身につくこと

- 移動平均クロスオーバー戦略をpandasでベクトル化してバックテストする方法
- 勝率・最大ドローダウン・累積リターンなどの指標をPythonで集計する方法
- バックテスト結果をLLMに解説させる際、過学習・将来性能の限界を明記する設計

## 概要

バックテストとは、過去の価格データに対して売買ルールを適用し、
そのルールが過去にどう機能したかを検証する手法です。

バックテストの結果は「過去にうまくいった」ことを示すに過ぎず、
将来の成績を保証しません。本教材では、04-analysis-agentsの
テクニカル分析エージェントで扱った移動平均クロスオーバー戦略を例に、
バックテストの実装とLLMによる結果解説の設計を学びます。

## 位置づけ

この教材は05-portfolio-managementカテゴリの3番目の教材です。
01・02で学んだ「構成比の要約」「リスク指標の解説」に続き、
本教材では「戦略の過去成績の解説」を扱います。

次の04-lead-lag-correlation.mdでは、02で学んだ相関係数を
時間差の視点に拡張します。

## 主要概念・パラメータ解説

### バックテスト結果の指標

| 指標             | 計算方法                                        | 意味                                   |
| ---------------- | ----------------------------------------------- | -------------------------------------- |
| 累積リターン     | `(1 + 日次リターン).cumprod() - 1`            | 期間全体の総合的な収益率               |
| 勝率             | `プラスリターンの日数 ÷ 取引日数`            | シグナルに従った日のうち利益が出た割合 |
| 最大ドローダウン | 累積リターンのピークからの最大下落率            | 保有中に発生しうる最大の含み損幅       |
| 対ベンチマーク差 | `戦略の累積リターン - Buy&Holdの累積リターン` | 単純保有と比べた優劣                   |

### バックテストで注意すべき点

| 注意点                 | 内容                                                         |
| ---------------------- | ------------------------------------------------------------ |
| ルックアヘッドバイアス | シグナル発生日の終値ではなく、翌日の始値等で約定させる       |
| 過学習                 | パラメータを過去データに合わせすぎると将来性能が劣化しやすい |
| 取引コスト未考慮       | 手数料・スリッページを含めないと実績より良く見える           |
| 生存者バイアス         | 上場廃止銘柄を除いたデータだと成績が過大評価されやすい       |

これらの注意点は、LLMによる結果解説の中でも明示する必要があります。

## 実ソースコード（Python / プロンプト例）

### 移動平均クロスオーバーのベクトル化バックテスト

```python
import numpy as np
import pandas as pd
import yfinance as yf


def run_ma_crossover_backtest(
    ticker: str,
    short_window: int = 25,
    long_window: int = 75,
    period: str = "3y",
) -> dict:
    """移動平均クロスオーバー戦略をベクトル化してバックテストする。"""
    prices = yf.download(ticker, period=period)["Close"]
    short_ma = prices.rolling(short_window).mean()
    long_ma = prices.rolling(long_window).mean()

    # 短期MAが長期MAを上回っている日をロングポジション(1)とする
    position = (short_ma > long_ma).astype(int).shift(1).fillna(0)

    daily_return = prices.pct_change().fillna(0)
    strategy_return = position * daily_return
    benchmark_return = daily_return  # Buy & Hold

    cum_strategy = (1 + strategy_return).cumprod() - 1
    cum_benchmark = (1 + benchmark_return).cumprod() - 1

    trade_days = position[position != 0].index
    win_rate = (strategy_return.loc[trade_days] > 0).mean()

    running_max = (1 + cum_strategy).cummax()
    drawdown = (1 + cum_strategy) / running_max - 1
    max_drawdown = drawdown.min()

    return {
        "total_return": round(cum_strategy.iloc[-1] * 100, 2),
        "benchmark_return": round(cum_benchmark.iloc[-1] * 100, 2),
        "win_rate": round(win_rate * 100, 2),
        "max_drawdown": round(max_drawdown * 100, 2),
        "trade_days": int(len(trade_days)),
    }
```

### LLMによる結果解説

```python
def explain_backtest_result(ticker: str) -> str:
    """バックテスト結果を計算し、LLMに教育的な解説をさせる。"""
    stats = run_ma_crossover_backtest(ticker)

    prompt = f"""\
以下は移動平均クロスオーバー戦略（25日/75日）のバックテスト結果です
（Python側で計算済みのため再計算は不要です）。

この結果を投資初心者にも分かる言葉で説明してください。
以下を必ず含めてください。
1. 戦略のリターンとベンチマーク（Buy&Hold）の比較
2. 勝率・最大ドローダウンの意味
3. 過去の結果が将来の成績を保証しないこと、
   および過学習・取引コスト未考慮などバックテストの限界への注意喚起
4. 追加で確認する価値がある指標やシナリオの提案（実行はしない）

出力は事実の説明と教育的な提案にとどめ、「買うべき」「このルールで
今すぐ売買すべき」のような指示的な表現は使わないでください。

【対象銘柄】{ticker}
【累積リターン（戦略）】{stats["total_return"]}%
【累積リターン（Buy&Hold）】{stats["benchmark_return"]}%
【勝率】{stats["win_rate"]}%
【最大ドローダウン】{stats["max_drawdown"]}%
【取引日数】{stats["trade_days"]}日
"""
    return call_llm(prompt)


def call_llm(prompt: str) -> str:
    # 実装は 03-data-api/02-llm-api-integration.md 参照
    raise NotImplementedError


if __name__ == "__main__":
    print(explain_backtest_result("7203.T"))
```

### 実行結果例

```text
【対象銘柄】7203.T
【累積リターン（戦略）】18.4%
【累積リターン（Buy&Hold）】24.7%
【勝率】54.2%
【最大ドローダウン】-12.3%
【取引日数】312日
```

```text
この移動平均クロスオーバー戦略の累積リターンは18.4%で、
同期間のBuy&Hold（単純保有）の24.7%を下回りました。
シグナルに従った日のうち勝率は54.2%、保有中の最大下落幅は
12.3%でした。

これはあくまで過去3年間の1銘柄に対する結果であり、将来も
同様の成績になるとは限りません。特に、パラメータ（25日/75日）を
このデータに合わせて選んでいる場合は過学習のリスクがあり、
また今回の集計には取引手数料やスリッページを含めていない点にも
注意が必要です。

追加で確認する価値がある観点として、異なる期間での検証、
複数銘柄でのパラメータの再現性、取引コストを加味した再計算が
挙げられます。これらは一般的な教育目的の提案であり、
特定の売買を推奨するものではありません。
```

### 良い例と悪い例

悪い例は好成績の数値だけを示し、限界や注意点に触れていません。
バックテストの結果を実態以上に信頼させてしまうリスクがあります。

```text
❌ 悪い例:
「この戦略は勝率54.2%で有効です。この設定で運用しましょう。」
```

良い例は、過学習リスクと将来性能を保証しないことを明記しています。

```text
✅ 良い例:
「過去3年間の結果であり、将来も同様とは限りません。パラメータを
このデータに合わせて選んでいる場合は過学習のリスクがあります。
取引コストも含めていない点にご注意ください。」
```

## 演習課題

1. `run_ma_crossover_backtest` に取引コスト（1回あたり0.1%）を
   加味した場合の累積リターンを計算する処理を追加してください。
2. 短期/長期の移動平均期間を変えて複数パターンでバックテストし、
   結果が大きく変動するかどうかを確認してください。
3. 「悪い例」のプロンプト出力が問題になる理由を、
   [免責事項](../../DISCLAIMER.md)の内容と関連づけて説明してください。

## 理解度チェック

- [ ] ルックアヘッドバイアスを避けるためにシグナルを1日ずらす理由を説明できる
- [ ] バックテスト結果が将来の成績を保証しない理由を3つ以上挙げられる
- [ ] LLMの解説プロンプトに過学習への注意喚起を含める理由を説明できる

---

投資判断に関わる内容です。必ず [免責事項](../../DISCLAIMER.md) をご確認ください。

[← 前へ: リスク評価・分散](02-risk-assessment.md) | [次へ: 相関とリード・ラグ分析の基礎 →](04-lead-lag-correlation.md)
