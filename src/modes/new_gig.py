"""
/new-gig mode: drafts a full new gig listing based on a short brief,
using the seller's existing gigs/profile as style reference, and can
save the result back into the knowledge base (Layer 1) for reindexing.
"""
from pathlib import Path

from .. import config
from ..rag import citations_of, context_of, sources_of


NEW_GIG_INSTRUCTIONS = """You are drafting a NEW Fiverr gig listing for this seller,
matching their existing tone and structure (see context chunks of their other gigs).
Produce: a tagline, a seller pitch paragraph, a "what's delivered" bullet list,
a "how it works" section if relevant, and a suggested category.
Do not invent pricing -- ask the user for pricing tiers if not provided."""


def run(brain, brief: str, seller_id: str = None):
    """brief: short description of the new gig idea from the user."""
    chunks = brain.retrieve(brief, layer_filter="profile_gigs", seller_id=seller_id)
    context = context_of(
        chunks,
        fallback="(No existing gigs indexed yet — use a clean, professional Fiverr tone.)",
    )
    prompt = (
        f"{NEW_GIG_INSTRUCTIONS}\n\n"
        f"Reference chunks from existing gigs (style/tone match):\n{context}\n\n"
        f"New gig brief from seller: {brief}\n\n"
        f"Draft the new gig listing now."
    )
    answer = brain._call_llm(prompt)

    brain.remember(f"[new-gig] {brief}", answer)
    return {
        "answer": answer,
        "sources": sources_of(chunks),
        "chunks_used": len(chunks),
        "citations": citations_of(chunks),
    }


def save_and_reindex(brain, filename: str, content: str):
    """Save a newly drafted gig into kb/profile_gigs and trigger reindex."""
    from .. import ingest

    folder = Path(config.KB_FOLDERS["profile_gigs"]).resolve()
    # Only the bare name -- never let a path like "../../x.md" escape the KB.
    safe_name = Path(filename).name
    if not safe_name or safe_name in {".", ".."}:
        raise ValueError("Invalid filename.")

    target = folder / safe_name
    if target.suffix.lower() != ".md":
        target = target.with_suffix(".md")
    if target.resolve().parent != folder:
        raise ValueError("Refusing to write outside the knowledge base folder.")

    target.write_text(content, encoding="utf-8")
    ingest.build_index(verbose=False)
    brain.refresh_collection()
    return str(target)
