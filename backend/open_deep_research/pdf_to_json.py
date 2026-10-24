"""Extract text from digitized PDFs using pdfplumber and convert to LabParameterSchema JSON.

This module takes a PDF file (digitized/scanned with selectable text), extracts
all text via pdfplumber, and uses GPT-4o-mini to produce a JSON payload identical
to the ``LabParameterSchema`` structure consumed by the ``/api/v1/lab_parameters``
endpoint.

Usage
-----
    from .pdf_to_json import extract_lab_json_from_pdf

    result = await extract_lab_json_from_pdf(pdf_bytes, user_id="abc123")
    # result is a dict matching LabParameterSchema exactly
"""

import json
import os
import re
import uuid
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional

import pdfplumber
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# OpenAI client (lazy)
# ---------------------------------------------------------------------------

def _get_openai():
    """Create Groq-compatible OpenAI client (Groq key only)."""
    from openai import AsyncOpenAI

    groq_key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not groq_key:
        raise RuntimeError("GROQ_API_KEY is not set. Add it to your .env file.")
    return AsyncOpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")


# ---------------------------------------------------------------------------
# Prompt — instructs the LLM to return the EXACT schema
# ---------------------------------------------------------------------------

_PDF_TO_LAB_JSON_PROMPT = r"""You are a medical lab report parser.

You will receive raw text extracted from a medical/lab report PDF.
Your task is to extract ALL lab test results and patient metadata, then return
a single valid JSON object that matches the **exact structure** described below.

### REQUIRED JSON STRUCTURE ###

{
  "user_id": "<leave as empty string — will be filled by caller>",
  "parameterName": "<name of the MOST CLINICALLY IMPORTANT abnormal parameter, or the first parameter if all normal>",
  "currentValue": "<value of that primary parameter as a string>",
  "reportDate": "<YYYY-MM-DD  extracted from the report, or empty string>",
  "reportId": "",
  "previousValues": [],
  "linkedParameters": {
    "<parameter_key_1>": {
      "name": "<test name>",
      "normalRange": "<low - high   e.g. '13.0 - 17.0', or empty string>",
      "currentValues": [
        {
          "value": "<numeric or text value as string>",
          "date": "<YYYY-MM-DD same as reportDate>",
          "unit": "<unit string or empty string>"
        }
      ],
      "previousValues": []
    },
    "<parameter_key_2>": { ... }
  },
  "age": null,
  "gender": null,
  "chronicCondition": [],
  "bmi": null,
  "steps": {},
  "language": "english",
  "model": "openai"
}

### RULES ###

1. **parameterName** must be the single most important / most abnormal parameter.
   Its value goes into **currentValue**.
   ALL remaining parameters (including the primary one) go into **linkedParameters**.
2. Every parameter key in linkedParameters should be a lowercase snake_case version
   of the test name  (e.g. "hemoglobin", "total_cholesterol", "blood_urea_nitrogen").
3. If the report contains patient age, gender, or BMI, populate those fields.
   Otherwise leave them as null.
4. **reportDate** must be in YYYY-MM-DD format. Pick the collection/report date
   visible in the report. If multiple dates exist, use the most prominent one.
5. **previousValues** at both the top level and inside each linkedParameter must
   be empty arrays — we never invent historical data.
6. **Do NOT add commentary, markdown, or code fences — return raw JSON only.**
7. Include EVERY SINGLE test result found in the text, no matter how many.
8. For normalRange, use the reference range exactly as shown in the report.
   Format as "low - high" (space-dash-space). If not available, use empty string.

### LAB REPORT TEXT ###
"""


# ---------------------------------------------------------------------------
# PDF text extraction via pdfplumber
# ---------------------------------------------------------------------------

def extract_text_from_pdf(file_content: bytes) -> str:
    """Extract all text from a PDF using pdfplumber.

    Parameters
    ----------
    file_content : bytes
        Raw PDF bytes.

    Returns
    -------
    str
        Concatenated text from all pages.

    Raises
    ------
    ValueError
        If the PDF yields no extractable text.
    """
    try:
        with pdfplumber.open(BytesIO(file_content)) as pdf:
            pages_text: List[str] = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages_text.append(text)

                # Also try to extract tables and convert to text
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if row:
                            row_text = " | ".join(
                                str(cell).strip() if cell else "" for cell in row
                            )
                            pages_text.append(row_text)

        full_text = "\n".join(pages_text).strip()
    except Exception as exc:
        raise ValueError(f"PDF parsing failed: {exc}") from exc

    if not full_text:
        raise ValueError(
            "PDF contains no extractable text. It may be a scanned image PDF — "
            "try uploading as an image instead."
        )
    return full_text


# ---------------------------------------------------------------------------
# LLM-based JSON conversion
# ---------------------------------------------------------------------------

def _parse_llm_json(raw: str) -> Dict[str, Any]:
    """Strip markdown fences and parse JSON from LLM output."""
    text = raw.strip()
    # Remove markdown code fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    return json.loads(text)


async def _text_to_lab_json(full_text: str) -> Dict[str, Any]:
    """Send extracted PDF text to GPT-4o-mini and get LabParameterSchema JSON.

    Parameters
    ----------
    full_text : str
        Raw text extracted from the PDF.

    Returns
    -------
    dict
        Parsed JSON matching LabParameterSchema structure.
    """
    # Truncate to stay within token limits (~60 000 chars ≈ ~15 000 tokens)
    truncated = full_text[:60_000]

    oai = _get_openai()
    response = await oai.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {
                "role": "user",
                "content": _PDF_TO_LAB_JSON_PROMPT + truncated,
            }
        ],
        temperature=0,
        max_tokens=8192,
    )
    raw_json = response.choices[0].message.content or ""
    return _parse_llm_json(raw_json)


