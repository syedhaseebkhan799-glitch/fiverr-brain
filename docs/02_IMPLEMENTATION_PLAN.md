# Fiverr Brain — Implementation Plan: Profile Onboarding + Screenshot OCR Import

**Date:** 2026-08-06
**Status:** 🔴 **Awaiting approval — no code will be written until §1–§3 are answered.**
**Read first:** `docs/01_REPO_AUDIT.md`

---

## 1. The one blocking decision: which stack

The brief says *"follow the existing structure … do not introduce a new framework"* and also *"TypeScript throughout … Zod … Postgres via Prisma."* This repository is Python/Streamlit. Both cannot be honoured.

| | **Option A — build in Python (recommended)** | **Option B — rewrite in TypeScript/Next.js** |
|---|---|---|
| Honours | "do not introduce a new framework or restructure what already exists" | "TypeScript throughout, Zod, Prisma" |
| Reuses | All 2,718 existing lines, 57 passing tests, the tuned retrieval logic, the deployed Streamlit app | Nothing — Python cannot be imported from Node |
| Zod equivalent | `pydantic` v2 — same job: one schema drives form, OCR parsing and the DB layer | Zod itself |
| Prisma/Postgres equivalent | SQLite now, same table shapes, Postgres later via a connection string | Prisma + Postgres directly |
| Effort | ~5 stages as below | The 5 stages **plus** re-implementing chat, retrieval, ingestion, the 3 existing modes, the guardrails and the test suite |
| Risk | Low — extends working code | High — the "I don't know" behaviour, the injection fencing and the distance threshold all have to be rebuilt and re-tuned from scratch |

**Recommendation: Option A.** The instruction not to introduce a new framework is the one written specifically about *this* repository; the TypeScript/Prisma lines sit next to three unfilled `<>` placeholders and read as un-customised template boilerplate. Every functional requirement in the brief — one shared schema, server-side keys, per-seller namespacing, vision OCR, citations — is fully achievable in Python. Option B delivers the same features and throws away a working, tested application to do it.

**The rest of this plan assumes Option A.** If the boss confirms Option B, this document is void and a separate plan is needed — say so and it will be rewritten.

---

## 2. Three further decisions

### 2.1 Where profile data lives

The brief's placeholder says `<e.g. Postgres via Prisma>`. The current design stores everything as markdown in `kb/`, and `src/profile_setup.py` deliberately made markdown the single source of truth so a hand-edited file and a UI-built one are identical.

**That design cannot carry the required schema.** Flat `## Heading` markdown cannot reliably round-trip three pricing packages per gig (each with name, price, delivery days, revisions and a feature list), repeatable FAQs, portfolio items and individual reviews with star ratings. Nor can it hold a half-finished draft, which "save-as-draft between steps" requires, or a per-field `null` from an OCR run.

**Recommendation:** a **SQLite** database at `data/fiverr_brain.sqlite3`, with tables shaped exactly as the Prisma models would be — `sellers`, `gigs`, `packages`, `gig_faqs`, `portfolio_items`, `reviews`, `review_summary`, `drafts`. SQLite is in the Python standard library (no new dependency), the repo already uses it for onboarding progress, and moving to Postgres later is a driver swap rather than a redesign.

`kb/` markdown stays, but changes role: it becomes a **generated export** for human review and for the policies/SOPs layers, which are still hand-written files and should remain so. A one-time migration script imports the four existing `kb/profile_gigs/` files into the database so nothing is lost.

**Trade-off, stated plainly:** editing a profile by hand in a text editor stops being a supported workflow. Everything goes through the wizard or the OCR import. If the boss wants hand-editing kept, say so — the alternative is a JSON-per-seller file store, which keeps files editable but gives up queryability and the "same tables" wording in the brief.

### 2.2 The embedding model change is not free

The brief specifies `text-embedding-3-small`. The app currently embeds locally with MiniLM at zero cost and zero network dependency. Switching means:

- A full index rebuild (mandatory — the app detects the mismatch and warns, but retrieval returns nothing until it is done).
- **Re-tuning `MAX_DISTANCE`.** It is currently `1.49`, measured against MiniLM on this specific KB. OpenAI embeddings use a different distance scale, so the "I don't know" refusal — the core safety property of this tool — will misbehave until `scripts/check_threshold.py` is re-run. This is budgeted as explicit work in stage (c), not an afterthought.
- Ongoing API cost on every query and every reindex, where there was none.
- The 57-test suite currently calls the real embedder. It would need embeddings stubbed, or the suite starts costing money per run.

**Recommendation: follow the brief and switch**, because `text-embedding-3-small` is genuinely better and fixes the documented non-English retrieval weakness (README §6) — but implement it behind `config.EMBEDDING_PROVIDER` so local MiniLM stays a one-line fallback, and treat the threshold re-tune as a required deliverable of that stage.

