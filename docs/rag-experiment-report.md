# RAG 실험 리포트 (recipe_db 1,693 / bge-m3)

> 작성자: **neocello-ku** (B파트 RAG) · 2026-06-06
> 대상: recipe_db 1,693건(식약처 1146 + 농정원 537 + seed 10), embed_sig=bge-m3-1024
> 하네스: 16쿼리(오타/묘사/구어), 임베딩 bge-m3(LM Studio), LLM OpenRouter

## 1. 결과 (베이스라인)
| 경로 | P@1 | P@3 | MRR |
|---|---|---|---|
| PLAIN (순수 bge-m3) | 50% | 69% | 0.594 |
| SMART (HyDE/RAG-Fusion + LLM) | 75% | 88% | 0.802 |
| 차이 (smart-plain) | +25%p | +19%p | +0.208 |

- 오타(김치찌게 등): plain·smart 모두 4/4 (bge-m3 오타 강건).
- 묘사/구어: plain 약함 -> smart 가 LLM 쿼리확장으로 대폭 회복.

## 2. 핵심 발견
1. **고급 RAG(HyDE/RAG-Fusion+LLM) 가치 정량 입증** — +25%p. 묘사·구어에서 plain 벡터만으론 부족.
2. **exact-name 메트릭이 1,693 코퍼스에서 과소평가** — "miss" 다수가 정답 변형:
   - "두부 들어간 매운 중국요리" -> 마파두부덮밥 (사실상 정답)
   - "돼지고기 김치 국물요리" -> 돼지고기김치찌개 (정답인데 exact 김치찌개 아님)
   -> 실제 체감 정확도는 수치보다 높음.

## 3. embed_text ablation (실행: scripts/rag_ablation.py)
현행 V1(이름+전체재료+steps+영양+시간+장르) vs V2 lean(이름+재료+장르) plain 비교, 임시컬렉션(프로덕션 무영향):

| 지표 | V1 | V2 lean | 차이 |
|---|---|---|---|
| P@1 | 50% | 50% | 0.000 |
| P@3 | 69% | 69% | 0.000 |
| MRR | 0.594 | 0.594 | 0.000 |

- 집계 동일, 쿼리별 trade-off (lean이 어떤건 개선/어떤건 악화).
- **희석 가설 기각** — embed_text 깎아도 정확도 변화 없음. **진짜 레버는 embed_text 미세조정이 아니라 SMART(LLM) + 데이터 커버리지.**
- **현행 embed_text 유지** 결론 (다운스트림 정보도 풍부).
- 한계: 16쿼리·seed 편중(통계력 낮음). 데이터 1만건+ 시 100+쿼리 재검증.

## 4. 권장 (우선순위)
1. **데이터 1만건+** (외부채널 RDA/gimi9/크롤링) — 커버리지가 최대 축.
2. SMART 경로 기본 유지(이미 +25%p).
3. 메타데이터 pre-filter 연결(시간/장르/칼로리) + reranker.
4. embed_text 는 더 안 건드림(효과 0 확인).

## 5. 검증/QA 상태
- recipe_db 1,693 retrieval 정상, SMART P@1 75%/P@3 88%/MRR 0.802.
- embed_text ablation 실행 -> 현행 유지.
- 머지 레포 `app.main` import 부팅 OK + `recipe_agent.retrieve_recipes` e2e 통과(citation 포함).
- 후속: 데이터확충, 메타필터/reranker.
