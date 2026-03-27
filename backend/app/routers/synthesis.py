from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db
from app.models.synthesis import SynthesisRequest, SynthesisResult
from app.services.synthesis_service import SynthesisService, get_synthesis_service

router = APIRouter(prefix="/synthesis", tags=["synthesis"])


@router.post("/", response_model=SynthesisResult)
async def create_synthesis(
    body: SynthesisRequest,
    db: AsyncSession = Depends(get_db),
    service: SynthesisService = Depends(get_synthesis_service),
) -> SynthesisResult:
    """
    Generate a cross-paper meta-analysis for 2–5 summarised papers.

    Returns a cached result if one exists for the same set of paper_ids
    and was generated within the last hour.
    """
    try:
        return await service.synthesize(paper_ids=body.paper_ids, db=db)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
