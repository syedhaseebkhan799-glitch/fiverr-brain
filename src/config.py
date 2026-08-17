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

# --- LLM settings (Claude / Anthropic) ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5")

# Effort controls how much the model thinks before answering, and so how much
# it costs and how long the user waits. Answers here are short and grounded in
# retrieved chunks, not open-ended reasoning, so "low" is the right default.
LLM_EFFORT = os.getenv("LLM_EFFORT", "low")

# --- Embeddings ---
# Anthropic has no embeddings endpoint, so the vector half of the app is a
# separate decision from the LLM. Two providers, one switch:
#   "local"  -- all-MiniLM-L6-v2 via sentence-transformers. Free, offline, and
#               what the committed index was built with, so the app works with
#               nothing but an ANTHROPIC_API_KEY.
#   "openai" -- text-embedding-3-small. Better retrieval, fixes the documented
#               non-English weakness, but needs a second (OpenAI) key and costs
#               money per query and per reindex.
# Changing this invalidates the existing index (rebuild required) AND the
# relevance threshold below, which is calibrated per provider.
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "local").strip().lower()

# Only read when EMBEDDING_PROVIDER is "openai". The chat and vision paths do
# not touch it.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

_DEFAULT_EMBEDDING_MODEL = {
    "openai": "text-embedding-3-small",
    "local": "all-MiniLM-L6-v2",
}.get(EMBEDDING_PROVIDER, "all-MiniLM-L6-v2")

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

# What we want back as prose. Kept modest so a draft is a draft, not an essay.
MAX_ANSWER_TOKENS = 2000
# Claude's `max_tokens` caps thinking AND the visible answer together, so the
# request needs headroom above the answer budget or a thinking-heavy turn gets
# truncated mid-sentence and the user sees half a reply.
THINKING_HEADROOM_TOKENS = 6000
MAX_OUTPUT_TOKENS = MAX_ANSWER_TOKENS + THINKING_HEADROOM_TOKENS

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
    or MAX_DISTANCE_BY_PROVIDER.get(EMBEDDING_PROVIDER, 1.49)
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
VISION_MODEL = os.getenv("VISION_MODEL", "claude-opus-5")

# Reading a layout off a screenshot is worth more thought than answering from
# retrieved text, so this sits a step above LLM_EFFORT.
VISION_EFFORT = os.getenv("VISION_EFFORT", "medium")

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