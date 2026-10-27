import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from .config import load_environment


@dataclass
class AIEnrichmentResult:
    ok: bool
    results: Dict[str, Dict[str, Any]]
    error: str = ""


class AIClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: int = 45,
        max_items: int = 20,
        wire_api: str = "chat_completions",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = max(10, timeout)
        self.max_items = max(1, min(100, max_items))
        self.wire_api = (
            wire_api if wire_api in {"responses", "chat_completions"} else "chat_completions"
        )

    @classmethod
    def from_env(cls) -> "AIClient":
        load_environment()
        return cls(
            base_url=os.getenv("MONITOR_AI_BASE_URL", "").strip(),
            model=os.getenv("MONITOR_AI_MODEL", "").strip(),
            api_key=os.getenv("MONITOR_AI_API_KEY", "").strip(),
            timeout=int(os.getenv("MONITOR_AI_TIMEOUT", "45")),
            max_items=int(os.getenv("MONITOR_AI_MAX_ITEMS", "20")),
            wire_api=os.getenv("MONITOR_AI_WIRE_API", "chat_completions").strip(),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.model)

    @property
    def mode_label(self) -> str:
        return f"AI + 规则 · {self.model}" if self.enabled else "规则引擎 · 单机模式"

    def public_status(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "model": self.model if self.enabled else "",
            "base_url": self.base_url if self.enabled else "",
            "max_items": self.max_items,
            "wire_api": self.wire_api,
            "mode_label": self.mode_label,
        }

    def analyze(self, items: List[Dict[str, Any]], watch_terms: Iterable[str]) -> AIEnrichmentResult:
        if not self.enabled:
            return AIEnrichmentResult(False, {}, "AI 模型未配置")
        candidates = items[: self.max_items]
        if not candidates:
            return AIEnrichmentResult(True, {})

        system_prompt = (
            "你是舆情监测研判助手。只能依据用户提供的证据判断，不得补写事实。"
            "风险判断用于人工预警，不是法律结论。严格返回 JSON 对象，不要输出 Markdown。"
        )
        user_prompt = self._build_prompt(candidates, list(watch_terms))
        if self.wire_api == "responses":
            payload = {
                "model": self.model,
                "instructions": system_prompt,
                "input": user_prompt,
            }
            endpoint = (
                self.base_url
                if self.base_url.endswith("/responses")
                else self.base_url + "/responses"
            )
        else:
            payload = {
                "model": self.model,
                "temperature": 0.1,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
            endpoint = (
                self.base_url
                if self.base_url.endswith("/chat/completions")
                else self.base_url + "/chat/completions"
            )
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
            data = json.loads(body)
            content = (
                self._extract_responses_content(data)
                if self.wire_api == "responses"
                else self._extract_content(data)
            )
            parsed = self._parse_json_content(content)
            results = parsed.get("results", [])
            if not isinstance(results, list):
                raise ValueError("模型返回缺少 results 数组")
            mapped: Dict[str, Dict[str, Any]] = {}
            for result in results:
                if not isinstance(result, dict) or not result.get("id"):
                    continue
                mapped[str(result["id"])] = self._normalize_result(result)
            return AIEnrichmentResult(True, mapped)
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as exc:
            return AIEnrichmentResult(False, {}, f"{type(exc).__name__}: {exc}"[:500])

    def _build_prompt(self, items: List[Dict[str, Any]], watch_terms: List[str]) -> str:
        evidence = []
        for item in items:
            evidence.append(
                {
                    "id": item.get("id"),
                    "source": item.get("source"),
                    "title": item.get("title", "")[:240],
                    "summary": item.get("summary", "")[:800],
                    "author": item.get("author", ""),
                    "rank": item.get("rank"),
                    "hot_value": item.get("hot_value"),
                }
            )
        return (
            f"监测词：{json.dumps(watch_terms, ensure_ascii=False)}\n"
            f"证据：{json.dumps(evidence, ensure_ascii=False)}\n\n"
            "请返回如下结构：\n"
            '{"results":[{"id":"原始id","relevance":"direct|indirect|competitor|industry|unrelated",'
            '"risk_level":"low|medium|high","risk_categories":["最多3项"],'
            '"risk_reasons":["最多3条，每条必须引用证据中的事实"],'
            '"summary":"不超过120字，只能概括证据",'
            '"claim_type":"fact|claim|opinion|unverified",'
            '"verification_questions":["最多3个需要人工核查的问题"],'
            '"confidence":0.0}]}'
        )

    def _extract_responses_content(self, data: Dict[str, Any]) -> str:
        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text
        output = data.get("output")
        if isinstance(output, list):
            parts: List[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") in {"output_text", "text"} and isinstance(
                        part.get("text"), str
                    ):
                        parts.append(part["text"])
            if parts:
                return "".join(parts)
        if data.get("choices"):
            return self._extract_content(data)
        raise ValueError("Responses API 响应中未找到输出文本")

    def _extract_content(self, data: Dict[str, Any]) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            if isinstance(data.get("response"), str):
                return data["response"]
            raise ValueError("模型响应缺少 choices")
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
            content = "".join(parts)
        if not isinstance(content, str) or not content.strip():
            raise ValueError("模型响应内容为空")
        return content

    def _parse_json_content(self, content: str) -> Dict[str, Any]:
        text = content.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("模型未返回 JSON 对象")
        parsed = json.loads(text[start : end + 1])
        if not isinstance(parsed, dict):
            raise ValueError("模型 JSON 顶层不是对象")
        return parsed

    def _normalize_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        risk_level = str(result.get("risk_level", "low")).lower()
        if risk_level not in {"low", "medium", "high"}:
            risk_level = "low"

        def string_list(value: Any, limit: int = 3) -> List[str]:
            if not isinstance(value, list):
                return []
            return [str(item).strip()[:300] for item in value if str(item).strip()][:limit]

        try:
            confidence = float(result.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        return {
            "risk_level": risk_level,
            "relevance": str(result.get("relevance", "unrelated"))[:40],
            "risk_categories": string_list(result.get("risk_categories")),
            "risk_reasons": string_list(result.get("risk_reasons")),
            "summary": str(result.get("summary", "")).strip()[:500],
            "claim_type": str(result.get("claim_type", "unverified"))[:40],
            "verification_questions": string_list(result.get("verification_questions")),
            "confidence": max(0.0, min(1.0, confidence)),
        }


def merge_ai_result(analysis: Dict[str, Any], ai_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not ai_result:
        return analysis
    merged = dict(analysis)
    rule_risk = analysis.get("risk_level", "low")
    ai_risk = ai_result.get("risk_level", "low")
    order = {"low": 1, "medium": 2, "high": 3}
    combined_risk = max(rule_risk, ai_risk, key=lambda value: order.get(value, 0))
    if rule_risk == "low" and combined_risk in {"medium", "high"}:
        merged["risk_level"] = "medium"
    elif rule_risk == "medium":
        merged["risk_level"] = "medium"
    else:
        merged["risk_level"] = rule_risk
    reasons = list(analysis.get("risk_reasons", []))
    for reason in ai_result.get("risk_reasons", []):
        label = f"AI研判：{reason}"
        if label not in reasons:
            reasons.append(label)
    merged["risk_reasons"] = reasons[:10]
    merged["ai"] = ai_result
    merged["alert"] = bool(
        merged.get("is_relevant") and merged["risk_level"] in {"high", "medium"}
    )
    merged["method"] = f"{analysis.get('method', 'rules-v1')}+ai"
    return merged
