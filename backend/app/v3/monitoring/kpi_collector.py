"""KPI 적재 + 집계 — v3 kpi_log 를 실행마다 SQLite 에 쌓고 목표 대비 달성률 산출.

기획안 §6 KPI / project_plan Sprint 4-A 항목. 각 /api/run 완료 시 record_run() 호출.
적재만 담당 — kpi_log 계산은 각 노드가 이미 수행 (이 모듈은 LLM/추정 안 함).

저장소: SQLite (KPI_DB_PATH, 기본 ./data/kpi.sqlite). 단일 테이블 kpi_runs.
목표치: state_schema.md / 기획안 §6 기준.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

# 기획안 §6 KPI 목표 — 집계 시 달성 여부 판정에 사용
KPI_TARGETS = {
    "nutrition_score":   ("gte", 0.90),   # 영양 목표 충족률
    "pantry_coverage":   ("gte", 0.50),   # 재고 활용 (Waste-to-Zero)
    "schedule_match":    ("eq",  1.0),    # 끼니 슬롯 충족
    "budget_compliance": ("rate", 0.95),  # 예산 준수 세션 비율
    "citation_included": ("rate", 1.0),   # citation 포함 비율
    "e2e_success":       ("rate", 0.85),  # 완주율
}

# kpi_log 에서 적재할 수치 필드 (bool 은 0/1 로 저장)
_NUMERIC_FIELDS = (
    "nutrition_score", "pantry_coverage", "schedule_match", "ingredient_coverage",
    "dishes_in_plan", "reflexion_count", "substitutes_used",
    "unit_mismatch_count", "budget_over_pct",
)
_BOOL_FIELDS = ("budget_compliance", "citation_included", "e2e_success")


def _db_path() -> Path:
    p = Path(os.getenv("KPI_DB_PATH", "./data/kpi.sqlite"))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kpi_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT,
            user_id TEXT,
            ts REAL,
            nutrition_score REAL, pantry_coverage REAL, schedule_match REAL,
            ingredient_coverage REAL, dishes_in_plan INTEGER, reflexion_count INTEGER,
            substitutes_used INTEGER, unit_mismatch_count INTEGER, budget_over_pct REAL,
            budget_compliance INTEGER, citation_included INTEGER, e2e_success INTEGER,
            raw_json TEXT
        )
    """)
    return conn


def record_run(*, thread_id: str, user_id: str, kpi_log: dict) -> int:
    """한 번의 실행 KPI 를 적재. 반환: row id. 실패해도 파이프라인 막지 않도록 호출측에서 try."""
    cols = ["thread_id", "user_id", "ts"]
    vals: list = [thread_id, user_id, time.time()]
    for f in _NUMERIC_FIELDS:
        cols.append(f)
        vals.append(kpi_log.get(f, 0) or 0)
    for f in _BOOL_FIELDS:
        cols.append(f)
        vals.append(1 if kpi_log.get(f, False) else 0)
    cols.append("raw_json")
    vals.append(json.dumps(kpi_log, ensure_ascii=False))

    placeholders = ",".join("?" * len(cols))
    conn = _connect()
    try:
        cur = conn.execute(
            f"INSERT INTO kpi_runs ({','.join(cols)}) VALUES ({placeholders})", vals
        )
        conn.commit()
        return cur.lastrowid or -1
    finally:
        conn.close()


def aggregate(limit: int | None = None) -> dict:
    """적재된 실행들의 평균/달성률 + 목표 대비 통과 여부.

    limit: 최근 N건만 (None = 전체).
    """
    conn = _connect()
    try:
        where = ""
        if limit:
            where = f" WHERE id > (SELECT COALESCE(MAX(id),0) FROM kpi_runs) - {int(limit)}"
        rows = conn.execute(f"SELECT * FROM kpi_runs{where}").fetchall()
        col_names = [d[0] for d in conn.execute("SELECT * FROM kpi_runs LIMIT 0").description]
    finally:
        conn.close()

    n = len(rows)
    if n == 0:
        return {"runs": 0, "metrics": {}, "targets_met": {}}

    idx = {c: i for i, c in enumerate(col_names)}

    def avg(field: str) -> float:
        return sum((r[idx[field]] or 0) for r in rows) / n

    def rate(field: str) -> float:
        return sum(1 for r in rows if r[idx[field]]) / n

    metrics = {
        "nutrition_score":     round(avg("nutrition_score"), 3),
        "pantry_coverage":     round(avg("pantry_coverage"), 3),
        "schedule_match":      round(avg("schedule_match"), 3),
        "ingredient_coverage": round(avg("ingredient_coverage"), 3),
        "avg_reflexion":       round(avg("reflexion_count"), 2),
        "avg_dishes":          round(avg("dishes_in_plan"), 2),
        "budget_compliance":   round(rate("budget_compliance"), 3),
        "citation_included":   round(rate("citation_included"), 3),
        "e2e_success":         round(rate("e2e_success"), 3),
    }

    targets_met: dict[str, bool] = {}
    for key, (kind, goal) in KPI_TARGETS.items():
        if kind == "eq":
            targets_met[key] = abs(avg(key) - goal) < 1e-6
        elif kind == "gte":
            targets_met[key] = avg(key) >= goal
        elif kind == "rate":
            targets_met[key] = rate(key) >= goal

    return {"runs": n, "metrics": metrics, "targets_met": targets_met}
