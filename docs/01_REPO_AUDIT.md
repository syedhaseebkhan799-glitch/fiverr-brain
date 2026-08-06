# Fiverr Brain — Repository Audit

**Date:** 2026-08-06
**Purpose:** Step 1 of the brief — read the repo and report what is actually here, before any code is written for profile onboarding and screenshot OCR import.

---

## 1. The stack is Python, not TypeScript

This is the first thing that has to be settled, because the brief contradicts itself on it.

The brief says two things that cannot both be honoured:

> "Read the repository first and follow the existing structure, naming conventions, and libraries — **do not introduce a new framework or restructure what already exists.**"

> "**TypeScript throughout**, with a single shared schema (Zod) … `<Next.js 14 App Router + TypeScript + Tailwind, Node backend, Postgres>` … `<Postgres via Prisma>`"

The repository contains **no TypeScript, no Node, no Next.js, no Postgres and no Prisma**. There is no `package.json`. It is:

| Layer | What is actually used |
|---|---|
| UI | **Streamlit 1.60** (`app.py`, Python) |
| Language | **Python** — 2,718 lines across 16 files |
| LLM | **OpenAI `gpt-4o-mini`** via the `openai` 2.50 SDK |
| Embeddings | **`sentence-transformers` / `all-MiniLM-L6-v2`** — runs locally, free, no API call |
| Vector store | **ChromaDB 1.5.9**, persisted to `data/chroma_db/` |
| Structured storage | Markdown files in `kb/` + one **SQLite** table for onboarding progress |
| Tests | **pytest**, 57 tests, LLM stubbed (`tests/test_fiverr_brain.py`) |
| Deploy target | Streamlit Community Cloud (~1 GB RAM, ephemeral filesystem) |

The three `<>` placeholders in the brief (stack, vector store, profile storage) were never filled in, which is almost certainly why the boilerplate still says Next.js/Prisma. **The vector store placeholder resolves cleanly — Chroma is one of the three offered options and is already in use.** The others do not resolve.

**This needs a decision before stage (a) starts.** See `02_IMPLEMENTATION_PLAN.md` §1.

---

## 2. Repository structure

```
fiverr-brain/
├── app.py                        219 lines — Streamlit entry point, sidebar, chat loop
├── requirements.txt              5 pinned deps
├── .env.example                  OPENAI_API_KEY, OPENAI_MODEL, EMBEDDING_MODEL
├── README.md                     setup + deploy guide (current, accurate)
├── fiverr_brain_checklist.md     build checklist from the original phase plan
│
├── src/
│   ├── config.py            71   all settings, reads .env, no hardcoded secrets
│   ├── ingest.py           234   markdown → chunks → embeddings → Chroma
│   ├── rag.py              303   ** the chat logic lives here **
│   ├── logging_utils.py     55   JSONL query log + unanswered-question capture
│   ├── profile_setup.py    521   ** NEW, uncommitted ** — profile/gig read-write
│   ├── profile_ui.py       274   ** NEW, uncommitted ** — Streamlit wizard
│   └── modes/
│       ├── new_gig.py       61   drafts a new gig, saves back into kb/
│       ├── optimize.py      74   suggests improvements to an existing gig
│       ├── onboarding.py    93   SOP walkthrough, SQLite progress tracking
│       └── buyer_reply.py   47   drafts buyer replies, fences untrusted input
│
├── kb/                           the knowledge base — markdown is the source of truth
│   ├── profile_gigs/        4 files (seller_profile.md + 3 gigs)   → layer "profile_gigs"
│   ├── policies/            2 files                                → layer "policies"
│   └── sops/                2 files                                → layer "sops"
│
├── scripts/
│   ├── reindex.py           15   rebuild the whole index
│   └── check_threshold.py   97   re-calibrate the relevance cut-off
│
├── data/chroma_db/               committed prebuilt index (so deploys work immediately)
├── logs/query_log.jsonl          per-query log
└── tests/test_fiverr_brain.py   654 lines, 57 tests
```

---

## 3. Where the chat logic lives

**`src/rag.py` → `class FiverrBrain`.** Everything routes through it.

| Method | Line | What it does |
|---|---|---|
| `__init__` | 87 | Fails fast if `OPENAI_API_KEY` is missing; opens Chroma; checks the index was built by the current embedding model |
| `_search` | 190 | One vector query, then **drops any chunk whose cosine distance > `MAX_DISTANCE` (1.49)** — this is what makes "I don't know" possible |
| `retrieve` | 229 | Tries the question standalone; only if that finds nothing *and* it looks like a referential follow-up does it re-query blended with the previous turn |
| `_build_prompt` | 259 | Assembles `history + context chunks + question` |
| `_call_llm` | 134 | Single OpenAI call site, with typed error handling for auth/rate-limit/timeout/connection |
| `ask` | 283 | `retrieve → prompt → LLM → remember`, returns `{answer, sources, chunks_used}` |

