import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.agents.shopping_agent import shopping_agent, _format_quantity   # ← _format_quantity 추가

# ─────────────────────────────────────────────────────────────
# 테스트 Input 데이터
# test_meal_agent.py 동일 시나리오 (오늘: 2026-06-07)
#   재료: 닭가슴살(D+3), 계란(D+0), 브로콜리(D+1), 두부(D-1)
#   목표: 고단백 저탄수 / 2인 / 20분 이내 / 해산물 제외
# ─────────────────────────────────────────────────────────────
TEST_PANTRY_ITEMS = [
    {"name": "닭가슴살", "expiry_priority": "normal", "expiration_date": "2026-06-10"},
    {"name": "계란",     "expiry_priority": "high",   "expiration_date": "2026-06-07"},
    {"name": "브로콜리", "expiry_priority": "high",   "expiration_date": "2026-06-08"},
    {"name": "두부",     "expiry_priority": "high",   "expiration_date": "2026-06-06"},
]

TEST_SELECTED_RECIPES = [
    {
        "id":   "rcp_1",
        "name": "닭가슴살 두부 강된장 덮밥",
        "nutrition": {"calories": 520, "protein": 45, "carbs": 38, "fat": 14},
        "ingredients": [
            {"name": "닭가슴살", "amount": 200, "unit": "g"},
            {"name": "두부",     "amount": 150, "unit": "g"},
            {"name": "양파",     "amount": 100, "unit": "g"},
            {"name": "된장",     "amount": 30,  "unit": "g"},
            {"name": "현미밥",   "amount": 200, "unit": "g"},
        ],
        "score": 0.91,
    },
    {
        "id":   "rcp_2",
        "name": "브로콜리 계란 스크램블",
        "nutrition": {"calories": 280, "protein": 22, "carbs": 12, "fat": 18},
        "ingredients": [
            {"name": "브로콜리",   "amount": 150, "unit": "g"},
            {"name": "계란",       "amount": 2,   "unit": "개"},
            {"name": "올리브오일", "amount": 10,  "unit": "ml"},
            {"name": "소금",       "amount": 2,   "unit": "g"},
        ],
        "score": 0.84,
    },
    {
        "id":   "rcp_3",
        "name": "닭가슴살 두부 스테이크",
        "nutrition": {"calories": 410, "protein": 48, "carbs": 8, "fat": 16},
        "ingredients": [
            {"name": "닭가슴살", "amount": 200,  "unit": "g"},
            {"name": "두부",     "amount": 100,  "unit": "g"},
            {"name": "파프리카", "amount": 100,  "unit": "g"},
            {"name": "허브",     "amount": None, "unit": None},
        ],
        "score": 0.82,
    },
]

TEST_MEAL_PLAN = {
    "note": "임박 재료를 앞쪽 일자에 배치했어요.",
    "days": [
        {
            "label": "1일차",
            "entries": [
                {"slot": "아침", "recipeTitle": "브로콜리 계란 스크램블",    "usesPriorityItem": True},
                {"slot": "점심", "recipeTitle": "닭가슴살 두부 강된장 덮밥", "usesPriorityItem": True},
                {"slot": "저녁", "recipeTitle": "닭가슴살 두부 스테이크",    "usesPriorityItem": True},
            ],
        },
        {
            "label": "2일차",
            "entries": [
                {"slot": "아침", "recipeTitle": "그릭요거트 + 방울토마토",   "usesPriorityItem": False},  # selected_recipes에 없음
                {"slot": "점심", "recipeTitle": "닭가슴살 두부 강된장 덮밥", "usesPriorityItem": True},
                {"slot": "저녁", "recipeTitle": "브로콜리 계란 스크램블",    "usesPriorityItem": True},
            ],
        },
        {
            "label": "3일차",
            "entries": [
                {"slot": "아침", "recipeTitle": "계란 현미 주먹밥",       "usesPriorityItem": True},   # selected_recipes에 없음
                {"slot": "점심", "recipeTitle": "닭가슴살 두부 스테이크",  "usesPriorityItem": True},
                {"slot": "저녁", "recipeTitle": "닭가슴살 채소 볶음",     "usesPriorityItem": False},  # selected_recipes에 없음
            ],
        },
    ],
}


