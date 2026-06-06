from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.graph.orchestrator import build_graph


app = FastAPI(title="FridgeMate AI")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev: 프론트 포트 무관 허용 (8743 등)
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat")
def chat(req: ChatRequest):
    result = graph.invoke(
        {
            "user_input": req.message,
            "ingredient_entries": [
                entry.model_dump() for entry in req.ingredient_entries
            ],
            "budget_limit": req.budget_limit,
            "retry_count": 0,
            "logs": [],
        }
    )
    return result
