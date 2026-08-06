# Fiverr Brain — Build Checklist (Free Stack)

## Phase 1 — Knowledge Base
- [x] Layer 1: Profile & gigs (real data — 3 gigs + seller profile)
- [x] Layer 2: Policy summaries (seller fees verified via web search; general conduct is a placeholder — needs official verification)
- [x] Layer 3: Internal SOPs (placeholders — replace with real workflows when ready)

## Phase 2 — RAG Engine
- [x] `config.py` — central settings, reads `.env`, no hardcoded secrets
- [x] `ingest.py` — frontmatter parsing, chunking, local embeddings, ChromaDB storage
- [x] `rag.py` — retrieval + Gemini-grounded answers + citations + "I don't know" refusal + session memory
- [x] `logging_utils.py` — per-query logging + unanswered-question capture

## Phase 3 — Guided Modes
- [x] `/new-gig` — drafts new gig in existing style, can save + reindex
- [x] `/optimize` — suggests improvements to an existing gig
- [x] `/onboarding` — SQLite-tracked SOP walkthrough
- [x] `/buyer-reply` — drafts buyer replies grounded in gigs/policies/SOPs

## Phase 4 — Knowledge Loop
- [x] `scripts/reindex.py` — rebuild index after KB changes
- [x] `/new-gig` auto-saves drafts back into `kb/profile_gigs/`

## Testing (done without a live Gemini key — logic only)
- [x] Frontmatter parsing across all 8 real KB files
- [x] Chunking logic
- [x] ChromaDB storage + retrieval + layer metadata filtering (verified: 4 profile_gigs, 2 policies, 2 sops)
- [x] Full ingest pipeline end-to-end (with mocked embeddings)
- [x] RAG retrieval + prompt construction + session history (with mocked Gemini)
- [x] Onboarding SQLite progress tracking
- [x] Query logging + unanswered-question flagging
- [ ] **Not yet tested: live Gemini API calls** — needs your real, valid API key (the one pasted in chat did not look like a standard Gemini key format — please verify/regenerate)
- [ ] Streamlit app boot test (not yet run in this environment)

## Docs
- [x] README.md (setup guide)
- [x] This checklist

## Still needs YOUR input
- [ ] Replace placeholder general-conduct policy with officially verified Fiverr ToS wording
- [ ] Replace placeholder SOPs with your real workflows
- [ ] Provide a valid Gemini API key in your local `.env` (never in chat)
- [ ] Decide: stay local-only for now, or deploy later (e.g. Streamlit Community Cloud) for your boss to access via a link

---

## Phase 5 — Profile onboarding + screenshot OCR import

Built against `docs/00_BRIEF.md`, following `docs/02_IMPLEMENTATION_PLAN.md`
(Option A: Python, extending this repo rather than rewriting in TypeScript).

### Stage (a) — Schema and data layer
- [x] `src/schema.py` — one pydantic definition driving the form, the OCR
      extractor and the database. All six sections. Every field nullable so a
      screenshot or a draft can be represented honestly
- [x] `src/store.py` — SQLite: `sellers`, `gigs`, `packages`, `gig_faqs`,
      `portfolio_items`, `reviews`, `review_summary`, `drafts`. Prisma-shaped,
      foreign keys with cascade, every write in one transaction
- [x] `scripts/migrate_kb_to_store.py` — one-time import of the old
      `kb/profile_gigs/` markdown, including the free-text and table pricing
      formats. Dry run by default; renames rather than deletes
- [x] `requirements.txt` — `pydantic` and `Pillow` promoted to declared pins

### Stage (b) — Six-step onboarding form
- [x] Six numbered steps with a progress indicator
- [x] Per-step validation that blocks advancing
- [x] Save-as-draft on every step change, resumable after a browser close
- [x] Basic info: name, username, photo URL, country, languages, member since,
      average response time, headline, level
- [x] Gigs: three structured packages (name, price, currency, delivery days,
      revisions, features), extras, repeatable FAQs
- [x] Portfolio and reviews (with star breakdown) — both new
- [x] Multi-seller: a seller picker, and delete with vector cleanup

### Stage (c) — Embedding and vector pipeline
- [x] `src/documents.py` — one document per logical unit (bio, each gig, each
      portfolio item, a reviews digest) carrying `sellerId`, `sectionType`,
      `gigId`, `sourceType`
- [x] ~400-token chunks with ~50 overlap (word-approximated, no new dependency)
- [x] `EMBEDDING_PROVIDER` switch; `text-embedding-3-small` is the default,
      local MiniLM stays a one-line fallback
- [x] Per-seller upsert — re-onboarding replaces that seller's vectors and
      leaves every other seller, and the shared policy/SOP layers, untouched
- [x] `MAX_DISTANCE` re-measured for the **local** provider against the new
      chunking and document structure — all 11 cases classify correctly, 1.49
      confirmed (suggested 1.50)
- [ ] **`MAX_DISTANCE` re-tuned for the OpenAI embeddings** — blocked, no API
      key available. `scripts/check_threshold.py` prints the value to use; the
      app shows a banner until it is set

### Stage (d) — Retrieval in the chat endpoint
- [x] `TOP_K = 5`
- [x] Retrieval filtered by seller, with policies and SOPs still shared
- [x] `ask()` returns the source chunks, not just filenames
- [x] Citations rendered in the UI as expandable chunks

### Stage (e) — Screenshot OCR import
- [x] Upload area: images only, 10 MB cap, EXIF stripped by re-encoding
- [x] OpenAI vision model, image sent as base64
- [x] Reply bound to `SellerProfile.model_json_schema()` in strict mode
- [x] Prompt requires `null` for anything not visible; inventing forbidden
- [x] Editable review screen before anything is saved
- [x] Low-confidence extractions reported, with the manual form offered instead
- [x] Merge into an existing profile without erasing what the screenshot missed
- [x] Writes through the same store and the same index path as the form

### Docs and tests
- [x] `docs/SETUP.md`
- [x] README updated
- [x] 212 tests, none of which spends money

### Still needs YOUR input
- [x] Migration run: profile + 3 gigs (9 packages, PKR) imported; sources
      renamed to `*.md.imported`; index rebuilt to 8 chunks at schema version 2
- [ ] Add `OPENAI_API_KEY` to `.env`, then `python scripts/reindex.py`
- [ ] Run `python scripts/check_threshold.py` and set `MAX_DISTANCE` for OpenAI
- [ ] Test the screenshot import against a real Fiverr screenshot
