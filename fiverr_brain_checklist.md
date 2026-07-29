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
