"""Ingestion engine: Handles YouTube caption extraction, web article extraction,
and local audio extraction from uploaded videos using imageio-ffmpeg.
"""
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import imageio_ffmpeg
import trafilatura
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled, VideoUnavailable


def get_ffmpeg_binary() -> str:
    """Return path to ffmpeg binary bundled via imageio-ffmpeg."""
    return imageio_ffmpeg.get_ffmpeg_exe()


def extract_youtube_video_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from various standard YouTube URL formats."""
    parsed = urlparse(url.strip())
    hostname = parsed.hostname or ""
    
    if "youtu.be" in hostname:
        return parsed.path.lstrip("/").split("?")[0]
    
    if "youtube.com" in hostname or "m.youtube.com" in hostname:
        if parsed.path == "/watch":
            params = parse_qs(parsed.query)
            return params.get("v", [None])[0]
        if parsed.path.startswith("/shorts/"):
            return parsed.path.split("/")[2]
        if parsed.path.startswith("/live/"):
            return parsed.path.split("/")[2]
        if parsed.path.startswith("/embed/"):
            return parsed.path.split("/")[2]
            
    return None


def detect_source_type(input_text: str) -> str:
    """Classify input as 'youtube', 'webpage', 'direct_media', or 'text'."""
    text = input_text.strip()
    if text.startswith("http://") or text.startswith("https://"):
        if extract_youtube_video_id(text):
            return "youtube"
        path = urlparse(text).path.lower()
        if path.endswith((".mp4", ".mov", ".mkv", ".webm", ".avi", ".mp3", ".wav", ".m4a", ".aac")):
            return "direct_media"
        return "webpage"
    return "text"


def fetch_youtube_captions(video_id: str, preferred_lang: str = "en") -> Dict[str, Any]:
    """Attempt to fetch public captions using youtube-transcript-api.
    Does not download video bytes. Respects platform access rules.
    """
    try:
        # Support both youtube-transcript-api 1.2+ (instance) and older (class methods)
        try:
            api = YouTubeTranscriptApi()
            transcript_obj = api.fetch(video_id, languages=(preferred_lang, "en"))
        except (TypeError, AttributeError):
            # Fallback for older static class API
            if hasattr(YouTubeTranscriptApi, "get_transcript"):
                data = YouTubeTranscriptApi.get_transcript(video_id, languages=[preferred_lang, "en"])
                full_text = " ".join([item.get("text", "") for item in data])
                cleaned_text = re.sub(r"\s+", " ", full_text).strip()
                return {
                    "success": True,
                    "source_type": "youtube_captions",
                    "video_id": video_id,
                    "language": preferred_lang,
                    "is_generated": False,
                    "transcript": cleaned_text,
                    "segments_count": len(data),
                    "word_count": len(cleaned_text.split()),
                    "estimated_tokens": int(len(cleaned_text.split()) * 1.3)
                }
            raise

        snippets = getattr(transcript_obj, "snippets", [])
        full_text = " ".join([getattr(s, "text", "") for s in snippets])
        cleaned_text = re.sub(r"\s+", " ", full_text).strip()

        return {
            "success": True,
            "source_type": "youtube_captions",
            "video_id": video_id,
            "language": getattr(transcript_obj, "language", preferred_lang),
            "is_generated": getattr(transcript_obj, "is_generated", False),
            "transcript": cleaned_text,
            "segments_count": len(snippets),
            "word_count": len(cleaned_text.split()),
            "estimated_tokens": int(len(cleaned_text.split()) * 1.3)
        }

    except TranscriptsDisabled:
        return {
            "success": False,
            "error_type": "transcripts_disabled",
            "message": "The creator has disabled public captions for this video.",
            "options": [
                {"id": "extract_audio", "label": "Extract public audio track for local Whisper transcription"},
                {"id": "upload_file", "label": "Upload video/audio file directly"}
            ]
        }
    except VideoUnavailable:
        return {
            "success": False,
            "error_type": "video_unavailable",
            "message": "This video is unavailable, private, or region-restricted.",
            "options": [
                {"id": "upload_file", "label": "Upload the video file directly instead"}
            ]
        }
    except Exception as e:
        return {
            "success": False,
            "error_type": "caption_error",
            "message": f"Could not retrieve captions: {str(e)}",
            "options": [
                {"id": "extract_audio", "label": "Try extracting public audio for local Whisper transcription"},
                {"id": "upload_file", "label": "Upload the video file directly"}
            ]
        }


def extract_web_article(url: str) -> Dict[str, Any]:
    """Extract clean text content from a public web page/article using trafilatura."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return {
                "success": False,
                "message": f"Failed to fetch content from {url}. The page may be behind a paywall or blocking automated access."
            }
        
        extracted_text = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
        if not extracted_text or len(extracted_text.split()) < 30:
            return {
                "success": False,
                "message": "The page could not be parsed as an article or contained insufficient text. Try pasting the text directly."
            }

        words = len(extracted_text.split())
        return {
            "success": True,
            "source_type": "webpage",
            "url": url,
            "transcript": extracted_text,
            "word_count": words,
            "estimated_tokens": int(words * 1.3)
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error extracting article from URL: {str(e)}"
        }


def extract_audio_from_media(input_path: str, output_wav_path: Optional[str] = None) -> str:
    """Extract 16kHz mono WAV audio from any video or audio file using bundled ffmpeg.
    Optimized for Whisper transcription input.
    """
    ffmpeg_exe = get_ffmpeg_binary()
    if not output_wav_path:
        fd, output_wav_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)

    # ffmpeg -y -i <input> -vn -acodec pcm_s16le -ar 16000 -ac 1 <output>
    cmd = [
        ffmpeg_exe,
        "-y",
        "-i", input_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        output_wav_path
    ]

    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0:
        err = res.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"FFmpeg audio extraction failed: {err}")

    return output_wav_path


def download_public_audio_track(url: str, output_path: str) -> str:
    """Download only the public audio track using yt-dlp if permitted.
    Does not download full video streams, saving bandwidth and processing time.
    """
    import yt_dlp
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_path + '.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'extract_audio': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        # yt-dlp might have saved with extension
        base, ext = os.path.splitext(filename)
        candidates = [filename, output_path + '.webm', output_path + '.m4a', output_path + '.mp3']
        for cand in candidates:
            if os.path.exists(cand):
                return cand
        return filename
