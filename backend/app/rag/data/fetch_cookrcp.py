"""식약처 COOKRCP01 (조리식품의 레시피 DB) 수집.

대상: https://openapi.foodsafetykorea.go.kr/api/{KEY}/COOKRCP01/json/{START}/{END}
  - 실 키 (foodsafetykorea.go.kr 무료 발급): 전체 ~1,135건
  - "sample" 키 (발급 불요): 고정 5건 — 데모/검증용
수집 필드: RCP_NM(이름) RCP_PAT2(요리종류) RCP_WAY2(조리방법)
          INFO_ENG/PRO/CAR/FAT/NA(영양) RCP_PARTS_DTLS(재료) MANUAL01~20(조리순서)

키 우선순위: 인자 api_key > FOOD_SAFETY_API_KEY env > "sample".
FRIDGEMATE_MOCK_MODE=true 이고 명시 키 없으면: 외부호출 없이 seed_recipes.json (오프라인).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.rag._normalize import normalize_cookrcp

BASE = "https://openapi.foodsafetykorea.go.kr/api"
SAMPLE_KEY = "sample"   # 식약처 제공 테스트 키 — 발급 없이 5건 실데이터
DATA_DIR = Path(__file__).resolve().parent


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def _fetch_page(api_key: str, start: int, end: int) -> dict:
    url = f"{BASE}/{api_key}/COOKRCP01/json/{start}/{end}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.json()


def _load_seed() -> list[dict]:
    """seed_recipes.json 을 정규화된 형태로 반환 (이미 normalize 된 구조)."""
    raw = json.loads((DATA_DIR / "seed_recipes.json").read_text(encoding="utf-8"))
    from app.rag._normalize import make_embed_text
    for r in raw:
        r["embed_text"] = make_embed_text(r)
    return raw


async def fetch_cookrcp(limit: int = 100, *, api_key: str | None = None) -> list[dict]:
    """식약처 레시피 수집 → 정규화된 list 반환.

    - api_key 명시 시 그 키로 실수집 (mock 무시).
    - 미명시 + MOCK_MODE=true → seed (오프라인).
    - 미명시 + MOCK_MODE=false → FOOD_SAFETY_API_KEY 또는 sample 키로 실수집.
    """
    force_mock = os.getenv("FRIDGEMATE_MOCK_MODE", "true").lower() == "true"
    if api_key is None and force_mock:
        return _load_seed()

    key = api_key or os.getenv("FOOD_SAFETY_API_KEY") or SAMPLE_KEY

    page_size = 100
    out: list[dict] = []
    for start in range(1, limit + 1, page_size):
        end = min(start + page_size - 1, limit)
        try:
            data = await _fetch_page(key, start, end)
            rows = (data.get("COOKRCP01") or {}).get("row") or []
            for i, row in enumerate(rows):
                out.append(normalize_cookrcp(row, start + i))
        except Exception as exc:
            print(f"[fetch_cookrcp] {start}~{end} 실패: {exc}")
            continue

    if not out:
        print("[fetch_cookrcp] 외부 호출 0건 → seed_recipes.json fallback")
        return _load_seed()

    print(f"[fetch_cookrcp] key={'sample' if key == SAMPLE_KEY else '***'} → {len(out)}건 수집")
    return out
