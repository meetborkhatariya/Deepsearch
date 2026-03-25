import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from open_deep_research.pdf_to_json import _normalise_result, _parse_llm_json


def test_parse_llm_json_handles_markdown_fence():
    raw = '```json\n{"parameterName":"HbA1c","currentValue":"7.2"}\n```'

    parsed = _parse_llm_json(raw)

    assert parsed["parameterName"] == "HbA1c"
    assert parsed["currentValue"] == "7.2"


def test_normalise_result_adds_defaults_and_primary_parameter_entry():
    raw = {
        "parameterName": "HbA1c",
        "currentValue": 10.8,
        "reportDate": "25/03/2026",
        "linkedParameters": {
            "hemoglobin": {
                "name": "Hemoglobin",
                "normalRange": "13 - 17",
                "currentValues": [{"value": 13.4, "date": "2026-03-25", "unit": "g/dL"}],
            }
        },
    }

    result = _normalise_result(raw, user_id="u-123")

    assert result["user_id"] == "u-123"
    assert result["reportDate"] == "2026-03-25"
    assert result["language"] == "english"
    assert result["model"] == "openai"
    assert "hba1c" in result["linkedParameters"]
    assert result["linkedParameters"]["hba1c"]["currentValues"][0]["value"] == "10.8"


def test_normalise_result_builds_current_value_fallback_when_missing():
    raw = {
        "parameterName": "Total Cholesterol",
        "currentValue": "220",
        "reportDate": "2026-03-25",
        "linkedParameters": {
            "total_cholesterol": {
                "name": "Total Cholesterol",
                "normalRange": "< 200",
                "value": 220,
                "unit": "mg/dL",
                "currentValues": [],
            }
        },
    }

    result = _normalise_result(raw, user_id="u-xyz")
    cv = result["linkedParameters"]["total_cholesterol"]["currentValues"][0]

    assert cv["value"] == "220"
    assert cv["date"] == "2026-03-25"
    assert cv["unit"] == "mg/dL"
