"""외부 레시피 API → recipe_db 증분 주입 (멀티소스, 누적).

"API로 외부 데이터를 계속 주입" 하는 운영 경로. 노트북 01~04(수집→정규화→임베딩→주입)의
소스 게이트와 동일 철학이되, **lab(recipe_db_lab) 이 아니라 앱이 쓰는 recipe_db** 로,
**통째 재구축이 아니라 id 기준 upsert(누적)** 한다. 반복 실행해도 기존 코퍼스 보존.

소스 (키 있으면 수집, 없으면 SKIP):
  - seed            : 항상 (김치찌개 등 데모/테스트 정본 10건)
  - 식약처 COOKRCP01 : FOOD_SAFETY_API_KEY (실키 ~1,146건 / 미설정 시 sample 5건)
  - 농진청 RDA       : RDA_API_KEY (fetch_rda — 현재 스텁, 0건)
  - EPIS(농림수산식품): EPIS_RECIPE_KEY/BASE (정규화기 normalize_epis 미작성 → TODO)

전제: 주입·백엔드(8001)·평가가 **동일 EMBED_PROVIDER** 여야 같은 벡터공간을 공유한다.
"""
import os
import sys
import asyncio
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

from app.rag.data.fetch_cookrcp import fetch_cookrcp, _load_seed
from app.rag.data.fetch_rda import fetch_rda
from app.rag.embedder import CohereEmbedder
from app.rag.indexer import upsert_recipes

LIMIT = int(os.getenv("INGEST_LIMIT", "1200"))  # 식약처 전체 ~1,146건


async def _collect() -> list[dict]:
    """키 게이트로 가용 소스만 수집 → id 기준 dedup."""
    by_id: dict[str, dict] = {}

    def _add(label: str, recs: list[dict]) -> None:
        new = sum(1 for r in recs if r["id"] not in by_id)
        for r in recs:
            by_id[r["id"]] = r
        print(f"  [{label}] {len(recs)}건 (신규 {new})")

    # seed — 항상 (병합 보존, id seed-* 충돌 없음)
    _add("seed", _load_seed())

    # 식약처 — 키 있으면 실수집, 없으면 sample
    food_key = os.getenv("FOOD_SAFETY_API_KEY")
    _add("cookrcp", await fetch_cookrcp(limit=LIMIT, api_key=food_key))

    # 농림축산식품(MAFRA) — MAFRA_API_KEY 있으면 수집 (기본/재료/과정 조인, ~537건)
    if os.getenv("MAFRA_API_KEY"):
        from app.rag.data.fetch_mafra import fetch_mafra
        _add("mafra", await fetch_mafra(limit=int(os.getenv("MAFRA_LIMIT", "1000"))))
    else:
        print("  [mafra] MAFRA_API_KEY 미설정 → SKIP")

    # 농진청 — fetch_rda 스텁 (RDA_API_KEY 연결 시 동작)
    try:
        rda = await fetch_rda(limit=LIMIT)
        if rda:
            _add("rda", rda)
        else:
            print("  [rda] 0건 (스텁/키 미설정) → SKIP")
    except Exception as exc:
        print(f"  [rda] 실패 → SKIP: {exc}")

    # EPIS(농림수산식품) — 정규화기(normalize_epis) 미작성 → 추가 시 여기에 연결
    if os.getenv("EPIS_RECIPE_KEY"):
        print("  [epis] 키 감지 — normalize_epis 미작성, TODO. SKIP")

    return list(by_id.values())


async def main():
    print("=== 1) 수집 (멀티소스, 키 게이트) ===")
    recs = await _collect()
    print(f"수집 합계: {len(recs)}건 (dedup)")
    if not recs:
        print("수집 0건 — 중단")
        return

    print("=== 2) 증분 주입 (id upsert, 누적) ===")
    emb = CohereEmbedder()
    print(f"  embedder: provider={emb.provider} mock={emb.mock} sig={emb.signature}")
    res = await upsert_recipes(recs)
    print(f"  recipe_db: {res['before']} → {res['after']} (added {res['added']}, submitted {res['submitted']})")
    print(f"  embed_sig: {res['embed_sig']}")
    print("DONE — 백엔드(8001)/평가가 같은 EMBED_PROVIDER 로 떠야 이 코퍼스를 그대로 씀")


asyncio.run(main())
