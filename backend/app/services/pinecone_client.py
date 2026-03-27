"""
Thin Pinecone Serverless wrapper.

Responsibilities:
  - Connect to Pinecone and create the index if it doesn't exist
  - upsert_vectors()  — used by the indexing pipeline
  - query_vectors()   — used by the Phase 2 semantic search service

Vector schema
-------------
id:      "{paper_id}__chunk_{chunk_index}"
values:  list[float]  (768 dimensions — text-embedding-004 with output_dimensionality=768)
metadata:
  paper_id:     str
  chunk_index:  int
  text:         str   (raw chunk text, returned in search results)
  title:        str
  authors:      str   (comma-joined author names)
  year:         int | None
  source:       "full_paper" | "abstract_only"
"""

import logging
from typing import Any

from pinecone import Pinecone, ServerlessSpec

from app.config import get_settings

logger = logging.getLogger(__name__)

DIMENSIONS = 768
METRIC = "cosine"
UPSERT_BATCH_SIZE = 100  # Pinecone free-tier safe limit


class PineconeClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._pc = Pinecone(api_key=settings.pinecone_api_key)
        index_name = settings.pinecone_index_name

        existing = [idx.name for idx in self._pc.list_indexes()]
        if index_name not in existing:
            logger.info("Pinecone index '%s' not found — creating.", index_name)
            self._pc.create_index(
                name=index_name,
                dimension=DIMENSIONS,
                metric=METRIC,
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )
            logger.info("Pinecone index '%s' created.", index_name)
        else:
            logger.info("Pinecone index '%s' already exists.", index_name)

        self._index = self._pc.Index(index_name)

    def upsert_vectors(self, vectors: list[dict[str, Any]]) -> None:
        """Upsert vectors in batches of UPSERT_BATCH_SIZE."""
        for i in range(0, len(vectors), UPSERT_BATCH_SIZE):
            batch = vectors[i : i + UPSERT_BATCH_SIZE]
            self._index.upsert(vectors=batch)
            logger.debug("Upserted batch %d–%d (%d vectors).", i, i + len(batch), len(batch))
        logger.info("Upserted %d vectors total.", len(vectors))

    def query_vectors(
        self,
        embedding: list[float],
        top_k: int = 10,
        filter: dict | None = None,
    ) -> list[dict[str, Any]]:
        """Query the index and return matches with metadata."""
        response = self._index.query(
            vector=embedding,
            top_k=top_k,
            include_metadata=True,
            filter=filter,
        )
        return response.get("matches", [])

    def delete_paper_vectors(self, paper_id: str) -> None:
        """Delete all vectors for a paper (used if re-indexing is needed)."""
        self._index.delete(filter={"paper_id": {"$eq": paper_id}})
        logger.info("Deleted all vectors for paper '%s'.", paper_id)


# ---------------------------------------------------------------------------
# Module-level singleton — mirrors the pattern in semantic_scholar.py
# ---------------------------------------------------------------------------

_client_instance: PineconeClient | None = None


def get_pinecone_client() -> PineconeClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = PineconeClient()
    return _client_instance
