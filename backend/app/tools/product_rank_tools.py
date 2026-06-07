import json
import re
from typing import Any

from app.llm import generate_json


PRODUCT_RANK_PROMPT = """
당신은 식재료 장보기 상품을 판별하는 Shopping Agent의 상품 선택 도구입니다.
사용자가 요청한 식재료 자체를 구매할 수 있는 상품인지 의미적으로 판단하세요.
해당 재료가 사용될 레시피 이름을 참고해 조리 목적에 맞는 형태를 고르세요.

판단 우선순위:
1. 요청 식재료 자체 또는 일반적인 동의어 상품인지
2. 요리에 사용하는 원재료인지
3. 레시피 용도에 맞는 종류인지
4. 맛/향만 첨가된 과자, 음료, 즉석식품, 조리 완제품, 반려동물용, 모형, 씨앗이 아닌지
5. 필요 수량 또는 용량과 지나치게 동떨어지지 않는지
6. 위 조건을 만족하는 후보 중 가격과 배송 조건이 합리적인지

주의할 예:
- "간장"이 일반 조리용으로 필요하면 회간장, 초밥간장, 양념소스보다 일반 양조간장/진간장을 우선합니다.
- "쇠고기"가 재료로 필요하면 언양식 불고기, 소불고기 밀키트, 양념육 같은 조리 제품이 아니라 생고기를 고릅니다.
- 레시피가 특정 종류를 요구할 때만 국간장, 회간장, 다진 고기 같은 세부 형태를 선택합니다.

반드시 전달된 candidate_id 중 하나만 선택하세요.
적절한 후보가 없으면 selected_id를 null로 반환하세요.
confidence는 0과 1 사이 숫자여야 합니다.
JSON object만 반환하세요:
{
  "selected_id": 1 또는 null,
  "confidence": 0.0,
  "reason": "한국어 한 문장"
}
""".strip()

PROCESSED_TERMS = (
    "과자",
    "스낵",
    "칩",
    "음료",
    "주스",
    "즙",
    "차",
    "티백",
    "시즈닝",
    "조미료",
    "밀키트",
    "언양식",
    "양념육",
    "떡갈비",
    "함박",
    "완자",
    "회간장",
    "초밥간장",
    "사료",
    "간식",
    "모형",
    "장난감",
    "씨앗",
    "종자",
    "모종",
)


def _normalize(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", (value or "").lower())


def _fallback_candidate(ingredient: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    needle = _normalize(ingredient)
    best: tuple[float, int] | None = None

    for index, candidate in enumerate(candidates):
        name = _normalize(str(candidate.get("name") or ""))
        if not name:
            continue
        if any(term in name and term not in needle for term in PROCESSED_TERMS):
            continue
        relevance = 2.0 if needle and needle in name else 0.0
        relevance += min(float(candidate.get("score") or 0), 3.0) * 0.1
        if candidate.get("isRocket"):
            relevance += 0.05
        if best is None or relevance > best[0]:
            best = (relevance, index)

    selected_index = best[1] if best and best[0] > 0 else None
    return {
        "selected_id": selected_index,
        "confidence": 0.55 if selected_index is not None else 0.0,
        "reason": (
            "규칙 기반 관련성 점수가 가장 높은 후보입니다."
            if selected_index is not None
            else "규칙 기반으로도 적합한 원재료 후보를 찾지 못했습니다."
        ),
    }


def rank_product_candidates(
    *,
    ingredient: str,
    needed_amount: float | None,
    needed_unit: str | None,
    preference: str | None,
    recipe_contexts: list[str],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    limited = candidates[:5]
    fallback = _fallback_candidate(ingredient, limited)
    prompt_candidates = [
        {
            "candidate_id": index,
            "name": candidate.get("name"),
            "price": candidate.get("price"),
            "delivery": candidate.get("delivery"),
            "is_rocket": bool(candidate.get("isRocket")),
            "amount": candidate.get("amountG"),
        }
        for index, candidate in enumerate(limited)
    ]
    result = generate_json(
        system_prompt=PRODUCT_RANK_PROMPT,
        user_prompt=(
            f"요청 식재료: {ingredient}\n"
            f"필요량: {needed_amount if needed_amount is not None else '미지정'}"
            f"{needed_unit or ''}\n"
            f"사용 레시피: {', '.join(recipe_contexts) if recipe_contexts else '미지정'}\n"
            f"선호 조건: {preference or 'price'}\n"
            f"상품 후보:\n{json.dumps(prompt_candidates, ensure_ascii=False)}"
        ),
        fallback=fallback,
        temperature=0.0,
    )

    raw_id = result.get("selected_id")
    selected_id = raw_id if isinstance(raw_id, int) and 0 <= raw_id < len(limited) else None
    try:
        confidence = max(0.0, min(1.0, float(result.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0

    used_llm = bool(result.get("_meta", {}).get("used_llm"))
    auto_select = selected_id is not None and (not used_llm or confidence >= 0.75)
    return {
        "selected_id": selected_id,
        "confidence": confidence,
        "reason": str(result.get("reason") or "판정 이유가 제공되지 않았습니다."),
        "auto_select": auto_select,
        "provider": result.get("_meta", {}).get("provider", "unknown"),
        "used_llm": used_llm,
    }
