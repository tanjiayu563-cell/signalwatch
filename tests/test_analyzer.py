import unittest

from monitor_agent.analyzer import analyze_item, cluster_items, match_terms, title_similarity


class AnalyzerTests(unittest.TestCase):
    def test_keyword_match_ignores_spacing_and_case(self):
        item = {"title": "iPhone 新品回应", "summary": "", "author": ""}
        self.assertEqual(match_terms(item, ["iphone"]), ["iphone"])

    def test_matched_critical_item_raises_alert(self):
        item = {
            "title": "某品牌产品发生爆炸事故",
            "summary": "市场监管部门已立案调查",
            "author": "测试媒体",
            "rank": 3,
            "hot_value": 100000,
        }
        result = analyze_item(item, ["某品牌"])
        self.assertTrue(result["is_relevant"])
        self.assertTrue(result["alert"])
        self.assertEqual(result["risk_level"], "high")
        self.assertTrue(result["risk_reasons"])

    def test_unmatched_item_does_not_alert(self):
        item = {
            "title": "其他品牌发生安全事故",
            "summary": "事故正在调查",
            "author": "测试媒体",
            "rank": 1,
        }
        result = analyze_item(item, ["目标品牌"])
        self.assertFalse(result["is_relevant"])
        self.assertFalse(result["alert"])

    def test_weak_response_outside_top_ten_stays_low(self):
        item = {
            "title": "某品牌回应网络讨论",
            "summary": "品牌发布说明",
            "author": "品牌账号",
            "rank": 30,
        }
        result = analyze_item(item, ["某品牌"])
        self.assertEqual(result["risk_level"], "low")
        self.assertFalse(result["alert"])

    def test_no_watch_terms_never_creates_alert(self):
        item = {"title": "重大安全事故", "summary": "", "author": "", "rank": 1}
        result = analyze_item(item, [])
        self.assertFalse(result["alert"])

    def test_similar_titles_cluster_with_same_term(self):
        base = {
            "source": "weibo_hot",
            "risk_level": "medium",
            "risk_reasons": ["法律与监管：调查"],
            "matched_terms": ["某品牌"],
            "alert": True,
            "sentiment": "negative",
            "fetched_at": "2026-10-27T00:00:00+00:00",
            "published_at": None,
            "review_status": "new",
            "hot_value": 100,
        }
        items = [
            {
                **base,
                "id": "a",
                "title": "某品牌被调查",
                "summary": "",
                "source": "weibo_hot",
            },
            {
                **base,
                "id": "b",
                "title": "某品牌被立案调查",
                "summary": "",
                "source": "toutiao_hot",
            },
            {
                **base,
                "id": "c",
                "title": "完全无关的体育消息",
                "summary": "",
                "source": "douyin_hot",
                "matched_terms": [],
                "alert": False,
                "risk_level": "low",
            },
        ]
        events = cluster_items(items, threshold=0.3)
        first_event = next(event for event in events if "a" in event["item_ids"])
        self.assertIn("b", first_event["item_ids"])
        self.assertGreater(title_similarity(items[0]["title"], items[1]["title"]), 0.3)


if __name__ == "__main__":
    unittest.main()
