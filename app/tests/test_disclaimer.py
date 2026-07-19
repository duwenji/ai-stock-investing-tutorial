from common.disclaimer import DISCLAIMER_NOTICE


def test_disclaimer_notice_mentions_not_investment_advice():
    assert "投資助言ではありません" in DISCLAIMER_NOTICE


def test_disclaimer_notice_mentions_educational_purpose():
    assert "教育目的" in DISCLAIMER_NOTICE
