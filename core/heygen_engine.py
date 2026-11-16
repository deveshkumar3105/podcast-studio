"""Optional HeyGen Studio rendering using the user's own API credits."""
import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, List

import httpx

from config import HEYGEN_API_KEY, OUTPUTS_DIR


API_ROOT = "https://api.heygen.com/v3"
POLL_INTERVAL_SECONDS = 8
MAX_POLL_ATTEMPTS = 150


def _headers() -> Dict[str, str]:
    if not HEYGEN_API_KEY:
        raise RuntimeError("Premium rendering is not configured. Add HEYGEN_API_KEY to .env and restart Podcast Studio.")
    return {"X-Api-Key": HEYGEN_API_KEY, "Content-Type": "application/json"}


async def _list_pages(client: httpx.AsyncClient, path: str, params: Dict[str, str]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    token = None
    for _ in range(20):
        query = {**params, "limit": "50"}
        if token:
            query["token"] = token
        response = await client.get(f"{API_ROOT}{path}", headers=_headers(), params=query)
        if response.is_error:
            raise RuntimeError(f"HeyGen catalog request failed ({response.status_code}): {response.text[:500]}")
        result = response.json().get("data", {})
        if isinstance(result, list):
            items.extend(result)
            has_more = response.json().get("has_more", False)
            token = response.json().get("next_token")
        else:
            items.extend(result.get("data", []))
            has_more = result.get("has_more", False)
            token = result.get("next_token")
        if not has_more or not token:
            break
    return items


async def get_heygen_catalog() -> Dict[str, List[Dict[str, Any]]]:
    """Return public and account-owned avatar looks and voices."""
    async with httpx.AsyncClient(timeout=45) as client:
        jobs = []
        for ownership in ("public", "private"):
            jobs.append(_list_pages(client, "/avatars/looks", {"ownership": ownership}))
        for voice_type in ("public", "private"):
            jobs.append(_list_pages(client, "/models/audio/voices", {"type": voice_type}))
        public_avatars, private_avatars, public_voices, private_voices = await asyncio.gather(*jobs)

    avatars = [item for item in public_avatars + private_avatars if item.get("status", "completed") == "completed"]
    voices = [item for item in public_voices + private_voices if item.get("status", "ACTIVE") == "ACTIVE"]
    return {"avatars": avatars, "voices": voices}


def _read_scenes(episode_id: str, host1_avatar_id: str, host1_voice_id: str,
                 host2_avatar_id: str, host2_voice_id: str) -> List[Dict[str, Any]]:
    if not re.fullmatch(r"episode_[a-f0-9]{8}", episode_id):
        raise ValueError("Invalid episode ID.")
    metadata_path = OUTPUTS_DIR / f"{episode_id}.json"
    if not metadata_path.is_file():
        raise FileNotFoundError("Episode timing data is missing. Synthesize the episode again first.")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    dialogue: List[Dict[str, str]] = []
    for segment in metadata.get("segments", []):
        text = " ".join(str(segment.get("text", "")).split())
        if not text:
            continue
        speaker = str(segment.get("speaker", "Narrator"))
        if dialogue and dialogue[-1]["speaker"] == speaker:
            dialogue[-1]["text"] += " " + text
        else:
            dialogue.append({"speaker": speaker, "text": text})

    if not dialogue:
        raise ValueError("No dialogue segments are available for premium rendering.")
    if len(dialogue) > 50:
        raise ValueError("This script has more than 50 speaker turns. Shorten the script before premium rendering.")

    scenes = []
    for segment in dialogue:
        if segment["speaker"] == "Host 2":
            avatar_id, voice_id = host2_avatar_id, host2_voice_id
        else:
            avatar_id, voice_id = host1_avatar_id, host1_voice_id
        scenes.append({
            "type": "avatar_video",
            "input": {
                "type": "avatar",
                "avatar_id": avatar_id,
                "script": segment["text"],
                "voice_id": voice_id,
                "background": {"type": "color", "color": "#101827"},
            },
        })
    return scenes


async def create_heygen_video(
    episode_id: str,
    host1_avatar_id: str,
    host1_voice_id: str,
    host2_avatar_id: str,
    host2_voice_id: str,
) -> Dict[str, Any]:
    """Submit one multi-scene Studio job and download the completed MP4."""
    for identifier in (host1_avatar_id, host1_voice_id, host2_avatar_id, host2_voice_id):
        if not identifier or len(identifier) > 160 or not re.fullmatch(r"[A-Za-z0-9_-]+", identifier):
            raise ValueError("Select a valid HeyGen avatar and voice for both hosts.")

    scenes = _read_scenes(episode_id, host1_avatar_id, host1_voice_id, host2_avatar_id, host2_voice_id)
    payload = {
        "type": "studio",
        "title": f"Podcast Studio {episode_id}",
        "aspect_ratio": "16:9",
        "resolution": "1080p",
        "caption": {"file_format": "srt", "style": "default"},
        "scenes": scenes,
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(90, read=180)) as client:
        response = await client.post(f"{API_ROOT}/videos", headers=_headers(), json=payload)
        if response.is_error:
            raise RuntimeError(f"HeyGen rejected the premium video request ({response.status_code}): {response.text[:700]}")
        create_result = response.json().get("data", {})
        video_id = create_result.get("video_id") or create_result.get("id")
        if not video_id:
            raise RuntimeError("HeyGen accepted the request but did not return a video ID.")

        video_url = None
        for _ in range(MAX_POLL_ATTEMPTS):
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            status_response = await client.get(f"{API_ROOT}/videos/{video_id}", headers=_headers())
            if status_response.is_error:
                raise RuntimeError(f"Could not check HeyGen render status ({status_response.status_code}).")
            status_data = status_response.json().get("data", {})
            status = status_data.get("status", "").lower()
            if status in {"completed", "complete", "done"}:
                video_url = status_data.get("video_url") or status_data.get("url")
                break
            if status in {"failed", "error", "cancelled"}:
                raise RuntimeError(status_data.get("error", "HeyGen video generation failed."))
        if not video_url:
            raise TimeoutError("HeyGen is still rendering this video. Check your HeyGen dashboard before retrying to avoid a second credit charge.")

        output_path = OUTPUTS_DIR / f"{episode_id}_premium.mp4"
        temp_path = OUTPUTS_DIR / f".{episode_id}_premium.tmp.mp4"
        try:
            async with client.stream("GET", video_url, timeout=httpx.Timeout(60, read=600)) as download:
                download.raise_for_status()
                with temp_path.open("wb") as output_file:
                    async for chunk in download.aiter_bytes():
                        output_file.write(chunk)
            if not temp_path.is_file() or temp_path.stat().st_size < 1024:
                raise RuntimeError("HeyGen returned an incomplete video file.")
            temp_path.replace(output_path)
        finally:
            temp_path.unlink(missing_ok=True)

    return {
        "success": True,
        "episode_id": episode_id,
        "filename": output_path.name,
        "download_url": f"/api/download/{output_path.name}",
        "file_size_mb": round(output_path.stat().st_size / (1024 * 1024), 2),
        "scene_count": len(scenes),
        "provider": "HeyGen",
    }
