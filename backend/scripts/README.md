# backend/scripts — RAG 평가/인스펙션 하네스

원본 fridge-mate `scripts/` 에서 머지 레포(`app.rag.*`)에 맞게 적응 이식.
실험보고서(`docs/rag-experiment-report.md`) 수치를 재현/검증하는 도구.

전제: 전용 venv(`backend/.venv`) + `.env`(EMBED_PROVIDER=local, LMSTUDIO_*, FRIDGEMATE_USE_LLM=true).
모두 **backend 디렉토리에서** 실행 (스크립트가 `parents[1]`=backend 를 sys.path 에 추가).

| 스크립트 | 용도 | 비고 |
|---|---|---|
| `rag_eval.py` | P@1/P@3/MRR (plain vs smart), 16쿼리 오타/묘사/구어 | recipe_db 읽기만(wipe 없음). SMART 는 LLM이라 run마다 변동 |
| `rag_inspect.py` | 같은 쿼리를 Basic/HyDE/Fusion 강제 → dist/rrf/출처/차이 비교 | 전략 켜고끄고 비교용 |
| `rag_ablation.py` | embed_text V1(현행) vs V2(lean) plain 비교 | 임시 컬렉션 재임베딩(수분), recipe_db 무영향 |

```powershell
cd D:\Research\agents\fridgeMate-Merge\backend
.venv\Scripts\python.exe scripts\rag_eval.py
.venv\Scripts\python.exe scripts\rag_inspect.py "고단백 한식 다이어트 점심"
.venv\Scripts\python.exe scripts\rag_ablation.py
```

## 실측 (2026-06-06, recipe_db 1693 / bge-m3-1024)
- PLAIN: P@1 50% / P@3 69% / MRR 0.594 — **결정적(재현 동일)**
- SMART: run별 변동 (LLM 비결정) — Sonnet 75/88/.802, OpenRouter 50/81/.646, LM Studio qwen2.5-7b 62/81/.698
- 일관 결론: SMART 가 묘사·구어 P@3/MRR 을 끌어올림. P@1 향상폭은 run 의존 → 정밀비교는 온도0·다회평균 필요.
