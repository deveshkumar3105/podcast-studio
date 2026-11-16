"""Multi-voice Text-To-Speech synthesis engine using Edge-TTS.
Parses multi-speaker dialogue scripts and concatenates audio tracks using bundled FFmpeg.
"""
import asyncio
import json
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import edge_tts
from edge_tts.exceptions import NoAudioReceived
from config import DEFAULT_VOICES, OUTPUTS_DIR
from core.ingest import get_ffmpeg_binary


def parse_script_dialogue(script_text: str) -> List[Dict[str, str]]:
    """Parse dialogue script into ordered segments of (speaker, line_text)."""
    lines = script_text.strip().split("\n")
    segments: List[Dict[str, str]] = []
    current_speaker = "Host 1"
    current_buffer: List[str] = []

    # Regex matches: [Host 1]:, [Host 2]:, [Narrator]:, or Host 1:, Host 2:, Narrator:
    speaker_pattern = re.compile(r"^\[?(Host 1|Host 2|Narrator)\]?\s*:\s*(.*)$", re.IGNORECASE)

    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue
            
        match = speaker_pattern.match(line_clean)
        if match:
            if current_buffer:
                segments.append({
                    "speaker": current_speaker,
                    "text": " ".join(current_buffer).strip()
                })
                current_buffer = []
            
            raw_speaker = match.group(1).title()
            # Normalize casing
            if "Host 1" in raw_speaker:
                current_speaker = "Host 1"
            elif "Host 2" in raw_speaker:
                current_speaker = "Host 2"
            else:
                current_speaker = "Narrator"
                
            remainder = match.group(2).strip()
            if remainder:
                current_buffer.append(remainder)
        else:
            # Continuation line
            current_buffer.append(line_clean)

    if current_buffer:
        segments.append({
            "speaker": current_speaker,
            "text": " ".join(current_buffer).strip()
        })

    # If no speaker tags matched at all, treat whole text as Narrator
    if not segments and script_text.strip():
        segments.append({
            "speaker": "Narrator",
            "text": script_text.strip()
        })

    return segments


VOICE_DELIVERY = {
    # Distinct, restrained delivery presets for a less uniform two-host sound.
    "en-US-JennyNeural": {"rate": "-3%", "pitch": "-1Hz"},
    "en-US-ChristopherNeural": {"rate": "-8%", "pitch": "-5Hz"},
    "en-IE-EmilyNeural": {"rate": "-2%", "pitch": "+1Hz"},
    "en-IE-ConnorNeural": {"rate": "-3%", "pitch": "-2Hz"},
}


async def synthesize_segment(text: str, voice: str, output_path: str) -> None:
    """Generate one dialogue clip, retrying transient empty Edge-TTS responses."""
    delivery = VOICE_DELIVERY.get(voice, {})
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            Path(output_path).unlink(missing_ok=True)
            communicate = edge_tts.Communicate(text=text, voice=voice, **delivery)
            await communicate.save(output_path)
            if not Path(output_path).is_file() or Path(output_path).stat().st_size < 128:
                raise NoAudioReceived("Edge-TTS returned an empty audio file.")
            return
        except NoAudioReceived as exc:
            Path(output_path).unlink(missing_ok=True)
            if attempt == max_attempts:
                raise RuntimeError(
                    f"Microsoft Edge TTS returned no audio after {max_attempts} attempts "
                    f"for voice {voice}. Check internet access and try again; the speech "
                    "service may be temporarily unavailable."
                ) from exc
            await asyncio.sleep(1.5 * attempt)


def concatenate_audio_files(input_files: List[str], output_file: str) -> None:
    """Concatenate multiple mp3 clips into a single master mp3 using bundled ffmpeg."""
    ffmpeg_exe = get_ffmpeg_binary()
    
    # Create temporary concat list file
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        list_file_path = f.name
        for p in input_files:
            f.write(f"file '{os.path.abspath(p)}'\n")

    try:
        # Re-encode to ensure uniform sample rates and smooth seams between clips
        cmd = [
            ffmpeg_exe,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file_path,
            "-c:a", "libmp3lame",
            "-q:a", "2",
            output_file
        ]
        res = subprocess_run = __import__("subprocess").run(
            cmd,
            stdout=__import__("subprocess").PIPE,
            stderr=__import__("subprocess").PIPE
        )
        if res.returncode != 0:
            err = res.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"FFmpeg concatenation error: {err}")
    finally:
        if os.path.exists(list_file_path):
            try:
                os.unlink(list_file_path)
            except Exception:
                pass


