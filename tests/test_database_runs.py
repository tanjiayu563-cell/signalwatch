import tempfile
import unittest
from pathlib import Path

from monitor_agent import database


class DatabaseRunTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_path = database.DB_PATH
        database.DB_PATH = Path(self.tempdir.name) / "test.db"
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.tempdir.cleanup()

    def test_agent_run_lifecycle(self):
        run_id = database.create_agent_run(
            "test",
            ["品牌A"],
            {"objective": "测试目标", "source_ids": ["weibo_hot"]},
        )
        database.update_agent_run(
            run_id,
            status="completed",
            steps=[{"name": "plan", "status": "completed"}],
            metrics={"items_fetched": 2},
            finish=True,
        )
        run = database.fetch_agent_run(run_id)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["watch_terms"], ["品牌A"])
        self.assertEqual(run["metrics"]["items_fetched"], 2)
        self.assertEqual(run["steps"][0]["name"], "plan")

    def test_alert_candidates_are_deduplicated(self):
        item = {
            "id": "weibo_hot:1",
            "source": "weibo_hot",
            "external_id": "1",
            "title": "品牌A发生安全事故",
            "url": "https://example.com/1",
            "summary": "测试",
            "author": "微博热搜",
            "published_at": None,
            "fetched_at": database.utc_now(),
            "rank": 1,
            "hot_value": 100,
            "raw": {},
        }
        analysis = {
            "matched_terms": ["品牌A"],
            "risk_level": "high",
            "risk_reasons": ["人身与安全：事故"],
            "sentiment": "negative",
            "is_relevant": True,
            "alert": True,
            "method": "rules-v1",
            "analyzed_at": database.utc_now(),
        }
        database.upsert_item(item, analysis)
        run_id = database.create_agent_run("test", ["品牌A"], {})
        alert = {**item, **analysis}
        self.assertEqual(len(database.record_alert_candidates(run_id, [alert])), 1)
        self.assertEqual(len(database.record_alert_candidates(run_id, [alert])), 0)
        database.update_alert_delivery([item["id"]], "sent")
        recent = database.recent_alerts(10)
        self.assertEqual(recent[0]["delivery_status"], "sent")


if __name__ == "__main__":
    unittest.main()
