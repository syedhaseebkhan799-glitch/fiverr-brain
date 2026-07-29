"""
/buyer-reply mode: drafts a reply to a buyer's message, grounded in the
seller's gigs, policies, and messaging SOPs so tone and facts stay consistent.
"""

REPLY_INSTRUCTIONS = """You are drafting a reply to a Fiverr buyer's message on
behalf of the seller. Use the context (gigs, policies, SOPs) to keep facts
accurate (pricing, delivery time, revisions, what's included). Match a
friendly, professional tone per the messaging SOP. Keep it concise -- a real
buyer message, not an essay. Do not promise anything not covered in the gigs."""


def run(brain, buyer_message: str):
    chunks = brain.retrieve(buyer_message)  # search across all layers
    context = "\n---\n".join(doc for doc, _ in chunks)
    prompt = (
        f"{REPLY_INSTRUCTIONS}\n\n"
        f"Relevant context:\n{context}\n\n"
        f"Buyer's message: {buyer_message}\n\n"
        f"Draft the reply now."
    )
    return brain._call_llm(prompt)