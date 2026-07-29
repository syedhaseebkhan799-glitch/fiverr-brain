"""
/new-gig mode: drafts a full new gig listing based on a short brief,
using the seller's existing gigs/profile as style reference, and can
save the result back into the knowledge base (Layer 1) for reindexing.
"""
from pathlib import Path

from .. import config


NEW_GIG_INSTRUCTIONS = """You are drafting a NEW Fiverr gig listing for this seller,
matching their existing tone and structure (see context chunks of their other gigs).
Produce: a tagline, a seller pitch paragraph, a "what's delivered" bullet list,
a "how it works" section if relevant, and a suggested category.
Do not invent pricing -- ask the user for pricing tiers if not provided."""


def run(brain, brief: str):
    """brief: short description of the new gig idea from the user."""
    chunks = brain.retrieve(brief, layer_filter="profile_gigs")
    prompt = (
        f"{NEW_GIG_INSTRUCTIONS}\n\n"
        f"Reference chunks from existing gigs (style/tone match):\n"
        + "\n---\n".join(doc for doc, _ in chunks)
        + f"\n\nNew gig brief from seller: {brief}\n\n"
        f"Draft the new gig listing now."
    )
    return brain._call_llm(prompt)


def save_and_reindex(brain, filename: str, content: str):
    """Save a newly drafted gig into kb/profile_gigs and trigger reindex."""
    from .. import ingest

    target = Path(config.KB_FOLDERS["profile_gigs"]) / filename
    if not target.name.endswith(".md"):
        target = target.with_suffix(".md")
    target.write_text(content, encoding="utf-8")
    ingest.build_index(verbose=False)
    return str(target)