"""Stage 3 (FM 데이터 파이프라인) - 임베딩 입력 텍스트 생성(임베딩 준비).

읽기: data/pipeline/02_clean/recipes.json
쓰기: data/pipeline/03_embed_ready/recipes.json
      data/pipeline/03_embed_ready/_preview.txt  (실제 임베딩될 문자열 상위 20개 — 눈으로 검증용)

이 단계의 목적 = '무엇이 벡터로 들어가는지'를 명시적으로 드러내는 것.
정제된 레코드로부터 embed_text 를 다시 생성(authoritative)한다 — 정제 결과가 검색 텍스트에 반영됨.
embed_text 형식은 app/rag/_normalize.make_embed_text 정본을 따른다(정규화·검색 일관).

실행(backend 에서): .venv\\Scripts\\python.exe scripts\\pipeline\\s3_embed_text.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]            # = backend/
sys.path.insert(0, str(ROOT))
from app.rag._normalize import make_embed_text        # noqa: E402

PIPE = ROOT / "data" / "pipeline"
SRC, OUT = PIPE / "02_clean", PIPE / "03_embed_ready"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("=== Stage 3: 임베딩 입력 텍스트 생성 ===")
    recs = json.loads((SRC / "recipes.json").read_text(encoding="utf-8"))
    for r in recs:
        r["embed_text"] = make_embed_text(r)           # 정제 결과 반영(재생성 = 정본)
    (OUT / "recipes.json").write_text(json.dumps(recs, ensure_ascii=False), encoding="utf-8")

    preview = "\n".join(f"[{r['id']}] {r['embed_text'][:220]}" for r in recs[:20])
    (OUT / "_preview.txt").write_text(preview, encoding="utf-8")

    avg = round(sum(len(r["embed_text"]) for r in recs) / max(len(recs), 1))
    print(f"  {len(recs)}건 embed_text 생성 -> 03_embed_ready/recipes.json (평균 {avg}자)")
    print("  미리보기: 03_embed_ready/_preview.txt (상위 20건 실제 임베딩 문자열)")
    print("다음 단계: s4_index.py (bge-m3 임베딩 -> ChromaDB recipe_db 적재)")


if __name__ == "__main__":
    main()
