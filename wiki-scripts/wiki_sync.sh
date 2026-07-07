#!/usr/bin/env bash
set -euo pipefail

# --- config ---
SCRIPT_DIR="/Users/manoj2do/Desktop/BE/poc_workspace/wiki-scripts"
VENV_PYTHON="${SCRIPT_DIR}/.venv/bin/python"
LOG_DIR="${SCRIPT_DIR}/logs"
TIMESTAMP="$(date +'%Y-%m-%d_%H-%M-%S')"
LOG_FILE="${LOG_DIR}/wiki_sync_${TIMESTAMP}.log"
LATEST_LOG="${LOG_DIR}/wiki_sync_latest.log"
MAX_FETCH_RETRIES=10

TEST_BOOK_ID="${1:-}"
if [[ -n "$TEST_BOOK_ID" ]]; then
  BOOK_SELECTOR=(--book-id "$TEST_BOOK_ID")
else
  BOOK_SELECTOR=(--all-books)
fi

mkdir -p "$LOG_DIR"
cd "$SCRIPT_DIR"

# Redirect all output to log + latest symlink
exec > >(tee -a "$LOG_FILE") 2>&1
ln -sf "$LOG_FILE" "$LATEST_LOG"

log() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"; }

on_exit() {
  local exit_code=$?
  if [[ $exit_code -eq 0 ]]; then
    log "STATUS: SUCCESS"
  else
    log "STATUS: FAILED (exit code $exit_code)"
  fi
  exit "$exit_code"
}
trap on_exit EXIT

has_fetch_errors() {
  "$VENV_PYTHON" -c "
import json, sys
from pathlib import Path

path = Path('output/books_full.json')
if not path.exists():
    sys.exit(1)

errors = json.load(path.open(encoding='utf-8')).get('errors', [])
sys.exit(0 if errors else 1)
"
}

count_fetch_errors() {
  "$VENV_PYTHON" -c "
import json
from pathlib import Path

path = Path('output/books_full.json')
if not path.exists():
    print(0)
else:
    print(len(json.load(path.open(encoding='utf-8')).get('errors', [])))
"
}

count_book_files() {
  find output/books -maxdepth 1 -name 'book_*.json' 2>/dev/null | wc -l | tr -d ' '
}

count_chunks() {
  "$VENV_PYTHON" -c "
import json
from pathlib import Path

path = Path('output/pinecone/manifest.json')
if not path.exists():
    print(0)
else:
    print(json.load(path.open(encoding='utf-8')).get('total_chunks', 0))
"
}

log "=== Weekly wiki sync started ==="
log "Working directory: $(pwd)"
log "Python: $VENV_PYTHON"

# --- Step 1: Fetch all books ---
log "Step 1/4: Fetching all books..."
log "CMD: $VENV_PYTHON fetch_wiki_data.py ${BOOK_SELECTOR[*]} --no-plaintext-export"
"$VENV_PYTHON" fetch_wiki_data.py \
  "${BOOK_SELECTOR[@]}" \
  --no-plaintext-export

# --- Step 2: Retry errors (up to 3 attempts) ---
attempt=1
if has_fetch_errors; then
  while has_fetch_errors && [[ $attempt -le $MAX_FETCH_RETRIES ]]; do
    log "Step 2/4: Retry attempt ${attempt}/${MAX_FETCH_RETRIES} for failed books..."
    "$VENV_PYTHON" fetch_wiki_data.py \
      --retry-errors \
      --no-plaintext-export
    attempt=$((attempt + 1))
  done
fi

if has_fetch_errors; then
  remaining="$(count_fetch_errors)"
  log "WARNING: ${remaining} book(s) still failed after ${MAX_FETCH_RETRIES} retries. Continuing to Pinecone."
elif [[ $attempt -gt 1 ]]; then
  log "Step 2/4: All previously failed books recovered."
else
  log "Step 2/4: No errors to retry."
fi

# --- Gate: only stop if nothing to push to Pinecone ---
BOOK_FILE_COUNT="$(count_book_files)"
if [[ "$BOOK_FILE_COUNT" -eq 0 ]]; then
  log "ERROR: No book JSON files in output/books after fetch. Nothing to migrate to Pinecone. Exiting."
  exit 1
fi
log "Found ${BOOK_FILE_COUNT} book file(s) ready for Pinecone migration."

# --- Step 3: Prepare chunks (dry run) ---
log "Step 3/4: Preparing Pinecone chunks (dry run)..."
"$VENV_PYTHON" prepare_pinecone_data.py \
  --dry-run

CHUNK_COUNT="$(count_chunks)"
if [[ "$CHUNK_COUNT" -eq 0 ]]; then
  log "ERROR: Dry run produced 0 chunks. Nothing to upload to Pinecone. Exiting."
  exit 1
fi
log "Dry run produced ${CHUNK_COUNT} chunk(s)."

# --- Step 4: Upload to Pinecone ---
log "Step 4/4: Uploading to Pinecone..."
"$VENV_PYTHON" prepare_pinecone_data.py \
  --upload

log "=== Weekly wiki sync completed successfully ==="