Three details in here matter for the new work:

1. **`MAX_DISTANCE = 1.49` is hand-calibrated to MiniLM and to this specific 8-file KB** (`config.py:46-51`). Real matches measured 0.79–1.43, off-topic 1.54–2.04. It is a narrow gap. Changing the embedding model or adding a lot of content invalidates it.
2. **`fence()`** (`rag.py:53`) wraps untrusted text — a buyer's message, a pasted gig — in explicit data markers so it can never be read as an instruction. Any new untrusted input (OCR'd screenshot text) must go through it.
3. **`ask()` returns filenames only** (`sources_of()` → `["gig_n8n_automation.md"]`), not the chunk text. The brief wants the source chunks returned so the UI can show citations — that is a change, not something already there.

---

## 4. What already exists of Feature 1 (profile onboarding)

**A substantial first cut is already written and uncommitted:** `src/profile_setup.py` (521 lines) and `src/profile_ui.py` (274 lines), wired into `app.py` as a new `👤 Profile onboarding` sidebar mode that a session lands on first until the profile is complete.

What it already does well, and should be kept:

- A declarative `Field` class (`profile_setup.py:33`) drives the form, the validation and the markdown rendering from one list — the same "one source of truth" idea the brief asks for from Zod.
- Round-trips markdown: `render_profile_md` / `parse_profile_md`, so a profile edited by hand in a text editor and one built in the UI are the same file.
- Enforces real Fiverr limits — 600-char bio, 30 skills.
- Path-traversal-safe writes (`_safe_target`, line 311), the same rule as `new_gig.save_and_reindex`.
- Reindexes after every save and refuses to report success if the rebuild failed (`profile_ui._reindex`, line 71).
- `SECTION_ALIASES` (line 160) so an older hand-written profile opens populated rather than blank.
- An optional LLM bio drafter (`suggest_bio`, line 497) that fences the seller's own answers.

### Gap analysis against the six required sections

| # | Required section | Status |
|---|---|---|
| 1 | **Basic information** | ⚠️ Partial — has name, languages, level. **Missing: username, profile photo URL, country, member since, average response time as a discrete field** (it is currently free text merged with availability) |
| 2 | **About / bio** | ✅ Present, with the 600-char cap |
| 3 | **Skills** | ⚠️ Partial — skills, education, certifications present. **Missing: tests.** Skills are newline text, not repeatable tags |
| 4 | **Gigs** | ⚠️ Partial — title, category, description, requirements, extras. **Missing: the three structured pricing packages** (name/price/delivery days/revisions/included features each — currently one free-text "Packages" box) **and FAQs** |
| 5 | **Projects / portfolio** | ❌ Not present |
| 6 | **Reviews and ratings** | ❌ Not present |

### Gaps against the other stated requirements

| Requirement | Status |
|---|---|
| Six **separate steps** with a progress indicator | ⚠️ Three tabs (`Seller profile` / `Gigs` / `Review`), not six steps. A progress bar exists (`profile_ui.py:243`) |
| **Save-as-draft between steps** | ❌ Values live in `st.session_state` and are lost on reload; only a fully valid profile can be saved |
| **Per-step validation** | ⚠️ Validation is per-form, not per-step |
| Loading + error states on every async action | ✅ Spinners and typed error handling throughout |
| No mock/placeholder data | ✅ Placeholders are widget hints only, never saved |

---

## 5. What exists of the knowledge-base pipeline vs. what the brief specifies

`src/ingest.py::build_index` is the current pipeline. It is careful code — it embeds *before* deleting the live collection so a mid-way failure leaves the working index intact (line 199), it serialises concurrent rebuilds behind a lock (line 136), and it prunes orphaned Chroma segments so the committed index does not bloat the repo (line 81).

But it is a **full-rebuild** pipeline, and the brief specifies a **per-seller upsert** pipeline. Every numbered point differs:

| Brief | Current behaviour | Change needed |
|---|---|---|
| 1. One document **per logical unit** (bio, each gig, each portfolio item, reviews digest) | One document per **file**, chunked | Document assembly layer |
| 1. Metadata `sellerId`, `sectionType`, `gigId`, `sourceType` | Metadata is `source`, `layer`, `gig_name`, `category` (`ingest.py:182`) | New metadata schema |
| 2. ~400 tokens, ~50 overlap | **800 *words*, 150 overlap** (`config.py:33`) — words, not tokens; roughly 2.5× larger | Retune, and decide token-accurate vs. word-approximate |
| 3. Embed with **`text-embedding-3-small`** | Local MiniLM, free, offline | **Switches embeddings from free to paid, and invalidates `MAX_DISTANCE`** |
| 4. Upsert, **namespaced per seller**; re-onboarding replaces that seller's vectors | Deletes and recreates the **entire collection** every time | Incremental delete-by-`sellerId` + add. Chroma has no namespaces — a metadata filter is the equivalent |
| 5. Retrieve **top 5** for the selected seller | `TOP_K = 4`, no seller filter | Config + `where` clause |
| 5. Answer only from context; say "don't know" | ✅ Already done, and tested | None |
| 5. **Return the source chunks** alongside the answer for citations | Returns **filenames only** | `ask()` return-shape change |

