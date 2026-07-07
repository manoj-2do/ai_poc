# neo-wiki-scripts

Scripts to fetch TravClan BookStack wiki content and prepare it for Pinecone.

## Setup

```bash
pip install -r requirements.txt
```

## Step 1 — Fetch wiki data

Script: `fetch_wiki_data.py`

**List all books and shelves (index only):**

```bash
python fetch_wiki_data.py
```

**Fetch all books (full page content):**

```bash
python fetch_wiki_data.py --all-books --no-plaintext-export
```

**Resume interrupted fetch:**

```bash
python fetch_wiki_data.py --all-books --no-plaintext-export --skip-existing
```

**Retry failed books from `output/books_full.json`:**

```bash
python fetch_wiki_data.py --retry-errors --no-plaintext-export
```

**Single book:**

```bash
python fetch_wiki_data.py --book-id 151
```

**Multiple books:**

```bash
python fetch_wiki_data.py --book-id 151,152,153
```

**All books on a shelf:**

```bash
python fetch_wiki_data.py --shelf-keywords learning development --no-plaintext-export
```

**Output:** `output/books/book_{id}_{slug}.json`

---

## Step 2 — Prepare Pinecone data

Script: `prepare_pinecone_data.py`

**Dry run — all books → local JSONL (default, no Pinecone upload):**

```bash
python prepare_pinecone_data.py --all-books --dry-run
```

**Same as above (`--dry-run` is the default):**

```bash
python prepare_pinecone_data.py --all-books
```

**Only L&D shelf books:**

```bash
python prepare_pinecone_data.py --shelf-keywords learning development --dry-run
```

**Specific book IDs:**

```bash
python prepare_pinecone_data.py --book-id 151,152 --dry-run
```

**Override chunk settings (optional; otherwise uses `PINECONE_CHUNK_SIZE` / `PINECONE_CHUNK_OVERLAP` from `.env`):**

```bash
python prepare_pinecone_data.py --all-books --chunk-size 1500 --chunk-overlap 200 --dry-run
```

**Output:**

- `output/pinecone/chunks.jsonl` — one Pinecone record per line
- `output/pinecone/manifest.json` — stats, category breakdown, destination book IDs

---

## Step 3 — Upload to Pinecone

Review `output/pinecone/chunks.jsonl`, then:

```bash
python prepare_pinecone_data.py --all-books --upload
```

Requires `PINECONE_API_KEY`, `PINECONE_HOST`, `OPENAI_API_KEY`, `EMBEDDING_MODEL`, and `EMBEDDING_DIMENSIONS` in `.env`.

Your Pinecone index must be created with the same dimension as `EMBEDDING_DIMENSIONS` (e.g. `512` for `text-embedding-3-small`).

---

## Step 4 — Test vector search / chat

Script: `wiki_chat.py`

**Interactive chat (search + LLM answer):**

```bash
python wiki_chat.py
```

**Search-only mode (test Pinecone without LLM):**

```bash
python wiki_chat.py --search-only
```

**Single query test (non-interactive):**

```bash
python wiki_chat.py --search-only --query "What is user onboarding?"
```

**Filter to one book:**

```bash
python wiki_chat.py --book-id 2
python wiki_chat.py --search-only --book-id 2 --query "KYC process"
```

**Filter by category:**

```bash
python wiki_chat.py --category destinations
```

**Disable router (always vector search):**

```bash
python wiki_chat.py --no-router
```

**Show router decisions:**

```bash
python wiki_chat.py --verbose
```

### In-chat commands

| Command | Action |
|---------|--------|
| `/search <query>` | Vector search only, show scores + sources |
| `/filter category=internal` | Limit search to a category |
| `/filter book_id=2` | Limit search to one book |
| `/filter clear` | Remove filters |
| `/help` | Show commands |
| `/quit` | Exit |

**Query router:** Before vector search, a classifier decides if the message is a wiki question or something like a greeting/off-topic chat. Use `--verbose` to see routing decisions. Use `--no-router` to always search.

---

## Full workflow

```bash
# 1. Fetch wiki
python fetch_wiki_data.py --all-books --no-plaintext-export --skip-existing

# 2. Prepare chunks locally
python prepare_pinecone_data.py --all-books --dry-run

# 3. Review output/pinecone/chunks.jsonl, then upload
python prepare_pinecone_data.py --all-books --upload
```

---

## Pinecone storage

All vectors are upserted to the **default Pinecone namespace**. Use the `category` metadata field to filter at query time:

| Category | Contents |
|----------|----------|
| `destinations` | L&D shelf books (Dubai, Singapore, Flights, etc.) — detected via `DESTINATIONS_SHELF_KEYWORDS` |
| `operations` | Bookings, refunds, finance, post-booking ops |
| `product` | Portal, CMS, API, website tooling |
| `internal` | HR, onboarding, policies |
| `general` | Everything else |

## Metadata filters

Each chunk includes: `category`, `book_id`, `book_name`, `chapter_name`, `page_id`, `page_name`, `page_url`, `has_images`, `image_urls`, `chunk_index`, `total_chunks`, `updated_at`.

Example Pinecone filter:

```python
{"category": "destinations", "book_id": 151}
```

Example to pull failed IDs from books_full.json and pass them with --book-id:

```bash
python -c "
import json
data = json.load(open('output/books_full.json'))
print(','.join(str(e['book_id']) for e in data.get('errors', [])))
"
```

Then:
```bash
python fetch_wiki_data.py --book-id id1,id2,id3 --no-plaintext-export
```

Retry Errors
```bash
python fetch_wiki_data.py --retry-errors --no-plaintext-export
```

```bash
crontab -e
Opens an editor, there you need to add the command {{CRON_JOB_TIME}} {{FILE TO EXECUTE}}

example: 0 2 * * 3 /home/admin/manoj/wiki-scripts/wiki_sync.sh

Verify if it's added
crontab -l

To remove all cron jobs for your user
crontab -r


If a run is already in progress
Stopping cron does not stop a script that's already running. To stop that:

# Find the running process
ps aux | grep wiki_sync

# Kill it (use the PID from the output)
kill <PID>

#If it won't stop:
kill -9 <PID>
```