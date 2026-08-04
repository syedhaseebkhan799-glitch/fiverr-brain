"""
Lightweight local logging: every question + answer + sources gets
appended to a JSONL file. Also flags questions with zero retrieved
sources as "unanswered" for the seller to review and add KB content for.

Note: on Streamlit Community Cloud the filesystem is ephemeral, so this log
resets whenever the container restarts. It is a review aid, not a record.
"""
import json
from datetime import datetime, timezone

from . import config


def log_query(question: str, answer: str, sources: list, chunks_used: int, mode: str = "ask"):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "question": question,
        "answer": answer,
        "sources": sources,
        "chunks_used": chunks_used,
        "unanswered": chunks_used == 0,
    }
    try:
        config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.QUERY_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        # Read-only or full filesystem must never take down a user's answer.
        pass
    return entry


def get_unanswered_questions():
    """Questions that retrieved nothing relevant. Skips malformed lines so a
    single truncated write can't break the whole review view."""
    if not config.QUERY_LOG_FILE.exists():
        return []
    out = []
    try:
        with open(config.QUERY_LOG_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict) and entry.get("unanswered"):
                    out.append(entry)
    except OSError:
        return []
    return out
