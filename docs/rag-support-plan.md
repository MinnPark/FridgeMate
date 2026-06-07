# RAG 보강 작업 계획 — 팀 요구 기반 (영양·제약·필터·검색 전반)

> 작성: 2026-06-07 · B파트(RAG) · 구현 전 팀 협의용 계획 (정적 스펙 아님, "다음에 할 작업")

## 0. 한 줄
팀이 RAG에 요구하는 **필수(MUST) 반환은 이미 다 충족**. 남은 보강 작업 = **①영양 데이터 품질** **②요리정보 전 필드 기반 필터/검색(제약·시간·장르·재료 등)**. 아래는 "RAG가 할 일 + 팀과 합의할 것".

## 1. 현황 — 팀이 RAG에서 실제 쓰는 것 (다 충족됨)
| 요구자 | 쓰는 필드 | 충족 |
|---|---|---|
| recipe_agent (유일 직접호출 `retrieve_recipes`) | name, ingredients{name,amount,unit}, nutrition{cal,protein,carbs,fat}, score | ✅ |
| meal_agent (selected_recipes 소비) | name, ingredients.name, nutrition* | ✅ |
| shopping_agent (소비) | name, ingredients{name,amount,unit} | ✅ |
| v3.recipe_node (dish_resolver→smart_search) | id, name, ingredients, steps, nutrition*, source_url, time_min, cuisine_type | ✅ |

→ **MUST 필드는 RAG가 다 제공 중.** 작업은 ②③.

## 2. 영양(nutrition) — 할 일
- **문제**: 농정원 537건(코퍼스 32%)의 protein/carbs/fat = 0 (`_normalize.py`가 0 하드코딩, `fetch_mafra`가 영양 API 미수집). → 팀 `nutrition_tools.verify_nutrition_goal`이 거짓 "단백질 미달"/거짓 통과.
- **RAG 작업**: (a) 농정원 영양결합 API를 RECIPE_ID로 조인 → P/C/F 채움 + recipe_db 재적재 / (b) 미상 영양은 0 아닌 None → 검증서 "데이터 없음" 분기 / (c) [후순위] 재료별 영양 분해(`ingredients[].nutrition`), 조리손실 반영.

## 3. 필터·검색 — 요리정보 "모든 필드"를 검색/필터 차원으로 (핵심 확장)
RAG가 가진 레시피 메타를 **전부 검색·필터 조건으로 노출**한다. 현재는 의미검색(name/text) + 일부 필터만이고, 그나마 배선이 안 됨.

| 요리정보 필드 | 필터/검색 종류 | 예 | 현재 | RAG 작업 |
|---|---|---|---|---|
| nutrition.{calories,protein,carbs,fat} | 영양 목표/범위 | "고단백", "저칼로리 600 이하" | ❌ | constraints에 `nutrient_goal`/범위 추가 |
| time_min | 조리시간 | "30분 이내" | ⚠️ 코드만(미배선) + cookrcp time_min 데이터 0(30고정) | time_min 실값 채움 + 배선 |
| cuisine_type | 장르 | "한식만" | ⚠️ 코드만(미배선) | 라벨 정규화 + 배선 |
| ingredients[].name | 재료 포함 | "두부 들어간" | 의미검색만 | 재료 포함 필터 |
| ingredients[].name | **재료 제외(알레르기/제약)** | "계란·밀가루 빼고" | ❌ | constraints `exclude_ingredients` |
| (재고 매칭) | 냉장고 재료 활용도 | "있는 재료로 최대한" | ❌ | `prefer_pantry_coverage` 가중 |
| name/text | 키워드·의미 검색 | (기존 HyDE/Fusion) | ✅ | 유지 |

- **공통 작업**: `integration.search(constraints=)` 를 위 전 필드로 확장하고(현재 cuisine_filter/max_time만), `recipe_agent`가 사용자 요청에서 이 제약을 뽑아 RAG로 **전달(배선)**.
- **개인화**: 사용자 선호 boost(`preference_store`/`agent.py` 코드 있음, 미연결) — 검색 결과 재순위에 반영.
- **대체재 검색**: `sub_indexer.find_substitutes` 를 reflexion 외에도 노출(부족재료 대체).

## 4. 작업 목록 + 소유 구분
| # | 작업 | 소유 | 난이도 |
|---|---|---|---|
| 1 | 농정원 영양 enrich + 재적재 | **RAG 단독** | 중 (외부 API) |
| 2 | 영양 None/"데이터없음" 처리 | RAG + nutrition_tools 협의 | 하 |
| 3 | constraints 전 필드 확장(영양/시간/장르/재료포함·제외) | **RAG 단독** | 중 |
| 4 | cookrcp time_min 실값 + cuisine 라벨 정규화 | **RAG 단독(데이터)** | 중 |
| 5 | constraints 배선(recipe_agent→search) | **팀 협의**(recipe_agent=에이전트 파트) | 하 |
| 6 | 개인화 boost 연결 | **팀 협의**(FridgeMateState에 user_id 추가) | 중 |
| 7 | 대체재 검색 노출 | RAG + shopping 협의 | 하 |

## 5. 구현 전 합의 필요 (팀)
- `FridgeMateState`에 `user_id` 추가(개인화).
- `recipe_agent`가 사용자 제약(영양/시간/장르/재료 제외 등)을 RAG `search(constraints=)`로 전달하는 경로 정의.

---
※ 별개 발견(팀 전달만, RAG 수정 아님): `shopping_tools.py:21` amount/unit None → "None" 문자열로 쿠팡검색 깨질 위험 / shopping_agent 레시피명 매칭 실패 시 빈 재료.
