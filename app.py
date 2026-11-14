"""FastAPI Application for Podcast Studio.
Serves the REST API and modern interactive frontend.
"""
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import BASE_DIR, CACHE_DIR, DEFAULT_VOICES, OUTPUTS_DIR
from core.cache import cache_manager
from core.ingest import (
    detect_source_type,
    download_public_audio_track,
    extract_web_article,
    extract_youtube_video_id,
    fetch_youtube_captions,
)
from core.model_router import (
    DEFAULT_GEMINI_MODELS,
    discover_available_gemini_models,
)
from core.script_engine import estimate_token_count, generate_podcast_script
from core.transcribe import transcribe_media_file
from core.tts_engine import generate_podcast_audio_async

app = FastAPI(title="Podcast Studio", version="1.0.0")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount outputs for direct media access
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


# Pydantic Schemas
class IngestTextRequest(BaseModel):
    input_text: str
    force_refresh: bool = False
    action_override: Optional[str] = None  # e.g., 'extract_audio'


class GenerateScriptRequest(BaseModel):
    transcript: str
    cache_key: Optional[str] = None
    style: str = "two_host"  # 'two_host' or 'one_narrator'
    duration: str = "medium"  # 'short', 'medium', 'long'
    language: str = "English"
    api_key: Optional[str] = None
    preferred_model: Optional[str] = None
    force_refresh: bool = False


class SynthesizeAudioRequest(BaseModel):
    script: str
    voice_host1: str = "en-US-GuyNeural"
    voice_host2: str = "en-US-JennyNeural"
    voice_narrator: str = "en-US-ChristopherNeural"


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = BASE_DIR / "static" / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>Podcast Studio is starting up...</h1>")
    with open(index_file, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/api/status")
async def get_system_status():
    env_api_key = os.environ.get("GEMINI_API_KEY", "")
    return {
        "status": "online",
        "has_env_api_key": bool(env_api_key),
        "api_key_masked": f"{env_api_key[:4]}...{env_api_key[-4:]}" if len(env_api_key) > 8 else None,
        "cache_stats": cache_manager.stats(),
        "default_voices": DEFAULT_VOICES,
        "fallback_models": DEFAULT_GEMINI_MODELS
    }


@app.post("/api/models")
async def list_models(payload: Dict[str, Optional[str]]):
    api_key = payload.get("api_key") or os.environ.get("GEMINI_API_KEY", "")
    force_refresh = payload.get("force_refresh", False)
    if not api_key:
        return {"models": DEFAULT_GEMINI_MODELS, "source": "config_defaults"}
    
    models = discover_available_gemini_models(api_key, force_refresh=bool(force_refresh))
    return {
        "models": models,
        "source": "dynamic_discovery",
        "count": len(models)
    }


@app.post("/api/ingest")
async def ingest_source(payload: IngestTextRequest):
    input_text = payload.input_text.strip()
    if not input_text:
        raise HTTPException(status_code=400, detail="Input text or URL cannot be empty.")

    cache_key = cache_manager.compute_hash(input_text)

    # Check cache first
    if not payload.force_refresh and not payload.action_override:
        cached = cache_manager.get(cache_key, "transcript")
        if cached:
            return {
                **cached["payload"],
                "cache_key": cache_key,
                "from_cache": True,
                "saved_at": cached.get("saved_at")
            }

    source_type = detect_source_type(input_text)

    if source_type == "youtube":
        video_id = extract_youtube_video_id(input_text)
        if not video_id:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL format.")

        # If user explicitly requested audio fallback because captions were absent
        if payload.action_override == "extract_audio":
            temp_dir = tempfile.mkdtemp()
            try:
                temp_audio_base = os.path.join(temp_dir, f"yt_{video_id}")
                audio_file = download_public_audio_track(input_text, temp_audio_base)
                result = transcribe_media_file(
                    file_path=audio_file,
                    cache_key=cache_key,
                    force_refresh=payload.force_refresh
                )
                result["cache_key"] = cache_key
                result["source_url"] = input_text
                return result
            finally:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)

        # 1. Caption-first extraction
        caption_res = fetch_youtube_captions(video_id)
        if caption_res.get("success"):
            caption_res["cache_key"] = cache_key
            caption_res["source_url"] = input_text
            caption_res["privacy_notice"] = "Public captions retrieved directly via YouTube Transcript API. Zero video downloaded."
            cache_manager.set(cache_key, "transcript", caption_res)
            return caption_res
        else:
            # Return explanation and allowed options without bypassing platform rules
            return {
                "success": False,
                "requires_user_action": True,
                "cache_key": cache_key,
                "error_type": caption_res.get("error_type"),
                "message": caption_res.get("message"),
                "options": caption_res.get("options", [])
            }

    elif source_type == "webpage":
        # Public web article reader
        res = extract_web_article(input_text)
        if not res.get("success"):
            raise HTTPException(status_code=400, detail=res.get("message", "Could not extract article content."))
        
        res["cache_key"] = cache_key
        res["privacy_notice"] = "Article text extracted directly from URL via clean reader. Zero tokens used for ingestion."
        cache_manager.set(cache_key, "transcript", res)
        return res

    else:
        # Direct raw text
        words = len(input_text.split())
        if words < 10:
            raise HTTPException(status_code=400, detail="Input text is too short. Please provide at least a couple of sentences.")
        
        result = {
            "success": True,
            "source_type": "pasted_text",
            "cache_key": cache_key,
            "transcript": input_text,
            "word_count": words,
            "estimated_tokens": int(words * 1.3),
            "privacy_notice": "Stored in local cache only. Not transmitted until you generate the script."
        }
        cache_manager.set(cache_key, "transcript", result)
        return result


