"""
Ingestion pipeline: reads KB markdown files, chunks them, embeds locally
with sentence-transformers, and stores in a local ChromaDB collection.
No external API calls needed for this step -- fully free and offline.
"""
import re
import shutil
import threading
from pathlib import Path

import chromadb

from . import config


def parse_frontmatter(text: str):
    """Split simple YAML-ish frontmatter (between --- lines) from body."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not match:
        return {}, text
    raw_meta, body = match.groups()
    meta = {}
    for line in raw_meta.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, body


def chunk_text(text: str, chunk_size: int = None, overlap: int = None):
    """Simple word-based chunker with overlap. No network dependency."""
    chunk_size = chunk_size or config.CHUNK_SIZE
    overlap = overlap or config.CHUNK_OVERLAP
    # Guard: overlap >= chunk_size makes `start` stop advancing -> infinite loop.
    if overlap >= chunk_size:
        overlap = max(0, chunk_size // 4)
    words = text.split()
    if not words:
        return []
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        if chunk.strip():
            chunks.append(chunk.strip())
        if end >= len(words):
            break
        start = end - overlap
    return chunks


def load_kb_files(warn=None):
    """Walk all KB folders and return list of (path, layer, text).

    One unreadable file must not abort the whole rebuild, and non-.md files
    are reported rather than silently ignored.
    """
    warn = warn or (lambda msg: None)
    files = []
    for layer, folder in config.KB_FOLDERS.items():
        folder = Path(folder)
        if not folder.exists():
            warn(f"KB folder missing, skipped: {folder}")
            continue
        for path in sorted(folder.iterdir()):
            if not path.is_file():
                continue
            if path.suffix.lower() != ".md":
                warn(f"Ignored (not a .md file): {path.name}")
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError) as e:
                warn(f"Could not read {path.name}, skipped: {e}")
                continue
            files.append((path, layer, text))
    return files


def _prune_orphan_segments(warn):
    """Delete segment folders no longer referenced by chroma.sqlite3.

    Each rebuild creates a new segment directory but Chroma leaves the old one
    on disk. Since data/chroma_db/ is committed so the deployed app ships with
    a prebuilt index, those orphans get committed too and bloat the repo.

    Caveat: on Windows, a segment created earlier in the *same process* stays
    mmapped and cannot be deleted. That is fine in practice -- the standard
    `python scripts/reindex.py` run is a fresh process and clears the backlog,
    and that is the run whose output gets committed. Repeated in-app rebuilds
    accumulate orphans only until the process restarts.
    """
    import sqlite3

    root = Path(config.CHROMA_PERSIST_DIR)
    db = root / "chroma.sqlite3"
    if not db.exists():
        return
    try:
        with sqlite3.connect(db) as conn:
            live = {r[0] for r in conn.execute("SELECT id FROM segments")}
    except sqlite3.Error as e:
        warn(f"Could not check for orphaned index segments: {e}")
        return

    stale = [p for p in root.iterdir() if p.is_dir() and p.name not in live]
    if not stale:
        return

    # On Windows the previous client keeps the old HNSW file mmapped, so the
    # delete fails with WinError 32 until Chroma's cached System is released.
    try:
        from chromadb.api.shared_system_client import SharedSystemClient

        SharedSystemClient.clear_system_cache()
    except Exception:
        pass

    for path in stale:
        try:
            shutil.rmtree(path)
        except OSError:
            # Still locked. Harmless -- the next rebuild in a fresh process
            # will clear it. Not worth alarming the user about.
            pass


class RebuildInProgress(RuntimeError):
    """Another rebuild is already running."""


# Streamlit serves each session on a thread of one process, so two users
# hitting "Rebuild index" together would delete and recreate the collection
# concurrently -- a reliable way to corrupt it or hit 'database is locked'.
_REBUILD_LOCK = threading.Lock()


def build_index(verbose: bool = True, warn=None):
    """Serialised wrapper -- only one rebuild may run at a time."""
    if not _REBUILD_LOCK.acquire(blocking=False):
        raise RebuildInProgress(
            "A rebuild is already running. Wait for it to finish and try again."
        )
    try:
        return _build_index(verbose=verbose, warn=warn)
    finally:
        _REBUILD_LOCK.release()


def _build_index(verbose: bool = True, warn=None):
    """Full pipeline: load -> chunk -> embed -> store in ChromaDB.

    The existing collection is only deleted once the new embeddings have been
    computed successfully, so a failure part-way through leaves the live index
    intact instead of wiping it.
    """
    from .rag import get_embed_model

    warnings = []

    def _warn(msg):
        warnings.append(msg)
        if verbose:
            print(f"  WARNING: {msg}")
        if warn:
            warn(msg)

    model = get_embed_model()

    all_chunks, all_metas, all_ids = [], [], []
    files = load_kb_files(warn=_warn)

    for path, layer, raw_text in files:
        meta, body = parse_frontmatter(raw_text)
        chunks = chunk_text(body)
        if not chunks:
            _warn(f"{path.name} has no body content after frontmatter, skipped.")
            continue
        for i, chunk in enumerate(chunks):
            all_chunks.append(chunk)
            all_metas.append({
                "source": path.name,
                "layer": layer,
                "gig_name": meta.get("gig_name", "N/A"),
                "category": meta.get("category", "N/A"),
            })
            # Layer prefix: two files with the same stem in different folders
            # would otherwise collide and silently overwrite each other.
            all_ids.append(f"{layer}__{path.stem}_{i}")
        if verbose:
            print(f"  chunked {path.name} -> {len(chunks)} chunk(s)")

    if not all_chunks:
        _warn("No KB content found -- add .md files under kb/ first. "
              "Existing index left untouched.")
        return 0

    # Embed BEFORE touching the live collection -- this is the step most
    # likely to fail (OOM, model download), and we want it to fail safely.
    raw_embeddings = model.encode(all_chunks, show_progress_bar=verbose)
    embeddings = raw_embeddings.tolist() if hasattr(raw_embeddings, "tolist") else list(raw_embeddings)

    client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
    try:
        client.delete_collection(config.COLLECTION_NAME)
    except Exception:
        pass
    # Stamp the model in. Querying an index built by a *different* embedding
    # model returns silent nonsense (both MiniLM variants are 384-dim, so
    # there is no dimension error to catch it) -- rag.py checks this on load.
    collection = client.create_collection(
        config.COLLECTION_NAME,
        metadata={"embedding_model": config.EMBEDDING_MODEL},
    )

    collection.add(
        documents=all_chunks,
        embeddings=embeddings,
        metadatas=all_metas,
        ids=all_ids,
    )

    _prune_orphan_segments(_warn)

    if verbose:
        print(f"Indexed {len(all_chunks)} chunks from {len(files)} file(s).")
        if warnings:
            print(f"Completed with {len(warnings)} warning(s).")
    return len(all_chunks)


if __name__ == "__main__":
    build_index()
