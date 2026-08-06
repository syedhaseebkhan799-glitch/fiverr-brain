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

# --- Embeddings ---
# Two providers, one switch:
#   "openai" -- text-embedding-3-small. Better retrieval, fixes the documented
#               non-English weakness, costs money per query and per reindex.
#   "local"  -- all-MiniLM-L6-v2 via sentence-transformers. Free, offline.
# Changing this invalidates the existing index (rebuild required) AND the
# relevance threshold below, which is calibrated per provider.
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "openai").strip().lower()

_DEFAULT_EMBEDDING_MODEL = {
    "openai": "text-embedding-3-small",
    "local": "all-MiniLM-L6-v2",
}.get(EMBEDDING_PROVIDER, "text-embedding-3-small")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", _DEFAULT_EMBEDDING_MODEL)

# --- Vector store ---
CHROMA_PERSIST_DIR = str(PROJECT_ROOT / "data" / "chroma_db")
COLLECTION_NAME = "fiverr_brain_kb"

# Chroma has no namespaces. A metadata filter on sellerId is the equivalent,
# and is what makes "re-onboarding replaces that seller's vectors" possible.
# Content that belongs to no single seller (policies, SOPs) is tagged shared
# so it stays retrievable whichever seller is selected.
SHARED_SELLER_ID = "__shared__"

# --- Knowledge base folders ---
KB_DIR = PROJECT_ROOT / "kb"
KB_FOLDERS = {
    "profile_gigs": KB_DIR / "profile_gigs",
    "policies": KB_DIR / "policies",
    "sops": KB_DIR / "sops",
}

# --- Chunking ---
# The target is ~400 tokens with ~50 overlap. The chunker counts words, not
# tokens, to avoid a tiktoken dependency: English prose runs about 1.33 tokens
# per word, so 300 words is ~400 tokens and 38 words is ~50. Accurate to within
# roughly 10%, which does not change retrieval quality at this chunk size.
CHUNK_TOKENS = 400
CHUNK_OVERLAP_TOKENS = 50
TOKENS_PER_WORD = 1.33

CHUNK_SIZE = int(CHUNK_TOKENS / TOKENS_PER_WORD)            # 300 words
CHUNK_OVERLAP = int(CHUNK_OVERLAP_TOKENS / TOKENS_PER_WORD)  # 37 words

# --- Retrieval ---
TOP_K = 5

# --- Limits ---
# Cap what we send so a huge paste can't overflow the context window,
# and cap what comes back so long drafts aren't cut off mid-sentence.
MAX_INPUT_CHARS = 8000      # per user message, before it reaches the prompt
MAX_PROMPT_CHARS = 24000    # whole assembled prompt (~6k tokens)
MAX_OUTPUT_TOKENS = 2000

# Distance above which a retrieved chunk is treated as irrelevant. This is the
# single value that makes "I don't know" possible, and it is calibrated per
# embedding provider -- the two models put their vectors on different scales,
# so a threshold measured against one is meaningless against the other.
#
#   local  : MEASURED with scripts/check_threshold.py. Re-measured 2026-08-06
#            after the chunk size and document structure changed: real topical
#            matches now span 0.79-1.43 and off-topic 1.58-2.04, so 1.49 still
#            sits in the gap and all 11 calibration cases classify correctly.
#            The margin is narrow because the KB is small.
#   openai : ESTIMATE, NOT YET MEASURED. Both models emit unit-norm vectors and
#            Chroma's default space is squared L2 (= 2 - 2*cosine), so the
#            scales are comparable, but the actual spread has not been observed
#            on a real index. Run scripts/check_threshold.py once an API key is
#            available and replace this number with what it suggests.
MAX_DISTANCE_BY_PROVIDER = {
    "local": 1.49,
    "openai": 1.35,
}
MAX_DISTANCE = float(
    os.getenv("MAX_DISTANCE")
    or MAX_DISTANCE_BY_PROVIDER.get(EMBEDDING_PROVIDER, 1.35)
)

# True while the active provider's threshold is the unmeasured estimate, so the
# UI can say so rather than quietly trusting a guessed refusal boundary.
MAX_DISTANCE_IS_ESTIMATED = (
    EMBEDDING_PROVIDER == "openai" and not os.getenv("MAX_DISTANCE")
)


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

# --- Structured profile storage ---
# Tables shaped the way the Prisma models in the brief would be, so moving to
# Postgres later is a driver swap rather than a redesign.
PROFILE_DB = PROJECT_ROOT / "data" / "fiverr_brain.sqlite3"

# --- Screenshot OCR import ---
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_FORMATS = {"PNG", "JPEG", "WEBP", "GIF", "BMP"}
VISION_MODEL = os.getenv("VISION_MODEL", "gpt-4o-mini")

# Below this share of populated fields, an extraction is reported as
# low-confidence and the user is sent to the manual form instead of saving
# a profile made mostly of nulls.
OCR_MIN_CONFIDENCE = 0.15

# --- Guardrail system prompt ---
SYSTEM_PROMPT = """You are Fiverr Brain, an internal assistant for a Fiverr seller's own business.
Answer ONLY using the provided context chunks below. Do not use outside knowledge or guess.
If the answer is not covered in the context, say clearly that you don't know / it isn't covered
in the knowledge base yet, and suggest the user add it. Always cite which source file(s) your
answer came from, using their bare filename in parentheses, e.g. (gig_n8n_automation.md).
Be concise and direct."""