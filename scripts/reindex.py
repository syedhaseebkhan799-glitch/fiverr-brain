"""
Standalone script to rebuild the vector index from the current kb/ folder.
Run whenever you add, edit, or remove knowledge base files:

    python scripts/reindex.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import ingest

if __name__ == "__main__":
    ingest.build_index(verbose=True)
