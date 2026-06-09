from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage, SystemMessage          # ← 추가
from pydantic import BaseModel, Field

from app.graph.orchestrator import build_graph, build_tool_graph          # ← FRIDGEMATE_TOOLS 제거
from app.tools.nutrition_tools import verify_nutrition_goal_tool          # ← 직접 import
from app.tools.shopping_tools import search_coupang_products_tool         # ← 직접 import
from app.llm import get_llm                                              # ← 추가
from app.prompts.tool_prompts import TOOL_SYSTEM_PROMPT, build_tool_prompt  # ← 추가
from app.tools.product_rank_tools import rank_product_candidates
from app.tools.budget_reflexion_tools import build_budget_reflexion       # ← 예산 회고
from app.v3.graph import compile_graph                                    # ← v3 그래프
from app.v3.api_adapter import (                                          # ← v3 어댑터
    chat_request_to_v3_state,
    v3_state_to_chat_state,
)


app = FastAPI(title="FridgeMate AI")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

graph      = build_graph()                                               # 기존 /chat 전용
graph_tool = build_tool_graph()                                          # ← /chat/tool 전용
graph_v3   = compile_graph()                                             # ← /chat/v3 전용 (async + checkpointer)


class IngredientEntry(BaseModel):
    name: str
    amount: str
    expiration_date: str
    storage_type: str


class ChatRequest(BaseModel):
    message: str = Field(..., examples=["냉장고에 두부, 계란, 애호박이 있어. 고단백 한식 식단 짜줘"])
    budget_limit: int | None = Field(default=None, examples=[30000])
    ingredient_entries: list[IngredientEntry] = Field(default_factory=list)
    excluded_ingredients: str | None = Field(default=None, examples=["닭가슴살,돼지고기"])
    mode: str | None = Field(default="today", examples=["today", "weekend", "mealprep", "goal"])  # ← 추가
    people: int = Field(default=1, examples=[1, 2, 4])               # ← v3 인원수 (gap_calc 가중)

    # 영양 목표
    protein_target_gram:  int | None = Field(default=None, examples=[120])
    calorie_target_kcal:  int | None = Field(default=None, examples=[1700])
    carbs_target_gram:    int | None = Field(default=None, examples=[150])
    fat_target_gram:      int | None = Field(default=None, examples=[55])


class ProductCandidate(BaseModel):
    name: str
    price: int
    url: str
    isAd: bool = False
    isRocket: bool = False
    delivery: str | None = None
    amountG: float | None = None
    score: float = 0


class ProductRankRequest(BaseModel):
    ingredient: str
    needed_amount: float | None = None
    needed_unit: str | None = None
    preference: str | None = None
    recipe_contexts: list[str] = Field(default_factory=list)
    candidates: list[ProductCandidate]


def _build_nutrition_goal(req: ChatRequest) -> dict:
    goal: dict = {}
    if req.protein_target_gram:    # None, 0 모두 제외 ← 핵심 수정
        goal["protein_target"] = req.protein_target_gram
    if req.calorie_target_kcal:    # None, 0 모두 제외
        goal["calorie_target"] = req.calorie_target_kcal
    if req.carbs_target_gram:
        goal["carbs_target"] = req.carbs_target_gram
    if req.fat_target_gram:
        goal["fat_target"] = req.fat_target_gram
    return goal


def _build_invoke_input(req: ChatRequest) -> dict:
    """graph.invoke() 공통 입력 구성"""
    return {
        "user_input":           req.message,
        "ingredient_entries":   [e.model_dump() for e in req.ingredient_entries],
        "budget_limit":         req.budget_limit,
        "nutrition_goal":       _build_nutrition_goal(req),
        "excluded_ingredients": req.excluded_ingredients or "",
        "mode":                 req.mode or "today",                     # ← 추가
        "retry_count":          0,
        "logs":                 [],
    }


def _run_tool_by_name(
    name: str,
    *,
    selected_recipes: list,
    nutrition_goal: dict,
    missing_ingredients: list,
):
    if name == "verify_nutrition_goal_tool":
        return verify_nutrition_goal_tool.invoke(
            {
                "recipes": selected_recipes,
                "goal": nutrition_goal,
                "num_days": 3,
            }
        )
    if name == "search_coupang_products_tool":
        return search_coupang_products_tool.invoke(
            {"missing_ingredients": missing_ingredients}
        )
    raise ValueError(f"Unknown tool: {name}")


