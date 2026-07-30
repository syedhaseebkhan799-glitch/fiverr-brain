"""
Core RAG logic: embed the question, retrieve top matching chunks from
ChromaDB, build a grounded prompt, and call OpenAI for the answer.
"""
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer
from openai import OpenAI

from . import config


class FiverrBrain:
    def __init__(self):
        if not config.OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to your .env file first."
            )
        self.client_llm = OpenAI(api_key=config.OPENAI_API_KEY)
        self.embed_model = SentenceTransformer(config.EMBEDDING_MODEL)
        self.client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
        self.collection = self.client.get_or_create_collection(config.COLLECTION_NAME)
        self.history = []  # simple in-memory session history: list of (role, text)

    def refresh_collection(self):
        self.client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
        self.collection = self.client.get_or_create_collection(config.COLLECTION_NAME)
        self.history = []  # simple in-memory session history: list of (role, text)

    def _call_llm(self, prompt: str) -> str:
        response = self.client_llm.chat.completions.create(
            model=config.OPENAI_MODEL,
            max_tokens=1000,
            messages=[
                {"role": "system", "content": config.SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content

    def retrieve(self, question: str, top_k: int = None, layer_filter: str = None):
        top_k = top_k or config.TOP_K
        raw = self.embed_model.encode([question])
        query_embedding = raw.tolist() if hasattr(raw, "tolist") else list(raw)

        where = {"layer": layer_filter} if layer_filter else None

        try:
            results = self.collection.query(
                query_embeddings=query_embedding,
                n_results=top_k,
                where=where,
            )
        except Exception:
            self.refresh_collection()
            results = self.collection.query(
                query_embeddings=query_embedding,
                n_results=top_k,
                where=where,
            )

        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        return list(zip(docs, metas))

    def _build_prompt(self, question: str, chunks):
        if not chunks:
            context_block = "(No relevant context found in the knowledge base.)"
        else:
            parts = []
            for doc, meta in chunks:
                src = Path(meta.get("source", "unknown")).name
                parts.append(f"[Source: {src}]\n{doc}")
            context_block = "\n\n---\n\n".join(parts)

        history_block = ""
        if self.history:
            recent = self.history[-6:]  # last few turns for light memory
            history_block = "\n".join(f"{role}: {text}" for role, text in recent)
            history_block = f"Conversation so far:\n{history_block}\n\n"

        prompt = (
            f"{history_block}"
            f"Context chunks:\n{context_block}\n\n"
            f"Question: {question}\n\n"
            f"Answer using only the context above. Cite sources by bare filename."
        )
        return prompt

    def ask(self, question: str, layer_filter: str = None):
        chunks = self.retrieve(question, layer_filter=layer_filter)
        prompt = self._build_prompt(question, chunks)
        answer = self._call_llm(prompt)

        self.history.append(("User", question))
        self.history.append(("Assistant", answer))

        sources = sorted({Path(meta.get("source", "unknown")).name for _, meta in chunks})
        return {"answer": answer, "sources": sources, "chunks_used": len(chunks)}

    def reset_history(self):
        self.history = []