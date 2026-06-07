from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.graph.orchestrator import build_graph
from app.tools.product_rank_tools import rank_product_candidates


app = FastAPI(title="FridgeMate AI")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
graph = build_graph()


class IngredientEntry(BaseModel):
    name: str
    amount: str
    expiration_date: str
    storage_type: str


class ChatRequest(BaseModel):
    message: str = Field(..., examples=["냉장고에 두부, 계란, 애호박이 있어. 고단백 한식 식단 짜줘"])
    budget_limit: int | None = Field(default=None, examples=[30000])
    ingredient_entries: list[IngredientEntry] = Field(default_factory=list)
    excluded_ingredients: str | None = Field(default=None, examples=["닭가슴살,돼지고기"])  # ← 추가

    # 영양 목표 — 모두 optional, 없으면 nutrition_tools.py 기본값 사용
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat")
def chat(req: ChatRequest):
    # nutrition_goal: 하나라도 값이 있으면 dict 구성, 모두 None이면 빈 dict
    nutrition_goal: dict = {}
    if req.protein_target_gram is not None:
        nutrition_goal["protein_target"] = req.protein_target_gram
    if req.calorie_target_kcal is not None:
        nutrition_goal["calorie_target"] = req.calorie_target_kcal
    if req.carbs_target_gram is not None:
        nutrition_goal["carbs_target"] = req.carbs_target_gram
    if req.fat_target_gram is not None:
        nutrition_goal["fat_target"] = req.fat_target_gram

    result = graph.invoke(
        {
            "user_input":            req.message,
            "ingredient_entries":    [
                entry.model_dump() for entry in req.ingredient_entries
            ],
            "budget_limit":          req.budget_limit,
            "nutrition_goal":        nutrition_goal,
            "excluded_ingredients":  req.excluded_ingredients or "",  # ← 추가
            "retry_count":           0,
            "logs":                  [],
        }
    )
    return result


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
