"""레시피 정규화 + embed_text 생성.

원본 (식약처/농진청/만개의레시피) → 표준 dict → 검색 친화 텍스트 → 임베딩

embed_text 형식 (검색 품질 핵심):
  "{이름} 재료: {재료1}, {재료2} 조리법: {핵심동사} 영양: {kcal}kcal 단백질 {g}g 시간: {분}분 장르: {한식}"
"""
from __future__ import annotations

import re
from typing import TypedDict


class NormalizedRecipe(TypedDict):
    id: str
    name: str
    cuisine_type: str          # 한식 / 양식 / 일식 / 중식 / 기타
    ingredients: list[dict]    # [{name, qty, unit}]
    steps: list[str]
    time_min: int
    difficulty: str            # easy / medium / hard
    calories: int              # 1인분 기준
    protein: float
    carb: float
    fat: float
    source: str                # "cookrcp" / "rda" / "manual"
    source_url: str
    embed_text: str            # RAG 검색용


_STEP_VERBS = re.compile(r"(볶|끓|찌|굽|튀기|삶|데치|썰|손질|버무리|섞|넣)")

# cookrcp 재료 텍스트(RCP_PARTS_DTLS) 파싱 ─────────────────────────────────
# 미터법(g/ml...) 우선 + 가정용 계량. 기호로 시작하는 단위(예: %)는 의도적으로 제외.
_ING_UNIT = (r"kg|g|mg|ml|l|개|마리|봉지|봉|장|모|컵|큰술|작은술|꼬집|줌|쪽|단|알"
             r"|조각|대|cm|인분|미|편|통|줄기|포기|뿌리|국자|스푼|T|t")
_ING_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(" + _ING_UNIT + r")")
_ING_AMT_NONE_RE = re.compile(r"약간|적당량|적당히|조금|소량|기호")
# 재료가 아닌 섹션 머리말 — 단독으로 오면 스킵 (소스 텍스트에 '●양념장' 등 헤더가 섞임)
_ING_SECTIONS = {"고명", "양념", "양념장", "소스", "부재료", "주재료", "재료", "육수",
                 "국물", "반죽", "고물", "곁들임", "드레싱", "육수재료", "양념재료"}


def _parse_cookrcp_ingredient(token: str, dish_nospace: str) -> dict | None:
    """RCP_PARTS_DTLS 한 토큰 → {name, qty, unit} 또는 None(섹션/제목/빈값).

    소스 예: '연두부 75g(3/4모)', '●양념장 : 고춧가루 4g(1작은술)', '[1인분]조선부추 50g', '통깨 약간'.
    미터법 수치가 가정용 계량 앞에 오므로 첫 수치+단위를 분량으로, 그 앞을 이름으로 취한다.
    """
    t = token.strip()
    if not t:
        return None
    if ":" in t or "：" in t:                        # '●양념장 : 재료' → 콜론 뒤 실제 재료만
        t = re.split(r"[:：]", t, maxsplit=1)[-1].strip()
    t = re.sub(r"^[\[\(][^\]\)]*[\]\)]\s*", "", t)   # 선두 분량표기 [1인분]/(4인분) 제거
    t = t.lstrip("●·*-•◦∙▶▪ ").strip()
    if not t or t in _ING_SECTIONS:
        return None
    if t.replace(" ", "") == dish_nospace:           # 첫 줄에 박힌 요리명
        return None
    m = _ING_UNIT_RE.search(t)
    if m:
        name = t[:m.start()].strip().rstrip(":").strip()
        qty, unit = float(m.group(1)), m.group(2)
    else:                                            # '약간/적당량' → 수치 없는 실재료
        a = _ING_AMT_NONE_RE.search(t)
        name = (t[:a.start()] if a else t).strip()
        qty, unit = None, ("약간" if a else "")
    name = name.strip(" ,.·-()")
    if not name or len(name) > 20:                   # 설명문 등 노이즈 컷
        return None
    return {"name": name, "qty": qty, "unit": unit}


def _extract_core_verbs(steps: list[str], limit: int = 3) -> list[str]:
    """레시피 단계에서 핵심 동사 추출 (검색 토큰화에 활용)."""
    verbs: list[str] = []
    for step in steps:
        for m in _STEP_VERBS.finditer(step):
            verbs.append(m.group(0))
            if len(verbs) >= limit:
                return verbs
    return verbs


def make_embed_text(recipe: dict) -> str:
    name = recipe["name"]
    ingredients = ", ".join(i["name"] for i in recipe["ingredients"])      # 전체 재료 (recall)
    steps = " ".join(recipe.get("steps") or [])[:400]                       # 과정 텍스트(방법 의미) — 희석 방지 컷
    kcal = recipe.get("calories") or 0                                      # None(영양 미수집) → 0 (검색텍스트 오염 방지)
    protein = recipe.get("protein") or 0
    time_min = recipe.get("time_min") or 0
    cuisine = recipe.get("cuisine_type", "기타")
    return (
        f"{name} 재료: {ingredients} 조리: {steps} "
        f"영양: {kcal}kcal 단백질 {protein}g 시간: {time_min}분 장르: {cuisine}"
    )


