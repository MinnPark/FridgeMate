from typing import Any


def _build_warnings(totals: dict, targets: dict) -> list[str]:
    """
    목표 대비 실제 영양소 비교 → 한국어 경고 문장 리스트 반환.

    경고 생성 기준:
      protein  < target            → 단백질 미달
      fat      < target * 0.8      → 지방 부족
      carbs    > target * 1.2      → 탄수화물 초과
      calories < target * 0.9      → 칼로리 부족
      calories > target * 1.1      → 칼로리 초과
    """
    warnings: list[str] = []

    if totals["protein"] < targets["protein"]:
        warnings.append(
            f"단백질이 목표({targets['protein']}g)에 미달해요. "
            "닭가슴살·두부를 추가하면 좋아요."
        )
    if totals["fat"] < targets["fat"] * 0.8:
        warnings.append(
            "지방이 목표 대비 다소 낮아요. 견과류를 소량 추가하면 균형이 좋아져요."
        )
    if totals["carbs"] > targets["carbs"] * 1.2:
        warnings.append(
            "탄수화물이 목표를 초과했어요. 밥 양을 줄이거나 채소로 대체해 보세요."
        )
    if totals["calories"] < targets["calories"] * 0.9:
        warnings.append(
            f"칼로리가 목표({targets['calories']}kcal) 대비 부족해요. "
            "한 끼 분량을 늘려보세요."
        )
    if totals["calories"] > targets["calories"] * 1.1:
        warnings.append(
            f"칼로리가 목표({targets['calories']}kcal)를 초과했어요. "
            "간식이나 소스 양을 줄여보세요."
        )

    return warnings


def _build_message(passed: bool, totals: dict, targets: dict) -> str:
    """
    passed 여부 + 영양소 상태 → 한국어 요약 메시지 반환.

    passed=True  → 긍정 메시지 + 탄수화물 여유 여부 포함
    passed=False → 경고 확인 안내 메시지
    """
    if not passed:
        return "목표 영양소를 충족하지 못했어요. 아래 경고를 확인해 주세요."

    parts = ["단백질·칼로리 목표를 충족했어요."]
    if totals["carbs"] <= targets["carbs"]:
        parts.append("탄수화물은 목표 범위 안에서 여유가 있어요.")

    return " ".join(parts)


def verify_nutrition_goal(
    recipes: list[dict[str, Any]],
    goal: dict[str, Any],
) -> dict[str, Any]:
    """
    selected_recipes 영양 합산 → 목표 대비 검증 결과 반환.

    입력:
      recipes: selected_recipes (integration.to_contract 계약 형태)
               recipe["nutrition"] = {"calories", "protein", "carbs", "fat"}
               → ChromaDB recipe_db 에 이미 포함된 값 (외부 API 불필요)
      goal:    state["nutrition_goal"]
               {"protein_target": 120, "calorie_target": 1700,
                "carbs_target": 150,   "fat_target": 55}

    출력 (mock.ts NutritionResult 계약):
      {
        "protein":  {"current": 115, "target": 120, "unit": "g"},
        "calories": {"current": 1210, "target": 1700, "unit": "kcal"},
        "carbs":    {"current": 58,  "target": 150,  "unit": "g"},
        "fat":      {"current": 48,  "target": 55,   "unit": "g"},
        "passed":   False,
        "message":  "목표 영양소를 충족하지 못했어요. 아래 경고를 확인해 주세요.",
        "warnings": ["칼로리가 목표(1700kcal) 대비 부족해요."],
      }
    """
    # 1. selected_recipes["nutrition"] 직접 합산
    #    ChromaDB → integration.to_contract() 가 이미 carbs, fat 변환 완료
    totals = {
        "calories": round(sum(r.get("nutrition", {}).get("calories", 0) for r in recipes)),
        "protein":  round(sum(r.get("nutrition", {}).get("protein",  0) for r in recipes)),
        "carbs":    round(sum(r.get("nutrition", {}).get("carbs",    0) for r in recipes)),
        "fat":      round(sum(r.get("nutrition", {}).get("fat",      0) for r in recipes)),
    }

    # 2. 목표값 추출
    #    protein_target / protein_min 둘 다 허용 (기존 meal_agent 호환)
    targets = {
        "protein":  goal.get("protein_target",  goal.get("protein_min",  40)),
        "calories": goal.get("calorie_target",  goal.get("calorie_min",  1500)),
        "carbs":    goal.get("carbs_target",    150),
        "fat":      goal.get("fat_target",      55),
    }

    # 3. passed 판정
    #    단백질 목표 달성 + 칼로리 ±10% 범위 내
    passed = (
        totals["protein"]  >= targets["protein"]
        and totals["calories"] >= targets["calories"] * 0.9
        and totals["calories"] <= targets["calories"] * 1.1
    )

    # 4. warnings / message 생성
    warnings = _build_warnings(totals, targets)
    message  = _build_message(passed, totals, targets)

    # 5. mock.ts NutritionResult 계약 형태로 반환
    return {
        "protein":  {"current": totals["protein"],  "target": targets["protein"],  "unit": "g"},
        "calories": {"current": totals["calories"], "target": targets["calories"], "unit": "kcal"},
        "carbs":    {"current": totals["carbs"],    "target": targets["carbs"],    "unit": "g"},
        "fat":      {"current": totals["fat"],      "target": targets["fat"],      "unit": "g"},
        "passed":   passed,
        "message":  message,
        "warnings": warnings,
    }
