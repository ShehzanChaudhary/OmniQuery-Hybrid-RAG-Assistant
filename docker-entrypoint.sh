#!/bin/sh
set -e

# Azure App Service (Linux) persists /home across restarts and redeploys via an
# Azure Files-backed mount; the rest of the container filesystem is ephemeral and
# is wiped on every restart/redeploy. Without this, every uploaded document, the
# vector store, SQLite tables, and chat history would vanish on the next restart.
#
# Requires WEBSITES_ENABLE_APP_SERVICE_STORAGE=true in the Web App's Application
# Settings. Plain `docker run` also has a writable /home, so this relocates data
# there consistently in every environment — mount a volume at /home locally
# (`docker run -v ragdata:/home ...`) to get the same persistence outside Azure.
PERSIST_ROOT="/home"

if [ -d "$PERSIST_ROOT" ] && [ -w "$PERSIST_ROOT" ]; then
    mkdir -p "$PERSIST_ROOT/data" "$PERSIST_ROOT/chroma_store"

    # First boot only: seed persistent storage with whatever shipped in the image
    # (the existing chroma_store / data checked into this repo). Later restarts
    # find $PERSIST_ROOT already populated and leave it untouched.
    if [ -d /app/data ] && [ -z "$(ls -A "$PERSIST_ROOT/data" 2>/dev/null)" ]; then
        cp -a /app/data/. "$PERSIST_ROOT/data/"
    fi
    if [ -d /app/chroma_store ] && [ -z "$(ls -A "$PERSIST_ROOT/chroma_store" 2>/dev/null)" ]; then
        cp -a /app/chroma_store/. "$PERSIST_ROOT/chroma_store/"
    fi

    rm -rf /app/data /app/chroma_store
    ln -s "$PERSIST_ROOT/data" /app/data
    ln -s "$PERSIST_ROOT/chroma_store" /app/chroma_store
fi

exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
