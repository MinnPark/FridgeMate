"""LLM 호출 추상화 — provider-agnostic (anthropic | openrouter | local).

설계 원칙:
- LLM_PROVIDER env 가 전역 디폴트 (anthropic). 호출 시 provider 인자로 노드별 override 가능.
- 각 provider 의 SDK 는 지연 import — 미설치/미사용 provider 가 import 실패해도 다른 provider 동작.
- prompt caching: anthropic 만 정식 지원. OpenRouter 는 일부 모델만 — best-effort 적용.
- 키/엔드포인트 없거나 FRIDGEMATE_USE_LLM != "true" 면 fallback 즉시 반환 (offline OK).

Env:
  LLM_PROVIDER          anthropic | openrouter | local (default: anthropic)
  ANTHROPIC_API_KEY     anthropic 모드
  OPENROUTER_API_KEY    openrouter 모드
  OPENROUTER_BASE_URL   기본 https://openrouter.ai/api/v1
  LLM_LOCAL_BASE_URL       기본 http://127.0.0.1:11434/v1 (OpenAI 호환 엔드포인트)

모델 ID 선택 우선순위 (호출 시 model 인자 > 환경변수 model_env > provider 디폴트):
  anthropic    : ANTHROPIC_MODEL_DEFAULT (claude-sonnet-4-6) / ANTHROPIC_MODEL_JUDGE (claude-opus-4-7)
  openrouter   : OPENROUTER_MODEL_DEFAULT  (예: anthropic/claude-sonnet-4-6)
                 OPENROUTER_MODEL_JUDGE    (예: anthropic/claude-opus-4-7)
  local : LOCAL_MODEL_DEFAULT (qwen2.5:7b) / LOCAL_MODEL_JUDGE (qwen2.5:14b)
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[0] / "prompts"

PROVIDER_DEFAULT_MODELS: dict[str, dict[str, str]] = {
    "anthropic": {
        "ANTHROPIC_MODEL_DEFAULT": "claude-sonnet-4-6",
        "ANTHROPIC_MODEL_JUDGE": "claude-opus-4-7",
    },
    "openrouter": {
        "ANTHROPIC_MODEL_DEFAULT": "anthropic/claude-sonnet-4-6",
        "ANTHROPIC_MODEL_JUDGE": "anthropic/claude-opus-4-7",
        "OPENROUTER_MODEL_DEFAULT": "anthropic/claude-sonnet-4-6",
        "OPENROUTER_MODEL_JUDGE": "anthropic/claude-opus-4-7",
    },
    "local": {
        "ANTHROPIC_MODEL_DEFAULT": "qwen2.5:7b",
        "ANTHROPIC_MODEL_JUDGE": "qwen2.5:14b",
        "LOCAL_MODEL_DEFAULT": "qwen2.5:7b",
        "LOCAL_MODEL_JUDGE": "qwen2.5:14b",
    },
}


def current_provider() -> str:
    return os.getenv("LLM_PROVIDER", "anthropic").lower()


def llm_enabled(provider: str | None = None) -> bool:
    if os.getenv("FRIDGEMATE_USE_LLM", "false").lower() != "true":
        return False
    p = (provider or current_provider()).lower()
    if p == "anthropic":
        return bool(os.getenv("ANTHROPIC_API_KEY"))
    if p == "openrouter":
        return bool(os.getenv("OPENROUTER_API_KEY"))
    if p == "local":
        return True   # 로컬은 key 불필요 — local 가 떠있다고 가정 (호출 시 실패 시 fallback)
    return False


@lru_cache(maxsize=8)
def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"prompt not found: {path}")
    return path.read_text(encoding="utf-8")


def _resolve_model(provider: str, model_env: str) -> str:
    """provider 마다 자기 모델 env 를 본다 (교차 오염 방지).

    openrouter → OPENROUTER_MODEL_* / local → LOCAL_MODEL_* / anthropic → ANTHROPIC_MODEL_*.
    anthropic 직접용 ID(claude-sonnet-4-6)가 openrouter("anthropic/..." 필요)로 새지 않게 한다.
    """
    if provider == "openrouter":
        own = model_env.replace("ANTHROPIC_MODEL", "OPENROUTER_MODEL")
    elif provider == "local":
        own = model_env.replace("ANTHROPIC_MODEL", "LOCAL_MODEL")
    else:
        own = model_env
    return os.getenv(own) or PROVIDER_DEFAULT_MODELS.get(provider, {}).get(model_env, "")


async def _call_anthropic(*, system_text: str, user_content: str, model: str, max_tokens: int) -> str:
    import anthropic
    client = anthropic.AsyncAnthropic()
    response = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{
            "type": "text",
            "text": system_text,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_content}],
    )
    parts = [b.text for b in response.content if getattr(b, "type", "") == "text"]
    return "".join(parts).strip()


async def _call_openai_compat(
    *,
    base_url: str,
    api_key: str,
    system_text: str,
    user_content: str,
    model: str,
    max_tokens: int,
    cache_hint: bool = False,
) -> str:
    """OpenAI 호환 엔드포인트 (OpenRouter, local, vLLM, llama.cpp).

    cache_hint=True 이고 anthropic 모델이면 system content 블록 안에 cache_control 인라인
    (Anthropic native 형식 — OpenRouter 가 그대로 패스스루). 그 외엔 일반 string content.
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(base_url=base_url, api_key=api_key or "local")

    if cache_hint:
        system_msg = {
            "role": "system",
            "content": [
                {"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}},
            ],
        }
    else:
        system_msg = {"role": "system", "content": system_text}

    response = await client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[system_msg, {"role": "user", "content": user_content}],
    )
    return (response.choices[0].message.content or "").strip()


async def call_llm(
    *,
    system_prompt_name: str,
    user_content: str,
    model_env: str = "ANTHROPIC_MODEL_DEFAULT",
    provider: str | None = None,
    fallback: str = "",
    max_tokens: int = 512,
) -> str:
    """단발 호출. provider 미지정 시 LLM_PROVIDER env 사용. 비활성/실패 시 fallback."""
    p = (provider or current_provider()).lower()
    if not llm_enabled(p):
        return fallback

    system_text = load_prompt(system_prompt_name)
    model = _resolve_model(p, model_env)
    if not model:
        return fallback

    try:
        if p == "anthropic":
            out = await _call_anthropic(
                system_text=system_text,
                user_content=user_content,
                model=model,
                max_tokens=max_tokens,
            )
        elif p == "openrouter":
            out = await _call_openai_compat(
                base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
                api_key=os.environ["OPENROUTER_API_KEY"],
                system_text=system_text,
                user_content=user_content,
                model=model,
                max_tokens=max_tokens,
                cache_hint=model.startswith("anthropic/"),
            )
        elif p == "local":
            out = await _call_openai_compat(
                base_url=os.getenv("LLM_LOCAL_BASE_URL", "http://127.0.0.1:11434/v1"),
                api_key="local",
                system_text=system_text,
                user_content=user_content,
                model=model,
                max_tokens=max_tokens,
            )
        else:
            return fallback
    except Exception as exc:  # noqa: BLE001 — 모든 provider 오류는 fallback 으로
        print(f"[llm] provider={p} model={model} failed: {exc}")
        return fallback

    return out or fallback
