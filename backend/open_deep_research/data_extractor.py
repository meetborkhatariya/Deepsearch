"""Extract structured lab parameters from medical report files (PDF or image).

Supports:
  - application/pdf  → text extracted via PyMuPDF, then parsed by GPT-4o-mini
  - image/jpeg, image/png, image/webp → sent directly to GPT-4o vision

Returns
-------
dict
    On success::

        {
            "parameters": [
                {
                    "name": "Hemoglobin",
                    "value": "11.2",
                    "unit": "g/dL",
                    "normal_range": "13.0 - 17.0",
                    "status": "LOW"
                },
                ...
            ],
            "report_date": "2025-01-15",   # best-effort, empty string if not found
            "patient_name": "...",          # best-effort, empty string if not found
            "raw_text": "..."               # only present for PDF extractions
        }

    On failure::

        {"error": "human-readable reason"}
"""

import base64
import json
import os
from typing import Any, Dict

import fitz  # PyMuPDF

_EXTRACTION_PROMPT = """You are a medical lab report parser.
Extract ALL lab test results from the text below and return ONLY a valid JSON object.

Required JSON structure:
{
  "parameters": [
    {
      "name": "<test name>",
      "value": "<numeric or text value>",
      "unit": "<unit or empty string>",
      "normal_range": "<reference range or empty string>",
      "status": "<HIGH | LOW | NORMAL | UNKNOWN>"
    }
  ],
  "report_date": "<YYYY-MM-DD or empty string>",
  "patient_name": "<name or empty string>"
}

Rules:
- Include every single test result found.
- Do NOT add commentary, markdown, or code fences — raw JSON only.
- If a field cannot be determined, use an empty string.
- For status: compare value to normal_range if available, otherwise use UNKNOWN.

Lab report text:
"""

_VISION_PROMPT = """You are a medical lab report parser.
Look at this lab report image and extract ALL test results.
Return ONLY a valid JSON object with this exact structure:
{
  "parameters": [
    {
      "name": "<test name>",
      "value": "<numeric or text value>",
      "unit": "<unit or empty string>",
      "normal_range": "<reference range or empty string>",
      "status": "<HIGH | LOW | NORMAL | UNKNOWN>"
    }
  ],
  "report_date": "<YYYY-MM-DD or empty string>",
  "patient_name": "<name or empty string>"
}

Rules:
- Include every single test result visible.
- Do NOT add commentary, markdown, or code fences — raw JSON only.
- For status: compare value to normal_range if available, otherwise use UNKNOWN.
"""


def _get_openai():
    """Lazy import to avoid crash when OPENAI_API_KEY is not yet loaded."""
    from openai import AsyncOpenAI
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to your .env file."
        )
    return AsyncOpenAI(api_key=api_key)


def _parse_llm_json(raw: str) -> Dict[str, Any]:
    """Strip markdown fences and parse JSON from LLM output."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop opening fence line and closing fence line
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    return json.loads(text)


async def _extract_from_pdf(file_content: bytes) -> Dict[str, Any]:
    """Extract lab parameters from a PDF using PyMuPDF + GPT-4o-mini."""
    try:
        doc = fitz.open(stream=file_content, filetype="pdf")
        pages_text = []
        for page in doc:
            pages_text.append(page.get_text())
        doc.close()
        full_text = "\n".join(pages_text).strip()
    except Exception as exc:
        return {"error": f"PDF parsing failed: {exc}"}

    if not full_text:
        return {"error": "PDF contains no extractable text (may be a scanned image PDF). Try uploading as an image instead."}

    # Truncate to avoid token limits (~60k chars ≈ ~15k tokens)
    truncated = full_text[:60_000]

    oai = _get_openai()
    try:
        response = await oai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": _EXTRACTION_PROMPT + truncated,
                }
            ],
            temperature=0,
            max_tokens=4096,
        )
        raw_json = response.choices[0].message.content or ""
        result = _parse_llm_json(raw_json)
        result["raw_text"] = full_text[:5000]  # store first 5k chars for debugging
        return result
    except json.JSONDecodeError as exc:
        return {"error": f"LLM returned invalid JSON: {exc}"}
    except Exception as exc:
        return {"error": f"OpenAI call failed: {exc}"}


async def _extract_from_image(file_content: bytes, content_type: str) -> Dict[str, Any]:
    """Extract lab parameters from an image using GPT-4o vision."""
    b64 = base64.b64encode(file_content).decode("utf-8")
    data_url = f"data:{content_type};base64,{b64}"

    oai = _get_openai()
    try:
        response = await oai.chat.completions.create(
            model="gpt-4o",  # vision-capable model
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _VISION_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
                    ],
                }
            ],
            temperature=0,
            max_tokens=4096,
        )
        raw_json = response.choices[0].message.content or ""
        return _parse_llm_json(raw_json)
    except json.JSONDecodeError as exc:
        return {"error": f"LLM returned invalid JSON: {exc}"}
    except Exception as exc:
        return {"error": f"OpenAI vision call failed: {exc}"}


async def extract_data(file_content: bytes, content_type: str) -> Dict[str, Any]:
    """Dispatch to the appropriate extractor based on *content_type*.

    Parameters
    ----------
    file_content:
        Raw bytes of the uploaded file.
    content_type:
        MIME type string, e.g. ``"application/pdf"``, ``"image/jpeg"``.

    Returns
    -------
    dict
        Structured extraction result or ``{"error": "..."}`` on failure.
    """
    if not file_content:
        return {"error": "Empty file content received."}

    ct = (content_type or "").lower().split(";")[0].strip()

    if ct == "application/pdf":
        return await _extract_from_pdf(file_content)

    if ct in ("image/jpeg", "image/jpg", "image/png", "image/webp"):
        return await _extract_from_image(file_content, ct)

    return {"error": f"Unsupported content type: {content_type}. Supported: application/pdf, image/jpeg, image/png, image/webp"}
