import unittest

from monitor_agent.evaluation import metrics_for_rows


class EvaluationTests(unittest.TestCase):
    def test_alert_metrics(self):
        rows = [
            {
                "expected": {"alert": True},
                "predicted": {"alert": True},
                "relevance_correct": True,
                "risk_correct": True,
            },
            {
                "expected": {"alert": True},
                "predicted": {"alert": False},
                "relevance_correct": True,
                "risk_correct": False,
            },
            {
                "expected": {"alert": False},
                "predicted": {"alert": True},
                "relevance_correct": True,
                "risk_correct": True,
            },
        ]
        metrics = metrics_for_rows(rows)
        self.assertEqual(metrics["confusion"], {"tp": 1, "fp": 1, "fn": 1, "tn": 0})
        self.assertEqual(metrics["alert_precision"], 0.5)
        self.assertEqual(metrics["alert_recall"], 0.5)
        self.assertEqual(metrics["alert_f1"], 0.5)


if __name__ == "__main__":
    unittest.main()
