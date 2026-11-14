"""Dynamic Gemini Model Router with Auto-Discovery and Free-Tier Rate-Limit Failover.
Uses the modern official google.genai SDK.
Automatically detects active models from Google and switches models without user intervention when 429 hits.
"""
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from google import genai
from google.genai import types
from config import DEFAULT_GEMINI_MODELS

logger = logging.getLogger("model_router")

# Cache discovered models in memory with timestamp
_DISCOVERED_MODELS_CACHE: Dict[str, Any] = {
    "timestamp": 0,
    "models": []
}
CACHE_TTL_SECONDS = 3600 * 6  # 6 hours


def discover_available_gemini_models(api_key: str, force_refresh: bool = False) -> List[str]:
    """Dynamically query Google Gemini API to discover active models supporting text generation.
    Filters and ranks free-tier-friendly models without requiring user configuration updates.
    """
    global _DISCOVERED_MODELS_CACHE
    now = time.time()
    
    if not force_refresh and _DISCOVERED_MODELS_CACHE["models"] and (now - _DISCOVERED_MODELS_CACHE["timestamp"] < CACHE_TTL_SECONDS):
        return _DISCOVERED_MODELS_CACHE["models"]

    try:
        client = genai.Client(api_key=api_key)
        all_models = list(client.models.list())
        
        supported = []
        for m in all_models:
            actions = getattr(m, "supported_actions", []) or []
            name = (getattr(m, "name", "") or "").replace("models/", "")
            # Check if model supports generateContent
            if not actions or "generateContent" in actions or "generate_content" in actions:
                # Include standard text models
                if "gemini" in name.lower() and not any(x in name.lower() for x in ["vision", "embedding", "aqa", "imagen"]):
                    supported.append(name)

        # Rank models favoring fastest and best free-tier models first
        def rank_key(model_name: str) -> Tuple[int, str]:
            lower = model_name.lower()
            if "gemini-2.5-flash" in lower:
                return (1, lower)
            if "gemini-2.0-flash" in lower and "lite" not in lower:
                return (2, lower)
            if "gemini-2.0-flash-lite" in lower:
                return (3, lower)
            if "gemini-1.5-flash" in lower and "8b" not in lower:
                return (4, lower)
            if "gemini-1.5-flash-8b" in lower:
                return (5, lower)
            if "flash" in lower:
                return (6, lower)
            if "pro" in lower:
                return (7, lower)
            return (8, lower)

        ranked = sorted(list(set(supported)), key=rank_key)
        
        if ranked:
            _DISCOVERED_MODELS_CACHE["timestamp"] = now
            _DISCOVERED_MODELS_CACHE["models"] = ranked
            return ranked

    except Exception as e:
        logger.warning(f"Dynamic model discovery failed: {e}. Using fallback defaults.")

    return DEFAULT_GEMINI_MODELS


def is_rate_limit_error(error: Exception) -> bool:
    """Detect HTTP 429, ResourceExhausted, or quota limits."""
    msg = str(error).lower()
    return any(indicator in msg for indicator in [
        "429",
        "resourceexhausted",
        "quota",
        "rate limit",
        "too many requests",
        "exhausted",
        "limit exceeded"
    ])


def generate_with_failover(
    prompt: str,
    system_instruction: str,
    api_key: str,
    preferred_model: Optional[str] = None
) -> Dict[str, Any]:
    """Execute text generation with dynamic fallback across free-tier models.
    Catches 429 errors and automatically switches models without user intervention.
    """
    client = genai.Client(api_key=api_key)
    available_models = discover_available_gemini_models(api_key)

    # Build model candidate sequence starting with preferred model if provided
    candidate_models: List[str] = []
    if preferred_model and preferred_model in available_models:
        candidate_models.append(preferred_model)
    for m in available_models:
        if m not in candidate_models:
            candidate_models.append(m)

    failover_log: List[Dict[str, str]] = []
    last_error = None

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.7,
    )

    for model_name in candidate_models:
        try:
            logger.info(f"Attempting generation with model: {model_name}")
            
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config
            )
            
            # Successful response
            response_text = response.text or ""
            usage = getattr(response, "usage_metadata", None)
            prompt_tokens = getattr(usage, "prompt_token_count", int(len(prompt.split()) * 1.3)) if usage else int(len(prompt.split()) * 1.3)
            candidate_tokens = getattr(usage, "candidates_token_count", int(len(response_text.split()) * 1.3)) if usage else int(len(response_text.split()) * 1.3)

            return {
                "success": True,
                "text": response_text,
                "model_used": model_name,
                "failover_occurred": len(failover_log) > 0,
                "failover_log": failover_log,
                "prompt_tokens": prompt_tokens,
                "output_tokens": candidate_tokens,
                "total_tokens": prompt_tokens + candidate_tokens,
                "estimated_cost_usd": 0.0, # Free tier
                "available_model_pool": available_models[:6]
            }

        except Exception as e:
            last_error = e
            if is_rate_limit_error(e):
                logger.warning(f"Rate limit hit on {model_name}. Switching to next model...")
                failover_log.append({
                    "model": model_name,
                    "reason": "429 Rate Limit / Quota Exhausted. Auto-switched to next model."
                })
                time.sleep(1.0)
                continue
            else:
                logger.warning(f"Error on {model_name}: {e}. Retrying with next candidate...")
                failover_log.append({
                    "model": model_name,
                    "reason": f"API Error: {str(e)[:120]}"
                })
                continue

    return {
        "success": False,
        "error": f"All free-tier models failed or were rate-limited. Last error: {str(last_error)}",
        "failover_log": failover_log,
        "available_model_pool": available_models
    }