def _required_tool_names(
    *,
    mode: str,
    nutrition_goal: dict,
    missing_ingredients: list,
) -> list[str]:
    tool_names: list[str] = []
    if nutrition_goal:
        tool_names.append("verify_nutrition_goal_tool")
    if mode != "today" and missing_ingredients:
        tool_names.append("search_coupang_products_tool")
    return tool_names


def _run_required_tools(
    *,
    mode: str,
    selected_recipes: list,
    nutrition_goal: dict,
    missing_ingredients: list,
) -> tuple[list[str], dict]:
    calls: list[str] = []
    results: dict = {}
    for name in _required_tool_names(
        mode=mode,
        nutrition_goal=nutrition_goal,
        missing_ingredients=missing_ingredients,
    ):
        results[name] = _run_tool_by_name(
            name,
            selected_recipes=selected_recipes,
            nutrition_goal=nutrition_goal,
            missing_ingredients=missing_ingredients,
        )
        calls.append(name)
    return calls, results


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat")
def chat(req: ChatRequest):
    """기존 파이프라인 — 변경 없음"""
    result = graph.invoke(_build_invoke_input(req))
    return result


@app.post("/chat/tool")
def chat_with_tools(req: ChatRequest):
    """
    /chat/tool — Tool Calling 엔드포인트

    흐름:
      ① 선형 파이프라인 실행 (pantry→recipe→meal→shopping)
      ② selected_recipes, nutrition_goal, missing_ingredients 확보
      ③ LLM이 2개 tool 중 선택적 호출
         - verify_nutrition_goal_tool  (nutrition_goal 있을 때)
         - search_coupang_products_tool (missing 있고 today 아닐 때)
      ④ 결과 반환
    """
    mode = req.mode or "today"

    # ① 선형 파이프라인 실행
    pipeline_result = graph_tool.invoke(_build_invoke_input(req))

    # ② 파이프라인 결과 추출
    selected_recipes    = pipeline_result.get("selected_recipes",    [])
    nutrition_goal      = pipeline_result.get("nutrition_goal",      {})
    missing_ingredients = pipeline_result.get("missing_ingredients", [])

    # ③ LLM 메시지 구성 (tool 호출 판단 근거 포함)
    nutrition_summary = (
        f"단백질 {nutrition_goal.get('protein_target')}g, "
        f"칼로리 {nutrition_goal.get('calorie_target')}kcal"
        if nutrition_goal
        else "입력 없음"
    )
    missing_summary = (
        ", ".join(
            f"{m.get('name')} {m.get('amount', '')}{m.get('unit', '')}"
            for m in missing_ingredients
        )
        if missing_ingredients
        else "없음 (냉장고에 모두 있음)"
    )

    tool_context = (
        f"\n\n[파이프라인 분석 결과]\n"
        f"영양 목표:    {nutrition_summary}\n"
        f"부족한 재료:  {missing_summary}\n"
        f"선택된 레시피: {len(selected_recipes)}개"
    )

    final_message = build_tool_prompt(mode, req.message) + tool_context

    # ④ LLM + tools 조건부 바인딩 ← 수정
    try:
        llm   = get_llm()
        tools = []

        if nutrition_goal:              # 영양 목표 있을 때만 verify 포함
            tools.append(verify_nutrition_goal_tool)

        if mode != "today":             # today 제외한 모드만 search 포함
            tools.append(search_coupang_products_tool)

        llm_with_tools = llm.bind_tools(tools) if tools else llm

        response = llm_with_tools.invoke([
            SystemMessage(content=TOOL_SYSTEM_PROMPT),
            HumanMessage(content=final_message),
        ])

    except Exception as e:
        # Fallback: 로컬 LLM tool_calls 미지원 시에도 mode 정책대로 도구 실행
        tool_calls_made, tool_results = _run_required_tools(
            mode=mode,
            selected_recipes=selected_recipes,
            nutrition_goal=nutrition_goal,
            missing_ingredients=missing_ingredients,
        )
        if mode == "today":
            pipeline_result.pop("missing_ingredients", None)
            pipeline_result.pop("cart_items", None)
        return {
            **pipeline_result,
            "tool_calls_made": tool_calls_made,
            "tool_results":    tool_results,
            "mode":            mode,
            "fallback":        True,
            "fallback_reason": str(e),
        }

    # ⑤ LLM이 선택한 tool 실행
    tool_calls_made = []
    tool_results    = {}

    # tools 딕셔너리 (FRIDGEMATE_TOOLS 대신 조건부 tools 사용) ← 수정
    tools_map = {t.name: t for t in tools}

    if hasattr(response, "tool_calls") and response.tool_calls:
        for tc in response.tool_calls:
            name = tc["name"]

            if name not in tools_map:   # ← 바인딩 안 된 tool 차단
                continue

            tool_result = _run_tool_by_name(
                name,
                selected_recipes=selected_recipes,
                nutrition_goal=nutrition_goal,
                missing_ingredients=missing_ingredients,
            )
            tool_calls_made.append(name)
            tool_results[name] = tool_result

    # LLM이 도구를 호출하지 않았더라도 UI 입력 정책상 필요한 도구는 실행한다.
    for required_name in _required_tool_names(
        mode=mode,
        nutrition_goal=nutrition_goal,
        missing_ingredients=missing_ingredients,
    ):
        if required_name in tool_results:
            continue
        tool_results[required_name] = _run_tool_by_name(
            required_name,
            selected_recipes=selected_recipes,
            nutrition_goal=nutrition_goal,
            missing_ingredients=missing_ingredients,
        )
        tool_calls_made.append(required_name)

    # today 모드 → 장보기 결과 제거 ← 추가
    if mode == "today":
        pipeline_result.pop("missing_ingredients", None)
        pipeline_result.pop("cart_items", None)

    return {
        **pipeline_result,
        "tool_calls_made": tool_calls_made,
        "tool_results":    tool_results,
        "mode":            mode,
        "fallback":        False,
    }


