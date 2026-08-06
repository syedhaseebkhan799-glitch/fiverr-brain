"""
Shared test setup.

Two rules the whole suite depends on:

  * No test costs money. The LLM is stubbed, the vision call is stubbed, and
    embeddings run on the local provider -- which is also why EMBEDDING_PROVIDER
    is forced here, before src.config is imported and reads it.
  * No test writes to real data. The profile database, the query log and the KB
    folder are all redirected into tmp_path by autouse fixtures, so running the
    suite can never mutate the developer's own profile or index.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Must happen before `from src import config` anywhere.
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")
os.environ.setdefault("EMBEDDING_PROVIDER", "local")

from src import config  # noqa: E402
from src.rag import FiverrBrain  # noqa: E402


@pytest.fixture(scope="session")
def brain():
    b = FiverrBrain()
    b._call_llm = lambda prompt: "[stubbed llm reply]"
    return b


@pytest.fixture(autouse=True)
def clean_history(brain):
    brain.reset_history()
    yield
    brain.reset_history()


@pytest.fixture(autouse=True)
def isolated_log(tmp_path, monkeypatch):
    """Never let a test append to the real logs/query_log.jsonl."""
    monkeypatch.setattr(config, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(config, "QUERY_LOG_FILE", tmp_path / "query_log.jsonl")


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Every test gets an empty profile database of its own."""
    monkeypatch.setattr(config, "PROFILE_DB", tmp_path / "profiles.sqlite3")


@pytest.fixture
def kb(tmp_path, monkeypatch):
    """Point Layer 1 at a scratch folder -- never edit the real kb/ in tests."""
    folder = tmp_path / "profile_gigs"
    folder.mkdir()
    monkeypatch.setitem(config.KB_FOLDERS, "profile_gigs", folder)
    return folder
