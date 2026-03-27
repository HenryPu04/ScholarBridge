import asyncio

from fastapi import APIRouter, HTTPException

from app import state
from app.models.summary import ExecutiveSummary, PipelineStatus, SummaryRequest, SummaryStatusResponse
from app.services.indexing_pipeline import run_pipeline

router = APIRouter(prefix="/summaries", tags=["summaries"])


@router.post("/request", response_model=SummaryStatusResponse)
async def request_summary(body: SummaryRequest):
    """Trigger JIT indexing for a paper. Idempotent — safe to call multiple times."""
    current = state.pipeline_status.get(body.paper_id)
    # Don't re-trigger if already in-flight or complete
    if current not in (None, PipelineStatus.FAILED):
        return SummaryStatusResponse(
            paper_id=body.paper_id,
            status=current,
            message=state.pipeline_messages.get(body.paper_id),
        )

    state.pipeline_status[body.paper_id] = PipelineStatus.PENDING
    asyncio.create_task(run_pipeline(body.paper_id))
    return SummaryStatusResponse(
        paper_id=body.paper_id,
        status=PipelineStatus.PENDING,
        message="Indexing started.",
    )


@router.get("/{paper_id}/status", response_model=SummaryStatusResponse)
async def get_summary_status(paper_id: str):
    """Poll the JIT pipeline status for a paper."""
    status = state.pipeline_status.get(paper_id, PipelineStatus.PENDING)
    return SummaryStatusResponse(
        paper_id=paper_id,
        status=status,
        message=state.pipeline_messages.get(paper_id),
    )


@router.get("/{paper_id}", response_model=ExecutiveSummary)
async def get_summary(paper_id: str):
    """Get the completed executive summary for a paper. Stub — implemented in Phase 2."""
    status = state.pipeline_status.get(paper_id)
    if status in (PipelineStatus.INDEXED, PipelineStatus.COMPLETE):
        raise HTTPException(
            status_code=404,
            detail="Paper is indexed but summary generation not yet implemented (Phase 2).",
        )
    if status == PipelineStatus.FAILED:
        raise HTTPException(
            status_code=500,
            detail=f"Pipeline failed: {state.pipeline_messages.get(paper_id, 'unknown error')}",
        )
    raise HTTPException(status_code=404, detail="Summary not yet generated.")
