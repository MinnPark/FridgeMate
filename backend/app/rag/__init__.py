"""RAG 엔진 (이식 — fridge-mate B파트). bge-m3 임베딩 + HyDE/RAG-Fusion/RRF + recipe_db.

자기완결 패키지: import 시 .env 자동 로드(os.getenv 설정 사용). dotenv 미설치/부재 시 무시.
필요 env: EMBED_PROVIDER=local · LMSTUDIO_BASE_URL · LMSTUDIO_API_KEY · EMBED_MODEL_LOCAL ·
          EMBED_SIG · CHROMADB_PATH · LLM_PROVIDER(+키, HyDE/Fusion용) · FRIDGEMATE_USE_LLM.
"""
try:  # 자기완결 env — 그쪽 main 이 dotenv 안 써도 RAG 설정이 잡히게
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # dotenv 미설치 등 — 환경변수가 이미 세팅됐다면 그대로 동작
    pass
