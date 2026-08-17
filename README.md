# Fiverr Brain 🧠

An internal RAG-powered chatbot for your Fiverr business. Ask it about your
gigs, pricing, policies, and SOPs — it answers only from your own knowledge
base, shows the exact chunks it used, and says "I don't know" instead of
guessing.

It also onboards a seller profile: a six-step form covering basic information,
bio, skills, gigs with their three pricing packages, portfolio and reviews —
or a screenshot of a Fiverr page, read by a vision model and shown to you for
checking before anything is saved.

Vector store is ChromaDB, running locally and free. The LLM and the vision
model are both Claude (`claude-opus-5` by default, via the Anthropic API).
Embeddings default to a free offline model, because Anthropic has no
embeddings endpoint — OpenAI's is one line away if you want it.

> **Full setup instructions: [`docs/SETUP.md`](docs/SETUP.md).** The sections
> below are the short version plus the operational details worth knowing.

## 1. Setup

```bash
cd fiverr-brain
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Add your Anthropic API key

1. Go to https://console.anthropic.com/settings/keys → "Create Key".
2. Copy the key.
3. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
4. Open `.env` and paste your key after `ANTHROPIC_API_KEY=`.

That is the only key the app needs. An `OPENAI_API_KEY` is required *only* if
you switch `EMBEDDING_PROVIDER` to `openai` (see §6) — Claude handles every
answer and every screenshot either way.

**Never commit or share your real `.env` file or API key.**

## 3. Build the knowledge base index

Knowledge comes from two places now:

| Source | Where | Edited how |
|---|---|---|
| Seller profiles and gigs | `data/fiverr_brain.sqlite3` | In the app, or by screenshot import |
| Policies and SOPs | `kb/policies/`, `kb/sops/` | Hand-written markdown |

`kb/profile_gigs/*_profile.md` is still written on every save, but it is now a
**generated export** — readable and diffable, not read back. Flat markdown
cannot round-trip three pricing packages per gig, repeatable FAQs, individual
reviews, or a per-field `null` from a screenshot.

Coming from the old markdown-only layout? Import it once:

```bash
python scripts/migrate_kb_to_store.py            # preview, writes nothing
python scripts/migrate_kb_to_store.py --apply    # import
```

Then build the index:

```bash
python scripts/reindex.py
```

Re-run it after editing `kb/policies/` or `kb/sops/` by hand, or after changing
the embedding provider. You do **not** need it after saving a profile in the
app — the wizard updates that seller's vectors on its own and leaves everyone
else's alone.

## 4. Run the app

```bash
streamlit run app.py
```

This opens a local web app in your browser (usually `http://localhost:8501`).
It only runs on your machine — it is not on the public internet unless you
deploy it separately (e.g. Streamlit Community Cloud).

## 5. Modes

Use the sidebar to switch modes:
- **👤 Profile onboarding** — the six-step form. A draft is saved on every step
  change, so closing the tab costs nothing
- **🖼️ Import from screenshot** — drop in a Fiverr profile or gig screenshot;
  it is read by a vision model, shown to you for checking, and pre-fills the
  onboarding form. Nothing is saved until you confirm
- **Ask a question** — general Q&A grounded in your KB, with the source chunks
  shown under each answer
- **/new-gig** — drafts a new gig listing in your existing style
- **/optimize** — suggests improvements to an existing gig
- **/onboarding** — walks a new hire through your SOPs
- **/buyer-reply** — drafts a reply to a buyer message

With more than one seller stored, a picker appears in the sidebar. Every answer
is then grounded in that seller's own profile only — policies and SOPs stay
shared, because they belong to the business rather than to one seller.

## 6. Updating knowledge over time

- Add/edit `.md` files in `kb/`, then re-run `python scripts/reindex.py`.
- `/new-gig` drafts can be saved directly back into `kb/profile_gigs/` and
  the index rebuilt automatically (see `src/modes/new_gig.save_and_reindex`).
- Questions with no matching KB content are logged to `logs/query_log.jsonl`
  with `"unanswered": true`, and shown in the sidebar under **Knowledge gaps** —
  review these periodically to see what's missing from your knowledge base.

### Embeddings: which provider, and what it costs

