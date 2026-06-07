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
    base = os.getenv("FRIDGEMATE_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    endpoint = f"{base}/chat/completions"

    def request(current_payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            endpoint,  # OpenRouter, LM Studio 등 OpenAI 호환 엔드포인트 지원
            data=json.dumps(current_payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM HTTP {exc.code}: {body}") from exc

    try:
        raw = request(payload)
    except RuntimeError as exc:
        # LM Studio 일부 버전은 json_object 대신 text/json_schema만 허용한다.
        if "response_format.type" not in str(exc):
            raise
        payload["response_format"] = {"type": "text"}
        payload["messages"][-1]["content"] += "\n반드시 JSON object만 출력하세요."
        raw = request(payload)

    content = raw["choices"][0]["message"]["content"]
    return _parse_json_object(content)


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])

    if not isinstance(parsed, dict):
        raise ValueError("LLM response must be a JSON object")
    return parsed


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
