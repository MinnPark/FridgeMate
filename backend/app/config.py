from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "FridgeMate AI"
    max_shopping_retries: int = 3
    hyde_query_length_threshold: int = 10
    rag_fusion_query_count: int = 4


settings = Settings()