def divider(title: str):
    print(f"\n{'=' * 65}")
    print(f"  {title}")
    print(f"{'=' * 65}")


# 검증에 필요한 집합 — 입력 데이터에서만 도출
pantry_names    = {p["name"] for p in TEST_PANTRY_ITEMS if p.get("name")}
recipe_name_map = {r["name"]: r for r in TEST_SELECTED_RECIPES if r.get("name")}
used_titles     = {
    entry.get("recipeTitle", "")
    for day  in TEST_MEAL_PLAN.get("days", [])
    for entry in day.get("entries", [])
    if entry.get("recipeTitle")
}
used_ingredient_names = {
    ing["name"]
    for title in used_titles
    if title in recipe_name_map
    for ing in recipe_name_map[title].get("ingredients", [])
    if ing.get("name")
}
expected_missing_names = used_ingredient_names - pantry_names


# ─────────────────────────────────────────────────────────────
# STEP 1: shopping_agent() 정상 실행 — state 구조 검증
# ─────────────────────────────────────────────────────────────
divider("STEP 1: shopping_agent() 정상 실행 — state 구조 검증")

result  = shopping_agent({
    "meal_plan":        TEST_MEAL_PLAN,
    "selected_recipes": TEST_SELECTED_RECIPES,
    "pantry_items":     TEST_PANTRY_ITEMS,
    "logs":             [],
})
missing       = result.get("missing_ingredients") or []
missing_names = {m["name"] for m in missing}

print(f"\n  [ missing_ingredients ]")
print(json.dumps(missing, ensure_ascii=False, indent=2))

required_keys = {"name", "amount", "unit", "needed_by"}
ok1a = "missing_ingredients" in result
ok1b = isinstance(missing, list)
ok1c = all(required_keys.issubset(m.keys()) for m in missing)
ok1d = all(isinstance(m["needed_by"], list) for m in missing)

step1_pass = ok1a and ok1b and ok1c and ok1d

print(f"\n  missing_ingredients 키 존재              : {'✅' if ok1a else '❌'}")
print(f"  리스트 타입 여부                          : {'✅' if ok1b else '❌'} ({len(missing)}개)")
print(f"  필수 필드(name/amount/unit/needed_by) 존재: {'✅' if ok1c else '❌'}")
print(f"  needed_by 리스트 타입 여부                : {'✅' if ok1d else '❌'}")
print(f"\n  STEP 1 결과: {'✅' if step1_pass else '❌'}")


# ─────────────────────────────────────────────────────────────
# STEP 2: pantry 재료 제외 검증
# pantry_items의 재료가 missing_ingredients에 있으면 안 됨
# ─────────────────────────────────────────────────────────────
divider("STEP 2: pantry 재료 제외 검증")

leaked_names = pantry_names & missing_names   # 있으면 ❌

step2_pass = len(leaked_names) == 0

print(f"\n  pantry 재료  : {sorted(pantry_names)}")
print(f"  missing 재료 : {sorted(missing_names)}")
print(f"  교집합       : {sorted(leaked_names)}  {'✅ (없음)' if not leaked_names else '❌ (있으면 안 됨)'}")
print(f"\n  STEP 2 결과: {'✅' if step2_pass else '❌'}")


# ─────────────────────────────────────────────────────────────
# STEP 3: 미보유 재료 포함 검증
# 식단에서 사용된 레시피 재료 중 pantry에 없는 것이 missing에 있어야 함
# ─────────────────────────────────────────────────────────────
divider("STEP 3: 미보유 재료 포함 검증")

ok3 = expected_missing_names == missing_names

step3_pass = ok3

print(f"\n  meal_plan 사용 레시피 재료 : {sorted(used_ingredient_names)}")
print(f"  pantry 재료                : {sorted(pantry_names)}")
print(f"  기대 missing 집합          : {sorted(expected_missing_names)}")
print(f"  실제 missing 집합          : {sorted(missing_names)}")

