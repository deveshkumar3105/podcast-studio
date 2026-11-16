#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Optional local secrets. Keep .env out of Git.
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
fi

echo "=========================================================="
echo "           🎙️  Starting Podcast Studio Web Server         "
echo "=========================================================="
echo "Open your browser at: http://127.0.0.1:8000"
echo "Press Ctrl+C to stop."
echo "=========================================================="

exec .venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
