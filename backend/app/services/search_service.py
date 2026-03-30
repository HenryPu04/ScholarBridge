"""
Semantic Search Service
========================
Orchestrates the full search pipeline:

1. Query Expansion   — Gemini Flash generates 3 academic phrases from the user query
2. Embed             — gemini-embedding-001 (768 dims) embeds the expanded query
3. Parallel Search   — Pinecone vector search and Semantic Scholar keyword search run
                       concurrently via asyncio; neither blocks the other
4. Threshold filter  — Pinecone results below SIMILARITY_THRESHOLD are discarded
5. Deduplicate       — best chunk per paper_id within Pinecone results
6. Hybrid re-rank    — FinalScore = sim×0.8 + norm_citations×0.2 (Pinecone results only)
7. Merge             — Pinecone results (sorted by relevance) + SS-only results;
                       papers present in both get Pinecone relevance + SS metadata enrichment
"""

import asyncio
import logging

from google.genai import types as genai_types

from app.config import get_settings
from app.models.paper import Author, PaperResult
from app.models.search import SearchResult
from app.services.indexing_pipeline import EMBED_DIMENSIONS, _get_genai_client
from app.services.pinecone_client import get_pinecone_client
from app.services.semantic_scholar import SemanticScholarService, get_semantic_scholar_service

logger = logging.getLogger(__name__)

EMBED_MODEL = "gemini-embedding-001"   # must match indexing_pipeline.py
FLASH_MODEL = "gemini-2.5-flash"
SIMILARITY_THRESHOLD = 0.55   # minimum score to include a Pinecone result
PROMOTION_THRESHOLD = 0.72    # above this → promoted to top of merged list


