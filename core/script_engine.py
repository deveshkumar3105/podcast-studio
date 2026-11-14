"""Podcast script generation engine.
Implements strict factual grounding, 1-narrator or 2-host styles,
hierarchical chunk-and-summarize for long inputs, and local caching.
"""
import math
import re
from typing import Any, Dict, List, Optional
from config import CHUNK_OVERLAP_WORDS, CHUNK_SIZE_WORDS, CHUNK_WORD_THRESHOLD
from core.cache import cache_manager
from core.model_router import generate_with_failover


def estimate_token_count(text: str) -> int:
    """Fast local heuristic token estimator (~1.3 tokens per word)."""
    words = len(text.strip().split())
    return int(words * 1.3)


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE_WORDS, overlap: int = CHUNK_OVERLAP_WORDS) -> List[str]:
    """Split long text into overlapping word chunks for map-reduce summarization."""
    words = text.strip().split()
    if len(words) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk_words = words[start:end]
        chunks.append(" ".join(chunk_words))
        if end >= len(words):
            break
        start += (chunk_size - overlap)
    return chunks


def summarize_chunk(chunk: str, api_key: str, preferred_model: Optional[str] = None) -> str:
    """Extract core claims and facts from a single text chunk once."""
    system_instruction = (
        "You are an objective fact extraction assistant. Extract all factual claims, data points, "
        "names, and key concepts from the text. Do not invent any facts. Preserve accuracy strictly."
    )
    prompt = (
        "Analyze the following text and extract the key points, claims, and findings as bullet points.\n\n"
        f"SOURCE TEXT:\n{chunk}\n\n"
        "KEY POINTS (bullet points only, strictly factual):"
    )
    res = generate_with_failover(prompt, system_instruction, api_key, preferred_model)
    if res.get("success"):
        return res["text"]
    return chunk[:1000] # Fallback if summarization fails


def build_system_prompt(style: str, language: str) -> str:
    """Create system instructions with strict grounding and formatting rules."""
    lang_instruction = f"The entire script must be written in {language}."
    
    if style == "two_host":
        return f"""You are an award-winning podcast writer producing a conversational, informative two-host podcast episode.
{lang_instruction}

STRICT GROUNDING RULES:
1. Do NOT invent facts, statistics, quotes, or findings.
2. Every major claim must originate directly from the source material.
3. If the hosts offer an analogy, clarifying explanation, or conversational bridge, it must be framed naturally as host interpretation, clearly distinct from the source's verified claims.
4. Keep the banter lively, natural, curious, and fast-paced—not robotic or corporate.

SPEAKER FORMAT RULES (CRITICAL FOR TTS PARSING):
Every line of dialogue MUST begin with either '[Host 1]:' or '[Host 2]:' on a new line.
- [Host 1] is the curious, relatable main host who guides the listener and asks probing questions.
- [Host 2] is the knowledgeable co-host who unpacks the details, findings, and nuances.
Do NOT include sound effect markers, background music cues, or markdown asterisks around speaker names. Output ONLY the lines of dialogue.
"""
    else: # one_narrator
        return f"""You are an award-winning podcast writer and narrative audio storyteller.
{lang_instruction}

STRICT GROUNDING RULES:
1. Do NOT invent facts, statistics, quotes, or findings.
2. Every core insight must originate directly from the source material.
3. If offering context or analogies, ensure the listener understands what came from the source versus narrative transition.
4. The tone should be engaging, immersive, and clear.

SPEAKER FORMAT RULES (CRITICAL FOR TTS PARSING):
Every paragraph must begin with '[Narrator]:' on a new line.
Do NOT include sound effect markers, background music cues, or markdown asterisks around speaker names. Output ONLY the narrative lines.
"""


