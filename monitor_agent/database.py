import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from .config import DB_PATH


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS watch_terms (
                term TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS items (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                external_id TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                author TEXT NOT NULL DEFAULT '',
                published_at TEXT,
                first_seen_at TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                rank INTEGER,
                hot_value INTEGER,
                raw_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(source, external_id)
            );

            CREATE INDEX IF NOT EXISTS idx_items_fetched_at
                ON items(fetched_at DESC);
            CREATE INDEX IF NOT EXISTS idx_items_source
                ON items(source);

            CREATE TABLE IF NOT EXISTS analyses (
                item_id TEXT PRIMARY KEY,
                matched_terms TEXT NOT NULL DEFAULT '[]',
                risk_level TEXT NOT NULL DEFAULT 'low',
                risk_reasons TEXT NOT NULL DEFAULT '[]',
                sentiment TEXT NOT NULL DEFAULT 'neutral',
                is_relevant INTEGER NOT NULL DEFAULT 0,
                alert INTEGER NOT NULL DEFAULT 0,
                method TEXT NOT NULL DEFAULT 'rules-v1',
                ai_json TEXT NOT NULL DEFAULT '{}',
                analyzed_at TEXT NOT NULL,
                FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS source_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                item_count INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_source_runs_source
                ON source_runs(source, id DESC);

            CREATE TABLE IF NOT EXISTS reviews (
                item_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'new',
                note TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS agent_runs (
                id TEXT PRIMARY KEY,
                trigger TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                watch_terms TEXT NOT NULL DEFAULT '[]',
                plan_json TEXT NOT NULL DEFAULT '{}',
                steps_json TEXT NOT NULL DEFAULT '[]',
                metrics_json TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_agent_runs_started
                ON agent_runs(started_at DESC);

            CREATE TABLE IF NOT EXISTS alert_deliveries (
                item_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                title TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                delivery_status TEXT NOT NULL DEFAULT 'pending',
                delivery_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                delivered_at TEXT,
                FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_alert_deliveries_created
                ON alert_deliveries(created_at DESC);
            """
        )
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(items)").fetchall()
        }
        if "first_seen_at" not in columns:
            conn.execute("ALTER TABLE items ADD COLUMN first_seen_at TEXT")
        conn.execute(
            "UPDATE items SET first_seen_at = fetched_at WHERE first_seen_at IS NULL"
        )
        analysis_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(analyses)").fetchall()
        }
        if "ai_json" not in analysis_columns:
            conn.execute(
                "ALTER TABLE analyses ADD COLUMN ai_json TEXT NOT NULL DEFAULT '{}'"
            )


def get_watch_terms() -> List[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT term FROM watch_terms ORDER BY created_at ASC, term ASC"
        ).fetchall()
    return [row["term"] for row in rows]


def set_watch_terms(terms: Iterable[str]) -> List[str]:
    clean: List[str] = []
    seen = set()
    for term in terms:
        value = str(term).strip()
        key = value.casefold()
        if value and key not in seen:
            clean.append(value[:60])
            seen.add(key)

    with connect() as conn:
        conn.execute("DELETE FROM watch_terms")
        conn.executemany(
            "INSERT INTO watch_terms(term, created_at) VALUES (?, ?)",
            [(term, utc_now()) for term in clean],
        )
    return clean


def start_source_run(source: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO source_runs(source, status, started_at) VALUES (?, 'running', ?)",
            (source, utc_now()),
        )
        return int(cur.lastrowid)


def finish_source_run(
    run_id: int, status: str, item_count: int = 0, error: str = ""
) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE source_runs
            SET status = ?, finished_at = ?, item_count = ?, error = ?
            WHERE id = ?
            """,
            (status, utc_now(), item_count, error[:1000], run_id),
        )


def upsert_item(item: Dict[str, Any], analysis: Dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO items(
                id, source, external_id, title, url, summary, author,
                published_at, first_seen_at, fetched_at, rank, hot_value, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, external_id) DO UPDATE SET
                title = excluded.title,
                url = excluded.url,
                summary = excluded.summary,
                author = excluded.author,
                published_at = excluded.published_at,
                fetched_at = excluded.fetched_at,
                rank = excluded.rank,
                hot_value = excluded.hot_value,
                raw_json = excluded.raw_json
            """,
            (
                item["id"],
                item["source"],
                item["external_id"],
                item["title"],
                item["url"],
                item.get("summary", ""),
                item.get("author", ""),
                item.get("published_at"),
                item.get("first_seen_at") or item["fetched_at"],
                item["fetched_at"],
                item.get("rank"),
                item.get("hot_value"),
                json.dumps(item.get("raw", {}), ensure_ascii=False),
            ),
        )
        conn.execute(
            """
            INSERT INTO analyses(
                item_id, matched_terms, risk_level, risk_reasons, sentiment,
                is_relevant, alert, method, ai_json, analyzed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_id) DO UPDATE SET
                matched_terms = excluded.matched_terms,
                risk_level = excluded.risk_level,
                risk_reasons = excluded.risk_reasons,
                sentiment = excluded.sentiment,
                is_relevant = excluded.is_relevant,
                alert = excluded.alert,
                method = excluded.method,
                ai_json = excluded.ai_json,
                analyzed_at = excluded.analyzed_at
            """,
            (
                item["id"],
                json.dumps(analysis["matched_terms"], ensure_ascii=False),
                analysis["risk_level"],
                json.dumps(analysis["risk_reasons"], ensure_ascii=False),
                analysis["sentiment"],
                1 if analysis["is_relevant"] else 0,
                1 if analysis["alert"] else 0,
                analysis["method"],
                json.dumps(analysis.get("ai") or {}, ensure_ascii=False),
                analysis["analyzed_at"],
            ),
        )


def fetch_recent_items(limit: int = 400) -> List[Dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                i.*,
                a.matched_terms, a.risk_level, a.risk_reasons, a.sentiment,
                a.is_relevant, a.alert, a.method, a.ai_json, a.analyzed_at,
                COALESCE(r.status, 'new') AS review_status,
                COALESCE(r.note, '') AS review_note
            FROM items i
            JOIN analyses a ON a.item_id = i.id
            LEFT JOIN reviews r ON r.item_id = i.id
            ORDER BY i.fetched_at DESC, i.hot_value DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    result: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["matched_terms"] = json.loads(item["matched_terms"] or "[]")
        item["risk_reasons"] = json.loads(item["risk_reasons"] or "[]")
        item["ai"] = json.loads(item.get("ai_json") or "{}")
        item.pop("ai_json", None)
        item["is_relevant"] = bool(item["is_relevant"])
        item["alert"] = bool(item["alert"])
        item["raw_json"] = json.loads(item["raw_json"] or "{}")
        result.append(item)
    return result


def latest_source_runs() -> Dict[str, Dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT sr.*
            FROM source_runs sr
            JOIN (
                SELECT source, MAX(id) AS max_id
                FROM source_runs
                GROUP BY source
            ) latest ON latest.max_id = sr.id
            """
        ).fetchall()
    return {row["source"]: dict(row) for row in rows}


def review_items(item_ids: Iterable[str], status: str, note: str = "") -> int:
    allowed = {"new", "reviewing", "closed", "false_positive"}
    if status not in allowed:
        raise ValueError("invalid review status")
    ids = list(dict.fromkeys(str(item_id) for item_id in item_ids if item_id))
    if not ids:
        return 0
    now = utc_now()
    with connect() as conn:
        conn.executemany(
            """
            INSERT INTO reviews(item_id, status, note, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(item_id) DO UPDATE SET
                status = excluded.status,
                note = excluded.note,
                updated_at = excluded.updated_at
            """,
            [(item_id, status, note[:500], now) for item_id in ids],
        )
    return len(ids)


def last_successful_scan() -> Optional[str]:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT MAX(finished_at) AS finished_at
            FROM source_runs
            WHERE status = 'ok'
            """
        ).fetchone()
    return row["finished_at"] if row else None


def fetch_items_for_reanalysis(limit: int = 1000) -> List[Dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM items
            ORDER BY fetched_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    result: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["raw"] = json.loads(item.pop("raw_json") or "{}")
        result.append(item)
    return result


def create_agent_run(trigger: str, watch_terms: Iterable[str], plan: Dict[str, Any]) -> str:
    run_id = uuid.uuid4().hex
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO agent_runs(
                id, trigger, status, started_at, watch_terms, plan_json
            ) VALUES (?, ?, 'running', ?, ?, ?)
            """,
            (
                run_id,
                trigger[:40],
                utc_now(),
                json.dumps(list(watch_terms), ensure_ascii=False),
                json.dumps(plan, ensure_ascii=False),
            ),
        )
    return run_id


def update_agent_run(
    run_id: str,
    status: Optional[str] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    metrics: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    finish: bool = False,
) -> None:
    assignments: List[str] = []
    params: List[Any] = []
    if status is not None:
        assignments.append("status = ?")
        params.append(status)
    if steps is not None:
        assignments.append("steps_json = ?")
        params.append(json.dumps(steps, ensure_ascii=False))
    if metrics is not None:
        assignments.append("metrics_json = ?")
        params.append(json.dumps(metrics, ensure_ascii=False))
    if error is not None:
        assignments.append("error = ?")
        params.append(error[:2000])
    if finish:
        assignments.append("finished_at = ?")
        params.append(utc_now())
    if not assignments:
        return
    params.append(run_id)
    with connect() as conn:
        conn.execute(
            f"UPDATE agent_runs SET {', '.join(assignments)} WHERE id = ?",
            params,
        )


def _parse_agent_run(row: sqlite3.Row) -> Dict[str, Any]:
    result = dict(row)
    result["watch_terms"] = json.loads(result.get("watch_terms") or "[]")
    result["plan"] = json.loads(result.pop("plan_json", "{}") or "{}")
    result["steps"] = json.loads(result.pop("steps_json", "[]") or "[]")
    result["metrics"] = json.loads(result.pop("metrics_json", "{}") or "{}")
    return result


def fetch_agent_runs(limit: int = 20) -> List[Dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_runs ORDER BY started_at DESC LIMIT ?",
            (max(1, min(100, limit)),),
        ).fetchall()
    return [_parse_agent_run(row) for row in rows]


def fetch_agent_run(run_id: str) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM agent_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    return _parse_agent_run(row) if row else None


def record_alert_candidates(
    run_id: str,
    items: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    created: List[Dict[str, Any]] = []
    now = utc_now()
    with connect() as conn:
        for item in items:
            payload = {
                "item_id": item.get("id"),
                "source": item.get("source"),
                "title": item.get("title"),
                "url": item.get("url"),
                "summary": item.get("summary"),
                "risk_level": item.get("risk_level"),
                "risk_reasons": item.get("risk_reasons", []),
                "matched_terms": item.get("matched_terms", []),
                "published_at": item.get("published_at"),
                "fetched_at": item.get("fetched_at"),
            }
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO alert_deliveries(
                    item_id, run_id, risk_level, title, payload_json,
                    delivery_status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    item["id"],
                    run_id,
                    item.get("risk_level", "low"),
                    item.get("title", ""),
                    json.dumps(payload, ensure_ascii=False),
                    now,
                ),
            )
            if cur.rowcount:
                created.append(payload)
    return created


def update_alert_delivery(
    item_ids: Iterable[str],
    status: str,
    error: str = "",
) -> None:
    ids = list(dict.fromkeys(str(item_id) for item_id in item_ids if item_id))
    if not ids:
        return
    now = utc_now()
    delivered_at = now if status in {"sent", "skipped"} else None
    placeholders = ",".join("?" for _ in ids)
    with connect() as conn:
        conn.execute(
            f"""
            UPDATE alert_deliveries
            SET delivery_status = ?, delivery_error = ?, delivered_at = ?
            WHERE item_id IN ({placeholders})
            """,
            [status, error[:1000], delivered_at, *ids],
        )


def recent_alerts(limit: int = 50) -> List[Dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM alert_deliveries ORDER BY created_at DESC LIMIT ?",
            (max(1, min(200, limit)),),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        result.append(item)
    return result
