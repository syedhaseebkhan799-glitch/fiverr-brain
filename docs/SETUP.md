# Fiverr Brain — Setup

Everything needed to run the app from a clean checkout, in the order it has to
happen.

---

## 1. Install

```bash
cd fiverr-brain
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Python 3.12 or newer. On Streamlit Community Cloud, pin the Python version in
**Advanced settings** — leaving it unset means a platform default change can
break the `torch` install.

---

## 2. Environment variables

Copy the template and fill in your key:

```bash
cp .env.example .env
```

| Variable | Required | Default | What it does |
|---|---|---|---|
| `OPENAI_API_KEY` | **Yes** | — | Chat, screenshot reading, and (on the default provider) embeddings. The app refuses to start without it. |
| `OPENAI_MODEL` | No | `gpt-4o-mini` | The model that writes answers. |
| `VISION_MODEL` | No | `gpt-4o-mini` | Reads uploaded screenshots. Must support vision. |
| `EMBEDDING_PROVIDER` | No | `openai` | `openai` or `local`. See §3. |
| `EMBEDDING_MODEL` | No | per provider | `text-embedding-3-small` for openai, `all-MiniLM-L6-v2` for local. |
| `MAX_DISTANCE` | No | per provider | The relevance cut-off. See §5 — **you should set this**. |

The key never reaches the browser. Streamlit executes entirely server-side, and
both `.env` and `.streamlit/secrets.toml` are gitignored.

Get a key at <https://platform.openai.com/api-keys>. Never commit it.

---

## 3. Choose an embedding provider

| | `openai` (default) | `local` |
|---|---|---|
| Model | `text-embedding-3-small` | `all-MiniLM-L6-v2` |
| Retrieval quality | Better, and handles non-English questions | Weaker outside English |
| Cost | Per query **and** per reindex | Free |
| Network | Required | None — fully offline |
| Memory | Negligible | ~400 MB of torch + weights |

Set it in `.env`:

```bash
EMBEDDING_PROVIDER=openai   # or: local
```

**Changing this invalidates the index.** The two models put their vectors in
different spaces, and a mismatch produces no error — retrieval just silently
returns nothing. The app detects the mismatch on startup and shows a banner, but
the fix is always the same: rebuild (§4).

---

## 4. Load your data and build the index

### If you have an existing `kb/profile_gigs/` from before the SQLite change

Profiles now live in `data/fiverr_brain.sqlite3`. Import the old markdown once:

```bash
python scripts/migrate_kb_to_store.py            # preview — writes nothing
python scripts/migrate_kb_to_store.py --apply    # import
```

It prints what it found before touching anything. After a successful import the
source files are renamed to `*.md.imported` so the same content is not indexed
twice. **Nothing is deleted**, and `--keep-files` skips the rename.

`kb/policies/` and `kb/sops/` are unaffected — they are still hand-written
markdown and should stay that way.

### Build the index

```bash
python scripts/reindex.py
```

This reads every markdown file under `kb/` **and** every seller in the profile
database, and rebuilds the whole collection. Run it after:

- changing `EMBEDDING_PROVIDER` or `EMBEDDING_MODEL`
- editing files in `kb/policies/` or `kb/sops/` by hand
- the migration above

You do **not** need it after saving a profile in the app — the wizard updates
that seller's vectors on its own, and leaves everyone else's alone.

---

## 5. Calibrate the relevance threshold

`MAX_DISTANCE` is the distance above which a retrieved chunk is thrown away. It
is the single value that lets the app say "I don't know" instead of answering
from whatever happened to be nearest.

It is calibrated per provider **and** per knowledge base:

- The built-in `local` value (1.49) was measured against the shipped KB.
- The built-in `openai` value (1.35) is an **estimate**. It has not been
  measured against a real index, and the app says so in a banner until you set
  `MAX_DISTANCE` yourself.

Measure it:

```bash
python scripts/check_threshold.py
```

It prints the retrieval distance for questions the KB *should* answer and for
questions it *should not*, then suggests a threshold in the gap. Put that in
`.env`:

```bash
MAX_DISTANCE=1.28
```

Re-run it after adding a lot of content. Too high and the bot answers off-topic
questions from irrelevant chunks; too low and it refuses real ones.

> On the `openai` provider this makes one paid embedding call per test question
> — about a dozen, so fractions of a cent.

---

## 6. Run

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`. It runs only on your machine unless you deploy
it (§8).

---

## 7. First run in the app

1. **👤 Profile onboarding** — six steps: basic information, bio, skills, gigs
   (with Basic/Standard/Premium packages, extras and FAQs), portfolio, reviews.
   A draft is saved on every step change, so closing the tab costs nothing.
   Press **Save profile & index** at the end.
2. **🖼️ Import from screenshot** — optional shortcut. Drop in a screenshot of
   your Fiverr profile or a gig page; it is read, shown to you for checking, and
   pre-fills the onboarding form. Nothing is saved until you confirm.
3. **Ask a question** — and the other four modes.

---

## 8. Deploying to Streamlit Community Cloud

1. Push to GitHub. `data/chroma_db/` is committed, so the deployed app has a
   working index immediately.
2. share.streamlit.io → **New app** → pick the repo, main file `app.py`.
3. **Advanced settings → Secrets**:
   ```toml
   OPENAI_API_KEY = "sk-..."
   OPENAI_MODEL = "gpt-4o-mini"
   EMBEDDING_PROVIDER = "openai"
   MAX_DISTANCE = "1.28"
   ```
4. **Advanced settings → Python version**: pin it.
5. **Settings → Sharing**: "Anyone with the link", or people just see a login page.

### The filesystem there is ephemeral

Anything written at runtime is lost when the container restarts. That includes
**the profile database**, which matters a great deal for a feature whose whole
job is saving a profile. The app warns about this on every save.

To make a profile permanent: do the onboarding locally, then commit
`data/fiverr_brain.sqlite3`, `data/chroma_db/` and `kb/`, and push.

Also ephemeral: `logs/query_log.jsonl` and onboarding progress.

---

## 9. Tests

```bash
pip install pytest
python -m pytest tests/ -q
```

210 tests. **None of them costs money** — the chat model and the vision model
are both stubbed, and embeddings are forced onto the local provider in
`tests/conftest.py`. No test writes to the real profile database, query log or
`kb/` folder either; they are all redirected to a temp directory.

| File | Covers |
|---|---|
| `tests/test_fiverr_brain.py` | Retrieval, thresholding, follow-ups, mode contracts, injection fencing, error handling, atomic reindex, seller isolation, citations |
| `tests/test_schema.py` | Validation per step, nullability on the OCR path, the strict JSON schema, SQLite round trip, drafts |
| `tests/test_documents.py` | Document splitting, metadata, per-seller upsert and replacement |
| `tests/test_profile_setup.py` | Form coercion, saving, exports, status, drafts, the KB migration |
| `tests/test_ocr.py` | Upload validation, EXIF stripping, schema binding, confidence, merging |
| `tests/test_app_smoke.py` | Runs `app.py` through Streamlit's own harness: every mode renders, every wizard step draws, the import review screen works |

---

## 10. Where things live

| Path | What |
|---|---|
| `data/fiverr_brain.sqlite3` | Seller profiles — the source of truth |
| `data/chroma_db/` | The vector index (committed, so deploys work immediately) |
| `kb/policies/`, `kb/sops/` | Hand-written markdown, still the source of truth for those layers |
| `kb/profile_gigs/*_profile.md` | **Generated export.** Readable and diffable, but edits are not read back |
| `logs/query_log.jsonl` | Every question, with unanswered ones flagged |
| `.env` | Your key. Gitignored. |
