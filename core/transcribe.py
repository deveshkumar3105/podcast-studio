"""Local transcription engine using faster-whisper.
Runs 100% on-device (CPU / Apple Silicon).
"""
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import av
# Compatibility patch: PyAV >= 19 removed the deprecated 'metadata_errors' parameter
_orig_av_open = av.open
def _safe_av_open(*args, **kwargs):
    kwargs.pop("metadata_errors", None)
    return _orig_av_open(*args, **kwargs)
av.open = _safe_av_open

from faster_whisper import WhisperModel
from core.cache import cache_manager
from core.ingest import extract_audio_from_media

# Singleton model cache to avoid re-loading weights into RAM on each request
_LOADED_MODELS: Dict[str, WhisperModel] = {}


def get_whisper_model(model_size: str = "base") -> WhisperModel:
    """Retrieve or lazily initialize the faster-whisper model.
    Checks local HuggingFace cache first for 100% offline operation.
    """
    global _LOADED_MODELS
    if model_size not in _LOADED_MODELS:
        import glob
        snapshot_pattern = os.path.expanduser(f"~/.cache/huggingface/hub/models--Systran--faster-whisper-{model_size}/snapshots/*")
        snaps = glob.glob(snapshot_pattern)
        
        target_path_or_size = snaps[0] if snaps else model_size

        _LOADED_MODELS[model_size] = WhisperModel(
            target_path_or_size,
            device="cpu",
            compute_type="int8"
        )
    return _LOADED_MODELS[model_size]


def transcribe_media_file(
    file_path: str,
    cache_key: Optional[str] = None,
    model_size: str = "base",
    force_refresh: bool = False
) -> Dict[str, Any]:
    """Transcribe a local video or audio file with faster-whisper.
    Checks and updates local disk cache.
    """
    # 1. Check cache if key provided
    if cache_key and not force_refresh:
        cached = cache_manager.get(cache_key, "transcript")
        if cached:
            return {
                **cached["payload"],
                "from_cache": True,
                "saved_at": cached.get("saved_at")
            }

    start_time = time.time()
    temp_wav_path = None
    
    try:
        # 2. If it's a video file or non-wav audio, extract 16kHz mono WAV first
        ext = Path(file_path).suffix.lower()
        if ext in [".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4a", ".aac", ".flac", ".ogg"]:
            temp_wav_path = extract_audio_from_media(file_path)
            audio_target = temp_wav_path
        else:
            audio_target = file_path

        # 3. Load model and transcribe
        model = get_whisper_model(model_size)
        segments, info = model.transcribe(
            audio_target,
            beam_size=5,
            vad_filter=True, # Voice Activity Detection filters out silent chunks
            vad_parameters=dict(min_silence_duration_ms=500)
        )

        segment_list = []
        full_text_parts = []
        for seg in segments:
            text = seg.text.strip()
            if text:
                full_text_parts.append(text)
                segment_list.append({
                    "start": round(seg.start, 2),
                    "end": round(seg.end, 2),
                    "text": text
                })

        full_transcript = " ".join(full_text_parts)
        words = len(full_transcript.split())
        elapsed = round(time.time() - start_time, 2)

        result = {
            "success": True,
            "source_type": "local_whisper",
            "model_used": f"faster-whisper ({model_size})",
            "detected_language": info.language,
            "language_probability": round(info.language_probability, 3),
            "duration_seconds": round(info.duration, 2),
            "processing_time_seconds": elapsed,
            "transcript": full_transcript,
            "segments": segment_list,
            "word_count": words,
            "estimated_tokens": int(words * 1.3),
            "privacy_notice": "100% processed locally on your Mac. No audio was sent to any external server."
        }

        # 4. Save to cache
        if cache_key:
            cache_manager.set(cache_key, "transcript", result)

        return result

    finally:
        # Cleanup temporary audio extraction file
        if temp_wav_path and os.path.exists(temp_wav_path):
            try:
                os.unlink(temp_wav_path)
            except Exception:
                pass
