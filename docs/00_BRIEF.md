# Fiverr Brain — The Brief (as received)

**Received:** 2026-08-06
**Source:** Prompt provided by management for Claude Code
**Status:** Captured verbatim below. Four `<>` placeholders were left unfilled — see §B.

This file is the record of what was asked for. Two companion documents answer it:

- `docs/01_REPO_AUDIT.md` — what the repository actually contains today (step 1 of the brief)
- `docs/02_IMPLEMENTATION_PLAN.md` — the proposed plan and file list (step 2, awaiting approval)

---

## A. The brief, verbatim

> # Claude Code prompt — Fiverr Brain: profile onboarding + screenshot OCR import
>
> > Paste everything below the line into Claude Code. Fill in the four `<>` placeholders first.
>
> ---
>
> ## Context
>
> I am working on an existing project called **Fiverr Brain**. It currently has a working chatbot built on the OpenAI API. Read the repository first and follow the existing structure, naming conventions, and libraries — do not introduce a new framework or restructure what already exists.
>
> My stack: `<e.g. Next.js 14 App Router + TypeScript + Tailwind, Node backend, Postgres>`
> Vector store I want to use: `<Pinecone | Chroma | Supabase pgvector — pick one>`
> Where profile data should live: `<e.g. Postgres via Prisma>`
>
> ## What I am building
>
> Two features that share one knowledge base.
>
> ### Feature 1 — Profile onboarding
>
> A multi-step form that imports one Fiverr seller's full profile into the platform and stores it in a knowledge base the chatbot can query.
>
> The form must be split into these six sections, as separate steps with a progress indicator, save-as-draft between steps, and validation per step:
>
> 1. **Basic information** — name, username, profile photo URL, country, languages, member since, average response time
> 2. **About / bio** — full seller description (long text)
> 3. **Skills** — skills (repeatable tags), education, certifications, tests
> 4. **Gigs** — repeatable gig blocks. Each gig: title, category, full description, three pricing packages (basic / standard / premium, each with name, price, delivery days, revisions, included features), gig extras, FAQs (repeatable question + answer)
> 5. **Projects / portfolio** — repeatable items: title, description, image URL, link
> 6. **Reviews and ratings** — overall rating, total review count, star breakdown, repeatable reviews (text, stars, buyer country, date)
>
> ### Feature 2 — Screenshot import with OCR
>
> An upload area where the user drops a screenshot of a Fiverr gig or profile page. The system reads the image, extracts structured data, shows it in an editable review screen, and on confirmation writes it into the same tables and the same knowledge base as Feature 1.
>
> Use the OpenAI vision model for extraction (not Tesseract) — send the image as base64 and prompt it to return **only** JSON matching my profile schema, with `null` for any field not visible in the screenshot. Never invent values that are not in the image.
>
> ## Knowledge base pipeline
>
> After a profile is saved (from either feature):
>
> 1. Turn the stored profile into clean text documents, one per logical unit — bio, each gig, each portfolio item, a reviews digest. Each document keeps metadata: `sellerId`, `sectionType`, `gigId`, `sourceType` (`manual` or `ocr`).
> 2. Chunk to roughly 400 tokens with about 50 tokens of overlap.
> 3. Embed with `text-embedding-3-small`.
> 4. Upsert into the vector store, namespaced per seller. Re-onboarding the same seller must replace that seller's vectors, not duplicate them.
> 5. Update the existing chat endpoint to do retrieval: embed the question, fetch the top 5 chunks for the selected seller, and pass them to the model with an instruction to answer only from the provided context and to say it does not know when the context does not cover the question. Return the source chunks alongside the answer so the UI can show citations.
>
> ## Requirements
>
> - TypeScript throughout, with a single shared schema (Zod) used by the form, the OCR extraction, and the database layer — one source of truth.
> - API keys server-side only. Never expose the OpenAI key to the browser.
> - Validate uploads: images only, max 10 MB, and strip EXIF.
> - Handle failure honestly — if OCR returns low-confidence or mostly-null data, tell the user and let them fill the gaps manually instead of silently saving empty fields.
> - Loading and error states on every async action.
> - No mock or placeholder data in the final code paths.
>
> ## How I want you to work
>
> 1. First, read the repo and tell me what you found — the structure, where the chat logic lives, what is already installed.
> 2. Then give me a short implementation plan and the file list you intend to create or change, and **wait for my approval before writing code**.
> 3. Build it in this order, stopping after each so I can test: (a) schema and database layer, (b) onboarding form, (c) embedding and vector store pipeline, (d) retrieval in the chat endpoint, (e) screenshot OCR flow.
> 4. Ask me before adding any new dependency.
> 5. At the end, write a short `SETUP.md` with the environment variables I need and the steps to run it.
>
> ## Out of scope
>
> Do not build a Fiverr scraper and do not fetch anything from fiverr.com. Data enters the system only through the manual form or a screenshot upload.

---

## B. The four placeholders were never filled in

The brief's own first line says: *"Fill in the four `<>` placeholders first."* They arrived unfilled.

