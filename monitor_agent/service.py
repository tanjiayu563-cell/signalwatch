import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from . import database
from .ai import AIClient, merge_ai_result
from .analyzer import analyze_item, cluster_items
from .config import SCAN_INTERVAL_SECONDS
from .credentials import (
    credential_summary,
    delete_credential,
    get_credential,
    set_credential,
)
from .notifications import Notifier
from .sources import (
    AUTH_REQUIRED_SOURCES,
    PUBLIC_SOURCE_IDS,
    SOURCE_CATALOG,
    SourceResult,
    fetch_authorized_source,
    fetch_source,
)


SOURCE_NAMES = {source["id"]: source["name"] for source in SOURCE_CATALOG}
SOURCE_NAMES.update({source["id"]: source["name"] for source in AUTH_REQUIRED_SOURCES})
AUTH_SOURCE_IDS = {source["id"] for source in AUTH_REQUIRED_SOURCES}
RISK_ORDER = {"high": 3, "medium": 2, "low": 1}
COVERAGE_NOTE = (
    "当前接入公开热榜与公开新闻源；登录态或授权供应商来源只有在配置并验证接口后计入覆盖。"
    "未覆盖来源不会被解释为‘全网无舆情’。"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def split_terms(value: Any) -> List[str]:
    if isinstance(value, str):
        raw_terms = re.split(r"[,，\n;；]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_terms = list(value)
    else:
        raw_terms = []
    terms: List[str] = []
    seen = set()
    for raw in raw_terms:
        term = str(raw).strip()
        key = term.casefold()
        if term and key not in seen:
            terms.append(term[:60])
            seen.add(key)
        if len(terms) >= 30:
            break
    return terms


class MonitorService:
    def __init__(self) -> None:
        self._scan_lock = threading.Lock()
        self._last_error = ""
        self._last_finished_at: Optional[str] = None
        self.ai_client = AIClient.from_env()
        self.notifier = Notifier.from_env()
        self._last_ai_error = ""

    @property
    def running(self) -> bool:
        return self._scan_lock.locked()

    def set_watch_terms(self, value: Any) -> List[str]:
        terms = split_terms(value)
        database.set_watch_terms(terms)
        self.reanalyze_cached(terms)
        return terms

    def reanalyze_cached(self, terms: Optional[Iterable[str]] = None) -> int:
        active_terms = list(terms if terms is not None else database.get_watch_terms())
        items = database.fetch_items_for_reanalysis(limit=1500)
        for item in items:
            analysis = analyze_item(item, active_terms)
            database.upsert_item(item, analysis)
        return len(items)

    def authorize_source(
        self,
        source_id: str,
        auth_type: str,
        secret: str,
        endpoint: str = "",
    ) -> None:
        if source_id not in AUTH_SOURCE_IDS:
            raise ValueError("该来源不支持交互式授权")
        set_credential(source_id, auth_type=auth_type, secret=secret, endpoint=endpoint)

    def revoke_source(self, source_id: str) -> bool:
        if source_id not in AUTH_SOURCE_IDS:
            raise ValueError("该来源不是授权来源")
        return delete_credential(source_id)

    def scan(self, trigger: str = "manual") -> Dict[str, Any]:
        if not self._scan_lock.acquire(blocking=False):
            return {
                "status": "busy",
                "message": "扫描正在进行中",
            }
        started_monotonic = time.monotonic()
        started_at = utc_now()
        steps: List[Dict[str, Any]] = []
        run_id = ""
        try:
            terms = database.get_watch_terms()
            authorized_sources: Dict[str, Dict[str, Any]] = {}
            for source in AUTH_REQUIRED_SOURCES:
                credential = get_credential(source["id"])
                if credential and credential.get("endpoint"):
                    authorized_sources[source["id"]] = credential
            active_source_ids = PUBLIC_SOURCE_IDS + list(authorized_sources)
            plan = {
                "objective": "在已声明来源范围内发现与监测目标相关的舆情信号，聚合证据并进行风险研判。",
                "watch_terms": terms,
                "source_ids": active_source_ids,
                "source_names": [
                    SOURCE_NAMES.get(source_id, source_id)
                    for source_id in active_source_ids
                ],
                "analysis_pipeline": [
                    "规则关键词匹配与风险预筛",
                    "相似标题跨来源事件聚合",
                    (
                        "模型仅分析命中候选并要求结构化输出"
                        if self.ai_client.enabled
                        else "模型未配置，使用规则引擎独立研判"
                    ),
                    "规则风险不因模型输出而降低",
                    "告警候选去重后进入人工复核队列",
                ],
                "stop_policy": "所有来源返回、超时或失败后结束；失败来源必须显式记录，不解释为无舆情。",
            }
            run_id = database.create_agent_run(trigger, terms, plan)
            steps.append(
                self._step(
                    "plan",
                    "completed",
                    f"已生成查询与研判计划，使用 {len(active_source_ids)} 个来源",
                    {
                        "watch_terms": terms,
                        "authorized_sources": list(authorized_sources),
                    },
                )
            )
            database.update_agent_run(run_id, status="running", steps=steps)

            run_ids = {
                source_id: database.start_source_run(source_id)
                for source_id in active_source_ids
            }
            results: Dict[str, SourceResult] = {}
            errors: Dict[str, str] = {}

            with ThreadPoolExecutor(max_workers=max(1, len(active_source_ids))) as executor:
                futures = {}
                for source_id in PUBLIC_SOURCE_IDS:
                    futures[executor.submit(fetch_source, source_id)] = source_id
                for source_id, credential in authorized_sources.items():
                    futures[
                        executor.submit(fetch_authorized_source, source_id, credential, terms)
                    ] = source_id
                for future in as_completed(futures):
                    source_id = futures[future]
                    try:
                        result = future.result()
                        results[source_id] = result
                        database.finish_source_run(
                            run_ids[source_id], "ok", item_count=len(result.items)
                        )
                    except Exception as exc:
                        message = str(exc)[:1000]
                        errors[source_id] = message
                        database.finish_source_run(
                            run_ids[source_id], "error", error=message
                        )

            steps.append(
                self._step(
                    "collect",
                    "completed" if not errors else "partial",
                    f"{len(results)} 个来源成功，{len(errors)} 个来源失败",
                    {
                        "sources_ok": [
                            {
                                "id": source_id,
                                "name": SOURCE_NAMES.get(source_id, source_id),
                                "items": len(result.items),
                            }
                            for source_id, result in results.items()
                        ],
                        "sources_failed": [
                            {
                                "id": source_id,
                                "name": SOURCE_NAMES.get(source_id, source_id),
                                "error": message,
                            }
                            for source_id, message in errors.items()
                        ],
                    },
                )
            )

            analyzed_items = []
            seen_all = set()
            for result in results.values():
                for item in result.items:
                    if item["id"] in seen_all:
                        continue
                    seen_all.add(item["id"])
                    analysis = analyze_item(item, terms)
                    analyzed_items.append((item, analysis))

            matched_count = sum(
                1 for _, analysis in analyzed_items if analysis.get("is_relevant")
            )
            steps.append(
                self._step(
                    "rule_analysis",
                    "completed",
                    f"完成 {len(analyzed_items)} 条规则研判，命中监测目标 {matched_count} 条",
                    {
                        "items": len(analyzed_items),
                        "matched": matched_count,
                    },
                )
            )

            ai_enriched = 0
            if self.ai_client.enabled:
                candidates = [
                    item
                    for item, analysis in analyzed_items
                    if analysis.get("is_relevant") and analysis.get("matched_terms")
                ][: self.ai_client.max_items]
                if candidates:
                    ai_result = self.ai_client.analyze(candidates, terms)
                    if ai_result.ok:
                        candidate_ids = {item["id"] for item in candidates}
                        for item, analysis in analyzed_items:
                            if item["id"] in candidate_ids:
                                ai_item = ai_result.results.get(item["id"])
                                if ai_item:
                                    analysis.update(merge_ai_result(analysis, ai_item))
                                    ai_enriched += 1
                        self._last_ai_error = ""
                        steps.append(
                            self._step(
                                "ai_analysis",
                                "completed",
                                f"{self.ai_client.model} 完成 {ai_enriched} 条辅助研判",
                                {
                                    "model": self.ai_client.model,
                                    "candidates": len(candidates),
                                    "enriched": ai_enriched,
                                },
                            )
                        )
                    else:
                        self._last_ai_error = ai_result.error
                        steps.append(
                            self._step(
                                "ai_analysis",
                                "failed_fallback",
                                "模型调用失败，已保留规则研判结果",
                                {"error": self._last_ai_error},
                            )
                        )
                else:
                    self._last_ai_error = ""
                    steps.append(
                        self._step(
                            "ai_analysis",
                            "skipped",
                            "没有命中监测词的候选内容，跳过模型调用",
                        )
                    )
            else:
                steps.append(
                    self._step(
                        "ai_analysis",
                        "skipped",
                        "模型未配置，使用规则引擎",
                    )
                )

            for item, analysis in analyzed_items:
                database.upsert_item(item, analysis)

            alert_candidates = [
                {**item, **analysis}
                for item, analysis in analyzed_items
                if analysis.get("alert")
            ]
            created_alerts = database.record_alert_candidates(run_id, alert_candidates)
            notification_result = self.notifier.notify(
                created_alerts,
                run_id,
                COVERAGE_NOTE,
            )
            created_ids = [alert.get("item_id") for alert in created_alerts]
            eligible_ids = notification_result.get("eligible_item_ids", [])
            if notification_result.get("status") == "sent":
                database.update_alert_delivery(eligible_ids, "sent")
                remaining = [item_id for item_id in created_ids if item_id not in eligible_ids]
                database.update_alert_delivery(remaining, "skipped", "低于告警阈值")
            elif notification_result.get("status") == "failed":
                database.update_alert_delivery(
                    eligible_ids,
                    "failed",
                    "; ".join(notification_result.get("errors", [])),
                )
                remaining = [item_id for item_id in created_ids if item_id not in eligible_ids]
                database.update_alert_delivery(remaining, "skipped", "低于告警阈值")
            else:
                database.update_alert_delivery(
                    created_ids,
                    "skipped",
                    "未配置Webhook或邮件告警通道",
                )

            steps.append(
                self._step(
                    "alert_delivery",
                    (
                        "completed"
                        if notification_result.get("status") == "sent"
                        else "partial"
                        if notification_result.get("status") == "failed"
                        else "skipped"
                    ),
                    f"新增 {len(created_alerts)} 条告警候选；送达状态：{notification_result.get('status')}",
                    notification_result,
                )
            )
            steps.append(
                self._step(
                    "persist",
                    "completed",
                    f"已持久化 {len(analyzed_items)} 条信号和 {len(created_alerts)} 条告警候选",
                )
            )

            inserted = len(analyzed_items)
            self._last_finished_at = utc_now()
            self._last_error = "; ".join(
                f"{SOURCE_NAMES.get(source_id, source_id)}: {message}"
                for source_id, message in errors.items()
            )
            duration_seconds = round(time.monotonic() - started_monotonic, 3)
            final_status = "completed" if not errors else "partial"
            alert_count = sum(1 for _, analysis in analyzed_items if analysis.get("alert"))
            metrics = {
                "duration_seconds": duration_seconds,
                "sources_ok": len(results),
                "sources_failed": len(errors),
                "items_fetched": inserted,
                "items_matched": matched_count,
                "alerts": alert_count,
                "new_alert_candidates": len(created_alerts),
                "ai_enriched": ai_enriched,
                "notification_status": notification_result.get("status"),
            }
            database.update_agent_run(
                run_id,
                status=final_status,
                steps=steps,
                metrics=metrics,
                error=self._last_error,
                finish=True,
            )
            return {
                "status": "ok" if not errors else "partial",
                "run_id": run_id,
                "trigger": trigger,
                "started_at": started_at,
                "finished_at": self._last_finished_at,
                "items": inserted,
                "sources_ok": len(results),
                "sources_failed": len(errors),
                "errors": errors,
                "ai_enabled": self.ai_client.enabled,
                "ai_enriched": ai_enriched,
                "ai_error": self._last_ai_error,
                "notifications": notification_result,
                "metrics": metrics,
            }
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            steps.append(self._step("fatal_error", "failed", message))
            if run_id:
                database.update_agent_run(
                    run_id,
                    status="failed",
                    steps=steps,
                    error=message,
                    finish=True,
                )
            raise
        finally:
            self._scan_lock.release()

    @staticmethod
    def _step(
        name: str,
        status: str,
        summary: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "name": name,
            "status": status,
            "summary": summary,
            "details": details or {},
            "at": utc_now(),
        }

    def review_items(self, item_ids: Iterable[str], status: str, note: str = "") -> int:
        return database.review_items(item_ids, status, note)

    def get_agent_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        return database.fetch_agent_run(run_id)

    def _source_state(self) -> List[Dict[str, Any]]:
        latest = database.latest_source_runs()
        states: List[Dict[str, Any]] = []
        for source in SOURCE_CATALOG:
            state = dict(source)
            run = latest.get(source["id"])
            if not run:
                state.update(
                    {
                        "runtime_status": "idle",
                        "last_run_at": None,
                        "item_count": 0,
                        "error": "",
                    }
                )
            else:
                state.update(
                    {
                        "runtime_status": run.get("status", "idle"),
                        "last_run_at": run.get("finished_at") or run.get("started_at"),
                        "item_count": run.get("item_count", 0),
                        "error": run.get("error", ""),
                    }
                )
            states.append(state)

        for source in AUTH_REQUIRED_SOURCES:
            state = dict(source)
            credential = credential_summary(source["id"])
            state["credential"] = credential
            run = latest.get(source["id"])
            if run:
                state.update(
                    {
                        "runtime_status": run.get("status", "idle"),
                        "last_run_at": run.get("finished_at") or run.get("started_at"),
                        "item_count": run.get("item_count", 0),
                        "error": run.get("error", ""),
                    }
                )
            elif credential.get("configured") and credential.get("endpoint"):
                state.update(
                    {
                        "runtime_status": "authorized_unverified",
                        "last_run_at": credential.get("updated_at"),
                        "item_count": 0,
                        "error": "授权与接口已配置，等待下一次扫描验证",
                    }
                )
            else:
                state.update(
                    {
                        "runtime_status": "needs_auth",
                        "last_run_at": credential.get("updated_at"),
                        "item_count": 0,
                        "error": (
                            "已保存凭据，但未配置可调用的数据接口地址"
                            if credential.get("configured")
                            else "需要用户或供应商授权"
                        ),
                    }
                )
            states.append(state)
        return states

    def state(self) -> Dict[str, Any]:
        terms = database.get_watch_terms()
        items = database.fetch_recent_items(limit=500)
        for item in items:
            item.pop("raw_json", None)
        events = cluster_items(items)
        for event in events:
            for item in event["items"]:
                item.pop("raw_json", None)

        matched_items = [item for item in items if item.get("is_relevant")]
        alert_items = [item for item in items if item.get("alert")]
        high_risk_items = [item for item in items if item.get("risk_level") == "high"]
        pending_items = [
            item
            for item in items
            if item.get("review_status") in {"new", "reviewing"}
        ]
        source_states = self._source_state()
        public_sources = [
            state for state in source_states if not state.get("auth_required")
        ]
        auth_sources = [
            state for state in source_states if state.get("auth_required")
        ]
        source_ok = sum(
            1 for source in public_sources if source.get("runtime_status") == "ok"
        )
        last_success = database.last_successful_scan()
        return {
            "generated_at": utc_now(),
            "watch_terms": terms,
            "stats": {
                "items": len(items),
                "matched_items": len(matched_items),
                "alert_items": len(alert_items),
                "high_risk_items": len(high_risk_items),
                "pending_items": len(pending_items),
                "events": len(events),
                "sources_ok": source_ok,
                "sources_total": len(public_sources),
                "auth_pending": sum(
                    1
                    for source in auth_sources
                    if source.get("runtime_status") != "ok"
                ),
            },
            "scanner": {
                "running": self.running,
                "interval_seconds": SCAN_INTERVAL_SECONDS,
                "last_finished_at": self._last_finished_at or last_success,
                "last_error": self._last_error,
            },
            "ai": {
                **self.ai_client.public_status(),
                "last_error": self._last_ai_error,
            },
            "notifications": self.notifier.public_status(),
            "agent_runs": database.fetch_agent_runs(20),
            "recent_alerts": database.recent_alerts(20),
            "sources": source_states,
            "public_sources": public_sources,
            "auth_sources": auth_sources,
            "events": events,
            "items": items,
            "coverage_note": COVERAGE_NOTE,
        }

    def event_report(self, event_id: str) -> Optional[Dict[str, str]]:
        state = self.state()
        event = next((item for item in state["events"] if item["id"] == event_id), None)
        if not event:
            return None
        ai_item = next(
            (item for item in event["items"] if item.get("ai")), None
        )
        lines = [
            f"# {event.get('title', '舆情事件报告')}",
            "",
            f"- 生成时间：{state['generated_at']}",
            f"- 风险等级：{event.get('risk_level', 'low')}",
            f"- 监测命中：{'、'.join(event.get('matched_terms') or []) or '无'}",
            f"- 涉及来源：{'、'.join(SOURCE_NAMES.get(value, value) for value in event.get('sources', []))}",
            f"- 首次发现：{event.get('first_seen', '')}",
            f"- 最近更新：{event.get('last_seen', '')}",
            f"- 人工状态：{event.get('review_status', 'new')}",
            "",
            "## 事件摘要",
            "",
            event.get("summary") or "暂无摘要。",
            "",
            "## 规则研判",
            "",
        ]
        reasons = event.get("risk_reasons") or []
        lines.extend([f"- {reason}" for reason in reasons] or ["- 未命中明显风险词"])
        if ai_item:
            ai = ai_item.get("ai", {})
            lines.extend(
                [
                    "",
                    "## AI 辅助研判",
                    "",
                    ai.get("summary") or "模型未提供摘要。",
                    "",
                    f"- 模型风险等级：{ai.get('risk_level', 'low')}",
                    f"- 信息类型：{ai.get('claim_type', 'unverified')}",
                    f"- 置信度：{ai.get('confidence', 0)}",
                ]
            )
            for reason in ai.get("risk_reasons") or []:
                lines.append(f"- AI 原因：{reason}")
            for question in ai.get("verification_questions") or []:
                lines.append(f"- 待核查：{question}")
        lines.extend(["", "## 证据链", ""])
        for index, item in enumerate(event.get("items", []), start=1):
            lines.extend(
                [
                    f"### {index}. {item.get('title', '')}",
                    "",
                    f"- 来源：{SOURCE_NAMES.get(item.get('source'), item.get('source'))}",
                    f"- 作者：{item.get('author') or '未知'}",
                    f"- 榜单：{item.get('rank') or '不适用'}",
                    f"- 热度：{item.get('hot_value') or '不适用'}",
                    f"- 发布时间：{item.get('published_at') or '未提供'}",
                    f"- 首次采集：{item.get('first_seen_at') or item.get('fetched_at')}",
                    f"- 原文链接：{item.get('url', '')}",
                    "",
                ]
            )
        lines.extend(
            [
                "## 覆盖说明",
                "",
                COVERAGE_NOTE,
                "",
                "> 本报告由规则引擎和可选模型辅助生成，不构成事实认定、法律意见或公关决策。",
            ]
        )
        safe_id = re.sub(r"[^A-Za-z0-9_-]+", "-", event_id)[:80]
        return {
            "filename": f"signalwatch-{safe_id}.md",
            "content": "\n".join(lines),
        }

    def health(self) -> Dict[str, Any]:
        return {
            "status": "ok",
            "running": self.running,
            "database": str(database.DB_PATH),
            "last_scan_finished_at": self._last_finished_at
            or database.last_successful_scan(),
            "last_error": self._last_error,
            "ai": {
                **self.ai_client.public_status(),
                "last_error": self._last_ai_error,
            },
            "notifications": self.notifier.public_status(),
        }
