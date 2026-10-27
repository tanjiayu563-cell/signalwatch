import json
import unittest
from unittest.mock import patch

from monitor_agent.ai import AIClient, merge_ai_result


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class AIClientTests(unittest.TestCase):
    def test_disabled_without_configuration(self):
        client = AIClient("", "")
        self.assertFalse(client.enabled)
        result = client.analyze([], [])
        self.assertFalse(result.ok)

    def test_openai_compatible_response_is_parsed(self):
        model_output = {
            "results": [
                {
                    "id": "item-1",
                    "relevance": "direct",
                    "risk_level": "high",
                    "risk_categories": ["产品安全"],
                    "risk_reasons": ["多个账号声称产品开裂"],
                    "summary": "存在产品开裂相关指控，尚待核实。",
                    "claim_type": "claim",
                    "verification_questions": ["是否有检测报告？"],
                    "confidence": 0.82,
                }
            ]
        }
        api_payload = {
            "choices": [
                {
                    "message": {
                        "content": "```json\n"
                        + json.dumps(model_output, ensure_ascii=False)
                        + "\n```"
                    }
                }
            ]
        }
        client = AIClient("http://127.0.0.1:11434/v1", "test-model")
        with patch(
            "monitor_agent.ai.urllib.request.urlopen",
            return_value=FakeResponse(api_payload),
        ):
            result = client.analyze(
                [
                    {
                        "id": "item-1",
                        "source": "weibo_hot",
                        "title": "产品开裂",
                        "summary": "用户投诉",
                    }
                ],
                ["产品"],
            )
        self.assertTrue(result.ok)
        self.assertEqual(result.results["item-1"]["risk_level"], "high")
        self.assertEqual(result.results["item-1"]["claim_type"], "claim")


    def test_responses_api_output_is_parsed(self):
        model_output = {
            "results": [
                {
                    "id": "item-1",
                    "relevance": "direct",
                    "risk_level": "medium",
                    "risk_categories": ["产品"],
                    "risk_reasons": ["用户反馈产品故障"],
                    "summary": "需要核查产品故障反馈。",
                    "claim_type": "claim",
                    "verification_questions": ["是否有官方说明？"],
                    "confidence": 0.7,
                }
            ]
        }
        api_payload = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(model_output, ensure_ascii=False),
                        }
                    ],
                }
            ]
        }
        client = AIClient(
            "http://127.0.0.1:15721/v1",
            "deepseek-flash",
            wire_api="responses",
        )
        with patch(
            "monitor_agent.ai.urllib.request.urlopen",
            return_value=FakeResponse(api_payload),
        ):
            result = client.analyze(
                [
                    {
                        "id": "item-1",
                        "source": "weibo_hot",
                        "title": "产品故障",
                        "summary": "用户反馈",
                    }
                ],
                ["产品"],
            )
        self.assertTrue(result.ok)
        self.assertEqual(result.results["item-1"]["risk_level"], "medium")

    def test_merge_caps_ai_escalation(self):
        rule = {
            "risk_level": "medium",
            "risk_reasons": [],
            "alert": True,
            "is_relevant": True,
            "matched_terms": ["品牌"],
            "method": "rules-v1",
        }
        merged = merge_ai_result(
            rule,
            {
                "risk_level": "high",
                "risk_reasons": ["模型认为风险较高"],
                "summary": "需要核查",
                "risk_categories": ["产品"],
                "verification_questions": [],
                "claim_type": "claim",
                "relevance": "direct",
                "confidence": 0.9,
            },
        )
        self.assertEqual(merged["risk_level"], "medium")

    def test_merge_does_not_lower_rule_risk(self):
        rule = {
            "risk_level": "high",
            "risk_reasons": ["规则：事故"],
            "alert": True,
            "is_relevant": True,
            "matched_terms": ["品牌"],
            "method": "rules-v1",
        }
        merged = merge_ai_result(
            rule,
            {
                "risk_level": "low",
                "risk_reasons": [],
                "summary": "未发现明显风险",
                "risk_categories": [],
                "verification_questions": [],
                "claim_type": "opinion",
                "relevance": "direct",
                "confidence": 0.5,
            },
        )
        self.assertEqual(merged["risk_level"], "high")
        self.assertTrue(merged["alert"])
        self.assertIn("ai", merged)


if __name__ == "__main__":
    unittest.main()
