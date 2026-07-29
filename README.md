# Fiverr Brain 🧠

An internal RAG-powered chatbot for your Fiverr business. Ask it about your
gigs, pricing, policies, and SOPs — it answers only from your own knowledge
base, cites its sources, and says "I don't know" instead of guessing.

Built fully free: local embeddings (sentence-transformers), local vector
store (ChromaDB), and Google Gemini's free API tier for the LLM.

## 1. Setup

```bash
cd fiverr-brain
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Add your Gemini API key

1. Go to https://aistudio.google.com → sign in → "Get API key" → "Create API key".
2. Copy the key.
3. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
4. Open `.env` and paste your key after `GEMINI_API_KEY=`.

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
  with `"unanswered": true` — review these periodically to see what's
  missing from your knowledge base.

## Ground rules

- Internal tool only — not for public/buyer-facing use.
- Do not scrape Fiverr in violation of their Terms of Service.
- Never store passwords or payment data in the KB or logs.
- A human should always review `/new-gig` and `/buyer-reply` output before
  actually publishing or sending it.
