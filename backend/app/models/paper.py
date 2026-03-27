from pydantic import BaseModel
from typing import Optional


class Author(BaseModel):
    author_id: Optional[str] = None
    name: str


class OpenAccessPdf(BaseModel):
    url: str
    status: str  # e.g. "GREEN", "BRONZE", "GOLD"


class PaperResult(BaseModel):
    """Lightweight model returned in search results."""
    paper_id: str
    title: str
    abstract: Optional[str] = None
    authors: list[Author] = []
    year: Optional[int] = None
    citation_count: Optional[int] = None
    fields_of_study: list[str] = []
    open_access_pdf: Optional[OpenAccessPdf] = None
    venue: Optional[str] = None
    external_ids: Optional[dict] = None


class PaperDetail(PaperResult):
    """Full paper detail including TLDR from Semantic Scholar."""
    tldr: Optional[str] = None
    reference_count: Optional[int] = None
    influential_citation_count: Optional[int] = None
