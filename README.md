# FridgeMate AI

FridgeMate AI는 냉장고 재료 입력부터 식단 추천, 레시피 검색, 부족 재료 산출, 쿠팡 장바구니 후보 생성까지 연결하는 AI Agent MVP입니다.

> ▶ **설치·구동은 [RUN.md](RUN.md) 를 그대로 따라하면 됩니다** — venv 생성 → 의존성 설치(전부 버전 고정) → `.env` → 백엔드/프론트/Studio 기동까지 전 과정 상세.

## 프로젝트 조건 매핑

- 고급 Prompt Engineering: Supervisor, Plan-and-Execute, ReAct, Reflexion, HyDE, RAG-Fusion
- Function Calling / Tool Calling: pantry parsing, nutrition lookup, missing ingredient calculation, shopping search, cart deeplink
- RAG + VectorDB: bge-m3 임베딩 + ChromaDB(recipe_db 1,693건) + HyDE/RAG-Fusion/RRF 실연결 (mock 아님)
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

## 실행 (요약 — 전 과정 상세는 [RUN.md](RUN.md))

> 포트: 백엔드 **8742** · 프론트 8743 · Studio 8744. RAG 의존성은 `requirements.txt` 에 통합(별도 requirements-rag.txt 없음).

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate                    # mac/linux: source .venv/bin/activate
pip install -r requirements.txt           # 전부 버전 고정 — fresh clone 동일 재현(검증됨)
copy .env.example .env                     # -> .env 에 LMSTUDIO_API_KEY, OPENROUTER_API_KEY 채우기
python -m uvicorn app.main:app --port 8742 # 반드시 이 venv python 으로 (openai 등 deps)
# 확인: curl http://127.0.0.1:8742/health   ·   Swagger http://127.0.0.1:8742/docs
```

RAG는 **실연결**입니다: bge-m3 임베딩(LM Studio) + ChromaDB(recipe_db 1,693건 동봉) + HyDE/RAG-Fusion/RRF. 요청 예시·프론트·Studio 기동은 [RUN.md](RUN.md), LLM 티어링(오케스트레이션 OpenRouter / 서브쿼리 LM Studio)·런타임 주의는 [docs/rag-llm-tiering.md](docs/rag-llm-tiering.md).

## LLM 연결

> 현행 구성은 `backend/.env.example` + [docs/rag-llm-tiering.md](docs/rag-llm-tiering.md) 가 정본: **오케스트레이션=OpenRouter(Claude)**, **RAG 서브쿼리(HyDE/Fusion)=LM Studio 로컬 qwen2.5-7b**, 임베딩=bge-m3(LM Studio). 아래는 일반 설명.

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
- Coupang Product Ranker: 레시피 문맥을 고려한 쿠팡 상품 후보 판정

API 키가 없거나 호출이 실패하면 같은 JSON 구조의 fallback으로 계속 실행됩니다.

### LM Studio로 쿠팡 상품 판정 사용

LM Studio에서 `qwen2.5-7b-instruct` 같은 **채팅 모델**을 로드하고 Local
Server를 실행한 뒤 `backend/.env`를 다음처럼 설정합니다.

```env
FRIDGEMATE_LLM_PROVIDER=openai
FRIDGEMATE_LLM_BASE_URL=http://127.0.0.1:1234/v1
FRIDGEMATE_LLM_MODEL=qwen2.5-7b-instruct
OPENAI_API_KEY=lm-studio
```

- `openai`는 OpenAI 회사 모델을 의미하는 것이 아니라 **OpenAI 호환 API
  형식**을 의미합니다. 실제 요청 대상은 `FRIDGEMATE_LLM_BASE_URL`입니다.
- 로컬 LM Studio는 기본적으로 실제 API 키가 필요하지 않습니다.
  `OPENAI_API_KEY=lm-studio`는 현재 코드의 빈 값 검사를 통과시키는 더미
  문자열입니다.
- `FRIDGEMATE_LLM_MODEL`은 LM Studio의 `GET /v1/models` 응답에 표시된 모델
  ID와 정확히 같아야 합니다.
- `bge-m3`는 임베딩 모델이므로 상품 판정에 사용할 수 없습니다. 상품
  판정에는 별도의 채팅 모델이 필요합니다.
- 이 설정은 `app/llm.py`를 공유하는 Orchestrator, Meal, Shopping Agent와
  쿠팡 상품 판정을 모두 LM Studio로 연결합니다.

설정 변경 후 FastAPI를 완전히 다시 시작합니다.

```cmd
cd backend
python -m uvicorn app.main:app --reload --port 8742
```

다른 포트를 사용한다면 프런트의 `NEXT_PUBLIC_API_BASE_URL`도 같은 포트로
설정합니다.

LM Studio 연결과 모델 ID는 다음 명령으로 확인할 수 있습니다.

```cmd
curl http://127.0.0.1:1234/v1/models
```

쿠팡 상품 판정은 부족 재료명뿐 아니라 해당 재료가 사용되는 레시피명,
필요량, 배송 선호와 상품 후보 정보를 함께 비교합니다. LLM 판정 신뢰도가
75% 이상이면 자동 선택하고, 사용자는 화면의 `후보 선택`에서 결과를 변경할
수 있습니다. LLM 연결에 실패하면 기존 키워드·가격·배송 규칙의 최상위
후보를 자동 선택하며, 이 결과 역시 사용자가 변경할 수 있습니다.

화면에 `LLM 판정`이 표시되면 로컬 모델이 사용된 것이고, `규칙 판정`이
표시되면 LLM 호출 실패 또는 비활성화로 fallback이 사용된 것입니다.
