# RAG LLM 티어링 + 런타임 정리 (2026-06-06)

> 작성: B파트(RAG). 대상 브랜치: `feature/v3-graph-experiment`.
> 요약: RAG의 LLM 호출을 **2계층으로 분리** — 큰 오케스트레이션은 OpenRouter(Claude),
> 작은 서브쿼리(HyDE 가상답변 / Fusion 멀티쿼리)는 LM Studio 로컬 서브모델.
> 더불어 Fusion 미발동 버그 수정 + 전용 venv + 실험보고서 재검증.

---

## 1. LLM 티어링 (핵심)

| 계층 | 용도 | 위치 | provider / model |
|---|---|---|---|
| **오케스트레이션(대)** | supervisor 라우팅, 식단 구성 | `app/llm.py` | OpenRouter **Claude** (`anthropic/claude-sonnet-4-6`) |
| **서브쿼리(소)** | HyDE 가상답변, Fusion 멀티쿼리 생성 | `app/rag/_llm.py` | LM Studio **local** (`qwen2.5-7b-instruct`) |
| **임베딩** | 문서/쿼리 벡터화 | `app/rag/embedder.py` | LM Studio `text-embedding-bge-m3` (1024d) |

이유: 다각도 쿼리 생성/가상문서 같은 **싸고 빈번한 작은 작업**은 로컬 서브모델로 비용·지연을 줄이고,
라우팅·식단구성 같은 **중요 추론**만 Claude로 처리.

### 동작 토글 (env)
| 변수 | 기본값 | 설명 |
|---|---|---|
| `RAG_LLM_PROVIDER` | `local` | 서브쿼리 provider. `openrouter`로 두면 전부 Claude로 통일 |
| `LOCAL_MODEL_DEFAULT` | `qwen2.5-7b-instruct` | LM Studio 서브모델 id |
| `LLM_LOCAL_BASE_URL` | (없으면 `LMSTUDIO_BASE_URL` 폴백) | OpenAI 호환 엔드포인트 |
| `LMSTUDIO_BASE_URL` | `http://58.148.250.103:1234/v1` | 원격 LM Studio |
| `LMSTUDIO_API_KEY` | — | 원격 LM Studio Bearer 토큰 (로컬 provider 인증에도 사용) |
| `LLM_PROVIDER` | `openrouter` | 오케스트레이션 provider |
| `FRIDGEMATE_USE_LLM` | `true` | false면 전부 fallback(오프라인) |

---

## 2. 코드 변경

- `app/rag/_llm.py`
  - `local` provider가 LM Studio(원격)를 쓰도록: `base = LLM_LOCAL_BASE_URL or LMSTUDIO_BASE_URL`, `api_key = LMSTUDIO_API_KEY`. (기존엔 Ollama 기본 URL + `"local"` 더미키라 원격 인증 불가)
  - `rag_subquery_provider()` 추가 — 서브쿼리 전용 provider 결정(기본 local).
  - `local` 기본 모델 `qwen2.5:7b` → `qwen2.5-7b-instruct`(LM Studio id 형식).
- `app/rag/hyde.py`, `app/rag/rag_fusion.py`
  - `call_llm(..., provider=rag_subquery_provider())` 로 서브쿼리만 로컬로 라우팅.
  - 활성 게이트도 서브쿼리 provider 기준(`llm_enabled(provider)`).
  - 로그 `(LLM/OpenRouter)` → `(LLM:{provider})` 로 실제 provider 반영.
- `app/agents/meal_agent.py`
  - **Fusion 미발동 버그 수정**: `retrieve_recipes(meal_name, ...)` → 사용자 의도 키워드를 실어
    `retrieve_recipes(f"{meal_name} {intent}", ...)`. 의도(고단백/한식 등)가 요리명에만 의존하던 구조를 보정해 전략판정이 RAG-Fusion까지 도달.

---

## 3. 동작 검증 (실측 로그)

```
오케스트레이션 provider: openrouter | 서브쿼리 provider: local | 서브 enabled: True

[RAG/Fusion] multi_queries(LLM:local): ['고단백 두부 된장찌개','한식 두부 된장찌개 추천','고 단백질 두부 된장 찌개','두부와 된장 찌개 고단백 버전']
[RAG/Fusion]   -> 된장 두부찌개 | rrf=0.0667 | src=cookrcp | cite=https://www.foodsafetykorea.go.kr
[RAG/Fusion]   -> 된장찌개      | rrf=0.0653 | src=mafra   | cite=https://data.mafra.go.kr
==> strategy: RAG-Fusion | via: rag_fusion | n: 10          (via=rag_fusion = 폴백 아닌 실발동)

[RAG/HyDE] hypothetical_doc(LLM:local): ...재료: 된장, 대파, 김치... 장르: 한식
[RAG/HyDE]   -> 된장찌개 | src=manual | dist=0.282 | cite=https://example.com/doenjang-jjigae
```

- `via=rag_fusion` / `(LLM:local)` = 서브쿼리가 LM Studio 로컬에서 실제 생성됨(폴백 아님).
- 코퍼스 실측: recipe_db `1,693`건 (cookrcp 1146 / mafra 537 / manual 10), embed_sig `bge-m3-1024`.

### 트레이드오프
- 로컬 7b 서브모델은 Claude보다 가상답변/멀티쿼리 품질이 거칠다(가끔 군더더기 토큰). 검색용으론 충분하나, 품질 민감하면 `RAG_LLM_PROVIDER=openrouter`로 전환.

---

## 4. 런타임 (중요 — 그동안 혼란의 원인)

RAG LLM은 `openai` SDK로 OpenAI호환 엔드포인트를 호출한다. **`openai` 미설치 python으로 백엔드를 띄우면**
`[llm] ... failed: No module named 'openai'` → 조용히 일반 벡터검색 폴백(`via=None`). 라벨만 RAG-Fusion이고 실제 멀티쿼리는 안 돈다.

### 해결: 이 레포 전용 venv 사용
```powershell
cd D:\Research\agents\fridgeMate-Merge\backend
python -m venv .venv
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt
# 기동
& ".venv\Scripts\python.exe" -m uvicorn app.main:app --port 8742 --log-level info
```
- `backend/.venv` 는 `.gitignore` 처리(레포에 안 올림).
- 남의 레포 venv 빌려쓰지 말 것. 이 레포 안에서 deps 설치.

---

## 5. 실험보고서 재검증 (`docs/rag-experiment-report.md` §1-1 반영)

- PLAIN(순수 벡터)은 완전 재현(결정적). SMART(HyDE/Fusion)는 LLM이라 run마다 변동 → 보고서 SMART 수치는 1회치.
- 일관 결론: SMART가 묘사/구어 쿼리 P@3/MRR을 끌어올림. P@1 향상폭은 run 의존(온도0·다회평균이 후속 과제).

---

## 6. 남은 갭 / 후속

- `app/agents/recipe_agent.py` 죽은 코드(`MOCK_RECIPE_INDEX`, `mock_vector_search`, 더미 `generate_hyde_document`/`rewrite_queries_for_fusion`) 제거 필요.
- eval 하네스(`rag_eval.py`/`rag_ablation.py`)가 원본 fridge-mate에만 있음 → 머지 레포로 이식해 보고서와 동거.
- `pantry_agent`는 `origin/main`에 병합됨 — 본 브랜치는 미반영. pull 후 병합 상태에서 별도 점검·보정 예정.
- 전용 venv 표준화(팀 공통 setup 문서/스크립트).
