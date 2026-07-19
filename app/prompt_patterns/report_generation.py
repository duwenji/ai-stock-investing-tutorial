import json

from common.disclaimer import DISCLAIMER_NOTICE


def build_report_prompt(facts: dict) -> str:
    facts_json = json.dumps(facts, ensure_ascii=False, indent=2, default=str)
    return (
        "以下はポートフォリオの事実データ（Python側で計算済み）です。\n\n"
        f"{facts_json}\n\n"
        "このデータを見て、教育的な観察事項（例: 集中度が高い銘柄、"
        "ニュースセンチメントが弱い銘柄、テクニカルシグナルが弱含みの銘柄）を"
        "箇条書きで示してください。\n"
        "各銘柄に言及する際は、必ず「銘柄コード（銘柄名）」の形式で表記して"
        "ください（例: 7203.T（トヨタ自動車））。銘柄名は各データ内の"
        "name フィールドおよび ticker_names を参照してください。\n"
        "売買の推奨・指示・目標株価の提示は行わないでください。\n\n"
        f"{DISCLAIMER_NOTICE}"
    )