@app.post("/chat/v3")
async def chat_v3(req: ChatRequest):
    """
    /chat/v3 — v3 그래프 엔드포인트 (점진 전환용)

    classic(/chat, /chat/tool)은 그대로 두고 v3 그래프를 병행 운영한다.
    어댑터가 ChatRequest ↔ v3 state 를 양방향 변환하므로 응답은 기존 ChatState(snake)
    형태로 나가 프론트(chatAdapter.ts)가 무수정으로 소비한다.

    흐름:
      orchestrator → pantry → intake → meal_plan_composer → recipe
        → gap_calc → shopping_rank → judge ─[FAIL,<3]→ reflect → … / ─[PASS]→ cart → cooking_guide
    """
    v3_input = chat_request_to_v3_state(req.model_dump())
    config = {"configurable": {"thread_id": v3_input["thread_id"]}}
    result = await graph_v3.ainvoke(v3_input, config=config)
    return v3_state_to_chat_state(result, req.model_dump())


@app.post("/shopping/rank-products")
def rank_products(req: ProductRankRequest):
    return rank_product_candidates(
        ingredient=req.ingredient,
        needed_amount=req.needed_amount,
        needed_unit=req.needed_unit,
        preference=req.preference,
        recipe_contexts=req.recipe_contexts,
        candidates=[candidate.model_dump() for candidate in req.candidates],
    )


class BudgetReflexionItem(BaseModel):
    ingredient: str
    recipe_contexts: list[str] = Field(default_factory=list)
    selected: dict = Field(default_factory=dict)          # {name, price, url}
    candidates: list[dict] = Field(default_factory=list)  # [{name, price, url, delivery, isRocket, amountG}]


class BudgetReflexionRequest(BaseModel):
    budget: int = Field(..., examples=[30000])
    preference: str | None = Field(default=None, examples=["price"])
    items: list[BudgetReflexionItem]


@app.post("/shopping/budget-reflexion")
def budget_reflexion(req: BudgetReflexionRequest):
    """실가격 확정 후 예산 초과 회고 — 더 싼 후보 교체(swap) → 그래도 초과면 품목 제거(drop) 제안."""
    return build_budget_reflexion(
        budget=req.budget,
        preference=req.preference,
        items=[i.model_dump() for i in req.items],
    )
