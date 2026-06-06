# RUN — 전체 구동 한 문서 (이것만 보면 됨)

> by neocello-ku. 백엔드 + 프론트 + LangGraph Studio + LangSmith + Docker + 노트북.
> 포트(8000/3000 충돌 회피 -> 비표준 고정): **백엔드 8742 · 프론트 8743 · LangGraph Studio 8744**

---

## 0. 빠른 시작 (로컬, 2터미널)

```bash
# (1) 백엔드  http://localhost:8742
cd backend
python -m venv .venv && .venv\Scripts\activate          # mac/linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                                   # mac/linux: cp .env.example .env
#  -> .env 에 *** 비밀키 채우기: LMSTUDIO_API_KEY, OPENROUTER_API_KEY
uvicorn app.main:app --reload --port 8742

# (2) 프론트  http://localhost:8743  (새 터미널)
cd frontend/web
npm install
copy .env.local.example .env.local                       # NEXT_PUBLIC_API_BASE_URL=http://localhost:8742
npm run dev -- -p 8743

# (3) 확인
curl http://localhost:8742/health
# Swagger(API 스펙): http://localhost:8742/docs
```

데이터(recipe_db 1,693)는 `backend/data/chroma` 동봉 -> 추가 주입 없이 검색됨.

---

## 1. 환경변수 (.env) — 비밀키만 채우면 됨
`backend/.env.example` 복사 후:
| 키 | 용도 | 필수 |
|---|---|---|
| `LMSTUDIO_API_KEY` | bge-m3 임베딩(LM Studio) | 필수 |
| `OPENROUTER_API_KEY` | HyDE/RAG-Fusion LLM | 권장(없으면 plain 폴백) |
| `FOOD_SAFETY_API_KEY` / `MAFRA_API_KEY` | 사전임베딩 재수집 시 | 선택 |
나머지(EMBED_PROVIDER=local, LMSTUDIO_BASE_URL, EMBED_SIG, CHROMADB_PATH)는 기본값 채워져 있음.

## 2. 백엔드 (FastAPI + RAG) — 8742
- `uvicorn app.main:app --reload --port 8742` (backend/ 에서)
- `GET /health` · **`POST /chat`(프론트 연결 API)** · Swagger **/docs** · ReDoc /redoc
```bash
curl -X POST http://localhost:8742/chat -H "Content-Type: application/json" ^
  --data "{\"message\":\"두부 계란 애호박 고단백 한식\",\"budget_limit\":30000}"
```

## 3. 프론트 (Next.js) — 8743
- `cd frontend/web && npm install && npm run dev -- -p 8743` -> http://localhost:8743
- `.env.local` 의 `NEXT_PUBLIC_API_BASE_URL=http://localhost:8742`

## 4. LangGraph Studio (그래프 시각화/테스트) — 8744
```bash
pip install -U "langgraph-cli[inmem]"
langgraph dev --port 8744          # repo 루트(langgraph.json)에서
```
- 등록 그래프: `fridgemate`(메인), `rag_agent`(RAG 서브그래프)
- Studio UI: https://smith.langchain.com/studio?baseUrl=http://localhost:8744

## 5. LangSmith (트레이싱/테스트)
`.env`:
```
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_...
LANGCHAIN_PROJECT=fridgemate-merge
```
-> 모든 노드/LLM 호출이 LangSmith 에 자동 기록.

## 6. Docker (호스트 포트 동일)
```bash
docker compose up --build          # 백엔드 8742 + 프론트 8743
```
파일: `backend/Dockerfile`, `frontend/web/Dockerfile`, `docker-compose.yml`. 시크릿은 안 구움(compose 가 backend/.env 주입).

## 7. 노트북 (실험 도구, 서빙과 분리)
`notebooks/` (app.rag 재사용, 실험은 `recipe_db_lab` 별도 컬렉션):
01_collect 02_normalize 03_embed 04_index 05_search 06_advanced 07_eval
- `cd notebooks && jupyter lab`. 외부데이터 더 임베딩/주입 실험용.

## 8. 구동 확인 체크리스트
- [ ] `GET http://localhost:8742/health` 200
- [ ] `/docs` Swagger 열림
- [ ] `/chat` 200 + selected_recipes (실 bge-m3면 관련도 높음)
- [ ] 프론트 8743 접속 -> 결과 카드
- [ ] (선택) `langgraph dev --port 8744` -> Studio 에서 그래프 표시
