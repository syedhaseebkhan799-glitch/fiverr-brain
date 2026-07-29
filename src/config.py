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