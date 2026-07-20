def build_stock_detail_prompt(
    ticker: str, name: str | None, fundamentals: dict, technical: dict, news: list[dict]
) -> str:
    news_titles = "\n".join(f"- {item.get('title')}" for item in news) or "- (ニュースなし)"
    label = f"{ticker}（{name}）" if name else ticker
    return (
        f"銘柄 {label} について、以下のファンダメンタルズ・テクニカル・ニュース見出しを踏まえて、"
        "投資家向けの総合分析コメントを日本語で3〜4文程度で作成してください。"
        "断定的な売買判断は含めないでください。\n\n"
        f"PER: {fundamentals.get('per')}\n"
        f"PBR: {fundamentals.get('pbr')}\n"
        f"配当利回り: {fundamentals.get('dividend_yield')}\n"
        f"テクニカルシグナル: {technical.get('signal')}\n"
        f"直近ニュース見出し:\n{news_titles}\n"
    )
