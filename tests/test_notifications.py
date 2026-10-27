import json
import unittest
from unittest.mock import patch

from monitor_agent.notifications import Notifier


class FakeWebhookResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class NotificationTests(unittest.TestCase):
    def test_generic_webhook_payload(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeWebhookResponse()

        notifier = Notifier(
            webhook_url="https://example.com/hook",
            webhook_type="generic",
            min_risk="medium",
        )
        with patch(
            "monitor_agent.notifications.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            result = notifier.notify(
                [
                    {
                        "item_id": "item-1",
                        "risk_level": "high",
                        "title": "风险事件",
                        "source": "weibo_hot",
                        "url": "https://example.com/item-1",
                        "matched_terms": ["品牌A"],
                        "risk_reasons": ["事故"],
                    }
                ],
                "run-1",
                "覆盖说明",
            )
        self.assertEqual(result["status"], "sent")
        self.assertEqual(captured["body"]["run_id"], "run-1")
        self.assertEqual(captured["body"]["alerts"][0]["item_id"], "item-1")

    def test_low_risk_is_not_sent(self):
        notifier = Notifier(webhook_url="https://example.com/hook", min_risk="medium")
        result = notifier.notify(
            [{"item_id": "low", "risk_level": "low", "title": "低风险"}],
            "run-1",
        )
        self.assertEqual(result["status"], "no_eligible_alerts")
        self.assertEqual(result["sent"], 0)


if __name__ == "__main__":
    unittest.main()
