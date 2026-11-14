"""Local disk caching system for transcripts, summaries, and generated scripts.
Ensures zero redundant API calls and zero redundant Whisper passes.
"""
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional
from config import CACHE_DIR

class CacheManager:
    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def compute_hash(content: str) -> str:
        """Compute SHA-256 fingerprint for arbitrary text, URL, or identifier."""
        return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()

    @staticmethod
    def compute_file_hash(file_bytes: bytes) -> str:
        """Compute SHA-256 fingerprint for uploaded binary media."""
        return hashlib.sha256(file_bytes).hexdigest()

    def _get_path(self, cache_key: str, step: str) -> Path:
        return self.cache_dir / f"{cache_key}_{step}.json"

    def get(self, cache_key: str, step: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached entry for a given step ('transcript', 'script', 'summary')."""
        path = self._get_path(cache_key, step)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception:
            return None

    def set(self, cache_key: str, step: str, payload: Dict[str, Any]) -> None:
        """Persist data into cache file with timestamp metadata."""
        path = self._get_path(cache_key, step)
        data = {
            "cache_key": cache_key,
            "step": step,
            "saved_at": time.time(),
            "payload": payload
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def delete(self, cache_key: str) -> int:
        """Delete all cached files for a specific key."""
        count = 0
        for f in self.cache_dir.glob(f"{cache_key}_*.json"):
            try:
                f.unlink()
                count += 1
            except Exception:
                pass
        return count

    def clear_all(self) -> int:
        """Wipe entire cache directory."""
        count = 0
        for f in self.cache_dir.glob("*.json"):
            try:
                f.unlink()
                count += 1
            except Exception:
                pass
        return count

    def stats(self) -> Dict[str, Any]:
        """Return cache summary (total items, total disk size)."""
        files = list(self.cache_dir.glob("*.json"))
        total_size = sum(f.stat().st_size for f in files)
        return {
            "total_cached_items": len(files),
            "total_size_kb": round(total_size / 1024, 2)
        }

cache_manager = CacheManager()
