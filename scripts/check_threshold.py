"""
Calibration helper for config.MAX_DISTANCE.

Prints the retrieval distance for questions your KB SHOULD answer and for
questions it SHOULD NOT. A good threshold sits in the gap between the two
groups. Re-run this after adding new content to kb/ and adjust
config.MAX_DISTANCE if the groups have shifted.

    python scripts/check_threshold.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# No LLM calls here -- retrieval only. A placeholder key is enough to construct.
os.environ.setdefault("OPENAI_API_KEY", "not-needed-for-retrieval")

from src import config          # noqa: E402
from src.rag import FiverrBrain  # noqa: E402

SHOULD_MATCH = [
    ("How much does the n8n automation gig cost?", None),
    ("how do I deliver an order?", "sops"),
    ("how do I handle a revision request?", "sops"),
    ("what are your revision policies", "sops"),
    ("what is your refund policy", "policies"),
    ("tell me about the AI influencer gig", "profile_gigs"),
    ("Hi, I need 3 n8n workflows by Friday.", None),
]

SHOULD_NOT_MATCH = [
    ("What is the weather in Karachi today?", None),
    ("who won the football world cup", None),
    ("my Photoshop retouching gig", "profile_gigs"),
    ("can you write me a Python script to mine bitcoin", None),
]


def nearest(brain, question, layer):
    from src.rag import embed

    res = brain.collection.query(
        query_embeddings=embed([question]),
        n_results=config.TOP_K,
        where={"layer": layer} if layer else None,
        include=["distances"],
    )
    dists = (res.get("distances") or [[]])[0]
    return min(dists) if dists else None


def main():
    brain = FiverrBrain()
    print(f"Collection holds {brain.collection.count()} chunks.")
    print(f"Embedding provider   : {config.EMBEDDING_PROVIDER}")
    print(f"Embedding model      : {config.EMBEDDING_MODEL}")
    print(f"Current MAX_DISTANCE : {config.MAX_DISTANCE}"
          + ("  (ESTIMATE — this run is what replaces it)"
             if config.MAX_DISTANCE_IS_ESTIMATED else "  (measured)"))
    if config.EMBEDDING_PROVIDER == "openai":
        print("Note: this makes one paid embedding call per question below.")
    print()

    worst_match, best_nonmatch = 0.0, 99.0
    problems = []

    for label, cases, expect_match in [
        ("SHOULD match", SHOULD_MATCH, True),
        ("SHOULD NOT match", SHOULD_NOT_MATCH, False),
    ]:
        print(f"--- {label} ---")
        for q, layer in cases:
            d = nearest(brain, q, layer)
            if d is None:
                print(f"  (empty index)  {q}")
                continue
            passed = (d <= config.MAX_DISTANCE) == expect_match
            if expect_match:
                worst_match = max(worst_match, d)
            else:
                best_nonmatch = min(best_nonmatch, d)
            if not passed:
                problems.append((q, d, expect_match))
            print(f"  {d:5.3f}  {'ok ' if passed else 'BAD'}  {q}")
        print()

    print(f"Furthest real match : {worst_match:.3f}")
    print(f"Closest off-topic   : {best_nonmatch:.3f}")
    if best_nonmatch > worst_match:
        suggested = (worst_match + best_nonmatch) / 2
        print(f"Suggested MAX_DISTANCE: {suggested:.2f}")
        print(f"\nPut this in your .env to make it stick:\n"
              f"    MAX_DISTANCE={suggested:.2f}")
    else:
        print("No clean gap -- the groups overlap. Add clearer KB content.")

    if problems:
        print(f"\n{len(problems)} case(s) on the wrong side of the threshold.")
        return 1
    print("\nAll cases correctly classified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
