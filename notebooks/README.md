# 레시피 RAG 노트북 — 파이프라인 재현 / 실험

운영 데이터 파이프라인(`backend/scripts/pipeline/sN`)을 **작은 규모로 재현하고 탐색**하는 노트북.
서빙 데이터를 보호하려고 **격리**한다 — 산출물은 `backend/data/lab/`, 인덱싱은 ChromaDB `recipe_db_lab`
(서빙 `recipe_db` 1,693건은 건드리지 않음).

## 노트북 <-> 파이프라인 대응

| 노트북 | 대응 (운영 정본) | 하는 일 |
|---|---|---|
| `01_collect` | `scripts/pipeline/s0_collect_raw.py` | API **원문** 수집 -> `data/lab/00_raw.json` (정규화 전) |
| `02_normalize` | `s1_normalize.py` + `s2_clean.py` | 원문 -> 표준 dict + **품질 수치(분량/단위/영양 채움률)** -> `02_norm.json` |
| `03_embed` | `s3_embed_text.py` | `embed_text` -> bge-m3 벡터 -> `03_vecs.pkl` |
| `04_index` | `s4_index.py` | 벡터 -> ChromaDB **`recipe_db_lab`** (격리 데모) |
| `05_search` | `app.rag.retriever` | 서빙 `recipe_db`(1,693) 순수 벡터검색 |
| `06_advanced` | `app.rag.hyde` / `rag_fusion` | HyDE / RAG-Fusion (서브쿼리 LLM = LM Studio 로컬) |
| `07_eval` | `scripts/rag_eval.py` | precision@k / MRR (PLAIN vs SMART) |

> 차이: **노트북 = 작은 limit + lab 격리(탐색용)** / **파이프라인 = 전량 + 서빙 recipe_db(운영)**.
> 정규화 파서·임베더·인덱서는 **같은 정본**(`app.rag.*`)을 공유 — 결과가 일치하도록.

## 재현 순서

```
01_collect  ->  02_normalize  ->  03_embed  ->  04_index      (data/lab, recipe_db_lab 격리)
05_search / 06_advanced / 07_eval                              (서빙 recipe_db 1,693 대상)
```

- **파서를 고쳤다면** `01` 재수집 없이 `02`부터 재실행해 품질 수치 변화를 비교(재현의 핵심).
- `01`이 `00_raw.json`(원문)을 남기므로, `02`의 파서를 바꿔도 API 재호출이 필요 없다.

## 전제

- `backend/.venv` 활성, `EMBED_PROVIDER=local` (bge-m3, LM Studio).
- `FOOD_SAFETY_API_KEY`(식약처) / `MAFRA_API_KEY`(농정원) — `.env`. 없으면 해당 채널 0건.
- 실행 위치: `notebooks/` 또는 repo 루트 (셀이 `backend/`를 자동 탐지).
- 참고: `01`의 농정원 수집은 재료/과정 전량을 받아 다소 무겁다(수천 행).

## 품질 현황 (전량 기준, `s2_clean` report 정본)

cookrcp 1,146건 재료분량 94.9% / 영양 99.9% · mafra 537건 영양(P/C/F) 0%(미수집) · seed 10건 100%.
자세한 입출력 계약은 `docs/rag-io-contract.md`, 데이터 실태는 `data/pipeline/02_clean/report.json`.
