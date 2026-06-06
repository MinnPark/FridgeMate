"""부족 재료 산출 — gap_calc_node 가 사용.

레시피 재료 합(인원수 가중) vs pantry 재고. 단위 정합 규칙:
  - 단위 일치 (또는 한쪽 미지정) → 수치 뺄셈
  - 단위 불일치 → 변환표 없음 → 보유 처리 + unit_mismatch flag
  - 재고에 없음 → 전량 부족

Function calling 도입 시 tool spec:
  name        : compute_missing
  description : 식단 전체 재료를 인원수에 맞춰 합한 뒤 재고와 비교, 부족 재료 산출
  parameters  : {pantry: [{name,qty,unit}], recipes: [{ingredients:[...]}], people: int}
  returns     : {missing: [...], coverage: float, unit_mismatch_count: int}
"""
from __future__ import annotations


def _normalize_name(s: str) -> str:
    return (s or "").strip().lower()


def compute_missing(
    *,
    pantry: list[dict],
    recipes: list[dict],
    people: int,
) -> tuple[list[dict], float, int]:
    """반환: (missing_items, coverage[0~1], unit_mismatch_count)."""
    stock: dict[str, dict] = {}
    for p in pantry:
        key = _normalize_name(p["name"])
        stock[key] = {"name": p["name"], "qty": p.get("qty") or 0, "unit": p.get("unit") or ""}

    needed: dict[str, dict] = {}
    for recipe in recipes:
        for ing in recipe.get("ingredients", []):
            key = _normalize_name(ing["name"])
            if key not in needed:
                needed[key] = {"name": ing["name"], "qty": 0.0, "unit": ing.get("unit") or "", "used_in": []}
            needed[key]["qty"] += (ing.get("qty") or 1) * max(people, 1)
            needed[key]["used_in"].append(recipe["dish_name"])

    missing: list[dict] = []
    covered = 0
    unit_mismatch = 0
    for key, need in needed.items():
        in_stock = stock.get(key)
        if in_stock is None:
            missing.append({
                "name": need["name"], "shortage_qty": need["qty"], "needed_qty": need["qty"],
                "stock_qty": 0, "unit": need["unit"], "used_in": need["used_in"],
                "decision": "buy", "unit_mismatch": False,
            })
            continue

        su = in_stock.get("unit") or ""
        nu = need.get("unit") or ""
        if su == nu or not su or not nu:
            stock_qty = in_stock.get("qty") or 0
            shortage = need["qty"] - stock_qty
            if shortage > 0:
                missing.append({
                    "name": need["name"], "shortage_qty": shortage, "needed_qty": need["qty"],
                    "stock_qty": stock_qty, "unit": need["unit"],
                    "used_in": need["used_in"], "decision": "buy", "unit_mismatch": False,
                })
            else:
                covered += 1
        else:
            covered += 1
            unit_mismatch += 1

    coverage = covered / max(len(needed), 1)
    return missing, round(coverage, 3), unit_mismatch