# ---------------------------------------------------------------------------
# Post-processing — ensure schema compliance
# ---------------------------------------------------------------------------

def _normalise_result(raw: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """Ensure every required key exists and conforms to LabParameterSchema.

    Adds missing fields with safe defaults so the result can be passed directly
    to ``/api/v1/lab_parameters`` without modification.
    """
    # --- Top-level scalars ---------------------------------------------------
    result: Dict[str, Any] = {
        "user_id": user_id,
        "parameterName": raw.get("parameterName", ""),
        "currentValue": str(raw.get("currentValue", "")),
        "reportDate": raw.get("reportDate", ""),
        "reportId": raw.get("reportId", ""),
        "previousValues": raw.get("previousValues") or [],
        "age": raw.get("age"),
        "gender": raw.get("gender"),
        "chronicCondition": raw.get("chronicCondition") or [],
        "bmi": raw.get("bmi"),
        "steps": raw.get("steps") or {},
        "language": raw.get("language", "english"),
        "model": raw.get("model", "openai"),
    }

    # --- Normalise reportDate to YYYY-MM-DD -----------------------------------
    rd = result["reportDate"]
    if rd:
        # Try common formats
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y"):
            try:
                result["reportDate"] = datetime.strptime(rd, fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                continue

    report_date = result["reportDate"] or datetime.now().strftime("%Y-%m-%d")

    # --- linkedParameters -----------------------------------------------------
    linked_raw = raw.get("linkedParameters", {})
    linked_clean: Dict[str, Any] = {}

    for key, val in linked_raw.items():
        if not isinstance(val, dict):
            continue
        name = val.get("name", key)
        normal_range = val.get("normalRange", "")

        # Build currentValues list
        current_values_raw = val.get("currentValues", [])
        if not isinstance(current_values_raw, list) or len(current_values_raw) == 0:
            # Fallback: build from value/unit if present
            cv_value = str(val.get("value", ""))
            cv_unit = val.get("unit", "")
            current_values_raw = [{"value": cv_value, "date": report_date, "unit": cv_unit}]

        current_values = []
        for cv in current_values_raw:
            current_values.append({
                "value": str(cv.get("value", "")),
                "date": cv.get("date", report_date),
                "unit": cv.get("unit", ""),
            })

        linked_clean[key] = {
            "name": name,
            "normalRange": normal_range,
            "currentValues": current_values,
            "previousValues": val.get("previousValues") or [],
        }

    result["linkedParameters"] = linked_clean

    # --- Ensure primary parameter is also in linkedParameters ------------------
    pname = result["parameterName"]
    if pname:
        pkey = re.sub(r"[^a-z0-9]+", "_", pname.lower()).strip("_")
        if pkey not in linked_clean:
            linked_clean[pkey] = {
                "name": pname,
                "normalRange": "",
                "currentValues": [
                    {
                        "value": result["currentValue"],
                        "date": report_date,
                        "unit": "",
                    }
                ],
                "previousValues": [],
            }

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def extract_lab_json_from_pdf(
    file_content: bytes,
    user_id: str = "",
) -> Dict[str, Any]:
    """End-to-end: PDF bytes → LabParameterSchema-compatible JSON dict.

    Parameters
    ----------
    file_content : bytes
        Raw PDF file bytes.
    user_id : str, optional
        User identifier to embed in the resulting JSON. If empty, caller
        should fill it in before posting to ``/api/v1/lab_parameters``.

    Returns
    -------
    dict
        A dictionary that conforms to ``LabParameterSchema`` and can be
        posted directly to ``/api/v1/lab_parameters``.

    Raises
    ------
    ValueError
        If the PDF has no text or parsing fails.
    RuntimeError
        If the OpenAI call fails.
    """
    # Step 1: Extract text from PDF via pdfplumber
    print(f"[PDF→JSON] Extracting text with pdfplumber …")
    full_text = extract_text_from_pdf(file_content)
    print(f"[PDF→JSON] Extracted {len(full_text)} characters from PDF")

    # Step 2: Convert text to structured JSON via LLM
    print(f"[PDF→JSON] Sending text to GPT-4o-mini for structuring …")
    try:
        raw_result = await _text_to_lab_json(full_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM returned invalid JSON: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Groq call failed: {exc}") from exc

    # Step 3: Normalise to exact schema
    result = _normalise_result(raw_result, user_id)
    param_count = len(result.get("linkedParameters", {}))
    print(f"[PDF→JSON] Done — {param_count} parameters extracted, primary: {result['parameterName']}")

    return result


async def extract_lab_json_from_pdf_text(
    pdf_text: str,
    user_id: str = "",
) -> Dict[str, Any]:
    """Convert already-extracted PDF text to LabParameterSchema JSON.

    Useful when the caller has already run pdfplumber or another text
    extraction tool and just needs the LLM structuring step.

    Parameters
    ----------
    pdf_text : str
        Plain text extracted from the PDF.
    user_id : str, optional
        User identifier.

    Returns
    -------
    dict
        LabParameterSchema-compatible dictionary.
    """
    if not pdf_text or not pdf_text.strip():
        raise ValueError("Empty text provided.")

    try:
        raw_result = await _text_to_lab_json(pdf_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM returned invalid JSON: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Groq call failed: {exc}") from exc

    return _normalise_result(raw_result, user_id)
