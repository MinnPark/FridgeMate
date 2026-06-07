# RAG 실험 리포트 (recipe_db 1,693 / bge-m3)

> 작성자: **neocello-ku** (B파트 RAG) · 2026-06-06
> 대상: recipe_db 1,693건(식약처 1146 + 농정원 537 + seed 10), embed_sig=bge-m3-1024
> 하네스: 16쿼리(오타/묘사/구어), 임베딩 bge-m3(LM Studio), LLM OpenRouter
>
> ⚠️ **2026-06-07 갱신**: 본 보고서 §4.2 "SMART 경로 기본 유지(+25%p)" 권장은 이후 검증으로 보완됨.
> 그 +25%p는 **오타/묘사 16쿼리 + cloud Sonnet(run1)** 한정이고, **로컬 서브모델(qwen-7b)에선 PLAIN이 더 낫고 HyDE가 최약**.
> **현재 권장 = 3엔진 RRF 병합(merged)** + 어려운 묘사형만 Claude. 상세: `rag-verification-report.md`, `rag-strategy-proposal.md` / 인덱스: `rag-INDEX.md`.

## 1. 결과 (베이스라인)
| 경로 | P@1 | P@3 | MRR |
|---|---|---|---|
| PLAIN (순수 bge-m3) | 50% | 69% | 0.594 |
| SMART (HyDE/RAG-Fusion + LLM) | 75% | 88% | 0.802 |
| 차이 (smart-plain) | +25%p | +19%p | +0.208 |

- 오타(김치찌게 등): plain·smart 모두 4/4 (bge-m3 오타 강건).
- 묘사/구어: plain 약함 -> smart 가 LLM 쿼리확장으로 대폭 회복.

### 1-1. 재검증 (2026-06-06, `backend/scripts/rag_eval.py` 머지레포 이식 후 재실행)
| 경로 | P@1 | P@3 | MRR | 재현성 |
|---|---|---|---|---|
| PLAIN (전 run) | **50%** | **69%** | **0.594** | **완전 동일** (순수 벡터 = 결정적) |
| SMART run1 (보고서, cloud Sonnet) | 75% | 88% | 0.802 | — |
| SMART run2 (OpenRouter) | 50% | 81% | 0.646 | 변동 |
| SMART run3 (LM Studio qwen2.5-7b) | 62% | 81% | 0.698 | 변동 |

- **PLAIN 은 완전 재현됨** (벡터검색 결정적).
- **SMART 는 run/모델마다 변동** — HyDE 가상답변/Fusion 멀티쿼리가 LLM 출력이라 매 실행 달라짐. 보고서 SMART 수치는 "1회 측정치"이며 **고정값으로 보면 안 됨**. (로컬 7b 서브모델도 P@3 81%로 양호)
- **일관되게 유지되는 결론**: SMART 가 묘사/구어 쿼리에서 P@3/MRR 을 끌어올림(2회 모두 PLAIN 대비 P@3 +12~19%p). 단 **P@1 향상폭은 run 의존적**(run2 에선 +0%p).
- 정밀 비교하려면 **온도 0 고정 + 다회 평균** 필요 (후속 과제).

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

## 5. 검증/QA 상태 (2026-06-06 재검증)
- **코퍼스 실측**: recipe_db `1,693`건, embed_sig=`bge-m3-1024`, 출처 `cookrcp 1146 / mafra 537 / manual 10` (보고서 수치와 일치).
- **RAG 전략 실발동 확인**: `retrieve_recipes("…고단백 한식")` → `strategy=RAG-Fusion`, **`via=rag_fusion`** (멀티쿼리 4개 LLM 생성 → RRF → 출처 포함 10건). 폴백 아님 확인.
- `app.main` import 부팅 OK + `/chat` e2e 200 (citation 포함).
- embed_text ablation 실행 -> 현행 유지.
- **런타임 주의(중요)**: RAG LLM(HyDE/Fusion)은 `app/rag/_llm.py`가 `openai` SDK 로 OpenRouter/LM Studio 호출. **`openai` 미설치 python 으로 백엔드를 띄우면 LLM 호출이 `No module named 'openai'` 로 실패 → 조용히 일반 벡터검색으로 폴백(`via=None`)**. 라벨은 RAG-Fusion 으로 찍혀도 실제 멀티쿼리는 안 돎. → 의존성 설치된 python(또는 전용 venv)으로 기동 필수.
- **eval 하네스 이식 완료**: `backend/scripts/{rag_eval,rag_inspect,rag_ablation}.py` (+ README). 보고서 수치 재현/검증 가능.
- 후속: 전용 venv 표준화, 데이터확충, 메타필터/reranker, eval 온도0·다회평균.
