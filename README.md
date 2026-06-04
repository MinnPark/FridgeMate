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
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Recipe Agent를 실제 ChromaDB VectorDB에 연결할 때만 선택 의존성을 추가로 설치합니다.

```bash
pip install -r requirements-rag.txt
```

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"냉장고에 두부, 계란, 애호박이 있어. 고단백 한식 식단 짜줘","budget_limit":30000}'
```

현재 코드는 외부 API 없이 agent 흐름을 보여주는 mock MVP입니다. 이후 Claude, Cohere embedding, ChromaDB, PostgreSQL, Coupang 연동을 각 tool 함수 내부에 연결하면 됩니다.

## LLM 연결

기본값은 API 키 없이 동작하는 deterministic fallback입니다. 실제 LLM을 붙일 때는 백엔드 실행 전에 환경변수를 설정합니다.

```bash
set FRIDGEMATE_LLM_PROVIDER=anthropic
set FRIDGEMATE_LLM_MODEL=claude-3-5-sonnet-latest
set ANTHROPIC_API_KEY=your_api_key
uvicorn app.main:app --reload
```

OpenAI 계열 모델을 쓰려면 `FRIDGEMATE_LLM_PROVIDER=openai`, `OPENAI_API_KEY=...`로 바꾸면 됩니다.

현재 LLM 연결 지점:

- Orchestrator: Supervisor routing JSON 생성
- Meal Agent: Plan-and-Execute 식단 계획 JSON 생성
- Shopping Agent: Reflexion 실패 회고 JSON 생성

API 키가 없거나 호출이 실패하면 같은 JSON 구조의 fallback으로 계속 실행됩니다.
