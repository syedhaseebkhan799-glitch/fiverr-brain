"""
Ingestion pipeline. Two entry points, both writing to the same collection:

  build_index()   -- full rebuild. Reads every KB markdown file AND every
                     seller in the store, embeds the lot, and swaps the
                     collection. Use after editing kb/ by hand.
  upsert_seller() -- incremental. Replaces exactly one seller's vectors and
                     touches nothing else. This is what the wizard and the OCR
                     import call, and it is what makes re-onboarding the same
                     seller replace rather than duplicate.

Chroma has no namespaces, so `sellerId` in the metadata is the namespace. KB
content that belongs to no single seller (policies, SOPs) is tagged with
config.SHARED_SELLER_ID so it stays retrievable whichever seller is selected.
"""
import re
import shutil
import threading
from pathlib import Path

import chromadb

from . import config, documents


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
            if path.name.endswith(".md.imported"):
                # Migrated into the store by scripts/migrate_kb_to_store.py and
                # now indexed from there. Kept on disk, deliberately silent.
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


# Bumped when the metadata written onto each chunk changes in a way that
# retrieval depends on. Version 2 added sellerId/sectionType/gigId/sourceType;
# a version 1 index has no sellerId, so a seller-filtered query against it
# matches nothing at all rather than degrading gracefully.
SCHEMA_VERSION = 2


def _index_metadata() -> dict:
    """Stamped onto the collection so a mismatch can be detected.

    Querying an index built by a *different* embedding model returns silent
    nonsense rather than a dimension error whenever the two happen to share a
    width, so the model and provider are recorded and checked on load.
    """
    return {
        "embedding_model": config.EMBEDDING_MODEL,
        "embedding_provider": config.EMBEDDING_PROVIDER,
        "schema_version": SCHEMA_VERSION,
    }


def _get_collection(client):
    """The live collection, created with the model stamp if it is missing."""
    try:
        return client.get_collection(config.COLLECTION_NAME)
    except Exception:
        return client.create_collection(
            config.COLLECTION_NAME, metadata=_index_metadata()
        )


def _chunk_documents(docs):
    """(chunks, metadatas, ids) for a list of documents from documents.py."""
    chunks, metas, ids = [], [], []
    for doc in docs:
        for i, chunk in enumerate(chunk_text(doc["text"])):
            chunks.append(chunk)
            metas.append(dict(doc["metadata"]))
            ids.append(f"{doc['id']}_{i}")
    return chunks, metas, ids


def _kb_file_records(warn):
    """(chunks, metadatas, ids) for the hand-written markdown layers."""
    chunks, metas, ids = [], [], []
    files = load_kb_files(warn=warn)

    kept = []
    for path, layer, raw_text in files:
        meta, body = parse_frontmatter(raw_text)

        # Skip the wizard's own markdown export. It is generated from the
        # profile database, so indexing it too would store every seller twice
        # -- once correctly under their sellerId, and once as shared KB content
        # visible to every other seller, which defeats the whole point of the
        # per-seller filter.
        if meta.get("type") == "profile_export":
            continue
        kept.append(path)

        file_chunks = chunk_text(body)
        if not file_chunks:
            warn(f"{path.name} has no body content after frontmatter, skipped.")
            continue
        for i, chunk in enumerate(file_chunks):
            chunks.append(chunk)
            metas.append({
                "source": path.name,
                "layer": layer,
                "gig_name": meta.get("gig_name", "N/A"),
                "category": meta.get("category", "N/A"),
                # Hand-written KB content is not owned by one seller.
                "sellerId": config.SHARED_SELLER_ID,
                "sectionType": layer,
                "gigId": "N/A",
                "sourceType": "manual",
            })
            # Layer prefix: two files with the same stem in different folders
            # would otherwise collide and silently overwrite each other.
            ids.append(f"{layer}__{path.stem}_{i}")
    return chunks, metas, ids, kept


