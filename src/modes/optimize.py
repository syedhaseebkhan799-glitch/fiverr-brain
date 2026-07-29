"""
/optimize mode: takes an existing gig (by name or pasted text) and
suggests improvements -- clarity, SEO keywords, structure, upsell ideas.
"""

OPTIMIZE_INSTRUCTIONS = """You are reviewing an EXISTING Fiverr gig for improvement.
Suggest concrete edits: clearer tagline, stronger opening hook, missing
buyer-relevant details, better structure, and 3-5 relevant search keywords
a buyer might use to find this gig. Do not rewrite pricing unless asked.
Keep suggestions practical and specific to the text given, not generic advice."""


def run(brain, gig_name_or_text: str):
    chunks = brain.retrieve(gig_name_or_text, layer_filter="profile_gigs")
    context = "\n---\n".join(doc for doc, _ in chunks) if chunks else gig_name_or_text
    prompt = (
        f"{OPTIMIZE_INSTRUCTIONS}\n\n"
        f"Gig content to optimize:\n{context}\n\n"
        f"Provide your optimization suggestions now."
    )
    return brain._call_llm(prompt)