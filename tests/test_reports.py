import unittest
from unittest.mock import patch

from monitor_agent.service import MonitorService


class ReportTests(unittest.TestCase):
    def test_event_report_contains_evidence_and_disclaimer(self):
        service = MonitorService()
        state = {
            "generated_at": "2026-10-27T00:00:00+00:00",
            "events": [
                {
                    "id": "event:1",
                    "title": "品牌A安全事件",
                    "risk_level": "high",
                    "matched_terms": ["品牌A"],
                    "sources": ["weibo_hot"],
                    "first_seen": "2026-10-27T00:00:00+00:00",
                    "last_seen": "2026-10-27T00:01:00+00:00",
                    "review_status": "new",
                    "summary": "事件摘要",
                    "risk_reasons": ["人身与安全：事故"],
                    "items": [
                        {
                            "title": "原始内容",
                            "source": "weibo_hot",
                            "author": "微博热搜",
                            "rank": 1,
                            "hot_value": 100,
                            "published_at": None,
                            "first_seen_at": "2026-10-27T00:00:00+00:00",
                            "fetched_at": "2026-10-27T00:01:00+00:00",
                            "url": "https://example.com/item",
                            "ai": {},
                        }
                    ],
                }
            ],
        }
        with patch.object(service, "state", return_value=state):
            report = service.event_report("event:1")
        self.assertIsNotNone(report)
        self.assertIn("https://example.com/item", report["content"])
        self.assertIn("不构成事实认定", report["content"])


if __name__ == "__main__":
    unittest.main()