class SearchService:
    def __init__(self, ss_service: SemanticScholarService) -> None:
        self._ss = ss_service

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        limit: int = 10,
        year_min: int | None = None,
        year_max: int | None = None,
        fields_of_study: list[str] | None = None,
        open_access_only: bool = False,
    ) -> list[SearchResult]:
        settings = get_settings()
        use_mock = settings.use_mock_api or settings.gemini_api_key is None

        # ------------------------------------------------------------------
        # Step 1 — Query Expansion
        # ------------------------------------------------------------------
        expanded_query = query
        if not use_mock:
            expanded_query = await self._expand_query(query)

        # ------------------------------------------------------------------
        # Step 2 — Embed expanded query
        # ------------------------------------------------------------------
        query_embedding: list[float] | None = None
        if not use_mock:
            try:
                client = _get_genai_client()
                response = client.models.embed_content(
                    model=EMBED_MODEL,
                    contents=expanded_query,
                    config=genai_types.EmbedContentConfig(
                        output_dimensionality=EMBED_DIMENSIONS,
                    ),
                )
                query_embedding = response.embeddings[0].values
            except Exception as exc:
                logger.warning("Query embedding failed (%s) — Pinecone search skipped.", exc)

        # ------------------------------------------------------------------
        # Step 3 — Parallel search: kick off SS immediately, then run Pinecone
        # ------------------------------------------------------------------
        ss_task = asyncio.create_task(
            self._ss.search_papers(
                query=query,          # original query, not expanded
                limit=limit,
                year_min=year_min,
                year_max=year_max,
                open_access_only=open_access_only,
            )
        )

        pinecone_results: list[SearchResult] = []
        if query_embedding is not None:
            pinecone_results = self._query_pinecone(
                query_embedding=query_embedding,
                limit=limit,
                year_min=year_min,
                year_max=year_max,
                fields_of_study=fields_of_study or [],
            )

        try:
            ss_papers = await ss_task
        except Exception as exc:
            logger.warning("Semantic Scholar search failed (%s) — using Pinecone results only.", exc)
            ss_papers = []

        # ------------------------------------------------------------------
        # Step 4 — Merge and return
        # ------------------------------------------------------------------
        return self._merge(
            pinecone_results=pinecone_results,
            ss_papers=ss_papers,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # Step 1 helper — Query Expansion via Gemini Flash
    # ------------------------------------------------------------------

    async def _expand_query(self, query: str) -> str:
        prompt = (
            "You are a research librarian. A non-profit worker is searching for academic papers.\n"
            f'Their query is: "{query}"\n\n'
            "Generate exactly 3 academic technical phrases or keywords that would appear in "
            "relevant peer-reviewed research. Output one phrase per line, no numbering, no "
            "explanation — just the 3 phrases."
        )
        try:
            client = _get_genai_client()
            response = client.models.generate_content(
                model=FLASH_MODEL,
                contents=prompt,
            )
            raw = response.text.strip()
            phrases = [line.strip() for line in raw.splitlines() if line.strip()][:3]
            if phrases:
                expanded = query + " " + " ".join(phrases)
                logger.info(
                    "Query expanded: %r → %r (added %d phrase(s))",
                    query,
                    expanded,
                    len(phrases),
                )
                return expanded
        except Exception as exc:
            logger.warning("Query expansion failed (%s) — using original query.", exc)
        return query

    # ------------------------------------------------------------------
    # Pinecone query + threshold filter + deduplicate + hybrid re-rank
    # ------------------------------------------------------------------

    def _query_pinecone(
        self,
        query_embedding: list[float],
        limit: int,
        year_min: int | None,
        year_max: int | None,
        fields_of_study: list[str],
    ) -> list[SearchResult]:
        # Build metadata filter
        clauses: list[dict] = []
        if year_min:
            clauses.append({"year": {"$gte": year_min}})
        if year_max:
            clauses.append({"year": {"$lte": year_max}})
        if fields_of_study:
            clauses.append({"fields_of_study": {"$in": fields_of_study}})

        pin_filter: dict | None = None
        if len(clauses) == 1:
            pin_filter = clauses[0]
        elif len(clauses) > 1:
            pin_filter = {"$and": clauses}

        # Over-fetch to allow per-paper deduplication
        raw_matches = get_pinecone_client().query_vectors(
            embedding=query_embedding,
            top_k=limit * 5,
            filter=pin_filter,
        )

        if not raw_matches:
            return []

        # Deduplicate: keep best chunk per paper_id
        best: dict[str, dict] = {}
        for match in raw_matches:
            pid = match.get("metadata", {}).get("paper_id", match["id"].split("__chunk_")[0])
            if pid not in best or match["score"] > best[pid]["score"]:
                best[pid] = match

        deduped = list(best.values())

        # Discard results where even the best match is below threshold.
        # This prevents low-quality OCR chunks from surfacing for off-topic queries.
        deduped = [m for m in deduped if m["score"] >= SIMILARITY_THRESHOLD]

        if not deduped:
            logger.info(
                "All Pinecone scores below inclusion threshold (%.2f) — "
                "SS results will fill the response.",
                SIMILARITY_THRESHOLD,
            )
            return []

        # Hybrid re-rank: FinalScore = sim×0.8 + norm_citations×0.2
        max_cit = max(
            (m["metadata"].get("citation_count") or 0 for m in deduped),
            default=1,
        )
        max_cit = max(max_cit, 1)  # prevent divide-by-zero

        for m in deduped:
            sim = float(m["score"])
            cit = (m["metadata"].get("citation_count") or 0) / max_cit
            m["final_score"] = round(sim * 0.8 + cit * 0.2, 4)

        deduped.sort(key=lambda m: m["final_score"], reverse=True)

        return [self._match_to_search_result(m) for m in deduped[:limit]]

    # ------------------------------------------------------------------
    # Merge Pinecone + SS results
    # ------------------------------------------------------------------

    def _merge(
        self,
        pinecone_results: list[SearchResult],
        ss_papers: list[PaperResult],
        limit: int,
    ) -> list[SearchResult]:
        """
        Three-tier merge:

        - Promoted  (relevance_score > PROMOTION_THRESHOLD): always first — these are
                    high-confidence library matches.
        - Mid-tier  (SIMILARITY_THRESHOLD–PROMOTION_THRESHOLD): interleaved with
                    SS-only results by score; a highly-cited SS paper can outrank a
                    marginal Pinecone match.
        - SS-only   (not in Pinecone): scored by citation count (capped at 0.50) so
                    they rank cleanly against mid-tier Pinecone results.

        search_source:
          "pinecone"         — paper is indexed in your library
          "semantic_scholar" — found on the web, not yet indexed
        """
        ss_by_id: dict[str, PaperResult] = {p.paper_id: p for p in ss_papers}
        pinecone_ids: set[str] = {r.paper_id for r in pinecone_results}

        # Shared citation ceiling for consistent score normalisation across both sources
        max_cit = max(
            [r.citation_count or 0 for r in pinecone_results]
            + [p.citation_count or 0 for p in ss_papers]
            + [1],
        )

        # Enrich and split Pinecone results into promoted / mid-tier
        promoted: list[SearchResult] = []
        mid_tier: list[SearchResult] = []

        for pr in pinecone_results:
            ss_match = ss_by_id.get(pr.paper_id)
            if ss_match:
                pr = pr.model_copy(update={
                    "abstract": pr.abstract or ss_match.abstract,
                    "open_access_pdf": pr.open_access_pdf or ss_match.open_access_pdf,
                    "venue": pr.venue or ss_match.venue,
                    "citation_count": pr.citation_count or ss_match.citation_count,
                })
            if pr.relevance_score > PROMOTION_THRESHOLD:
                promoted.append(pr)
            else:
                mid_tier.append(pr)

        # SS-only results: citation-based score (max 0.50 — no similarity component)
        ss_only: list[SearchResult] = []
        for paper in ss_papers:
            if paper.paper_id not in pinecone_ids:
                cit_score = round((paper.citation_count or 0) / max_cit * 0.5, 4)
                ss_only.append(
                    SearchResult(
                        **paper.model_dump(),
                        relevance_score=cit_score,
                        matched_chunk_text=None,
                        search_source="semantic_scholar",
                    )
                )

        # Interleave mid-tier Pinecone + SS-only by relevance_score
        mixed = sorted(mid_tier + ss_only, key=lambda r: r.relevance_score, reverse=True)

        merged = promoted + mixed

        logger.info(
            "Search merge: %d promoted + %d mid-tier pinecone + %d ss-only = %d total (limit=%d)",
            len(promoted),
            len(mid_tier),
            len(ss_only),
            len(merged),
            limit,
        )

        return merged[:limit]

    def _match_to_search_result(self, match: dict) -> SearchResult:
        meta = match.get("metadata", {})

        # Reconstruct minimal Author list from stored comma-joined string
        authors_str: str = meta.get("authors", "")
        authors = [Author(name=n.strip()) for n in authors_str.split(",") if n.strip()]

        return SearchResult(
            paper_id=meta.get("paper_id", match["id"]),
            title=meta.get("title", "Unknown Title"),
            abstract=None,   # not stored in Pinecone — enriched from SS in _merge if available
            authors=authors,
            year=meta.get("year"),
            citation_count=meta.get("citation_count"),
            fields_of_study=meta.get("fields_of_study") or [],
            open_access_pdf=None,
            venue=None,
            external_ids=None,
            relevance_score=match["final_score"],
            matched_chunk_text=meta.get("text"),
            search_source="pinecone",
        )


# ---------------------------------------------------------------------------
# Singleton factory — mirrors the pattern in semantic_scholar.py
# ---------------------------------------------------------------------------

_search_service_instance: SearchService | None = None


def get_search_service() -> SearchService:
    global _search_service_instance
    if _search_service_instance is None:
        _search_service_instance = SearchService(
            ss_service=get_semantic_scholar_service(),
        )
    return _search_service_instance
