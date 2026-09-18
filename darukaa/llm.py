"""Thin OpenAI-compatible client (Groq or Gemini free tiers). Every caller has a
deterministic fallback, so the system still works when no key is configured."""

import json
import logging
import re
from functools import lru_cache

from darukaa import config

log = logging.getLogger("darukaa.llm")


def available() -> bool:
    return bool(config.LLM_API_KEY and config.LLM_BASE_URL)


@lru_cache(maxsize=1)
def _client():
    from openai import OpenAI

    # Few retries: on a rate limit we switch to the fallback model instead of waiting ~30 s.
    return OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL, timeout=40, max_retries=0)


def _complete(model: str, system: str, user: str, temperature: float, max_tokens: int) -> str | None:
    extra = {}
    if "gpt-oss" in model:
        # reasoning model: keep hidden reasoning short and leave room for the answer
        extra = {"reasoning_effort": "low"}
        max_tokens += 700
    resp = _client().chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
        max_tokens=max_tokens,
        **extra,
    )
    return resp.choices[0].message.content


def chat(system: str, user: str, temperature: float = 0.2, max_tokens: int = 900) -> str | None:
    if not available():
        return None
    models = [config.LLM_MODEL] + ([config.LLM_FALLBACK_MODEL] if config.LLM_FALLBACK_MODEL else [])
    for model in models:
        try:
            return _complete(model, system, user, temperature, max_tokens)
        except Exception as exc:
            log.warning("LLM call failed on %s: %s", model, str(exc)[:200])
    return None


def chat_json(system: str, user: str, max_tokens: int = 900):
    text = chat(system + "\nRespond with a single valid JSON object and nothing else.", user, temperature=0.0, max_tokens=max_tokens)
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        log.warning("LLM returned no JSON object (%d chars)", len(text))
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        log.warning("LLM returned invalid JSON: %s", exc)
        return None
