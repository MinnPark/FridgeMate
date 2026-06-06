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
    kcal = recipe.get("calories", 0)
    protein = recipe.get("protein", 0)
    time_min = recipe.get("time_min", 0)
    cuisine = recipe.get("cuisine_type", "기타")
    return (
        f"{name} 재료: {ingredients} 조리: {steps} "
        f"영양: {kcal}kcal 단백질 {protein}g 시간: {time_min}분 장르: {cuisine}"
    )


def normalize_cookrcp(raw: dict, idx: int) -> NormalizedRecipe:
    """식약처 COOKRCP01 raw → 표준."""
    name = (raw.get("RCP_NM") or "").strip()
    ingredients_raw = (raw.get("RCP_PARTS_DTLS") or "")
    ingredients = []
    for part in re.split(r"[,\n]", ingredients_raw):
        token = part.strip()
        if not token:
            continue
        m = re.match(r"([가-힣A-Za-z\s]+)\s*(\d+(?:\.\d+)?)?\s*(g|kg|ml|개|마리|봉|장|모|컵|큰술|작은술)?", token)
        if m:
            ingredients.append({
                "name": m.group(1).strip(),
                "qty": float(m.group(2)) if m.group(2) else None,
                "unit": m.group(3) or "",
            })

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
        "protein": 0.0,  # 기본정보엔 없음 — 영양 결합정보(464) 연결 시 채움
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
