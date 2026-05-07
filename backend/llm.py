import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
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
