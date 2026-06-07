# 레시피 데이터 파이프라인 (FM 정본)

여러 채널의 외부 레시피 API를 **수집 → 정규화 → 정제 → 임베딩준비 → 적재** 5단계로 처리한다.
각 단계가 **파일 산출물 하나**를 남기므로, 어디서 무엇이 깨지고 비는지 눈으로 확인할 수 있고,
**원천(raw)을 보존**하므로 파서를 고쳐도 API 재호출 없이 중간 단계부터 다시 돌릴 수 있다.

> 왜 이렇게 하나: 기존 경로(`scripts/ingest_recipes.py`)는 수집·정규화·적재가 한 번에 일어나
> 중간 데이터가 남지 않았다. 그래서 "재료 분량이 가짜다 / 영양이 0이다"를 확인하려면 매번 다시
> 긁어야 했고, 파서를 고쳐도 검증이 어려웠다. 이 파이프라인은 단계마다 결과를 박제해 그 문제를 없앤다.

---

## 단계 개요

| 단계 | 스크립트 | 읽기 | 쓰기 | 하는 일 |
|---|---|---|---|---|
| 0 수집 | `s0_collect_raw.py` | 외부 API | `00_raw/` | API 원문 그대로 저장(정규화 X) |
| 1 정규화 | `s1_normalize.py` | `00_raw/` | `01_normalized/` | 채널별 원문 → 표준 레시피 dict |
| 2 정제·검증 | `s2_clean.py` | `01_normalized/` | `02_clean/` | 합치기+중복제거+**품질 리포트** |
| 3 임베딩준비 | `s3_embed_text.py` | `02_clean/` | `03_embed_ready/` | 검색용 `embed_text` 생성(임베딩될 문자열 명시) |
| 4 적재 | `s4_index.py` | `03_embed_ready/` | ChromaDB `recipe_db` | bge-m3 임베딩 → 벡터DB upsert |

산출물 위치: `backend/data/pipeline/{00_raw,01_normalized,02_clean,03_embed_ready}/`

```
00_raw/        cookrcp.json · mafra_basic.json · mafra_ingredient.json · mafra_process.json · _manifest.json
01_normalized/ cookrcp.json · mafra.json
02_clean/      recipes.json · report.json          ← 데이터 실태 리포트(소스별 필드 채움률)
03_embed_ready/recipes.json · _preview.txt          ← 실제 임베딩될 문자열 상위 20건
```

---

## 채널(소스)

| 채널 | 기관 | 서비스 | 키(.env) | 비고 |
|---|---|---|---|---|
| cookrcp | 식약처 | COOKRCP01 | `FOOD_SAFETY_API_KEY` | 미설정 시 `sample` 5건. 어디서나 호출 가능. ~1,146건 |
| mafra | 농정원 | 기본 226 / 재료 227 / 과정 228 | `MAFRA_API_KEY` | `RECIPE_ID`로 3서비스 조인. ~537건 |
| seed | 자체 | `app/rag/data/seed_recipes.json` | - | 데모/테스트 정본 10건(2단계에서 합류) |

채널 추가는 `s0_collect_raw.py`(수집) + `app/rag/_normalize.py`(정규화기)에 더하면 끝.

---

## 표준 레시피 스키마 (1단계 산출, 데이터 계약)

```jsonc
{
  "id": "cookrcp-123",            // 소스접두-원본ID (dedup 키)
  "name": "새우 두부 계란찜",
  "cuisine_type": "반찬",          // 장르
  "ingredients": [                // 재료 (검색·장보기 핵심)
    {"name": "연두부", "qty": 75.0, "unit": "g"},
    {"name": "통깨",   "qty": null, "unit": "약간"}
  ],
  "steps": ["1. ...", "2. ..."],
  "time_min": 30,                 // cookrcp는 소스에 시간 필드 없음 → 30 placeholder
  "difficulty": "medium",
  "calories": 220, "protein": 14.0, "carb": 3.0, "fat": 17.0,  // 1인분
  "source": "cookrcp",
  "source_url": "https://www.foodsafetykorea.go.kr",
  "embed_text": "새우 두부 계란찜 재료: ... 영양: 220kcal ..."   // 3단계에서 정본 재생성
}
```

