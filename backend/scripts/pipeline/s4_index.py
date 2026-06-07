"""Stage 4 (FM 데이터 파이프라인) - 적재: 03_embed_ready → bge-m3 임베딩 → ChromaDB recipe_db.

읽기: data/pipeline/03_embed_ready/recipes.json
적재: ChromaDB recipe_db (id 기준 upsert, 누적 — 기존 코퍼스 보존). app/rag/indexer.upsert_recipes 정본.

기본은 DRY-RUN(임베더 연결만 확인, DB 미변경). 실제 적재는 --apply 필요.
  - 공유 recipe_db 를 바꾸는 작업이라 기본 안전(되돌리기 어려운 변경 방지).
  - 임베딩: bge-m3(LM Studio, EMBED_PROVIDER=local). 같은 임베더로 적재해야 검색 벡터공간 일치.

실행(backend 에서):
  점검:   .venv\\Scripts\\python.exe scripts\\pipeline\\s4_index.py
  적재:   .venv\\Scripts\\python.exe scripts\\pipeline\\s4_index.py --apply
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]            # = backend/
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv                         # noqa: E402

load_dotenv(ROOT / ".env")
from app.rag.embedder import Embedder                  # noqa: E402
from app.rag.indexer import upsert_recipes             # noqa: E402

PIPE = ROOT / "data" / "pipeline"
SRC = PIPE / "03_embed_ready" / "recipes.json"


async def main(apply: bool) -> None:
    print("=== Stage 4: 임베딩 + ChromaDB 적재 ===")
    recs = json.loads(SRC.read_text(encoding="utf-8"))
    emb = Embedder()
    print(f"  레코드: {len(recs)}건 | embedder provider={emb.provider} mock={emb.mock} sig={emb.signature}")

    # 임베더 연결/차원 확인 (1건 임베딩) — 어디서 끊기는지 조용히 넘기지 않음
    try:
        probe = await emb.embed_documents([recs[0]["embed_text"]])
        print(f"  임베더 확인 OK — dim={len(probe[0])}")
    except Exception as e:
        print(f"  임베더 호출 실패: {type(e).__name__}: {e}")
        print("  -> LM Studio(bge-m3) 연결 확인 필요. 적재 중단.")
        return

    if not apply:
        print("  [DRY-RUN] DB 미변경. 실제 적재는 --apply 옵션 추가.")
        print("  적재 대상 컬렉션: recipe_db (id upsert, 누적)")
        return

    res = await upsert_recipes(recs)
    print(f"  recipe_db: {res['before']} -> {res['after']} "
          f"(added {res['added']}, submitted {res['submitted']}, sig {res['embed_sig']})")
    print("  DONE — 백엔드/평가가 같은 EMBED_PROVIDER 로 떠야 이 코퍼스를 그대로 씀")


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
