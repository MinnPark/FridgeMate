"""Stage 0 (FM 데이터 파이프라인) - 원천 raw 수집·저장. 정규화 전 API 원문 그대로.

여러 채널의 raw 를 data/pipeline/00_raw/ 에 채널별 JSON + _manifest.json 으로 저장한다.
이후 단계(s1 정규화 / s2 정제 / s3 임베딩준비 / s4 적재)가 이 raw 를 재사용한다.
raw 를 보존하므로 파싱을 고쳐도 API 재호출 없이 s1 부터 재실행 가능.

실행(backend 에서):
  .venv\\Scripts\\python.exe scripts\\pipeline\\s0_collect_raw.py

API 연결 설정(엔드포인트 + 서비스 ID)은 코드 상수다 - env 로 관리하지 않는다.
env 는 자격증명(API 키)과 수집량 한도만 담당한다.
주의:
  - cookrcp(식약처): FOOD_SAFETY_API_KEY(또는 sample 5건).
  - mafra(농정원): MAFRA_API_KEY 필요. 이 PC 에서 직접 호출됨(이전 IP 제한 가정은 사실 아님).
자격증명/한도 env: MAFRA_API_KEY, FOOD_SAFETY_API_KEY, COOKRCP_LIMIT(기본 1200), MAFRA_LIMIT(기본 1000).
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]            # = backend/
load_dotenv(ROOT / ".env")
RAW = ROOT / "data" / "pipeline" / "00_raw"

COOKRCP_BASE = "https://openapi.foodsafetykorea.go.kr/api"
MAFRA_BASE = "http://211.237.50.150:7080/openapi"
MAFRA_SVCS = {                                        # 농정원 서비스 ID (연결 설정 = 코드 상수, env 아님)
    "basic": "Grid_20150827000000000226_1",       # 레시피 기본정보
    "ingredient": "Grid_20150827000000000227_1",  # 레시피 재료정보
    "process": "Grid_20150827000000000228_1",      # 레시피 과정정보
}


async def _get(client: httpx.AsyncClient, url: str) -> dict:
    r = await client.get(url)
    r.raise_for_status()
    return r.json()


async def collect_cookrcp(limit: int) -> tuple[list[dict], str]:
    """식약처 COOKRCP01 raw row 수집 (정규화 안 함)."""
    key = os.getenv("FOOD_SAFETY_API_KEY") or "sample"
    rows: list[dict] = []
    async with httpx.AsyncClient(timeout=20.0) as c:
        for start in range(1, limit + 1, 100):
            end = min(start + 99, limit)
            try:
                j = await _get(c, f"{COOKRCP_BASE}/{key}/COOKRCP01/json/{start}/{end}")
            except Exception as e:
                print(f"  [cookrcp] {start}-{end} 실패: {type(e).__name__}")
                break
            r = (j.get("COOKRCP01") or {}).get("row") or []
            if not r:
                break
            rows.extend(r)
            if len(r) < (end - start + 1):
                break
    return rows, ("real" if key != "sample" else "sample")


async def collect_mafra(limit: int) -> tuple[dict[str, list[dict]], str]:
    """농정원 서비스별(기본/재료/과정) raw row 수집. 키 없으면 보류."""
    key = os.getenv("MAFRA_API_KEY")
    if not key:
        return {}, "missing"
    out: dict[str, list[dict]] = {}
    async with httpx.AsyncClient(timeout=30.0) as c:
        for name, svc in MAFRA_SVCS.items():
            cap = limit if name == "basic" else 100000  # 재료/과정은 레시피당 다행 -> 큰 상한
            rows: list[dict] = []
            start = 1
            while start <= cap:
                end = min(start + 999, cap)
                try:
                    j = await _get(c, f"{MAFRA_BASE}/{key}/json/{svc}/{start}/{end}")
                except Exception as e:
                    print(f"  [mafra/{name}] 실패: {type(e).__name__}")
                    break
                r = (j.get(svc) or {}).get("row") or []
                if not r:
                    break
                rows.extend(r)
                if len(r) < (end - start + 1):
                    break
                start = end + 1
            out[name] = rows
    return out, "real"


def _save(path: Path, source: str, service: str, rows: list[dict]) -> int:
    path.write_text(json.dumps({
        "source": source,
        "service": service,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "count": len(rows),
        "rows": rows,                          # API 원문 그대로
    }, ensure_ascii=False), encoding="utf-8")
    return len(rows)


async def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    manifest = {"collected_at": datetime.now(timezone.utc).isoformat(), "channels": {}}

    print("=== Stage 0: 원천 raw 수집 ===")
    # 채널: 식약처
    rows, st = await collect_cookrcp(int(os.getenv("COOKRCP_LIMIT", "1200")))
    n = _save(RAW / "cookrcp.json", "cookrcp", "COOKRCP01", rows)
    manifest["channels"]["cookrcp"] = {"service": "COOKRCP01", "count": n, "key": st}
    print(f"  [cookrcp] raw {n}건 저장 (key={st})")

    # 채널: 농정원 (서비스별)
    msvc, st = await collect_mafra(int(os.getenv("MAFRA_LIMIT", "1000")))
    if st == "missing":
        print("  [mafra] MAFRA_API_KEY 미설정 -> 보류")
        manifest["channels"]["mafra"] = {"status": "skipped(no MAFRA_API_KEY)"}
    else:
        for name, mrows in msvc.items():
            n = _save(RAW / f"mafra_{name}.json", "mafra", MAFRA_SVCS[name], mrows)
            manifest["channels"][f"mafra_{name}"] = {"service": MAFRA_SVCS[name], "count": n, "key": st}
            print(f"  [mafra/{name}] raw {n}행 저장")

    (RAW / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n매니페스트: {RAW / '_manifest.json'}")
    print("다음 단계: s1_normalize.py (이 raw 를 정규화)")


if __name__ == "__main__":
    asyncio.run(main())
