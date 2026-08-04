"""
Central configuration for Fiverr Brain.
Reads settings from environment variables (.env file), never hardcodes secrets.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# --- LLM settings (OpenAI) ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# --- Embeddings (local, free, no key needed) ---
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# --- Vector store ---
CHROMA_PERSIST_DIR = str(PROJECT_ROOT / "data" / "chroma_db")
COLLECTION_NAME = "fiverr_brain_kb"

# --- Knowledge base folders ---
KB_DIR = PROJECT_ROOT / "kb"
KB_FOLDERS = {
    "profile_gigs": KB_DIR / "profile_gigs",
    "policies": KB_DIR / "policies",
    "sops": KB_DIR / "sops",
}

# --- Chunking ---
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150

# --- Retrieval ---
TOP_K = 4

# --- Limits ---
# Cap what we send so a huge paste can't overflow the context window,
# and cap what comes back so long drafts aren't cut off mid-sentence.
MAX_INPUT_CHARS = 8000      # per user message, before it reaches the prompt
MAX_PROMPT_CHARS = 24000    # whole assembled prompt (~6k tokens)
MAX_OUTPUT_TOKENS = 2000

# Cosine distance above which a retrieved chunk is treated as irrelevant.
# Calibrated with scripts/check_threshold.py against this KB: real topical
# matches measured 0.79-1.43, off-topic queries 1.54-2.04. 1.49 sits in the gap.
# The margin is narrow because the KB is only 8 files -- re-run the script and
# retune after adding content, or genuine questions will start being refused.
MAX_DISTANCE = 1.49


def is_ephemeral_host() -> bool:
    """True when running on a host whose filesystem resets on restart
    (Streamlit Community Cloud). Rebuilt indexes and logs will not survive."""
    return any(
        os.getenv(v) for v in ("STREAMLIT_SHARING_MODE", "STREAMLIT_RUNTIME_ENV")
    ) or os.path.isdir("/mount/src")

# --- Logging ---
LOGS_DIR = PROJECT_ROOT / "logs"
QUERY_LOG_FILE = LOGS_DIR / "query_log.jsonl"
ONBOARDING_DB = PROJECT_ROOT / "data" / "onboarding.sqlite3"

# --- Guardrail system prompt ---
SYSTEM_PROMPT = """You are Fiverr Brain, an internal assistant for a Fiverr seller's own business.
Answer ONLY using the provided context chunks below. Do not use outside knowledge or guess.
If the answer is not covered in the context, say clearly that you don't know / it isn't covered
in the knowledge base yet, and suggest the user add it. Always cite which source file(s) your
answer came from, using their bare filename in parentheses, e.g. (gig_n8n_automation.md).
Be concise and direct."""