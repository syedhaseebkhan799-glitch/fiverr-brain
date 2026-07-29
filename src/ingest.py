"""
Ingestion pipeline: reads KB markdown files, chunks them, embeds locally
with sentence-transformers, and stores in a local ChromaDB collection.
No external API calls needed for this step -- fully free and offline.
"""
import re
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

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


def load_kb_files():
    """Walk all KB folders and return list of (path, layer, text)."""
    files = []
    for layer, folder in config.KB_FOLDERS.items():
        folder = Path(folder)
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            files.append((path, layer, text))
    return files


def build_index(verbose: bool = True):
    """Full pipeline: load -> chunk -> embed -> store in ChromaDB."""
    model = SentenceTransformer(config.EMBEDDING_MODEL)

    client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
    # Fresh collection each rebuild to avoid stale duplicates
    try:
        client.delete_collection(config.COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(config.COLLECTION_NAME)

    all_chunks, all_metas, all_ids = [], [], []
    files = load_kb_files()

    for path, layer, raw_text in files:
        meta, body = parse_frontmatter(raw_text)
        chunks = chunk_text(body)
        for i, chunk in enumerate(chunks):
            all_chunks.append(chunk)
            all_metas.append({
                "source": path.name,
                "layer": layer,
                "gig_name": meta.get("gig_name", "N/A"),
                "category": meta.get("category", "N/A"),
            })
            all_ids.append(f"{path.stem}_{i}")
        if verbose:
            print(f"  chunked {path.name} -> {len(chunks)} chunk(s)")

    if not all_chunks:
        if verbose:
            print("No KB content found -- add .md files under kb/ first.")
        return 0

    raw_embeddings = model.encode(all_chunks, show_progress_bar=verbose)
    embeddings = raw_embeddings.tolist() if hasattr(raw_embeddings, "tolist") else list(raw_embeddings)

    collection.add(
        documents=all_chunks,
        embeddings=embeddings,
        metadatas=all_metas,
        ids=all_ids,
    )

    if verbose:
        print(f"Indexed {len(all_chunks)} chunks from {len(files)} file(s).")
    return len(all_chunks)


if __name__ == "__main__":
    build_index()