### The embedding-model switch is the single riskiest item

Moving to `text-embedding-3-small` is not a one-line config change:

- The index must be fully rebuilt; the app already detects the mismatch and warns rather than silently returning nothing (`rag.py:100`), which is good, but the rebuild is mandatory.
- **`MAX_DISTANCE = 1.49` becomes meaningless.** It was measured against MiniLM. OpenAI embeddings sit on a different distance scale, so the "I don't know" behaviour — the feature the whole tool is built around — will misfire until `scripts/check_threshold.py` is re-run and the value re-tuned.
- It introduces a per-query and per-reindex API cost where there was none, and a network dependency in the ingest path that currently works fully offline.
- 57 tests stub the LLM but **not** the embedder; they call the real `SentenceTransformer`. Switching means either stubbing embeddings too or the suite starts costing money on every run.

This is worth doing if the boss wants the retrieval quality — `text-embedding-3-small` is meaningfully better, and it fixes the documented non-English weakness (README §6). It just is not free and is not a drop-in.

---

## 6. What exists of Feature 2 (screenshot OCR import)

**Nothing.** No upload handling, no image processing, no vision call anywhere in the repo.

Everything needed is nonetheless within reach: `gpt-4o-mini` (already the configured model) supports vision, and the `openai` SDK is already a pinned dependency.

---

## 7. Installed packages

Declared in `requirements.txt`, all pinned:

```
streamlit==1.60.0   chromadb==1.5.9   sentence-transformers==5.6.1
openai==2.50.0      python-dotenv==1.2.2
```

Relevant to the new work, **already present in the venv as transitive dependencies but not declared**:

| Package | Version | Would be used for |
|---|---|---|
| `pydantic` | 2.13.4 | The shared schema — the Python equivalent of Zod (pulled in by chromadb) |
| `Pillow` | 12.3.0 | Image validation and EXIF stripping (pulled in by streamlit) |
| `numpy` | 2.5.1 | Already used indirectly by embeddings |

Not installed: `tiktoken` (would be needed only for *exact* 400-token chunking).

So the honest dependency position is: **no genuinely new package is required.** Two already-installed ones would need to be promoted to declared, pinned entries in `requirements.txt`. That still counts as a dependency change and is raised for approval in the plan rather than done silently.

---

## 8. Things already handled that must not be regressed

The existing code has scar tissue from 24 fixed edge cases (commit `b63d062`) and a 57-test regression suite. When the new features land, these must still hold:

- **Prompt-injection fencing** on all untrusted input (`rag.fence`). OCR'd screenshot text is untrusted and must be fenced.
- **Path-traversal refusal** on every KB write (`profile_setup._safe_target`, `new_gig.save_and_reindex`).
- **Atomic reindex** — never delete the live index before the new embeddings exist.
- **Concurrent-rebuild locking** (`ingest._REBUILD_LOCK`).
- **One shared embedding model process-wide** (`rag.get_embed_model`) — a per-session model instance would OOM the 1 GB Streamlit container.
- **Ephemeral-host warnings** (`config.is_ephemeral_host`) — on Streamlit Cloud, anything written at runtime is lost on restart. This matters a great deal for a feature whose whole job is saving a profile, and the wizard already warns about it (`profile_ui.py:96`).
- **API keys server-side only** — already satisfied: Streamlit runs entirely server-side, `.env` and `.streamlit/secrets.toml` are gitignored, and no key ever reaches the browser.

---

## 9. Summary

- Feature 1 is roughly **40% built** already, in Python, with good bones — but covers 2 of 6 required sections fully, and lacks portfolio, reviews, structured pricing packages, FAQs, six-step navigation and draft-saving.
- Feature 2 is **not started**.
- The KB pipeline exists and is well-built, but differs from the brief on **every one of the five specified points** — most consequentially the embedding model.
- The brief's stated stack (TypeScript/Next.js/Prisma/Postgres) **does not match this repository**, and its instruction to not introduce a new framework points the other way. This is the one blocking decision.

Proposed plan and file list: **`docs/02_IMPLEMENTATION_PLAN.md`**.
