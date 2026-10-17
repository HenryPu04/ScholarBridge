"""
Pydantic response models for the citation graph endpoint.
"""

from typing import Literal, Optional

from pydantic import BaseModel


class GraphNode(BaseModel):
    id: str
    title: str
    year: Optional[int] = None
    citation_count: int = 0
    similarity_score: Optional[float] = None
    is_indexed: bool
    open_access_pdf_url: Optional[str] = None


class GraphEdge(BaseModel):
    source: str
    target: str
    relation_type: Literal["cites", "cited_by", "semantic_peer"]
    weight: float = 1.0


class CitationGraphResponse(BaseModel):
    root_id: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    total_nodes: int
    total_edges: int
