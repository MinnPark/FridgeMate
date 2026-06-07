import sys
import os
import json
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.agents.pantry_agent import pantry_agent
from app.agents.recipe_agent import recipe_agent
from app.agents.meal_agent import (
    meal_agent,
    create_weekly_plan,
    # execute_meal_plan 제거 — RAG 9회 호출 문제로 삭제됨
    _mark_priority_items,
    _extract_constraints,
)
from app.tools.nutrition_tools import verify_nutrition_goal

# ─────────────────────────────────────────────────────
# 테스트 Input 데이터
# mock.ts DEMO_REQUEST 시나리오 기준 (오늘: 2026-06-06)
#   재료: 닭가슴살(D+4), 계란(D+1), 브로콜리(D+2), 두부(D+0)
#   목표: 고단백 저탄수 / 2인 / 20분 이내 / 해산물 제외
# ─────────────────────────────────────────────────────
TEST_ENTRIES = [
    {"name": "닭가슴살", "amount": "500g",  "expiration_date": "2026-06-10", "storage_type": "냉장 보관"},
    {"name": "계란",     "amount": "10개",  "expiration_date": "2026-06-07", "storage_type": "냉장 보관"},
    {"name": "브로콜리", "amount": "300g",  "expiration_date": "2026-06-08", "storage_type": "냉장 보관"},
    {"name": "두부",     "amount": "1모",   "expiration_date": "2026-06-06", "storage_type": "냉장 보관"},
]

TEST_USER_INPUT = (
    "냉장고에 닭가슴살, 계란, 브로콜리, 두부 있어. 고단백 저탄수. "
    "2인분, 조리 20분 이내, 칼로리 1700kcal, 단백질 120g, "
    "해산물 제외, 배송 freshness, goal 모드. 식단 짜줘"
)

TEST_NUTRITION_GOAL = {
    "protein_target":  120,
    "calorie_target":  1700,
    "carbs_target":    150,
    "fat_target":      55,
}

TEST_SELECTED_RECIPES = [
    {
        "id": "rcp_1",
        "name": "닭가슴살 두부 강된장 덮밥",
        "nutrition": {"calories": 520, "protein": 45, "carbs": 38, "fat": 14},
        "ingredients": [
            {"name": "닭가슴살", "amount": 200, "unit": "g"},
            {"name": "두부",     "amount": 150, "unit": "g"},
        ],
        "score": 0.91,
    },
    {
        "id": "rcp_2",
        "name": "브로콜리 계란 스크램블",
        "nutrition": {"calories": 280, "protein": 22, "carbs": 12, "fat": 18},
        "ingredients": [
            {"name": "브로콜리", "amount": 150, "unit": "g"},
            {"name": "계란",     "amount": 2,   "unit": "개"},
        ],
        "score": 0.84,
    },
    {
        "id": "rcp_3",
        "name": "닭가슴살 두부 스테이크",
        "nutrition": {"calories": 410, "protein": 48, "carbs": 8, "fat": 16},
        "ingredients": [
            {"name": "닭가슴살", "amount": 200, "unit": "g"},
            {"name": "두부",     "amount": 100, "unit": "g"},
        ],
        "score": 0.82,
    },
]

TEST_PANTRY_ITEMS = [
    {"name": "닭가슴살", "expiry_priority": "normal", "expiration_date": "2026-06-10"},
    {"name": "계란",     "expiry_priority": "high",   "expiration_date": "2026-06-07"},
    {"name": "브로콜리", "expiry_priority": "high",   "expiration_date": "2026-06-08"},
    {"name": "두부",     "expiry_priority": "high",   "expiration_date": "2026-06-06"},
]