### 2.3 Chunking: exact tokens or approximate

The brief says ~400 tokens with ~50 overlap. The current chunker counts **words** (800/150).

- **Approximate (recommended, no new dependency):** 300 words ≈ 400 tokens, 38 words overlap. Accurate to within ~10% for English prose.
- **Exact:** add `tiktoken`. One new dependency for precision that does not change retrieval quality meaningfully.

---

## 3. Dependency approval

The brief asks to be consulted before adding any dependency. The honest position:

| Package | Version installed | Currently | Ask |
|---|---|---|---|
| `pydantic` | 2.13.4 | Present transitively via `chromadb`, **not declared** | Promote to a pinned line in `requirements.txt` — it becomes the Zod equivalent and load-bearing |
| `Pillow` | 12.3.0 | Present transitively via `streamlit`, **not declared** | Promote to a pinned line — needed for image validation and EXIF stripping |
| `tiktoken` | not installed | — | Only if §2.3 chooses exact token counting. **Recommend skipping** |

**No genuinely new package is required.** Two already-installed ones need declaring, which is being raised rather than done quietly.

---

## 4. Build order and file list

Five stages, in the order the brief specifies, **stopping after each one for testing.**

### Stage (a) — Schema and data layer

The foundation. One schema definition that the form, the OCR extractor and the database all read from.

| File | Action | Contents |
|---|---|---|
| `src/schema.py` | **new** | Pydantic v2 models: `BasicInfo`, `About`, `Skills`, `Package`, `FAQ`, `Gig`, `PortfolioItem`, `Review`, `ReviewSummary`, `SellerProfile`. All six sections. Field-level constraints carrying the real Fiverr limits (600-char bio, 30 skills). Every field on the OCR path optional/nullable. `SellerProfile.model_json_schema()` is what gets handed to the vision model, so the schema literally cannot drift from the extractor |
| `src/store.py` | **new** | SQLite layer: `init_db`, `save_seller`, `load_seller`, `list_sellers`, `delete_seller`, `save_draft`, `load_draft`, `clear_draft`. Writes wrapped in a transaction so a re-onboard replaces a seller atomically |
| `scripts/migrate_kb_to_store.py` | **new** | One-time import of the 4 existing `kb/profile_gigs/*.md` files into the database, reusing `profile_setup.parse_profile_md` / `parse_gig_md` so nothing is lost |
| `src/config.py` | change | Add `PROFILE_DB` path, `MAX_UPLOAD_BYTES = 10 * 1024 * 1024`, `EMBEDDING_PROVIDER` |
| `tests/test_schema.py` | **new** | Validation boundaries, nullable-on-OCR-path behaviour, round-trip through the store |
| `requirements.txt` | change | Pin `pydantic`, `Pillow` (pending §3) |

**Stop. Testable:** `python scripts/migrate_kb_to_store.py` then inspect the database; `pytest tests/test_schema.py`.

### Stage (b) — Six-step onboarding form

Rework the existing wizard rather than replace it — the `Field` abstraction, the validation helpers, the reindex-before-reporting-success discipline and the path-safety rules in `profile_setup.py` all carry over.

| File | Action | Contents |
|---|---|---|
| `src/profile_setup.py` | **major change** | Field definitions regrouped into the six required sections; add the missing fields (username, profile photo URL, country, member since, average response time, tests); gig packages become three structured `Package` objects instead of one free-text box; add gig FAQs, portfolio, reviews. Reads/writes via `store.py`; markdown becomes a generated export |
| `src/profile_ui.py` | **major change** | Six numbered steps with next/back, a step progress indicator, per-step validation blocking advance, and **save-as-draft on every step transition** via `store.save_draft` |
| `app.py` | change | Wire the reworked wizard; add a seller selector when more than one seller exists |
| `tests/test_profile_setup.py` | **new** | Per-step validation, draft save/resume, the full six-section round-trip |

**Stop. Testable:** `streamlit run app.py` → walk all six steps, close the browser mid-way, reopen and confirm the draft survived.

### Stage (c) — Embedding and vector-store pipeline

| File | Action | Contents |
|---|---|---|
| `src/documents.py` | **new** | Profile → logical documents: one for the bio, one per gig, one per portfolio item, one reviews digest. Each carries `sellerId`, `sectionType`, `gigId`, `sourceType` |
| `src/ingest.py` | **major change** | Add per-seller upsert: `collection.delete(where={"sellerId": ...})` then add, so re-onboarding **replaces** rather than duplicates. Chroma has no namespaces — a `sellerId` metadata filter is the equivalent, and is what `where` clauses already use for `layer`. Chunk at ~400 tokens / ~50 overlap. Route embeddings through the provider switch. **Keep** the existing atomic-rebuild ordering, the concurrency lock and the orphan-segment pruning |
| `src/config.py` | change | `CHUNK_SIZE`/`CHUNK_OVERLAP` retuned; `EMBEDDING_MODEL` default → `text-embedding-3-small`; `TOP_K` → 5 |
| `scripts/check_threshold.py` | change | Re-run against the new embeddings and **re-tune `MAX_DISTANCE`** — a required deliverable, not optional |
| `.env.example` | change | Document the new variables |
| `tests/test_documents.py` | **new** | Document splitting, metadata correctness, and that re-ingesting one seller leaves other sellers' vectors untouched |

