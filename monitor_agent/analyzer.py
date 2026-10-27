import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Tuple


RISK_RULES: List[Tuple[str, str, List[str]]] = [
    (
        "人身与安全",
        "critical",
        [
            "死亡",
            "遇难",
            "身亡",
            "受伤",
            "失联",
            "爆炸",
            "起火",
            "火灾",
            "坍塌",
            "中毒",
            "袭击",
            "坠亡",
            "事故",
            "伤亡",
        ],
    ),
    (
        "产品与消费者",
        "high",
        [
            "召回",
            "质量问题",
            "安全隐患",
            "投诉",
            "维权",
            "退款",
            "退费",
            "虚假宣传",
            "欺诈",
            "食安",
            "食品安全",
        ],
    ),
    (
        "法律与监管",
        "high",
        [
            "违法",
            "犯罪",
            "调查",
            "处罚",
            "罚款",
            "起诉",
            "判决",
            "拘留",
            "逮捕",
            "立案",
            "监管",
            "约谈",
            "整改",
            "封禁",
            "下架",
            "泄露",
        ],
    ),
    (
        "声誉与传播",
        "medium",
        [
            "抵制",
            "翻车",
            "塌房",
            "造假",
            "解约",
            "终止合作",
            "黑幕",
            "网暴",
            "危机",
            "舆情",
        ],
    ),
    (
        "舆情弱信号",
        "weak",
        [
            "争议",
            "谣言",
            "辟谣",
            "道歉",
            "回应",
        ],
    ),
    (
        "政策与宏观",
        "policy",
        [
            "政策",
            "新规",
            "条例",
            "通知",
            "国务院",
            "中央",
            "部委",
            "监管总局",
            "商务部",
            "网信办",
            "央行",
            "证监会",
            "关税",
        ],
    ),
]

POSITIVE_WORDS = [
    "获奖",
    "突破",
    "增长",
    "创新",
    "首个",
    "成功",
    "夺冠",
    "领先",
    "合作",
    "投资",
    "开工",
    "竣工",
    "表彰",
]

