from pydantic import BaseModel
from typing import Optional
from enum import Enum


class PipelineStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXED = "indexed"
    SUMMARIZING = "summarizing"
    COMPLETE = "complete"
    FAILED = "failed"
    ABSTRACT_ONLY = "abstract_only"  # fallback: no PDF, used abstract


class SummaryRequest(BaseModel):
    paper_id: str


class SummaryStatusResponse(BaseModel):
    paper_id: str
    status: PipelineStatus
    message: Optional[str] = None


class ExecutiveSummary(BaseModel):
    paper_id: str
    title: str
    problem_statement: str
    key_findings: list[str]          # 3-5 bullet points
    practical_implications: str
    methodology_note: str
    confidence_note: str
    jargon_glossary: dict[str, str]  # term -> plain-english definition
    reading_time_minutes: int
    source: str  # "full_paper" or "abstract_only"
