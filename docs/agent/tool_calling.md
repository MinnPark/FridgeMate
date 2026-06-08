# FridgeMate Tool Calling 가이드

## 개요

FridgeMate는 LangChain의 **Tool Calling** 기능을 활용하여  
LLM이 상황에 따라 필요한 도구를 선택적으로 호출합니다.

---

## 아키텍처

```
프론트엔드
    ↓  POST /chat/tool
백엔드 main.py
    ↓  ① 파이프라인 실행 (LangGraph)
    ↓  ② LLM + tools 조건부 바인딩
    ↓  ③ LLM이 tool 호출 여부 판단
    ↓  ④ tool 실행 (선택적)
    ↓  ⑤ 결과 반환
프론트엔드
```

---

## Tool 목록

### 1. `verify_nutrition_goal_tool`
> 레시피의 영양소가 사용자 목표를 충족하는지 검증

```python
# 호출 조건
nutrition_goal = {"protein_target": 120, "calorie_target": 1700}
# → 사용자가 단백질/칼로리 목표를 입력했을 때만 바인딩

# 입력
{
    "recipes":  [...],   # 선택된 레시피 목록
    "goal":     {...},   # 영양 목표
    "num_days": 3        # 식단 기간
}

# 출력
{
    "protein":  {"current": 118, "target": 120, "unit": "g"},
    "calories": {"current": 1650, "target": 1700, "unit": "kcal"},
    "passed":   True,
    "warnings": []
}
```

---

### 2. `search_coupang_products_tool`
> 부족한 재료를 쿠팡에서 검색하여 장보기 목록 생성

```python
# 호출 조건
mode != "today"
# → today 모드는 당일 요리 → 장보기 불필요

# 입력
{
    "missing_ingredients": [
        {"name": "닭가슴살", "amount": 200, "unit": "g"}
    ]
}

# 출력
[
    {
        "name":     "닭가슴살",
        "product":  "하림 닭가슴살 200g",
        "price":    4500,
        "url":      "https://coupang.com/..."
    }
]
```

---

## 조건부 바인딩 로직

```python
# main.py
tools = []

# 영양 목표 있을 때만 verify tool 포함
if nutrition_goal:
    tools.append(verify_nutrition_goal_tool)

# today 제외한 모드만 search tool 포함
if mode != "today":
    tools.append(search_coupang_products_tool)

# tools가 있을 때만 bind
llm_with_tools = llm.bind_tools(tools) if tools else llm
```

---

## 모드별 동작

| 모드       | verify tool | search tool | 설명                        |
|-----------|:-----------:|:-----------:|-----------------------------|
| `today`   | 조건부       | ❌          | 당일 요리, 장보기 불필요      |
| `weekend` | 조건부       | ✅          | 주말 요리, 장보기 필요        |
| `mealprep`| 조건부       | ✅          | 밀프렙, 장보기 필요           |
| `goal`    | 조건부       | ✅          | 목표 달성, 장보기 필요        |

> **조건부** = 사용자가 단백질/칼로리 목표 입력 시에만 활성화

---

## 전체 실행 흐름

```
① 파이프라인 (LangGraph)
   pantry_agent  → 재료 분석
   recipe_agent  → 레시피 검색
   meal_agent    → 식단 구성
   shopping_agent→ 부족재료 계산 (today 모드 스킵)

② Tool Binding
   nutrition_goal 있음 → verify tool 추가
   mode != today       → search tool 추가
   llm.bind_tools(tools)

③ LLM 판단
   SystemMessage: TOOL_SYSTEM_PROMPT
   HumanMessage:  파이프라인 결과 요약
   → LLM이 tool 호출 여부 자율 판단

④ Tool 실행
   verify_nutrition_goal_tool → 영양 검증
   search_coupang_products_tool → 쿠팡 검색

⑤ 응답 반환
   {
     ...pipeline_result,
     "tool_calls_made": ["verify...", "search..."],
     "tool_results":    {...},
     "fallback":        false
   }
```

---

## fallback 처리

```python
# get_llm() 실패 시 (provider=mock 등)
# → tool 없이 파이프라인 결과만 반환
{
    "tool_calls_made": [],
    "fallback":        True,
    "fallback_reason": "Tool Calling 미지원 provider: mock"
}
```

---

## 환경 설정

```bash
# backend/.env

# OpenRouter (권장)
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL_DEFAULT=anthropic/claude-sonnet-4-5

# 또는 OpenAI
FRIDGEMATE_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...

# 또는 Anthropic
FRIDGEMATE_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

---

## 새 Tool 추가 방법

### 1. tool 정의
```python
# backend/app/tools/my_tool.py
from langchain_core.tools import tool

@tool
def my_new_tool(input: str) -> dict:
    """
    Tool 설명 (LLM이 이 설명을 보고 호출 여부 판단)

    Args:
        input: 입력값 설명
    Returns:
        결과 설명
    """
    return {"result": ...}
```

### 2. 조건부 바인딩 추가
```python
# backend/app/main.py
from app.tools.my_tool import my_new_tool

# 조건에 맞을 때만 추가
if some_condition:
    tools.append(my_new_tool)
```

### 3. tool 실행 핸들러 추가
```python
elif name == "my_new_tool":
    args = {"input": some_value}
```

---

## API 테스트

```powershell
# Swagger UI
http://127.0.0.1:8000/docs

# 직접 호출
Invoke-RestMethod -Uri "http://127.0.0.1:8000/chat/tool" `
  -Method POST `
  -ContentType "application/json" `
  -Body '{
    "message": "냉장고에 계란, 닭가슴살 있어",
    "mode": "goal",
    "protein_target_gram": 120,
    "calorie_target_kcal": 1700
  }'
```

### 정상 응답 확인 포인트
```json
{
  "fallback": false,
  "tool_calls_made": [
    "verify_nutrition_goal_tool",
    "search_coupang_products_tool"
  ],
  "tool_results": { "..." },
  "missing_ingredients": [ "..." ]
}
```