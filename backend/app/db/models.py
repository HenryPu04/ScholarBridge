"""
SQLAlchemy ORM table definitions.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.engine import Base


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paper_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    # The Semantic Scholar internal ID (may differ from paper_id when the user
    # queried via an external ID such as "ARXIV:2301.12345").
    # Used as the fallback lookup key and for Pinecone filter queries.
    ss_paper_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[str] = mapped_column(Text, nullable=False)           # JSON array of names
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    fields_of_study: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    citation_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class Summary(Base):
    __tablename__ = "summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paper_id: Mapped[str] = mapped_column(
        Text, ForeignKey("papers.paper_id"), unique=True, nullable=False, index=True
    )
    problem_statement: Mapped[str] = mapped_column(Text, nullable=False)
    key_findings: Mapped[str] = mapped_column(Text, nullable=False)          # JSON array
    practical_implications: Mapped[str] = mapped_column(Text, nullable=False)
    methodology_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reading_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="full_paper")
    jargon_glossary: Mapped[str] = mapped_column(Text, nullable=False)       # JSON object
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
