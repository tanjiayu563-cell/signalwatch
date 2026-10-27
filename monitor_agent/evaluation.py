import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .ai import AIClient, merge_ai_result
from .analyzer import analyze_item


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_cases(path: Path) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            case = json.loads(text)
            if not isinstance(case, dict) or not case.get("id") or not case.get("item"):
                raise ValueError(f"评测数据第 {line_number} 行格式不正确")
            cases.append(case)
    return cases


def predict_cases(
    cases: List[Dict[str, Any]], ai_client: Optional[AIClient] = None
) -> List[Dict[str, Any]]:
    predictions: List[Dict[str, Any]] = []
    for case in cases:
        analysis = analyze_item(case["item"], case.get("watch_terms", []))
        predictions.append(
            {
                "case_id": case["id"],
                "analysis": analysis,
                "ai_applied": False,
            }
        )

    if ai_client and ai_client.enabled:
        candidates = []
        prediction_map = {}
        for index, (case, prediction) in enumerate(zip(cases, predictions)):
            analysis = prediction["analysis"]
            if analysis.get("is_relevant") and analysis.get("matched_terms"):
                item = dict(case["item"])
                item["id"] = case["id"]
                item["fetched_at"] = utc_now()
                candidates.append(item)
                prediction_map[case["id"]] = index

        for start in range(0, len(candidates), ai_client.max_items):
            batch = candidates[start : start + ai_client.max_items]
            terms = []
            for item in batch:
                case = next(case for case in cases if case["id"] == item["id"])
                for term in case.get("watch_terms", []):
                    if term not in terms:
                        terms.append(term)
            result = ai_client.analyze(batch, terms)
            if not result.ok:
                raise RuntimeError(f"模型评测失败：{result.error}")
            for item in batch:
                ai_result = result.results.get(item["id"])
                if not ai_result:
                    continue
                index = prediction_map[item["id"]]
                predictions[index]["analysis"] = merge_ai_result(
                    predictions[index]["analysis"], ai_result
                )
                predictions[index]["ai_applied"] = True
    return predictions


