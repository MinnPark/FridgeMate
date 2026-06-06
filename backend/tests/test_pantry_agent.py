import json
from datetime import date
from app.tools.pantry_tools import (
    parse_amount_unit,
    calculate_days_left,
    expiry_priority_from_days,
    freshness_from_days,
    build_pantry_items,
    build_pantry_analysis,
)
from app.agents.pantry_agent import pantry_agent

# ─────────────────────────────────────────────
# 테스트 Input 데이터 (오늘: 2026-06-05 기준)
# ─────────────────────────────────────────────
TEST_ENTRIES = [
    {"name": "닭가슴살", "amount": "500g",  "expiration_date": "2026-06-10", "storage_type": "냉장 보관"},
    {"name": "계란",     "amount": "10개",  "expiration_date": "2026-06-07", "storage_type": "냉장 보관"},
    {"name": "브로콜리", "amount": "300g",  "expiration_date": "2026-06-08", "storage_type": "냉장 보관"},
    {"name": "두부",     "amount": "1모",   "expiration_date": "2026-06-06", "storage_type": "냉장 보관"},
]

def divider(title: str):
    print(f"\n{'='*50}")
    print(f"  {title}")
    print(f"{'='*50}")

# ─────────────────────────────────────────────
# STEP 1: parse_amount_unit 확인
# ─────────────────────────────────────────────
divider("STEP 1: parse_amount_unit()")
for e in TEST_ENTRIES:
    amount_val, unit = parse_amount_unit(e["amount"])
    print(f"  {e['name']}: '{e['amount']}' → amount={amount_val}, unit='{unit}'")

# ─────────────────────────────────────────────
# STEP 2: calculate_days_left 확인
# ─────────────────────────────────────────────
divider(f"STEP 2: calculate_days_left() | 오늘: {date.today()}")
for e in TEST_ENTRIES:
    days = calculate_days_left(e["expiration_date"])
    print(f"  {e['name']}: '{e['expiration_date']}' → {days}일 남음")

# ─────────────────────────────────────────────
# STEP 3: expiry_priority + freshness 확인
# ─────────────────────────────────────────────
divider("STEP 3: expiry_priority + freshness 계산")
print(f"  {'재료':<10} {'남은일':<8} {'expiry_priority':<16} {'freshness'}")
print(f"  {'-'*50}")
for e in TEST_ENTRIES:
    days = calculate_days_left(e["expiration_date"])
    priority = expiry_priority_from_days(days)
    freshness = freshness_from_days(days)
    print(f"  {e['name']:<10} {str(days)+'일':<8} {priority:<16} {freshness}")

# ─────────────────────────────────────────────
# STEP 4: build_pantry_items 확인
# ─────────────────────────────────────────────
divider("STEP 4: build_pantry_items() - 다른 agent용")
pantry_items = build_pantry_items(TEST_ENTRIES)
print(json.dumps(pantry_items, ensure_ascii=False, indent=2))

# ─────────────────────────────────────────────
# STEP 5: build_pantry_analysis 확인
# ─────────────────────────────────────────────
divider("STEP 5: build_pantry_analysis() - UI PantryCard용")
pantry_analysis = build_pantry_analysis(pantry_items)
print(json.dumps(pantry_analysis, ensure_ascii=False, indent=2))

# ─────────────────────────────────────────────
# STEP 6: pantry_agent 전체 실행
# ─────────────────────────────────────────────
divider("STEP 6: pantry_agent() - 최종 state 확인")
test_state = {
    "user_input": "냉장고에 닭가슴살, 계란, 브로콜리, 두부 있어. 고단백 저탄수 식단 짜줘",
    "budget_limit": 100000,
    "ingredient_entries": TEST_ENTRIES,
    "logs": [],
}

result = pantry_agent(test_state)

print("\n[ pantry_items ]")
print(json.dumps(result["pantry_items"], ensure_ascii=False, indent=2))

print("\n[ pantry_analysis ]")
print(json.dumps(result["pantry_analysis"], ensure_ascii=False, indent=2))

print("\n[ logs ]")
print(json.dumps(result["logs"], ensure_ascii=False, indent=2))