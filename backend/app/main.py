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


app = FastAPI(title="FridgeMate AI")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

graph      = build_graph()                                               # 기존 /chat 전용
graph_tool = build_tool_graph()                                          # ← /chat/tool 전용


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
        # Fallback: 로컬 LLM tool_calls 미지원 시
        return {
            **pipeline_result,
            "tool_calls_made": [],
            "tool_results":    {},
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

            if name == "verify_nutrition_goal_tool":
                args = {
                    "recipes":  selected_recipes,
                    "goal":     nutrition_goal,
                    "num_days": 3,
                }
            elif name == "search_coupang_products_tool":
                args = {
                    "missing_ingredients": missing_ingredients,
                }
            else:
                args = tc.get("args", {})

            tool_result = tools_map[name].invoke(args)   # ← tools_map 사용
            tool_calls_made.append(name)
            tool_results[name] = tool_result

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
