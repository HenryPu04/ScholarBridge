from app.models.paper import PaperResult


class SearchResult(PaperResult):
    """PaperResult enriched with search-quality metadata."""

    relevance_score: float = 0.0
    # The chunk of text from the paper that most closely matched the query.
    # None for Semantic Scholar fallback results (no vectors in Pinecone yet).
    matched_chunk_text: str | None = None
    # "pinecone" for vector search results; "semantic_scholar_fallback" when
    # Pinecone returned 0 matches and we fell back to keyword search.
    search_source: str = "pinecone"