RISK_ORDER = {"high": 3, "medium": 2, "low": 1}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_for_match(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[\s#【】\[\]（）()《》<>\"'“”‘’、，。,.!?！？:：;；/\\|_\-]+", "", text)
    return text


def match_terms(item: Dict[str, Any], watch_terms: Iterable[str]) -> List[str]:
    haystack = normalize_for_match(
        " ".join(
            [
                str(item.get("title") or ""),
                str(item.get("summary") or ""),
                str(item.get("author") or ""),
            ]
        )
    )
    matched: List[str] = []
    for term in watch_terms:
        needle = normalize_for_match(term)
        if needle and needle in haystack:
            matched.append(term)
    return matched


def detect_risk(text: str) -> Tuple[List[str], List[str]]:
    reasons: List[str] = []
    categories: List[str] = []
    for category, _level, words in RISK_RULES:
        hits = [word for word in words if word.casefold() in text]
        if hits:
            categories.append(category)
            reasons.append(f"{category}：" + "、".join(hits[:4]))
    return categories, reasons[:6]


def analyze_item(item: Dict[str, Any], watch_terms: Iterable[str]) -> Dict[str, Any]:
    terms = list(watch_terms)
    matched = match_terms(item, terms)
    text = " ".join(
        [
            str(item.get("title") or ""),
            str(item.get("summary") or ""),
        ]
    ).casefold()
    categories, reasons = detect_risk(text)

    rank = item.get("rank")
    try:
        rank = int(rank) if rank is not None else None
    except (TypeError, ValueError):
        rank = None

    level_counts = {"critical": 0, "high": 0, "medium": 0, "weak": 0, "policy": 0}
    for _, level, words in RISK_RULES:
        level_counts[level] += sum(1 for word in words if word.casefold() in text)

    if rank is not None and rank <= 10 and any(
        level_counts[name] for name in ("critical", "high", "medium", "weak", "policy")
    ):
        reasons.append(f"热榜高位：第 {rank} 位")

    if level_counts["critical"] >= 2 or (
        level_counts["critical"] >= 1
        and (level_counts["high"] >= 1 or (rank is not None and rank <= 20))
    ):
        risk_level = "high"
    elif level_counts["critical"] >= 1 or level_counts["high"] >= 1:
        risk_level = "medium"
    elif level_counts["medium"] >= 1:
        risk_level = "medium"
    elif level_counts["weak"] >= 2 or (
        level_counts["weak"] >= 1 and rank is not None and rank <= 20
    ):
        risk_level = "medium"
    elif level_counts["policy"] >= 1 and rank is not None and rank <= 20:
        risk_level = "medium"
    else:
        risk_level = "low"

    negative_hits = any(
        word.casefold() in text
        for _, level, words in RISK_RULES
        if level != "policy"
        for word in words
    )
    positive_hits = any(word.casefold() in text for word in POSITIVE_WORDS)
    if negative_hits:
        sentiment = "negative"
    elif positive_hits:
        sentiment = "positive"
    else:
        sentiment = "neutral"

    if terms:
        is_relevant = bool(matched)
    else:
        is_relevant = True
    alert = bool(terms and matched and risk_level in {"high", "medium"})

    return {
        "matched_terms": matched,
        "risk_level": risk_level,
        "risk_reasons": reasons,
        "risk_categories": categories,
        "sentiment": sentiment,
        "is_relevant": is_relevant,
        "alert": alert,
        "method": "rules-v1",
        "analyzed_at": utc_now(),
    }


def _title_text(item: Dict[str, Any]) -> str:
    return normalize_for_match(item.get("title") or "")


def _ngrams(text: str, n: int = 2) -> set:
    if len(text) <= n:
        return {text} if text else set()
    return {text[index : index + n] for index in range(len(text) - n + 1)}


def title_similarity(left: str, right: str) -> float:
    left_grams = _ngrams(_title_text({"title": left}))
    right_grams = _ngrams(_title_text({"title": right}))
    if not left_grams or not right_grams:
        return 0.0
    return 2 * len(left_grams & right_grams) / (len(left_grams) + len(right_grams))


def _sort_value(item: Dict[str, Any]) -> Tuple[int, int, int]:
    return (
        1 if item.get("alert") else 0,
        RISK_ORDER.get(item.get("risk_level", "low"), 0),
        int(item.get("hot_value") or 0),
    )


def cluster_items(items: List[Dict[str, Any]], threshold: float = 0.38) -> List[Dict[str, Any]]:
    ordered = sorted(items, key=_sort_value, reverse=True)
    groups: List[List[Dict[str, Any]]] = []
    group_terms: List[set] = []

    for item in ordered:
        item_terms = set(item.get("matched_terms") or [])
        best_index = None
        best_similarity = 0.0
        for index, group in enumerate(groups):
            shared_terms = item_terms & group_terms[index]
            if item_terms and group_terms[index] and not shared_terms:
                continue
            similarity = max(
                title_similarity(item.get("title", ""), existing.get("title", ""))
                for existing in group
            )
            if similarity > best_similarity:
                best_similarity = similarity
                best_index = index
        if best_index is not None and best_similarity >= threshold:
            groups[best_index].append(item)
            group_terms[best_index].update(item_terms)
        else:
            groups.append([item])
            group_terms.append(set(item_terms))

    events: List[Dict[str, Any]] = []
    for group in groups:
        group.sort(key=_sort_value, reverse=True)
        lead = group[0]
        reasons: List[str] = []
        terms: List[str] = []
        for item in group:
            for reason in item.get("risk_reasons") or []:
                if reason not in reasons:
                    reasons.append(reason)
            for term in item.get("matched_terms") or []:
                if term not in terms:
                    terms.append(term)
        risk_level = max(
            (item.get("risk_level", "low") for item in group),
            key=lambda value: RISK_ORDER.get(value, 0),
        )
        sources = list(dict.fromkeys(item.get("source", "") for item in group))
        events.append(
            {
                "id": "event:" + lead["id"],
                "title": lead.get("title", ""),
                "summary": lead.get("summary", ""),
                "risk_level": risk_level,
                "risk_reasons": reasons[:8],
                "sentiment": lead.get("sentiment", "neutral"),
                "matched_terms": terms,
                "sources": sources,
                "item_count": len(group),
                "item_ids": [item["id"] for item in group],
                "first_seen": min(
                    (item.get("published_at") or item.get("first_seen_at") or item.get("fetched_at") or "" for item in group),
                    default="",
                ),
                "last_seen": max(
                    (item.get("fetched_at") or item.get("published_at") or "" for item in group),
                    default="",
                ),
                "alert": any(bool(item.get("alert")) for item in group),
                "review_status": _group_review_status(group),
                "items": group,
            }
        )
    return sorted(
        events,
        key=lambda event: (
            1 if event["alert"] else 0,
            RISK_ORDER.get(event["risk_level"], 0),
            event["last_seen"],
            event["item_count"],
        ),
        reverse=True,
    )


def _group_review_status(group: List[Dict[str, Any]]) -> str:
    statuses = {item.get("review_status", "new") for item in group}
    for value in ("reviewing", "new", "false_positive", "closed"):
        if value in statuses:
            return value
    return "new"
