"""
Lightweight local logging: every question + answer + sources gets
appended to a JSONL file. Also flags questions with zero retrieved
sources as "unanswered" for the seller to review and add KB content for.
"""
import json
from datetime import datetime, timezone

from . import config


def log_query(question: str, answer: str, sources: list, chunks_used: int):
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "question": question,
        "answer": answer,
        "sources": sources,
        "chunks_used": chunks_used,
        "unanswered": chunks_used == 0,
    }
    with open(config.QUERY_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def get_unanswered_questions():
    if not config.QUERY_LOG_FILE.exists():
        return []
    out = []
    with open(config.QUERY_LOG_FILE, encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            if entry.get("unanswered"):
                out.append(entry)
    return out