Anthropic has no embeddings endpoint, so this is a separate decision from the
model that writes answers. `EMBEDDING_PROVIDER` in `.env` picks one of two:

| | `local` (default) | `openai` |
|---|---|---|
| Model | `all-MiniLM-L6-v2` | `text-embedding-3-small` |
| Second API key | None | `OPENAI_API_KEY` |
| Non-English questions | Poor — 4/7 on a cross-language test of this KB | Handled well |
| Cost | Free | Per query **and** per reindex |
| Network | None | Required |
| Memory | ~400 MB of torch + weights | Negligible |

`local` is the default because it keeps the app to a single vendor and a single
key, and it is what the committed index and the test suite both run on. Switch
to `openai` if non-English retrieval matters more than the second key — that
weakness is real and measured.

**Reindex after changing this** — `python scripts/reindex.py`. A mismatch
produces no error; retrieval just silently returns nothing. The app stamps the
model and provider onto the collection and shows a warning banner when they
disagree with the current settings.

### The relevance threshold is not optional

"Is this chunk actually relevant?" is decided by `MAX_DISTANCE`, and it is what
makes "I don't know" possible at all. It is calibrated **per provider and per
knowledge base**:

- The `local` default (1.49) — the one in force out of the box — was measured
  against the shipped KB.
- The `openai` default (1.35) is an **estimate**. It has never been measured
  against a real index. The app says so in a banner until you set it yourself.

```bash
python scripts/check_threshold.py
```

It prints the distances for questions the KB *should* and *should not* answer,
suggests a threshold in the gap, and tells you the `.env` line to add. Re-run it
after adding a lot of content. Too high → the bot answers off-topic questions
from irrelevant chunks. Too low → it says "I don't know" to real questions.

## 7. Deploying to Streamlit Community Cloud

1. Push to GitHub (the prebuilt index in `data/chroma_db/` is committed, so the
   deployed app has a working index immediately).
2. On share.streamlit.io → **New app** → pick the repo, main file `app.py`.
3. **Advanced settings → Secrets**, paste:
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   ANTHROPIC_MODEL = "claude-opus-5"
   ```
4. **Advanced settings → Python version**: pin it (3.12 is a safe choice).
   Leaving it unset means a platform default change can break the `torch` install.
5. **Settings → Sharing**: set to "Anyone with the link", otherwise everyone you
   share the URL with just sees a Streamlit login page.

### Known limits of the free tier

- **The filesystem is ephemeral.** "Rebuild index" works for the current
  session, but the container resets to whatever is in git on restart. This now
  includes **the profile database** — which matters a great deal for a feature
  whose whole job is saving a profile. The app warns on every save. For a
  permanent change: do the work locally, then commit
  `data/fiverr_brain.sqlite3`, `data/chroma_db/` and `kb/`, and push.
- Same for `logs/query_log.jsonl` and onboarding progress — they reset too.
- ~1 GB RAM. The embedding model is shared process-wide (`rag.get_embed_model`),
  so don't reintroduce a per-session `SentenceTransformer(...)`.

## 8. Tests

```bash
pip install pytest
python -m pytest tests/ -q
```

228 tests. The original 57 each map to a bug that was actually present in the
app: relevance thresholding, follow-up vs topic-change retrieval, mode return
contracts, prompt-injection fencing, API error handling, atomic reindexing,
concurrent rebuild locking, embedding-model/index mismatch, path traversal and
log robustness. The rest cover the profile schema and its SQLite round trip,
document splitting and per-seller upsert, seller isolation, citations, the
onboarding form's coercion and drafts, the KB migration, and the screenshot
import — upload validation, EXIF stripping, schema binding, confidence and
merging.

**No test spends money.** The chat model and the vision model are both stubbed,
and `tests/conftest.py` forces embeddings onto the local provider. No test
writes to the real profile database, query log or `kb/` folder either — they
are redirected to a temp directory. Run the suite before every deploy.

## Ground rules

- Internal tool only — not for public/buyer-facing use.
- Do not scrape Fiverr in violation of their Terms of Service.
- Never store passwords or payment data in the KB or logs.
- A human should always review `/new-gig` and `/buyer-reply` output before
  actually publishing or sending it.
