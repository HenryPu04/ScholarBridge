from pydantic import BaseModel
from typing import Optional


class ResearcherMatch(BaseModel):
    researcher_id: Optional[str] = None
    semantic_scholar_author_id: str
    name: str
    affiliation: Optional[str] = None
    homepage: Optional[str] = None
    paper_count: Optional[int] = None
    citation_count: Optional[int] = None
    on_platform: bool = False  # True if they've claimed their profile
