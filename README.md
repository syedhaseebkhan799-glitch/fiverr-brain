# Fiverr Brain 🧠

An internal RAG-powered chatbot for your Fiverr business. Ask it about your
gigs, pricing, policies, and SOPs — it answers only from your own knowledge
base, cites its sources, and says "I don't know" instead of guessing.

Built cheap: local embeddings (sentence-transformers, free), local vector
store (ChromaDB, free), and OpenAI `gpt-4o-mini` for the LLM (paid, but
fractions of a cent per question).

## 1. Setup

```bash
cd fiverr-brain
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Add your OpenAI API key

1. Go to https://platform.openai.com/api-keys → "Create new secret key".
2. Copy the key.
3. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
4. Open `.env` and paste your key after `OPENAI_API_KEY=`.

**Never commit or share your real `.env` file or API key.**

## 3. Build the knowledge base index

Your gigs, policies, and SOPs live as markdown files under `kb/`:
- `kb/profile_gigs/` — your gigs and seller profile
- `kb/policies/` — Fiverr policy summaries
- `kb/sops/` — your internal workflows

Edit/add `.md` files there, then build (or rebuild) the index:

```bash
python scripts/reindex.py
```

Run this again any time you change files in `kb/`.

## 4. Run the app

```bash
streamlit run app.py
```

This opens a local web app in your browser (usually `http://localhost:8501`).
It only runs on your machine — it is not on the public internet unless you
deploy it separately (e.g. Streamlit Community Cloud).

## 5. Modes

Use the sidebar to switch modes:
- **Ask a question** — general Q&A grounded in your KB
- **/new-gig** — drafts a new gig listing in your existing style
- **/optimize** — suggests improvements to an existing gig
- **/onboarding** — walks a new hire through your SOPs
- **/buyer-reply** — drafts a reply to a buyer message

## 6. Updating knowledge over time

- Add/edit `.md` files in `kb/`, then re-run `python scripts/reindex.py`.
- `/new-gig` drafts can be saved directly back into `kb/profile_gigs/` and
  the index rebuilt automatically (see `src/modes/new_gig.save_and_reindex`).
- Questions with no matching KB content are logged to `logs/query_log.jsonl`
  with `"unanswered": true`, and shown in the sidebar under **Knowledge gaps** —
  review these periodically to see what's missing from your knowledge base.

### Non-English buyer messages

The default embedding model (`all-MiniLM-L6-v2`) is English-only, so retrieval
degrades on other languages. Measured on this KB (7 cross-language queries):

| Model | Correct hits | Weights | Load time |
|---|---|---|---|
| `all-MiniLM-L6-v2` (default) | 4/7 | ~91 MB | ~15 s |
| `paraphrase-multilingual-MiniLM-L12-v2` | 5/7 | ~471 MB | ~55 s |

One extra hit for 5x the memory. On Streamlit Cloud's ~1 GB container that
risks an out-of-memory crash, so the English model stays the default. To switch
anyway (e.g. running locally with plenty of RAM):

```bash
# in .env
EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2
```

**You must reindex after changing this** — `python scripts/reindex.py`. Both
models are 384-dimensional, so a mismatch produces no error; retrieval just
silently returns nothing. The app detects this and shows a warning banner.

### Re-tune the relevance threshold after big KB changes

"Is this chunk actually relevant?" is decided by `config.MAX_DISTANCE`. It is
calibrated to the current KB. After adding a lot of content, re-check it:

```bash
python scripts/check_threshold.py
```

It prints the distances for questions the KB *should* and *should not* answer,
and suggests a new threshold. Too high → the bot answers off-topic questions
from irrelevant chunks. Too low → it says "I don't know" to real questions.

## 7. Deploying to Streamlit Community Cloud

1. Push to GitHub (the prebuilt index in `data/chroma_db/` is committed, so the
   deployed app has a working index immediately).
2. On share.streamlit.io → **New app** → pick the repo, main file `app.py`.
3. **Advanced settings → Secrets**, paste:
   ```toml
   OPENAI_API_KEY = "sk-..."
   OPENAI_MODEL = "gpt-4o-mini"
   ```
4. **Advanced settings → Python version**: pin it (3.12 is a safe choice).
   Leaving it unset means a platform default change can break the `torch` install.
5. **Settings → Sharing**: set to "Anyone with the link", otherwise everyone you
   share the URL with just sees a Streamlit login page.

### Known limits of the free tier

- **The filesystem is ephemeral.** "Rebuild index" works for the current
  session, but the container resets to whatever is in git on restart. For a
  permanent KB change: edit `kb/`, run `python scripts/reindex.py` locally,
  commit `data/chroma_db/`, and push.
- Same for `logs/query_log.jsonl` and onboarding progress — they reset too.
- ~1 GB RAM. The embedding model is shared process-wide (`rag.get_embed_model`),
  so don't reintroduce a per-session `SentenceTransformer(...)`.

## 8. Tests

```bash
pip install pytest
python -m pytest tests/ -q
```

57 tests, each mapped to a bug that was actually present in the app: relevance
thresholding, follow-up vs topic-change retrieval, mode return contracts,
prompt-injection fencing, OpenAI error handling, atomic reindexing, concurrent
rebuild locking, embedding-model/index mismatch, path traversal, and log
robustness. **No test calls the OpenAI API** — the LLM is stubbed, so the suite
is free to run. Run it before every deploy.

## Ground rules

- Internal tool only — not for public/buyer-facing use.
- Do not scrape Fiverr in violation of their Terms of Service.
- Never store passwords or payment data in the KB or logs.
- A human should always review `/new-gig` and `/buyer-reply` output before
  actually publishing or sending it.
