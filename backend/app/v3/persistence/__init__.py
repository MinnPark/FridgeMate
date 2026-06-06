"""영속 레이어 — 사용자 이력(history) · 세션/캐시(Redis) · 개인화 연계.

docs/data_architecture.md 정본 구현.
- history_store: 사용자 이력 (dev SQLite / prod Postgres). 개인화의 원천.
- cache: Redis 세션/캐시 어댑터 (namespaced, 옵션, 폴백).
"""
