import unittest

from monitor_agent.sources import (
    parse_authorized_items,
    parse_bilibili,
    parse_chinanews,
    parse_douyin,
    parse_toutiao,
    parse_weibo,
)


class SourceParserTests(unittest.TestCase):
    def setUp(self):
        self.fetched_at = "2026-10-27T00:00:00+00:00"

    def test_weibo_parser(self):
        payload = {
            "data": {
                "realtime": [
                    {"word": "测试热搜", "realpos": 1, "num": 12345},
                ]
            }
        }
        items = parse_weibo(payload, self.fetched_at)
        self.assertEqual(items[0]["source"], "weibo_hot")
        self.assertEqual(items[0]["rank"], 1)
        self.assertIn("q=", items[0]["url"])

    def test_douyin_parser(self):
        payload = {"word_list": [{"word": "抖音测试", "hot_value": 900}]}
        items = parse_douyin(payload, self.fetched_at)
        self.assertEqual(items[0]["source"], "douyin_hot")
        self.assertEqual(items[0]["hot_value"], 900)

    def test_toutiao_parser(self):
        payload = {
            "data": [
                {
                    "ClusterId": 123,
                    "Title": "头条测试",
                    "Url": "https://www.toutiao.com/trending/123/",
                    "HotValue": "888",
                }
            ]
        }
        items = parse_toutiao(payload, self.fetched_at)
        self.assertEqual(items[0]["external_id"], "123")
        self.assertEqual(items[0]["hot_value"], 888)

    def test_bilibili_parser(self):
        payload = {
            "data": {
                "list": [
                    {
                        "bvid": "BV123",
                        "title": "B站测试",
                        "desc": "描述",
                        "pubdate": 1790000000,
                        "owner": {"name": "UP主"},
                        "stat": {"view": 456},
                    }
                ]
            }
        }
        items = parse_bilibili(payload, self.fetched_at)
        self.assertEqual(items[0]["author"], "UP主")
        self.assertEqual(items[0]["hot_value"], 456)

    def test_chinanews_parser(self):
        xml = """<?xml version="1.0" encoding="utf-8"?>
        <rss><channel><item>
          <title>权威新闻测试</title>
          <link>https://example.com/news/1</link>
          <description>新闻摘要</description>
          <pubDate>Tue, 27 Oct 2026 10:00:00 +0800</pubDate>
        </item></channel></rss>""".encode("utf-8")
        items = parse_chinanews(xml, self.fetched_at)
        self.assertEqual(items[0]["source"], "chinanews")
        self.assertEqual(items[0]["title"], "权威新闻测试")

    def test_authorized_provider_contract(self):
        payload = {
            "items": [
                {
                    "id": "p1",
                    "title": "授权接口结果",
                    "url": "https://example.com/p1",
                    "summary": "摘要",
                    "author": "账号",
                    "rank": 2,
                }
            ]
        }
        items = parse_authorized_items(payload, "douyin_search", self.fetched_at)
        self.assertEqual(items[0]["source"], "douyin_search")
        self.assertEqual(items[0]["rank"], 2)


if __name__ == "__main__":
    unittest.main()


class AuthorizedConnectorTests(unittest.TestCase):
    def test_authorized_connector_uses_provider_contract(self):
        from unittest.mock import patch

        from monitor_agent.sources import fetch_authorized_source

        payload = {
            "items": [
                {
                    "id": "x1",
                    "title": "测试内容",
                    "url": "https://example.com/x1",
                }
            ]
        }
        calls = []

        def fake_request_json(url, headers=None, opener=None):
            calls.append((url, headers))
            return payload

        with patch("monitor_agent.sources.request_json", side_effect=fake_request_json):
            result = fetch_authorized_source(
                "douyin_search",
                {
                    "auth_type": "api_token",
                    "secret": "secret-token",
                    "endpoint": "https://provider.example/search",
                },
                ["测试品牌"],
            )

        self.assertEqual(len(calls), 1)
        self.assertIn("keyword=", calls[0][0])
        self.assertIn("limit=", calls[0][0])
        self.assertEqual(calls[0][1]["Authorization"], "Bearer secret-token")
        self.assertEqual(result.items[0]["source"], "douyin_search")
