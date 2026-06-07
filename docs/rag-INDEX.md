# RAG 문서 인덱스 (최신순)

> 파일명에 날짜가 없어 헷갈려 정리. **위가 최신.** 각 문서 제목에도 날짜 박혀 있음.

| # | 문서 | 날짜 | 목적 | 상태 |
|---|---|---|---|---|
| 0 | `rag-io-contract.md` | **2026-06-08** | **에이전트<->RAG 입출력 계약(구현 명세)** — query+constraints 입력 / 응답 dict 샘플 + constraints 파싱 위치 결정(에이전트가) | 최신·구현명세 |
| 0.5 | `rag-support-plan.md` | **2026-06-07** | **RAG 보강 작업 계획** — 영양·제약·필터/검색 전반, 팀 요구 기반·협의용 | 작업계획 |
| 1 | `rag-strategy-proposal.md` | **2026-06-07** | PLAIN/HyDE/Fusion/**MERGE** + 서브모델(qwen/gpt-oss-20b/claude) 비교 → 에이전트 라우팅 **제안** | 최신·제안 |
| 2 | `rag-verification-report.md` | **2026-06-07** | 튜닝본 로컬 **검증** — HyDE/Fusion 라우팅별 흐름 + P/R/MRR(4장르) | 최신·검증 |
| 2.5 | `rag-tuning-changelog.md` | **2026-06-07** | **튜닝 변경 내역(문제→원인→해결)**: Fusion 후보풀 확대·score 정규화·길이기준 통일 | 최신·변경내역 |
| 3 | `rag-llm-tiering.md` | 2026-06-06 | LLM 티어링(오케=OpenRouter / 서브=LM Studio) + venv·런타임 | 유효(설계) |
| 4 | `rag-experiment-report.md` | 2026-06-06 | **베이스라인 실험** — PLAIN vs SMART(16쿼리), embed_text ablation | 일부 갱신(아래) |
| 5 | `role-b-progress.md` | - | B파트 전반 진행 | 보조 |

## 현재 정본 결론 (옛↔새 충돌 정리)
**충돌 1건**: `rag-experiment-report.md` §4.2 *"SMART 경로 기본 유지(+25%p)"* ↔ 06-07 결론.
- 그 **+25%p 는 "오타/묘사 16쿼리 + cloud Sonnet(run1)" 한정** 수치. (§1-1에서 이미 run마다 변동 인정)
- **06-07 재검증**: 로컬 qwen-7b 서브모델에선 **HyDE가 최약**(MRR 0.70), 명확한 요리명은 **PLAIN이 더 정확**. 큰모델 gpt-oss-20b도 다각화 실패.
- → **모순이 아니라 "쿼리유형·서브모델"에 따른 차이**. 정리하면:
  - 오타/모호 쿼리 + 강한 LLM(Claude) → SMART(특히 Fusion) 이득.
  - 명확한 요리명 + 로컬 7b → PLAIN 이 낫고 HyDE는 손해.
- **현재 권장(최신 정본) = 단일 SMART 라우팅이 아니라 3엔진 RRF 병합(merged)** + 어려운 묘사형만 서브LLM Claude. (`rag-strategy-proposal.md` §5)

## 한 줄
> 베이스라인(06-06)에서 "SMART 좋다"였는데, 06-07 검증에서 **로컬 서브모델 기준으론 단일 SMART가 손해 → merged가 최선**으로 결론이 정밀화됨. 채택 전 100+쿼리·의미relevance 재검 권장.