def divider(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


# ─────────────────────────────────────────────────────
# STEP 1: _mark_priority_items() — usesPriorityItem 자동 보정
# ─────────────────────────────────────────────────────
divider(f"STEP 1: _mark_priority_items() | 오늘: {date.today()}")

plan_before = {
    "note": "임박 재료를 앞쪽 일자에 배치했어요.",
    "days": [
        {
            "label": "1일차",
            "entries": [
                {"slot": "아침",  "recipeTitle": "브로콜리 계란 스크램블"},
                {"slot": "점심",  "recipeTitle": "닭가슴살 두부 강된장 덮밥"},
                {"slot": "저녁",  "recipeTitle": "닭가슴살 채소 볶음"},
            ],
        },
        {
            "label": "2일차",
            "entries": [
                {"slot": "아침",  "recipeTitle": "그릭요거트 + 방울토마토"},
                {"slot": "점심",  "recipeTitle": "두부 된장찌개", "usesPriorityItem": False},  # → True 보정
                {"slot": "저녁",  "recipeTitle": "계란볶음밥"},
            ],
        },
    ],
}

plan_after = _mark_priority_items(plan_before, TEST_PANTRY_ITEMS)

print(f"\n  priority_names: {['계란', '브로콜리', '두부']}")
print(f"\n  {'일차':<6} {'슬롯':<6} {'recipeTitle':<28} {'기대':<8} {'실제':<8} {'결과'}")
print(f"  {'-' * 72}")

cases_step1 = [
    ("1일차", "아침",  "브로콜리 계란 스크램블",    True),
    ("1일차", "점심",  "닭가슴살 두부 강된장 덮밥",  True),
    ("1일차", "저녁",  "닭가슴살 채소 볶음",         False),
    ("2일차", "아침",  "그릭요거트 + 방울토마토",    False),
    ("2일차", "점심",  "두부 된장찌개",              True),
    ("2일차", "저녁",  "계란볶음밥",                True),
]

step1_pass = True
for day in plan_after["days"]:
    for entry in day["entries"]:
        expected = next(
            (e[3] for e in cases_step1 if e[2] == entry["recipeTitle"]), None
        )
        if expected is None:
            continue
        actual = entry.get("usesPriorityItem", False)
        ok = actual == expected
        if not ok:
            step1_pass = False
        print(
            f"  {day['label']:<6} {entry['slot']:<6} "
            f"{entry['recipeTitle']:<28} {str(expected):<8} {str(actual):<8} "
            f"{'✅' if ok else '❌'}"
        )

print(f"\n  STEP 1 결과: {'모두 통과 ✅' if step1_pass else '일부 실패 ❌'}")


# ─────────────────────────────────────────────────────
# STEP 2: _extract_constraints() — 제약 조건 추출
# ─────────────────────────────────────────────────────
divider("STEP 2: _extract_constraints() — 제약 조건 추출")

cases_step2 = [
    (TEST_USER_INPUT,              ["고단백", "저탄수"],   "고단백+저탄수 포함"),
    ("한식 위주로 간단하게",        ["한식", "간단"],       "한식+간단 포함"),
    ("저칼로리 주간 식단",          ["저칼로리", "주간"],   "저칼로리+주간 포함"),
    ("아무 키워드도 없는 문장",      [],                    "매칭 없음"),
]

print(f"\n  {'user_input':<38} {'기대':<22} {'실제':<22} {'결과'}")
print(f"  {'-' * 88}")

step2_pass = True
for query, expected, reason in cases_step2:
    actual = _extract_constraints(query)
    ok = set(actual) == set(expected)
    if not ok:
        step2_pass = False
    print(
        f"  {query[:36]:<38} {str(expected):<22} {str(actual):<22} "
        f"{'✅' if ok else '❌'}  {reason}"
    )

print(f"\n  STEP 2 결과: {'모두 통과 ✅' if step2_pass else '일부 실패 ❌'}")


# ─────────────────────────────────────────────────────
# STEP 3: verify_nutrition_goal() — 영양 합산 검증 (LLM 없음)
# selected_recipes["nutrition"] 직접 합산
# execute_meal_plan() 제거로 selected_recipes 오염 없음
# ─────────────────────────────────────────────────────
divider("STEP 3: verify_nutrition_goal() — 영양 합산 검증 (LLM 없음)")

nutrition_result = verify_nutrition_goal(TEST_SELECTED_RECIPES, TEST_NUTRITION_GOAL)

expected_totals = {
    "calories": 520 + 280 + 410,   # = 1210
    "protein":  45  + 22  + 48,    # = 115
    "carbs":    38  + 12  + 8,     # = 58
    "fat":      14  + 18  + 16,    # = 48
}

print(f"\n  [ 합산 결과 ]")
print(f"  {'영양소':<12} {'기대 current':<16} {'실제 current':<16} {'target':<10} {'unit':<6} {'결과'}")
print(f"  {'-' * 68}")

step3_pass = True
for key, unit in [("protein", "g"), ("calories", "kcal"), ("carbs", "g"), ("fat", "g")]:
    expected_current = expected_totals[key]
    actual_current   = nutrition_result[key]["current"]
    actual_target    = nutrition_result[key]["target"]
    actual_unit      = nutrition_result[key]["unit"]
    ok = actual_current == expected_current and actual_unit == unit
    if not ok:
        step3_pass = False
    print(
        f"  {key:<12} {expected_current:<16} {actual_current:<16} "
        f"{actual_target:<10} {actual_unit:<6} {'✅' if ok else '❌'}"
    )

expected_passed = False
actual_passed   = nutrition_result["passed"]
ok_passed = actual_passed == expected_passed
if not ok_passed:
    step3_pass = False
print(f"\n  passed 판정: 기대={expected_passed} 실제={actual_passed} {'✅' if ok_passed else '❌'}")
print(f"  → protein(115) < target(120) → passed=False")
print(f"\n  message  : {nutrition_result['message']}")
print(f"  warnings : {json.dumps(nutrition_result['warnings'], ensure_ascii=False)}")
print(f"\n  STEP 3 결과: {'모두 통과 ✅' if step3_pass else '일부 실패 ❌'}")


# ─────────────────────────────────────────────────────
# STEP 4: create_weekly_plan() — LLM 기반 식단 생성 (LLM 필요)
# ─────────────────────────────────────────────────────
divider("STEP 4: create_weekly_plan() — LLM 기반 식단 생성 (LLM 필요)")

plan_state = {
    "user_input":       TEST_USER_INPUT,
    "pantry_items":     TEST_PANTRY_ITEMS,
    "selected_recipes": TEST_SELECTED_RECIPES,
    "nutrition_goal":   TEST_NUTRITION_GOAL,
    "logs":             [],
}

print(f"\n  실행 중... (LLM 1회 호출, 수 초 소요 가능)")
plan = create_weekly_plan(plan_state)

print(f"\n  [ 생성된 식단 계획 ]")
print(f"  note: {plan.get('note')}")
print()

for day in plan.get("days", []):
    print(f"  {day.get('label')}")
    for entry in day.get("entries", []):
        print(
            f"    {entry.get('slot'):<6} | "
            f"{entry.get('recipeTitle', ''):<30} | "
            f"usesPriorityItem={entry.get('usesPriorityItem', False)}"
        )

days = plan.get("days", [])
ok4a = len(days) == 3
ok4b = all(len(day.get("entries", [])) == 3 for day in days)
ok4c = all(
    entry.get("slot") in ("아침", "점심", "저녁")
    for day in days
    for entry in day.get("entries", [])
)
ok4d = plan.get("note") is not None
step4_pass = ok4a and ok4b and ok4c and ok4d

print(f"\n  3일 구성 여부      : {'✅' if ok4a else '❌'} ({len(days)}일)")
print(f"  3끼 구성 여부      : {'✅' if ok4b else '❌'}")
print(f"  슬롯 한국어 여부    : {'✅' if ok4c else '❌'}")
print(f"  note 존재 여부     : {'✅' if ok4d else '❌'}")
print(f"\n  STEP 4 결과: {'✅' if step4_pass else '❌'}")


# ─────────────────────────────────────────────────────
# STEP 5: selected_recipes 오염 없음 확인 (LLM 없음)
# execute_meal_plan() 제거 후 selected_recipes가
# recipe_agent 결과 그대로 유지되는지 검증
# ─────────────────────────────────────────────────────
divider("STEP 5: selected_recipes 오염 없음 확인 (LLM 없음)")

before_count = len(TEST_SELECTED_RECIPES)

meal_result_for_step5 = meal_agent({
    "user_input":       TEST_USER_INPUT,
    "pantry_items":     TEST_PANTRY_ITEMS,
    "selected_recipes": TEST_SELECTED_RECIPES,
    "nutrition_goal":   TEST_NUTRITION_GOAL,
    "logs":             [],
})

after_recipes = meal_result_for_step5.get("selected_recipes") or []
after_count   = len(after_recipes)

# 영양 합산이 TEST_SELECTED_RECIPES 기준인지 확인
nr_step5 = meal_result_for_step5.get("nutrition_result") or {}
expected_protein_current  = 45 + 22 + 48   # = 115
expected_calories_current = 520 + 280 + 410 # = 1210

ok5a = after_count == before_count   # selected_recipes 수가 변하지 않아야 함
ok5b = nr_step5.get("protein",  {}).get("current") == expected_protein_current
ok5c = nr_step5.get("calories", {}).get("current") == expected_calories_current

step5_pass = ok5a and ok5b and ok5c

print(f"\n  [ selected_recipes 오염 여부 ]")
print(f"  meal_agent 호출 전 : {before_count}개")
print(f"  meal_agent 호출 후 : {after_count}개")
print(f"  수 변화 없음       : {'✅' if ok5a else f'❌ ({before_count} → {after_count})'}")

print(f"\n  [ 영양 계산 기준 확인 ]")
print(f"  protein  current : 기대={expected_protein_current}  실제={nr_step5.get('protein', {}).get('current')}  {'✅' if ok5b else '❌'}")
print(f"  calories current : 기대={expected_calories_current} 실제={nr_step5.get('calories', {}).get('current')} {'✅' if ok5c else '❌'}")
print(f"  → recipe_agent selected_recipes(3개) 기준으로만 합산됨")

print(f"\n  STEP 5 결과: {'✅' if step5_pass else '❌'}")


# ─────────────────────────────────────────────────────
# STEP 6: meal_agent() 전체 실행 (LLM 필요, RAG 없음)
# pantry_agent → recipe_agent → meal_agent 파이프라인
# ─────────────────────────────────────────────────────
divider("STEP 6: meal_agent() 전체 실행 (LLM 필요, RAG 없음)")

pantry_state = pantry_agent({
    "user_input":          TEST_USER_INPUT,
    "ingredient_entries":  TEST_ENTRIES,
    "logs":                [],
})
recipe_state = recipe_agent({
    **pantry_state,
    "nutrition_goal": TEST_NUTRITION_GOAL,
})

print(f"\n  실행 중... (LLM 1회 호출)")
meal_state = meal_agent({
    **recipe_state,
    "nutrition_goal": TEST_NUTRITION_GOAL,
})

meal_plan = meal_state.get("meal_plan") or {}
print(f"\n  [ meal_plan ]")
print(f"  note: {meal_plan.get('note')}")
for day in meal_plan.get("days", []):
    print(f"\n  {day.get('label')}")
    for entry in day.get("entries", []):
        print(
            f"    {entry.get('slot'):<6} | "
            f"{entry.get('recipeTitle', ''):<30} | "
            f"usesPriorityItem={entry.get('usesPriorityItem', False)}"
        )

nr = meal_state.get("nutrition_result") or {}
print(f"\n  [ nutrition_result ]")
print(json.dumps(nr, ensure_ascii=False, indent=2))

print(f"\n  [ logs (meal 노드) ]")
for log in (meal_state.get("logs") or []):
    if log.get("node") == "meal":
        print(f"  event={log['event']}")

ok6a = len(meal_plan.get("days", [])) == 3
ok6b = "protein" in nr and "calories" in nr and "carbs" in nr and "fat" in nr
ok6c = "passed" in nr and "message" in nr and "warnings" in nr
ok6d = "nutrition_result" in meal_state
ok6e = any(
    log.get("event") == "nutrition_verified"
    for log in (meal_state.get("logs") or [])
)
# selected_recipes 오염 없음 (recipe_agent 결과와 동일해야 함)
ok6f = len(meal_state.get("selected_recipes") or []) == len(recipe_state.get("selected_recipes") or [])

step6_pass = ok6a and ok6b and ok6c and ok6d and ok6e and ok6f
print(f"\n  meal_plan 3일 구성       : {'✅' if ok6a else '❌'}")
print(f"  nutrition 4개 영양소     : {'✅' if ok6b else '❌'}")
print(f"  passed/message/warnings  : {'✅' if ok6c else '❌'}")
print(f"  state nutrition_result   : {'✅' if ok6d else '❌'}")
print(f"  log nutrition_verified   : {'✅' if ok6e else '❌'}")
print(f"  selected_recipes 오염 없음: {'✅' if ok6f else '❌'}")
print(f"\n  STEP 6 결과: {'✅' if step6_pass else '❌'}")


# ─────────────────────────────────────────────────────
# STEP 7: meal_agent() — pantry_items 없음 (fallback 동작)
# ─────────────────────────────────────────────────────
divider("STEP 7: meal_agent() — pantry_items 없음 (fallback 동작)")

empty_state = {
    "user_input":       TEST_USER_INPUT,
    "pantry_items":     [],
    "selected_recipes": TEST_SELECTED_RECIPES,
    "nutrition_goal":   TEST_NUTRITION_GOAL,
    "logs":             [],
}

print(f"\n  실행 중... (LLM 1회 호출)")
empty_result = meal_agent(empty_state)

print(f"\n  meal_plan note    : {(empty_result.get('meal_plan') or {}).get('note')}")
print(f"  nutrition_result  : {list((empty_result.get('nutrition_result') or {}).keys())}")
print(f"  logs events       : {[l.get('event') for l in (empty_result.get('logs') or [])]}")

step7_pass = (
    empty_result.get("meal_plan") is not None
    and empty_result.get("nutrition_result") is not None
)
print(f"\n  STEP 7 결과: {'✅' if step7_pass else '❌'} (fallback 동작 확인)")


# ─────────────────────────────────────────────────────
# 최종 요약
# ─────────────────────────────────────────────────────
divider("최종 요약")
results_summary = [
    ("STEP 1", "_mark_priority_items() usesPriorityItem 보정",       step1_pass),
    ("STEP 2", "_extract_constraints() 제약 조건 추출",               step2_pass),
    ("STEP 3", "verify_nutrition_goal() 영양 합산 검증",              step3_pass),
    ("STEP 4", "create_weekly_plan() LLM 식단 생성",                 step4_pass),
    ("STEP 5", "selected_recipes 오염 없음 (execute_meal_plan 제거)", step5_pass),
    ("STEP 6", "meal_agent() 전체 실행",                             step6_pass),
    ("STEP 7", "meal_agent() pantry_items 없음 fallback",            step7_pass),
]
print()
for step, desc, passed in results_summary:
    print(f"  {'✅' if passed else '❌'}  {step}: {desc}")

all_passed = all(p for _, _, p in results_summary)
print(f"\n  {'🎉 전체 통과!' if all_passed else '⚠️  일부 실패 — 위 내용 확인 필요'}")