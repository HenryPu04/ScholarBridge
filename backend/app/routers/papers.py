import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from app.models.paper import PaperDetail, PaperResult
from app.models.search import SearchResult
from app.services.search_service import SearchService, get_search_service
from app.services.semantic_scholar import (
    SemanticScholarError,
    SemanticScholarService,
    get_semantic_scholar_service,
)

router = APIRouter(prefix="/papers", tags=["papers"])


@router.get("/search", response_model=list[SearchResult])
async def search_papers(
    query: str = Query(..., min_length=3, description="Plain-English search query"),
    limit: int = Query(default=10, ge=1, le=25),
    year_min: Optional[int] = Query(default=None),
    year_max: Optional[int] = Query(default=None),
    fields_of_study: list[str] = Query(default=[]),
    open_access_only: bool = Query(default=False),
    service: SearchService = Depends(get_search_service),
) -> list[SearchResult]:
    """Semantic vector search with hybrid re-ranking. Falls back to Semantic Scholar keyword search."""
    try:
        return await service.search(
            query=query,
            limit=limit,
            year_min=year_min,
            year_max=year_max,
            fields_of_study=fields_of_study,
            open_access_only=open_access_only,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/{paper_id}", response_model=PaperDetail)
async def get_paper(
    paper_id: str,
    service: SemanticScholarService = Depends(get_semantic_scholar_service),
) -> PaperDetail:
    """Get full paper details by Semantic Scholar paper ID."""
    try:
        return await service.get_paper_details(paper_id)
    except SemanticScholarError as exc:
        status = 404 if "404" in str(exc) else 502
        raise HTTPException(status_code=status, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Paper not found")
        raise HTTPException(status_code=502, detail="Upstream API error")


@router.get("/{paper_id}/researchers", response_model=list)
async def get_paper_researchers(paper_id: str) -> list:
    """Get researchers associated with this paper."""
    return []
