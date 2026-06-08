"""Stage 2 (FM 데이터 파이프라인) - 정제·검증 + 품질 리포트.

읽기: data/pipeline/01_normalized/{cookrcp,mafra}.json + seed(app 정본 10건)
쓰기: data/pipeline/02_clean/recipes.json  (id 기준 dedup 된 단일 코퍼스)
      data/pipeline/02_clean/report.json   (소스별 필드 채움률 — '데이터 실태' 자동 리포트)

원칙: 임의 보정을 하지 않는다(투명 우선). '무엇이 비어있고 가짜인지'를 수치로 드러낸다.
  - 제거: id 중복, 이름 없음, 재료 0개 레시피.
  - 리포트: 재료 분량/단위 채움률, 영양(칼로리/단백질·탄수·지방) 채움률, 조리시간 placeholder 비율.

실행(backend 에서): .venv\\Scripts\\python.exe scripts\\pipeline\\s2_clean.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]            # = backend/
sys.path.insert(0, str(ROOT))

PIPE = ROOT / "data" / "pipeline"
NORM, OUT = PIPE / "01_normalized", PIPE / "02_clean"

# 소스별 '조리시간 미수집' 표식 — cookrcp 는 시간 필드가 없어 30 을 placeholder 로 채움.
_TIME_PLACEHOLDER = {"cookrcp": 30}


def _load(name: str) -> list[dict]:
    p = NORM / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _load_seed() -> list[dict]:
    """app 정본 seed(데모/테스트 10건) — 이미 정규화 구조. embed_text 채워 합류."""
    seed_path = ROOT / "app" / "rag" / "data" / "seed_recipes.json"
    if not seed_path.exists():
        return []
    from app.rag._normalize import make_embed_text
    recs = json.loads(seed_path.read_text(encoding="utf-8"))
    for r in recs:
        r["embed_text"] = make_embed_text(r)
    return recs


def _pct(num: int, den: int) -> float:
    return round(100 * num / den, 1) if den else 0.0


def _source_report(recs: list[dict]) -> dict:
    """레시피 리스트의 필드 채움 실태 집계 (소스 단위 호출)."""
    n = len(recs)
    ing_tot = ing_qty = ing_unit = 0
    cal_ok = pcf_ok = steps_ok = time_default = 0
    src = recs[0].get("source") if recs else None
    placeholder = _TIME_PLACEHOLDER.get(src)
    for r in recs:
        ings = r.get("ingredients") or []
        ing_tot += len(ings)
        ing_qty += sum(1 for i in ings if i.get("qty") is not None)
        ing_unit += sum(1 for i in ings if i.get("unit"))
        if (r.get("calories") or 0) > 0:
            cal_ok += 1
        if any((r.get(k) or 0) > 0 for k in ("protein", "carb", "fat")):
            pcf_ok += 1
        if r.get("steps"):
            steps_ok += 1
        if placeholder is not None and r.get("time_min") == placeholder:
            time_default += 1
    rep = {
        "count": n,
        "ingredients_total": ing_tot,
        "ingredient_qty_filled_pct": _pct(ing_qty, ing_tot),
        "ingredient_unit_filled_pct": _pct(ing_unit, ing_tot),
        "calories_present_pct": _pct(cal_ok, n),
        "protein_carb_fat_present_pct": _pct(pcf_ok, n),
        "steps_present_pct": _pct(steps_ok, n),
    }
    if placeholder is not None:
        rep["time_min_placeholder_pct"] = _pct(time_default, n)
        rep["time_min_note"] = f"소스에 조리시간 필드 없음 — {placeholder}분 placeholder"
    if pcf_ok == 0 and n:
        rep["nutrition_note"] = "단백질/탄수/지방 미수집(0) — 영양결합 서비스 수집 전까지 신뢰 불가"
    return rep


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("=== Stage 2: 정제·검증 + 품질 리포트 ===")

    by_source = {"cookrcp": _load("cookrcp"), "mafra": _load("mafra"), "seed": _load_seed()}

    # 검증: 이름/재료 없는 레시피 제거 + id dedup (소스 우선순위 등장 순)
    seen: dict[str, dict] = {}
    dropped = {"no_name": 0, "no_ingredients": 0, "dup_id": 0}
    src_report: dict[str, dict] = {}
    for src, recs in by_source.items():
        kept: list[dict] = []
        for r in recs:
            if not (r.get("name") or "").strip():
                dropped["no_name"] += 1
                continue
            if not (r.get("ingredients") or []):
                dropped["no_ingredients"] += 1
                continue
            rid = r.get("id")
            if rid in seen:
                dropped["dup_id"] += 1
                continue
            seen[rid] = r
            kept.append(r)
        if recs:
            src_report[src] = _source_report(recs)

    corpus = list(seen.values())
    (OUT / "recipes.json").write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf-8")
    report = {
        "corpus_count": len(corpus),
        "dropped": dropped,
        "by_source": src_report,
    }
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"  코퍼스: {len(corpus)}건 -> 02_clean/recipes.json")
    print(f"  제거: {dropped}")
    for src, rep in src_report.items():
        print(f"  [{src}] {rep['count']}건 | 재료분량 {rep['ingredient_qty_filled_pct']}% "
              f"단위 {rep['ingredient_unit_filled_pct']}% | 칼로리 {rep['calories_present_pct']}% "
              f"P/C/F {rep['protein_carb_fat_present_pct']}% | 조리법 {rep['steps_present_pct']}%")
        if rep.get("nutrition_note"):
            print(f"        주의: {rep['nutrition_note']}")
        if rep.get("time_min_note"):
            print(f"        주의: 조리시간 placeholder {rep.get('time_min_placeholder_pct')}% — {rep['time_min_note']}")
    print("  리포트: 02_clean/report.json")
    print("다음 단계: s3_embed_text.py (임베딩 입력 텍스트 생성)")


if __name__ == "__main__":
    main()
