"""Multi-voice Text-To-Speech synthesis engine using Edge-TTS.
Parses multi-speaker dialogue scripts and concatenates audio tracks using bundled FFmpeg.
"""
import asyncio
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import edge_tts
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


async def synthesize_segment(text: str, voice: str, output_path: str) -> None:
    """Generate audio for a single dialogue line using Edge-TTS."""
    communicate = edge_tts.Communicate(text=text, voice=voice)
    await communicate.save(output_path)


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


async def generate_podcast_audio_async(
    script_text: str,
    voice_host1: str = "en-US-GuyNeural",
    voice_host2: str = "en-US-JennyNeural",
    voice_narrator: str = "en-US-ChristopherNeural",
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
            await synthesize_segment(text, voice, clip_path)
            clip_files.append(clip_path)

        if not clip_files:
            raise ValueError("No audio segments were successfully synthesized.")

        # Stitch all clips together into master mp3
        concatenate_audio_files(clip_files, str(final_output_path))
        
        file_size_mb = round(final_output_path.stat().st_size / (1024 * 1024), 2)
        
        return {
            "success": True,
            "episode_id": episode_id,
            "filename": f"{episode_id}.mp3",
            "file_path": str(final_output_path),
            "download_url": f"/api/download/{episode_id}.mp3",
            "stream_url": f"/api/audio/{episode_id}.mp3",
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
    voice_host1: str = "en-US-GuyNeural",
    voice_host2: str = "en-US-JennyNeural",
    voice_narrator: str = "en-US-ChristopherNeural"
) -> Dict[str, Any]:
    """Synchronous wrapper for generate_podcast_audio_async."""
    return asyncio.run(generate_podcast_audio_async(
        script_text=script_text,
        voice_host1=voice_host1,
        voice_host2=voice_host2,
        voice_narrator=voice_narrator
    ))