if not step3_pass:
    extra   = missing_names - expected_missing_names
    lacking = expected_missing_names - missing_names
    if extra:
        print(f"\n  ❌ 초과 항목 (있으면 안 됨): {extra}")
    if lacking:
        print(f"\n  ❌ 누락 항목 (있어야 함)  : {lacking}")

print(f"\n  STEP 3 결과: {'✅' if step3_pass else '❌'}")


# ─────────────────────────────────────────────────────────────
# STEP 4: needed_by 유효성 검증
# needed_by의 각 레시피명이 meal_plan의 recipeTitle 중 하나여야 함
# ─────────────────────────────────────────────────────────────
divider("STEP 4: needed_by 유효성 검증")

print(f"\n  {'재료명':<14} {'needed_by':<52} {'결과'}")
print(f"  {'-' * 74}")

step4_pass = True
for m in missing:
    invalid = [r for r in m["needed_by"] if r not in used_titles]
    ok = len(invalid) == 0
    if not ok:
        step4_pass = False
    print(
        f"  {m['name']:<14} {str(m['needed_by']):<52} "
        f"{'✅' if ok else f'❌ {invalid}'}"
    )

print(f"\n  STEP 4 결과: {'✅' if step4_pass else '❌'}")


# ─────────────────────────────────────────────────────────────
# STEP 5: 이름 오름차순 정렬 검증
# ─────────────────────────────────────────────────────────────
divider("STEP 5: 이름 오름차순 정렬 검증")

actual_order   = [m["name"] for m in missing]
expected_order = sorted(actual_order)
ok5 = actual_order == expected_order

step5_pass = ok5

print(f"\n  실제 순서 : {actual_order}")
print(f"  기대 순서 : {expected_order}")
print(f"\n  STEP 5 결과: {'✅' if step5_pass else '❌'}")


# ─────────────────────────────────────────────────────────────
# STEP 6: log 검증
# missing_calculated 이벤트 + result 필드 구조 확인
# ─────────────────────────────────────────────────────────────
divider("STEP 6: log 검증")

logs       = result.get("logs") or []
log_entry  = next((l for l in logs if l.get("event") == "missing_calculated"), None)
log_result = (log_entry.get("result") or {}) if log_entry else {}

ok6a = log_entry is not None
ok6b = log_result.get("missing_count")     == len(missing)
ok6c = set(log_result.get("missing_names") or []) == missing_names
ok6d = "used_recipe_count" in log_result
ok6e = "warnings" in log_result

step6_pass = ok6a and ok6b and ok6c and ok6d and ok6e

print(f"\n  log missing_calculated 존재   : {'✅' if ok6a else '❌'}")
print(f"  missing_count == len(missing)  : {'✅' if ok6b else '❌'} ({log_result.get('missing_count', 'N/A')}개)")
print(f"  missing_names 집합 일치        : {'✅' if ok6c else '❌'}")
print(f"  used_recipe_count 필드 존재    : {'✅' if ok6d else '❌'} ({log_result.get('used_recipe_count', 'N/A')}개)")
print(f"  warnings 필드 존재             : {'✅' if ok6e else '❌'}")
print(f"\n  STEP 6 결과: {'✅' if step6_pass else '❌'}")


# ─────────────────────────────────────────────────────────────
# STEP 7: 엣지케이스 — pantry_items=[]
# 냉장고가 비어있으면 사용 레시피 재료 전체가 missing
# ─────────────────────────────────────────────────────────────
divider("STEP 7: 엣지케이스 — pantry_items=[]")

result_empty = shopping_agent({
    "meal_plan":        TEST_MEAL_PLAN,
    "selected_recipes": TEST_SELECTED_RECIPES,
    "pantry_items":     [],
    "logs":             [],
})
missing_empty       = result_empty.get("missing_ingredients") or []
missing_empty_names = {m["name"] for m in missing_empty}

ok7 = missing_empty_names == used_ingredient_names

step7_pass = ok7