def generate_podcast_script(
    transcript: str,
    api_key: str,
    style: str = "two_host",
    duration: str = "medium",
    language: str = "English",
    cache_key: Optional[str] = None,
    preferred_model: Optional[str] = None,
    force_refresh: bool = False
) -> Dict[str, Any]:
    """Generate grounded podcast script from transcript with token caching & dynamic fallback."""
    # 1. Check cache for this specific combination
    script_cache_id = f"{cache_key}_{style}_{duration}_{language}" if cache_key else None
    if script_cache_id and not force_refresh:
        cached = cache_manager.get(script_cache_id, "script")
        if cached:
            return {
                **cached["payload"],
                "from_cache": True,
                "saved_at": cached.get("saved_at")
            }

    words_in_transcript = len(transcript.strip().split())

    # 2. Check if hierarchical summarization is required (for long content)
    working_content = transcript
    chunk_summaries_used = False
    
    if words_in_transcript > CHUNK_WORD_THRESHOLD:
        chunks = chunk_text(transcript)
        summaries = []
        for idx, ch in enumerate(chunks):
            # Check per-chunk cache
            ch_hash = cache_manager.compute_hash(ch)
            cached_ch = cache_manager.get(ch_hash, "chunk_summary")
            if cached_ch and not force_refresh:
                summaries.append(cached_ch["payload"]["summary"])
            else:
                summary_text = summarize_chunk(ch, api_key, preferred_model)
                summaries.append(summary_text)
                cache_manager.set(ch_hash, "chunk_summary", {"summary": summary_text})
                
        working_content = "\n\n---\n\n".join(summaries)
        chunk_summaries_used = True

    # 3. Target word counts based on duration
    length_guidelines = {
        "short": "approximately 500 to 750 words (around 3 to 4 minutes of spoken audio)",
        "medium": "approximately 1,100 to 1,400 words (around 8 to 10 minutes of spoken audio)",
        "long": "approximately 1,800 to 2,200 words (around 12 to 15 minutes of spoken audio)"
    }
    target_guidance = length_guidelines.get(duration, length_guidelines["medium"])

    system_instruction = build_system_prompt(style, language)
    
    prompt = f"""Write an engaging, grounded podcast script based strictly on the source material provided below.

TARGET DURATION & LENGTH:
Target length is {target_guidance}. Do not truncate prematurely. Provide a complete, satisfying episode with an intriguing intro, deep dive in the middle, and concise wrap-up.

LANGUAGE:
Produce the entire output in {language}.

SOURCE MATERIAL:
{working_content}

Write the podcast script now adhering strictly to the speaker tags format:"""

    result = generate_with_failover(
        prompt=prompt,
        system_instruction=system_instruction,
        api_key=api_key,
        preferred_model=preferred_model
    )

    if not result.get("success"):
        return result

    # 4. Clean up response to ensure clean speaker tags
    raw_script = result["text"]
    # Strip any accidental intro preamble before first speaker tag
    first_speaker_idx = re.search(r"\[(Host 1|Host 2|Narrator)\]:", raw_script)
    if first_speaker_idx:
        cleaned_script = raw_script[first_speaker_idx.start():].strip()
    else:
        cleaned_script = raw_script.strip()

    script_words = len(cleaned_script.split())
    # Estimate spoken duration (average talking speed ~150 words per minute)
    estimated_audio_minutes = round(script_words / 150, 1)

    output_payload = {
        "success": True,
        "script": cleaned_script,
        "style": style,
        "duration": duration,
        "language": language,
        "script_word_count": script_words,
        "estimated_audio_minutes": estimated_audio_minutes,
        "model_used": result["model_used"],
        "failover_occurred": result["failover_occurred"],
        "failover_log": result["failover_log"],
        "tokens": {
            "prompt_tokens": result["prompt_tokens"],
            "output_tokens": result["output_tokens"],
            "total_tokens": result["total_tokens"]
        },
        "chunk_summaries_used": chunk_summaries_used,
        "estimated_cost_usd": 0.0
    }

    # 5. Persist to cache
    if script_cache_id:
        cache_manager.set(script_cache_id, "script", output_payload)

    return output_payload
