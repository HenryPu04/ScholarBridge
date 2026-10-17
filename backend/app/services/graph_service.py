"""
Citation graph traversal service.

Fetches citation and reference relationships from Semantic Scholar, cross-references
local SQLite for indexed status, and optionally adds semantic_peer edges via Pinecone
cosine similarity between indexed papers' stored embeddings.
"""

import logging
import math
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Paper
from app.models.graph import CitationGraphResponse, GraphEdge, GraphNode
from app.services.semantic_scholar import SemanticScholarError, SemanticScholarService

logger = logging.getLogger(__name__)

# Minimum cosine similarity to emit a semantic_peer edge.
_PEER_THRESHOLD = 0.70


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


async def _fetch_indexed_ids(db: AsyncSession, paper_ids: list[str]) -> set[str]:
    """
    Return the subset of `paper_ids` that are present in the local papers table.
    Checks both paper_id and ss_paper_id columns.
    """
    if not paper_ids:
        return set()

    result = await db.execute(
        select(Paper.paper_id, Paper.ss_paper_id).where(
            Paper.paper_id.in_(paper_ids)
        )
    )
    rows = result.all()
    indexed: set[str] = set()
    for row in rows:
        if row.paper_id:
            indexed.add(row.paper_id)
        if row.ss_paper_id and row.ss_paper_id in paper_ids:
            indexed.add(row.ss_paper_id)
    return indexed


async def _fetch_embedding_for_paper(paper_id: str) -> Optional[list[float]]:
    """
    Attempt to fetch the first chunk embedding for a paper from Pinecone.
    Returns None if unavailable (no API key, paper not indexed, etc.).
    Failures are swallowed — semantic_peer edges are optional.
    """
    try:
        from app.services.pinecone_client import get_pinecone_client  # noqa: PLC0415
        pc = get_pinecone_client()
        # Query with a zero vector to fetch by metadata filter; fetch=1 vector by ID
        results = pc.query_vectors(
            embedding=[0.0] * 768,
            top_k=1,
            filter={"paper_id": {"$eq": paper_id}},
        )
        if results:
            return results[0].get("values")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not fetch embedding for %s: %s", paper_id, exc)
    return None


