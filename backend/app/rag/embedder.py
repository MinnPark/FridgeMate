"""Cohere embed-multilingual-v3 래퍼.

규칙 (변경 금지):
  - 인덱싱: embed_documents(texts) → input_type='search_document'
  - 검색:   embed_query(query)     → input_type='search_query'
혼용 시 검색 품질 30%+ 저하.

Mock 모드 (FRIDGEMATE_MOCK_MODE=true 또는 COHERE_API_KEY 미설정):
  - 결정론적 해시 기반 1024차원 벡터 반환 (외부 호출 없이 ChromaDB 인덱싱·검색 작동)
"""
from __future__ import annotations

import hashlib
import os
import struct
from typing import Optional

_EMBED_DIM = 1024


def _token_vector(token: str, dim: int = _EMBED_DIM) -> list[float]:
    """단일 토큰 → deterministic 벡터 (input_type prefix 제거 — 동일 토큰은 동일 벡터)."""
    h = hashlib.sha256(token.encode("utf-8")).digest()
    vals: list[float] = []
    seed = h
    while len(vals) < dim:
        seed = hashlib.sha256(seed).digest()
        for i in range(0, len(seed), 4):
            x = struct.unpack(">I", seed[i:i + 4])[0]
            vals.append((x / 2**32) * 2 - 1)
            if len(vals) >= dim:
                break
    return vals


def _tokenize(text: str) -> list[str]:
    """간단 한국어 토크나이저 — 2~4글자 어절 + 공백/특수문자 제거."""
    cleaned = text.replace(":", " ").replace(",", " ").replace(".", " ")
    raw_tokens = [t for t in cleaned.split() if len(t) >= 2]
    # 2~4글자 n-gram 도 추가 (부분 매칭 강화)
    extras: list[str] = []
    for tok in raw_tokens:
        if len(tok) > 4:
            for i in range(len(tok) - 1):
                extras.append(tok[i:i + 2])
    return raw_tokens + extras


def _hash_vector(text: str, dim: int = _EMBED_DIM) -> list[float]:
    """bag-of-tokens mock 임베딩.

    같은 토큰이 들어간 두 텍스트는 유사한 벡터를 갖는다.
    → 검색 시 "김치찌개" 쿼리와 "김치찌개 재료: ..." 문서가 매칭됨.
    """
    tokens = _tokenize(text)
    if not tokens:
        tokens = [text]

    # 토큰별 벡터 합산 → bag-of-words 임베딩
    summed = [0.0] * dim
    for tok in tokens:
        v = _token_vector(tok, dim)
        for i, x in enumerate(v):
            summed[i] += x

    # L2 정규화
    norm = sum(v * v for v in summed) ** 0.5 or 1.0
    return [v / norm for v in summed]


class CohereEmbedder:
    """Cohere 래퍼 + 명시적 input_type 분리 + Redis 캐시(옵션) + mock fallback."""

    def __init__(self, *, mock: Optional[bool] = None):
        self.provider = self._resolve_provider(mock)
        self.mock = self.provider == "mock"
        self._client = None
        self._cache = None

        if self.provider == "local":
            # LM Studio 등 OpenAI 호환 임베딩 서버 (bge-m3, 1024d). input_type 비대칭 없음.
            self.base_url = os.getenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")
            self.model = os.getenv("EMBED_MODEL_LOCAL", "text-embedding-bge-m3")
        elif self.provider == "cohere":
            self.model = os.getenv("COHERE_MODEL", "embed-multilingual-v3")
            import cohere
            self._client = cohere.Client(api_key=os.environ["COHERE_API_KEY"])
            try:
                import redis
                self._cache = redis.Redis.from_url(os.environ["REDIS_URL"])
                self._cache.ping()
            except Exception:
                self._cache = None  # 캐시 없어도 동작
        else:  # mock
            self.model = os.getenv("COHERE_MODEL", "embed-multilingual-v3")

    @property
    def signature(self) -> str:
        """벡터공간 식별자 — 인덱스↔쿼리 임베더 일치 가드(embed_sig)의 정본.

        같은 모델(예: bge-m3)을 로컬(LM Studio)에서 인덱싱하고 서빙 시 원격 URL로 쿼리할 때,
        엔드포인트가 모델 id 문자열을 다르게 노출하면(text-embedding-bge-m3 vs bge-m3) sig 가
        달라져 코퍼스를 거짓 wipe 한다. `EMBED_SIG` 를 설정하면 URL/모델ID 문자열과 무관하게
        '같은 공간'임을 명시(로컬·서빙에 동일 값) → 거짓 불일치 방지. 미설정 시 provider:model.
        """
        explicit = os.getenv("EMBED_SIG", "").strip()
        return explicit or f"{self.provider}:{self.model}"

    @staticmethod
    def _resolve_provider(mock: Optional[bool]) -> str:
        """EMBED_PROVIDER 우선. 없으면 기존 동작(cohere/mock) 유지."""
        explicit = os.getenv("EMBED_PROVIDER", "").strip().lower()
        if explicit:
            return explicit
        if mock is True:
            return "mock"
        if mock is False:
            return "cohere"
        if os.getenv("FRIDGEMATE_MOCK_MODE", "true").lower() == "true" or not os.getenv("COHERE_API_KEY"):
            return "mock"
        return "cohere"

    # ── 공용 API ────────────────────────────────────────────────────────
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts, input_type="search_document")

    async def embed_query(self, query: str) -> list[float]:
        result = await self._embed([query], input_type="search_query")
        return result[0]

    # ── 내부 ────────────────────────────────────────────────────────────
    async def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        if self.mock:
            return [_hash_vector(f"{input_type}::{t}") for t in texts]

        if self.provider == "local":
            return await self._embed_local(texts)

        # 캐시 조회
        keys = [self._cache_key(t, input_type) for t in texts] if self._cache else []
        cached_map: dict[str, list[float]] = {}
        missing: list[str] = []
        if self._cache:
            cached = self._cache.mget(keys)
            for text, raw in zip(texts, cached):
                if raw is None:
                    missing.append(text)
                else:
                    import json
                    cached_map[text] = json.loads(raw)
        else:
            missing = list(texts)

        if missing:
            res = self._client.embed(
                texts=missing,
                model=self.model,
                input_type=input_type,
            )
            for text, vec in zip(missing, res.embeddings):
                cached_map[text] = vec
                if self._cache:
                    import json
                    self._cache.set(self._cache_key(text, input_type), json.dumps(vec))

        return [cached_map[t] for t in texts]

    async def _embed_local(self, texts: list[str]) -> list[list[float]]:
        """OpenAI 호환 임베딩 서버(LM Studio bge-m3). 문서/쿼리 동일 경로(비대칭 없음)."""
        import httpx

        headers = {}
        token = os.getenv("LMSTUDIO_API_KEY")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{self.base_url}/embeddings",
                json={"model": self.model, "input": texts},
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()["data"]

        data.sort(key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in data]

    @staticmethod
    def _cache_key(text: str, input_type: str) -> str:
        h = hashlib.sha256(f"{input_type}::{text}".encode("utf-8")).hexdigest()
        return f"embed:{h}"
