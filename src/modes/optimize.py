"""
/optimize mode: takes an existing gig (by name or pasted text) and
suggests improvements -- clarity, SEO keywords, structure, upsell ideas.
"""
from ..rag import context_of, fence, sources_of

OPTIMIZE_INSTRUCTIONS = """You are reviewing an EXISTING Fiverr gig for improvement.
Suggest concrete edits: clearer tagline, stronger opening hook, missing
buyer-relevant details, better structure, and 3-5 relevant search keywords
a buyer might use to find this gig. Do not rewrite pricing unless asked.
Keep suggestions practical and specific to the text given, not generic advice."""

# A pasted gig is long; a gig *name* is short. Below this, treat the input as a
# lookup key that must match a real gig rather than as the gig text itself.
PASTED_TEXT_MIN_CHARS = 200


def run(brain, gig_name_or_text: str):
    chunks = brain.retrieve(gig_name_or_text, layer_filter="profile_gigs")
    looks_pasted = len(gig_name_or_text) >= PASTED_TEXT_MIN_CHARS

    if not chunks and not looks_pasted:
        # Named a gig we don't have. Say so instead of silently optimizing
        # whatever happened to be the nearest neighbour.
        available = _list_gig_names(brain)
        listing = "\n".join(f"- {name}" for name in available) or "- (none indexed yet)"
        return {
            "answer": (
                f"I couldn't find a gig matching **\"{gig_name_or_text}\"** in your "
                f"knowledge base, so I haven't optimized anything.\n\n"
                f"Your indexed gigs are:\n{listing}\n\n"
                f"Either pick one of those, or paste the full gig text and I'll "
                f"optimize it directly."
            ),
            "sources": [],
            "chunks_used": 0,
        }

    if chunks:
        context = context_of(chunks)
        source_note = ""
    else:
        context = fence(gig_name_or_text, "pasted_gig")
        source_note = (
            "> ℹ️ This gig isn't in your knowledge base — optimizing the pasted "
            "text directly.\n\n"
        )

    prompt = (
        f"{OPTIMIZE_INSTRUCTIONS}\n\n"
        f"Gig content to optimize:\n{context}\n\n"
        f"Provide your optimization suggestions now."
    )
    answer = source_note + brain._call_llm(prompt)

    brain.remember(f"[optimize] {gig_name_or_text}", answer)
    return {
        "answer": answer,
        "sources": sources_of(chunks),
        "chunks_used": len(chunks),
    }


def _list_gig_names(brain):
    """Every gig file currently in the profile_gigs layer."""
    try:
        got = brain.collection.get(where={"layer": "profile_gigs"}, include=["metadatas"])
    except Exception:
        return []
    names = set()
    for meta in got.get("metadatas") or []:
        gig = meta.get("gig_name")
        names.add(gig if gig and gig != "N/A" else meta.get("source", "unknown"))
    return sorted(names)