print(f"\n  기대 (사용 레시피 재료 전체): {sorted(used_ingredient_names)}")
print(f"  실제                        : {sorted(missing_empty_names)}")

if not step7_pass:
    print(f"\n  ❌ 초과: {missing_empty_names - used_ingredient_names}")
    print(f"  ❌ 누락: {used_ingredient_names - missing_empty_names}")

print(f"\n  STEP 7 결과: {'✅' if step7_pass else '❌'}")


# ─────────────────────────────────────────────────────────────
# STEP 8: 엣지케이스 — meal_plan={}
# 식단이 없으면 부족 재료도 없어야 함
# ─────────────────────────────────────────────────────────────
divider("STEP 8: 엣지케이스 — meal_plan={}")

result_no_plan  = shopping_agent({
    "meal_plan":        {},
    "selected_recipes": TEST_SELECTED_RECIPES,
    "pantry_items":     TEST_PANTRY_ITEMS,
    "logs":             [],
})
missing_no_plan = result_no_plan.get("missing_ingredients") or []

ok8 = len(missing_no_plan) == 0

step8_pass = ok8

print(f"\n  meal_plan={{}} → missing_ingredients 빈 리스트 기대")
print(f"  실제 개수: {len(missing_no_plan)}개")
print(f"\n  STEP 8 결과: {'✅' if step8_pass else '❌'}")


# ─────────────────────────────────────────────────────────────
# STEP 9: _format_quantity() 출력 테스트
# ─────────────────────────────────────────────────────────────
divider("STEP 9: _format_quantity() 출력 테스트")

FORMAT_CASES = [
    # (amount,   unit,       기대 출력,   설명)
    (200,        "g",        "200g",      "정수 + 단위"),
    (1.5,        "kg",       "1.5kg",     "소수 + 단위"),
    (3.0,        "개",       "3개",       "정수형 소수(3.0) → 정수(3) 변환"),
    (0.5,        "ml",       "0.5ml",     "소수점 ml"),
    (3,          None,       "3",         "단위 없음"),
    (100,        "ml",       "100ml",     "정수 ml"),
    (2,          "개",       "2개",       "정수 개"),
    (6,          "작은술",   "6작은술",   "한글 단위"),
    (1,          "큰술",     "1큰술",     "한글 단위"),
    (0,          "g",        "0g",        "amount=0"),
    (None,       "g",        None,        "amount=None → None 반환"),
    (None,       None,       None,        "amount=None, unit=None → None 반환"),
    (None,       "ml",       None,        "amount=None, unit=ml → None 반환"),
    (12,         "g",        "12g",       "'g+3' → 'g' 정규화 후"),
    (400,        "g",        "400g",      "정수 대용량"),
    (1.0,        "kg",       "1kg",       "1.0kg → 1kg 변환"),
]

print(f"\n  {'amount':<8} {'unit':<8} {'기대 출력':<12} {'실제 출력':<12} {'결과':<4} 설명")
print(f"  {'-' * 72}")

step9_pass = True

for amount, unit, expected, desc in FORMAT_CASES:
    actual = _format_quantity(amount, unit)
    ok     = actual == expected
    if not ok:
        step9_pass = False
    print(
        f"  {str(amount):<8} {str(unit):<8} "
        f"{str(expected):<12} {str(actual):<12} "
        f"{'✅' if ok else '❌':<4} {desc}"
    )

print(f"\n  STEP 9 결과: {'✅' if step9_pass else '❌'}")


# ─────────────────────────────────────────────────────────────
# STEP 10: 재료명 띄어쓰기 정규화 검증
# "닭  가슴살" / " 닭가슴살 " 등이 pantry의 "닭가슴살"과 동일하게 인식되어야 함
# ─────────────────────────────────────────────────────────────
divider("STEP 10: 재료명 띄어쓰기 정규화 검증")

# 재료명에 의도적으로 띄어쓰기 오류를 넣은 데이터
WHITESPACE_PANTRY = [
    {"name": "닭가슴살"},   # 정상
    {"name": " 두부 "},     # 앞뒤 공백
]

