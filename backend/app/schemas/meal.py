from pydantic import BaseModel


class Ingredient(BaseModel):
    name: str
    amount: float
    unit: str


class Recipe(BaseModel):
    name: str
    ingredients: list[Ingredient]
    nutrition: dict[str, float]


class MealPlan(BaseModel):
    strategy: str
    days: list[dict]
