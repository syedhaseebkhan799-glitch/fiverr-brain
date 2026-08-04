"""
/onboarding mode: walks a new hire through the SOPs step by step,
tracking progress in a local SQLite database (free, no server needed).
"""
import sqlite3
from datetime import datetime, timezone

from .. import config
from ..rag import context_of, sources_of

ONBOARDING_STEPS = [
    "sop_order_handling",
    "sop_buyer_messaging",
]


def _get_conn():
    config.ONBOARDING_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.ONBOARDING_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS onboarding_progress (
            trainee TEXT NOT NULL,
            step TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            PRIMARY KEY (trainee, step)
        )
    """)
    return conn


def mark_step_complete(trainee: str, step: str):
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO onboarding_progress (trainee, step, completed_at) VALUES (?, ?, ?)",
        (trainee, step, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def unmark_step(trainee: str, step: str):
    """Undo a completed step (the sidebar checkbox can be unticked)."""
    conn = _get_conn()
    conn.execute(
        "DELETE FROM onboarding_progress WHERE trainee = ? AND step = ?",
        (trainee, step),
    )
    conn.commit()
    conn.close()


def get_progress(trainee: str):
    conn = _get_conn()
    rows = conn.execute(
        "SELECT step, completed_at FROM onboarding_progress WHERE trainee = ?",
        (trainee,),
    ).fetchall()
    conn.close()
    done = {step: ts for step, ts in rows}
    return [
        {"step": step, "done": step in done, "completed_at": done.get(step)}
        for step in ONBOARDING_STEPS
    ]


def run(brain, trainee: str, question: str):
    """Answer an onboarding question using only the SOP layer."""
    chunks = brain.retrieve(question, layer_filter="sops", use_history=True)

    if not chunks:
        return {
            "answer": (
                "That isn't covered by any SOP in the knowledge base yet. "
                "Ask the seller to add it to `kb/sops/`, then rebuild the index."
            ),
            "sources": [],
            "chunks_used": 0,
        }

    context = context_of(chunks)
    prompt = (
        "You are training a new hire on this business's internal SOPs. "
        "Explain clearly and simply, using only the SOP context below. "
        "If the SOPs don't cover it, say so rather than guessing.\n\n"
        f"SOP context:\n{context}\n\nNew hire's question: {question}"
    )
    answer = brain._call_llm(prompt)

    brain.remember(f"[onboarding:{trainee}] {question}", answer)
    return {
        "answer": answer,
        "sources": sources_of(chunks),
        "chunks_used": len(chunks),
    }