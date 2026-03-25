"""Tavily search client (async) — simple HTTP wrapper.

Unlike the LangGraph @tool in utils.py, this function is a plain async helper
suitable for direct calls inside endpoint/researcher functions.

Environment variable required
------------------------------
TAVILY_API_KEY
"""

import os
import httpx
from typing import Any, Dict, List, Optional

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


async def tavily_search(
    query: str,
    max_results: int = 5,
    search_depth: str = "basic",
    include_answer: bool = True,
    include_raw_content: bool = False,
    timeout_s: float = 15.0,
) -> Dict[str, Any]:
    """Perform a Tavily web search and return structured results.

    Parameters
    ----------
    query:               Search query string.
    max_results:         Maximum number of results to return.
    search_depth:        "basic" or "advanced".
    include_answer:      Whether to include a generated answer.
    include_raw_content: Whether to include raw page content.
    timeout_s:           HTTP request timeout in seconds.

    Returns
    -------
    dict with keys:
        ok:      bool   — True on success
        results: list   — list of result dicts (url, title, content, score)
        answer:  str    — AI-generated answer (empty string if not requested)
        error:   str    — error message on failure (empty string on success)
    """
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return {
            "ok": False,
            "results": [],
            "answer": "",
            "error": "TAVILY_API_KEY is not set.",
        }

    payload: Dict[str, Any] = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": search_depth,
        "include_answer": include_answer,
        "include_raw_content": include_raw_content,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(
                TAVILY_SEARCH_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()

        return {
            "ok": True,
            "results": data.get("results", []),
            "answer": data.get("answer", ""),
            "error": "",
        }

    except httpx.TimeoutException:
        return {"ok": False, "results": [], "answer": "", "error": "Request timed out"}
    except httpx.HTTPStatusError as exc:
        return {"ok": False, "results": [], "answer": "", "error": f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"}
    except Exception as exc:
        return {"ok": False, "results": [], "answer": "", "error": str(exc)}
