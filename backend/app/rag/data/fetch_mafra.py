"""농림축산식품(MAFRA) 공공데이터 레시피 수집 — 기본/재료/과정 조인.

엔드포인트: http://211.237.50.150:7080/openapi/{KEY}/json/{SERVICE}/{start}/{end}
서비스(Grid_):
  - 레시피 기본정보 TI_RECIPE_INFO : Grid_20150827000000000226_1 (~537건)
  - 레시피 재료정보               : Grid_20150827000000000227_1 (~6,104행)
  - 레시피 과정정보               : Grid_20150827000000000228_1 (~3,022행)
세 서비스를 RECIPE_ID 로 조인해 완전한 레시피를 만든다.

키: 인자 api_key > MAFRA_API_KEY env > "sample"(공개 테스트).
⚠️ 실키는 호출서버 IP(58.148.250.103) 제한 — 그 IP에서만 호출 성공.
"""
from __future__ import annotations

import os
from collections import defaultdict

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.rag._normalize import normalize_mafra

BASE = "http://211.237.50.150:7080/openapi"
SAMPLE_KEY = "sample"

SVC_BASIC = "Grid_20150827000000000226_1"
SVC_INGREDIENT = "Grid_20150827000000000227_1"
SVC_PROCESS = "Grid_20150827000000000228_1"

_PAGE = 1000


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def _fetch_page(client: httpx.AsyncClient, key: str, service: str, start: int, end: int) -> dict:
    r = await client.get(f"{BASE}/{key}/json/{service}/{start}/{end}")
    r.raise_for_status()
    return r.json()


async def _fetch_all(client: httpx.AsyncClient, key: str, service: str, limit: int) -> list[dict]:
    """서비스 전체 행을 페이징 수집 (limit 까지)."""
    out: list[dict] = []
    start = 1
    while start <= limit:
        end = min(start + _PAGE - 1, limit)
        data = await _fetch_page(client, key, service, start, end)
        rows = (data.get(service) or {}).get("row") or []
        if not rows:
            break
        out.extend(rows)
        if len(rows) < (end - start + 1):
            break
        start = end + 1
    return out


async def fetch_mafra(limit: int = 1000, *, api_key: str | None = None) -> list[dict]:
    """MAFRA 레시피 수집 → 정규화 list. basic 기준 limit 건.

    재료/과정은 basic 의 RECIPE_ID 집합에 해당하는 행만 매칭(전량 받아 dict 조인).
    """
    key = api_key or os.getenv("MAFRA_API_KEY") or SAMPLE_KEY
    async with httpx.AsyncClient(timeout=30.0) as client:
        basics = await _fetch_all(client, key, SVC_BASIC, limit)
        if not basics:
            print("[fetch_mafra] basic 0건 — IP 제한(58.148.250.103) 또는 키 확인")
            return []
        # 재료/과정은 전량(혹은 넉넉히) 받아 RECIPE_ID 로 인덱싱
        ingredients = await _fetch_all(client, key, SVC_INGREDIENT, 100000)
        processes = await _fetch_all(client, key, SVC_PROCESS, 100000)

    ing_by_id: dict[str, list[dict]] = defaultdict(list)
    for r in ingredients:
        ing_by_id[str(r.get("RECIPE_ID"))].append(r)
    proc_by_id: dict[str, list[dict]] = defaultdict(list)
    for r in processes:
        proc_by_id[str(r.get("RECIPE_ID"))].append(r)

    out: list[dict] = []
    for b in basics:
        rid = str(b.get("RECIPE_ID"))
        out.append(normalize_mafra(b, ing_by_id.get(rid, []), proc_by_id.get(rid, [])))

    print(f"[fetch_mafra] key={'sample' if key == SAMPLE_KEY else '***'} → "
          f"basic {len(basics)} / ing {len(ingredients)} / proc {len(processes)} → {len(out)} 레시피")
    return out
