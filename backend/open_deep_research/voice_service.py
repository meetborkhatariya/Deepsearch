"""Voice insight generation service for health reports.

Pipeline
--------
1. GPT-4o-mini generates a patient-friendly voice script from the analysis.
2. (Optional) Sarvam AI TTS converts the script to speech in the requested language.

Languages supported: english, hindi, gujarati

Environment variables
---------------------
OPENAI_API_KEY   - required for script generation
SARVAM_API_KEY   - optional; if absent, audio is skipped and only the script is returned

Sarvam AI voice codes used
--------------------------
english  → anushka (en-IN)
hindi    → anushka (hi-IN)
gujarati → anushka (gu-IN)
"""

import os
import base64
import httpx
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Language config
# ---------------------------------------------------------------------------

_LANGUAGE_CONFIG: Dict[str, Dict[str, str]] = {
    "english": {
        "code": "en-IN",
        "voice": "anushka",  # confirmed valid speaker for bulbul:v2
        "instruction": "Write in clear, simple English.",
    },
    "hindi": {
        "code": "hi-IN",
        "voice": "anushka",  # anushka is multilingual, supports Hindi
        "instruction": "Write entirely in Hindi (Devanagari script). Use simple, everyday Hindi.",
    },
    "gujarati": {
        "code": "gu-IN",
        "voice": "anushka",  # confirmed valid: bulbul:v2 + anushka + gu-IN
        "instruction": "Write entirely in Gujarati (Gujarati script). Use simple, everyday Gujarati.",
    },
    "marathi": {
        "code": "mr-IN",
        "voice": "anushka",  # anushka is multilingual, supports Marathi
        "instruction": "Write entirely in Marathi (Devanagari script). Use simple, everyday Marathi.",
    },
    "malayalam": {
        "code": "ml-IN",
        "voice": "anushka",  # anushka is multilingual, supports Malayalam
        "instruction": "Write entirely in Malayalam. Use simple, everyday Malayalam.",
    },
    "kannada": {
        "code": "kn-IN",
        "voice": "anushka",  # anushka is multilingual, supports Kannada
        "instruction": "Write entirely in Kannada. Use simple, everyday Kannada.",
    },
    "tamil": {
        "code": "ta-IN",
        "voice": "anushka",  # anushka is multilingual, supports Tamil
        "instruction": "Write entirely in Tamil. Use simple, everyday Tamil.",
    },
    "bangla": {
        "code": "bn-IN",
        "voice": "anushka",  # anushka is multilingual, supports Bengali
        "instruction": "Write entirely in Bangla (Bengali script). Use simple, everyday Bangla.",
    },
}

_SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"

# ---------------------------------------------------------------------------
# Script generation
# ---------------------------------------------------------------------------

_SCRIPT_SYSTEM = """You are a warm, empathetic health advisor creating a SHORT voice message 
for a patient about their lab results. The message will be read aloud by a text-to-speech engine.

Guidelines:
- 150-250 words maximum (≈ 1 minute of audio)
- Conversational, friendly tone — avoid clinical jargon
- Mention the most important finding(s) with the actual value
- Give 1-2 clear, actionable next steps
- End with encouragement
- Do NOT use markdown, bullet points, asterisks, or any special characters
- Write in plain flowing prose only
"""


def _get_openai_async():
    from openai import AsyncOpenAI
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    return AsyncOpenAI(api_key=api_key)


async def _generate_script(
    full_analysis: str,
    structured_summary: Dict[str, Any],
    language: str,
    is_new_user: bool,
    report_date: str,
) -> str:
    """Use GPT-4o-mini to produce a spoken-word voice script."""
    lang_cfg = _LANGUAGE_CONFIG.get(language, _LANGUAGE_CONFIG["english"])
    lang_instruction = lang_cfg["instruction"]

    greeting = "Welcome!" if is_new_user else "Welcome back!"

    # Build a concise context for the model
    primary_param = ""
    if isinstance(structured_summary, dict):
        pp = structured_summary.get("primary_parameter", {})
        if isinstance(pp, dict):
            primary_param = f"{pp.get('name', '')} = {pp.get('value', '')} {pp.get('unit', '')}".strip()

    user_prompt = (
        f"{greeting}\n"
        f"Report date: {report_date}\n"
        f"Primary finding: {primary_param}\n\n"
        f"Full analysis summary (use this as your source):\n{full_analysis[:3000]}\n\n"
        f"{lang_instruction}\n"
        "Now write the voice message:"
    )

    oai = _get_openai_async()
    response = await oai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _SCRIPT_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.6,
        max_tokens=600,
    )
    return (response.choices[0].message.content or "").strip()


