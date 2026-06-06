# RAG / Recipe Agent (B파트) — by neocello-ku

> 브랜치: `feature/recipe-rag_agent` · 작성자: **neocello-ku** (B파트 / RAG·VectorDB)
> 이 문서는 RAG 이식분 전용 README. 메인 `README.md`(팀 공통) 와 별개.

기존 레포의 mock Recipe Agent 를 **실제 RAG 엔진**으로 교체한 기여물입니다.
bge-m3 임베딩 + ChromaDB(recipe_db 1,693건) + HyDE / RAG-Fusion / RRF + 개인화 boost.

---

## 1. 무엇이 바뀌나 (한 줄)

`app/agents/recipe_agent.py:retrieve_recipes` 한 곳만 mock -> 실 RAG 로 교체.
recipe/meal 두 경로가 이 함수를 공유하므로 동시에 실검색 사용. 반환 계약/trace 포맷 동일 유지.

## 2. 로컬 구동 (프론트 + 백엔드 동시)

### 백엔드 (port 8000)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # mac/linux: source .venv/bin/activate
pip install -r requirements.txt   # chromadb 등 RAG 의존 포함됨
copy .env.example .env            # mac/linux: cp .env.example .env
#  -> .env 열어서 *** 비밀키 채우기:
#     LMSTUDIO_API_KEY  (bge-m3 임베딩, 필수)
#     OPENROUTER_API_KEY(HyDE/RAG-Fusion 질의생성; 없으면 plain 벡터검색으로 폴백)
uvicorn app.main:app --reload     # http://localhost:8000  (/health, /chat)
```

### 프론트 (port 3000)

```bash
cd frontend/web
npm install
copy .env.local.example .env.local   # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm run dev                           # http://localhost:3000
```

### 동작 확인

```bash
curl -X POST http://127.0.0.1:8000/chat -H "Content-Type: application/json" ^
  -d "{\"message\":\"두부 계란 애호박으로 고단백 한식\",\"budget_limit\":30000}"
```

- recipe 경로가 실 RAG 로 레시피를 가져오면 통합 성공. (chroma 1,693건 동봉됨)
- 비밀키 미설정 시: bge-m3 호출 실패로 RAG 단계 에러. 키만 채우면 동작.

## 3. 구조 (이식분)

```
backend/
  app/rag/                 # RAG 엔진 자기완결 패키지
    integration.py         # 통합 어댑터(to_contract + retrieve_recipes 동기 드롭인) <- seam
    embedder.py indexer.py retriever.py
    hyde.py rag_fusion.py smart_search.py preference_store.py agent.py
    _llm.py _normalize.py  data/(fetch_*)  prompts/(hyde,fusion)
    __init__.py            # import 시 load_dotenv() 자동
  app/agents/recipe_agent.py   # retrieve_recipes 만 교체(나머지 무수정)
  scripts/ingest_recipes.py    # 사전임베딩(식약처+농정원+seed -> recipe_db)
  data/chroma/                 # 사전임베딩 산출물(recipe_db 1,693) 동봉
  .env.example                 # 풀 템플릿(비밀키만 채우면 구동)
```

## 4. RAG 동작 방식 (요약)

- 쿼리 -> `choose_rag_strategy`(10자 임계) -> HyDE(짧음) / RAG-Fusion(복합) / Basic
- bge-m3 임베딩(LM Studio) -> ChromaDB recipe_db 벡터검색 -> (Fusion 시 RRF 병합)
- 기존 그래프=동기라 `retrieve_recipes`는 sync 브리지(asyncio.run, RAG 내부 병렬 보존)

## 5. 실험 결과 (요약)

- 1,693 코퍼스: PLAIN P@1 50% -> SMART(HyDE/Fusion+LLM) P@1 75% (+25%p)
- embed_text ablation: 현행 vs lean 집계 동일 -> 미세조정 효과 0, LLM 이 진짜 레버
- 상세: [docs/rag-experiment-report.md](docs/rag-experiment-report.md)

## 6. 관련 문서 (작성자 구분)

- [docs/role-b-progress.md](docs/role-b-progress.md) — B파트 진행 (by neocello-ku)
- [docs/rag-experiment-report.md](docs/rag-experiment-report.md) — RAG 실험 (by neocello-ku)
- [docs/architecture_review.md](docs/architecture_review.md) — 아키텍처 점검 (by neocello-ku)

## 7. 후속 (추후보완중)

전체 앱 .env 적용 / 노트북 실험폴더 / 도커 서빙 / LangGraph Studio+LangSmith /
메타필터+reranker / 데이터 1만건+ (외부채널 추가).