def normalize_cookrcp(raw: dict, idx: int) -> NormalizedRecipe:
    """식약처 COOKRCP01 raw → 표준."""
    name = (raw.get("RCP_NM") or "").strip()
    dish_nospace = name.replace(" ", "")
    ingredients = []
    for part in re.split(r"[,\n]", raw.get("RCP_PARTS_DTLS") or ""):
        item = _parse_cookrcp_ingredient(part, dish_nospace)
        if item:
            ingredients.append(item)

    steps = []
    for k in [f"MANUAL{i:02d}" for i in range(1, 21)]:
        v = (raw.get(k) or "").strip()
        if v:
            steps.append(v)

    recipe = {
        "id": f"cookrcp-{raw.get('RCP_SEQ', idx)}",
        "name": name,
        "cuisine_type": (raw.get("RCP_PAT2") or "한식").strip(),
        "ingredients": ingredients,
        "steps": steps,
        "time_min": 30,  # cookrcp 에 시간 필드 없음 — Sprint 2 추정 로직 추가
        "difficulty": "medium",
        "calories": int(float(raw.get("INFO_ENG") or 0)),
        "protein": float(raw.get("INFO_PRO") or 0),
        "carb": float(raw.get("INFO_CAR") or 0),
        "fat": float(raw.get("INFO_FAT") or 0),
        "source": "cookrcp",
        "source_url": "https://www.foodsafetykorea.go.kr",
    }
    recipe["embed_text"] = make_embed_text(recipe)
    return recipe  # type: ignore[return-value]


_LEVEL_MAP = {"아무나": "easy", "초급": "easy", "중급": "medium", "고급": "hard"}


def _parse_time_min(raw: str) -> int:
    """COOKING_TIME ('60분이내', '30분', '2시간') → 분."""
    s = raw or ""
    h = re.search(r"(\d+)\s*시간", s)
    m = re.search(r"(\d+)\s*분", s)
    total = (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)
    if total == 0:
        d = re.search(r"\d+", s)
        total = int(d.group(0)) if d else 30
    return total


def _first_int(raw: str) -> int:
    """'580Kcal', '4인분' 등에서 첫 정수 추출 (없으면 0)."""
    m = re.search(r"\d+", raw or "")
    return int(m.group(0)) if m else 0


def normalize_mafra(basic: dict, ingredients: list[dict], steps: list[dict]) -> NormalizedRecipe:
    """농림축산식품(MAFRA) 레시피 기본/재료/과정 조인 → 표준.

    basic = TI_RECIPE_INFO row, ingredients/steps = 같은 RECIPE_ID 의 행들.
    """
    rid = str(basic.get("RECIPE_ID", "")).strip()

    ing = []
    for r in sorted(ingredients, key=lambda x: int(x.get("IRDNT_SN") or 0)):
        token = (r.get("IRDNT_NM") or "").strip()
        if not token:
            continue
        cap = (r.get("IRDNT_CPCTY") or "").strip()
        m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(g|kg|ml|l|개|마리|봉|장|모|컵|큰술|작은술|꼬집|줌|쪽|단)?", cap)
        ing.append({
            "name": token,
            "qty": float(m.group(1)) if m and m.group(1) else None,
            "unit": (m.group(2) if m else "") or "",
        })

    step_list = [
        (s.get("COOKING_DC") or "").strip()
        for s in sorted(steps, key=lambda x: int(x.get("COOKING_NO") or 0))
        if (s.get("COOKING_DC") or "").strip()
    ]

    recipe = {
        "id": f"mafra-{rid}",
        "name": (basic.get("RECIPE_NM_KO") or "").strip(),
        "cuisine_type": (basic.get("NATION_NM") or "기타").strip(),
        "ingredients": ing,
        "steps": step_list,
        "time_min": _parse_time_min(basic.get("COOKING_TIME")),
        "difficulty": _LEVEL_MAP.get((basic.get("LEVEL_NM") or "").strip(), "medium"),
        "calories": _first_int(basic.get("CALORIE")),
        # 226 기본정보엔 P/C/F 없음(열량만). 채울 소스가 없어 0 으로 둔다 — 응답은
        # integration.to_contract 에서 nutrition_available=False 로 '미상'을 식별한다.
        "protein": 0.0,
        "carb": 0.0,
        "fat": 0.0,
        "source": "mafra",
        "source_url": "https://data.mafra.go.kr",
    }
    recipe["embed_text"] = make_embed_text(recipe)
    return recipe  # type: ignore[return-value]


def normalize_rda(raw: dict, idx: int) -> NormalizedRecipe:
    """농촌진흥청 raw → 표준 (필드명만 다름)."""
    recipe = {
        "id": f"rda-{raw.get('id', idx)}",
        "name": raw.get("name", "").strip(),
        "cuisine_type": raw.get("category", "한식"),
        "ingredients": raw.get("ingredients", []),
        "steps": raw.get("steps", []),
        "time_min": raw.get("time_min", 30),
        "difficulty": raw.get("difficulty", "medium"),
        "calories": int(raw.get("calories", 0)),
        "protein": float(raw.get("protein", 0)),
        "carb": float(raw.get("carb", 0)),
        "fat": float(raw.get("fat", 0)),
        "source": "rda",
        "source_url": "https://koreanfood.rda.go.kr",
    }
    recipe["embed_text"] = make_embed_text(recipe)
    return recipe  # type: ignore[return-value]
