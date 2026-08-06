# Fiverr Brain — Delivery Audit

**Date:** 2026-08-06
**Against:** `docs/00_BRIEF.md`
**Built per:** `docs/02_IMPLEMENTATION_PLAN.md`
**Tests:** 212 passing, none of which spends money

---

## 0. The five open decisions, and what was chosen

The plan blocked on five questions. Each was resolved by taking the plan's own
recommendation.

| # | Question | Decision | Why |
|---|---|---|---|
| 1 | Python or a TypeScript rewrite | **Python** | The brief's own "do not introduce a new framework" is the line written about *this* repository. The TypeScript/Prisma lines sit beside three unfilled `<>` placeholders |
| 2 | Where profile data lives | **SQLite**, Prisma-shaped tables | Flat markdown cannot round-trip three packages per gig, repeatable FAQs, individual reviews, or a per-field `null` from OCR |
| 3 | Embedding model | **`text-embedding-3-small`**, behind `EMBEDDING_PROVIDER` | Follows the brief; local MiniLM stays a one-line fallback and is what the tests run on |
| 4 | Chunking | **Approximate**, no `tiktoken` | 300 words ≈ 400 tokens, within ~10%. Exactness does not change retrieval here |
| 5 | Dependencies | **Declared `pydantic` and `Pillow`** | Both were already installed transitively. Nothing genuinely new was added |

---

## 1. Feature 1 — Profile onboarding

### The six sections

| # | Section | Required fields | Status |
|---|---|---|---|
| 1 | Basic information | name, username, photo URL, country, languages, member since, average response time | ✅ All present, plus headline and Fiverr level |
| 2 | About / bio | full seller description | ✅ With the 600-character Fiverr cap enforced |
| 3 | Skills | skills (repeatable), education, certifications, tests | ✅ All four; skills capped at 30 |
| 4 | Gigs | title, category, description, 3 packages (name/price/delivery days/revisions/features), extras, repeatable FAQs | ✅ All present. A `currency` field was added — Fiverr shows local currency, and converting would invent a number |
| 5 | Projects / portfolio | title, description, image URL, link | ✅ Repeatable |
| 6 | Reviews and ratings | overall rating, review count, star breakdown, repeatable reviews | ✅ All present |

### Form behaviour

| Requirement | Status | Where |
|---|---|---|
| Six **separate steps** | ✅ | `schema.STEPS`, `profile_ui.render` |
| Progress indicator | ✅ Bar plus a per-step tick list | `profile_ui.render` |
| Save-as-draft between steps | ✅ Written on Back, Next, and an explicit button; resumable after a browser close | `store.save_draft`, `drafts` table |
| Validation per step | ✅ Blocks Next; the step is named in the error | `schema.validate_step` |

---

## 2. Feature 2 — Screenshot import with OCR

| Requirement | Status | Where |
|---|---|---|
| Upload area for a screenshot | ✅ | `ocr_ui._render_upload` |
| OpenAI **vision** model, not Tesseract | ✅ `gpt-4o-mini`, configurable via `VISION_MODEL` | `ocr.extract` |
| Image sent as base64 | ✅ As a `data:image/png;base64,…` URL | `ocr.to_data_url` |
| Returns **only** JSON matching the profile schema | ✅ Bound with `response_format: json_schema, strict: true`, generated from `SellerProfile.model_json_schema()` — never hand-written, so the extractor cannot drift from the form | `schema.ocr_json_schema` |
| `null` for anything not visible; never invent | ✅ Instructed explicitly, and every field is nullable so the model can comply | `ocr.EXTRACTION_PROMPT` |
| Editable review screen before saving | ✅ The extraction is shown, then handed to the onboarding form to edit and save. There is no separate save path | `ocr_ui._render_review` |
| Writes to the **same** tables and knowledge base | ✅ Same `store.save_seller`, same `documents`, same `ingest.upsert_seller` | — |

**Beyond the brief, because the obvious use is a single-gig screenshot:**
`ocr.merge_into` overlays an extraction onto an existing profile rather than
replacing it. A screenshot of one gig adds that gig; it does not blank out the
seller's country because the image did not show it.

