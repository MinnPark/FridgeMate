import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
from datetime import date

from app.agents.pantry_agent import pantry_agent
from app.agents.recipe_agent import _build_query, choose_rag_strategy, recipe_agent
from app.rag.integration import REQUIRED_CONTRACT_KEYS

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

# chatAdapter.ts mapRequestToChat() 가 생성하는 message 와 동일한 형태
TEST_USER_INPUT = (
    "냉장고에 닭가슴살, 계란, 브로콜리, 두부 있어. 고단백 저탄수. "
    "2인분, 조리 20분 이내, 칼로리 1700kcal, 단백질 120g, "
    "해산물 제외, 배송 freshness, goal 모드. 식단 짜줘"
)


def divider(title: str):
    print(f"\n{'=' * 55}")
    print(f"  {title}")
    print(f"{'=' * 55}")


# ─────────────────────────────────────────────────────
# STEP 1: choose_rag_strategy() 테스트
# 기준: 공백 제거 후 길이 < 10 → HyDE / >= 10 → RAG-Fusion
# ─────────────────────────────────────────────────────
divider(f"STEP 1: choose_rag_strategy() | threshold=10 | 오늘: {date.today()}")

cases = [
    ("두부",                                  "HyDE",       "2자  < 10"),
    ("계란 두부",                              "HyDE",       "4자  < 10 (공백제거)"),
    ("두부 고단백 한식",                        "HyDE",       "7자  < 10 (공백제거)"),
    ("두부브로콜리계란닭가",                     "RAG-Fusion", "10자 >= 10"),  # 9자→10자 수정
    ("닭가슴살 브로콜리 고단백 저탄수 식단 짜줘", "RAG-Fusion", "공백제거 후 >= 10"),
]

print(f"\n  {'쿼리':<42} {'기대':<12} {'실제':<12} {'공백제거 길이':<6} {'결과'}")
print(f"  {'-' * 82}")

step1_pass = True
for query, expected, reason in cases:
    actual = choose_rag_strategy(query)
    length = len(query.replace(" ", ""))
    ok = "✅" if actual == expected else "❌"
    if actual != expected:
        step1_pass = False
    print(f"  {query:<42} {expected:<12} {actual:<12} {length}자  {reason}  {ok}")

print(f"\n  STEP 1 결과: {'모두 통과 ✅' if step1_pass else '일부 실패 ❌'}")


# ─────────────────────────────────────────────────────
# STEP 2: pantry_agent 선행 실행 → pantry_items 생성
# recipe_agent 의 실제 input 을 만들기 위해 선행 실행
# ─────────────────────────────────────────────────────
divider(f"STEP 2: pantry_agent() 선행 실행 → pantry_items 확인 | 오늘: {date.today()}")

pantry_state = pantry_agent({
    "user_input": TEST_USER_INPUT,
    "ingredient_entries": TEST_ENTRIES,
    "logs": [],
})
pantry_items = pantry_state["pantry_items"]

print(f"\n  {'재료':<12} {'expiry_priority':<16} {'expiration_date'}")
print(f"  {'-' * 48}")
for item in pantry_items:
    print(f"  {item['name']:<12} {item['expiry_priority']:<16} {item.get('expiration_date')}")

priority_names = [i["name"] for i in pantry_items if i.get("expiry_priority") == "high"]
print(f"\n  priority(high) 재료: {priority_names}")
print(f"  기대값: ['계란', '브로콜리', '두부'] (D+1, D+2, D+0)")
step2_ok = set(priority_names) == {"계란", "브로콜리", "두부"}
print(f"  STEP 2 결과: {'✅' if step2_ok else '❌'}")


# ─────────────────────────────────────────────────────
# STEP 3: _build_query() - expiry_priority='high' 있는 경우
# ─────────────────────────────────────────────────────
divider("STEP 3: _build_query() - expiry_priority='high' 재료 있음")

state_with_priority = {
    **pantry_state,
    "user_input": TEST_USER_INPUT,
}
query_priority = _build_query(state_with_priority)
length_priority = len(query_priority.replace(" ", ""))
strategy_priority = choose_rag_strategy(query_priority)

print(f"\n  생성된 쿼리 : '{query_priority}'")
print(f"  공백제거 길이: {length_priority}자")
print(f"  선택 전략   : {strategy_priority}")
print(f"\n  기대: 쿼리 앞부분에 priority 재료 포함, 전략=RAG-Fusion")
ok3a = all(name in query_priority for name in priority_names)
ok3b = strategy_priority == "RAG-Fusion"
print(f"  priority 재료 쿼리 포함: {'✅' if ok3a else '❌'}")
print(f"  전략 RAG-Fusion 여부  : {'✅' if ok3b else '❌'}")
step3_ok = ok3a and ok3b
print(f"  STEP 3 결과: {'✅' if step3_ok else '❌'}")


# ─────────────────────────────────────────────────────
# STEP 4: _build_query() - expiry_priority='high' 없는 경우
# ─────────────────────────────────────────────────────
divider("STEP 4: _build_query() - expiry_priority='high' 재료 없음 (전체 재료 폴백)")

all_normal_items = [
    {"name": "닭가슴살", "amount": 500.0, "unit": "g",  "expiry_priority": "normal", "expiration_date": "2026-06-20", "storage_type": "냉장 보관"},
    {"name": "계란",     "amount": 10.0,  "unit": "개", "expiry_priority": "normal", "expiration_date": "2026-06-25", "storage_type": "냉장 보관"},
]
state_all_normal = {
    "pantry_items": all_normal_items,
    "user_input": "고단백 저탄수 식단 짜줘",
}
query_normal = _build_query(state_all_normal)
print(f"\n  전체 재료 normal → 전체 이름 사용")
print(f"  생성된 쿼리: '{query_normal}'")
print(f"  선택 전략  : {choose_rag_strategy(query_normal)}")
step4_ok = "닭가슴살" in query_normal and "계란" in query_normal
print(f"  STEP 4 결과: {'✅' if step4_ok else '❌'} (전체 재료 포함 여부)")


