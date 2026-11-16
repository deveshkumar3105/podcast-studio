"""Configuration and settings for the Podcast Studio."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache"
OUTPUTS_DIR = BASE_DIR / "outputs"
HEYGEN_API_KEY = os.environ.get("HEYGEN_API_KEY", "").strip()
CACHE_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)

# Default Model Pool fallback order for Google Gemini free tier
DEFAULT_GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
]

# Voice presets for Edge-TTS
DEFAULT_VOICES = {
    "en": {
        "host1": {"name": "Jenny (US, Warm/Natural)", "id": "en-US-JennyNeural"},
        "host2": {"name": "Emily (Ireland, Conversational/Clear)", "id": "en-IE-EmilyNeural"},
        "narrator": {"name": "Jenny (US, Warm/Storyteller)", "id": "en-US-JennyNeural"},
    },
    "es": {
        "host1": {"name": "Alvaro (Spain, Dynamic)", "id": "es-ES-AlvaroNeural"},
        "host2": {"name": "Elvira (Spain, Clear)", "id": "es-ES-ElviraNeural"},
        "narrator": {"name": "Alvaro (Spain, Storyteller)", "id": "es-ES-AlvaroNeural"},
    },
    "fr": {
        "host1": {"name": "Henri (France, Dynamic)", "id": "fr-FR-HenriNeural"},
        "host2": {"name": "Denise (France, Warm)", "id": "fr-FR-DeniseNeural"},
        "narrator": {"name": "Henri (France, Storyteller)", "id": "fr-FR-HenriNeural"},
    },
    "de": {
        "host1": {"name": "Conrad (Germany, Clear)", "id": "de-DE-ConradNeural"},
        "host2": {"name": "Katja (Germany, Engaging)", "id": "de-DE-KatjaNeural"},
        "narrator": {"name": "Conrad (Germany, Storyteller)", "id": "de-DE-ConradNeural"},
    },
    "hi": {
        "host1": {"name": "Madhur (India, Energetic)", "id": "hi-IN-MadhurNeural"},
        "host2": {"name": "Swara (India, Clear)", "id": "hi-IN-SwaraNeural"},
        "narrator": {"name": "Madhur (India, Storyteller)", "id": "hi-IN-MadhurNeural"},
    }
}

# Long-form threshold (words) before triggering hierarchical chunk & summarize
CHUNK_WORD_THRESHOLD = 2500
CHUNK_SIZE_WORDS = 1800
CHUNK_OVERLAP_WORDS = 200
