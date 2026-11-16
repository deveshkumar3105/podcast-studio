"""Render a timed podcast episode as a captioned 16:9 MP4."""
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

from config import OUTPUTS_DIR


WIDTH = 1280
HEIGHT = 720
STOCK_STUDIO_VIDEO = Path(__file__).resolve().parent.parent / "static" / "media" / "podcast_hosts_pexels_2.mp4"


def _font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def _render_overlay(segment: Dict[str, Any], index: int, total: int, output: Path) -> None:
    """Draw a legible lower-third over the live two-host stock footage."""
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    speaker = str(segment.get("speaker", "Narrator"))
    accent = (129, 140, 248, 255) if speaker == "Host 1" else (45, 212, 191, 255) if speaker == "Host 2" else (216, 180, 254, 255)
    draw.rounded_rectangle((48, 448, 1232, 694), radius=25, fill=(4, 8, 20, 190), outline=(148, 163, 184, 72), width=2)
    draw.rounded_rectangle((78, 470, 300, 516), radius=15, fill=(accent[0], accent[1], accent[2], 45), outline=accent, width=2)
    draw.text((96, 478), speaker.upper(), font=_font(21), fill=accent)
    draw.text((1195, 480), f"{index + 1:02d}", font=_font(20), fill=(203, 213, 225, 230), anchor="ra")

    text = " ".join(str(segment.get("text", "")).split())
    body_font = _font(34)
    lines = _wrap_text(draw, text, body_font, 1060)
    while len(lines) > 3 and body_font.size > 27:
        body_font = _font(body_font.size - 2)
        lines = _wrap_text(draw, text, body_font, 1060)
    line_height = body_font.size + 9
    y = 530 + max(0, (116 - len(lines) * line_height) // 2)
    for line in lines:
        draw.text((82, y), line, font=body_font, fill=(248, 250, 252, 255))
        y += line_height

    draw.rounded_rectangle((78, 674, 1200, 679), radius=3, fill=(71, 85, 105, 220))
    progress_end = 78 + int(1122 * (index + 1) / max(1, total))
    draw.rounded_rectangle((78, 674, progress_end, 679), radius=3, fill=accent)
    image.save(output, format="PNG", optimize=True)


def create_captioned_video(episode_id: str) -> Dict[str, Any]:
    """Create a two-host studio video with timed subtitles from TTS metadata."""
    if not episode_id.startswith("episode_") or not episode_id.replace("episode_", "").isalnum():
        raise ValueError("Invalid episode ID.")

    audio_path = OUTPUTS_DIR / f"{episode_id}.mp3"
    metadata_path = OUTPUTS_DIR / f"{episode_id}.json"
    video_path = OUTPUTS_DIR / f"{episode_id}.mp4"
    render_path = OUTPUTS_DIR / f".{episode_id}.{uuid.uuid4().hex}.tmp.mp4"
    if not STOCK_STUDIO_VIDEO.is_file():
        raise FileNotFoundError("The bundled podcast studio footage is missing.")
    if not audio_path.is_file() or not metadata_path.is_file():
        raise FileNotFoundError("Episode audio or timing metadata was not found. Generate the audio again first.")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    source_segments = [s for s in metadata.get("segments", []) if str(s.get("text", "")).strip() and float(s.get("duration", 0)) > 0]
    if not source_segments:
        raise ValueError("No timed dialogue segments are available for this episode.")

    # Long spoken turns become multiple lower-thirds, with time split by word count.
    probe = ImageDraw.Draw(Image.new("RGB", (WIDTH, HEIGHT)))
    caption_font = _font(34)
    segments = []
    for source in source_segments:
        lines = _wrap_text(probe, " ".join(str(source["text"]).split()), caption_font, 1060)
        pages = [lines[offset:offset + 3] for offset in range(0, len(lines), 3)]
        page_words = [max(1, len(" ".join(page).split())) for page in pages]
        total_words = sum(page_words)
        for page, words in zip(pages, page_words):
            segments.append({
                "speaker": source.get("speaker", "Narrator"),
                "text": " ".join(page),
                "duration": float(source["duration"]) * words / total_words,
            })

    with tempfile.TemporaryDirectory(prefix="podcast_video_") as temp_dir:
        temp_path = Path(temp_dir)
        overlay_files = []
        for index, segment in enumerate(segments):
            overlay_path = temp_path / f"overlay_{index:05d}.png"
            _render_overlay(segment, index, len(segments), overlay_path)
            overlay_files.append(overlay_path)

        concat_path = temp_path / "overlays.txt"
        with concat_path.open("w", encoding="utf-8") as concat_file:
            for overlay_path, segment in zip(overlay_files, segments):
                concat_file.write(f"file '{overlay_path.as_posix()}'\n")
                concat_file.write(f"duration {float(segment['duration']):.3f}\n")
            # Make the final overlay slightly longer so the audio determines the end time.
            concat_file.write(f"file '{overlay_files[-1].as_posix()}'\n")

        command = [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
            "-stream_loop", "-1", "-i", str(STOCK_STUDIO_VIDEO),
            "-f", "concat", "-safe", "0", "-i", str(concat_path),
            "-i", str(audio_path),
            "-filter_complex", "[0:v]scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,fps=30[bg];[1:v]fps=30,format=rgba[fg];[bg][fg]overlay=shortest=1,format=yuv420p[outv]",
            "-map", "[outv]", "-map", "2:a:0",
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-profile:v", "main", "-level:v", "3.1", "-tag:v", "avc1",
            "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-profile:a", "aac_low", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", "-shortest", str(render_path),
        ]
        try:
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            if result.returncode != 0:
                detail = result.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(detail or "FFmpeg could not render the video.")
            if not render_path.is_file() or render_path.stat().st_size < 1024:
                raise RuntimeError("FFmpeg produced an incomplete video file.")
            os.replace(render_path, video_path)
        finally:
            render_path.unlink(missing_ok=True)

    return {
        "success": True,
        "episode_id": episode_id,
        "filename": video_path.name,
        "download_url": f"/api/download/{video_path.name}",
        "file_size_mb": round(video_path.stat().st_size / (1024 * 1024), 2),
        "scene_count": len(segments),
        "width": WIDTH,
        "height": HEIGHT,
    }
