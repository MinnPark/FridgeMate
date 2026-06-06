"""사용자 이력(history) — 개인화의 원천 (기획안: Postgres '사용자 이력').

dev=SQLite(HISTORY_DB_PATH) / prod=Postgres(DATABASE_URL, psycopg 있을 때).
DDL 은 양쪽 호환 표준 SQL. 매 run 종료 시 record_run_history() 호출.

개인화 연계: sync_preferences_from_history() 가 수락 레시피를 user_preference 벡터로 옮김.
docs/data_architecture.md §4.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

_PG = bool(os.getenv("DATABASE_URL"))


def _connect():
    """DATABASE_URL + psycopg 있으면 Postgres, 아니면 SQLite."""
    url = os.getenv("DATABASE_URL")
    if url:
        try:
            import psycopg  # type: ignore
            return ("pg", psycopg.connect(url))
        except Exception:
            pass  # psycopg 미설치 → SQLite 폴백
    path = Path(os.getenv("HISTORY_DB_PATH", "./data/history.sqlite"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return ("sqlite", sqlite3.connect(str(path)))


_DDL = """
CREATE TABLE IF NOT EXISTS run_history (
    id          {pk},
    user_id     TEXT,
    thread_id   TEXT,
    ts          REAL,
    accepted    TEXT,   -- JSON: [{recipe_id, dish_name, embed_text}]
    rejected    TEXT,   -- JSON: [recipe_id ...]
    budget      INTEGER,
    judge_pass  INTEGER,
    raw         TEXT    -- JSON: 요약 스냅샷
)
"""


def _ensure(kind: str, conn) -> None:
    pk = "SERIAL PRIMARY KEY" if kind == "pg" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    conn.execute(_DDL.replace("{pk}", pk))
    if kind == "sqlite":
        conn.commit()


def record_run_history(
    *,
    user_id: str,
    thread_id: str,
    accepted: list[dict],
    rejected: Optional[list[str]] = None,
    budget: int = 0,
    judge_pass: bool = False,
    raw: Optional[dict] = None,
) -> int:
    """한 run 의 이력 적재. accepted=[{recipe_id, dish_name, embed_text}, ...]."""
    kind, conn = _connect()
    try:
        _ensure(kind, conn)
        ph = "%s" if kind == "pg" else "?"
        cols = "user_id, thread_id, ts, accepted, rejected, budget, judge_pass, raw"
        vals = [
            user_id, thread_id, time.time(),
            json.dumps(accepted, ensure_ascii=False),
            json.dumps(rejected or [], ensure_ascii=False),
            int(budget or 0), 1 if judge_pass else 0,
            json.dumps(raw or {}, ensure_ascii=False),
        ]
        sql = f"INSERT INTO run_history ({cols}) VALUES ({','.join([ph]*8)})"
        if kind == "pg":
            sql += " RETURNING id"
            cur = conn.execute(sql, vals)
            rid = cur.fetchone()[0]
            conn.commit()
        else:
            cur = conn.execute(sql, vals)
            conn.commit()
            rid = cur.lastrowid or -1
        return rid
    finally:
        conn.close()


def get_user_history(user_id: str, limit: int = 50) -> list[dict]:
    kind, conn = _connect()
    try:
        _ensure(kind, conn)
        ph = "%s" if kind == "pg" else "?"
        rows = conn.execute(
            f"SELECT user_id, thread_id, ts, accepted, rejected, budget, judge_pass "
            f"FROM run_history WHERE user_id={ph} ORDER BY ts DESC LIMIT {int(limit)}",
            [user_id],
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        out.append({
            "user_id": r[0], "thread_id": r[1], "ts": r[2],
            "accepted": json.loads(r[3] or "[]"), "rejected": json.loads(r[4] or "[]"),
            "budget": r[5], "judge_pass": bool(r[6]),
        })
    return out


async def sync_preferences_from_history(user_id: str) -> dict:
    """이력의 '수락 레시피' → user_preference 벡터로 동기화 (개인화 연계)."""
    from app.rag.preference_store import record_preference

    history = get_user_history(user_id)
    synced = 0
    for run in history:
        if not run["judge_pass"]:
            continue
        for dish in run["accepted"]:
            rid = dish.get("recipe_id")
            text = dish.get("embed_text") or dish.get("dish_name") or ""
            if rid and text:
                await record_preference(user_id, rid, text, accepted=True,
                                        meta={"thread_id": run["thread_id"]})
                synced += 1
    return {"user_id": user_id, "runs": len(history), "preferences_synced": synced}