def _seller_records(warn):
    """(chunks, metadatas, ids) for every seller in the store."""
    from . import store

    try:
        profiles = store.load_all_sellers()
    except Exception as e:
        warn(f"Could not read stored profiles, indexing KB files only: {e}")
        return [], [], [], []

    docs = []
    for profile in profiles:
        docs.extend(documents.build_documents(profile))
    chunks, metas, ids = _chunk_documents(docs)
    return chunks, metas, ids, profiles


def _build_index(verbose: bool = True, warn=None):
    """Full pipeline: load -> chunk -> embed -> store in ChromaDB.

    The existing collection is only deleted once the new embeddings have been
    computed successfully, so a failure part-way through leaves the live index
    intact instead of wiping it.
    """
    from .rag import embed

    warnings = []

    def _warn(msg):
        warnings.append(msg)
        if verbose:
            print(f"  WARNING: {msg}")
        if warn:
            warn(msg)

    file_chunks, file_metas, file_ids, files = _kb_file_records(_warn)
    seller_chunks, seller_metas, seller_ids, profiles = _seller_records(_warn)

    all_chunks = file_chunks + seller_chunks
    all_metas = file_metas + seller_metas
    all_ids = file_ids + seller_ids

    if verbose:
        print(f"  {len(files)} KB file(s) -> {len(file_chunks)} chunk(s)")
        print(f"  {len(profiles)} stored profile(s) -> {len(seller_chunks)} chunk(s)")

    if not all_chunks:
        _warn("No KB content found -- add .md files under kb/ or complete "
              "profile onboarding first. Existing index left untouched.")
        return 0

    # Embed BEFORE touching the live collection -- this is the step most
    # likely to fail (OOM, model download, API error), and it must fail safely.
    embeddings = embed(all_chunks)

    client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
    try:
        client.delete_collection(config.COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(
        config.COLLECTION_NAME, metadata=_index_metadata()
    )

    collection.add(
        documents=all_chunks,
        embeddings=embeddings,
        metadatas=all_metas,
        ids=all_ids,
    )

    _prune_orphan_segments(_warn)

    if verbose:
        print(f"Indexed {len(all_chunks)} chunks.")
        if warnings:
            print(f"Completed with {len(warnings)} warning(s).")
    return len(all_chunks)


def delete_seller_vectors(seller_id: str) -> None:
    """Drop every chunk belonging to one seller."""
    client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
    try:
        collection = client.get_collection(config.COLLECTION_NAME)
    except Exception:
        return  # nothing indexed yet
    collection.delete(where={"sellerId": seller_id})


def upsert_seller(profile, verbose: bool = False, warn=None) -> int:
    """Replace one seller's vectors. Everything else is left untouched.

    Serialised behind the same lock as a full rebuild: an upsert landing
    halfway through `create_collection` would write into a collection that is
    about to be replaced, and the seller's data would vanish.
    """
    if not _REBUILD_LOCK.acquire(blocking=False):
        raise RebuildInProgress(
            "A rebuild is already running. Wait for it to finish and try again."
        )
    try:
        return _upsert_seller(profile, verbose=verbose, warn=warn)
    finally:
        _REBUILD_LOCK.release()


def _upsert_seller(profile, verbose: bool = False, warn=None) -> int:
    from .rag import embed

    warn = warn or (lambda msg: None)
    seller_id = profile.resolved_seller_id()

    chunks, metas, ids = _chunk_documents(documents.build_documents(profile))

    # Embed first. If this fails the seller's existing vectors are still there,
    # which is the same guarantee a full rebuild gives.
    embeddings = embed(chunks) if chunks else []

    client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
    collection = _get_collection(client)

    # Delete-then-add rather than Chroma's upsert: chunk ids depend on how the
    # text splits, so a profile that got shorter would leave the tail of the
    # previous version behind and answer questions from deleted content.
    collection.delete(where={"sellerId": seller_id})

    if not chunks:
        warn(
            "Nothing to index for this seller yet — the profile has no bio, "
            "gigs, portfolio or reviews with any content in them."
        )
        return 0

    collection.add(
        documents=chunks, embeddings=embeddings, metadatas=metas, ids=ids
    )
    if verbose:
        print(f"Indexed {len(chunks)} chunk(s) for {seller_id}.")
    return len(chunks)


if __name__ == "__main__":
    build_index()
