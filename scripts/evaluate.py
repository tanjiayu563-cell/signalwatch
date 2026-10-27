#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from monitor_agent.ai import AIClient
from monitor_agent.evaluation import build_results, load_cases, predict_cases, render_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 SignalWatch 合成回归评测")
    parser.add_argument("--dataset", default=str(ROOT / "eval" / "cases.jsonl"))
    parser.add_argument("--output-dir", default=str(ROOT / "outputs"))
    parser.add_argument("--use-ai", action="store_true", help="使用环境变量配置的模型")
    args = parser.parse_args()

    cases = load_cases(Path(args.dataset))
    ai_client = AIClient.from_env() if args.use_ai else None
    if args.use_ai and not ai_client.enabled:
        raise SystemExit("已指定 --use-ai，但未配置 MONITOR_AI_BASE_URL 和 MONITOR_AI_MODEL")
    predictions = predict_cases(cases, ai_client)
    report = build_results(cases, predictions)
    mode = "规则 + AI" if ai_client and ai_client.enabled else "规则引擎"
    model = ai_client.model if ai_client and ai_client.enabled else ""
    report.update({"mode": mode, "model": model})

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "evaluation-report.json"
    md_path = output_dir / "evaluation-report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report, mode, model), encoding="utf-8")

    overall = report["overall"]
    print(json.dumps({
        "mode": mode,
        "cases": overall["cases"],
        "relevance_accuracy": overall["relevance_accuracy"],
        "risk_accuracy": overall["risk_accuracy"],
        "alert_precision": overall["alert_precision"],
        "alert_recall": overall["alert_recall"],
        "alert_f1": overall["alert_f1"],
        "failures": len(report["failures"]),
        "json_report": str(json_path),
        "markdown_report": str(md_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