def _confusion(pairs: Iterable[Tuple[bool, bool]]) -> Dict[str, int]:
    tp = fp = fn = tn = 0
    for expected, predicted in pairs:
        if expected and predicted:
            tp += 1
        elif expected and not predicted:
            fn += 1
        elif not expected and predicted:
            fp += 1
        else:
            tn += 1
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def _ratio(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def metrics_for_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {
            "cases": 0,
            "relevance_accuracy": 0.0,
            "risk_accuracy": 0.0,
            "alert_precision": 0.0,
            "alert_recall": 0.0,
            "alert_f1": 0.0,
            "alert_accuracy": 0.0,
            "confusion": {"tp": 0, "fp": 0, "fn": 0, "tn": 0},
        }
    relevance_correct = sum(1 for row in rows if row["relevance_correct"])
    risk_correct = sum(1 for row in rows if row["risk_correct"])
    confusion = _confusion(
        (bool(row["expected"]["alert"]), bool(row["predicted"]["alert"]))
        for row in rows
    )
    precision = _ratio(confusion["tp"], confusion["tp"] + confusion["fp"])
    recall = _ratio(confusion["tp"], confusion["tp"] + confusion["fn"])
    f1 = _ratio(2 * precision * recall, precision + recall)
    alert_accuracy = _ratio(
        confusion["tp"] + confusion["tn"], len(rows)
    )
    return {
        "cases": len(rows),
        "relevance_accuracy": round(relevance_correct / len(rows), 4),
        "risk_accuracy": round(risk_correct / len(rows), 4),
        "alert_precision": precision,
        "alert_recall": recall,
        "alert_f1": f1,
        "alert_accuracy": alert_accuracy,
        "confusion": confusion,
    }


def build_results(
    cases: List[Dict[str, Any]], predictions: List[Dict[str, Any]]
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for case, prediction in zip(cases, predictions):
        analysis = prediction["analysis"]
        expected = case["expected"]
        predicted = {
            "is_relevant": bool(analysis.get("is_relevant")),
            "risk_level": analysis.get("risk_level", "low"),
            "alert": bool(analysis.get("alert")),
            "matched_terms": analysis.get("matched_terms", []),
            "risk_reasons": analysis.get("risk_reasons", []),
        }
        rows.append(
            {
                "case_id": case["id"],
                "scenario": case.get("scenario", ""),
                "tags": case.get("tags", []),
                "expected": expected,
                "predicted": predicted,
                "relevance_correct": expected["is_relevant"] == predicted["is_relevant"],
                "risk_correct": expected["risk_level"] == predicted["risk_level"],
                "alert_correct": expected["alert"] == predicted["alert"],
                "ai_applied": prediction.get("ai_applied", False),
                "ai": analysis.get("ai", {}),
                "risk_reasons": analysis.get("risk_reasons", []),
            }
        )

    tags = sorted({tag for row in rows for tag in row["tags"]})
    by_tag = {
        tag: metrics_for_rows([row for row in rows if tag in row["tags"]])
        for tag in tags
    }
    rule_regression = [
        row for row in rows if "rule_regression" in row.get("tags", [])
    ]
    ai_required = [row for row in rows if "ai_required" in row.get("tags", [])]
    failures = [
        row
        for row in rows
        if not (
            row["relevance_correct"]
            and row["risk_correct"]
            and row["alert_correct"]
        )
    ]
    return {
        "generated_at": utc_now(),
        "dataset_note": (
            "该数据集是合成回归集，用于发现规则和模型链路退化，不代表真实业务准确率。"
            "真实准确率需要使用客户历史事件和人工标注集重新评估。"
        ),
        "overall": metrics_for_rows(rows),
        "rule_regression": metrics_for_rows(rule_regression),
        "ai_required": metrics_for_rows(ai_required),
        "by_tag": by_tag,
        "failures": failures,
        "rows": rows,
    }


def render_markdown(report: Dict[str, Any], mode: str, model: str = "") -> str:
    overall = report["overall"]
    confusion = overall["confusion"]
    lines = [
        "# SignalWatch 评测报告",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 运行模式：{mode}" + (f"（{model}）" if model else ""),
        f"- 样本数：{overall['cases']}",
        "",
        "> " + report["dataset_note"],
        "",
        "## 总体指标",
        "",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| 相关性准确率 | {overall['relevance_accuracy']:.2%} |",
        f"| 风险等级准确率 | {overall['risk_accuracy']:.2%} |",
        f"| 告警准确率 | {overall['alert_accuracy']:.2%} |",
        f"| 告警精确率 | {overall['alert_precision']:.2%} |",
        f"| 告警召回率 | {overall['alert_recall']:.2%} |",
        f"| 告警 F1 | {overall['alert_f1']:.2%} |",
        "",
        "## 告警混淆矩阵",
        "",
        "| | 预测告警 | 预测不告警 |",
        "|---|---:|---:|",
        f"| 实际告警 | {confusion['tp']} | {confusion['fn']} |",
        f"| 实际不告警 | {confusion['fp']} | {confusion['tn']} |",
        "",
        "## 分组指标",
        "",
        "| 分组 | 样本 | 相关性准确率 | 风险准确率 | 告警精确率 | 告警召回率 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    groups = {
        "rule_regression": report["rule_regression"],
        "ai_required": report["ai_required"],
        **{f"tag:{tag}": value for tag, value in report["by_tag"].items()},
    }
    for name, metrics in groups.items():
        lines.append(
            f"| {name} | {metrics['cases']} | {metrics['relevance_accuracy']:.2%} | "
            f"{metrics['risk_accuracy']:.2%} | {metrics['alert_precision']:.2%} | "
            f"{metrics['alert_recall']:.2%} |"
        )
    lines.extend(["", "## 未通过案例", ""])
    if not report["failures"]:
        lines.append("全部案例通过。")
    else:
        for row in report["failures"]:
            lines.extend(
                [
                    f"### {row['case_id']} · {row['scenario']}",
                    "",
                    f"- 标签：{', '.join(row['tags'])}",
                    f"- 预期：relevance={row['expected']['is_relevant']}, "
                    f"risk={row['expected']['risk_level']}, alert={row['expected']['alert']}",
                    f"- 实际：relevance={row['predicted']['is_relevant']}, "
                    f"risk={row['predicted']['risk_level']}, alert={row['predicted']['alert']}",
                    f"- 匹配词：{'、'.join(row['predicted']['matched_terms']) or '无'}",
                    "",
                ]
            )
    lines.extend(
        [
            "## 解释边界",
            "",
            "- 本报告不是线上真实准确率。",
            "- 合成样本只用于回归检查，必须补充真实历史事件和人工双标数据。",
            "- 告警阈值、模型和规则版本变化后必须重新运行。",
        ]
    )
    return "\n".join(lines) + "\n"
