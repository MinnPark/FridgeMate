"""농촌진흥청(RDA) 농식품올바로 / 전통향토음식 API 수집.

⚠️ 미구현 (정직한 스텁). 실 RDA 엔드포인트 연결은 미완 — 호출하면 빈 리스트.
   이전에는 seed 를 "rda" 출처로 재포장해 수집인 척했으나, 가짜 수집이라 제거함.
   구현 시: RDA OpenAPI 키 + normalize_rda(raw) 연결 (normalize.py 에 정규화기는 준비됨).
"""
from __future__ import annotations

import os


async def fetch_rda(limit: int = 100) -> list[dict]:
    api_key = os.getenv("RDA_API_KEY")
    if not api_key:
        print("[fetch_rda] RDA_API_KEY 없음 — 미구현 스텁, 0건 반환")
        return []

    # TODO: 실제 RDA endpoint 호출 + normalize_rda. 현재 미연결.
    print("[fetch_rda] 실 엔드포인트 미연결 — 0건 반환")
    return []