---

## 3. Knowledge base pipeline

| # | Brief | Status | Where |
|---|---|---|---|
| 1 | One document per logical unit — bio, each gig, each portfolio item, a reviews digest | ✅ Exactly these four kinds | `documents.build_documents` |
| 1 | Metadata `sellerId`, `sectionType`, `gigId`, `sourceType` | ✅ On every chunk, always populated (Chroma rejects `None`, and a missing key cannot be matched by a filter) | `documents._doc` |
| 2 | ~400 tokens, ~50 overlap | ✅ 300 words / 37 words, from an explicit tokens-per-word constant | `config.CHUNK_SIZE` |
| 3 | Embed with `text-embedding-3-small` | ✅ The default | `rag.OpenAIEmbedder` |
| 4 | Upsert namespaced per seller; re-onboarding **replaces**, does not duplicate | ✅ Chroma has no namespaces, so a `sellerId` filter is the namespace. Delete-then-add, not Chroma's `upsert` — chunk ids depend on how text splits, so a profile that got shorter would otherwise leave its tail behind | `ingest.upsert_seller` |
| 5 | Top **5** chunks for the selected seller | ✅ `TOP_K = 5`, filtered on seller | `rag._where` |
| 5 | Answer only from context; say "I don't know" | ✅ Unchanged — it already met the brief | `config.SYSTEM_PROMPT`, `MAX_DISTANCE` |
| 5 | Return the **source chunks** for citations | ✅ `ask()` returns `citations`, rendered as expandable chunks | `rag.citations_of` |

**Design decision worth flagging:** policies and SOPs are tagged
`sellerId = "__shared__"` rather than being owned by a seller. They belong to
the business, and excluding them would make "what is the refund policy?"
unanswerable the moment a seller is selected.

---

## 4. Cross-cutting requirements

| Requirement | Status | Evidence |
|---|---|---|
| Single shared schema across form, OCR and DB | ✅ | `src/schema.py`. Form fields carry a dotted `path` into the model; the OCR schema is generated from it; `store.py` reads and writes the same models |
| API keys server-side only | ✅ | Streamlit runs entirely server-side; `.env` and `.streamlit/secrets.toml` gitignored; no key reaches the browser |
| Uploads: images only, ≤10 MB, EXIF stripped | ✅ | `ocr.validate_image` checks size **before** decoding (a decompression bomb is refused on size), verifies the header rather than the extension, and `strip_exif` re-encodes through a fresh Pillow image. Tested against a fixture that really carries EXIF |
| Handle OCR failure honestly | ✅ | A confidence report counts populated fields, names which sections were readable and which were not, and flags a mostly-null extraction with an explicit "upload a clearer screenshot, or fill it in yourself" |
| Loading and error states on every async action | ✅ | `st.spinner` on every call; typed exceptions (`LLMError`, `EmbeddingError`, `OCRError`) turned into actionable messages, never tracebacks |
| No mock or placeholder data | ✅ | Widget placeholders are display hints and are never persisted. The migration imports real content |
| Ask before adding a dependency | ✅ | Raised in the plan; only already-installed packages were promoted to declared pins |
| `SETUP.md` at the end | ✅ | `docs/SETUP.md` |

---

## 5. Out of scope — confirmed

No scraper. No request to fiverr.com anywhere in the codebase. Data enters only
through the form or a screenshot the user uploads. Stated in the UI as well as
here.

---

## 6. Nothing previously working was regressed

The audit that produced commit `b63d062` fixed 24 edge cases. All of them still
hold, and the tests that pin them still pass:

- Prompt-injection fencing — extended to OCR'd text, which is untrusted
- Path-traversal refusal — extended to the markdown export, whose filename
  derives from a username the seller types
- Atomic reindex — embeddings computed before the live collection is touched,
  on both the rebuild and the upsert path
- Concurrent-rebuild locking — upsert takes the same lock, so it cannot land
  mid-rebuild and write into a collection about to be replaced