| Placeholder | Value as received | Resolves against this repo? |
|---|---|---|
| My stack | `<e.g. Next.js 14 App Router + TypeScript + Tailwind, Node backend, Postgres>` | ❌ No. The repo is Python + Streamlit. There is no `package.json`, no Node, no Next.js |
| Vector store | `<Pinecone \| Chroma \| Supabase pgvector — pick one>` | ✅ Yes — **Chroma**, already installed and in use |
| Where profile data should live | `<e.g. Postgres via Prisma>` | ❌ No. There is no Postgres and no Prisma. Data currently lives in markdown files plus one SQLite table |
| (fourth) | Not present in the text as received | — Only three `<>` markers appear in the brief |

Because the placeholders still carry their example text, the "TypeScript throughout / Zod / Prisma" requirement reads as un-customised template boilerplate rather than a deliberate instruction about this codebase — and it directly contradicts the brief's own opening instruction to *"follow the existing structure, naming conventions, and libraries — do not introduce a new framework."*

**This is the one decision that blocks everything else.** The options and a recommendation are in `docs/02_IMPLEMENTATION_PLAN.md` §1.

---

## C. Requirements checklist extracted from the brief

Tracking table. Status reflects the repository as of 2026-08-06, before any new work.

### Feature 1 — Profile onboarding

| # | Section | Required fields | Status today |
|---|---|---|---|
| 1 | Basic information | name, username, profile photo URL, country, languages, member since, average response time | ⚠️ Partial — name, languages present |
| 2 | About / bio | full seller description | ✅ Present |
| 3 | Skills | skills (repeatable tags), education, certifications, tests | ⚠️ Partial — tests missing |
| 4 | Gigs | title, category, description, 3 pricing packages (name/price/delivery days/revisions/features), extras, FAQs | ⚠️ Partial — packages are free text, FAQs missing |
| 5 | Projects / portfolio | title, description, image URL, link | ❌ Not built |
| 6 | Reviews and ratings | overall rating, review count, star breakdown, repeatable reviews | ❌ Not built |

| Form behaviour | Status today |
|---|---|
| Six **separate steps** | ❌ Currently three tabs |
| Progress indicator | ✅ Present |
| Save-as-draft between steps | ❌ Not built |
| Validation per step | ⚠️ Per-form, not per-step |

### Feature 2 — Screenshot OCR import

| Requirement | Status today |
|---|---|
| Upload area for a screenshot | ❌ Not built |
| OpenAI **vision** model, not Tesseract | ❌ Not built |
| Image sent as base64 | ❌ Not built |
| Returns **only** JSON matching the profile schema | ❌ Not built |
| `null` for anything not visible; never invent values | ❌ Not built |
| Editable review screen before saving | ❌ Not built |
| Writes to the **same** tables and knowledge base as Feature 1 | ❌ Not built |

### Knowledge base pipeline

| # | Requirement | Status today |
|---|---|---|
| 1 | One document per logical unit (bio, each gig, each portfolio item, reviews digest) | ❌ One document per *file* |
| 1 | Metadata: `sellerId`, `sectionType`, `gigId`, `sourceType` | ❌ Metadata is `source`, `layer`, `gig_name`, `category` |
| 2 | ~400 tokens, ~50 overlap | ❌ 800 **words**, 150 overlap |
| 3 | Embed with `text-embedding-3-small` | ❌ Local `all-MiniLM-L6-v2` (free, offline) |
| 4 | Upsert namespaced per seller; re-onboarding replaces, does not duplicate | ❌ Deletes and rebuilds the entire collection |
| 5 | Top **5** chunks for the selected seller | ⚠️ Top 4, no seller filter |
| 5 | Answer only from context; say "I don't know" otherwise | ✅ Built and tested |
| 5 | Return **source chunks** for citations | ⚠️ Returns filenames only |

### Cross-cutting requirements

| Requirement | Status today |
|---|---|
| Single shared schema across form, OCR and DB | ⚠️ A declarative `Field` list exists, but covers only the form |
| API keys server-side only | ✅ Satisfied — Streamlit is server-side; `.env` is gitignored |
| Uploads: images only, ≤10 MB, EXIF stripped | ❌ No uploads exist |
| Handle OCR failure honestly | ❌ Not built |
| Loading and error states on every async action | ✅ Established pattern throughout |
| No mock or placeholder data | ✅ Satisfied |
| Ask before adding any dependency | ✅ Raised in plan §3 — no genuinely new package is required |
| `SETUP.md` at the end | ⏳ Deferred to the end, as the brief instructs |

### Out of scope — confirmed and respected

No Fiverr scraper. No requests to fiverr.com. Data enters only via the manual form or a screenshot upload.

---

## D. Open questions for management

Answers to these unblock stage (a). Full context for each is in `docs/02_IMPLEMENTATION_PLAN.md` §1–§3.

1. **Stack** — build in Python, following the existing repository (recommended), or rewrite the project in TypeScript/Next.js?
2. **Profile storage** — SQLite with Prisma-shaped tables (recommended, migratable to Postgres later), accepting that hand-editing profile markdown ends?
3. **Embeddings** — switch to `text-embedding-3-small` as specified, accepting the API cost and a mandatory re-tune of the relevance threshold that powers the "I don't know" behaviour?
4. **Chunking** — approximate token counting with no new dependency (recommended), or add `tiktoken` for exact counts?
5. **Dependencies** — approve declaring `pydantic` and `Pillow` in `requirements.txt`? Both are already installed as transitive dependencies.