async def build_citation_graph(
    root_id: str,
    db: AsyncSession,
    ss_service: SemanticScholarService,
    depth: int = 1,
    max_nodes: int = 10,
) -> CitationGraphResponse:
    """
    Build a citation graph rooted at `root_id`.

    Strategy
    --------
    1. Fetch root paper details from Semantic Scholar.
    2. BFS up to `depth` hops, collecting citation and reference lists.
       Stop expanding once `max_nodes` is reached.
    3. Query SQLite to mark which nodes are already indexed locally.
    4. For each pair of indexed nodes, attempt a Pinecone embedding lookup
       and emit a "semantic_peer" edge when similarity >= 0.70.
    5. Return a CitationGraphResponse.
    """
    nodes_map: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    seen_edge_keys: set[tuple[str, str, str]] = set()

    # ------------------------------------------------------------------ #
    # Step 1 — fetch root paper
    # ------------------------------------------------------------------ #
    try:
        root_detail = await ss_service.get_paper_details(root_id)
    except SemanticScholarError as exc:
        raise exc  # caller converts to 404/502

    pdf_url = root_detail.open_access_pdf.url if root_detail.open_access_pdf else None

    # We populate is_indexed after collecting all IDs; placeholder False for now.
    nodes_map[root_id] = GraphNode(
        id=root_id,
        title=root_detail.title,
        year=root_detail.year,
        citation_count=root_detail.citation_count or 0,
        is_indexed=False,
        open_access_pdf_url=pdf_url,
    )

    # ------------------------------------------------------------------ #
    # Step 2 — BFS traversal over citations/references
    # ------------------------------------------------------------------ #
    # Each frontier item is (paper_id, current_depth)
    frontier: list[tuple[str, int]] = [(root_id, 0)]
    visited: set[str] = {root_id}

    # Fetch citation and reference lists from SS.
    # The /paper/{id} endpoint supports fields=citations,references.
    async def _fetch_neighbors(paper_id: str) -> tuple[list[dict], list[dict]]:
        """Returns (citations_list, references_list) — raw SS dicts."""
        try:
            data = await ss_service._get(
                f"/paper/{paper_id}",
                {"fields": "citations,references,title,year,citationCount,openAccessPdf"},
            )
            citations = data.get("citations") or []
            references = data.get("references") or []
            return citations, references
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not fetch neighbors for %s: %s", paper_id, exc)
            return [], []

    while frontier:
        current_id, current_depth = frontier.pop(0)

        if current_depth >= depth:
            # Don't expand further, but we've already added the node
            continue

        if len(nodes_map) >= max_nodes:
            break

        citations, references = await _fetch_neighbors(current_id)

        # citations: papers that cite current_id  → edge: neighbor --cites--> current_id
        for cited_paper in citations:
            if not isinstance(cited_paper, dict):
                continue
            neighbor_id = cited_paper.get("paperId") or cited_paper.get("paper_id")
            if not neighbor_id or neighbor_id == current_id:
                continue
            if len(nodes_map) >= max_nodes:
                break

            # Add node if new
            if neighbor_id not in nodes_map:
                title = cited_paper.get("title") or "Untitled"
                year = cited_paper.get("year")
                cc = cited_paper.get("citationCount") or 0
                oap = cited_paper.get("openAccessPdf")
                oap_url = oap.get("url") if isinstance(oap, dict) else None
                nodes_map[neighbor_id] = GraphNode(
                    id=neighbor_id,
                    title=title,
                    year=year,
                    citation_count=cc,
                    is_indexed=False,
                    open_access_pdf_url=oap_url,
                )
            # Directional edge: neighbor cites current_id
            edge_key = (neighbor_id, current_id, "cites")
            if edge_key not in seen_edge_keys:
                seen_edge_keys.add(edge_key)
                edges.append(GraphEdge(source=neighbor_id, target=current_id, relation_type="cites"))

            if neighbor_id not in visited:
                visited.add(neighbor_id)
                frontier.append((neighbor_id, current_depth + 1))

        # references: papers that current_id cites  → edge: current_id --cites--> neighbor
        for ref_paper in references:
            if not isinstance(ref_paper, dict):
                continue
            neighbor_id = ref_paper.get("paperId") or ref_paper.get("paper_id")
            if not neighbor_id or neighbor_id == current_id:
                continue
            if len(nodes_map) >= max_nodes:
                break

            if neighbor_id not in nodes_map:
                title = ref_paper.get("title") or "Untitled"
                year = ref_paper.get("year")
                cc = ref_paper.get("citationCount") or 0
                oap = ref_paper.get("openAccessPdf")
                oap_url = oap.get("url") if isinstance(oap, dict) else None
                nodes_map[neighbor_id] = GraphNode(
                    id=neighbor_id,
                    title=title,
                    year=year,
                    citation_count=cc,
                    is_indexed=False,
                    open_access_pdf_url=oap_url,
                )
            # Directional edge: current_id cites neighbor  (cited_by from neighbor's perspective)
            edge_key = (current_id, neighbor_id, "cites")
            if edge_key not in seen_edge_keys:
                seen_edge_keys.add(edge_key)
                edges.append(GraphEdge(source=current_id, target=neighbor_id, relation_type="cites"))

            if neighbor_id not in visited:
                visited.add(neighbor_id)
                frontier.append((neighbor_id, current_depth + 1))

    # ------------------------------------------------------------------ #
    # Step 3 — mark indexed nodes
    # ------------------------------------------------------------------ #
    all_ids = list(nodes_map.keys())
    indexed_ids = await _fetch_indexed_ids(db, all_ids)
    for pid, node in nodes_map.items():
        nodes_map[pid] = node.model_copy(update={"is_indexed": pid in indexed_ids})

    # ------------------------------------------------------------------ #
    # Step 4 — semantic_peer edges (best-effort; no errors if unavailable)
    # ------------------------------------------------------------------ #
    indexed_list = [pid for pid in all_ids if pid in indexed_ids]
    if len(indexed_list) >= 2:
        # Fetch embeddings lazily; cache per ID for this call
        embedding_cache: dict[str, Optional[list[float]]] = {}

        for i, pid_a in enumerate(indexed_list):
            for pid_b in indexed_list[i + 1 :]:
                # Avoid duplicate / reverse duplicate peer edges
                peer_key = (min(pid_a, pid_b), max(pid_a, pid_b), "semantic_peer")
                if peer_key in seen_edge_keys:
                    continue

                if pid_a not in embedding_cache:
                    embedding_cache[pid_a] = await _fetch_embedding_for_paper(pid_a)
                if pid_b not in embedding_cache:
                    embedding_cache[pid_b] = await _fetch_embedding_for_paper(pid_b)

                emb_a = embedding_cache[pid_a]
                emb_b = embedding_cache[pid_b]

                if emb_a is None or emb_b is None:
                    continue

                sim = _cosine(emb_a, emb_b)
                if sim >= _PEER_THRESHOLD:
                    seen_edge_keys.add(peer_key)
                    nodes_map[pid_a] = nodes_map[pid_a].model_copy(
                        update={"similarity_score": round(sim, 4)}
                    )
                    edges.append(
                        GraphEdge(
                            source=pid_a,
                            target=pid_b,
                            relation_type="semantic_peer",
                            weight=round(sim, 4),
                        )
                    )

    # ------------------------------------------------------------------ #
    # Step 5 — assemble response
    # ------------------------------------------------------------------ #
    final_nodes = list(nodes_map.values())
    return CitationGraphResponse(
        root_id=root_id,
        nodes=final_nodes,
        edges=edges,
        total_nodes=len(final_nodes),
        total_edges=len(edges),
    )
