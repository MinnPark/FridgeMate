"""예산 검증 — shopping_rank_node 가 사용.

selected shopping_list 합계 vs budget 비교. Tool 수치 기반.

Function calling 도입 시 tool spec:
  name        : validate_budget
  description : 장바구니 선택 합계가 예산을 초과했는지 + 초과율
  parameters  : {total_price: int, budget: int}
  returns     : {ok: bool, over_amount: int, over_pct: float}
"""
from __future__ import annotations


def validate_budget(total_price: int, budget: int) -> dict:
    """예산 검증.

    - budget<=0 → 검증 비활성 (ok=True)
    - total<=budget → ok
    - 그 외 → over_amount/over_pct 계산
    """
    if budget <= 0 or total_price <= budget:
        return {"ok": True, "over_amount": 0, "over_pct": 0.0}
    over = total_price - budget
    return {
        "ok": False,
        "over_amount": over,
        "over_pct": round(over / budget, 3),
    }
