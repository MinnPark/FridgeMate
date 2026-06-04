import json
import os
import urllib.error
import urllib.request
from typing import Any


class LLMResult(dict):
    @property
    def used_llm(self) -> bool:
        return bool(self.get("used_llm"))


def generate_json(
    *,
    system_prompt: str,
    user_prompt: str,
    fallback: dict[str, Any],
    temperature: float = 0.2,
) -> LLMResult:
    """Return structured JSON from an LLM, falling back to deterministic data.

    The project can run without API keys for demos. To connect a real model, set
    either OpenAI-compatible variables:
    - FRIDGEMATE_LLM_PROVIDER=openai
    - OPENAI_API_KEY=...
    - FRIDGEMATE_LLM_MODEL=gpt-4o-mini or another JSON-capable model

    or Anthropic variables:
    - FRIDGEMATE_LLM_PROVIDER=anthropic
    - ANTHROPIC_API_KEY=...
    - FRIDGEMATE_LLM_MODEL=claude-3-5-sonnet-latest
    """
    provider = os.getenv("FRIDGEMATE_LLM_PROVIDER", "mock").lower()
    if provider == "openai" and os.getenv("OPENAI_API_KEY"):
        try:
            data = _call_openai_json(system_prompt, user_prompt, temperature)
            data["_meta"] = {"used_llm": True, "provider": "openai"}
            return LLMResult(data)
        except Exception as exc:
            fallback = {
                **fallback,
                "_meta": {
                    "used_llm": False,
                    "provider": "fallback",
                    "error": str(exc),
                },
            }
            return LLMResult(fallback)

    if provider == "anthropic" and os.getenv("ANTHROPIC_API_KEY"):
        try:
            data = _call_anthropic_json(system_prompt, user_prompt, temperature)
            data["_meta"] = {"used_llm": True, "provider": "anthropic"}
            return LLMResult(data)
        except Exception as exc:
            fallback = {
                **fallback,
                "_meta": {
                    "used_llm": False,
                    "provider": "fallback",
                    "error": str(exc),
                },
            }
            return LLMResult(fallback)

    fallback = {
        **fallback,
        "_meta": {"used_llm": False, "provider": "deterministic-fallback"},
    }
    return LLMResult(fallback)


def _call_openai_json(
    system_prompt: str,
    user_prompt: str,
    temperature: float,
) -> dict[str, Any]:
    api_key = os.environ["OPENAI_API_KEY"]
    model = os.getenv("FRIDGEMATE_LLM_MODEL", "gpt-4o-mini")
    payload = {
        "model": model,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            raw = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM HTTP {exc.code}: {body}") from exc

    content = raw["choices"][0]["message"]["content"]
    return json.loads(content)


def _call_anthropic_json(
    system_prompt: str,
    user_prompt: str,
    temperature: float,
) -> dict[str, Any]:
    api_key = os.environ["ANTHROPIC_API_KEY"]
    model = os.getenv("FRIDGEMATE_LLM_MODEL", "claude-3-5-sonnet-latest")
    payload = {
        "model": model,
        "max_tokens": 1200,
        "temperature": temperature,
        "system": system_prompt,
        "messages": [
            {
                "role": "user",
                "content": user_prompt + "\n\n반드시 JSON object만 출력하세요.",
            }
        ],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            raw = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Anthropic HTTP {exc.code}: {body}") from exc

    text = "".join(
        block.get("text", "")
        for block in raw.get("content", [])
        if block.get("type") == "text"
    )
    return json.loads(text)
