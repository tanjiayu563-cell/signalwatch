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


@dataclass
class AIRelationsResult:
    ok: bool
    analysis: Dict[str, Any]
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
        try:
            parsed = self._complete_json(system_prompt, user_prompt)
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

    def analyze_public_relations(
        self,
        company: str,
        event: Dict[str, Any],
        evidence: List[Dict[str, Any]],
    ) -> AIRelationsResult:
        if not self.enabled:
            return AIRelationsResult(False, {}, "AI 模型未配置")
        system_prompt = (
            "你是企业公共关系与危机传播分析助手。你只能依据提供的证据研判，"
            "不得虚构事实、来源、引文或书籍原文。请综合使用利益相关方分析、议题生命周期、"
            "情境危机传播、形象修复和双向对称沟通等通用公共关系方法，但不要声称逐字引用书籍。"
            "结论是辅助建议，不替代法务、管理层或公关负责人决策。严格返回 JSON 对象，不要输出 Markdown。"
        )
        user_prompt = self._build_relations_prompt(company, event, evidence)
        try:
            parsed = self._complete_json(system_prompt, user_prompt)
            return AIRelationsResult(True, self._normalize_relations_analysis(parsed))
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as exc:
            return AIRelationsResult(False, {}, f"{type(exc).__name__}: {exc}"[:500])

    def _complete_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        if not self.enabled:
            raise ValueError("AI 模型未配置")
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
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = response.read().decode("utf-8")
        data = json.loads(body)
        content = (
            self._extract_responses_content(data)
            if self.wire_api == "responses"
            else self._extract_content(data)
        )
        return self._parse_json_content(content)

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

    def _build_relations_prompt(
        self,
        company: str,
        event: Dict[str, Any],
        evidence: List[Dict[str, Any]],
    ) -> str:
        compact_evidence = []
        for index, item in enumerate(evidence[:5], start=1):
            compact_evidence.append(
                {
                    "evidence_id": item.get("evidence_id") or item.get("id") or f"E{index}",
                    "source": item.get("source", ""),
                    "title": str(item.get("title", ""))[:240],
                    "url": item.get("url", ""),
                    "published_at": item.get("published_at"),
                    "excerpt": str(item.get("text") or item.get("summary") or "")[:4000],
                    "content_error": item.get("content_error", ""),
                }
            )
        event_payload = {
            "company": company,
            "title": event.get("title", ""),
            "summary": event.get("summary", ""),
            "risk_level": event.get("risk_level", ""),
            "risk_reasons": event.get("risk_reasons", []),
            "sources": event.get("sources", []),
            "first_seen": event.get("first_seen"),
            "last_seen": event.get("last_seen"),
            "evidence": compact_evidence,
        }
        return (
            "请对下面的企业舆情事件做公共关系研判。事实、来源声称和模型推断必须分开。\n"
            "分析要求：\n"
            "1. 使用议题生命周期判断事件阶段。\n"
            "2. 使用利益相关方分析识别核心关切、影响和优先级。\n"
            "3. 使用情境危机传播思路判断危机类型，但必须说明证据限制。\n"
            "4. 给出审慎的响应姿态、即时动作、沟通原则和声明草稿。\n"
            "5. 明确列出不能说的话、未证实说法和仍需核查的证据。\n"
            "6. 不提出删帖、压制传播、水军、煽动情绪或误导公众的建议。\n"
            "7. 草稿必须标记为待人工和法务复核。\n\n"
            f"事件材料：{json.dumps(event_payload, ensure_ascii=False)}\n\n"
            "严格返回以下 JSON 结构：\n"
            '{"executive_summary":"不超过180字",'
            '"issue_stage":"latent|emerging|outbreak|spreading|receding|unknown",'
            '"crisis_type":"victim|accidental|preventable|not_crisis|unknown",'
            '"severity":"low|medium|high",'
            '"frameworks_applied":["最多4项"],'
            '"stakeholders":[{"name":"","concern":"","impact":"","priority":"high|medium|low"}],'
            '"facts":[{"statement":"","evidence_ids":["E1"]}],'
            '"unverified_claims":[{"claim":"","evidence_ids":["E1"]}],'
            '"reputational_risks":["最多5项"],'
            '"response_posture":"一句话说明建议姿态及边界",'
            '"immediate_actions":[{"timing":"immediate|24h|ongoing","action":"","reason":""}],'
            '"message_principles":["最多5项"],'
            '"draft_holding_statement":"待人工和法务复核的简短声明草稿",'
            '"avoid_actions":["最多5项"],'
            '"monitoring_questions":["最多5项"],'
            '"evidence_gaps":["最多5项"],'
            '"confidence":0.0}'
        )

    def _normalize_relations_analysis(self, result: Dict[str, Any]) -> Dict[str, Any]:
        def string_list(value: Any, limit: int = 5) -> List[str]:
            if not isinstance(value, list):
                return []
            return [str(item).strip()[:500] for item in value if str(item).strip()][:limit]

        def object_list(value: Any, keys: List[str], limit: int = 8) -> List[Dict[str, Any]]:
            if not isinstance(value, list):
                return []
            output = []
            for item in value[:limit]:
                if not isinstance(item, dict):
                    continue
                normalized = {}
                for key in keys:
                    raw = item.get(key)
                    if isinstance(raw, list):
                        normalized[key] = [str(entry).strip()[:200] for entry in raw if str(entry).strip()][:8]
                    else:
                        normalized[key] = str(raw or "").strip()[:800]
                if any(normalized.values()):
                    output.append(normalized)
            return output

        issue_stage = str(result.get("issue_stage", "unknown")).lower()
        if issue_stage not in {"latent", "emerging", "outbreak", "spreading", "receding", "unknown"}:
            issue_stage = "unknown"
        crisis_type = str(result.get("crisis_type", "unknown")).lower()
        if crisis_type not in {"victim", "accidental", "preventable", "not_crisis", "unknown"}:
            crisis_type = "unknown"
        severity = str(result.get("severity", "medium")).lower()
        if severity not in {"low", "medium", "high"}:
            severity = "medium"
        try:
            confidence = float(result.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        return {
            "executive_summary": str(result.get("executive_summary", "")).strip()[:1000],
            "issue_stage": issue_stage,
            "crisis_type": crisis_type,
            "severity": severity,
            "frameworks_applied": string_list(result.get("frameworks_applied"), 4),
            "stakeholders": object_list(
                result.get("stakeholders"), ["name", "concern", "impact", "priority"]
            ),
            "facts": object_list(result.get("facts"), ["statement", "evidence_ids"]),
            "unverified_claims": object_list(
                result.get("unverified_claims"), ["claim", "evidence_ids"]
            ),
            "reputational_risks": string_list(result.get("reputational_risks"), 5),
            "response_posture": str(result.get("response_posture", "")).strip()[:1000],
            "immediate_actions": object_list(
                result.get("immediate_actions"), ["timing", "action", "reason"]
            ),
            "message_principles": string_list(result.get("message_principles"), 5),
            "draft_holding_statement": str(result.get("draft_holding_statement", "")).strip()[:2000],
            "avoid_actions": string_list(result.get("avoid_actions"), 5),
            "monitoring_questions": string_list(result.get("monitoring_questions"), 5),
            "evidence_gaps": string_list(result.get("evidence_gaps"), 5),
            "confidence": max(0.0, min(1.0, confidence)),
            "review_required": True,
        }

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