def get_audio_duration(path: str) -> float:
    """Read an audio file duration from FFmpeg's stream metadata."""
    ffmpeg_exe = get_ffmpeg_binary()
    result = subprocess.run(
        [ffmpeg_exe, "-hide_banner", "-i", path, "-f", "null", "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    output = result.stderr.decode("utf-8", errors="replace")
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    if not match:
        raise RuntimeError(f"Could not determine audio duration for {Path(path).name}.")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


async def generate_podcast_audio_async(
    script_text: str,
    voice_host1: str = "en-US-JennyNeural",
    voice_host2: str = "en-IE-EmilyNeural",
    voice_narrator: str = "en-US-JennyNeural",
    episode_title: Optional[str] = None
) -> Dict[str, Any]:
    """Parse dialogue lines, synthesize speaker audio segments with Edge-TTS,
    and merge into a single downloadable .mp3 file.
    """
    segments = parse_script_dialogue(script_text)
    if not segments:
        raise ValueError("Script is empty or has no readable text.")

    episode_id = f"episode_{uuid.uuid4().hex[:8]}"
    final_output_path = OUTPUTS_DIR / f"{episode_id}.mp3"
    timeline = []
    
    temp_dir = tempfile.mkdtemp(prefix="podcast_tts_")
    clip_files = []
    
    try:
        speaker_stats = {"Host 1": 0, "Host 2": 0, "Narrator": 0}
        
        for idx, seg in enumerate(segments):
            speaker = seg["speaker"]
            text = seg["text"]
            if not text:
                continue

            # Select voice according to speaker tag
            if speaker == "Host 1":
                voice = voice_host1
                speaker_stats["Host 1"] += 1
            elif speaker == "Host 2":
                voice = voice_host2
                speaker_stats["Host 2"] += 1
            else:
                voice = voice_narrator
                speaker_stats["Narrator"] += 1

            clip_path = os.path.join(temp_dir, f"clip_{idx:04d}.mp3")
            # Track the path before synthesis so any partial file is cleaned up
            # if the upstream service or local network fails mid-request.
            clip_files.append(clip_path)
            try:
                await synthesize_segment(text, voice, clip_path)
            except Exception as exc:
                raise RuntimeError(
                    f"Audio synthesis failed for {speaker} using {voice} "
                    f"(dialogue segment {idx + 1} of {len(segments)}): {exc}"
                ) from exc
            timeline.append({
                "speaker": speaker,
                "text": text,
                "duration": get_audio_duration(clip_path),
            })

        if not clip_files:
            raise ValueError("No audio segments were successfully synthesized.")

        # Stitch all clips together into master mp3
        concatenate_audio_files(clip_files, str(final_output_path))
        metadata_path = OUTPUTS_DIR / f"{episode_id}.json"
        metadata_path.write_text(
            json.dumps({"segments": timeline}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        
        file_size_mb = round(final_output_path.stat().st_size / (1024 * 1024), 2)
        
        return {
            "success": True,
            "episode_id": episode_id,
            "filename": f"{episode_id}.mp3",
            "file_path": str(final_output_path),
            "download_url": f"/api/download/{episode_id}.mp3",
            "stream_url": f"/api/audio/{episode_id}.mp3",
            "episode_id": episode_id,
            "file_size_mb": file_size_mb,
            "total_segments": len(clip_files),
            "speaker_breakdown": speaker_stats
        }

    finally:
        # Clean up temporary clip directory
        for p in clip_files:
            if os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass
        if os.path.exists(temp_dir):
            try:
                os.rmdir(temp_dir)
            except Exception:
                pass


def generate_podcast_audio(
    script_text: str,
    voice_host1: str = "en-US-JennyNeural",
    voice_host2: str = "en-IE-EmilyNeural",
    voice_narrator: str = "en-US-JennyNeural"
) -> Dict[str, Any]:
    """Synchronous wrapper for generate_podcast_audio_async."""
    return asyncio.run(generate_podcast_audio_async(
        script_text=script_text,
        voice_host1=voice_host1,
        voice_host2=voice_host2,
        voice_narrator=voice_narrator
    ))
