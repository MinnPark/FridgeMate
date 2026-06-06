# FridgeMate backend (FastAPI + RAG). chroma 산출물(data/chroma) 포함. 시크릿은 굽지 않음(.env 는 런타임 주입).
FROM python:3.11-slim

WORKDIR /app

# 빌드 캐시 활용: requirements 먼저
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 + 사전임베딩 산출물(data/chroma) 복사 (.dockerignore 가 .env/__pycache__ 제외)
COPY . .

EXPOSE 8742
# .env 는 docker run --env-file 또는 compose env_file 로 주입 (LMSTUDIO_API_KEY 등)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8742"]
