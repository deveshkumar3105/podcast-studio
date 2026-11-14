# 🎙️ Podcast Studio

**Podcast Studio** is a cost-efficient, privacy-respecting application that transforms **pasted text**, **uploaded video/audio**, or **video links** into downloadable, broadcast-quality podcast episodes.

Built with a local-first philosophy, it maximizes free and open-source tools (Edge-TTS, Faster-Whisper, ImageIO-FFmpeg) and pairs them with Google Gemini API for intelligent, grounded podcast scripting with zero redundant token waste.

---

## 📑 Table of Contents
- [Architecture & Tech Stack](#-architecture--tech-stack)
- [Key Features](#-key-features)
- [How Caching Works (Demystified)](#-how-caching-works-demystified)
- [Rate Limit Handling & Dynamic Model Failover](#-rate-limit-handling--dynamic-model-failover)
- [Quick Start Guide](#-quick-start-guide)
- [Core Workflow](#-core-workflow)
- [Project Directory Structure](#-project-directory-structure)
- [Troubleshooting & FAQ](#-troubleshooting--faq)

---

## 🏗️ Architecture & Tech Stack

| Layer | Technology | Purpose & Why Chosen |
| :--- | :--- | :--- |
| **Frontend** | HTML5 + Tailwind CSS + Alpine/Vanilla JS | Modern dark-mode studio UI, live token estimator, side-by-side editable review boxes, interactive audio player. |
| **Backend API** | FastAPI + Uvicorn | Lightweight, high-performance async Python backend. |
| **Speech-to-Text (STT)** | `faster-whisper` (CTranslate2) | 100% on-device local transcription for uploaded files. Zero audio sent to external servers. |
| **Audio Processing** | `imageio-ffmpeg` | Bundles static FFmpeg binaries automatically; extracts audio from MP4/MOV/MKV and stitches MP3 dialogues without needing system package installs. |
| **Captions Ingest** | `youtube-transcript-api` | Probes YouTube for official captions first (0 MB video download, instant, free, respects platform terms). |
| **Article Extractor** | `trafilatura` | Strips ads, navbars, and boilerplate from public article links with 0 AI tokens. |
| **Script Generation** | Google Gemini API (`google-genai`) | High-speed, long-context grounded generation with free-tier support. |
| **Text-to-Speech (TTS)** | `edge-tts` | Studio-quality neural multi-voice synthesis (Guy, Jenny, Christopher, etc.) with 0 API keys and zero cost. |

---

## ⚡ Key Features

1. **Multi-Source Ingestion:**
   - **YouTube URLs:** Fetches human or auto-generated captions in <1 second. If captions are disabled by the creator, clearly offers accessible fallback options without silently breaking platform rules.
   - **File Uploads:** Drag-and-drop video (`.mp4`, `.mov`, `.mkv`, `.webm`) or audio (`.mp3`, `.wav`, `.m4a`). Audio is extracted and transcribed locally on your Mac.
   - **Pasted Text:** Instant intake for research notes, articles, or transcripts with live word/token counters.

2. **Full Review & Editability:**
   - **Step 2 (Transcript Review):** Full editable textarea to prune or amend source text before any LLM processing.
   - **Step 3 (Script Studio):** Edit the generated dialogue directly, tweak host jokes, or refine explanations before audio synthesis.

3. **Multi-Voice Studio Casting:**
   - **Two Hosts:** Conversational banter between `[Host 1]` (curious/engaging) and `[Host 2]` (expert/analytical).
   - **Solo Narrator:** Immersive narrative storytelling style.
   - Natural 350ms conversational pauses and seamless FFmpeg audio stitching.

---

## 💾 How Caching Works (Demystified)

Every source input (URL, text, or file) has a unique **SHA-256 fingerprint** computed:
```
Input Source -> SHA-256 Hash (e.g. 8f4a2b1c...) -> Saved to ./cache/
```

* **Why it saves time & tokens:**
  - If you transcribe a 15-minute video, Whisper takes ~1–2 minutes of CPU work. If you subsequently decide to change the episode length from 5 minutes to 8 minutes, the cache ensures **you never wait for Whisper again**—the transcript loads in 0 milliseconds.
  - If you re-open an episode you worked on earlier, it loads instantly from disk with **0 LLM calls**.
  - For long documents (>2,500 words), chunk summaries are saved individually. Re-running the script only synthesizes the final dialogue without re-summarizing each chunk.
* **Full User Control:**
  - Check the **"Ignore local cache and re-fetch"** box to force fresh processing.
  - Click the **trash icon** in the top navigation bar to clear the cache anytime.

---

## 🔄 Rate Limit Handling & Dynamic Model Failover

Google's free-tier Gemini API enforces RPM/TPM limits. If hit, it returns HTTP `429 (ResourceExhausted)`.

Podcast Studio includes an automatic router:
1. **Dynamic Model Discovery:** On startup (and refreshed via the UI), it queries the Gemini API to list all active generation models (e.g., `gemini-2.0-flash`, `gemini-1.5-flash`, `gemini-1.5-flash-8b`).
2. **Auto-Switching Failover:** When a rate limit or quota error occurs on the primary model, the router catches it, logs the switch, and automatically retries with the next available model in the sequence **without failing or requiring user intervention**.
3. **Failover Banner:** A notification banner in the UI informs you if a model switch occurred.

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- macOS (Apple Silicon or Intel) or Linux
- Python 3.9+ (Python 3.10–3.14 supported)

### 2. Launching the App
Simply run the included launch script:
```bash
./run_studio.sh
```

Or manually via terminal:
```bash
# 1. Activate the virtual environment
source .venv/bin/activate

# 2. Start the Uvicorn server
uvicorn app:app --host 127.0.0.1 --port 8000
```

### 3. Open in Your Browser
Navigate to:
👉 **[http://127.0.0.1:8000](http://127.0.0.1:8000)**

### 4. Setting Your Gemini API Key
Click **"Set API Key"** in the top right of the web UI to paste your key (stored in your browser's local storage), or set it in your terminal:
```bash
export GEMINI_API_KEY="your-gemini-api-key"
```
*(Get a free key at [Google AI Studio](https://aistudio.google.com/app/apikey))*

---

## 🔄 Core Workflow

```
[ Step 1: Source Input ]
   │  Choose YouTube URL, Video/Audio Upload, or Raw Text
   ▼
[ Step 2: Transcript Review & Edit ]
   │  Review extracted text, inspect token count, edit if desired
   ▼
[ Step 3: Script Studio ]
   │  Pick Host Style (1 or 2), Length (3m, 8m, 15m), Language & Voices
   │  Click "Generate Podcast Script" (with 429 auto-switch failover)
   │  Edit dialogue lines directly in the script editor
   ▼
[ Step 4: Listen & Download ]
      Edge-TTS synthesizes dialogue segments
      FFmpeg stitches into master MP3
      Stream in browser player or download episode
```

---

## 📁 Project Directory Structure

```
bu/
├── app.py                  # FastAPI REST endpoints & route controllers
├── config.py               # Voice mappings, model fallback list, thresholds
├── run_studio.sh           # One-click executable launch script
├── requirements.txt        # Pinned Python package dependencies
├── FAQ.txt                 # Detailed FAQ, resolved bugs, and troubleshooting
├── README.md               # System documentation (this file)
│
├── core/
│   ├── cache.py            # Local SHA-256 disk cache manager
│   ├── ingest.py           # Caption extractor, article reader, FFmpeg audio converter
│   ├── model_router.py     # Dynamic Gemini model discovery & 429 auto-failover
│   ├── script_engine.py    # Grounded podcast prompt builder & chunking engine
│   ├── transcribe.py       # faster-whisper local STT with PyAV compatibility
│   └── tts_engine.py       # Multi-voice Edge-TTS synthesizer & audio stitcher
│
├── static/
│   ├── index.html          # Clean dark-mode responsive web studio
│   ├── style.css           # Custom audio player and stepper animations
│   └── app.js              # Client-side state, API calls, and event wiring
│
├── cache/                  # Disk cache directory for transcripts and scripts
└── outputs/                # Generated .mp3 podcast episodes
```

---

## ❓ Troubleshooting & FAQ

For known issues, detailed explanations of errors faced during development, and troubleshooting resolutions, refer to **[FAQ.txt](FAQ.txt)**.
