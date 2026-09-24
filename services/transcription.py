from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests


DEEPGRAM_ENDPOINT = "https://api.deepgram.com/v1/listen"


def transcribe_audio(path: Path, mime_type: str) -> dict[str, Any]:
    """Transcribe one answer, or return a safe manual-entry fallback."""

    api_key = os.getenv("DEEPGRAM_API_KEY", "").strip()
    if not api_key:
        return {
            "transcript": "",
            "provider": "manual",
            "warning": "Speech-to-text is not configured. Enter or paste the transcript manually.",
        }

    endpoint = os.getenv("DEEPGRAM_BASE_URL", DEEPGRAM_ENDPOINT).strip()
    params = {
        "model": os.getenv("DEEPGRAM_MODEL", "nova-3"),
        "language": os.getenv("DEEPGRAM_LANGUAGE", "en-AU"),
        "smart_format": "true",
        "punctuate": "true",
    }
    try:
        with path.open("rb") as audio_file:
            response = requests.post(
                endpoint,
                params=params,
                headers={
                    "Authorization": f"Token {api_key}",
                    "Content-Type": mime_type or "application/octet-stream",
                },
                data=audio_file,
                timeout=(5, 70),
            )
        response.raise_for_status()
        payload = response.json()
        transcript = (
            payload.get("results", {})
            .get("channels", [{}])[0]
            .get("alternatives", [{}])[0]
            .get("transcript", "")
        )
        return {
            "transcript": str(transcript or "").strip(),
            "provider": "deepgram",
            "warning": None,
        }
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return {
            "transcript": "",
            "provider": "manual",
            "warning": "Automatic transcription failed. The recording is preserved for manual review.",
        }
