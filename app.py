#!/usr/bin/env python3
import argparse
import json
import mimetypes
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, unquote, urlparse

from monitor_agent.config import DB_PATH, HOST, PORT, SCAN_INTERVAL_SECONDS
from monitor_agent.database import init_db
from monitor_agent.service import MonitorService


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
MAX_BODY_BYTES = 1_000_000


class MonitorHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, service: MonitorService):
        super().__init__(address, handler)
        self.service = service


class Handler(BaseHTTPRequestHandler):
    server: MonitorHTTPServer

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[http] {self.address_string()} {fmt % args}")

    def _send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _error(self, status: int, message: str) -> None:
        self._send_json({"error": message}, status=status)

    def _send_download(self, filename: str, content: str) -> None:
        body = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/markdown; charset=utf-8")
        self.send_header(
            "Content-Disposition", f"attachment; filename*=UTF-8''{filename}"
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("请求体不是有效 JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return payload

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/state":
            self._send_json(self.server.service.state())
            return
        if path == "/api/health":
            self._send_json(self.server.service.health())
            return
        if path.startswith("/api/runs/"):
            run_id = path[len("/api/runs/") :]
            run = self.server.service.get_agent_run(run_id)
            if not run:
                self._error(404, "未找到该运行记录")
            else:
                self._send_json(run)
            return
        if path == "/api/reports/event":
            event_id = parse_qs(urlparse(self.path).query).get("event_id", [""])[0]
            report = self.server.service.event_report(event_id)
            if not report:
                self._error(404, "未找到该事件")
            else:
                self._send_download(report["filename"], report["content"])
            return
        if path in {"/", "/index.html"}:
            self._serve_static("index.html")
            return
        if path.startswith("/static/"):
            self._serve_static(path[len("/static/") :])
            return
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        self._error(404, "未找到该页面")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
            if path == "/api/scan":
                trigger = str(payload.get("trigger") or "manual")[:40]
                self._send_json(self.server.service.scan(trigger=trigger))
                return
            if path == "/api/watch-terms":
                terms = self.server.service.set_watch_terms(payload.get("terms", []))
                self._send_json({"ok": True, "terms": terms})
                return
            if path == "/api/authorize":
                source_id = str(payload.get("source_id") or "")
                auth_type = str(payload.get("auth_type") or "")
                secret = str(payload.get("secret") or "")
                endpoint = str(payload.get("endpoint") or "")
                self.server.service.authorize_source(
                    source_id, auth_type, secret, endpoint
                )
                self._send_json(
                    {
                        "ok": True,
                        "message": "授权凭据已保存在本机。当前连接器仍需通过可用性验证。",
                    }
                )
                return
            if path == "/api/authorize/revoke":
                removed = self.server.service.revoke_source(
                    str(payload.get("source_id") or "")
                )
                self._send_json({"ok": True, "removed": removed})
                return
            if path == "/api/reviews":
                item_ids = payload.get("item_ids") or []
                status = str(payload.get("status") or "")
                note = str(payload.get("note") or "")
                if not isinstance(item_ids, list):
                    raise ValueError("item_ids 必须是数组")
                count = self.server.service.review_items(item_ids, status, note)
                self._send_json({"ok": True, "updated": count})
                return
            self._error(404, "未找到该接口")
        except ValueError as exc:
            self._error(400, str(exc))
        except Exception as exc:
            print(f"[error] {type(exc).__name__}: {exc}")
            self._error(500, "服务处理失败，请查看终端日志")

    def _serve_static(self, relative_path: str) -> None:
        requested = unquote(relative_path)
        target = (STATIC_DIR / requested).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self._error(403, "禁止访问")
            return
        if not target.is_file():
            self._error(404, "静态文件不存在")
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") or content_type.endswith("javascript") or content_type.endswith("json") else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return


def scheduler(service: MonitorService, stop_event: threading.Event, initial_scan: bool) -> None:
    if initial_scan:
        stop_event.wait(1.5)
        if not stop_event.is_set():
            try:
                result = service.scan(trigger="startup")
                print(f"[scan] initial scan: {json.dumps(result, ensure_ascii=False)}")
            except Exception as exc:
                print(f"[scan] initial scan failed: {exc}")
    while not stop_event.wait(SCAN_INTERVAL_SECONDS):
        try:
            result = service.scan(trigger="scheduled")
            print(f"[scan] scheduled scan: {json.dumps(result, ensure_ascii=False)}")
        except Exception as exc:
            print(f"[scan] scheduled scan failed: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="公开舆情监测 Agent MVP")
    parser.add_argument("--scan-once", action="store_true", help="只执行一次采集后退出")
    parser.add_argument("--no-initial-scan", action="store_true", help="启动时不自动扫描")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    init_db()
    service = MonitorService()
    if args.scan_once:
        print(json.dumps(service.scan(trigger="cli"), ensure_ascii=False, indent=2))
        return

    stop_event = threading.Event()
    scan_thread = threading.Thread(
        target=scheduler,
        args=(service, stop_event, not args.no_initial_scan),
        name="monitor-scheduler",
        daemon=True,
    )
    scan_thread.start()

    server = MonitorHTTPServer((args.host, args.port), Handler, service)
    print(f"舆情雷达已启动：http://{args.host}:{args.port}")
    print(f"数据库：{DB_PATH}")
    print(f"自动扫描间隔：{SCAN_INTERVAL_SECONDS} 秒")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止服务…")
    finally:
        stop_event.set()
        server.server_close()


if __name__ == "__main__":
    main()