# ---------------------------------------------------------------------------
# Sarvam AI TTS
# ---------------------------------------------------------------------------

async def _sarvam_tts(script: str, language: str) -> Optional[str]:
    """Call Sarvam AI TTS and return base64-encoded audio, or None on failure."""
    api_key = os.getenv("SARVAM_API_KEY")
    if not api_key:
        return None

    lang_cfg = _LANGUAGE_CONFIG.get(language, _LANGUAGE_CONFIG["english"])

    # Sarvam TTS accepts max ~500 chars per request; split if needed
    chunks = [script[i : i + 500] for i in range(0, len(script), 500)]
    audio_parts: list[str] = []

    async with httpx.AsyncClient(timeout=30) as http:
        for chunk in chunks:
            payload = {
                "inputs": [chunk],
                "target_language_code": lang_cfg["code"],
                "speaker": lang_cfg["voice"],
                "pace": 1.15,
                "speech_sample_rate": 22050,
                "enable_preprocessing": True,
                "model": "bulbul:v2",
            }
            try:
                resp = await http.post(
                    _SARVAM_TTS_URL,
                    json=payload,
                    headers={
                        "api-subscription-key": api_key,
                        "Content-Type": "application/json",
                    },
                )
                if not resp.is_success:
                    print(f"[VoiceService] Sarvam TTS error {resp.status_code}: {resp.text[:300]}")
                resp.raise_for_status()
                data = resp.json()
                audios = data.get("audios", [])
                if audios:
                    audio_parts.append(audios[0])
            except Exception as exc:
                print(f"[VoiceService] Sarvam TTS chunk failed: {exc}")
                # Continue — partial audio is still useful

    if not audio_parts:
        return None

    if len(audio_parts) == 1:
        return audio_parts[0]

    # Concatenate multiple WAV base64 chunks into a single WAV
    # Each chunk is a full WAV file; we need to strip headers from subsequent chunks
    import io
    import wave

    combined = io.BytesIO()
    writer = None
    for idx, b64_chunk in enumerate(audio_parts):
        raw = base64.b64decode(b64_chunk)
        buf = io.BytesIO(raw)
        try:
            reader = wave.open(buf, "rb")
        except Exception:
            continue
        if writer is None:
            writer = wave.open(combined, "wb")
            writer.setnchannels(reader.getnchannels())
            writer.setsampwidth(reader.getsampwidth())
            writer.setframerate(reader.getframerate())
        writer.writeframes(reader.readframes(reader.getnframes()))
        reader.close()
    if writer:
        writer.close()
    return base64.b64encode(combined.getvalue()).decode("utf-8")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_health_voice_insight(
    full_analysis: str,
    structured_summary: Dict[str, Any],
    user_id: str,
    report_date: str,
    txn_id: str,
    is_new_user: bool = False,
    language: str = "english",
) -> Dict[str, Any]:
    """Generate a voice insight for a health report.

    Parameters
    ----------
    full_analysis:       Complete text analysis from the researcher.
    structured_summary:  Structured summary dict (may contain primary_parameter etc.).
    user_id:             Patient identifier.
    report_date:         ISO date string of the report.
    txn_id:              Transaction ID (for logging).
    is_new_user:         Whether this is the patient's first report.
    language:            Output language — 'english', 'hindi', or 'gujarati'.

    Returns
    -------
    dict with keys:
        voice_agent_script  str   Plain-text voice script
        audio_base64        str | None  Base64-encoded WAV (None if Sarvam key absent)
        language            str
        language_code       str
        tts_provider        str
        character_count     int
    """
    language = (language or "english").lower()
    if language not in _LANGUAGE_CONFIG:
        language = "english"

    print(f"[VoiceService] Generating {language} voice for txn={txn_id}, user={user_id}")

    try:
        script = await _generate_script(
            full_analysis=full_analysis,
            structured_summary=structured_summary,
            language=language,
            is_new_user=is_new_user,
            report_date=report_date,
        )
    except Exception as exc:
        print(f"[VoiceService] Script generation failed: {exc}")
        script = "Your health report has been analysed. Please consult your doctor for details."

    audio_b64 = await _sarvam_tts(script, language)
    tts_provider = "sarvam" if audio_b64 else "none"

    lang_cfg = _LANGUAGE_CONFIG[language]
    print(
        f"[VoiceService] Done. Script length={len(script)} chars, "
        f"audio={'yes' if audio_b64 else 'no'}, provider={tts_provider}"
    )

    return {
        "voice_agent_script": script,
        "audio_base64": audio_b64,
        "language": language,
        "language_code": lang_cfg["code"],
        "tts_provider": tts_provider,
        "character_count": len(script),
    }