@app.post("/api/upload")
async def upload_media_file(
    file: UploadFile = File(...),
    model_size: str = Form("base"),
    force_refresh: bool = Form(False)
):
    """Handle uploaded video/audio file and transcribe locally with faster-whisper."""
    filename = file.filename or "upload.mp4"
    suffix = Path(filename).suffix.lower()
    allowed_exts = [".mp4", ".mov", ".mkv", ".webm", ".avi", ".mp3", ".wav", ".m4a", ".aac", ".flac"]
    
    if suffix not in allowed_exts:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{suffix}'. Supported formats: {', '.join(allowed_exts)}"
        )

    # Save to temporary file and compute hash
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as f:
            file_bytes = f.read(1024 * 1024) # Read first MB for quick unique hash
        cache_key = cache_manager.compute_file_hash(file_bytes)

        res = transcribe_media_file(
            file_path=tmp_path,
            cache_key=cache_key,
            model_size=model_size,
            force_refresh=force_refresh
        )
        res["cache_key"] = cache_key
        res["original_filename"] = filename
        return res

    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


@app.post("/api/generate-script")
async def generate_script(payload: GenerateScriptRequest):
    """Generate podcast script using Google Gemini with dynamic model failover on 429."""
    api_key = payload.api_key or os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="Google Gemini API Key is required. Please set GEMINI_API_KEY or enter your key in the header."
        )

    if not payload.transcript.strip():
        raise HTTPException(status_code=400, detail="Transcript content is empty.")

    result = generate_podcast_script(
        transcript=payload.transcript,
        api_key=api_key,
        style=payload.style,
        duration=payload.duration,
        language=payload.language,
        cache_key=payload.cache_key,
        preferred_model=payload.preferred_model,
        force_refresh=payload.force_refresh
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Failed to generate script across all available models.")
        )

    return result


@app.post("/api/synthesize-audio")
async def synthesize_audio(payload: SynthesizeAudioRequest):
    """Synthesize multi-speaker podcast audio from script via Edge-TTS."""
    if not payload.script.strip():
        raise HTTPException(status_code=400, detail="Podcast script is empty.")

    try:
        result = await generate_podcast_audio_async(
            script_text=payload.script,
            voice_host1=payload.voice_host1,
            voice_host2=payload.voice_host2,
            voice_narrator=payload.voice_narrator
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Audio synthesis failed: {str(e)}")


@app.get("/api/audio/{filename}")
async def stream_audio(filename: str):
    """Stream generated MP3 for browser player."""
    file_path = OUTPUTS_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio episode not found.")
    return FileResponse(file_path, media_type="audio/mpeg")


@app.get("/api/download/{filename}")
async def download_audio(filename: str):
    """Download MP3 episode file."""
    file_path = OUTPUTS_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio episode not found.")
    return FileResponse(
        file_path,
        media_type="audio/mpeg",
        filename=f"podcast_{filename}",
        headers={"Content-Disposition": f'attachment; filename="podcast_{filename}"'}
    )


@app.post("/api/cache/clear")
async def clear_cache():
    """Clear all cached transcripts and scripts."""
    count = cache_manager.clear_all()
    return {"success": True, "cleared_files": count}