**Stop. Testable:** `python scripts/reindex.py`, then `python scripts/check_threshold.py` and confirm the refusal boundary still separates real questions from off-topic ones.

### Stage (d) — Retrieval in the chat endpoint

| File | Action | Contents |
|---|---|---|
| `src/rag.py` | change | `retrieve()` accepts a `seller_id` and filters on it; `TOP_K = 5`; `ask()` returns the **source chunks** (text + metadata), not just filenames, so the UI can render citations. The existing grounding prompt, refusal behaviour and follow-up resolution stay as they are — they already meet the brief |
| `app.py` | change | Render citations as expandable source chunks under each answer |
| `tests/test_fiverr_brain.py` | change | Update for the new return shape; add seller-isolation tests (seller A's question must never retrieve seller B's chunks) |

**Stop. Testable:** ask questions in the app, confirm the citations shown match the answer and that a second seller's data never leaks in.

### Stage (e) — Screenshot OCR import

| File | Action | Contents |
|---|---|---|
| `src/ocr.py` | **new** | Validate (image MIME only, ≤10 MB), **strip EXIF** by re-encoding through Pillow, base64-encode, call `gpt-4o-mini` vision with `response_format` bound to `SellerProfile.model_json_schema()` so the reply is JSON matching the schema by construction. Prompt requires `null` for anything not visible and forbids inventing values. Returns the parsed model plus a **confidence report** — which fields came back populated |
| `src/ocr_ui.py` | **new** | Upload area → extraction spinner → **editable review screen** pre-filled with what was found, blanks clearly marked. On confirm, writes through the *same* `store.py` and `documents.py` path as stage (b) with `sourceType="ocr"`. If extraction is mostly null or low-confidence, say so plainly and hand the user the manual form instead of saving empty fields |
| `app.py` | change | Add the screenshot-import mode |
| `tests/test_ocr.py` | **new** | Oversized upload rejected, non-image rejected, EXIF actually stripped, low-confidence path triggers the warning, vision call stubbed (**no test spends money**) |

**Stop. Testable:** drop a real Fiverr screenshot in, check the extracted fields against the image, confirm nothing was invented.

### Final

| File | Action |
|---|---|
| `docs/SETUP.md` | **new** — every environment variable and the steps to run, per the brief |
| `README.md` | change — new modes, the storage change, the embedding-model change and its cost |
| `fiverr_brain_checklist.md` | change — mark the new phases |

---

## 5. How the requirements are met

| Requirement | How |
|---|---|
| Single shared schema, one source of truth | `src/schema.py` — the form fields, the OCR JSON schema and the database columns are all generated from or validated against the same pydantic models |
| API keys server-side only | Already satisfied. Streamlit executes entirely server-side; `.env` and `.streamlit/secrets.toml` are gitignored; no key reaches the browser |
| Uploads: images only, ≤10 MB, EXIF stripped | `src/ocr.py` — MIME check, size check, and a Pillow re-encode that discards metadata |
| Handle OCR failure honestly | Confidence report → explicit warning → manual form. Never a silent save of empty fields |
| Loading and error states everywhere | Existing pattern (`st.spinner` + typed exception handling) extended to the new async paths |
| No mock or placeholder data | Migration imports real KB content; widget placeholders are display hints and are never persisted |
| Prompt-injection safety | OCR'd text is untrusted and goes through the existing `rag.fence()` before reaching any prompt |

---

## 6. Out of scope — confirmed

No scraper. Nothing is fetched from fiverr.com. Data enters only through the manual form or a screenshot upload. Nothing in this plan makes an outbound request to Fiverr.

---

## 7. What is needed to start

1. **§1 — Python (Option A) or a TypeScript rewrite (Option B)?**
2. **§2.1 — SQLite structured store, accepting that hand-editing profile markdown ends?**
3. **§2.2 — Switch to `text-embedding-3-small`, accepting the API cost and the threshold re-tune?**
4. **§2.3 — Approximate token chunking (no new dependency), or add `tiktoken`?**
5. **§3 — Approve declaring `pydantic` and `Pillow` in `requirements.txt`?**

On approval, work starts at stage (a) and stops after it for testing.