# ─────────────────────────────────────────────────────
# STEP 5: _build_query() - pantry_items 없는 경우
# ─────────────────────────────────────────────────────
divider("STEP 5: _build_query() - pantry_items 없음 (user_input 만 반환)")

state_empty_pantry = {
    "pantry_items": [],
    "user_input": "식단 짜줘",
}
query_empty = _build_query(state_empty_pantry)
print(f"\n  pantry_items=[] → user_input 만 사용")
print(f"  생성된 쿼리: '{query_empty}'")
step5_ok = query_empty == "식단 짜줘"
print(f"  STEP 5 결과: {'✅' if step5_ok else '❌'} (user_input 그대로 반환 여부)")


# ─────────────────────────────────────────────────────
# STEP 6: recipe_agent() 전체 실행 - 정상 케이스
# ChromaDB + bge-m3 embedder 연결 필요
# ─────────────────────────────────────────────────────
divider("STEP 6: recipe_agent() - 정상 실행 (ChromaDB 연결 필요)")

full_state = {
    **pantry_state,
    "user_input": TEST_USER_INPUT,
}

print(f"\n  실행 중... (RAG 검색 포함, 수 초 소요 가능)")
result = recipe_agent(full_state)

# recipe_search_trace 확인
trace = result.get("recipe_search_trace") or {}
print(f"\n[ recipe_search_trace ]")
print(json.dumps(trace, ensure_ascii=False, indent=2))

# selected_recipes 확인
selected = result.get("selected_recipes") or []
print(f"\n[ selected_recipes ] ({len(selected)}개)")
for i, r in enumerate(selected, 1):
    print(f"\n  레시피 {i}: {r.get('name')}")
    print(f"    id          : {r.get('id')}")
    print(f"    text        : {r.get('text')}")
    print(f"    score       : {r.get('score')}")
    print(f"    final_score : {r.get('final_score')}")
    print(f"    ingredients : {[ing.get('name') for ing in r.get('ingredients', [])]}")
    print(f"    nutrition   : {r.get('nutrition')}")
    print(f"    citation_url: {str(r.get('citation_url', ''))[:50]}")

# 계약 키 검증
print(f"\n[ 계약 키 검증 (REQUIRED_CONTRACT_KEYS) ]")
contract_ok = True
for r in selected:
    missing = [k for k in REQUIRED_CONTRACT_KEYS if k not in r]
    if missing:
        print(f"  ❌ '{r.get('name')}' 누락 키: {missing}")
        contract_ok = False
    else:
        print(f"  ✅ '{r.get('name')}' 계약 통과")

# logs 확인
print(f"\n[ logs ]")
print(json.dumps(result.get("logs"), ensure_ascii=False, indent=2))

step6_ok = (
    len(selected) > 0
    and trace.get("strategy") in ("HyDE", "RAG-Fusion", "Basic-RAG")
    and contract_ok
)
print(f"\n  STEP 6 결과: {'✅' if step6_ok else '❌'}")
if not step6_ok:
    print(f"  → 레시피 수  : {len(selected)}")
    print(f"  → 전략       : {trace.get('strategy')}")
    print(f"  → 계약 통과  : {contract_ok}")


# ─────────────────────────────────────────────────────
# STEP 7: recipe_agent() - pantry_items 없음 (조기 반환)
# ─────────────────────────────────────────────────────
divider("STEP 7: recipe_agent() - pantry_items 없음 (조기 반환)")

empty_state = {
    "user_input": TEST_USER_INPUT,
    "pantry_items": [],
    "logs": [],
}
empty_result = recipe_agent(empty_state)

print(f"\n  selected_recipes   : {empty_result.get('selected_recipes')}")
print(f"  recipe_search_trace: {empty_result.get('recipe_search_trace')}")
print(f"  logs: {json.dumps(empty_result.get('logs'), ensure_ascii=False)}")

step7_ok = (
    empty_result.get("selected_recipes") == []
    and empty_result.get("recipe_search_trace", {}).get("strategy") == "none"
    and any(
        log.get("event") == "skipped"
        for log in (empty_result.get("logs") or [])
    )
)
print(f"\n  STEP 7 결과: {'✅' if step7_ok else '❌'} (조기 반환 동작 확인)")


# ─────────────────────────────────────────────────────
# 최종 요약
# ─────────────────────────────────────────────────────
divider("최종 요약")
results_summary = [
    ("STEP 1", "choose_rag_strategy() 전략 선택",    step1_pass),
    ("STEP 2", "pantry_agent() priority 재료 식별",  step2_ok),
    ("STEP 3", "_build_query() priority 재료 포함",  step3_ok),
    ("STEP 4", "_build_query() 전체 재료 폴백",      step4_ok),
    ("STEP 5", "_build_query() pantry 없음",         step5_ok),
    ("STEP 6", "recipe_agent() 정상 실행",           step6_ok),
    ("STEP 7", "recipe_agent() 조기 반환",           step7_ok),
]
print()
for step, desc, passed in results_summary:
    print(f"  {'✅' if passed else '❌'}  {step}: {desc}")

all_passed = all(p for _, _, p in results_summary)
print(f"\n  {'🎉 전체 통과!' if all_passed else '⚠️  일부 실패 — 위 내용 확인 필요'}")