WHITESPACE_RECIPES = [
    {
        "name": "테스트 레시피",
        "ingredients": [
            {"name": "닭 가슴살",  "amount": 200, "unit": "g"},   # 내부 공백 → pantry "닭가슴살"과 달라야 감지
            {"name": " 두부",      "amount": 100, "unit": "g"},   # 앞 공백 → pantry " 두부 "와 매칭
            {"name": "양파",       "amount": 100, "unit": "g"},   # pantry에 없음 → missing
        ],
    },
]

WHITESPACE_MEAL_PLAN = {
    "days": [{
        "label": "1일차",
        "entries": [{"slot": "점심", "recipeTitle": "테스트 레시피"}],
    }]
}

ws_result  = shopping_agent({
    "meal_plan":        WHITESPACE_MEAL_PLAN,
    "selected_recipes": WHITESPACE_RECIPES,
    "pantry_items":     WHITESPACE_PANTRY,
    "logs":             [],
})
ws_missing       = ws_result.get("missing_ingredients") or []
ws_missing_names = {m["name"] for m in ws_missing}

# "닭 가슴살" → 정규화 → "닭 가슴살" (단일 공백)
# pantry "닭가슴살" → 정규화 → "닭가슴살"
# 띄어쓰기가 다르면 다른 재료 → missing에 포함될 수 있음
# 이 케이스는 의도적으로 감지: "닭 가슴살" ≠ "닭가슴살" 은 현재 스펙상 다른 재료
# → 실제 LLM이 일관된 이름을 쓰는지 확인하는 것이 목적

ok10a = "양파" in ws_missing_names            # pantry에 없는 재료는 반드시 missing
ok10b = " 두부 " not in ws_missing_names      # 앞뒤 공백 정규화 → missing에서 제외
ok10c = " 두부" not in ws_missing_names       # 앞 공백 정규화 → missing에서 제외

step10_pass = ok10a and ok10b and ok10c

print(f"\n  whitespace 포함 pantry : {[p['name'] for p in WHITESPACE_PANTRY]}")
print(f"  whitespace 포함 재료명 : {[i['name'] for i in WHITESPACE_RECIPES[0]['ingredients']]}")
print(f"  실제 missing           : {sorted(ws_missing_names)}")
print(f"\n  '양파' missing 포함 (pantry에 없음)    : {'✅' if ok10a else '❌'}")
print(f"  ' 두부 ' missing 제외 (앞뒤 공백 정규화): {'✅' if ok10b else '❌'}")
print(f"  ' 두부'  missing 제외 (앞 공백 정규화)  : {'✅' if ok10c else '❌'}")
print(f"\n  STEP 10 결과: {'✅' if step10_pass else '❌'}")


# ─────────────────────────────────────────────────────────────
# 최종 요약
# ─────────────────────────────────────────────────────────────
divider("최종 요약")

results_summary = [
    ("STEP 1",  "shopping_agent() 정상 실행 — state 구조 검증",   step1_pass),
    ("STEP 2",  "pantry 재료 제외 검증",                          step2_pass),
    ("STEP 3",  "미보유 재료 포함 검증",                          step3_pass),
    ("STEP 4",  "needed_by 유효성 검증",                          step4_pass),
    ("STEP 5",  "이름 오름차순 정렬 검증",                        step5_pass),
    ("STEP 6",  "log 검증",                                       step6_pass),
    ("STEP 7",  "엣지케이스: pantry_items=[]",                    step7_pass),
    ("STEP 8",  "엣지케이스: meal_plan={}",                       step8_pass),
    ("STEP 9",  "_format_quantity() 출력 테스트",                 step9_pass),
    ("STEP 10", "재료명 띄어쓰기 정규화 검증",                    step10_pass),
]
print()
for step, desc, passed in results_summary:
    print(f"  {'✅' if passed else '❌'}  {step}: {desc}")

all_passed = all(p for _, _, p in results_summary)
print(f"\n  {'🎉 전체 통과!' if all_passed else '⚠️  일부 실패 — 위 내용 확인 필요'}")