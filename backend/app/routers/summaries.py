import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import state
from app.db.engine import get_db
from app.db.models import Paper, Summary
from app.models.summary import ExecutiveSummary, PipelineStatus, SummaryRequest, SummaryStatusResponse
from app.services.indexing_pipeline import run_pipeline

router = APIRouter(prefix="/summaries", tags=["summaries"])


@router.get("/", response_model=list[ExecutiveSummary])
async def list_summaries(db: AsyncSession = Depends(get_db)) -> list[ExecutiveSummary]:
    """
    The Library — returns all papers that have been summarised, newest first.
    """
    result = await db.execute(
        select(Summary, Paper)
        .join(Paper, Paper.paper_id == Summary.paper_id)
        .order_by(Summary.created_at.desc())
    )
    rows = result.all()

    return [
        ExecutiveSummary(
            paper_id=summary_row.paper_id,
            title=paper_row.title,
            problem_statement=summary_row.problem_statement,
            key_findings=json.loads(summary_row.key_findings),
            practical_implications=summary_row.practical_implications,
            methodology_note=summary_row.methodology_note or "",
            confidence_note=summary_row.confidence_note or "",
            reading_time_minutes=summary_row.reading_time_minutes or 1,
            source=summary_row.source,
            jargon_glossary=json.loads(summary_row.jargon_glossary),
        )
        for summary_row, paper_row in rows
    ]


@router.post("/request", response_model=SummaryStatusResponse)
async def request_summary(body: SummaryRequest) -> SummaryStatusResponse:
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
async def get_summary_status(paper_id: str) -> SummaryStatusResponse:
    """Poll the JIT pipeline status for a paper."""
    status = state.pipeline_status.get(paper_id, PipelineStatus.PENDING)
    return SummaryStatusResponse(
        paper_id=paper_id,
        status=status,
        message=state.pipeline_messages.get(paper_id),
    )


@router.get("/{paper_id}", response_model=ExecutiveSummary)
async def get_summary(
    paper_id: str,
    db: AsyncSession = Depends(get_db),
) -> ExecutiveSummary:
    """Get the completed executive summary for a paper."""
    status = state.pipeline_status.get(paper_id)

    if status == PipelineStatus.FAILED:
        raise HTTPException(
            status_code=500,
            detail=f"Pipeline failed: {state.pipeline_messages.get(paper_id, 'unknown error')}",
        )

    # Primary lookup: match the exact ID the user supplied.
    # Fallback: match via the SS internal ID stored in papers.ss_paper_id —
    # handles the case where the paper was indexed under an ArXiv ID but the
    # user is now querying with the Semantic Scholar internal ID, or vice-versa.
    result = await db.execute(
        select(Summary, Paper)
        .join(Paper, Paper.paper_id == Summary.paper_id)
        .where(
            or_(
                Summary.paper_id == paper_id,
                Paper.ss_paper_id == paper_id,
            )
        )
    )
    row = result.one_or_none()

    if row is None:
        if status in (
            PipelineStatus.DOWNLOADING,
            PipelineStatus.EXTRACTING,
            PipelineStatus.CHUNKING,
            PipelineStatus.EMBEDDING,
            PipelineStatus.INDEXED,
            PipelineStatus.SUMMARIZING,
        ):
            raise HTTPException(
                status_code=202,
                detail=f"Summary in progress — current status: {status.value}",
            )
        raise HTTPException(
            status_code=404,
            detail="No summary found. Use POST /summaries/request to trigger indexing.",
        )

    summary_row, paper_row = row
    return ExecutiveSummary(
        paper_id=summary_row.paper_id,
        title=paper_row.title,
        problem_statement=summary_row.problem_statement,
        key_findings=json.loads(summary_row.key_findings),
        practical_implications=summary_row.practical_implications,
        methodology_note=summary_row.methodology_note or "",
        confidence_note=summary_row.confidence_note or "",
        reading_time_minutes=summary_row.reading_time_minutes or 1,
        source=summary_row.source,
        jargon_glossary=json.loads(summary_row.jargon_glossary),
    )