정규화기 정본 = `app/rag/_normalize.py` (운영 `ingest_recipes.py`와 **같은 파서** — 이원화 방지).

---

## 실행

backend 디렉터리에서, 프로젝트 venv로:

```powershell
# 전체 (수집부터)
.venv\Scripts\python.exe scripts\pipeline\s0_collect_raw.py
.venv\Scripts\python.exe scripts\pipeline\s1_normalize.py
.venv\Scripts\python.exe scripts\pipeline\s2_clean.py
.venv\Scripts\python.exe scripts\pipeline\s3_embed_text.py
.venv\Scripts\python.exe scripts\pipeline\s4_index.py            # DRY-RUN(임베더 확인만, DB 미변경)
.venv\Scripts\python.exe scripts\pipeline\s4_index.py --apply    # 실제 recipe_db 적재
```

- **파서만 고쳤다면** `s1`부터 재실행하면 된다(`s0` 재수집 불요 — raw 보존).
- 4단계는 공유 `recipe_db`를 바꾸므로 **기본 DRY-RUN**, 적재는 `--apply` 명시 필요.
- 임베딩은 bge-m3(LM Studio, `EMBED_PROVIDER=local`). 적재·백엔드·평가가 **같은 임베더**여야 벡터공간이 일치한다.

환경변수: `COOKRCP_LIMIT`(기본 1200) · `MAFRA_LIMIT`(기본 1000) · `MAFRA_NUTRITION_SERVICE`(영양 서비스 ID, 미확정).

---

## 현재 데이터 실태 (2단계 리포트 기준)

| 소스 | 건수 | 재료 분량 | 재료 단위 | 칼로리 | 단백질·탄수·지방 | 조리법 |
|---|---|---|---|---|---|---|
| cookrcp | 1,146 | 94.9% | 96.4% | 99.9% | 99.9% | 99.9% |
| mafra | 537 | 80.3% | 58.8% | 94.2% | **0%** | 100% |
| seed | 10 | 100% | 100% | 100% | 100% | 100% |

코퍼스 합계 1,689건(재료 0개 4건 제거). 최신 수치는 항상 `02_clean/report.json`이 정본.

### 알려진 갭 (가짜로 채우지 않고 드러냄)
1. **mafra 영양(단백질/탄수/지방) = 0%** — 농정원 기본/재료/과정 서비스에 해당 필드가 없다.
   영양 결합 서비스를 추가 수집해야 채워진다(`MAFRA_NUTRITION_SERVICE` 미확정 — 서비스 ID 확인 필요).
   그전까지 mafra 레시피의 P/C/F는 0(placeholder)이며 신뢰 불가.
2. **cookrcp 조리시간 = 30분 placeholder(100%)** — 식약처 소스에 조리시간 필드가 없다.
   조리시간 필터를 정확히 쓰려면 다른 근거가 필요하다.
3. **mafra 재료 단위 58.8%** — `약간`·`1/2모`(분수)처럼 단위가 없거나 분수인 항목이 다수.

### 직전에 고친 것 (파싱)
cookrcp 재료 분량/단위가 ~45% → 94.9%/96.4%로 올랐다. 원인은 재료 텍스트(`RCP_PARTS_DTLS`)에
요리명 줄·섹션 머리말(`고명`, `●양념장 :`)·분량표기(`[1인분]`)가 섞여 있어, 기존 파서가 이들을
가짜 재료로 만들거나(헤더), 기호로 시작하는 줄의 진짜 재료를 통째로 버린 것이었다.
`app/rag/_normalize.py`의 `_parse_cookrcp_ingredient`가 헤더/제목/분량표기를 걷어내고
미터법 수치(`75g`)를 분량으로, 그 앞을 이름으로 잡도록 고쳤다.
