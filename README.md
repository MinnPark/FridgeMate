# FridgeMate AI

FridgeMate AI는 냉장고 재료 입력부터 식단 추천, 레시피 검색, 부족 재료 산출, 쿠팡 장바구니 후보 생성까지 연결하는 AI Agent MVP입니다.

## 프로젝트 조건 매핑

- 고급 Prompt Engineering: Supervisor, Plan-and-Execute, ReAct, Reflexion, HyDE, RAG-Fusion
- Function Calling / Tool Calling: pantry parsing, nutrition lookup, missing ingredient calculation, shopping search, cart deeplink
- RAG + VectorDB: Recipe Agent에 ChromaDB 연결 지점을 분리해 둔 mock RAG 구조
- Agent 구조: Orchestrator, Meal Agent, Recipe Agent, Shopping Agent

## 구조

```text
backend/
  app/
    main.py
    graph/
      state.py
      orchestrator.py
    agents/
      meal_agent.py
      recipe_agent.py
      shopping_agent.py
    prompts/
    tools/
    schemas/
```

## 실행

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"냉장고에 두부, 계란, 애호박이 있어. 고단백 한식 식단 짜줘","budget_limit":30000}'
```

현재 코드는 외부 API 없이 agent 흐름을 보여주는 mock MVP입니다. 이후 Claude, Cohere embedding, ChromaDB, PostgreSQL, Coupang 연동을 각 tool 함수 내부에 연결하면 됩니다.
