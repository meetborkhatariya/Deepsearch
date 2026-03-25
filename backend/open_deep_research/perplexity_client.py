"""Perplexity AI chat client (async).

Wraps the Perplexity /chat/completions API using httpx.

Environment variable required
------------------------------
PERPLEXITY_API_KEY
"""

import os
import httpx
from typing import Any, Dict, List, Optional

PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"


async def call_perplexity_chat(
    messages: List[Dict[str, str]],
    model: str = "sonar",
    max_tokens: int = 1500,
    temperature: float = 0.7,
    timeout_s: float = 30.0,
) -> str:
    """Call Perplexity chat completions and return the assistant message text.

    Parameters
    ----------
    messages:    List of {"role": ..., "content": ...} dicts.
    model:       Perplexity model name (e.g. "sonar", "sonar-pro").
    max_tokens:  Max completion tokens.
    temperature: Sampling temperature.
    timeout_s:   HTTP request timeout in seconds.

    Returns
    -------
    str — the assistant reply text.

    Raises
    ------
    RuntimeError  if PERPLEXITY_API_KEY is not set.
    httpx.HTTPStatusError  on non-2xx responses.
    """
    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        raise RuntimeError(
            "PERPLEXITY_API_KEY is not set. Add it to your .env file."
        )

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.post(
            PERPLEXITY_API_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        data = response.json()

    return data["choices"][0]["message"]["content"]
