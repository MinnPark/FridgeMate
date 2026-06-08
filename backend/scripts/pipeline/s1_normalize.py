"""Stage 1 (FM 데이터 파이프라인) - 정규화: 00_raw 채널별 원문 → 표준 레시피 dict.

읽기: data/pipeline/00_raw/{cookrcp,mafra_basic,mafra_ingredient,mafra_process}.json
쓰기: data/pipeline/01_normalized/{cookrcp,mafra}.json
      (NormalizedRecipe 리스트 — id/name/ingredients[{name,qty,unit}]/steps/영양/embed_text 포함)

정규화기는 app/rag/_normalize.py(운영 ingest 와 동일한 정본)를 그대로 쓴다 — 파서 이원화 방지.
raw 가 보존되므로 파서를 고친 뒤 이 단계만 재실행하면 된다(API 재호출 불요).

실행(backend 에서): .venv\\Scripts\\python.exe scripts\\pipeline\\s1_normalize.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")              # cp949 콘솔에서도 한글 깨짐 방지

ROOT = Path(__file__).resolve().parents[2]            # = backend/
sys.path.insert(0, str(ROOT))
from app.rag._normalize import normalize_cookrcp, normalize_mafra  # noqa: E402

PIPE = ROOT / "data" / "pipeline"
RAW, OUT = PIPE / "00_raw", PIPE / "01_normalized"


def _load_rows(name: str) -> list[dict]:
    p = RAW / f"{name}.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("rows") or []


def normalize_cookrcp_all() -> list[dict]:
    return [normalize_cookrcp(r, i) for i, r in enumerate(_load_rows("cookrcp"))]


def normalize_mafra_all() -> list[dict]:
    """basic/재료/과정을 RECIPE_ID 로 조인 → normalize_mafra."""
    basics = _load_rows("mafra_basic")
    if not basics:
        return []
    ing_by_id: dict[str, list[dict]] = defaultdict(list)
    for r in _load_rows("mafra_ingredient"):
        ing_by_id[str(r.get("RECIPE_ID"))].append(r)
    proc_by_id: dict[str, list[dict]] = defaultdict(list)
    for r in _load_rows("mafra_process"):
        proc_by_id[str(r.get("RECIPE_ID"))].append(r)
    out = []
    for b in basics:
        rid = str(b.get("RECIPE_ID"))
        out.append(normalize_mafra(b, ing_by_id.get(rid, []), proc_by_id.get(rid, [])))
    return out


def _save(name: str, recs: list[dict]) -> None:
    (OUT / f"{name}.json").write_text(json.dumps(recs, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("=== Stage 1: 정규화 (raw -> 표준 dict) ===")
    ck = normalize_cookrcp_all()
    _save("cookrcp", ck)
    print(f"  [cookrcp] {len(ck)}건 정규화 -> 01_normalized/cookrcp.json")
    mf = normalize_mafra_all()
    if mf:
        _save("mafra", mf)
        print(f"  [mafra]   {len(mf)}건 정규화 -> 01_normalized/mafra.json")
    else:
        print("  [mafra]   00_raw/mafra_basic.json 없음 -> 건너뜀")
    print("다음 단계: s2_clean.py (정제·검증·품질리포트)")


if __name__ == "__main__":
    main()
