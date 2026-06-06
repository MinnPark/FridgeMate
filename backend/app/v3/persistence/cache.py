"""Redis 세션/캐시 어댑터 (기획안: Redis = Session / Cache).

- REDIS_URL 있으면 Redis, 없으면 in-process dict 폴백 (개발 무중단).
- 키는 FRIDGEMATE_REDIS_PREFIX 로 네임스페이스 → 공용 Redis(타 프로젝트 valkey) 충돌 방지.
- 용도: ① LLM/임베딩 응답 캐시 ② 세션 대화상태(B패턴 드로어, 활성 thread 포인터).

docs/data_architecture.md §1, §3.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Optional

_PREFIX = os.getenv("FRIDGEMATE_REDIS_PREFIX", "fridgemate")


class _MemoryBackend:
    """Redis 없을 때 폴백 — TTL 흉내내는 in-process store."""

    def __init__(self) -> None:
        self._d: dict[str, tuple[str, float]] = {}

    def get(self, key: str) -> Optional[str]:
        v = self._d.get(key)
        if not v:
            return None
        val, exp = v
        if exp and exp < time.time():
            self._d.pop(key, None)
            return None
        return val

    def set(self, key: str, val: str, ex: Optional[int] = None) -> None:
        self._d[key] = (val, time.time() + ex if ex else 0.0)

    def delete(self, key: str) -> None:
        self._d.pop(key, None)


class SessionCache:
    """세션/캐시 통합 진입점. backend = Redis | in-memory."""

    def __init__(self) -> None:
        self.backend_kind = "memory"
        self._b: Any = _MemoryBackend()
        url = os.getenv("REDIS_URL")
        if url:
            try:
                import redis
                client = redis.Redis.from_url(url, decode_responses=True)
                client.ping()
                self._b = client
                self.backend_kind = "redis"
            except Exception:
                pass  # 폴백 유지

    def _k(self, *parts: str) -> str:
        return ":".join([_PREFIX, *parts])

    # ── 범용 캐시 ──────────────────────────────────────────
    def cache_get(self, namespace: str, key: str) -> Optional[Any]:
        raw = self._b.get(self._k(namespace, key))
        return json.loads(raw) if raw else None

    def cache_set(self, namespace: str, key: str, value: Any, ttl: int = 3600) -> None:
        self._b.set(self._k(namespace, key), json.dumps(value, ensure_ascii=False), ex=ttl)

    # ── 세션 상태 (대화/활성 thread) ──────────────────────
    def session_get(self, user_id: str) -> dict:
        raw = self._b.get(self._k("session", user_id))
        return json.loads(raw) if raw else {}

    def session_set(self, user_id: str, state: dict, ttl: int = 86400) -> None:
        self._b.set(self._k("session", user_id), json.dumps(state, ensure_ascii=False), ex=ttl)

    def session_set_active_thread(self, user_id: str, thread_id: str) -> None:
        st = self.session_get(user_id)
        st["active_thread_id"] = thread_id
        st["updated_at"] = time.time()
        self.session_set(user_id, st)


_singleton: Optional[SessionCache] = None


def get_cache() -> SessionCache:
    global _singleton
    if _singleton is None:
        _singleton = SessionCache()
    return _singleton