- One shared embedding model process-wide
- Ephemeral-host warnings — now also covering the profile database
- Relevance thresholding, follow-up vs topic-change retrieval, bounded history,
  typed error handling, log robustness

---

## 7. Bugs found and fixed during the build

Four of these were caught by tests written for this work, not by inspection.

| Bug | Consequence | Fix |
|---|---|---|
| `gig_id` is a global primary key, but two sellers could carry the same one (from an OCR extraction, or a draft written under another username) | The second seller's save died with a raw `sqlite3.IntegrityError` | `store.save_seller` namespaces any foreign id to the seller and de-duplicates within them |
| `%g` formatting of prices | `11667.42` rendered as `11667.4` — wrong data in the index, and silently corrupted on reopening the form | `schema.format_number`, which keeps cents |
| `wiz_gig…` widget prefix also matched the `wiz_gigs` list | Deleting a gig deleted the gig list itself | Widgets moved to their own `wiz_w_` namespace |
| The seller selector rendered only on the first pass | A seller with two profiles could never reach the second | Rendered every rerun, with the reload guarded on the selection changing |
| `st.text_input(value=…, key=…)` on the FAQ rows | Streamlit overwrites what the user just typed on rerun | Seed session state once, bind by key alone |
| An index built before this change has no `sellerId` | A `where` clause cannot match a missing key, so every scoped question would come back "I don't know" — silently | `schema_version` stamped on the collection; the app tells you to reindex |
| `CREATE TABLE IF NOT EXISTS` does nothing to an existing table | Upgrading a database that already held profiles died on the first write with `table packages has no column named currency` | `store.ADDED_COLUMNS` + `_apply_column_migrations`, run on every `init_db` |
| The wizard's generated markdown export was re-indexed as hand-written KB content | Every seller filed **twice** — once correctly under their `sellerId`, once as `__shared__` content visible to every other seller. Seller isolation silently defeated | `_kb_file_records` skips files whose frontmatter says `type: profile_export` |

---

## 8. What is **not** done, and why

### `MAX_DISTANCE` — done for `local`, still blocked for `openai`

**Done:** the `local` threshold was re-measured on 2026-08-06 against the new
chunk size and the new document structure, both of which changed under it.
Real topical matches span 0.79–1.43, off-topic 1.58–2.04; all 11 calibration
cases classify correctly and the suggested value (1.50) is within rounding of
the existing 1.49, so it stands — now on evidence rather than inheritance.

**Still blocked:** the `openai` figure. There is no API key in this checkout, so
no OpenAI index can be built and no distance measured. The shipped 1.35 is an
estimate, `config.MAX_DISTANCE_IS_ESTIMATED` is true while it is in force, and
the app shows a banner saying so. It does not pretend to be calibrated.

**To close it:** add a key, `python scripts/reindex.py`, then
`python scripts/check_threshold.py`, and put the suggested value in `.env`.
Roughly a dozen embedding calls — fractions of a cent.

### The vision path has never seen a real screenshot

Every branch is tested with a stubbed client — validation, EXIF stripping,
schema binding, parsing, confidence, merging, and the review screen rendering.
But no real image has been sent to a real model, because that needs a key. The
prompt and the strict schema are the parts most likely to need a tweak once you
try them on an actual Fiverr page.

### The committed index is built with `local`, not `openai`

`data/chroma_db/` now holds 8 chunks at schema version 2 — 4 shared
(policies + SOPs) and 4 for `syed_haseeb` (1 bio + 3 gigs). It is stamped
`local`, because rebuilding with the default provider needs a key. On first run
with `EMBEDDING_PROVIDER=openai` the app will correctly tell you to reindex.

---

## 9. Your next four commands

```bash
# 1. Add OPENAI_API_KEY to .env  (cp .env.example .env)

# 2. Import the existing profile and gigs
python scripts/migrate_kb_to_store.py            # preview first
python scripts/migrate_kb_to_store.py --apply

# 3. Build the index with the new embeddings
python scripts/reindex.py

# 4. Measure the refusal boundary, then put it in .env
python scripts/check_threshold.py
```

Then `streamlit run app.py`.
