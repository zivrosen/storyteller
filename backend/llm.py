import os
import threading

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# Hard cap per LLM call. The SDK's default is 10 minutes, which would let a
# stuck call hold an SSE connection (and a worker thread) indefinitely. 45s
# comfortably covers the storyteller stage on gpt-3.5-turbo. The SDK retries
# transient failures up to max_retries times within this budget.
_REQUEST_TIMEOUT_SECONDS = 45.0

_client: OpenAI | None = None
_client_lock = threading.Lock()


def _get_client() -> OpenAI:
    """Lazy, thread-safe singleton. Double-checked locking avoids the rare
    race where two threads both see `_client is None` on first hit."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = OpenAI(
                    api_key=os.getenv("OPENAI_API_KEY"),
                    timeout=_REQUEST_TIMEOUT_SECONDS,
                )
    return _client


def call_model(
    prompt: str,
    max_tokens: int = 1800,
    temperature: float = 0.7,
    json_mode: bool = False,
    system: str | None = None,
) -> str:
    """Call gpt-3.5-turbo. Model is fixed per assignment requirement.

    json_mode=True forces a JSON-only response, used by categorizer/planner/judge.
    """
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict = {
        "model": "gpt-3.5-turbo",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    resp = _get_client().chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""
