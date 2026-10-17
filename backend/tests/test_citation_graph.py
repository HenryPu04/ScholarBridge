"""
Integration and unit tests for the citation graph endpoint and service.

Scenarios
---------
1. Standard paper with mixed citations and references — correct nodes & directional edges.
2. Paper with 0 citations and 0 references — returns root node only, empty edges, 200 OK.
3. Circular citations (A cites B, B cites A) — no duplicate or infinite-loop edges.
4. Non-existent paper ID — endpoint returns 404.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.models.graph import CitationGraphResponse


# ---------------------------------------------------------------------------
# Helpers to build fake Semantic Scholar _get responses
# ---------------------------------------------------------------------------

def _make_ss_paper_raw(
    paper_id: str,
    title: str = "Test Paper",
    year: int = 2023,
    citation_count: int = 5,
    citations: list[dict] | None = None,
    references: list[dict] | None = None,
) -> dict:
    """Raw dict as returned by the Semantic Scholar /paper/{id} API."""
    return {
        "paperId": paper_id,
        "title": title,
        "year": year,
        "citationCount": citation_count,
        "openAccessPdf": None,
        "citations": citations or [],
        "references": references or [],
    }


def _make_neighbor(paper_id: str, title: str = "Neighbor", year: int = 2022, citation_count: int = 3) -> dict:
    return {
        "paperId": paper_id,
        "title": title,
        "year": year,
        "citationCount": citation_count,
        "openAccessPdf": None,
    }


# ---------------------------------------------------------------------------
# Shared mock factories
# ---------------------------------------------------------------------------

def _make_mock_db_session(indexed_ids: list[str] | None = None) -> MagicMock:
    """
    Returns an async-capable SQLAlchemy session mock.
    `indexed_ids` is the list of paper_id values to simulate as locally indexed.
    """
    session = MagicMock()

    # Build fake row objects
    rows = []
    for pid in (indexed_ids or []):
        row = MagicMock()
        row.paper_id = pid
        row.ss_paper_id = None
        rows.append(row)

    result_mock = MagicMock()
    result_mock.all = MagicMock(return_value=rows)

    session.execute = AsyncMock(return_value=result_mock)
    return session


def _make_mock_ss_service(get_side_effect=None, get_return_value: dict | None = None) -> MagicMock:
    """
    Returns a mock SemanticScholarService.
    `get_side_effect` overrides `_get` with a callable (for per-call variation).
    `get_return_value` sets a static return value for all `_get` calls.
    """
    svc = MagicMock()
    if get_side_effect is not None:
        svc._get = AsyncMock(side_effect=get_side_effect)
    elif get_return_value is not None:
        svc._get = AsyncMock(return_value=get_return_value)
    else:
        svc._get = AsyncMock(return_value={})
    return svc


# ---------------------------------------------------------------------------
# Scenario 1 — Standard paper with mixed citations and references
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_standard_paper_mixed_citations_and_references():
    """
    Root paper has:
      - 2 citations (papers that cite it)
      - 2 references (papers it cites)
    Expected: 5 nodes total (root + 4 neighbours), 4 directional edges.
    """
    root_id = "ROOT_001"
    citer_a = "CITER_A"
    citer_b = "CITER_B"
    ref_c   = "REF_C"
    ref_d   = "REF_D"

    root_raw = _make_ss_paper_raw(
        paper_id=root_id,
        title="Root Paper",
        citation_count=10,
        citations=[
            _make_neighbor(citer_a, "Citer Alpha"),
            _make_neighbor(citer_b, "Citer Beta"),
        ],
        references=[
            _make_neighbor(ref_c, "Reference Gamma"),
            _make_neighbor(ref_d, "Reference Delta"),
        ],
    )

    # Map calls to root detail (used by get_paper_details) and BFS expansion
    async def _get_dispatch(path: str, params: dict) -> dict:
        # Any call to /paper/{id} with citation/reference fields returns root_raw for root
        pid = path.lstrip("/paper/").lstrip("paper/").split("/")[-1]
        if pid == root_id or path.endswith(root_id):
            return root_raw
        # Neighbor calls: return minimal graph with no further children
        return _make_ss_paper_raw(paper_id=pid, citations=[], references=[])

    from app.models.paper import PaperDetail
    root_detail = PaperDetail(
        paper_id=root_id, title="Root Paper", year=2023, citation_count=10
    )

    ss_svc = MagicMock()
    ss_svc.get_paper_details = AsyncMock(return_value=root_detail)
    ss_svc._get = AsyncMock(side_effect=_get_dispatch)

    db_session = _make_mock_db_session(indexed_ids=[root_id, citer_a])

    with patch("app.services.graph_service._fetch_embedding_for_paper", new=AsyncMock(return_value=None)):
        from app.services.graph_service import build_citation_graph
        result = await build_citation_graph(
            root_id=root_id,
            db=db_session,
            ss_service=ss_svc,
            depth=1,
            max_nodes=10,
        )

    assert isinstance(result, CitationGraphResponse)
    assert result.root_id == root_id

    node_ids = {n.id for n in result.nodes}
    assert root_id in node_ids
    assert citer_a in node_ids
    assert citer_b in node_ids
    assert ref_c in node_ids
    assert ref_d in node_ids
    assert result.total_nodes == 5

    # Verify directional edges:
    # citations  → citer_a cites root, citer_b cites root
    # references → root cites ref_c, root cites ref_d
    edge_tuples = {(e.source, e.target, e.relation_type) for e in result.edges}
    assert (citer_a, root_id, "cites") in edge_tuples
    assert (citer_b, root_id, "cites") in edge_tuples
    assert (root_id, ref_c, "cites") in edge_tuples
    assert (root_id, ref_d, "cites") in edge_tuples
    assert result.total_edges == 4

    # Indexed flags
    indexed_node_ids = {n.id for n in result.nodes if n.is_indexed}
    assert root_id in indexed_node_ids
    assert citer_a in indexed_node_ids
    assert citer_b not in indexed_node_ids


# ---------------------------------------------------------------------------
# Scenario 2 — Paper with 0 citations and 0 references
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_paper_with_zero_citations_and_references():
    """
    Root paper has no citations and no references.
    Expect: 1 node (root), 0 edges, 200 OK from the endpoint.
    """
    root_id = "ISOLATED_001"

    root_raw = _make_ss_paper_raw(root_id, citations=[], references=[])

    from app.models.paper import PaperDetail
    root_detail = PaperDetail(paper_id=root_id, title="Isolated Paper", year=2020, citation_count=0)

    ss_svc = MagicMock()
    ss_svc.get_paper_details = AsyncMock(return_value=root_detail)
    ss_svc._get = AsyncMock(return_value=root_raw)

    db_session = _make_mock_db_session(indexed_ids=[])

    with patch("app.services.graph_service._fetch_embedding_for_paper", new=AsyncMock(return_value=None)):
        from app.services.graph_service import build_citation_graph
        result = await build_citation_graph(
            root_id=root_id,
            db=db_session,
            ss_service=ss_svc,
            depth=1,
            max_nodes=10,
        )

    assert result.root_id == root_id
    assert result.total_nodes == 1
    assert result.total_edges == 0
    assert len(result.edges) == 0
    assert result.nodes[0].id == root_id

    # Also verify via the FastAPI endpoint
    from app.services.semantic_scholar import get_semantic_scholar_service
    from app.db.engine import get_db

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_semantic_scholar_service] = lambda: ss_svc

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch("app.services.graph_service._fetch_embedding_for_paper", new=AsyncMock(return_value=None)):
                response = await client.get(f"/api/v1/papers/{root_id}/graph")
        assert response.status_code == 200
        data = response.json()
        assert data["total_nodes"] == 1
        assert data["total_edges"] == 0
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Scenario 3 — Circular citations (A cites B, B cites A)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_circular_citations_no_duplicates():
    """
    Paper A cites Paper B, and Paper B cites Paper A.
    No duplicate edges or infinite loops should occur.
    """
    id_a = "CIRC_A"
    id_b = "CIRC_B"

    raw_a = _make_ss_paper_raw(
        paper_id=id_a,
        title="Paper A",
        references=[_make_neighbor(id_b, "Paper B")],  # A cites B
        citations=[_make_neighbor(id_b, "Paper B")],   # B also cites A
    )
    raw_b = _make_ss_paper_raw(
        paper_id=id_b,
        title="Paper B",
        references=[_make_neighbor(id_a, "Paper A")],  # B cites A (circular)
        citations=[_make_neighbor(id_a, "Paper A")],   # A also cites B (circular)
    )

    raw_map = {id_a: raw_a, id_b: raw_b}

    async def _get_dispatch(path: str, params: dict) -> dict:
        for pid, raw in raw_map.items():
            if path.endswith(pid):
                return raw
        return _make_ss_paper_raw(paper_id="UNKNOWN")

    from app.models.paper import PaperDetail
    root_detail = PaperDetail(paper_id=id_a, title="Paper A", year=2021, citation_count=1)

    ss_svc = MagicMock()
    ss_svc.get_paper_details = AsyncMock(return_value=root_detail)
    ss_svc._get = AsyncMock(side_effect=_get_dispatch)

    db_session = _make_mock_db_session(indexed_ids=[])

    with patch("app.services.graph_service._fetch_embedding_for_paper", new=AsyncMock(return_value=None)):
        from app.services.graph_service import build_citation_graph
        result = await build_citation_graph(
            root_id=id_a,
            db=db_session,
            ss_service=ss_svc,
            depth=2,
            max_nodes=25,
        )

    # Both nodes must be present
    node_ids = {n.id for n in result.nodes}
    assert id_a in node_ids
    assert id_b in node_ids

    # Check no duplicate edges
    edge_tuples = [(e.source, e.target, e.relation_type) for e in result.edges]
    assert len(edge_tuples) == len(set(edge_tuples)), "Duplicate edges detected"

    # Verify total_nodes / total_edges are consistent
    assert result.total_nodes == len(result.nodes)
    assert result.total_edges == len(result.edges)


# ---------------------------------------------------------------------------
# Scenario 4 — Non-existent paper ID → 404
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nonexistent_paper_returns_404():
    """
    Requesting a graph for a paper ID that does not exist in Semantic Scholar
    must return HTTP 404.
    """
    import httpx
    from app.services.semantic_scholar import SemanticScholarError

    bad_id = "DOES_NOT_EXIST_XYZ"

    ss_svc = MagicMock()
    ss_svc.get_paper_details = AsyncMock(
        side_effect=SemanticScholarError(f"Semantic Scholar returned 404 for /paper/{bad_id}")
    )

    from app.services.semantic_scholar import get_semantic_scholar_service
    from app.db.engine import get_db

    db_session = _make_mock_db_session(indexed_ids=[])

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_semantic_scholar_service] = lambda: ss_svc

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/papers/{bad_id}/graph")
        assert response.status_code == 404, (
            f"Expected 404 for unknown paper, got {response.status_code}: {response.text}"
        )
    finally:
        app.dependency_overrides.clear()
